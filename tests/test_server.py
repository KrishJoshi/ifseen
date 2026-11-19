from __future__ import annotations

import base64
import json
import threading
import time
from contextlib import contextmanager

import httpx
import pytest

from ifseen.cli import main
from ifseen.config import ConfigError
from ifseen.server import make_server

TOKEN = "s3cret-token-for-tests"


@contextmanager
def running(**kw):
    srv = make_server("127.0.0.1", 0, **kw)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=srv.url, timeout=10) as client:
            yield srv, client
    finally:
        srv.close()


@pytest.fixture
def gemini_env(fake_server, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    for k in ("GOOGLE_API_KEY", "TYPESAFE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return {"name": "gemini", "base_url": f"{fake_server.url}/v1beta/decisions"}


def watcher_config(path, provider, **extra):
    return {
        "source": {"file": str(path)},
        "provider": provider,
        "every": "100ms",
        "rules": [{"name": "red", "when": "The image is mostly red.", "cooldown": 0}],
        **extra,
    }


def post(client, url, body=None, **kw):
    return client.post(url, json=body if body is not None else {}, **kw)


class SSE:
    """Reads an event stream in a background thread."""

    def __init__(self, base_url: str, query: str = "", headers=None):
        self.lines: list[str] = []
        self.events: list[dict] = []
        self.connected = threading.Event()
        self.status: int | None = None
        self._client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10, read=None))
        self._thread = threading.Thread(target=self._run, args=(query, headers), daemon=True)
        self._thread.start()
        assert self.connected.wait(5)

    def _run(self, query, headers):
        try:
            with self._client.stream("GET", f"/v1/events{query}", headers=headers) as r:
                self.status = r.status_code
                self.connected.set()
                for line in r.iter_lines():
                    self.lines.append(line)
                    if line.startswith("data: "):
                        self.events.append(json.loads(line[6:]))
        except httpx.HTTPError:
            pass
        finally:
            self.connected.set()

    def wait_for(self, pred, timeout=8.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for e in list(self.events):
                if pred(e):
                    return e
            time.sleep(0.02)
        raise AssertionError(f"event not seen; got {[e['event'] for e in self.events]}")

    def close(self):
        self._client.close()


def test_health():
    with running() as (srv, client):
        r = client.get("/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] and body["api"] == "v1" and body["version"]
        assert "mock" in body["providers"]
        assert body["auth"] is False and body["allow_shell"] is False


def test_check_against_fake_gemini(gemini_env, red_png):
    image = base64.b64encode(red_png.read_bytes()).decode()
    with running(allow_custom_endpoints=True) as (srv, client):
        r = post(
            client,
            "/v1/check",
            {
                "image_base64": image,
                "rules": {"red": "The image is mostly red.", "green": "The image is mostly green."},
                "provider": gemini_env,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["probs"]["red"] > 0.9 and body["probs"]["green"] < 0.1
        assert body["tokens"] > 0 and body["latency_ms"] >= 0
        assert body["provider"].startswith("gemini")
        assert "test-key" not in r.text

        r = post(
            client,
            "/v1/check",
            {
                "image_base64": f"data:image/png;base64,{image}",
                "rules": ["A red image."],
                "provider": gemini_env,
            },
        )
        assert r.status_code == 200
        assert list(r.json()["probs"]) == ["a-red-image"]


def test_check_validation(red_png, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    image = base64.b64encode(red_png.read_bytes()).decode()
    with running() as (srv, client):

        def code(body):
            r = post(client, "/v1/check", body)
            return r.status_code, r.json()["error"]["code"]

        assert code({"image_base64": image}) == (400, "invalid_request")
        assert code({"rules": ["x"]}) == (400, "invalid_request")
        assert code({"image_base64": "!!!", "rules": ["x"]}) == (400, "invalid_request")
        assert code({"image_base64": image, "rules": ["x"], "extra": 1}) == (
            400,
            "invalid_request",
        )
        assert code({"image_base64": image, "rules": {"bad name": "x"}}) == (400, "invalid_config")
        assert code({"image_base64": base64.b64encode(b"nope").decode(), "rules": ["x"]}) == (
            400,
            "invalid_config",
        )
        assert code({"image_base64": image, "rules": ["x"], "provider": "jev"})[0] == 400
        r = client.post(
            "/v1/check", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_json"
        r = client.post("/v1/check", content=b"[]", headers={"Content-Type": "application/json"})
        assert r.json()["error"]["code"] == "invalid_json"
        # form posts (what a malicious web page could send) are refused
        r = client.post("/v1/check", content=b"{}", headers={"Content-Type": "text/plain"})
        assert r.status_code == 415


def test_custom_endpoints_need_opt_in(gemini_env, red_png):
    image = base64.b64encode(red_png.read_bytes()).decode()
    with running() as (srv, client):
        r = post(
            client, "/v1/check", {"image_base64": image, "rules": ["x"], "provider": gemini_env}
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "custom_endpoint_not_allowed"
        r = post(
            client,
            "/v1/check",
            {
                "image_base64": image,
                "rules": ["x"],
                "provider": {"name": "gemini", "api_key_env": "HOME"},
            },
        )
        assert r.status_code == 403
        r = post(client, "/v1/watchers", watcher_config(red_png, gemini_env))
        assert r.status_code == 403


def test_body_limit():
    with running(max_body=1000) as (srv, client):
        r = post(client, "/v1/check", {"image_base64": "A" * 2000, "rules": ["x"]})
        assert r.status_code == 413
        assert r.json()["error"]["code"] == "payload_too_large"
        assert client.get("/v1/health").status_code == 200


def test_token_auth():
    with running(token=TOKEN) as (srv, client):
        assert client.get("/v1/health").status_code == 401
        bad = client.get("/v1/health", headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401 and bad.json()["error"]["code"] == "unauthorized"
        assert TOKEN not in bad.text
        assert (
            client.get("/v1/watchers", headers={"Authorization": f"Basic {TOKEN}"}).status_code
            == 401
        )
        ok = client.get("/v1/health", headers={"Authorization": f"Bearer {TOKEN}"})
        assert ok.status_code == 200 and ok.json()["auth"] is True
        assert TOKEN not in ok.text
        # with a token, any Host header is fine
        r = client.get(
            "/v1/health", headers={"Authorization": f"Bearer {TOKEN}", "Host": "box.lan"}
        )
        assert r.status_code == 200


def test_host_header_pinned_without_token():
    with running() as (srv, client):
        assert client.get("/v1/health", headers={"Host": "evil.example"}).status_code == 403
        assert client.get("/v1/health", headers={"Host": "localhost:8899"}).status_code == 200
        assert client.get("/v1/health", headers={"Host": "[::1]:8899"}).status_code == 200


def test_refuses_unsafe_listen_configs():
    with pytest.raises(ConfigError, match="without a token"):
        make_server("0.0.0.0", 0)
    with pytest.raises(ConfigError, match="at least"):
        make_server("127.0.0.1", 0, token="short")
    srv = make_server("0.0.0.0", 0, token=TOKEN)
    srv.server_close()


def test_cli_serve_refuses_public_host_without_token(capsys, monkeypatch):
    monkeypatch.delenv("IFSEEN_TOKEN", raising=False)
    assert main(["serve", "--host", "0.0.0.0", "--port", "0"]) == 2
    assert "refusing" in capsys.readouterr().err


def test_watcher_lifecycle_events_and_snapshot(gemini_env, red_png):
    with running(allow_custom_endpoints=True, keepalive=0.2) as (srv, client):
        r = post(
            client,
            "/v1/watchers",
            {"id": "porch", "start": False, **watcher_config(red_png, gemini_env)},
        )
        assert r.status_code == 201, r.text
        assert r.headers["Location"] == "/v1/watchers/porch"
        state = r.json()
        assert state["id"] == "porch" and state["running"] is False
        assert state["rules"][0]["name"] == "red" and state["rules"][0]["fires"] == 0
        assert "test-key" not in r.text and "base_url" not in r.text

        assert [w["id"] for w in client.get("/v1/watchers").json()["watchers"]] == ["porch"]
        assert client.get("/v1/watchers/porch/snapshot").status_code == 404

        stream = SSE(srv.url)
        filtered = SSE(srv.url, "?watcher=porch&types=fire")
        try:
            r = post(client, "/v1/watchers/porch/start")
            assert r.status_code == 200 and r.json()["running"] is True
            start = stream.wait_for(lambda e: e["event"] == "start")
            assert start["watcher"] == "porch" and start["rules"] == ["red"]
            decision = stream.wait_for(lambda e: e["event"] == "decision")
            assert decision["probs"]["red"] > 0.9
            fire = stream.wait_for(lambda e: e["event"] == "fire")
            assert fire == {**fire, "watcher": "porch", "rule": "red"}
            filtered.wait_for(lambda e: e["event"] == "fire")
            time.sleep(0.5)
            assert {e["event"] for e in filtered.events} == {"fire"}
            assert ": keep-alive" in stream.lines
            assert any(line.startswith("id: ") for line in stream.lines)
            assert any(line == "event: fire" for line in stream.lines)

            state = client.get("/v1/watchers/porch").json()
            assert state["rules"][0]["fires"] == 1 and state["stats"]["calls"] >= 1

            snap = client.get("/v1/watchers/porch/snapshot")
            assert snap.status_code == 200 and snap.headers["Content-Type"] == "image/jpeg"
            assert snap.content[:2] == b"\xff\xd8"

            r = post(client, "/v1/watchers/porch/stop")
            assert r.json()["running"] is False and r.json()["stop_reason"] == "stopped"
            stream.wait_for(lambda e: e["event"] == "stop" and e["watcher"] == "porch")
        finally:
            stream.close()
            filtered.close()

        r = client.delete("/v1/watchers/porch")
        assert r.status_code == 200 and r.json() == {"id": "porch", "deleted": True}
        assert client.get("/v1/watchers/porch").status_code == 404
        assert client.get("/v1/events?watcher=porch").status_code == 404


def test_watcher_create_errors(red_png):
    mock = {"name": "mock"}
    with running(max_watchers=2) as (srv, client):
        ok = post(
            client, "/v1/watchers", {"id": "a", "start": False, **watcher_config(red_png, mock)}
        )
        assert ok.status_code == 201
        dup = post(
            client, "/v1/watchers", {"id": "a", "start": False, **watcher_config(red_png, mock)}
        )
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "already_exists"
        bad_id = post(client, "/v1/watchers", {"id": "no spaces", **watcher_config(red_png, mock)})
        assert bad_id.status_code == 400 and bad_id.json()["error"]["code"] == "invalid_id"
        unknown = post(client, "/v1/watchers", {**watcher_config(red_png, mock), "surprise": 1})
        assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "invalid_config"
        assert "surprise" in unknown.json()["error"]["message"]
        no_rules = post(client, "/v1/watchers", {"source": "screen", "rules": []})
        assert no_rules.status_code == 400
        generated = post(client, "/v1/watchers", {"start": False, **watcher_config(red_png, mock)})
        assert generated.status_code == 201 and len(generated.json()["id"]) == 12
        full = post(client, "/v1/watchers", {"start": False, **watcher_config(red_png, mock)})
        assert full.status_code == 409 and full.json()["error"]["code"] == "too_many_watchers"
        assert client.get("/v1/watchers/missing").status_code == 404
        assert client.delete("/v1/nope").status_code == 404
        r = client.put("/v1/watchers/a")
        assert r.status_code == 405 and r.json()["error"]["code"] == "method_not_allowed"
        stop = client.post(
            "/v1/watchers/a/stop", content=b"", headers={"Content-Type": "text/plain"}
        )
        assert stop.status_code == 415


@pytest.mark.parametrize("then", [[{"shell": "touch pwned"}], ["touch pwned"], "echo hi"])
def test_shell_actions_rejected_over_http(red_png, then):
    cfg = watcher_config(red_png, "mock")
    cfg["rules"][0]["then"] = then
    with running() as (srv, client):
        r = post(client, "/v1/watchers", {"start": False, **cfg})
        assert r.status_code == 403 and r.json()["error"]["code"] == "shell_not_allowed"
        assert client.get("/v1/watchers").json()["watchers"] == []
    with running(allow_shell=True) as (srv, client):
        r = post(client, "/v1/watchers", {"start": False, **cfg})
        assert r.status_code == 201
        assert r.json()["rules"][0]["actions"] == ["shell"]


def test_http_configs_are_not_env_expanded_or_notifying(red_png, monkeypatch):
    monkeypatch.setenv("SECRET_THING", "hunter2")
    notified = []
    monkeypatch.setattr("ifseen.actions.desktop_notify", lambda t, m: notified.append(t))
    cfg = watcher_config(red_png, "mock", context="${SECRET_THING}")
    cfg["rules"][0]["threshold"] = 0.01
    with running() as (srv, client):
        r = post(client, "/v1/watchers", {"id": "w", **cfg})
        assert r.status_code == 201
        watcher = srv.get("w").watcher
        assert watcher.config.context == "${SECRET_THING}"
        deadline = time.time() + 5
        while client.get("/v1/watchers/w").json()["rules"][0]["fires"] == 0:
            assert time.time() < deadline
            time.sleep(0.05)
    assert notified == []


def test_dry_run_server_uses_mock(gemini_env, red_png):
    image = base64.b64encode(red_png.read_bytes()).decode()
    with running(dry_run=True) as (srv, client):
        assert client.get("/v1/health").json()["providers"] == ["mock"]
        r = post(client, "/v1/check", {"image_base64": image, "rules": ["x"], "provider": "gemini"})
        assert r.status_code == 200 and r.json()["provider"].startswith("mock")
        r = post(client, "/v1/watchers", {"start": False, **watcher_config(red_png, "gemini")})
        assert r.status_code == 201 and r.json()["provider"] == "mock"


def test_preloaded_watchers_are_trusted(red_png, tmp_path, monkeypatch):
    monkeypatch.setenv("IMG", str(red_png))
    srv = make_server("127.0.0.1", 0)
    try:
        entry = srv.add_watcher(
            {
                "source": {"file": "${IMG}"},
                "provider": "mock",
                "rules": [{"name": "r", "when": "x", "then": "echo local file"}],
            },
            "local",
            trusted=True,
            start=False,
        )
        assert entry.watcher.config.source.file.path == str(red_png)
        assert entry.state()["rules"][0]["actions"] == ["shell"]
    finally:
        srv.release()


def test_server_close_ends_streams(red_png):
    srv = make_server("127.0.0.1", 0, keepalive=30)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    stream = SSE(srv.url)
    srv.close()
    stream._thread.join(5)
    assert not stream._thread.is_alive()
    stream.close()
