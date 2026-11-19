/** Base class for every error this package throws. */
export class IfseenError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = new.target.name;
  }
}

/** Bad input: rules, media or options. Nothing was sent. */
export class ConfigError extends IfseenError {}

/** A decision provider call failed (network, 5xx after retries, unexpected response). */
export class ProviderError extends IfseenError {
  /** Provider name, e.g. `"gemini"`. */
  readonly provider: string;
  /** HTTP status, if the provider answered. */
  readonly status: number | undefined;

  constructor(provider: string, message: string, status?: number, options?: { cause?: unknown }) {
    super(message, options);
    this.provider = provider;
    this.status = status;
  }
}

/** The provider rejected the API key (401 / 403, or Google's 400 `API_KEY_INVALID`). Not retried. */
export class AuthError extends ProviderError {}

/** Out of credits or billing disabled (402). Not retried. */
export class BillingError extends ProviderError {}

/** An error response from `ifseen serve`, with its stable machine-readable `code`. */
export class IfseenApiError extends IfseenError {
  /** HTTP status code. */
  readonly status: number;
  /** Error code from docs/api.md, e.g. `"invalid_config"`, `"not_found"`, `"unauthorized"`. */
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** `ifseen serve` couldn't be reached (connection refused, DNS, timeout, dropped stream). */
export class IfseenConnectionError extends IfseenError {}
