# ifseen HTTP API (v1)

`ifseen serve` runs a small local HTTP server: one-shot checks, long-running watchers and a
live Server-Sent Events stream. This document is the contract that clients (the TypeScript
client, the Home Assistant integration) implement.

```bash
ifseen serve                                   # http://127.0.0.1:8899, no auth, loopback only
ifseen serve doorbell rules.yaml               # also start watchers from recipes / files
ifseen serve --host 0.0.0.0 --token "$TOKEN"   # LAN access: a token is required
ifseen serve --dry-run                         # mock provider, actions printed not run
```

| flag | default | meaning |
|---|---|---|
| `--host` | `127.0.0.1` | interface to bind. Anything that isn't loopback requires a token |
| `--port` | `8899` | TCP port |
| `--token` | `$IFSEEN_TOKEN` | require `Authorization: Bearer <token>`. At least 16 characters |
| `--allow-shell` | off | accept `shell` actions in configs sent over HTTP |
| `--allow-custom-endpoints` | off | accept provider `base_url` / `api_key_env` over HTTP |
| `--dry-run` | off | every check and watcher uses the `mock` provider; actions are logged, not run |
| `FILE\|RECIPE ...` | | watchers started at boot; id = file stem / recipe name |

## Conventions

- Base path: `/v1`. All bodies are JSON (UTF-8) except the snapshot (JPEG) and the event
  stream (`text/event-stream`).
- **Every `POST` must send `Content-Type: application/json`**, even with an empty body
  (`start` / `stop`). Anything else gets `415`.
- Request bodies must have a `Content-Length` (no chunked uploads) and be at most 25 MB.
- Times are Unix epoch seconds (float, millisecond precision). Probabilities are 0-1.
- Watcher ids match `^[A-Za-z0-9_-]{1,64}$`.
- Responses carry `Cache-Control: no-store`. There are no CORS headers (see Security).

### Errors

Every error is a JSON body with a stable machine-readable `code`:

```json
{"error": {"code": "invalid_config", "message": "invalid config:\n  rules.0.threshold: threshold must be between 0 and 1 (exclusive)"}}
```

| status | code | when |
|---|---|---|
| 400 | `invalid_json` | body isn't a JSON object |
| 400 | `invalid_request` | missing / wrong-typed / unknown field, bad base64 |
| 400 | `invalid_config` | config or rules failed validation (message lists each problem) |
| 400 | `invalid_id` | watcher id doesn't match the pattern |
| 400 | `provider_unavailable` | no key for the provider, or it can't handle the input (e.g. audio) |
| 400 | `bad_request` | invalid `Content-Length` |
| 401 | `unauthorized` | token configured and missing / wrong |
| 403 | `bad_host` | no token configured and the `Host` header isn't loopback |
| 403 | `shell_not_allowed` | config has a `shell` action and the server lacks `--allow-shell` |
| 403 | `custom_endpoint_not_allowed` | provider `base_url` / `api_key_env` without `--allow-custom-endpoints` |
| 404 | `not_found` | unknown endpoint or watcher |
| 404 | `no_snapshot` | watcher hasn't captured an image yet |
| 405 | `method_not_allowed` | known path, wrong method |
| 409 | `already_exists` | watcher id taken |
| 409 | `too_many_watchers` | limit (32) reached |
| 411 | `length_required` | chunked request body |
| 413 | `payload_too_large` | body over 25 MB |
| 415 | `unsupported_media_type` | `POST` without `Content-Type: application/json` |
| 500 | `internal_error` | bug; message is only the exception class name |
| 502 | `provider_error` | the decision provider failed (network, 5xx, bad response) |

## Endpoints

### `GET /v1/health`

```json
{
  "ok": true,
  "version": "0.1.0",
  "api": "v1",
  "providers": ["gemini", "mock"],
  "default_provider": "gemini",
  "auth": false,
  "allow_shell": false,
  "dry_run": false
}
```

`providers` lists providers usable right now: one whose key is set (`gemini`, `jev`, `azure`,
`openai`), `local` if its dependencies are installed, and always `mock`. `ollama` and
`systemone` aren't listed since they need a model / `base_url`. `default_provider` is what
`"auto"` resolves to, or `null`. No key or secret is ever returned.

### `POST /v1/check`

One-shot: ask every rule about one image and/or audio clip. Same as `ifseen.check()`.

Request:

```json
{
  "image_base64": "/9j/4AAQSkZJRg...",
  "audio_base64": "UklGRi...",
  "rules": ["A parcel is on the doorstep.", "A person is visible."],
  "provider": "gemini",
  "model": "gemini-decision-1",
  "context": "Doorbell camera, front of the house."
}
```

| field | type | |
|---|---|---|
| `image_base64` | string | any format Pillow reads (JPEG, PNG, WebP...). A `data:...;base64,` prefix is accepted |
| `audio_base64` | string | PCM WAV. At least one of image / audio is required |
| `rules` | `string[]` or `{name: string \| RuleSpec}` | required, 1-1000. List items get slug names: `"A parcel is on the doorstep."` → `"a-parcel-is-on-the-doorstep"` |
| `provider` | string or object | optional, default `"auto"`. Object = YAML `provider:` shape, e.g. `{"name": "gemini", "resolution": "low"}` |
| `model` | string | optional model override |
| `context` | string | optional extra text sent with the capture |

`RuleSpec` = `{"when": string, "true_means"?: string, "false_means"?: string}`. Names match
`^[A-Za-z0-9_-]{1,64}$`.

Response `200`:

```json
{
  "probs": {"a-parcel-is-on-the-doorstep": 0.9612, "a-person-is-visible": 0.031},
  "tokens": 1350,
  "latency_ms": 412.7,
  "cost_usd": 0.000135,
  "provider": "gemini (gemini-decision-1)"
}
```

`probs` keys are in request order.

### `GET /v1/watchers`

```json
{"watchers": [WatcherState, ...]}
```

### `POST /v1/watchers`

The body is a rules-file config (exactly the YAML schema from the README, as JSON) plus two
optional control fields:

| field | type | |
|---|---|---|
| `id` | string | optional; generated (12 hex chars) if omitted |
| `start` | boolean | default `true`: start watching immediately |

```json
{
  "id": "front-door",
  "source": {"url": "http://frigate.local/api/front/latest.jpg"},
  "provider": {"name": "gemini", "resolution": "low"},
  "every": "2s",
  "rules": [
    {"name": "person", "when": "A person is at the front door.", "threshold": 0.85, "for": 2, "cooldown": "1m"},
    {"name": "parcel", "when": "A parcel has been left on the doorstep.", "then": [{"ntfy": {"topic": "my-topic"}}]}
  ]
}
```

Response `201` with a `Location: /v1/watchers/{id}` header and the `WatcherState`.

Differences from running the same file with `ifseen watch`:

- `${VAR}` references are **not** expanded (a client must not be able to read the server's
  environment). Send literal values.
- Rules without `then:` run **no** actions (the CLI would show a desktop notification).
  React to `fire` events instead.
- `shell` actions → `403 shell_not_allowed` unless `--allow-shell`. Note a bare string action
  that isn't an action name (`then: "echo hi"`) *is* a shell action.
- provider / prefilter-provider `base_url` or `api_key_env` → `403
  custom_endpoint_not_allowed` unless `--allow-custom-endpoints`.

Watchers live in memory only; they're gone when the server restarts.

### `GET /v1/watchers/{id}`

`WatcherState`:

```json
{
  "id": "front-door",
  "created": 1763560000.123,
  "running": true,
  "stop_reason": null,
  "error": null,
  "source": "url frigate.local/api/front/latest.jpg",
  "provider": "gemini (gemini-decision-1)",
  "every": 2.0,
  "rules": [
    {
      "name": "person",
      "when": "A person is at the front door.",
      "threshold": 0.85,
      "for": 2,
      "cooldown": 60.0,
      "prob": 0.912,
      "streak": 1,
      "armed": true,
      "fires": 3,
      "last_fired": 1763560321.5,
      "status": "confirming 1/2",
      "actions": [],
      "callbacks": 0
    }
  ],
  "stats": {
    "started": 1763560000.2,
    "ticks": 160,
    "calls": 41,
    "skipped": 119,
    "errors": 0,
    "input_tokens": 21320,
    "cost_usd": 0.002132,
    "cost_per_hour": 0.0237,
    "last_latency_ms": 388.1,
    "last_skip_reason": "unchanged",
    "prefilter_calls": 0,
    "prefiltered": 0,
    "last_prefilter_prob": null
  }
}
```

| field | |
|---|---|
| `running` | the watch loop is active |
| `stop_reason` | why the last run ended (see `stop` event), `null` if it never ran |
| `error` | message of the fatal error that ended the last run (bad key, missing camera...), else `null` |
| `source`, `provider` | human-readable descriptions; before the first start, just the configured kinds/names |
| `rules[].prob` | latest probability (0 before the first decision) |
| `rules[].streak` | consecutive ticks at/above threshold |
| `rules[].armed` | `false` after firing until the probability drops below threshold − hysteresis |
| `rules[].fires` | fires in the current run |
| `rules[].last_fired` | epoch time of the last fire in the current run, or `null` |
| `rules[].status` | `"idle"` (not started), `"watching"`, `"confirming N/M"`, `"fired, clearing"` |
| `rules[].actions` | action kinds from `then:` (destinations and options are never returned) |
| `stats` | `null` until the first start |

Rule state and stats reset every time the watcher starts. The config itself is never echoed
back, because it can contain webhook URLs, ntfy tokens and headers.

### `DELETE /v1/watchers/{id}`

Stops the watcher (waits up to 10 s for an in-flight provider call) and removes it.

```json
{"id": "front-door", "deleted": true}
```

### `POST /v1/watchers/{id}/start` · `POST /v1/watchers/{id}/stop`

Empty body (still with `Content-Type: application/json`). Both are idempotent and return the
`WatcherState`. `stop` waits up to 10 s for the loop to finish.

### `GET /v1/watchers/{id}/snapshot`

The latest captured frame as `image/jpeg` (resized so the long side is at most 1568 px).
`404 no_snapshot` before the first image or for audio-only sources. The last frame is kept
after the watcher stops. Suitable for a Home Assistant camera entity.

### `GET /v1/events`

A Server-Sent Events stream of engine events from all watchers.

| query | |
|---|---|
| `watcher` | only this watcher's events (`404` if it doesn't exist) |
| `types` | comma-separated event kinds, e.g. `types=fire,error,stop` |

```
retry: 3000
: connected

id: 17
event: decision
data: {"event": "decision", "watcher": "front-door", "time": 1763560321.4, "probs": {"person": 0.912}, "latency_ms": 388.1, "tokens": 520}

id: 18
event: fire
data: {"event": "fire", "watcher": "front-door", "time": 1763560321.5, "rule": "person", "when": "A person is at the front door.", "probability": 0.912}

: keep-alive
```

- `id` is a server-wide sequence number. `Last-Event-ID` replay is **not** supported: a
  reconnecting client should re-read `GET /v1/watchers` to resync state.
- A `: keep-alive` comment is sent after 15 s without events.
- A client that falls 1000 events behind is disconnected (reconnect to resume).
- The stream ends when the server shuts down.
- Browsers' `EventSource` can't send an `Authorization` header; with a token, use a
  fetch-based SSE reader.

#### Event schema

Every event has `event` (the kind), `watcher` (id) and `time`. The same dicts (minus
`watcher`) are what `Watcher.on_event` subscribers get in Python and what `ifseen ... --json`
prints.

| event | fields | |
|---|---|---|
| `start` | `source`, `provider`, `rules` (names), `prefilter`? | a run began |
| `decision` | `probs` `{rule: prob}`, `latency_ms`, `tokens`, `prefilter`?, `skipped`? | one model call. Unchanged/silent ticks that reuse the previous answer emit nothing; a prefilter-gated tick has `skipped: "prefilter"`, `prefilter: <prob>` and all-zero `probs` |
| `fire` | `rule`, `when`, `probability` | a rule fired (after threshold, `for`, cooldown, hysteresis) |
| `error` | `message`, `retry_in`?, `fatal`?, `origin`? | `retry_in`: provider error, backing off N s. `fatal: true`: the run is ending (a `stop` follows). `origin: "callback"`: a Python callback/listener raised |
| `log` | `level` (`info` \| `warn` \| `error` \| `dry`), `message` | output from actions (`log` action, action failures, dry-run lines). URLs and tokens are never included |
| `stop` | `reason` | the run ended. Exactly one per run |

`stop.reason` values: `"stopped"` (stop / delete / shutdown), `"done"` (tick limit),
`"rule '<name>' fired"` (an `exit` action), `"finished <file>"` (a file source ran out),
`"interrupted"` (Ctrl+C), `"error"` (after a fatal `error` event).

## Security

- **Loopback by default.** Without a token the server only binds loopback addresses and
  rejects requests whose `Host` header isn't `localhost` / `127.0.0.1` / `::1` (DNS-rebinding
  protection). Binding anything else without a token is refused at startup.
- **Token.** `--token` / `IFSEEN_TOKEN` (min 16 chars) protects every endpoint, compared in
  constant time. It's never logged or returned. Treat it like a password: anyone holding it
  can point ifseen at any camera, screen, file or URL the server can reach and read the frames
  back through `/snapshot`, and configure webhooks/ntfy pushes.
- **No CORS, JSON-only POSTs.** Other web pages can't read responses, and because every POST
  needs `Content-Type: application/json` they can't send simple cross-site form posts either.
- **Shell actions** in configs sent over HTTP are remote code execution, so they're rejected
  unless the server runs with `--allow-shell`. Watchers loaded from files on the command line
  are trusted and may use them.
- **Key exfiltration.** A config could set a provider `base_url` to a host the client controls
  and receive the server's API key, or use `api_key_env` to send any environment variable.
  Both are rejected unless `--allow-custom-endpoints`; `${VAR}` expansion is off for HTTP
  configs.
- Bodies are capped at 25 MB; at most 32 watchers.
- Request logs contain method, path and status only. Error messages never include keys,
  webhook URLs or ntfy topics.
