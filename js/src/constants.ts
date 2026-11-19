/** Package version, kept in sync with package.json. */
export const VERSION = "0.1.0";

export const GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/decisions";
export const GEMINI_DEFAULT_MODEL = "gemini-decision-1";
export const GEMINI_KEY_ENVS = ["GEMINI_API_KEY", "GOOGLE_API_KEY"] as const;

export const JEV_URL = "https://api.typesafe.ai/v1/systemone";
export const JEV_DEFAULT_MODEL = "jev-latest";
export const JEV_KEY_ENV = "TYPESAFE_API_KEY";
export const JEV_IMAGE_HEADER = "TypeSafe-Danger-Zone-Images";

export const AZURE_ENDPOINT_ENV = "AZURE_DECISION_ENDPOINT";
export const AZURE_KEY_ENV = "AZURE_DECISION_KEY";
export const AZURE_DEPLOYMENT_ENV = "AZURE_DECISION_DEPLOYMENT";
export const AZURE_PATH = "/providers/microsoft/v1/systemone";
export const AZURE_DEFAULT_MODEL = "Microsoft-Decision-1.1";

export const SYSTEMONE_PATH = "/v1/systemone";

/** USD per 1M input tokens. Output tokens are free on all decision models. */
export const PRICE_PER_M_INPUT = {
  gemini: 0.1,
  jev: 0.042,
  azure: 0.042,
  systemone: 0,
} as const;

/** Decision APIs accept at most this many questions per call. */
export const MAX_QUESTIONS = 1000;
export const RULE_NAME_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
export const WATCHER_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

/** System One (Jev / Azure) rejects images outside these bounds instead of resizing them. */
export const SYSTEMONE_IMAGE_MIN_SIDE = 280;
export const SYSTEMONE_IMAGE_MAX_SIDE = 1568;

export const HTTP_TIMEOUT_MS = 30_000;
export const RETRY_STATUSES: ReadonlySet<number> = new Set([429, 500, 502, 503, 504]);
export const MAX_ATTEMPTS = 3;
export const RETRY_BASE_DELAY_MS = 500;
/** Longest provider error text copied into an error message. */
export const ERROR_TEXT_LIMIT = 300;

export const SERVE_DEFAULT_URL = "http://127.0.0.1:8899";
/** Reconnect delay before the server has sent a `retry:` field. */
export const SSE_DEFAULT_RETRY_MS = 3000;
export const SSE_MAX_RETRY_MS = 30_000;
/** The server sends a keep-alive comment every 15 s; treat 45 s of silence as a dead stream. */
export const SSE_IDLE_TIMEOUT_MS = 45_000;
