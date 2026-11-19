import assert from "node:assert/strict";
import { test } from "node:test";

import { ConfigError, slugify, toQuestions } from "../src/index.js";
import { toServeRules } from "../src/rules.js";

test("slugify matches the Python implementation", () => {
  const taken = new Set<string>();
  const got = [
    "A parcel is on the doorstep.",
    "A person is visible.",
    "  !!! ",
    "The quick brown fox jumps over the lazy dog near the river bank",
    "The quick brown fox jumps over the lazy dog near the river bank!",
    "Café is OPEN — yes",
    "A parcel is on the doorstep!",
  ].map((s) => slugify(s, taken));
  assert.deepEqual(got, [
    "a-parcel-is-on-the-doorstep",
    "a-person-is-visible",
    "rule",
    "the-quick-brown-fox-jumps-over-the-lazy",
    "the-quick-brown-fox-jumps-over-the-l-2",
    "caf-is-open-yes",
    "a-parcel-is-on-the-doorstep-2",
  ]);
});

test("toQuestions: list, single string and mapping", () => {
  assert.deepEqual(toQuestions(["A dog.", "A dog!"]), [
    { key: "a-dog", statement: "A dog." },
    { key: "a-dog-2", statement: "A dog!" },
  ]);
  assert.deepEqual(toQuestions("Red."), [{ key: "red", statement: "Red." }]);
  assert.deepEqual(
    toQuestions({ door: { when: "The door is open.", falseMeans: "Closed.", true_means: "Ajar or open." }, red: "Red." }),
    [
      { key: "door", statement: "The door is open.", trueMeans: "Ajar or open.", falseMeans: "Closed." },
      { key: "red", statement: "Red." },
    ],
  );
});

test("toQuestions rejects bad input", () => {
  assert.throws(() => toQuestions([]), ConfigError);
  assert.throws(() => toQuestions({}), ConfigError);
  assert.throws(() => toQuestions({ "bad name": "x" }), /letters, digits/);
  assert.throws(() => toQuestions({ ok: { when: "x", nope: 1 } as never }), /unknown keys nope/);
  assert.throws(() => toQuestions({ ok: { when: "" } }), /'when'/);
  assert.throws(() => toQuestions([1 as never]), /must be strings/);
  assert.throws(() => toQuestions(Array.from({ length: 1001 }, (_, i) => `s${i}`)), /at most 1000/);
});

test("toServeRules converts camelCase specs to the wire shape", () => {
  assert.deepEqual(toServeRules(["a"]), ["a"]);
  assert.deepEqual(toServeRules({ p: { when: "x", trueMeans: "t" }, q: "y" }), {
    p: { when: "x", true_means: "t" },
    q: "y",
  });
});
