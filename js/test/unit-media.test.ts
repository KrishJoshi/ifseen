import assert from "node:assert/strict";
import { test } from "node:test";

import { base64ToBytes, bytesToBase64, ConfigError, detectImageMime, imageSize, isWav } from "../src/index.js";
import { loadImage, toBytes } from "../src/media.js";
import { fixture, fixtureBytes } from "./helpers.js";

test("base64 round-trips and matches Buffer for every length mod 3", () => {
  for (let len = 0; len < 40; len++) {
    const bytes = new Uint8Array(len).map((_, i) => (i * 37 + len) & 0xff);
    const b64 = bytesToBase64(bytes);
    assert.equal(b64, Buffer.from(bytes).toString("base64"));
    assert.deepEqual(base64ToBytes(b64), bytes);
  }
  const big = new Uint8Array(100_000).map((_, i) => i & 0xff);
  assert.equal(bytesToBase64(big), Buffer.from(big).toString("base64"));
  assert.deepEqual(base64ToBytes("aGk"), new TextEncoder().encode("hi")); // unpadded
  assert.deepEqual(base64ToBytes("_-8"), new Uint8Array([0xff, 0xef])); // url-safe
  assert.throws(() => base64ToBytes("ab$c"), ConfigError);
});

test("magic-byte detection", () => {
  assert.equal(detectImageMime(fixtureBytes("red.jpg")), "image/jpeg");
  assert.equal(detectImageMime(fixtureBytes("blue.png")), "image/png");
  assert.equal(detectImageMime(fixtureBytes("tone.wav")), undefined);
  assert.equal(detectImageMime(new Uint8Array([0xff, 0xd8])), undefined);
  assert.equal(detectImageMime(new TextEncoder().encode("GIF89a......")), undefined);
  assert.ok(isWav(fixtureBytes("tone.wav")));
  assert.ok(!isWav(fixtureBytes("red.jpg")));
});

test("imageSize reads PNG and JPEG headers", () => {
  assert.deepEqual(imageSize(fixtureBytes("red.jpg")), { width: 400, height: 300 });
  assert.deepEqual(imageSize(fixtureBytes("blue.png")), { width: 400, height: 300 });
  assert.deepEqual(imageSize(fixtureBytes("small-green.jpg")), { width: 100, height: 80 });
  assert.equal(imageSize(new Uint8Array([1, 2, 3])), undefined);
});

test("toBytes accepts every input form", async () => {
  const jpg = fixtureBytes("red.jpg");
  const b64 = Buffer.from(jpg).toString("base64");
  const forms: unknown[] = [
    jpg,
    jpg.buffer.slice(jpg.byteOffset, jpg.byteOffset + jpg.byteLength),
    Buffer.from(jpg),
    new DataView(jpg.buffer, jpg.byteOffset, jpg.byteLength),
    new Blob([new Uint8Array(jpg)]),
    b64,
    b64.replace(/(.{76})/g, "$1\n"),
    `data:image/jpeg;base64,${b64}`,
    { base64: b64 },
    fixture("red.jpg"),
    { path: fixture("red.jpg") },
  ];
  for (const f of forms) assert.deepEqual(await toBytes(f as never), jpg);
});

test("toBytes / loadImage errors", async () => {
  await assert.rejects(toBytes("/definitely/not/here.jpg"), /no such file/);
  await assert.rejects(toBytes(""), ConfigError);
  await assert.rejects(toBytes(42 as never), /unsupported media/);
  await assert.rejects(toBytes("data:text/plain,hello"), /base64 data: URLs/);
  await assert.rejects(loadImage(fixtureBytes("tone.wav")), /only JPEG and PNG/);
});
