import {
  AZURE_DEFAULT_MODEL,
  AZURE_DEPLOYMENT_ENV,
  AZURE_ENDPOINT_ENV,
  AZURE_KEY_ENV,
  AZURE_PATH,
  GEMINI_DEFAULT_MODEL,
  GEMINI_KEY_ENVS,
  GEMINI_URL,
  JEV_DEFAULT_MODEL,
  JEV_IMAGE_HEADER,
  JEV_KEY_ENV,
  JEV_URL,
  PRICE_PER_M_INPUT,
  SYSTEMONE_PATH,
} from "./constants.js";
import { ConfigError, ProviderError } from "./errors.js";
import { bytesToBase64, type ImageMime } from "./media.js";
import type { Question } from "./rules.js";

export type ProviderName = "gemini" | "jev" | "azure" | "systemone";

/** What one capture contains; the input to a request builder. */
export interface Capture {
  image?: { bytes: Uint8Array; mime: ImageMime } | undefined;
  wav?: Uint8Array | undefined;
  /** Where the capture came from, used in the text prompt. Default `"image"` / `"audio"`. */
  label?: string | undefined;
  context?: string | undefined;
  capturedAt?: Date | undefined;
}

/** A fully resolved provider: where to send what. */
export interface ResolvedProvider {
  name: ProviderName;
  url: string;
  model: string;
  headers: Record<string, string>;
  /** Extra headers only sent when the request carries an image (Jev's danger-zone header). */
  imageHeaders: Record<string, string>;
  pricePerMInput: number;
  apiKey?: string | undefined;
  resolution?: string | undefined;
}

export interface ProviderOptions {
  /** Default `"gemini"`. */
  provider?: ProviderName | undefined;
  /**
   * API key. Defaults to the same env vars as the Python package when a `process.env` /
   * `Deno.env` exists: `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `TYPESAFE_API_KEY`, `AZURE_DECISION_KEY`.
   */
  apiKey?: string | undefined;
  model?: string | undefined;
  /**
   * Endpoint override for proxies, self-hosted servers and tests.
   * gemini / jev: the full endpoint URL. azure: the Foundry resource endpoint (or a full
   * `.../systemone` URL). systemone: the server's base URL (required).
   */
  baseUrl?: string | undefined;
  /** Gemini only: `"low"` / `"medium"` / `"high"`. Fewer image tokens = cheaper. */
  resolution?: "low" | "medium" | "high" | undefined;
  /** Extra request headers. */
  headers?: Record<string, string> | undefined;
}

/** Read an env var without assuming Node, and without tripping Deno's permission errors. */
export function readEnv(name: string): string | undefined {
  const g = globalThis as {
    process?: { env?: Record<string, string | undefined> };
    Deno?: { env?: { get(key: string): string | undefined } };
  };
  try {
    const v = g.process?.env?.[name] ?? g.Deno?.env?.get(name);
    return v || undefined;
  } catch {
    return undefined;
  }
}

function firstEnv(names: readonly string[]): string | undefined {
  for (const n of names) {
    const v = readEnv(n);
    if (v) return v;
  }
  return undefined;
}

export function resolveProvider(opts: ProviderOptions): ResolvedProvider {
  const name = opts.provider ?? "gemini";
  const extra = opts.headers ?? {};
  const keyFor = (envs: readonly string[], required: boolean): string | undefined => {
    const key = opts.apiKey ?? firstEnv(envs);
    if (!key && required) {
      throw new ConfigError(`provider '${name}' needs an API key: pass apiKey or set ${envs.join(" / ")}`);
    }
    return key;
  };
  switch (name) {
    case "gemini": {
      const key = keyFor(GEMINI_KEY_ENVS, true)!;
      return {
        name,
        url: opts.baseUrl ?? GEMINI_URL,
        model: opts.model ?? GEMINI_DEFAULT_MODEL,
        headers: { "x-goog-api-key": key, ...extra },
        imageHeaders: {},
        pricePerMInput: PRICE_PER_M_INPUT.gemini,
        apiKey: key,
        resolution: opts.resolution,
      };
    }
    case "jev": {
      const key = keyFor([JEV_KEY_ENV], true)!;
      return {
        name,
        url: opts.baseUrl ?? JEV_URL,
        model: opts.model ?? JEV_DEFAULT_MODEL,
        headers: { Authorization: `Bearer ${key}`, ...extra },
        imageHeaders: { [JEV_IMAGE_HEADER]: "true" },
        pricePerMInput: PRICE_PER_M_INPUT.jev,
        apiKey: key,
      };
    }
    case "azure": {
      const endpoint = opts.baseUrl ?? readEnv(AZURE_ENDPOINT_ENV);
      if (!endpoint) {
        throw new ConfigError(
          `provider 'azure' needs baseUrl (your Foundry resource endpoint) or $${AZURE_ENDPOINT_ENV}`,
        );
      }
      const key = keyFor([AZURE_KEY_ENV], true)!;
      let url = endpoint.replace(/\/+$/, "");
      if (!url.endsWith("/systemone")) url += AZURE_PATH;
      return {
        name,
        url,
        model: opts.model ?? readEnv(AZURE_DEPLOYMENT_ENV) ?? AZURE_DEFAULT_MODEL,
        headers: { "api-key": key, ...extra },
        imageHeaders: {},
        pricePerMInput: PRICE_PER_M_INPUT.azure,
        apiKey: key,
      };
    }
    case "systemone": {
      if (!opts.baseUrl) {
        throw new ConfigError("provider 'systemone' needs baseUrl, e.g. http://localhost:8080");
      }
      let url = opts.baseUrl.replace(/\/+$/, "");
      if (!url.endsWith("/systemone")) url += SYSTEMONE_PATH;
      const key = keyFor([JEV_KEY_ENV], false);
      return {
        name,
        url,
        model: opts.model ?? JEV_DEFAULT_MODEL,
        headers: { ...(key ? { Authorization: `Bearer ${key}` } : {}), ...extra },
        imageHeaders: { [JEV_IMAGE_HEADER]: "true" },
        pricePerMInput: PRICE_PER_M_INPUT.systemone,
        apiKey: key,
      };
    }
    default:
      throw new ConfigError(`unknown provider '${String(name)}' (use gemini, jev, azure or systemone)`);
  }
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** The text prompt, same as the Python `describe_capture`. */
export function describeCapture(capture: Capture): string {
  const at = capture.capturedAt ?? new Date();
  const when = `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
  const what: string[] = [];
  if (capture.image) what.push("a still frame");
  if (capture.wav) what.push("an audio clip");
  const label = capture.label ?? (capture.image ? "image" : "audio");
  let text = `Live capture (${what.join(" and ")}) from ${label} at ${when}.`;
  if (capture.context) text += `\nContext: ${capture.context}`;
  return text;
}

export interface GeminiRequest {
  model: string;
  input: Array<
    | { type: "text"; text: string }
    | { type: "image"; data: string; mime_type: string; resolution?: string }
    | { type: "audio"; data: string; mime_type: string }
  >;
  questions: Record<
    string,
    { type: "noul"; instructions: string; criteria?: { true_description?: string; false_description?: string } }
  >;
}

export function buildGeminiRequest(p: ResolvedProvider, capture: Capture, questions: Question[]): GeminiRequest {
  const input: GeminiRequest["input"] = [{ type: "text", text: describeCapture(capture) + "\n" }];
  if (capture.image) {
    const image: GeminiRequest["input"][number] = {
      type: "image",
      data: bytesToBase64(capture.image.bytes),
      mime_type: capture.image.mime,
    };
    if (p.resolution) image.resolution = p.resolution;
    input.push(image);
  }
  if (capture.wav) input.push({ type: "audio", data: bytesToBase64(capture.wav), mime_type: "audio/wav" });
  const qs: GeminiRequest["questions"] = {};
  for (const q of questions) {
    const item: GeminiRequest["questions"][string] = { type: "noul", instructions: q.statement };
    if (q.trueMeans || q.falseMeans) {
      item.criteria = {};
      if (q.trueMeans) item.criteria.true_description = q.trueMeans;
      if (q.falseMeans) item.criteria.false_description = q.falseMeans;
    }
    qs[q.key] = item;
  }
  return { model: p.model, input, questions: qs };
}

export interface SystemOneRequest {
  model: string;
  state: string;
  assets?: Record<string, { type: "image"; format: "jpg" | "png"; data_base64: string }>;
  questions: Record<string, { type: "noul"; instructions: string; criteria?: { true?: string; false?: string } }>;
}

function randomHex(chars: number): string {
  let out = "";
  for (let i = 0; i < chars; i++) out += Math.floor(Math.random() * 16).toString(16);
  return out;
}

export function buildSystemOneRequest(
  p: ResolvedProvider,
  capture: Capture,
  questions: Question[],
): { body: SystemOneRequest; headers: Record<string, string> } {
  let state = describeCapture(capture);
  const headers = { ...p.headers };
  let assets: SystemOneRequest["assets"];
  if (capture.image) {
    const format = capture.image.mime === "image/png" ? "png" : "jpg";
    // Jev swaps any plain-text occurrence of the asset key for the image; Azure expects an
    // "image:<key>" reference. "image:<key>" satisfies both.
    const key = `frame-${randomHex(12)}.${format}`;
    state += `\nFrame: image:${key}`;
    assets = { [key]: { type: "image", format, data_base64: bytesToBase64(capture.image.bytes) } };
    Object.assign(headers, p.imageHeaders);
  }
  const qs: SystemOneRequest["questions"] = {};
  for (const q of questions) {
    const item: SystemOneRequest["questions"][string] = { type: "noul", instructions: q.statement };
    if (q.trueMeans || q.falseMeans) {
      item.criteria = {};
      if (q.trueMeans) item.criteria.true = q.trueMeans;
      if (q.falseMeans) item.criteria.false = q.falseMeans;
    }
    qs[q.key] = item;
  }
  const body: SystemOneRequest = { model: p.model, state, ...(assets ? { assets } : {}), questions: qs };
  return { body, headers };
}

export function clampProb(value: unknown): number {
  const p = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN;
  if (Number.isNaN(p)) return 0;
  return Math.min(1, Math.max(0, p));
}

/** Pull noul probabilities and token usage out of a decision response, defensively. */
export function parseNoulAnswers(
  provider: string,
  data: unknown,
  questions: Question[],
  usageKey: string,
): { probs: Record<string, number>; tokens: number } {
  const answers = (data as { answers?: unknown } | null)?.answers;
  if (!data || typeof data !== "object" || !answers || typeof answers !== "object") {
    throw new ProviderError(provider, `${provider}: response had no answers`);
  }
  const probs: Record<string, number> = {};
  for (const q of questions) {
    const a = (answers as Record<string, unknown>)[q.key];
    probs[q.key] = a && typeof a === "object" ? clampProb((a as { noul?: unknown }).noul) : 0;
  }
  const usage = (data as { usage?: unknown }).usage;
  const raw = usage && typeof usage === "object" ? (usage as Record<string, unknown>)[usageKey] : 0;
  const tokens = Number.parseInt(String(raw ?? 0), 10);
  return { probs, tokens: Number.isFinite(tokens) ? tokens : 0 };
}
