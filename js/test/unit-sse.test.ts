import assert from "node:assert/strict";
import { test } from "node:test";

import { IfseenApiError, IfseenClient, type IfseenEvent, SseParser, type SseMessage } from "../src/index.js";
import { json, mockFetch, streamResponse } from "./helpers.js";

function parse(chunks: string[]) {
  const messages: SseMessage[] = [];
  const comments: string[] = [];
  const retries: number[] = [];
  const p = new SseParser({
    onMessage: (m) => messages.push(m),
    onComment: (c) => comments.push(c),
    onRetry: (ms) => retries.push(ms),
  });
  for (const c of chunks) p.feed(c);
  return { messages, comments, retries };
}

/** Feed `text` split at every possible position (two chunks) and one char at a time. */
function everySplit(text: string, check: (r: ReturnType<typeof parse>) => void) {
  for (let i = 0; i <= text.length; i++) check(parse([text.slice(0, i), text.slice(i)]));
  check(parse([...text]));
}

test("parses the server's stream: retry, comments, id/event/data", () => {
  const stream =
    "retry: 3000\n: connected\n\n" +
    'id: 17\nevent: decision\ndata: {"event": "decision"}\n\n' +
    ": keep-alive\n\n" +
    'id: 18\nevent: fire\ndata: {"event": "fire"}\n\n';
  everySplit(stream, ({ messages, comments, retries }) => {
    assert.deepEqual(retries, [3000]);
    assert.deepEqual(comments, ["connected", "keep-alive"]);
    assert.deepEqual(messages, [
      { event: "decision", data: '{"event": "decision"}', id: "17" },
      { event: "fire", data: '{"event": "fire"}', id: "18" },
    ]);
  });
});

test("multi-line data, CRLF / CR line endings split across chunks, no-space values", () => {
  const stream = "data: line one\r\ndata:line two\r\ndata\r\n\r\nevent:x\rdata: a\r\r";
  everySplit(stream, ({ messages }) => {
    assert.deepEqual(messages, [
      { event: "message", data: "line one\nline two\n", id: undefined },
      { event: "x", data: "a", id: undefined },
    ]);
  });
});

test("edge cases: BOM, empty data block, unknown fields, bad retry, id persistence, unterminated tail", () => {
  const { messages, retries } = parse([
    "﻿id: 1\nevent: ignored\n\n", // no data: not dispatched, event type reset
    "foo: bar\nretry: soon\ndata: x\n\n",
    "data:  two spaces\n\n",
    "id\ndata: y\n\n",
    "data: never finished",
  ]);
  assert.deepEqual(retries, []);
  assert.deepEqual(messages, [
    { event: "message", data: "x", id: "1" },
    { event: "message", data: " two spaces", id: "1" },
    { event: "message", data: "y", id: "" },
  ]);
});

// -- client.events() over a mocked fetch -----------------------------------------------------

const frame = (id: number, event: Record<string, unknown>) =>
  `id: ${id}\nevent: ${String(event.event)}\ndata: ${JSON.stringify(event)}\n\n`;

async function collect(it: AsyncIterable<IfseenEvent>, n: number): Promise<IfseenEvent[]> {
  const out: IfseenEvent[] = [];
  for await (const e of it) {
    out.push(e);
    if (out.length >= n) break;
  }
  return out;
}

test("events(): UTF-8 split across chunks, keep-alives, typed events with seq", async () => {
  const fire = { event: "fire", watcher: "w", time: 1.5, rule: "café", when: "Ünïcode ☕ is visible.", probability: 0.9 };
  const bytes = new TextEncoder().encode("retry: 10\n: connected\n\n: keep-alive\n\n" + frame(7, fire));
  // split inside the multi-byte characters: one byte per chunk
  const chunks = Array.from(bytes, (b) => new Uint8Array([b]));
  const fetch = mockFetch(() => streamResponse(chunks, { keepOpen: true }));
  const client = new IfseenClient({ baseUrl: "http://h:1/", token: "t".repeat(16), fetch });
  const [e] = await collect(client.events({ watcher: "w", types: ["fire", "stop"] }), 1);
  assert.deepEqual(e, { ...fire, seq: 7 });
  const req = fetch.calls[0]!;
  assert.equal(req.url, "http://h:1/v1/events?watcher=w&types=fire%2Cstop");
  assert.equal(req.headers.authorization, `Bearer ${"t".repeat(16)}`);
  assert.equal(req.headers.accept, "text/event-stream");
});

test("events(): unknown kinds pass through as generic events; junk data is skipped", async () => {
  const fetch = mockFetch(() =>
    streamResponse([
      "data: not json\n\n",
      "data: [1,2]\n\n",
      frame(1, { event: "teleport", watcher: "w", time: 2, where: "mars" }),
      frame(2, { event: "clear", watcher: "w", time: 3, rule: "r", probability: 0.1 }),
    ]),
  );
  const client = new IfseenClient({ fetch });
  const events = await collect(client.events({ reconnect: false }), 5);
  assert.deepEqual(events, [
    { event: "unknown", kind: "teleport", watcher: "w", time: 2, seq: 1, payload: { event: "teleport", watcher: "w", time: 2, where: "mars" } },
    { event: "clear", watcher: "w", time: 3, rule: "r", probability: 0.1, seq: 2 },
  ]);
});

test("events(): reconnects after the server ends the stream and after 503, honouring retry:", async () => {
  const opens: boolean[] = [];
  const disconnects: number[] = [];
  const fetch = mockFetch((_req, i) => {
    if (i === 0) return streamResponse(["retry: 5\n\n", frame(1, { event: "start", watcher: "a", time: 1, source: "s", provider: "p", rules: [] })]);
    if (i === 1) return json({ error: { code: "internal_error", message: "x" } }, 503);
    if (i === 2) throw new TypeError("connection refused");
    return streamResponse([frame(9, { event: "stop", watcher: "a", time: 2, reason: "stopped" })], { keepOpen: true });
  });
  const client = new IfseenClient({ fetch });
  const events = await collect(
    client.events({
      onOpen: ({ reconnect }) => opens.push(reconnect),
      onDisconnect: ({ retryInMs }) => disconnects.push(retryInMs),
    }),
    2,
  );
  assert.deepEqual(events.map((e) => e.event), ["start", "stop"]);
  assert.equal(fetch.calls.length, 4);
  assert.deepEqual(opens, [false, true]);
  assert.equal(disconnects.length, 3);
  // clean end waits ~retry (5 ms ±20 %), failures back off exponentially from there
  assert.ok(disconnects[0]! <= 6 && disconnects[1]! <= 6 && disconnects[2]! >= 8 && disconnects[2]! <= 12, String(disconnects));
});

test("events(): 401 and 404 throw IfseenApiError instead of retrying", async () => {
  for (const [status, code] of [
    [401, "unauthorized"],
    [404, "not_found"],
  ] as const) {
    const fetch = mockFetch(() => json({ error: { code, message: "nope" } }, status));
    const client = new IfseenClient({ fetch });
    await assert.rejects(collect(client.events(), 1), (e: unknown) => {
      assert.ok(e instanceof IfseenApiError);
      assert.equal(e.code, code);
      assert.equal(e.status, status);
      return true;
    });
    assert.equal(fetch.calls.length, 1);
  }
});

test("events(): aborting the signal ends iteration without an error; idle streams reconnect", async () => {
  const controller = new AbortController();
  let n = 0;
  const fetch = mockFetch(() => {
    n++;
    return streamResponse([": connected\n\n"], { keepOpen: true });
  });
  const client = new IfseenClient({ fetch });
  setTimeout(() => controller.abort(), 120);
  const seen: IfseenEvent[] = [];
  for await (const e of client.events({ signal: controller.signal, idleTimeoutMs: 30, maxRetryDelayMs: 5 })) seen.push(e);
  assert.equal(seen.length, 0);
  assert.ok(n >= 2, `expected an idle reconnect, got ${n} connections`);
});

test("on(): typed handler, filtering, unsubscribe and handler errors", async () => {
  const fetch = mockFetch(() =>
    streamResponse(
      [
        frame(1, { event: "decision", watcher: "w", time: 1, probs: { a: 0.2 }, latency_ms: 1, tokens: 2 }),
        frame(2, { event: "fire", watcher: "w", time: 2, rule: "a", when: "A.", probability: 0.95 }),
        frame(3, { event: "fire", watcher: "w", time: 3, rule: "b", when: "B.", probability: 0.85 }),
      ],
      { keepOpen: true },
    ),
  );
  const client = new IfseenClient({ fetch });
  const rules: string[] = [];
  const errors: unknown[] = [];
  const done = new Promise<void>((resolve) => {
    const off = client.on(
      "fire",
      (e) => {
        rules.push(`${e.rule}@${e.probability}`);
        if (rules.length === 1) throw new Error("handler blew up");
        off();
        resolve();
      },
      { watcher: "w", onError: (e) => errors.push(e) },
    );
  });
  await done;
  assert.deepEqual(rules, ["a@0.95", "b@0.85"]);
  assert.equal(errors.length, 1);
  assert.equal(fetch.calls[0]!.url, "http://127.0.0.1:8899/v1/events?watcher=w&types=fire");
});

test("on(): fatal stream errors go to onError", async () => {
  const fetch = mockFetch(() => json({ error: { code: "unauthorized", message: "bad token" } }, 401));
  const client = new IfseenClient({ fetch });
  const err = await new Promise<unknown>((resolve) => client.on("*", () => {}, { onError: resolve }));
  assert.ok(err instanceof IfseenApiError && err.code === "unauthorized");
});
