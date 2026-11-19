import { SERVE_DEFAULT_URL, SSE_DEFAULT_RETRY_MS, SSE_IDLE_TIMEOUT_MS, SSE_MAX_RETRY_MS, WATCHER_ID_PATTERN } from "./constants.js";
import { IfseenApiError, IfseenConnectionError } from "./errors.js";
import { type FetchLike, abortReason, linkedSignal, sleep } from "./http.js";
import { bytesToBase64, type MediaInput, toBytes } from "./media.js";
import { type Statements, toServeRules } from "./rules.js";
import { SseParser } from "./sse.js";
import type {
  DeleteWatcherResponse,
  EventOfKind,
  HealthResponse,
  IfseenEvent,
  KnownEventKind,
  ProviderConfig,
  ServeCheckResult,
  WatcherConfig,
  WatcherState,
} from "./types.js";

export interface IfseenClientOptions {
  /** Default `http://127.0.0.1:8899`. */
  baseUrl?: string;
  /** Bearer token, if the server runs with `--token` / `IFSEEN_TOKEN`. */
  token?: string;
  /** Custom fetch. Default `globalThis.fetch`. */
  fetch?: FetchLike;
  /** Timeout for normal requests (not the event stream). Default 120 000 ms. */
  timeoutMs?: number;
  /** Extra headers on every request. */
  headers?: Record<string, string>;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

export interface ServeCheckOptions extends RequestOptions {
  /** PCM WAV clip to send with (or instead of) the image. */
  audio?: MediaInput;
  /** Provider name or `{ name, resolution, ... }`. Default `"auto"` (the server decides). */
  provider?: ProviderConfig;
  model?: string;
  context?: string;
}

export interface EventsOptions {
  /** Only this watcher's events (the server answers 404 if it doesn't exist). */
  watcher?: string;
  /** Only these event kinds, e.g. `["fire", "error", "stop"]`. */
  types?: readonly (KnownEventKind | (string & {}))[];
  /** Abort to end the iteration cleanly (no error is thrown). */
  signal?: AbortSignal;
  /** Reconnect when the stream drops or the server is briefly unreachable. Default `true`. */
  reconnect?: boolean;
  /** Upper bound for the reconnect backoff. Default 30 000 ms. */
  maxRetryDelayMs?: number;
  /**
   * Reconnect if nothing (not even a keep-alive comment, sent every 15 s) arrives for this
   * long. Default 45 000 ms; 0 disables.
   */
  idleTimeoutMs?: number;
  /**
   * Called on every successful (re)connection. Events aren't replayed after a reconnect, so
   * this is the place to resync with `listWatchers()`.
   */
  onOpen?: (info: { reconnect: boolean }) => void;
  /** Called when a connection fails or drops and a reconnect is scheduled. */
  onDisconnect?: (info: { error?: unknown; retryInMs: number }) => void;
}

export interface OnOptions extends Omit<EventsOptions, "types"> {
  /**
   * Gets errors thrown by the handler and fatal stream errors (bad token, unknown watcher).
   * Default: `console.error`.
   */
  onError?: (error: unknown) => void;
}

const KNOWN_KINDS: ReadonlySet<string> = new Set<KnownEventKind>([
  "start",
  "decision",
  "fire",
  "clear",
  "error",
  "log",
  "pause",
  "resume",
  "stop",
]);

/** Statuses worth reconnecting on; anything else (401, 404...) won't fix itself. */
const RETRYABLE_STATUSES: ReadonlySet<number> = new Set([408, 425, 429, 500, 502, 503, 504]);

/** Turn one SSE message into an event, or `undefined` if it isn't one. */
export function parseEvent(data: string, sseEvent: string, id: string | undefined): IfseenEvent | undefined {
  let obj: unknown;
  try {
    obj = JSON.parse(data);
  } catch {
    return undefined;
  }
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) return undefined;
  const payload = obj as Record<string, unknown>;
  const kind = typeof payload.event === "string" ? payload.event : sseEvent;
  const seq = id !== undefined && /^\d+$/.test(id) ? Number(id) : undefined;
  const base = {
    watcher: typeof payload.watcher === "string" ? payload.watcher : "",
    time: typeof payload.time === "number" ? payload.time : 0,
  };
  if (KNOWN_KINDS.has(kind)) {
    return { ...payload, ...base, event: kind, ...(seq !== undefined ? { seq } : {}) } as IfseenEvent;
  }
  return { ...base, event: "unknown", kind, payload, ...(seq !== undefined ? { seq } : {}) };
}

function kindOf(event: IfseenEvent): string {
  return event.event === "unknown" ? event.kind : event.event;
}

function checkId(id: string): string {
  if (typeof id !== "string" || !WATCHER_ID_PATTERN.test(id)) {
    throw new IfseenApiError(400, "invalid_id", "id must be 1-64 letters, digits, '_' or '-'");
  }
  return id;
}

/**
 * A client for the `ifseen serve` HTTP API (docs/api.md). Safe to use from a browser: it
 * talks to your own ifseen server, never to a provider, so no provider key is involved.
 */
export class IfseenClient {
  readonly baseUrl: string;
  readonly #token: string | undefined;
  readonly #fetch: FetchLike;
  readonly #timeoutMs: number;
  readonly #headers: Record<string, string>;

  constructor(options: IfseenClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? SERVE_DEFAULT_URL).replace(/\/+$/, "");
    this.#token = options.token || undefined;
    const custom = options.fetch;
    this.#fetch = custom ?? ((input, init) => globalThis.fetch(input, init));
    this.#timeoutMs = options.timeoutMs ?? 120_000;
    this.#headers = { ...(options.headers ?? {}) };
  }

  // -- endpoints ----------------------------------------------------------------------------

  /** `GET /v1/health`. */
  health(opts: RequestOptions = {}): Promise<HealthResponse> {
    return this.#json("GET", "/v1/health", undefined, opts);
  }

  /** `POST /v1/check`: one-shot probabilities, using the server's provider and key. */
  async check(
    image: MediaInput | null | undefined,
    rules: Statements,
    opts: ServeCheckOptions = {},
  ): Promise<ServeCheckResult> {
    const body: Record<string, unknown> = { rules: toServeRules(rules) };
    if (image != null) body.image_base64 = bytesToBase64(await toBytes(image));
    if (opts.audio != null) body.audio_base64 = bytesToBase64(await toBytes(opts.audio));
    if (opts.provider !== undefined) body.provider = opts.provider;
    if (opts.model !== undefined) body.model = opts.model;
    if (opts.context !== undefined) body.context = opts.context;
    const res = await this.#json<{
      probs: Record<string, number>;
      tokens: number;
      latency_ms: number;
      cost_usd: number;
      provider: string;
    }>("POST", "/v1/check", body, opts);
    return {
      probs: res.probs,
      tokens: res.tokens,
      latencyMs: res.latency_ms,
      costUsd: res.cost_usd,
      provider: res.provider,
    };
  }

  /** `GET /v1/watchers`. */
  async listWatchers(opts: RequestOptions = {}): Promise<WatcherState[]> {
    return (await this.#json<{ watchers: WatcherState[] }>("GET", "/v1/watchers", undefined, opts)).watchers;
  }

  /** `POST /v1/watchers`: a rules-file config as JSON, plus optional `id` and `start`. */
  async createWatcher(config: WatcherConfig, opts: RequestOptions = {}): Promise<WatcherState> {
    if (config.id !== undefined) checkId(config.id);
    return this.#json("POST", "/v1/watchers", config, opts);
  }

  /** `GET /v1/watchers/{id}`. */
  async getWatcher(id: string, opts: RequestOptions = {}): Promise<WatcherState> {
    return this.#json("GET", `/v1/watchers/${checkId(id)}`, undefined, opts);
  }

  /** `DELETE /v1/watchers/{id}`: stops (waiting up to 10 s) and removes it. */
  async deleteWatcher(id: string, opts: RequestOptions = {}): Promise<DeleteWatcherResponse> {
    return this.#json("DELETE", `/v1/watchers/${checkId(id)}`, undefined, opts);
  }

  /** `POST /v1/watchers/{id}/start`. Idempotent. */
  async startWatcher(id: string, opts: RequestOptions = {}): Promise<WatcherState> {
    return this.#json("POST", `/v1/watchers/${checkId(id)}/start`, {}, opts);
  }

  /** `POST /v1/watchers/{id}/stop`. Idempotent; waits up to 10 s for the loop to finish. */
  async stopWatcher(id: string, opts: RequestOptions = {}): Promise<WatcherState> {
    return this.#json("POST", `/v1/watchers/${checkId(id)}/stop`, {}, opts);
  }

  /** `GET /v1/watchers/{id}/snapshot`: the latest frame as JPEG bytes (404 `no_snapshot` before the first). */
  async snapshot(id: string, opts: RequestOptions = {}): Promise<Uint8Array> {
    const res = await this.#request("GET", `/v1/watchers/${checkId(id)}/snapshot`, undefined, opts);
    return new Uint8Array(await res.arrayBuffer());
  }

  // -- events -------------------------------------------------------------------------------

  /**
   * `GET /v1/events` as an async iterable, read with fetch (so a bearer token works, unlike
   * `EventSource`). Reconnects with backoff when the stream drops; ends when `signal` aborts
   * or you `break` out of the loop. Throws {@link IfseenApiError} for errors a retry can't
   * fix (401, unknown watcher).
   */
  events(opts: EventsOptions = {}): AsyncIterableIterator<IfseenEvent> {
    return this.#events(opts);
  }

  async *#events(opts: EventsOptions): AsyncGenerator<IfseenEvent, void, undefined> {
    const { signal } = opts;
    const reconnect = opts.reconnect ?? true;
    const maxDelay = opts.maxRetryDelayMs ?? SSE_MAX_RETRY_MS;
    const idleTimeout = opts.idleTimeoutMs ?? SSE_IDLE_TIMEOUT_MS;
    const wanted = opts.types?.length ? new Set<string>(opts.types) : undefined;
    const query = new URLSearchParams();
    if (opts.watcher !== undefined) query.set("watcher", checkId(opts.watcher));
    if (wanted) query.set("types", [...wanted].join(","));
    const qs = query.toString();
    const url = `${this.baseUrl}/v1/events${qs ? `?${qs}` : ""}`;

    let retryMs = SSE_DEFAULT_RETRY_MS;
    let failures = 0;
    let connected = false;

    // Returns false when the iteration should end (aborted).
    const backoff = async (error: unknown, clean: boolean): Promise<boolean> => {
      const delay = clean ? retryMs : Math.min(maxDelay, retryMs * 2 ** Math.min(failures - 1, 10));
      const jittered = Math.round(delay * (0.8 + Math.random() * 0.4));
      opts.onDisconnect?.({ ...(error !== undefined ? { error } : {}), retryInMs: jittered });
      try {
        await sleep(jittered, signal);
        return true;
      } catch {
        return false;
      }
    };

    while (!signal?.aborted) {
      const controller = new AbortController();
      let idleTimer: ReturnType<typeof setTimeout> | undefined;
      let idled = false;
      // The generator may sit suspended at a `yield` forever if the consumer stops pulling,
      // so its finally blocks can't be relied on: aborting must release everything itself.
      const onAbort = () => {
        if (idleTimer !== undefined) clearTimeout(idleTimer);
        controller.abort(abortReason(signal!));
      };
      signal?.addEventListener("abort", onAbort, { once: true });
      const resetIdle = () => {
        if (!idleTimeout || controller.signal.aborted) return;
        if (idleTimer !== undefined) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
          idled = true;
          controller.abort(new DOMException("event stream idle", "TimeoutError"));
        }, idleTimeout);
      };
      let error: unknown;
      let clean = false;
      try {
        resetIdle();
        let res: Response;
        try {
          res = await this.#fetch(url, {
            method: "GET",
            headers: this.#buildHeaders({ Accept: "text/event-stream" }),
            signal: controller.signal,
            cache: "no-store",
          });
        } catch (e) {
          if (signal?.aborted) return;
          throw new IfseenConnectionError(
            idled ? `${this.baseUrl}: timed out connecting to the event stream` : `could not reach ${this.baseUrl}`,
            { cause: e },
          );
        }
        if (!res.ok) {
          const apiError = await toApiError(res);
          if (!reconnect || !RETRYABLE_STATUSES.has(res.status)) throw apiError;
          throw Object.assign(apiError, { retryable: true });
        }
        if (!res.body) throw new IfseenConnectionError("the event stream response had no body");
        failures = 0;
        opts.onOpen?.({ reconnect: connected });
        connected = true;

        const queue: IfseenEvent[] = [];
        const parser = new SseParser({
          onMessage: (m) => {
            const event = parseEvent(m.data, m.event, m.id);
            if (event && (!wanted || wanted.has(kindOf(event)))) queue.push(event);
          },
          onRetry: (ms) => {
            retryMs = ms;
          },
        });
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        // Not every fetch implementation errors a pending read() on abort; cancelling the
        // reader always ends it.
        controller.signal.addEventListener("abort", () => void reader.cancel().catch(() => {}), { once: true });
        try {
          for (;;) {
            const { done, value } = await reader.read();
            if (signal?.aborted) return;
            if (idled) throw new IfseenConnectionError("event stream went idle");
            if (done) break;
            resetIdle();
            parser.feed(decoder.decode(value, { stream: true }));
            while (queue.length) yield queue.shift()!;
          }
          parser.feed(decoder.decode());
          while (queue.length) yield queue.shift()!;
          clean = true; // the server ended the stream (shutdown, or we fell 1000 events behind)
        } finally {
          reader.cancel().catch(() => {});
        }
      } catch (e) {
        if (signal?.aborted) return;
        const retryable =
          e instanceof IfseenConnectionError ||
          (e instanceof IfseenApiError && (e as { retryable?: boolean }).retryable === true) ||
          !(e instanceof IfseenApiError);
        if (!reconnect || !retryable) {
          if (e instanceof IfseenApiError || e instanceof IfseenConnectionError) throw e;
          throw new IfseenConnectionError(idled ? "event stream went idle" : "event stream dropped", { cause: e });
        }
        error = e;
      } finally {
        if (idleTimer !== undefined) clearTimeout(idleTimer);
        signal?.removeEventListener("abort", onAbort);
        controller.abort();
      }
      if (!reconnect) return;
      if (!clean) failures++;
      if (!(await backoff(error, clean))) return;
    }
  }

  /**
   * Call `handler` for every event of one kind (or `"*"` for all) until the returned
   * function is called. Runs the event stream in the background with auto-reconnect.
   *
   * ```ts
   * const off = client.on("fire", (e) => console.log(e.rule, e.probability), { watcher: "front-door" });
   * ```
   */
  on<K extends KnownEventKind | "*" | (string & {})>(
    kind: K,
    handler: (event: K extends "*" ? IfseenEvent : EventOfKind<K>) => void | Promise<void>,
    opts: OnOptions = {},
  ): () => void {
    const controller = new AbortController();
    const { onError = (e: unknown) => console.error("ifseen:", e), signal, ...rest } = opts;
    if (signal?.aborted) return () => {};
    signal?.addEventListener("abort", () => controller.abort(), { once: true });
    void (async () => {
      try {
        const iterable = this.events({
          ...rest,
          ...(kind === "*" ? {} : { types: [kind] }),
          signal: controller.signal,
        });
        for await (const event of iterable) {
          if (kind !== "*" && kindOf(event) !== kind) continue;
          try {
            await handler(event as never);
          } catch (e) {
            onError(e);
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) onError(e);
      }
    })();
    return () => controller.abort();
  }

  // -- plumbing -----------------------------------------------------------------------------

  #buildHeaders(extra: Record<string, string>): Record<string, string> {
    const headers: Record<string, string> = { ...this.#headers, ...extra };
    if (this.#token) headers.Authorization = `Bearer ${this.#token}`;
    return headers;
  }

  async #request(method: string, path: string, body: unknown, opts: RequestOptions): Promise<Response> {
    const { signal, cleanup, timedOut } = linkedSignal(opts.signal, this.#timeoutMs);
    try {
      let res: Response;
      try {
        res = await this.#fetch(`${this.baseUrl}${path}`, {
          method,
          headers: this.#buildHeaders(
            body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
          ),
          ...(body === undefined ? {} : { body: JSON.stringify(body) }),
          signal,
          cache: "no-store",
        });
      } catch (e) {
        if (opts.signal?.aborted) throw abortReason(opts.signal);
        throw new IfseenConnectionError(
          timedOut() ? `${method} ${path}: timed out` : `could not reach ${this.baseUrl}`,
          { cause: e },
        );
      }
      if (!res.ok) throw await toApiError(res);
      return res;
    } finally {
      cleanup();
    }
  }

  async #json<T>(method: string, path: string, body: unknown, opts: RequestOptions): Promise<T> {
    const res = await this.#request(method, path, body, opts);
    const text = await res.text();
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new IfseenApiError(res.status, "invalid_response", `${method} ${path}: response was not JSON`);
    }
  }
}

async function toApiError(res: Response): Promise<IfseenApiError> {
  let text = "";
  try {
    text = await res.text();
  } catch {
    // ignore: fall back to the status
  }
  try {
    const body = JSON.parse(text) as { error?: { code?: unknown; message?: unknown } };
    const err = body?.error;
    if (err && typeof err.code === "string") {
      return new IfseenApiError(res.status, err.code, typeof err.message === "string" ? err.message : err.code);
    }
  } catch {
    // not JSON (a proxy in between?)
  }
  return new IfseenApiError(res.status, `http_${res.status}`, `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ""}`);
}
