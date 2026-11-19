import { SYSTEMONE_IMAGE_MAX_SIDE, SYSTEMONE_IMAGE_MIN_SIDE } from "./constants.js";
import { ConfigError } from "./errors.js";
import { type FetchLike, postJson } from "./http.js";
import { imageSize, loadImage, loadWav, type MediaInput } from "./media.js";
import {
  buildGeminiRequest,
  buildSystemOneRequest,
  type Capture,
  parseNoulAnswers,
  type ProviderOptions,
  resolveProvider,
} from "./providers.js";
import { type Statements, toQuestions } from "./rules.js";

export interface CheckOptions extends ProviderOptions {
  /** A PCM WAV clip to send with (or instead of) the image. Gemini only. */
  audio?: MediaInput | undefined;
  /** Extra text sent with the capture, e.g. `"Doorbell camera, front of the house."`. */
  context?: string | undefined;
  /** Where the capture came from, used in the prompt. Default `"image"`. */
  label?: string | undefined;
  signal?: AbortSignal | undefined;
  /** Per-attempt timeout. Default 30 000 ms. */
  timeoutMs?: number | undefined;
  /** Attempts on network errors, 429 and 5xx. Default 3 (backoff 0.5 s, 1 s). */
  maxAttempts?: number | undefined;
  /** First retry delay; doubles each attempt. Default 500 ms. */
  retryDelayMs?: number | undefined;
  /** Custom fetch (proxies, tests, older runtimes). Default `globalThis.fetch`. */
  fetch?: FetchLike | undefined;
}

export interface CheckResult {
  /** `{ name: probability }` in the order the statements were given. */
  probs: Record<string, number>;
  /** Input tokens billed (0 if the provider didn't say). */
  tokens: number;
  latencyMs: number;
  /** Model that answered. */
  model: string;
  /** e.g. `"gemini (gemini-decision-1)"`. */
  provider: string;
  /** Estimated cost from list prices. */
  costUsd: number;
}

/**
 * Ask a decision model how likely each statement is for one image (and/or WAV clip).
 *
 * Calls the provider directly with your API key, so only use it server-side (Node, Bun,
 * Deno, workers). In a browser the key would be visible to anyone: use `IfseenClient` against
 * `ifseen serve`, or your own backend, instead.
 *
 * @returns `{ name: probability }` in the order the statements were given.
 */
export async function check(
  image: MediaInput | null | undefined,
  statements: Statements,
  opts: CheckOptions = {},
): Promise<Record<string, number>> {
  return (await checkDetailed(image, statements, opts)).probs;
}

/** Like {@link check}, but also returns tokens, latency, model and estimated cost. */
export async function checkDetailed(
  image: MediaInput | null | undefined,
  statements: Statements,
  opts: CheckOptions = {},
): Promise<CheckResult> {
  const questions = toQuestions(statements);
  const provider = resolveProvider(opts);
  if (image == null && opts.audio == null) throw new ConfigError("give an image and/or audio");

  const capture: Capture = { label: opts.label, context: opts.context, capturedAt: new Date() };
  if (image != null) capture.image = await loadImage(image);
  if (opts.audio != null) {
    if (provider.name !== "gemini") {
      throw new ConfigError(`${provider.name} can't hear audio; use provider 'gemini' for audio`);
    }
    capture.wav = await loadWav(opts.audio);
  }

  const post = {
    fetch: opts.fetch,
    signal: opts.signal,
    timeoutMs: opts.timeoutMs,
    maxAttempts: opts.maxAttempts,
    retryDelayMs: opts.retryDelayMs,
    secrets: provider.apiKey ? [provider.apiKey] : [],
  };

  let probs: Record<string, number>;
  let tokens: number;
  let latencyMs: number;
  let model = provider.model;
  if (provider.name === "gemini") {
    const body = buildGeminiRequest(provider, capture, questions);
    const res = await postJson(provider.name, provider.url, body, provider.headers, post);
    ({ probs, tokens } = parseNoulAnswers(provider.name, res.data, questions, "total_input_tokens"));
    latencyMs = res.latencyMs;
  } else {
    if (capture.image) {
      const size = imageSize(capture.image.bytes);
      if (
        size &&
        (Math.min(size.width, size.height) < SYSTEMONE_IMAGE_MIN_SIDE ||
          Math.max(size.width, size.height) > SYSTEMONE_IMAGE_MAX_SIDE)
      ) {
        throw new ConfigError(
          `${provider.name} needs images between ${SYSTEMONE_IMAGE_MIN_SIDE} and ${SYSTEMONE_IMAGE_MAX_SIDE} px ` +
            `per side (got ${size.width}x${size.height}); resize it first`,
        );
      }
    }
    const { body, headers } = buildSystemOneRequest(provider, capture, questions);
    const res = await postJson(provider.name, provider.url, body, headers, post);
    ({ probs, tokens } = parseNoulAnswers(provider.name, res.data, questions, "input_tokens"));
    latencyMs = res.latencyMs;
    const answered = (res.data as { model?: unknown }).model;
    if (typeof answered === "string" && answered) model = answered;
  }

  return {
    probs,
    tokens,
    latencyMs,
    model,
    provider: `${provider.name} (${model})`,
    costUsd: (tokens * provider.pricePerMInput) / 1_000_000,
  };
}
