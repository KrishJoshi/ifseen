/**
 * Direct provider checks against the repo's fake decision server (tests/fake_server.py),
 * which speaks the Gemini and System One wire formats on 127.0.0.1 and scores colour
 * statements by actually looking at the image. No paid API calls.
 */
import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { AuthError, check, checkDetailed } from "../src/index.js";
import { fixture, fixtureBytes, freePort, havePython, PYTHON_BIN, REPO_ROOT, type Spawned, spawnProcess, waitFor } from "./helpers.js";

const skip = havePython ? false : `python not found at ${PYTHON_BIN}`;
const KEY = "test-key";
const RULES = ["The image is mostly red.", "The image is mostly blue."];

describe("direct check() against the fake decision server", { skip }, () => {
  let server: Spawned;
  let base: string;

  before(async () => {
    const port = await freePort();
    server = spawnProcess(PYTHON_BIN, ["-u", `${REPO_ROOT}tests/fake_server.py`, String(port)], "SIGTERM");
    base = `http://127.0.0.1:${port}`;
    await waitFor(async () => server.output().includes("fake decision server on"), 20_000, "fake server", server.output);
  });
  after(async () => server?.stop());

  test("gemini", async () => {
    const res = await checkDetailed(fixture("red.jpg"), RULES, { apiKey: KEY, baseUrl: `${base}/v1beta/decisions`, context: "A test card." });
    assert.ok(res.probs["the-image-is-mostly-red"]! > 0.9, JSON.stringify(res.probs));
    assert.ok(res.probs["the-image-is-mostly-blue"]! < 0.1, JSON.stringify(res.probs));
    assert.ok(res.tokens > 258);
    assert.equal(res.model, "gemini-decision-1");
    assert.ok(res.costUsd > 0);
  });

  test("gemini with audio and criteria", async () => {
    const probs = await check(fixtureBytes("red.jpg"), { red: { when: "It is red.", trueMeans: "Mostly red.", falseMeans: "Other colours." } }, {
      apiKey: KEY,
      baseUrl: `${base}/v1beta/decisions`,
      audio: fixture("tone.wav"),
    });
    assert.ok(probs.red! > 0.9);
  });

  test("jev: JPEG and PNG", async () => {
    const red = await checkDetailed(fixtureBytes("red.jpg"), RULES, { provider: "jev", apiKey: KEY, baseUrl: `${base}/v1/systemone` });
    assert.ok(red.probs["the-image-is-mostly-red"]! > 0.9);
    assert.equal(red.tokens, 300);
    assert.equal(red.model, "jev-latest");
    const blue = await check(fixture("blue.png"), RULES, { provider: "jev", apiKey: KEY, baseUrl: `${base}/v1/systemone` });
    assert.ok(blue["the-image-is-mostly-blue"]! > 0.9 && blue["the-image-is-mostly-red"]! < 0.1);
  });

  test("azure: endpoint gets the System One path appended", async () => {
    const res = await checkDetailed(fixtureBytes("red.jpg"), RULES, { provider: "azure", apiKey: KEY, baseUrl: base, model: "Microsoft-Decision-1.1" });
    assert.ok(res.probs["the-image-is-mostly-red"]! > 0.9);
    assert.equal(res.provider, "azure (Microsoft-Decision-1.1)");
  });

  test("wrong keys are AuthErrors", async () => {
    await assert.rejects(check(fixtureBytes("red.jpg"), RULES, { apiKey: "wrong-key", baseUrl: `${base}/v1beta/decisions` }), AuthError);
    await assert.rejects(check(fixtureBytes("red.jpg"), RULES, { provider: "jev", apiKey: "wrong-key", baseUrl: `${base}/v1/systemone` }), AuthError);
  });
});
