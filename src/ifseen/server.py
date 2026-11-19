"""`ifseen serve`: a small local HTTP + Server-Sent Events API. See docs/api.md."""

from __future__ import annotations

import base64
import binascii
import hmac
import ipaddress
import json
import logging
import queue
import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .config import ConfigError, ProviderConfig, WatchConfig
from .constants import (
    SERVER_LOOPBACK_HOSTS,
    SERVER_MAX_BODY_BYTES,
    SERVER_MAX_WATCHERS,
    SERVER_MIN_TOKEN_LENGTH,
    SERVER_SSE_KEEPALIVE_SECONDS,
    SERVER_SSE_QUEUE_SIZE,
    VERSION,
    WATCHER_ID_PATTERN,
)
from .oneshot import check_detailed, make_sample, provider_config, statement_rules
from .providers import ProviderConfigError, ProviderError, available_providers
from .providers import detect_provider_name as _detect
from .watcher import Watcher

log = logging.getLogger("ifseen.server")

_ID = re.compile(WATCHER_ID_PATTERN)
_ROUTES: list[tuple[str, re.Pattern[str], str]] = [
    ("GET", re.compile(r"^/v1/health$"), "health"),
    ("POST", re.compile(r"^/v1/check$"), "check"),
    ("GET", re.compile(r"^/v1/events$"), "events"),
    ("GET", re.compile(r"^/v1/watchers$"), "list_watchers"),
    ("POST", re.compile(r"^/v1/watchers$"), "create_watcher"),
    ("GET", re.compile(r"^/v1/watchers/([^/]+)$"), "get_watcher"),
    ("DELETE", re.compile(r"^/v1/watchers/([^/]+)$"), "delete_watcher"),
    ("POST", re.compile(r"^/v1/watchers/([^/]+)/start$"), "start_watcher"),
    ("POST", re.compile(r"^/v1/watchers/([^/]+)/stop$"), "stop_watcher"),
    ("GET", re.compile(r"^/v1/watchers/([^/]+)/snapshot$"), "snapshot"),
]


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def is_loopback(host: str) -> bool:
    if host in SERVER_LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def check_untrusted(
    cfg: WatchConfig | None,
    providers: list[ProviderConfig],
    allow_shell: bool,
    allow_custom_endpoints: bool,
) -> None:
    """Reject the parts of a remotely submitted config that could run code or leak keys."""
    if cfg is not None:
        if not allow_shell:
            for rule in cfg.rules:
                if any("shell" in a for a in rule.then):
                    raise ApiError(
                        403,
                        "shell_not_allowed",
                        f"rule {rule.name!r} has a shell action; start the server with "
                        "--allow-shell to accept shell actions over the API",
                    )
        providers = [cfg.provider, *([cfg.prefilter.provider] if cfg.prefilter else [])]
    if not allow_custom_endpoints:
        for p in providers:
            if p.base_url or p.api_key_env:
                raise ApiError(
                    403,
                    "custom_endpoint_not_allowed",
                    "provider base_url / api_key_env could send this server's API keys "
                    "elsewhere; start the server with --allow-custom-endpoints to accept them",
                )


# -- events --------------------------------------------------------------------------------


class _Client:
    def __init__(self, watcher: str | None, kinds: frozenset[str] | None):
        self.watcher = watcher
        self.kinds = kinds
        self.queue: queue.Queue[tuple[int, dict[str, Any]] | None] = queue.Queue(
            SERVER_SSE_QUEUE_SIZE
        )
        self.lock = threading.Lock()

    def wants(self, event: dict[str, Any]) -> bool:
        if self.watcher is not None and event.get("watcher") != self.watcher:
            return False
        return self.kinds is None or event.get("event") in self.kinds

    def put(self, item: tuple[int, dict[str, Any]] | None) -> None:
        with self.lock:
            try:
                self.queue.put_nowait(item)
            except queue.Full:
                # too slow to keep up: end its stream so it reconnects instead of lagging
                while True:
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        break
                self.queue.put_nowait(None)


class EventHub:
    """Fans engine events out to every SSE client."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: set[_Client] = set()
        self._seq = 0

    def subscribe(self, watcher: str | None, kinds: frozenset[str] | None) -> _Client:
        client = _Client(watcher, kinds)
        with self._lock:
            self._clients.add(client)
        return client

    def unsubscribe(self, client: _Client) -> None:
        with self._lock:
            self._clients.discard(client)

    def publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            seq = self._seq
            clients = [c for c in self._clients if c.wants(event)]
        for c in clients:
            c.put((seq, event))

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients)
        for c in clients:
            c.put(None)


# -- watchers ------------------------------------------------------------------------------


@dataclass
class _Entry:
    id: str
    watcher: Watcher
    created: float = field(default_factory=time.time)

    def state(self) -> dict[str, Any]:
        state = self.watcher.state()
        state.pop("name", None)
        return {"id": self.id, "created": round(self.created, 3), **state}


class IfseenServer(ThreadingHTTPServer):
    """The HTTP server. Use :func:`make_server` to build one with the safety checks."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        token: str | None = None,
        allow_shell: bool = False,
        allow_custom_endpoints: bool = False,
        dry_run: bool = False,
        max_body: int = SERVER_MAX_BODY_BYTES,
        keepalive: float = SERVER_SSE_KEEPALIVE_SECONDS,
        max_watchers: int = SERVER_MAX_WATCHERS,
    ):
        super().__init__(address, _Handler)
        self.token = token
        self.allow_shell = allow_shell
        self.allow_custom_endpoints = allow_custom_endpoints
        self.dry_run = dry_run
        self.max_body = max_body
        self.keepalive = keepalive
        self.max_watchers = max_watchers
        self.hub = EventHub()
        self.closing = threading.Event()
        self._watchers: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        host = f"[{host}]" if ":" in str(host) else host
        return f"http://{host}:{port}"

    # -- registry --------------------------------------------------------------------------

    def add_watcher(
        self,
        data: dict[str, Any],
        watcher_id: str | None = None,
        *,
        trusted: bool = False,
        start: bool = True,
    ) -> _Entry:
        """Register a watcher from a config dict. Untrusted configs (HTTP) get no ${VAR}
        expansion, no default desktop notifications and the shell/endpoint checks."""
        if watcher_id is not None and not (isinstance(watcher_id, str) and _ID.match(watcher_id)):
            raise ApiError(400, "invalid_id", "id must be 1-64 letters, digits, '_' or '-'")
        watcher = Watcher.from_config(
            data,
            dry_run=self.dry_run,
            expand_env=trusted,
            notify_by_default=trusted,
        )
        cfg = watcher.config
        if not trusted:
            check_untrusted(cfg, [], self.allow_shell, self.allow_custom_endpoints)
        with self._lock:
            if len(self._watchers) >= self.max_watchers:
                raise ApiError(409, "too_many_watchers", f"at most {self.max_watchers} watchers")
            wid = watcher_id or uuid.uuid4().hex[:12]
            if wid in self._watchers:
                raise ApiError(409, "already_exists", f"watcher {wid!r} already exists")
            entry = _Entry(wid, watcher)
            watcher.name = wid
            self._watchers[wid] = entry
        watcher.on_event(self._forward(wid))
        if start:
            watcher.start()
        return entry

    def _forward(self, wid: str) -> Callable[[dict[str, Any]], None]:
        def forward(event: dict[str, Any]) -> None:
            self.hub.publish({"event": event["event"], "watcher": wid, **event})

        return forward

    def get(self, wid: str) -> _Entry:
        with self._lock:
            entry = self._watchers.get(wid)
        if entry is None:
            raise ApiError(404, "not_found", f"no watcher {wid!r}")
        return entry

    def entries(self) -> list[_Entry]:
        with self._lock:
            return list(self._watchers.values())

    def remove(self, wid: str) -> None:
        entry = self.get(wid)
        entry.watcher.stop(wait=True)
        with self._lock:
            self._watchers.pop(wid, None)

    def close(self) -> None:
        """Stop a server running `serve_forever` in another thread, its watchers and streams."""
        self.closing.set()
        self.shutdown()
        self.release()

    def release(self) -> None:
        """Stop every watcher, end SSE streams and close the socket (after serve_forever)."""
        self.closing.set()
        for entry in self.entries():
            entry.watcher.stop(wait=False)
        for entry in self.entries():
            entry.watcher.stop(wait=True)
        self.hub.close()
        self.server_close()


def make_server(
    host: str,
    port: int,
    *,
    token: str | None = None,
    allow_shell: bool = False,
    allow_custom_endpoints: bool = False,
    dry_run: bool = False,
    **kwargs: Any,
) -> IfseenServer:
    """Create (but don't start) a server. Refuses non-loopback hosts without a token."""
    if token is not None and len(token) < SERVER_MIN_TOKEN_LENGTH:
        raise ConfigError(f"--token must be at least {SERVER_MIN_TOKEN_LENGTH} characters")
    if not token and not is_loopback(host):
        raise ConfigError(
            f"refusing to listen on {host} without a token: anyone who can reach it could "
            "watch your camera/screen. Pass --token (or set IFSEEN_TOKEN), or use 127.0.0.1"
        )
    return IfseenServer(
        (host, port),
        token=token or None,
        allow_shell=allow_shell,
        allow_custom_endpoints=allow_custom_endpoints,
        dry_run=dry_run,
        **kwargs,
    )


# -- HTTP ----------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server: IfseenServer
    protocol_version = "HTTP/1.1"
    server_version = f"ifseen/{VERSION}"

    def log_message(self, format: str, *args: Any) -> None:
        log.info("%s %s", self.address_string(), format % args)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_DELETE(self) -> None:  # noqa: N802
        self._dispatch("DELETE")

    def do_PUT(self) -> None:  # noqa: N802
        self._dispatch("PUT")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._dispatch("OPTIONS")

    # -- plumbing --------------------------------------------------------------------------

    def _dispatch(self, method: str) -> None:
        self._body_read = False
        try:
            self._authorize()
            url = urlsplit(self.path)
            path = url.path.rstrip("/") or "/"
            allowed = []
            for route_method, pattern, name in _ROUTES:
                m = pattern.match(path)
                if not m:
                    continue
                if route_method != method:
                    allowed.append(route_method)
                    continue
                getattr(self, f"_h_{name}")(*m.groups(), query=parse_qs(url.query))
                return
            if allowed:
                raise ApiError(405, "method_not_allowed", f"use {' or '.join(allowed)}")
            raise ApiError(404, "not_found", "no such endpoint")
        except ApiError as e:
            self._error(e.status, e.code, e.message)
        except ConfigError as e:
            self._error(400, "invalid_config", str(e))
        except ProviderConfigError as e:
            self._error(400, "provider_unavailable", str(e))
        except ProviderError as e:
            self._error(502, "provider_error", str(e))
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception as e:  # never let one request take the server down
            log.exception("unhandled error on %s %s", method, urlsplit(self.path).path)
            self._error(500, "internal_error", type(e).__name__)

    def _authorize(self) -> None:
        token = self.server.token
        if token is None:
            # Without a token we only listen on loopback; also pin the Host header so a web
            # page can't reach us through DNS rebinding.
            host = (self.headers.get("Host") or "").strip()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host[1:].split("]")[0]
            if not is_loopback(name):
                raise ApiError(403, "bad_host", "Host header must be a loopback address")
            return
        header = self.headers.get("Authorization") or ""
        scheme, _, given = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            given.strip().encode(), token.encode()
        ):
            raise ApiError(401, "unauthorized", "missing or wrong bearer token")

    def _read_json(self, allow_empty: bool = False) -> dict[str, Any]:
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # also forces a CORS preflight, so other web pages can't POST to us
            raise ApiError(415, "unsupported_media_type", "send Content-Type: application/json")
        if self.headers.get("Transfer-Encoding"):
            raise ApiError(411, "length_required", "send Content-Length, not chunked bodies")
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as e:
            raise ApiError(400, "bad_request", "invalid Content-Length") from e
        if length < 0:
            raise ApiError(400, "bad_request", "invalid Content-Length")
        if length > self.server.max_body:
            raise ApiError(413, "payload_too_large", f"body is over {self.server.max_body} bytes")
        raw = self.rfile.read(length) if length else b""
        self._body_read = True
        if not raw:
            if allow_empty:
                return {}
            raise ApiError(400, "invalid_json", "expected a JSON object body")
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as e:
            raise ApiError(400, "invalid_json", "body is not valid JSON") from e
        if not isinstance(data, dict):
            raise ApiError(400, "invalid_json", "expected a JSON object body")
        return data

    def _drain_ok(self) -> bool:
        """True if the request body (if any) has been consumed, so keep-alive is safe."""
        if self._body_read:
            return True
        try:
            return int(self.headers.get("Content-Length") or 0) == 0 and not self.headers.get(
                "Transfer-Encoding"
            )
        except ValueError:
            return False

    def _send(self, status: int, body: bytes, ctype: str, headers: dict[str, str] | None = None):
        if not self._drain_ok():
            self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self.close_connection:
            self.send_header("Connection", "close")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: Any, headers: dict[str, str] | None = None) -> None:
        self._send(status, json.dumps(data).encode(), "application/json", headers)

    def _error(self, status: int, code: str, message: str) -> None:
        try:
            self._json(status, {"error": {"code": code, "message": message}})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # -- endpoints -------------------------------------------------------------------------

    def _h_health(self, query: dict[str, list[str]]) -> None:
        if self.server.dry_run:
            providers, default = ["mock"], "mock"
        else:
            providers = available_providers()
            try:
                default = _detect()
            except ProviderConfigError:
                default = None
        self._json(
            200,
            {
                "ok": True,
                "version": VERSION,
                "api": "v1",
                "providers": providers,
                "default_provider": default,
                "auth": self.server.token is not None,
                "allow_shell": self.server.allow_shell,
                "dry_run": self.server.dry_run,
            },
        )

    def _h_check(self, query: dict[str, list[str]]) -> None:
        body = self._read_json()
        unknown = set(body) - {
            "image_base64",
            "audio_base64",
            "rules",
            "provider",
            "model",
            "context",
        }
        if unknown:
            raise ApiError(400, "invalid_request", f"unknown fields {sorted(unknown)}")
        if "rules" not in body:
            raise ApiError(400, "invalid_request", "'rules' is required")
        rules = body["rules"]
        if not isinstance(rules, (list, dict)):
            raise ApiError(400, "invalid_request", "'rules' must be a list or an object")
        statement_rules(rules)
        image = _b64(body.get("image_base64"), "image_base64")
        audio = _b64(body.get("audio_base64"), "audio_base64")
        if image is None and audio is None:
            raise ApiError(400, "invalid_request", "send image_base64 and/or audio_base64")
        context = body.get("context")
        if context is not None and not isinstance(context, str):
            raise ApiError(400, "invalid_request", "'context' must be a string")
        model = body.get("model")
        if model is not None and not isinstance(model, str):
            raise ApiError(400, "invalid_request", "'model' must be a string")
        spec = "mock" if self.server.dry_run else body.get("provider") or "auto"
        if not isinstance(spec, (str, dict)):
            raise ApiError(400, "invalid_request", "'provider' must be a string or an object")
        pcfg = provider_config(spec, None if self.server.dry_run else model)
        check_untrusted(None, [pcfg], self.server.allow_shell, self.server.allow_custom_endpoints)
        make_sample(image, audio)  # validate media before spending a provider call
        result = check_detailed(image, rules, audio=audio, provider=pcfg, context=context)
        self._json(
            200,
            {
                "probs": {k: round(v, 4) for k, v in result.probs.items()},
                "tokens": result.input_tokens,
                "latency_ms": round(result.latency_ms, 1),
                "cost_usd": round(result.cost_usd, 8),
                "provider": result.provider,
            },
        )

    def _h_list_watchers(self, query: dict[str, list[str]]) -> None:
        self._json(200, {"watchers": [e.state() for e in self.server.entries()]})

    def _h_create_watcher(self, query: dict[str, list[str]]) -> None:
        body = self._read_json()
        wid = body.pop("id", None)
        start = body.pop("start", True)
        if not isinstance(start, bool):
            raise ApiError(400, "invalid_request", "'start' must be true or false")
        entry = self.server.add_watcher(body, wid, start=start)
        self._json(201, entry.state(), {"Location": f"/v1/watchers/{entry.id}"})

    def _h_get_watcher(self, wid: str, query: dict[str, list[str]]) -> None:
        self._json(200, self.server.get(wid).state())

    def _h_delete_watcher(self, wid: str, query: dict[str, list[str]]) -> None:
        self.server.remove(wid)
        self._json(200, {"id": wid, "deleted": True})

    def _h_start_watcher(self, wid: str, query: dict[str, list[str]]) -> None:
        self._read_json(allow_empty=True)
        entry = self.server.get(wid)
        if not entry.watcher.running:
            entry.watcher.start()
        self._json(200, entry.state())

    def _h_stop_watcher(self, wid: str, query: dict[str, list[str]]) -> None:
        self._read_json(allow_empty=True)
        entry = self.server.get(wid)
        entry.watcher.stop(wait=True)
        self._json(200, entry.state())

    def _h_snapshot(self, wid: str, query: dict[str, list[str]]) -> None:
        jpeg = self.server.get(wid).watcher.snapshot()
        if jpeg is None:
            raise ApiError(404, "no_snapshot", "no frame captured yet")
        self._send(200, jpeg, "image/jpeg")

    def _h_events(self, query: dict[str, list[str]]) -> None:
        wid = (query.get("watcher") or [None])[0]
        if wid is not None:
            self.server.get(wid)
        types = (query.get("types") or [None])[0]
        kinds = frozenset(t.strip() for t in types.split(",") if t.strip()) if types else None
        client = self.server.hub.subscribe(wid, kinds)
        self.close_connection = True
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self._write(b"retry: 3000\n: connected\n\n")
            while not self.server.closing.is_set():
                try:
                    item = client.queue.get(timeout=self.server.keepalive)
                except queue.Empty:
                    self._write(b": keep-alive\n\n")
                    continue
                if item is None:
                    break
                seq, event = item
                frame = f"id: {seq}\nevent: {event['event']}\ndata: {json.dumps(event)}\n\n"
                self._write(frame.encode())
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.server.hub.unsubscribe(client)

    def _write(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()


def _b64(value: Any, name: str) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(400, "invalid_request", f"'{name}' must be a base64 string")
    if value.startswith("data:"):
        value = value.split(",", 1)[-1]
    try:
        return base64.b64decode("".join(value.split()), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ApiError(400, "invalid_request", f"'{name}' is not valid base64") from e


def serve(
    host: str,
    port: int,
    *,
    token: str | None = None,
    allow_shell: bool = False,
    allow_custom_endpoints: bool = False,
    dry_run: bool = False,
    preload: list[tuple[str, dict[str, Any]]] | None = None,
    on_ready: Callable[[IfseenServer], None] | None = None,
) -> int:
    """Run the server until Ctrl+C. `preload` = (id, config) pairs from local files (trusted)."""
    server = make_server(
        host,
        port,
        token=token,
        allow_shell=allow_shell,
        allow_custom_endpoints=allow_custom_endpoints,
        dry_run=dry_run,
    )
    try:
        for wid, data in preload or []:
            server.add_watcher(data, wid, trusted=True)
        if on_ready is not None:
            on_ready(server)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.release()
    return 0
