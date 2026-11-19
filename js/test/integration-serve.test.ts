/**
 * Runs the client against a real `ifseen serve --dry-run` (mock provider, no network calls).
 * Skipped when the Python package isn't installed (set IFSEEN_BIN to point at the CLI).
 */
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { detectImageMime, IfseenApiError, IfseenClient, type IfseenEvent } from "../src/index.js";
import { fixture, fixtureBytes, freePort, haveIfseen, IFSEEN_BIN, type Spawned, spawnProcess, waitFor } from "./helpers.js";

const skip = haveIfseen ? false : `ifseen CLI not found at ${IFSEEN_BIN}`;

async function startServe(port: number, extra: string[] = []): Promise<Spawned> {
  const proc = spawnProcess(IFSEEN_BIN, ["serve", "--dry-run", "--port", String(port), ...extra]);
  const probe = new IfseenClient({ baseUrl: `http://127.0.0.1:${port}` });
  await waitFor(
    async () => {
      try {
        return (await probe.health()).ok;
      } catch (e) {
        // a token-protected server answering 401 is up too
        return e instanceof IfseenApiError && e.code === "unauthorized";
      }
    },
    20_000,
    "ifseen serve",
    proc.output,
  );
  return proc;
}

/** Pull events from a shared iterator until `pred` matches. */
async function until(it: AsyncIterator<IfseenEvent>, pred: (e: IfseenEvent) => boolean, seen: IfseenEvent[], timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const left = deadline - Date.now();
    if (left <= 0) throw new Error(`event not seen; got ${JSON.stringify(seen.map((e) => e.event))}`);
    let timer: ReturnType<typeof setTimeout> | undefined;
    const next = await Promise.race([
      it.next(),
      new Promise<"timeout">((r) => (timer = setTimeout(() => r("timeout"), left))),
    ]).finally(() => clearTimeout(timer));
    if (next === "timeout") continue;
    if (next.done) throw new Error("event stream ended");
    seen.push(next.value);
    if (pred(next.value)) return next.value;
  }
}

describe("ifseen serve --dry-run", { skip }, () => {
  let server: Spawned;
  let client: IfseenClient;

  before(async () => {
    const port = await freePort();
    server = await startServe(port);
    client = new IfseenClient({ baseUrl: `http://127.0.0.1:${port}` });
  });
  after(async () => server?.stop());

  test("health", async () => {
    const h = await client.health();
    assert.equal(h.ok, true);
    assert.equal(h.api, "v1");
    assert.equal(h.dry_run, true);
    assert.deepEqual(h.providers, ["mock"]);
    assert.equal(h.auth, false);
  });

  test("one-shot check through the server", async () => {
    const res = await client.check(fixtureBytes("red.jpg"), ["The image is mostly red.", "The image is mostly blue."]);
    assert.deepEqual(Object.keys(res.probs), ["the-image-is-mostly-red", "the-image-is-mostly-blue"]);
    for (const p of Object.values(res.probs)) assert.ok(p >= 0 && p <= 1);
    assert.match(res.provider, /^mock/);
    assert.equal(typeof res.latencyMs, "number");
    // a file path works too, and a PNG
    const res2 = await client.check(fixture("blue.png"), { blue: { when: "It is blue.", falseMeans: "Any other colour." } });
    assert.deepEqual(Object.keys(res2.probs), ["blue"]);
  });

  test("watcher lifecycle: create, SSE start/decision/fire, snapshot, state, stop, delete", async (t) => {
    const controller = new AbortController();
    t.after(() => controller.abort());
    let stream!: AsyncIterator<IfseenEvent>;
    let pending: Promise<IteratorResult<IfseenEvent>> | undefined;
    const opened = new Promise<void>((resolve) => {
      stream = client.events({ signal: controller.signal, onOpen: () => resolve() })[Symbol.asyncIterator]();
      // the request is only sent once the iterator is pulled
      pending = stream.next();
    });
    await opened;
    const seen: IfseenEvent[] = [];
    const firstOf = async (pred: (e: IfseenEvent) => boolean) => {
      // drain the first pending pull, then keep pulling
      if (pending) {
        const r = await pending;
        pending = undefined;
        if (!r.done) {
          seen.push(r.value);
          if (pred(r.value)) return r.value;
        }
      }
      return until(stream, pred, seen);
    };

    const created = await client.createWatcher({
      id: "js-int",
      source: { file: fixture("red.jpg") },
      every: "200ms",
      rules: [{ name: "red", when: "The image is mostly red.", threshold: 0.01 }],
    });
    assert.equal(created.id, "js-int");
    assert.deepEqual(created.rules.map((r) => r.name), ["red"]);

    const start = await firstOf((e) => e.event === "start" && e.watcher === "js-int");
    assert.ok(start.event === "start" && start.rules.includes("red"));
    const decision = await firstOf((e) => e.event === "decision" && e.watcher === "js-int");
    assert.ok(decision.event === "decision" && typeof decision.probs.red === "number");
    assert.ok(typeof decision.seq === "number" && decision.seq > 0);
    const fire = await firstOf((e) => e.event === "fire" && e.watcher === "js-int");
    assert.ok(fire.event === "fire");
    assert.equal(fire.rule, "red");
    assert.equal(fire.when, "The image is mostly red.");

    const jpeg = await client.snapshot("js-int");
    assert.equal(detectImageMime(jpeg), "image/jpeg");

    const state = await client.getWatcher("js-int");
    assert.equal(state.running, true);
    assert.equal(state.paused, false);
    assert.ok(state.rules[0]!.fires >= 1);
    assert.equal(typeof state.rules[0]!.active, "boolean");
    assert.ok(state.stats && state.stats.calls >= 1);
    assert.ok((await client.listWatchers()).some((w) => w.id === "js-int"));

    const stopped = await client.stopWatcher("js-int");
    assert.equal(stopped.running, false);
    assert.equal(stopped.stop_reason, "stopped");
    const stop = await firstOf((e) => e.event === "stop" && e.watcher === "js-int");
    assert.ok(stop.event === "stop" && stop.reason === "stopped");
    assert.equal((await client.startWatcher("js-int")).running, true);

    assert.deepEqual(await client.deleteWatcher("js-int"), { id: "js-int", deleted: true });
    controller.abort();
    await assert.rejects(client.getWatcher("js-int"), (e: unknown) => e instanceof IfseenApiError && e.code === "not_found");
  });

  test("on('fire') with a watcher filter, then unsubscribe", async (t) => {
    const controller = new AbortController();
    t.after(() => controller.abort());
    await client.createWatcher({
      id: "js-on",
      start: false,
      source: { file: fixture("red.jpg") },
      every: "200ms",
      rules: [{ name: "red", when: "The image is mostly red.", threshold: 0.01 }],
    });
    const fired = new Promise<IfseenEvent>((resolve, reject) => {
      const off = client.on(
        "fire",
        (e) => {
          off();
          resolve(e);
        },
        { watcher: "js-on", signal: controller.signal, onError: reject, onOpen: () => void client.startWatcher("js-on") },
      );
    });
    const e = await fired;
    assert.ok(e.event === "fire" && e.watcher === "js-on" && e.rule === "red");
    await client.deleteWatcher("js-on");
  });

  test("API error codes", async () => {
    const code = async (p: Promise<unknown>) => {
      try {
        await p;
      } catch (e) {
        assert.ok(e instanceof IfseenApiError, String(e));
        return `${e.status} ${e.code}`;
      }
      return "no error";
    };
    const source = { file: fixture("red.jpg") };
    assert.equal(await code(client.getWatcher("missing")), "404 not_found");
    assert.equal(await code(client.snapshot("missing")), "404 not_found");
    assert.equal(await code(client.createWatcher({ source, rules: [{ name: "x", when: "x", threshold: 2 }] })), "400 invalid_config");
    assert.equal(
      await code(client.createWatcher({ source, start: false, rules: [{ name: "x", when: "x", then: [{ shell: "echo hi" }] }] })),
      "403 shell_not_allowed",
    );
    await client.createWatcher({ id: "dupe", start: false, source, rules: [{ name: "x", when: "x" }] });
    assert.equal(await code(client.createWatcher({ id: "dupe", start: false, source, rules: [{ name: "x", when: "x" }] })), "409 already_exists");
    assert.equal(await code(client.snapshot("dupe")), "404 no_snapshot");
    await client.deleteWatcher("dupe");
    assert.equal(await code(client.check(fixtureBytes("red.jpg"), [])), "400 invalid_config");
    const it = client.events({ watcher: "missing" });
    assert.equal(await code(it.next()), "404 not_found");
  });
});

describe("ifseen serve with a token, and SSE reconnect across a restart", { skip }, () => {
  const token = "js-integration-token-0123456789";
  let port: number;
  let server: Spawned;

  before(async () => {
    port = await freePort();
    server = await startServe(port, ["--token", token]);
  });
  after(async () => server?.stop());

  test("bearer auth on requests and on the event stream", async () => {
    const anon = new IfseenClient({ baseUrl: `http://127.0.0.1:${port}` });
    await assert.rejects(anon.health(), (e: unknown) => e instanceof IfseenApiError && e.code === "unauthorized");
    await assert.rejects(anon.events().next(), (e: unknown) => e instanceof IfseenApiError && e.code === "unauthorized");
    const client = new IfseenClient({ baseUrl: `http://127.0.0.1:${port}`, token });
    assert.equal((await client.health()).auth, true);
  });

  test("events() reconnects after the server restarts", async () => {
    const client = new IfseenClient({ baseUrl: `http://127.0.0.1:${port}`, token });
    const controller = new AbortController();
    const opens: boolean[] = [];
    let reopened!: () => void;
    const reopenedP = new Promise<void>((r) => (reopened = r));
    let firstOpen!: () => void;
    const firstOpenP = new Promise<void>((r) => (firstOpen = r));
    const it = client
      .events({
        signal: controller.signal,
        types: ["start"],
        maxRetryDelayMs: 500,
        onOpen: ({ reconnect }) => {
          opens.push(reconnect);
          if (reconnect) reopened();
          else firstOpen();
        },
      })
      [Symbol.asyncIterator]();
    try {
      const next = it.next();
      await firstOpenP;

      await server.stop();
      server = await startServe(port, ["--token", token]);
      await reopenedP;

      await client.createWatcher({ id: "after-restart", source: { file: fixture("red.jpg") }, rules: [{ name: "red", when: "Red." }] });
      const r = await next;
      assert.ok(!r.done && r.value.event === "start" && r.value.watcher === "after-restart");
      assert.deepEqual(opens, [false, true]);
      await client.deleteWatcher("after-restart");
    } finally {
      controller.abort();
    }
  });
});
