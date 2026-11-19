import { ERROR_TEXT_LIMIT, HTTP_TIMEOUT_MS, MAX_ATTEMPTS, RETRY_BASE_DELAY_MS, RETRY_STATUSES } from "./constants.js";
import { AuthError, BillingError, ProviderError } from "./errors.js";

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface PostOptions {
  fetch?: FetchLike | undefined;
  signal?: AbortSignal | undefined;
  timeoutMs?: number | undefined;
  maxAttempts?: number | undefined;
  retryDelayMs?: number | undefined;
  /** Strings scrubbed from every error message (API keys). */
  secrets?: readonly string[] | undefined;
}

export function now(): number {
  return globalThis.performance?.now() ?? Date.now();
}

export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortReason(signal));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortReason(signal!));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export function abortReason(signal: AbortSignal): unknown {
  return signal.reason ?? new DOMException("The operation was aborted.", "AbortError");
}

export function isAbortError(e: unknown): boolean {
  return e instanceof Error && (e.name === "AbortError" || e.name === "TimeoutError");
}

/** A signal that aborts when `parent` aborts or after `timeoutMs`. AbortSignal.any isn't in Node 18. */
export function linkedSignal(
  parent: AbortSignal | undefined,
  timeoutMs?: number,
): { signal: AbortSignal; cleanup: () => void; timedOut: () => boolean } {
  const controller = new AbortController();
  let didTimeout = false;
  const onAbort = () => controller.abort(parent ? abortReason(parent) : undefined);
  if (parent?.aborted) onAbort();
  else parent?.addEventListener("abort", onAbort, { once: true });
  const timer =
    timeoutMs && timeoutMs > 0
      ? setTimeout(() => {
          didTimeout = true;
          controller.abort(new DOMException("timed out", "TimeoutError"));
        }, timeoutMs)
      : undefined;
  return {
    signal: controller.signal,
    cleanup: () => {
      if (timer !== undefined) clearTimeout(timer);
      parent?.removeEventListener("abort", onAbort);
    },
    timedOut: () => didTimeout,
  };
}

export function redact(text: string, secrets: readonly string[] | undefined): string {
  let out = text;
  for (const s of secrets ?? []) {
    if (s && s.length >= 4) out = out.split(s).join("***");
  }
  return out;
}

function errorText(raw: string): string {
  try {
    const body = JSON.parse(raw) as unknown;
    if (body && typeof body === "object") {
      const err = (body as { error?: unknown }).error;
      if (err && typeof err === "object" && typeof (err as { message?: unknown }).message === "string") {
        return (err as { message: string }).message.slice(0, ERROR_TEXT_LIMIT);
      }
      const detail = (body as { detail?: unknown }).detail;
      if (detail) return (typeof detail === "string" ? detail : JSON.stringify(detail)).slice(0, ERROR_TEXT_LIMIT);
    }
    return JSON.stringify(body).slice(0, 200);
  } catch {
    return raw.slice(0, 200);
  }
}

function resolveFetch(custom: FetchLike | undefined): FetchLike {
  const f = custom ?? (globalThis.fetch as FetchLike | undefined);
  if (!f) throw new ProviderError("ifseen", "no global fetch; pass the `fetch` option (Node 18+ has one built in)");
  return custom ? f : (input, init) => globalThis.fetch(input, init);
}

/**
 * POST JSON to a decision provider with retry/backoff on network errors, 429 and 5xx.
 * Mirrors the Python `Provider._post`.
 */
export async function postJson(
  provider: string,
  url: string,
  body: unknown,
  headers: Record<string, string>,
  opts: PostOptions = {},
): Promise<{ data: unknown; latencyMs: number }> {
  const fetchFn = resolveFetch(opts.fetch);
  const attempts = Math.max(1, opts.maxAttempts ?? MAX_ATTEMPTS);
  const baseDelay = opts.retryDelayMs ?? RETRY_BASE_DELAY_MS;
  const payload = JSON.stringify(body);
  const fail = (message: string, status?: number, cause?: unknown) =>
    new ProviderError(provider, redact(message, opts.secrets), status, cause ? { cause } : undefined);
  let last: ProviderError | undefined;

  for (let attempt = 0; attempt < attempts; attempt++) {
    if (opts.signal?.aborted) throw abortReason(opts.signal);
    const { signal, cleanup, timedOut } = linkedSignal(opts.signal, opts.timeoutMs ?? HTTP_TIMEOUT_MS);
    const start = now();
    try {
      let res: Response | undefined;
      try {
        res = await fetchFn(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json", ...headers },
          body: payload,
          signal,
        });
      } catch (e) {
        if (opts.signal?.aborted) throw abortReason(opts.signal);
        const kind = timedOut() ? "timed out" : `network error (${(e as Error)?.name ?? "Error"})`;
        last = fail(`${provider}: ${kind}`);
      }
      if (res) {
        const text = await res.text();
        const latencyMs = now() - start;
        if (res.status < 400) {
          try {
            return { data: JSON.parse(text) as unknown, latencyMs };
          } catch (e) {
            throw fail(`${provider}: response was not JSON`, res.status, e);
          }
        }
        // Google reports a bad key as 400 + API_KEY_INVALID rather than 401
        if (res.status === 401 || res.status === 403 || text.includes("API_KEY_INVALID")) {
          throw new AuthError(
            provider,
            `${provider}: authentication failed (HTTP ${res.status}) - check your API key`,
            res.status,
          );
        }
        if (res.status === 402) {
          throw new BillingError(
            provider,
            redact(`${provider}: billing problem (HTTP 402): ${errorText(text)}`, opts.secrets),
            402,
          );
        }
        last = fail(`${provider}: HTTP ${res.status}: ${errorText(text)}`, res.status);
        if (!RETRY_STATUSES.has(res.status)) throw last;
      }
    } catch (e) {
      if (opts.signal?.aborted) throw abortReason(opts.signal);
      if (e instanceof ProviderError) throw e;
      // body read failed mid-stream: retry like a network error
      last = fail(`${provider}: network error (${(e as Error)?.name ?? "Error"})`, undefined, e);
    } finally {
      cleanup();
    }
    if (attempt < attempts - 1) await sleep(baseDelay * 2 ** attempt, opts.signal);
  }
  throw last ?? fail(`${provider}: request failed`);
}
