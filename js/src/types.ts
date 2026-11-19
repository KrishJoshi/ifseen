/**
 * Types for the `ifseen serve` HTTP API (docs/api.md). Field names are the wire names
 * (snake_case), so they match the YAML rule files and the JSON you see with curl.
 */

/** A duration: seconds as a number, or a string like `"2s"`, `"500ms"`, `"1m"`, `"15m"`. */
export type Duration = number | string;

// -- config ---------------------------------------------------------------------------------

export type ProviderKind = "auto" | "gemini" | "jev" | "azure" | "systemone" | "openai" | "ollama" | "local" | "mock";

export interface ProviderConfigObject {
  name: ProviderKind | (string & {});
  model?: string;
  /** gemini: `"low"` / `"medium"` / `"high"`. */
  resolution?: "low" | "medium" | "high";
  /** Rejected (403 `custom_endpoint_not_allowed`) unless the server runs with `--allow-custom-endpoints`. */
  base_url?: string;
  /** Rejected (403 `custom_endpoint_not_allowed`) unless the server runs with `--allow-custom-endpoints`. */
  api_key_env?: string;
  headers?: Record<string, string>;
  seed?: number;
  [key: string]: unknown;
}

export type ProviderConfig = ProviderKind | (string & {}) | ProviderConfigObject;

export interface ScreenSourceObject {
  monitor?: number;
  region?: [number, number, number, number];
}
export interface UrlSourceObject {
  url: string;
  headers?: Record<string, string>;
}
export interface FileSourceObject {
  path: string;
  realtime?: boolean;
  loop?: boolean;
}
export interface MicSourceObject {
  seconds?: number;
  [key: string]: unknown;
}

/** `source:` from the rules file: one visual source and/or a mic. */
export interface SourceConfig {
  /** Monitor number (0 = all) or `{ monitor, region: [x, y, w, h] }`. */
  screen?: number | ScreenSourceObject;
  /** Webcam index or an `rtsp://` URL. */
  camera?: number | string | { [key: string]: unknown };
  /** Snapshot URL. */
  url?: string | UrlSourceObject;
  /** Image, `.wav` or video path on the server's machine. */
  file?: string | FileSourceObject;
  /** Last N seconds of audio each tick (Gemini only). */
  mic?: boolean | number | MicSourceObject;
  [key: string]: unknown;
}

/** An action under `then:`. A bare string is an action name (`"notify"`, `"exit"`...) or else a shell command. */
export type ActionConfig =
  | "notify"
  | "log"
  | "exit"
  | "snapshot"
  | "say"
  | (string & {})
  | { notify: string | Record<string, unknown> }
  | { say: string | Record<string, unknown> }
  | { shell: string | Record<string, unknown> }
  | { webhook: string | { url: string; image?: boolean; headers?: Record<string, string>; [key: string]: unknown } }
  | { ntfy: string | { topic: string; priority?: string; server?: string; [key: string]: unknown } }
  | { snapshot: string | Record<string, unknown> }
  | { log: string | Record<string, unknown> }
  | { exit: unknown }
  | Record<string, unknown>;

/** A rule in a watcher config (rules-file schema). */
export interface Rule {
  /** Required. 1-64 letters, digits, `-` and `_`. */
  name: string;
  when: string;
  true_means?: string;
  false_means?: string;
  /** Probability needed to count as a hit, 0-1 exclusive. Default 0.8. */
  threshold?: number;
  /** Consecutive hits before firing. Default 1. */
  for?: number;
  /** Minimum time between fires. Default 30 s. */
  cooldown?: Duration;
  /** Re-arm once the probability drops below threshold − hysteresis. Default 0.15. */
  hysteresis?: number;
  /** Actions. Without `then:`, HTTP-created rules run none: react to `fire` events instead. */
  then?: ActionConfig | ActionConfig[];
  [key: string]: unknown;
}

export interface PrefilterConfig {
  provider: ProviderConfig;
  when: string;
  threshold?: number;
}

/** The body of `POST /v1/watchers`: a rules-file config as JSON, plus `id` and `start`. */
export interface WatcherConfig {
  /** Optional; 12 hex chars are generated if omitted. Must match `^[A-Za-z0-9_-]{1,64}$`. */
  id?: string;
  /** Start watching immediately. Default `true`. */
  start?: boolean;
  source: SourceConfig | string;
  provider?: ProviderConfig;
  /** How often to look (min 100 ms). Default 2 s. */
  every?: Duration;
  skip_unchanged?: boolean;
  change_threshold?: number;
  max_skip?: Duration;
  context?: string;
  prefilter?: PrefilterConfig;
  /**
   * Home Assistant MQTT discovery (see docs/homeassistant.md). Rejected over HTTP
   * (403 `mqtt_not_allowed`) unless the server runs with `--allow-custom-endpoints`.
   */
  mqtt?: Record<string, unknown>;
  rules: Rule[];
  [key: string]: unknown;
}

// -- state ----------------------------------------------------------------------------------

export interface RuleState {
  name: string;
  when: string;
  threshold: number;
  for: number;
  cooldown: number;
  /** Latest probability (0 before the first decision). */
  prob: number;
  /** Consecutive ticks at/above threshold. */
  streak: number;
  /** `false` after firing until the probability drops below threshold − hysteresis. */
  armed: boolean;
  /** `true` from a fire until it re-arms, i.e. `!armed` (ended by a `clear` event). */
  active: boolean;
  /** Fires in the current run. */
  fires: number;
  last_fired: number | null;
  /** `"idle"`, `"watching"`, `"confirming N/M"`, `"fired, clearing"`. */
  status: string;
  /** Action kinds from `then:` (destinations and options are never returned). */
  actions: string[];
  callbacks: number;
  [key: string]: unknown;
}

export interface WatcherStats {
  started: number;
  ticks: number;
  calls: number;
  skipped: number;
  errors: number;
  input_tokens: number;
  cost_usd: number;
  cost_per_hour: number;
  last_latency_ms: number | null;
  last_skip_reason: string | null;
  prefilter_calls: number;
  prefiltered: number;
  last_prefilter_prob: number | null;
  [key: string]: unknown;
}

/** `GET /v1/watchers/{id}`. The config itself is never echoed back. */
export interface WatcherState {
  id: string;
  created: number;
  /** The watch loop is active. */
  running: boolean;
  /** Paused (Python `Watcher.pause()` or the Home Assistant switch): no captures, no calls. */
  paused: boolean;
  /** Why the last run ended (see the `stop` event), `null` if it never ran. */
  stop_reason: string | null;
  /** Message of the fatal error that ended the last run, else `null`. */
  error: string | null;
  source: string;
  provider: string;
  every: number;
  rules: RuleState[];
  /** `null` until the first start. */
  stats: WatcherStats | null;
  [key: string]: unknown;
}

export interface HealthResponse {
  ok: boolean;
  version: string;
  api: string;
  providers: string[];
  default_provider: string | null;
  auth: boolean;
  allow_shell: boolean;
  dry_run: boolean;
  [key: string]: unknown;
}

/** `POST /v1/check` response, camelCased. */
export interface ServeCheckResult {
  probs: Record<string, number>;
  tokens: number;
  latencyMs: number;
  costUsd: number;
  provider: string;
}

export interface DeleteWatcherResponse {
  id: string;
  deleted: true;
}

// -- events ---------------------------------------------------------------------------------

interface EventBase {
  /** Watcher id. */
  watcher: string;
  /** Unix epoch seconds. */
  time: number;
  /** Server-wide SSE sequence number (`id:`), when known. Not part of the JSON payload. */
  seq?: number;
}

/** A run began. */
export interface StartEvent extends EventBase {
  event: "start";
  source: string;
  provider: string;
  /** Rule names. */
  rules: string[];
  prefilter?: unknown;
}

/** One model call (or a prefilter-gated tick with `skipped: "prefilter"` and all-zero probs). */
export interface DecisionEvent extends EventBase {
  event: "decision";
  probs: Record<string, number>;
  latency_ms: number;
  tokens: number;
  prefilter?: number;
  skipped?: string;
}

/** A rule fired (after threshold, `for`, cooldown, hysteresis). */
export interface FireEvent extends EventBase {
  event: "fire";
  rule: string;
  when: string;
  probability: number;
}

/** A fired rule re-armed (probability fell below threshold − hysteresis); it's no longer `active`. */
export interface ClearEvent extends EventBase {
  event: "clear";
  rule: string;
  probability: number;
}

export interface ErrorEvent extends EventBase {
  event: "error";
  message: string;
  /** Provider error, backing off this many seconds. */
  retry_in?: number;
  /** The run is ending; a `stop` follows. */
  fatal?: boolean;
  /** `"callback"`: a Python callback/listener raised. `"observer"`: an integration such as MQTT failed. */
  origin?: "callback" | "observer" | (string & {});
}

/** Output from actions. URLs and tokens are never included. */
export interface LogEvent extends EventBase {
  event: "log";
  level: "info" | "warn" | "error" | "dry" | (string & {});
  message: string;
}

/** The watcher was paused; while paused no ticks run. */
export interface PauseEvent extends EventBase {
  event: "pause";
}

/** The watcher was resumed. */
export interface ResumeEvent extends EventBase {
  event: "resume";
}

/** The run ended. Exactly one per run. */
export interface StopEvent extends EventBase {
  event: "stop";
  /** `"stopped"`, `"done"`, `"rule '<name>' fired"`, `"finished <file>"`, `"interrupted"`, `"error"`. */
  reason: string;
}

/** Every event kind this version knows about. */
export type KnownEvent =
  | StartEvent
  | DecisionEvent
  | FireEvent
  | ClearEvent
  | ErrorEvent
  | LogEvent
  | PauseEvent
  | ResumeEvent
  | StopEvent;

export type KnownEventKind = KnownEvent["event"];

/**
 * An event kind added by a newer server than this client knows. It is passed through rather
 * than dropped or thrown on: `kind` is the server's `event` value and `payload` the full JSON.
 */
export interface UnknownEvent extends EventBase {
  event: "unknown";
  kind: string;
  payload: Record<string, unknown>;
}

/** An engine event from `GET /v1/events`: a discriminated union on `event`. */
export type IfseenEvent = KnownEvent | UnknownEvent;

export type EventOfKind<K extends string> = K extends KnownEventKind ? Extract<KnownEvent, { event: K }> : UnknownEvent;
