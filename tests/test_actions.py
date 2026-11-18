from __future__ import annotations

import json
import time

import httpx
from conftest import solid_jpeg

from ifseen.actions import ActionRunner, FireEvent, render
from ifseen.config import load_config
from ifseen.media import Sample


def event(name="door", when="a person's at the door", prob=0.93):
    rule = load_config({"source": "screen", "rules": [{"name": name, "when": when}]}).rules[0]
    return FireEvent(rule, prob, time.time(), Sample(jpeg=solid_jpeg((200, 0, 0))), "camera 0")


def test_render_templates_and_unknown_placeholders():
    e = event()
    assert render("{rule} {percent} {nope}", e) == "door 93% {nope}"


def test_render_shell_quotes_values():
    e = event(when="it's $(rm -rf /) time")
    out = render("echo {when}", e, shell=True)
    assert out == "echo 'it'\"'\"'s $(rm -rf /) time'"


def test_shell_action_gets_env_and_runs(tmp_path):
    out = tmp_path / "out.txt"
    logs = []
    runner = ActionRunner(log=lambda *a: logs.append(a), background=False)
    stop = runner.run(
        [{"shell": {"cmd": f'echo "$IFSEEN_RULE $IFSEEN_PERCENT" > {out}', "wait": True}}], event()
    )
    assert not stop
    assert out.read_text().strip() == "door 93%"
    assert not logs


def test_exit_and_dry_run(tmp_path):
    logs = []
    marker = tmp_path / "ran"
    runner = ActionRunner(log=lambda lvl, m: logs.append((lvl, m)), dry_run=True, background=False)
    stop = runner.run([{"shell": f"touch {marker}"}, {"exit": True}], event())
    assert stop
    assert not marker.exists()
    assert logs and logs[0][0] == "dry"


def test_snapshot_writes_jpeg(tmp_path):
    runner = ActionRunner(log=lambda *a: None, background=False)
    runner.run([{"snapshot": str(tmp_path / "caps")}], event())
    files = list((tmp_path / "caps").glob("door-*.jpg"))
    assert len(files) == 1 and files[0].read_bytes()[:2] == b"\xff\xd8"


def test_webhook_payload(fake_server):
    runner = ActionRunner(log=lambda *a: None, background=False)
    runner.run([{"webhook": {"url": f"{fake_server.url}/hook", "image": True}}], event())
    body = fake_server.requests[-1]["body"]
    assert body["rule"] == "door" and body["probability"] == 0.93
    assert body["image_base64"]


def test_ntfy_attaches_image():
    seen = {}

    def handler(request: httpx.Request):
        seen["method"] = request.method
        seen["url"] = request.url
        seen["len"] = len(request.content)
        return httpx.Response(200, json={})

    runner = ActionRunner(
        log=lambda *a: None,
        background=False,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    runner.run([{"ntfy": {"topic": "my-topic", "priority": "high"}}], event())
    assert seen["method"] == "PUT"
    assert seen["url"].path == "/my-topic"
    assert seen["url"].params["filename"] == "door.jpg"
    assert seen["url"].params["priority"] == "high"
    assert seen["url"].params["message"] == "a person's at the door (93%)"
    assert seen["len"] > 100


def test_failing_action_is_logged_not_raised():
    logs = []
    runner = ActionRunner(log=lambda lvl, m: logs.append((lvl, m)), background=False)
    runner.run([{"webhook": "http://127.0.0.1:1/unreachable"}], event())
    assert logs and logs[0][0] == "error" and "webhook failed" in logs[0][1]


def test_default_action_is_notify(monkeypatch):
    called = []
    monkeypatch.setattr("ifseen.actions.desktop_notify", lambda t, m: called.append((t, m)))
    ActionRunner(log=lambda *a: None, background=False).run([], event())
    assert called == [("ifseen: door", "a person's at the door (93%)")]


def test_json_roundtrip_of_fields():
    assert json.dumps(event().fields())
