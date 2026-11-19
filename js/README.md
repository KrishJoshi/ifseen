# ifseen (TypeScript / JavaScript)

**If seen (or heard), then do.** The official JS package for [ifseen](https://github.com/KrishJoshi/ifseen):

1. **Direct one-shot checks**: ask a decision model (Gemini Decision 1, TypeSafe Jev,
   Microsoft-Decision on Azure, or a self-hosted System One server) how likely each
   plain-English statement is for an image. No Python needed.
2. **`IfseenClient`** for [`ifseen serve`](../docs/api.md): one-shot checks with the server's
   key, long-running watchers on cameras / screens / snapshot URLs, the latest frame, and a
   live event stream (`start` / `decision` / `fire` / `clear` / `error` / `stop` ...).

Zero runtime dependencies. ESM with types. Works in Node 18+, Bun, Deno
and browsers (it only needs `fetch`, `TextDecoder` and `AbortController`).

```bash
npm install ifseen
```

## Quick start: direct checks (server-side)

```ts
import { check, checkDetailed } from "ifseen";

// GEMINI_API_KEY is read from the environment (or pass apiKey)
const probs = await check("door.jpg", ["A parcel is on the doorstep.", "A person is visible."]);
// { "a-parcel-is-on-the-doorstep": 0.96, "a-person-is-visible": 0.03 }

const result = await checkDetailed(
  imageBytes,                                      // Uint8Array | ArrayBuffer | Blob | base64 | path
  {
    parcel: "A parcel is on the doorstep.",        // your own names
    person: { when: "A person is at the door.", falseMeans: "A poster or reflection." },
  },
  { provider: "jev", apiKey: process.env.TYPESAFE_API_KEY, context: "Doorbell camera." },
);
// { probs: {...}, tokens: 300, latencyMs: 412, model: "jev-latest", provider: "jev (jev-latest)", costUsd: 0.0000126 }
```

> **Don't call providers from a browser.** `check()` sends your provider API key with the
> request, so in a web page anyone can read it from DevTools. For web apps, run
> `ifseen serve` (or your own backend) and use `IfseenClient`, which never sees a provider key.

### Deno

```ts
import { check } from "npm:ifseen";
const probs = await check(await Deno.readFile("door.jpg"), ["A parcel is on the doorstep."], {
  apiKey: Deno.env.get("GEMINI_API_KEY"),
});
```

File-path strings need `node:fs` (Node, Bun, Deno with `--allow-read`); everywhere else pass
bytes, a `Blob` or base64.

## Quick start: `ifseen serve`

```bash
ifseen serve                      # http://127.0.0.1:8899, loopback only, no auth
ifseen serve --dry-run            # mock provider: try everything without a key
```

```ts
import { IfseenClient } from "ifseen";

const client = new IfseenClient(); // { baseUrl: "http://127.0.0.1:8899", token? }

await client.createWatcher({
  id: "front-door",
  source: { url: "http://frigate.local/api/front/latest.jpg" },
  provider: { name: "gemini", resolution: "low" },
  every: "2s",
  rules: [{ name: "person", when: "A person is at the front door.", threshold: 0.85, for: 2, cooldown: "1m" }],
});

// Every fire, until you call off(). Reconnects on its own.
const off = client.on("fire", async (e) => {
  console.log(e.watcher, e.rule, e.probability);
  const jpeg = await client.snapshot(e.watcher); // Uint8Array
}, { watcher: "front-door" });

// Or iterate the stream yourself
const controller = new AbortController();
for await (const event of client.events({ types: ["decision", "fire"], signal: controller.signal })) {
  if (event.event === "decision") console.log(event.probs);
}
```

### From a browser (via `ifseen serve`)

`ifseen serve` sends no CORS headers and checks the `Host` header, so a page on another
origin can't call it directly. Serve your page from the same origin (a reverse proxy that
forwards `/v1/*` to ifseen), or call it from your backend. With `--token`, keep the token on
the server side too: anyone holding it can point ifseen at any camera or URL it can reach.

```ts
const client = new IfseenClient({ baseUrl: "/ifseen" }); // same-origin proxy path
const off = client.on("fire", (e) => showToast(`${e.rule} (${Math.round(e.probability * 100)}%)`));
```

## API

### `check(image, statements, options?)` → `Promise<Record<string, number>>`
### `checkDetailed(image, statements, options?)` → `Promise<CheckResult>`

- `image`: `Uint8Array` / `ArrayBuffer` / any `ArrayBufferView` (Node `Buffer`) / `Blob` /
  base64 string / `data:` URL / file path / `{ path }` / `{ base64 }`, or `null` with `audio`.
  JPEG or PNG, detected from magic bytes and sent as-is (no resizing). Jev / Azure only accept
  280-1568 px per side; a clear `ConfigError` is thrown before sending otherwise.
- `statements`: a string, a list (names become slugs exactly like the Python package:
  `"A parcel is on the doorstep."` → `"a-parcel-is-on-the-doorstep"`, duplicates get `-2`),
  or `{ name: statement | { when, trueMeans?, falseMeans? } }`. 1-1000 per call.
- `options`:

| option | |
|---|---|
| `provider` | `"gemini"` (default) · `"jev"` · `"azure"` · `"systemone"` |
| `apiKey` | default from `GEMINI_API_KEY` / `GOOGLE_API_KEY`, `TYPESAFE_API_KEY`, `AZURE_DECISION_KEY` when `process.env` / `Deno.env` exists |
| `model` | default `gemini-decision-1`, `jev-latest`, `$AZURE_DECISION_DEPLOYMENT` or `Microsoft-Decision-1.1` |
| `baseUrl` | endpoint override for proxies and tests. gemini / jev: the full URL. azure: the Foundry resource endpoint (`$AZURE_DECISION_ENDPOINT`), `/providers/microsoft/v1/systemone` is appended. systemone: server base URL, `/v1/systemone` appended |
| `audio` | a PCM WAV clip (Gemini only) |
| `context` | extra text sent with the capture |
| `resolution` | Gemini: `"low"` / `"medium"` / `"high"` (low is ~2.5x cheaper) |
| `headers`, `label` | extra request headers; capture label used in the prompt |
| `signal`, `timeoutMs` | abort / per-attempt timeout (default 30 s) |
| `maxAttempts`, `retryDelayMs` | network errors, 429 and 5xx are retried: 3 attempts, 0.5 s then 1 s |
| `fetch` | custom fetch implementation |

`CheckResult` = `{ probs, tokens, latencyMs, model, provider, costUsd }` (`probs` in statement order).

Errors: `ConfigError` (bad input, nothing sent) · `AuthError` (401 / 403, or Google's 400
`API_KEY_INVALID`) · `BillingError` (402) · `ProviderError` (network, 5xx after retries, bad
response; has `.provider` and `.status`). `AuthError` and `BillingError` extend
`ProviderError`; all extend `IfseenError`. API keys are never included in messages.

### `new IfseenClient({ baseUrl?, token?, fetch?, timeoutMs?, headers? })`

| method | endpoint | returns |
|---|---|---|
| `health()` | `GET /v1/health` | `HealthResponse` |
| `check(image, statements, { audio?, provider?, model?, context? })` | `POST /v1/check` | `{ probs, tokens, latencyMs, costUsd, provider }` |
| `listWatchers()` | `GET /v1/watchers` | `WatcherState[]` |
| `createWatcher(config)` | `POST /v1/watchers` | `WatcherState` |
| `getWatcher(id)` | `GET /v1/watchers/{id}` | `WatcherState` |
| `deleteWatcher(id)` | `DELETE /v1/watchers/{id}` | `{ id, deleted: true }` |
| `startWatcher(id)` / `stopWatcher(id)` | `POST /v1/watchers/{id}/start` · `/stop` | `WatcherState` |
| `snapshot(id)` | `GET /v1/watchers/{id}/snapshot` | `Uint8Array` (JPEG) |
| `events({ watcher?, types?, signal?, ... })` | `GET /v1/events` | `AsyncIterableIterator<IfseenEvent>` |
| `on(kind \| "*", handler, { watcher?, signal?, onError?, ... })` | `GET /v1/events` | `() => void` (unsubscribe) |

Every method takes an optional `{ signal }`. `WatcherConfig` is the rules-file schema from the
main README as JSON (snake_case, like the YAML), plus `id` and `start`. Errors from the server
are `IfseenApiError` with `.status` and the stable `.code` from docs/api.md (`invalid_config`,
`not_found`, `unauthorized`, `shell_not_allowed`, ...); an unreachable server is
`IfseenConnectionError`.

`IfseenEvent` is a discriminated union on `event`: `start`, `decision`, `fire`, `clear`,
`error`, `log`, `pause`, `resume`, `stop`. Each has `watcher`, `time` (epoch seconds) and
`seq` (the SSE id). Event kinds added by a newer server arrive as
`{ event: "unknown", kind, payload }` instead of being dropped or throwing.

### How the event stream works

`events()` reads `text/event-stream` with `fetch` and a streaming parser rather than
`EventSource`, because `EventSource` can't send an `Authorization` header. The connection is
opened when you start iterating.

- **Reconnects** when the stream ends (server restart, or the client fell 1000 events behind)
  after the server's `retry:` delay (3 s), and on network errors / 5xx with exponential
  backoff up to `maxRetryDelayMs` (30 s), with jitter. 401 / 404 are thrown, not retried.
- **Keep-alives**: the server sends a `: keep-alive` comment every 15 s; if nothing at all
  arrives for `idleTimeoutMs` (45 s) the connection is treated as dead and reopened.
- **No replay**: the server doesn't support `Last-Event-ID`. Use `onOpen({ reconnect })` to
  resync with `listWatchers()` after a reconnect. `onDisconnect({ error, retryInMs })` reports
  drops.
- Abort `signal` or `break` out of the loop to close the connection; neither throws.
- The parser (`SseParser`, exported) follows the WHATWG spec: multi-line `data:`, CR / LF /
  CRLF line endings split across chunks, comments, BOM, and UTF-8 characters split across
  network chunks.

## Security notes

- **Provider keys belong on a server.** Direct `check()` calls send the key in a header
  (`x-goog-api-key`, `Authorization: Bearer`, `api-key`). Use them in Node / Bun / Deno /
  workers, never in code shipped to browsers.
- `ifseen serve` binds to loopback without a token and refuses other hosts. For LAN access
  run it with `--token` (16+ chars) and pass the same `token` to `IfseenClient`; treat the token
  like a password.
- Configs sent over HTTP can't use `shell` actions (`403 shell_not_allowed`), an `mqtt` section (`403 mqtt_not_allowed`) or custom provider
  `base_url` / `api_key_env` (`403 custom_endpoint_not_allowed`) unless the server opts in, and
  `${VAR}` isn't expanded.
- Error messages never include API keys; provider error text is redacted before it's thrown.

## Development

```bash
cd js
npm install
npm run typecheck   # src + tests + examples
npm run build       # dist/ (ESM + .d.ts)
npm test            # unit + integration (node --test)
```

The integration tests spawn the Python `ifseen serve --dry-run` and `tests/fake_server.py`
from the repo's `.venv` (override with `IFSEEN_BIN` / `IFSEEN_PYTHON`) and are skipped if they
aren't there. They make no network calls beyond 127.0.0.1.

### CI

```yaml
  js:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        node: [18, 20, 22]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m venv .venv && .venv/bin/pip install -e .
      - uses: actions/setup-node@v4
        with:
          node-version: ${{ matrix.node }}
      - working-directory: js
        run: |
          npm install
          npm run typecheck
          npm run build
          npm test
```

## License

MIT
