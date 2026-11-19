from __future__ import annotations

import asyncio
import io
import threading
import time

import pytest
from PIL import Image

import ifseen
from ifseen import ConfigError, FireEvent, ProviderConfigError, Watcher, check, check_detailed
from ifseen.media import pcm16_to_wav
from ifseen.providers import Decision, Provider


class ConstProvider(Provider):
    """Answers every question with a fixed probability (or per-key overrides)."""

    name = "const"
    supports = frozenset({"image", "audio"})
    price_per_m_input = 2.0

    def __init__(self, prob: float = 0.9, probs: dict[str, float] | None = None, error=None):
        super().__init__("const-1")
        self.prob = prob
        self.probs = probs or {}
        self.error = error
        self.calls: list[tuple] = []

    def decide(self, sample, questions, context=None):
        self.calls.append((sample, list(questions), context))
        if self.error is not None:
            raise self.error
        return Decision(
            probs={q.key: self.probs.get(q.key, self.prob) for q in questions},
            input_tokens=500,
            latency_ms=3.0,
        )


def wav_bytes(loud: bool = True) -> bytes:
    import struct

    samples = [3000 if (i // 20) % 2 else -3000 for i in range(1600)] if loud else [0] * 1600
    return pcm16_to_wav(struct.pack(f"<{len(samples)}h", *samples), 16000)


def watcher_on(path, provider=None, **kw) -> Watcher:
    kw.setdefault("every", "100ms")
    return Watcher(source={"file": str(path)}, provider=provider or ConstProvider(), **kw)


def collect(w: Watcher, kinds=None) -> list[dict]:
    events: list[dict] = []
    w.on_event(events.append, kinds)
    return events


# -- check() -------------------------------------------------------------------------------


def test_public_exports():
    for name in ("Watcher", "check", "FireEvent", "check_detailed", "ConfigError"):
        assert name in ifseen.__all__


def test_check_list_uses_slugs_and_keeps_order(red_png):
    p = ConstProvider(probs={"a-person-is-visible": 0.1})
    probs = check(red_png, ["A parcel is on the doorstep.", "A person is visible."], provider=p)
    assert list(probs) == ["a-parcel-is-on-the-doorstep", "a-person-is-visible"]
    assert probs["a-person-is-visible"] == 0.1


def test_check_named_statements_with_clarifications(red_png):
    p = ConstProvider()
    probs = check(
        str(red_png),
        {"door": {"when": "The door is open.", "false_means": "The door is closed."}, "x": "Y."},
        provider=p,
        context="front porch",
    )
    assert set(probs) == {"door", "x"}
    _, questions, context = p.calls[0]
    assert questions[0].false_means == "The door is closed."
    assert context == "front porch"


def test_check_accepts_bytes_pil_and_audio(red_png, tmp_path):
    p = ConstProvider()
    check(red_png.read_bytes(), ["Red."], provider=p)
    check(Image.new("RGB", (300, 300)), ["Red."], provider=p)
    wav = tmp_path / "a.wav"
    wav.write_bytes(wav_bytes())
    check(red_png, ["Red."], audio=wav, provider=p)
    check(wav, ["Someone speaks."], provider=p)
    check(None, ["Someone speaks."], audio=wav_bytes(), provider=p)
    kinds = [(s.has_image, s.has_audio) for s, _, _ in p.calls]
    assert kinds == [(True, False), (True, False), (True, True), (False, True), (False, True)]


def test_check_detailed_reports_usage(red_png):
    result = check_detailed(red_png, ["Red."], provider=ConstProvider())
    assert result.input_tokens == 500
    assert result.cost_usd == pytest.approx(0.001)
    assert result.provider == "const (const-1)"


@pytest.mark.parametrize(
    "media, statements",
    [
        (b"not an image", ["x"]),
        ("/nope/missing.jpg", ["x"]),
        (None, ["x"]),
        ("RED", []),
        ("RED", {"bad name!": "x"}),
        ("RED", {"ok": {"when": "x", "threshold": 0.5}}),
        ("RED", [1]),
    ],
)
def test_check_rejects_bad_input(red_png, media, statements):
    with pytest.raises(ConfigError):
        check(red_png if media == "RED" else media, statements, provider=ConstProvider())


def test_check_against_fake_gemini(fake_server, red_png, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    probs = check(
        red_png,
        {"red": "The image is mostly red.", "green": "The image is mostly green."},
        provider={"name": "gemini", "base_url": f"{fake_server.url}/v1beta/decisions"},
    )
    assert probs["red"] > 0.9 and probs["green"] < 0.1


def test_check_audio_with_image_only_provider_fails(tmp_path):
    from ifseen.providers import MockProvider

    class ImageOnly(MockProvider):
        supports = frozenset({"image"})

    with pytest.raises(ProviderConfigError):
        check(None, ["x"], audio=wav_bytes(), provider=ImageOnly())


# -- Watcher -------------------------------------------------------------------------------


def test_decorator_callback_fires_with_fire_event(red_png):
    w = watcher_on(red_png, skip_unchanged=False)
    got: list[FireEvent] = []

    @w.when("A person is at the front door.", threshold=0.85, for_=2, cooldown="1m", name="person")
    def person(event: FireEvent) -> None:
        got.append(event)

    events = collect(w)
    assert w.run(max_ticks=4) == "done"
    assert [e.name for e in got] == ["person"]
    assert got[0].probability == 0.9 and got[0].jpeg and got[0].jpeg[:2] == b"\xff\xd8"
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "stop" and kinds.count("stop") == 1
    fire_at = kinds.index("fire")
    assert kinds[:fire_at].count("decision") == 2  # for_=2


def test_callback_exceptions_are_reported_not_fatal(red_png):
    w = watcher_on(red_png, skip_unchanged=False)
    calls = []

    @w.when("boom", cooldown=0, name="boom")
    def boom(event):
        calls.append(1)
        raise ValueError("kaboom")

    errors = collect(w, ["error"])

    def bad_listener(e):
        raise RuntimeError("listener broke too")

    w.on_error(bad_listener)
    w.on_decision(bad_listener)
    assert w.run(max_ticks=3) == "done"
    assert calls == [1]
    assert errors and all(e["origin"] == "callback" for e in errors)
    assert any(
        "callback for rule 'boom' failed: ValueError: kaboom" in e["message"] for e in errors
    )
    assert w.state()["stats"]["ticks"] == 3


def test_async_callbacks_in_run_async(red_png):
    w = watcher_on(red_png)
    seen = []

    @w.when("red", name="r")
    async def on_red(event):
        await asyncio.sleep(0.01)
        seen.append((event.name, threading.current_thread() is threading.main_thread()))

    decisions = []

    async def on_decision(e):
        decisions.append(e["probs"])

    w.on_decision(on_decision)
    assert asyncio.run(w.run_async(max_ticks=2)) == "done"
    assert seen == [("r", True)]  # ran on the event loop's thread
    assert decisions and decisions[0] == {"r": 0.9}


def test_async_callback_in_blocking_run(red_png):
    w = watcher_on(red_png)
    seen = []

    async def on_red(event):
        await asyncio.sleep(0)
        seen.append(event.probability)

    w.add_rule("red", on_red, name="r")
    w.run(max_ticks=1)
    assert seen == [0.9]


def test_run_async_cancel_stops_the_watcher(red_png):
    w = watcher_on(red_png)
    w.add_rule("red", lambda e: None)

    async def main():
        task = asyncio.create_task(w.run_async())
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    deadline = time.time() + 5
    while w.running and time.time() < deadline:
        time.sleep(0.05)
    assert not w.running and w.state()["stop_reason"] == "stopped"


def test_yaml_actions_run_alongside_callbacks(red_png, monkeypatch):
    notified = []
    monkeypatch.setattr("ifseen.actions.desktop_notify", lambda t, m: notified.append(t))
    w = Watcher.from_config(
        {
            "source": {"file": str(red_png)},
            "every": "100ms",
            "rules": [
                {"name": "logged", "when": "x", "then": [{"log": "saw {rule}"}]},
                {"name": "plain", "when": "y"},
                {"name": "cb-only", "when": "z"},
            ],
        },
        provider=ConstProvider(),
    )
    got = []
    w.on("logged")(lambda e: got.append(e.name))
    w.on("cb-only")(lambda e: got.append(e.name))
    logs = collect(w, ["log"])
    w.run(max_ticks=1)
    assert sorted(got) == ["cb-only", "logged"]
    assert any(e["message"] == "[logged] saw logged" for e in logs)
    # only the rule with neither `then` nor a callback falls back to a desktop notification
    assert notified == ["ifseen: plain"]


def test_notify_by_default_off(red_png, monkeypatch):
    notified = []
    monkeypatch.setattr("ifseen.actions.desktop_notify", lambda t, m: notified.append(t))
    w = Watcher.from_config(
        {"source": {"file": str(red_png)}, "rules": [{"name": "plain", "when": "y"}]},
        provider=ConstProvider(),
        notify_by_default=False,
    )
    w.run(max_ticks=1)
    assert notified == []


def test_background_start_stop_state_and_snapshot(red_png):
    w = watcher_on(red_png, name="porch")
    w.add_rule("red", lambda e: None, name="red", threshold=0.5)
    before = w.state()
    assert before["running"] is False and before["rules"][0]["status"] == "idle"
    assert w.snapshot() is None
    w.start()
    deadline = time.time() + 5
    while w.state()["rules"][0]["fires"] == 0 and time.time() < deadline:
        time.sleep(0.02)
    s = w.state()
    assert s["running"] and s["name"] == "porch"
    rule = s["rules"][0]
    assert rule["prob"] == 0.9 and rule["fires"] == 1 and rule["armed"] is False
    assert rule["last_fired"] is not None and rule["callbacks"] == 1
    assert s["stats"]["calls"] >= 1 and s["source"] == f"image {red_png.name}"
    with pytest.raises(RuntimeError):
        w.start()
    with pytest.raises(RuntimeError):
        w.add_rule("another")
    w.stop()
    assert not w.running and w.state()["stop_reason"] == "stopped"
    assert Image.open(io.BytesIO(w.snapshot())).format == "JPEG"
    # a stopped watcher can be restarted
    w.start(max_ticks=2)
    w.join(5)
    assert w.state()["stop_reason"] == "done"


def test_stop_from_inside_a_callback(red_png):
    w = watcher_on(red_png)
    w.add_rule("red", lambda e: w.stop(), name="r")
    t0 = time.time()
    w.start()
    w.join(5)
    assert not w.running and w.state()["stop_reason"] == "stopped"
    assert time.time() - t0 < 4


def test_fatal_errors(red_png):
    w = watcher_on(red_png, provider=ConstProvider(error=ProviderConfigError("bad key")))
    w.add_rule("red")
    events = collect(w)
    with pytest.raises(ProviderConfigError):
        w.run()
    assert [e["event"] for e in events][-2:] == ["error", "stop"]
    assert events[-2]["fatal"] is True and w.state()["error"] == "bad key"

    w2 = watcher_on("/nope/missing.png")
    w2.add_rule("red")
    events2 = collect(w2)
    w2.start()
    w2.join(5)
    assert "no such file" in w2.state()["error"]
    assert [e["event"] for e in events2] == ["error", "stop"]


def test_ctrl_c_is_clean(red_png):
    w = watcher_on(red_png, provider=ConstProvider(error=KeyboardInterrupt()))
    w.add_rule("red")
    assert w.run() == "interrupted"


def test_validation_happens_early():
    with pytest.raises(ConfigError):
        Watcher(source={"camera": 0, "screen": 1})
    with pytest.raises(ConfigError):
        Watcher(source="screen", every="1ms")
    with pytest.raises(ConfigError):
        Watcher(source="screen", provider="nope")
    w = Watcher(source="screen", provider="mock")
    with pytest.raises(ConfigError):
        w.add_rule("x", threshold=2)
    w.add_rule("same", name="same")
    with pytest.raises(ConfigError):
        w.add_rule("other", name="same")
    with pytest.raises(ConfigError):
        w.on("missing")
    with pytest.raises(ConfigError):
        Watcher(source="screen").run()  # no rules


def test_from_yaml_and_dry_run(tmp_path, red_png, monkeypatch):
    monkeypatch.setenv("IMG", str(red_png))
    path = tmp_path / "r.yaml"
    path.write_text(
        'source: {file: "${IMG}"}\nprovider: gemini\nevery: 100ms\n'
        "rules:\n  - {name: r, when: x, then: [log]}\n"
    )
    w = Watcher.from_yaml(path, dry_run=True)
    assert w.config.provider.name == "mock"
    events = collect(w, ["start"])
    w.run(max_ticks=1)
    assert events[0]["provider"].startswith("mock")


def test_from_config_without_env_expansion(monkeypatch):
    monkeypatch.setenv("SECRET", "hunter2")
    w = Watcher.from_config(
        {"source": "screen", "context": "${SECRET}", "rules": [{"name": "a", "when": "b"}]},
        expand_env=False,
    )
    assert w.config.context == "${SECRET}"
