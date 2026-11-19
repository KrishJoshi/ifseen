import { MAX_QUESTIONS, RULE_NAME_PATTERN } from "./constants.js";
import { ConfigError } from "./errors.js";

/** A statement with optional clarifications of what "true" and "false" mean. */
export interface StatementSpec {
  when: string;
  trueMeans?: string;
  falseMeans?: string;
  /** snake_case aliases, as in YAML rule files and the HTTP API. */
  true_means?: string;
  false_means?: string;
}

/**
 * Plain-English statements: a list (names become slugs, e.g.
 * `"A parcel is on the doorstep."` → `"a-parcel-is-on-the-doorstep"`) or `{ name: statement }`.
 */
export type Statements = string | readonly string[] | Record<string, string | StatementSpec>;

/** One normalised question sent to a decision model. */
export interface Question {
  key: string;
  statement: string;
  trueMeans?: string;
  falseMeans?: string;
}

/**
 * A unique rule name derived from a statement, same as the Python `slugify`.
 * Adds the result to `taken`.
 */
export function slugify(text: string, taken: Set<string> = new Set()): string {
  const base =
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40)
      .replace(/^-+|-+$/g, "") || "rule";
  let name = base;
  let n = 2;
  while (taken.has(name)) {
    name = `${base.slice(0, 36)}-${n}`;
    n++;
  }
  taken.add(name);
  return name;
}

function optionalString(value: unknown, field: string, name: string): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  if (typeof value !== "string") throw new ConfigError(`statement '${name}': ${field} must be a string`);
  return value;
}

/** Validate statements and turn them into questions (in the order given). */
export function toQuestions(statements: Statements): Question[] {
  const list = typeof statements === "string" ? [statements] : statements;
  const questions: Question[] = [];
  if (Array.isArray(list)) {
    const taken = new Set<string>();
    for (const s of list as readonly unknown[]) {
      if (typeof s !== "string") throw new ConfigError(`statements must be strings, got ${typeof s}`);
      if (!s.trim()) throw new ConfigError("statements must not be empty");
      questions.push({ key: slugify(s, taken), statement: s });
    }
  } else if (list && typeof list === "object") {
    for (const [name, value] of Object.entries(list as Record<string, unknown>)) {
      if (!RULE_NAME_PATTERN.test(name)) {
        throw new ConfigError(`statement name '${name}' must be 1-64 letters, digits, '_' or '-'`);
      }
      if (typeof value === "string") {
        if (!value.trim()) throw new ConfigError(`statement '${name}' must not be empty`);
        questions.push({ key: name, statement: value });
        continue;
      }
      if (!value || typeof value !== "object") {
        throw new ConfigError(`statement '${name}' must be a string or { when, trueMeans?, falseMeans? }`);
      }
      const spec = value as Record<string, unknown>;
      const allowed = new Set(["when", "trueMeans", "falseMeans", "true_means", "false_means"]);
      const extra = Object.keys(spec).filter((k) => !allowed.has(k));
      if (extra.length) throw new ConfigError(`statement '${name}': unknown keys ${extra.sort().join(", ")}`);
      const when = spec.when;
      if (typeof when !== "string" || !when.trim()) {
        throw new ConfigError(`statement '${name}': 'when' must be a non-empty string`);
      }
      const q: Question = { key: name, statement: when };
      const t = optionalString(spec.trueMeans ?? spec.true_means, "trueMeans", name);
      const f = optionalString(spec.falseMeans ?? spec.false_means, "falseMeans", name);
      if (t) q.trueMeans = t;
      if (f) q.falseMeans = f;
      questions.push(q);
    }
  } else {
    throw new ConfigError("statements must be a list of strings or a { name: statement } object");
  }
  if (!questions.length) throw new ConfigError("at least one statement is required");
  if (questions.length > MAX_QUESTIONS) throw new ConfigError(`at most ${MAX_QUESTIONS} statements per call`);
  return questions;
}

/** The HTTP API's `rules` shape (`{ name: string | { when, true_means?, false_means? } }`). */
export function toServeRules(
  statements: Statements,
): string[] | Record<string, string | { when: string; true_means?: string; false_means?: string }> {
  if (typeof statements === "string") return [statements];
  if (Array.isArray(statements)) return [...(statements as readonly string[])];
  const out: Record<string, string | { when: string; true_means?: string; false_means?: string }> = {};
  for (const [name, value] of Object.entries(statements as Record<string, string | StatementSpec>)) {
    if (typeof value === "string" || !value || typeof value !== "object") {
      out[name] = value as string;
      continue;
    }
    const spec: { when: string; true_means?: string; false_means?: string } = { when: value.when };
    const t = value.trueMeans ?? value.true_means;
    const f = value.falseMeans ?? value.false_means;
    if (t) spec.true_means = t;
    if (f) spec.false_means = f;
    out[name] = spec;
  }
  return out;
}
