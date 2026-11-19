import assert from "node:assert/strict";
import { test } from "node:test";

import { IfseenApiError, IfseenClient, IfseenConnectionError } from "../src/index.js";
import { fixtureBytes, json, mockFetch } from "./helpers.js";

const state = { id: "front-door", created: 1, running: true, paused: false, stop_reason: null, error: null, source: "s", provider: "p", every: 2, rules: [], stats: null };

test("endpoint shapes: methods, paths, JSON content type on every POST, bearer token", async () => {
  const fetch = mockFetch((req) => {
    if (req.url.endsWith("/v1/health")) return json({ ok: true, version: "0.1.0", api: "v1", providers: ["mock"], default_provider: "mock", auth: true, allow_shell: false, dry_run: true });
    if (req.url.endsWith("/v1/watchers") && req.method === "GET") return json({ watchers: [state] });
    if (req.url.endsWith("/v1/watchers")) return json(state, 201);
    if (req.method === "DELETE") return json({ id: "front-door", deleted: true });
    if (req.url.endsWith("/snapshot")) return new Response(new Uint8Array([0xff, 0xd8, 0xff, 1]), { headers: { "Content-Type": "image/jpeg" } });
    return json(state);
  });
  const client = new IfseenClient({ baseUrl: "http://pi.local:8899/", token: "abcdefghijklmnop", fetch });
  assert.equal((await client.health()).dry_run, true);
  assert.deepEqual(await client.listWatchers(), [state]);
  await client.createWatcher({ id: "front-door", source: { file: { path: "/x.jpg", loop: true } }, rules: [{ name: "person", when: "A person.", for: 2, cooldown: "1m" }] });
  await client.getWatcher("front-door");
  await client.startWatcher("front-door");
  await client.stopWatcher("front-door");
  assert.deepEqual(await client.snapshot("front-door"), new Uint8Array([0xff, 0xd8, 0xff, 1]));
  assert.deepEqual(await client.deleteWatcher("front-door"), { id: "front-door", deleted: true });

  assert.deepEqual(
    fetch.calls.map((c) => `${c.method} ${c.url.replace("http://pi.local:8899", "")}`),
    [
      "GET /v1/health",
      "GET /v1/watchers",
      "POST /v1/watchers",
      "GET /v1/watchers/front-door",
      "POST /v1/watchers/front-door/start",
      "POST /v1/watchers/front-door/stop",
      "GET /v1/watchers/front-door/snapshot",
      "DELETE /v1/watchers/front-door",
    ],
  );
  for (const c of fetch.calls) {
    assert.equal(c.headers.authorization, "Bearer abcdefghijklmnop");
    if (c.method === "POST") {
      assert.equal(c.headers["content-type"], "application/json");
      assert.ok(c.body !== undefined);
    } else {
      assert.equal(c.body, undefined);
    }
  }
  assert.deepEqual(JSON.parse(fetch.calls[2]!.body!), {
    id: "front-door",
    source: { file: { path: "/x.jpg", loop: true } },
    rules: [{ name: "person", when: "A person.", for: 2, cooldown: "1m" }],
  });
});

test("check(): wire body and camelCased result", async () => {
  const fetch = mockFetch(() =>
    json({ probs: { parcel: 0.9612, "a-person-is-visible": 0.031 }, tokens: 1350, latency_ms: 412.7, cost_usd: 0.000135, provider: "gemini (gemini-decision-1)" }),
  );
  const client = new IfseenClient({ fetch });
  const jpg = fixtureBytes("red.jpg");
  const wav = fixtureBytes("tone.wav");
  const res = await client.check(jpg, { parcel: { when: "A parcel.", falseMeans: "Empty." }, "a-person-is-visible": "A person is visible." }, {
    audio: wav,
    provider: { name: "gemini", resolution: "low" },
    model: "gemini-decision-1",
    context: "Doorbell.",
  });
  assert.deepEqual(res, { probs: { parcel: 0.9612, "a-person-is-visible": 0.031 }, tokens: 1350, latencyMs: 412.7, costUsd: 0.000135, provider: "gemini (gemini-decision-1)" });
  const req = fetch.calls[0]!;
  assert.equal(req.url, "http://127.0.0.1:8899/v1/check");
  assert.equal(req.headers.authorization, undefined);
  assert.deepEqual(JSON.parse(req.body!), {
    rules: { parcel: { when: "A parcel.", false_means: "Empty." }, "a-person-is-visible": "A person is visible." },
    image_base64: Buffer.from(jpg).toString("base64"),
    audio_base64: Buffer.from(wav).toString("base64"),
    provider: { name: "gemini", resolution: "low" },
    model: "gemini-decision-1",
    context: "Doorbell.",
  });
});

test("API errors map to IfseenApiError with the server's code", async () => {
  const fetch = mockFetch((_r, i) =>
    i === 0
      ? json({ error: { code: "invalid_config", message: "invalid config:\n  rules.0.threshold: ..." } }, 400)
      : new Response("<html>Bad gateway</html>", { status: 502, statusText: "Bad Gateway" }),
  );
  const client = new IfseenClient({ fetch });
  await assert.rejects(client.createWatcher({ source: "screen", rules: [{ name: "x", when: "x", threshold: 2 }] }), (e: unknown) => {
    assert.ok(e instanceof IfseenApiError);
    assert.equal(e.status, 400);
    assert.equal(e.code, "invalid_config");
    assert.match(e.message, /rules\.0\.threshold/);
    return true;
  });
  await assert.rejects(client.health(), (e: unknown) => e instanceof IfseenApiError && e.code === "http_502" && e.status === 502);
});

test("bad ids are rejected locally; unreachable server is an IfseenConnectionError", async () => {
  const fetch = mockFetch(() => {
    throw new TypeError("fetch failed");
  });
  const client = new IfseenClient({ fetch });
  await assert.rejects(client.getWatcher("../health"), (e: unknown) => e instanceof IfseenApiError && e.code === "invalid_id");
  await assert.rejects(client.createWatcher({ id: "a b", source: "screen", rules: [] }), /invalid|letters/);
  assert.equal(fetch.calls.length, 0);
  await assert.rejects(client.health(), IfseenConnectionError);
});
