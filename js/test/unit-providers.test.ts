import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { AuthError, BillingError, check, checkDetailed, ConfigError, ProviderError } from "../src/index.js";
import { fixtureBytes, json, mockFetch } from "./helpers.js";

const KEY = "sk-secret-key-123456";
const jpg = fixtureBytes("red.jpg");
const png = fixtureBytes("blue.png");
const wav = fixtureBytes("tone.wav");

const geminiOk = (probs: Record<string, number>, tokens = 1350) =>
  json({
    answers: Object.fromEntries(Object.entries(probs).map(([k, p]) => [k, { type: "noul", noul: p }])),
    usage: { total_input_tokens: tokens },
  });

afterEach(() => {
  delete process.env.GEMINI_API_KEY;
  delete process.env.GOOGLE_API_KEY;
  delete process.env.TYPESAFE_API_KEY;
  delete process.env.AZURE_DECISION_ENDPOINT;
  delete process.env.AZURE_DECISION_KEY;
  delete process.env.AZURE_DECISION_DEPLOYMENT;
});

test("gemini request shape", async () => {
  const fetch = mockFetch(() => geminiOk({ parcel: 0.9612, "a-person-is-visible": 0.031 }));
  const res = await checkDetailed(
    jpg,
    { parcel: { when: "A parcel is on the doorstep.", falseMeans: "An empty step." }, "a-person-is-visible": "A person is visible." },
    { apiKey: KEY, fetch, context: "Doorbell camera.", resolution: "low", audio: wav, label: "door" },
  );
  assert.equal(fetch.calls.length, 1);
  const req = fetch.calls[0]!;
  assert.equal(req.url, "https://generativelanguage.googleapis.com/v1beta/decisions");
  assert.equal(req.method, "POST");
  assert.equal(req.headers["x-goog-api-key"], KEY);
  assert.equal(req.headers["content-type"], "application/json");
  const body = JSON.parse(req.body!);
  assert.equal(body.model, "gemini-decision-1");
  assert.equal(body.input.length, 3);
  assert.equal(body.input[0].type, "text");
  assert.match(body.input[0].text, /^Live capture \(a still frame and an audio clip\) from door at \d\d:\d\d:\d\d\.\nContext: Doorbell camera\.\n$/);
  assert.deepEqual(body.input[1], {
    type: "image",
    data: Buffer.from(jpg).toString("base64"),
    mime_type: "image/jpeg",
    resolution: "low",
  });
  assert.deepEqual(body.input[2], { type: "audio", data: Buffer.from(wav).toString("base64"), mime_type: "audio/wav" });
  assert.deepEqual(body.questions, {
    parcel: { type: "noul", instructions: "A parcel is on the doorstep.", criteria: { false_description: "An empty step." } },
    "a-person-is-visible": { type: "noul", instructions: "A person is visible." },
  });
  assert.deepEqual(res.probs, { parcel: 0.9612, "a-person-is-visible": 0.031 });
  assert.deepEqual(Object.keys(res.probs), ["parcel", "a-person-is-visible"]);
  assert.equal(res.tokens, 1350);
  assert.equal(res.model, "gemini-decision-1");
  assert.equal(res.provider, "gemini (gemini-decision-1)");
  assert.ok(Math.abs(res.costUsd - 0.000135) < 1e-12);
  assert.ok(res.latencyMs >= 0);
});

test("gemini: PNG mime, env key, list statements, missing answers default to 0 and clamp", async () => {
  process.env.GOOGLE_API_KEY = "env-key-abcdef";
  const fetch = mockFetch(() => json({ answers: { "it-is-blue": { noul: 1.7 } }, usage: {} }));
  const probs = await check(png, ["It is blue.", "It is red."], { fetch, baseUrl: "http://proxy.local/x" });
  const req = fetch.calls[0]!;
  assert.equal(req.url, "http://proxy.local/x");
  assert.equal(req.headers["x-goog-api-key"], "env-key-abcdef");
  assert.equal(JSON.parse(req.body!).input[1].mime_type, "image/png");
  assert.deepEqual(probs, { "it-is-blue": 1, "it-is-red": 0 });
});

test("jev request shape: bearer, danger-zone header, asset referenced in state", async () => {
  const fetch = mockFetch(() =>
    json({ model: "jev-1.13", answers: { door: { noul: 0.5 } }, usage: { input_tokens: 300 } }),
  );
  const res = await checkDetailed(jpg, { door: { when: "Door open.", trueMeans: "Open.", falseMeans: "Shut." } }, {
    provider: "jev",
    apiKey: KEY,
    fetch,
  });
  const req = fetch.calls[0]!;
  assert.equal(req.url, "https://api.typesafe.ai/v1/systemone");
  assert.equal(req.headers.authorization, `Bearer ${KEY}`);
  assert.equal(req.headers["typesafe-danger-zone-images"], "true");
  const body = JSON.parse(req.body!);
  assert.equal(body.model, "jev-latest");
  const keys = Object.keys(body.assets);
  assert.equal(keys.length, 1);
  assert.match(keys[0]!, /^frame-[0-9a-f]{12}\.jpg$/);
  assert.ok(body.state.endsWith(`\nFrame: image:${keys[0]}`));
  assert.match(body.state, /^Live capture \(a still frame\) from image at /);
  assert.deepEqual(body.assets[keys[0]!], { type: "image", format: "jpg", data_base64: Buffer.from(jpg).toString("base64") });
  assert.deepEqual(body.questions, { door: { type: "noul", instructions: "Door open.", criteria: { true: "Open.", false: "Shut." } } });
  assert.equal(res.tokens, 300);
  assert.equal(res.model, "jev-1.13");
  assert.equal(res.provider, "jev (jev-1.13)");
});

test("azure request shape: endpoint path, api-key header, png format, no jev header", async () => {
  process.env.AZURE_DECISION_DEPLOYMENT = "my-deploy";
  const fetch = mockFetch(() => json({ answers: { a: { noul: 0.2 } }, usage: { input_tokens: 10 } }));
  await check(png, { a: "A." }, { provider: "azure", apiKey: KEY, baseUrl: "https://res.services.ai.azure.com/", fetch });
  const req = fetch.calls[0]!;
  assert.equal(req.url, "https://res.services.ai.azure.com/providers/microsoft/v1/systemone");
  assert.equal(req.headers["api-key"], KEY);
  assert.equal(req.headers["typesafe-danger-zone-images"], undefined);
  assert.equal(req.headers.authorization, undefined);
  const body = JSON.parse(req.body!);
  assert.equal(body.model, "my-deploy");
  const [key] = Object.keys(body.assets);
  assert.match(key!, /\.png$/);
  assert.equal(body.assets[key!].format, "png");

  // a full .../systemone URL is used as-is; endpoint can come from the env
  process.env.AZURE_DECISION_ENDPOINT = "https://other/custom/systemone";
  process.env.AZURE_DECISION_KEY = "azure-env-key";
  await check(png, ["x"], { provider: "azure", fetch });
  assert.equal(fetch.calls[1]!.url, "https://other/custom/systemone");
  assert.equal(fetch.calls[1]!.headers["api-key"], "azure-env-key");
});

test("systemone (self-hosted): base URL path, optional key", async () => {
  const fetch = mockFetch(() => json({ answers: {}, usage: {} }));
  await check(jpg, ["x"], { provider: "systemone", baseUrl: "http://localhost:8080", fetch });
  assert.equal(fetch.calls[0]!.url, "http://localhost:8080/v1/systemone");
  assert.equal(fetch.calls[0]!.headers.authorization, undefined);
  await assert.rejects(check(jpg, ["x"], { provider: "systemone", fetch }), /needs baseUrl/);
});

test("config errors before any request", async () => {
  const fetch = mockFetch(() => json({}));
  await assert.rejects(check(jpg, ["x"], { fetch }), /needs an API key/);
  await assert.rejects(check(jpg, ["x"], { provider: "azure", apiKey: KEY, fetch }), /needs baseUrl/);
  await assert.rejects(check(null, ["x"], { apiKey: KEY, fetch }), /image and\/or audio/);
  await assert.rejects(check(jpg, ["x"], { provider: "jev", apiKey: KEY, audio: wav, fetch }), /can't hear audio/);
  await assert.rejects(
    check(fixtureBytes("small-green.jpg"), ["x"], { provider: "jev", apiKey: KEY, fetch }),
    (e: unknown) => e instanceof ConfigError && /280 and 1568 px.*100x80/.test(e.message),
  );
  await assert.rejects(check(jpg, ["x"], { provider: "nope" as never, apiKey: KEY, fetch }), /unknown provider/);
  assert.equal(fetch.calls.length, 0);
});

test("audio-only gemini check", async () => {
  const fetch = mockFetch(() => geminiOk({ crying: 0.7 }, 400));
  const probs = await check(null, { crying: "A baby is crying." }, { apiKey: KEY, audio: wav, fetch });
  const body = JSON.parse(fetch.calls[0]!.body!);
  assert.deepEqual(body.input.map((b: { type: string }) => b.type), ["text", "audio"]);
  assert.match(body.input[0].text, /\(an audio clip\) from audio at/);
  assert.deepEqual(probs, { crying: 0.7 });
});

// -- error mapping ---------------------------------------------------------------------------

const opts = { apiKey: KEY, retryDelayMs: 1 };

test("401 / 403 / 400 API_KEY_INVALID -> AuthError, no retry, no key in message", async () => {
  for (const [status, body] of [
    [401, { detail: `bad key ${KEY}` }],
    [403, { error: { message: `API key not valid: ${KEY}` } }],
    [400, { error: { code: 400, message: "API key not valid.", status: "INVALID_ARGUMENT", details: [{ reason: "API_KEY_INVALID" }] } }],
  ] as const) {
    const fetch = mockFetch(() => json(body, status));
    await assert.rejects(check(jpg, ["x"], { ...opts, fetch }), (e: unknown) => {
      assert.ok(e instanceof AuthError, `status ${status}`);
      assert.equal(e.status, status);
      assert.equal(e.provider, "gemini");
      assert.ok(!e.message.includes(KEY));
      return true;
    });
    assert.equal(fetch.calls.length, 1);
  }
});

test("402 -> BillingError, key redacted from provider text", async () => {
  const fetch = mockFetch(() => json({ error: { message: `no credits left for ${KEY}` } }, 402));
  await assert.rejects(check(jpg, ["x"], { ...opts, fetch }), (e: unknown) => {
    assert.ok(e instanceof BillingError);
    assert.match(e.message, /billing problem \(HTTP 402\): no credits left for \*\*\*/);
    assert.ok(!e.message.includes(KEY));
    return true;
  });
  assert.equal(fetch.calls.length, 1);
});

test("429 / 5xx / network errors are retried, then succeed", async () => {
  const fetch = mockFetch((_req, i) => {
    if (i === 0) return json({ error: { message: "slow down" } }, 429);
    if (i === 1) throw new TypeError("fetch failed");
    return geminiOk({ x: 0.4 });
  });
  const probs = await check(jpg, ["x"], { ...opts, fetch });
  assert.deepEqual(probs, { x: 0.4 });
  assert.equal(fetch.calls.length, 3);
});

test("retries give up after maxAttempts with a ProviderError", async () => {
  const fetch = mockFetch(() => new Response("upstream down", { status: 503 }));
  await assert.rejects(check(jpg, ["x"], { ...opts, fetch, maxAttempts: 2 }), (e: unknown) => {
    assert.ok(e instanceof ProviderError && !(e instanceof AuthError));
    assert.equal(e.status, 503);
    assert.match(e.message, /gemini: HTTP 503: upstream down/);
    return true;
  });
  assert.equal(fetch.calls.length, 2);
});

test("other 4xx are not retried; bad JSON and missing answers are ProviderErrors", async () => {
  let fetch = mockFetch(() => json({ error: { message: "bad request" } }, 400));
  await assert.rejects(check(jpg, ["x"], { ...opts, fetch }), /HTTP 400: bad request/);
  assert.equal(fetch.calls.length, 1);
  fetch = mockFetch(() => new Response("<html>", { status: 200 }));
  await assert.rejects(check(jpg, ["x"], { ...opts, fetch }), /response was not JSON/);
  fetch = mockFetch(() => json({ nope: 1 }));
  await assert.rejects(check(jpg, ["x"], { ...opts, fetch }), /response had no answers/);
});

test("timeouts are retried and reported; aborts propagate untouched", async () => {
  const hang = mockFetch(
    (req) =>
      new Promise<Response>((_resolve, reject) => {
        void req;
        setTimeout(() => reject(new DOMException("aborted", "AbortError")), 50);
      }),
  );
  await assert.rejects(check(jpg, ["x"], { ...opts, fetch: hang, timeoutMs: 5, maxAttempts: 2 }), ProviderError);

  const controller = new AbortController();
  const slow = mockFetch(() => new Promise<Response>(() => {}));
  const slowFetch = (input: string, init?: RequestInit) => {
    void slow(input, init);
    return new Promise<Response>((_r, reject) => init?.signal?.addEventListener("abort", () => reject(init.signal!.reason)));
  };
  const p = check(jpg, ["x"], { ...opts, fetch: slowFetch, signal: controller.signal });
  controller.abort();
  await assert.rejects(p, (e: unknown) => (e as Error).name === "AbortError");
});
