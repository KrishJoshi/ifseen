from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import httpx
import pytest
from conftest import solid_jpeg
from test_api import ConstProvider
from test_engine import FakeClock, ListSource, ScriptedProvider, frames
from test_server import post, running, watcher_config

import ifseen.mqtt as mqtt_mod
from ifseen import Watcher
from ifseen.actions import ActionRunner
from ifseen.cli import main
from ifseen.config import ConfigError, load_config
from ifseen.constants import VERSION
from ifseen.engine import Engine
from ifseen.ha import discovery_configs, resolve_watcher_id
from ifseen.media import Sample
from ifseen.mqtt import MqttBridge, attach_bridge

PREFIX = "homeassistant"


class FakeInfo:
    rc = 0

    def wait_for_publish(self, timeout=None):
        return True


class FakeClient:
    """Records what a paho client would be asked to do."""

    def __init__(self, client_id: str = "test"):
        self.client_id = client_id
        self.published: list[tuple[str, bytes, int, bool]] = []
        self.subscribed: list[str] = []
        self.will = None
        self.auth = None
        self.tls = None
        self.connect_args = None
        self.loop_started = self.loop_stopped = self.disconnected = False
        self.fail_publish = False
        self.on_connect = self.on_disconnect = self.on_message = None

    # paho API surface used by the bridge
    def username_pw_set(self, username, password=None):
        self.auth = (username, password)

    def tls_set(self, **kw):
        self.tls = kw

    def tls_insecure_set(self, value):
        self.tls = {**(self.tls or {}), "insecure": value}

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay, max_delay):
        pass

    def max_queued_messages_set(self, n):
        pass

    def connect_async(self, host, port, keepalive):
        self.connect_args = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload=None, qos=0, retain=False):
        if self.fail_publish:
            raise OSError("broker exploded")
        data = payload.encode() if isinstance(payload, str) else (payload or b"")
        self.published.append((topic, data, qos, retain))
        return FakeInfo()

    # test helpers
    def connect(self):
        self.on_connect(self, None, {}, SimpleNamespace(is_failure=False), None)

    def drop(self):
        self.on_disconnect(self, None, {}, SimpleNamespace(is_failure=True), None)

    def message(self, topic, payload, retain=False):
        self.on_message(self, None, SimpleNamespace(topic=topic, payload=payload, retain=retain))

    def last(self, topic):
        for t, data, *_ in reversed(self.published):
            if t == topic:
                return data
        return None

    def all(self, topic):
        return [data for t, data, *_ in self.published if t == topic]

    def json(self, topic):
        data = self.last(topic)
        return None if data is None else json.loads(data)


@pytest.fixture
def clients(monkeypatch):
    made: list[FakeClient] = []

    def factory(client_id):
        made.append(FakeClient(client_id))
        return made[-1]

    monkeypatch.setattr(mqtt_mod, "paho_client_factory", factory)
    return made


def mqtt_cfg(**kw):
    return {"host": "broker", "id": "front-door", "name": "Front door", **kw}


def make_engine(script, samples, rules=None, mqtt=None, **cfg):
    clock = FakeClock()
    rules = rules or [
        {"name": "person", "when": "A person is at the door.", "cooldown": 0, "then": ["log"]}
    ]
    config = load_config(
        {
            "source": "screen",
            "rules": rules,
            "every": "1s",
            "skip_unchanged": False,
            "mqtt": mqtt or mqtt_cfg(),
            **cfg,
        }
    )
    events: list[dict] = []
    engine = Engine(
        config,
        ListSource(samples),
        ScriptedProvider(script),
        ActionRunner(log=lambda *a: None, background=False),
        listener=events.append,
        clock=clock,
        sleep=clock.sleep,
    )
    fake = FakeClient()
    bridge = attach_bridge(config, engine, client_factory=lambda cid: fake)
    bridge._clock = clock
    return engine, bridge, fake, events, config


# -- config ----------------------------------------------------------------------------------


def test_mqtt_config_defaults_and_shorthand():
    cfg = load_config({"source": "screen", "mqtt": "core-mosquitto", "rules": [_rule()]})
    m = cfg.mqtt
    assert (m.host, m.port, m.base_topic, m.discovery_prefix) == (
        "core-mosquitto",
        1883,
        "ifseen",
        "homeassistant",
    )
    assert m.discovery and m.fire_image and m.pause_switch and m.frame_every == 0
    with_port = load_config({"source": "screen", "mqtt": "broker.lan:8883", "rules": [_rule()]})
    assert (with_port.mqtt.host, with_port.mqtt.port) == ("broker.lan", 8883)
    tls = load_config({"source": "screen", "mqtt": {"host": "b", "tls": True}, "rules": [_rule()]})
    assert tls.mqtt.tls is not None and tls.mqtt.tls.insecure is False


def test_mqtt_password_comes_from_env_and_is_never_printed(monkeypatch):
    monkeypatch.setenv("MQTT_PASSWORD", "hunter2")
    cfg = load_config(
        {
            "source": "screen",
            "mqtt": {"host": "b", "username": "ha", "password": "${MQTT_PASSWORD}"},
            "rules": [_rule()],
        }
    )
    assert cfg.mqtt.password.get_secret_value() == "hunter2"
    assert "hunter2" not in repr(cfg) and "hunter2" not in str(cfg.mqtt)


@pytest.mark.parametrize(
    "bad",
    [
        {"host": "b", "base_topic": "ifseen/#"},
        {"host": "b", "base_topic": "/ifseen"},
        {"host": "b", "discovery_prefix": "home assistant"},
        {"host": "b", "discovery_prefix": "a//b"},
        {"host": "mqtt://b"},
        {"host": "b", "port": 0},
        {"host": "b", "id": "no spaces"},
        {"host": "b", "frame_every": "500ms"},
        {"host": "b", "surprise": 1},
    ],
)
def test_mqtt_config_rejects_bad_values(bad):
    with pytest.raises(ConfigError):
        load_config({"source": "screen", "mqtt": bad, "rules": [_rule()]})


def test_ha_device_class_is_validated():
    ok = load_config({"source": "screen", "rules": [{**_rule(), "ha_device_class": "occupancy"}]})
    assert ok.rules[0].ha_device_class == "occupancy"
    with pytest.raises(ConfigError, match="device class"):
        load_config({"source": "screen", "rules": [{**_rule(), "ha_device_class": "doorbell"}]})


def test_watcher_id_resolution():
    base = load_config({"source": "screen", "mqtt": "b", "rules": [_rule()]}).mqtt
    assert resolve_watcher_id(base) == "ifseen"
    assert resolve_watcher_id(base, "My Rules") == "my-rules"
    named = base.model_copy(update={"name": "Front door"})
    assert resolve_watcher_id(named, "rules") == "front-door"
    explicit = named.model_copy(update={"id": "porch_cam"})
    assert resolve_watcher_id(explicit, "rules") == "porch_cam"


def _rule(**kw):
    return {"name": "r", "when": "x", **kw}


# -- discovery payloads ------------------------------------------------------------------------


def test_discovery_payloads_exact():
    cfg = load_config(
        {
            "source": "screen",
            "mqtt": mqtt_cfg(),
            "rules": [
                {"name": "person-at-door", "when": "A person.", "ha_device_class": "occupancy"},
                {"name": "parcel", "when": "A parcel.", "threshold": 0.85},
            ],
        }
    )
    configs = discovery_configs(
        cfg.mqtt, "front-door", "Front door", cfg.rules, model="gemini watcher"
    )
    node = "ifseen_front-door"
    assert sorted(configs) == sorted(
        [
            f"{PREFIX}/binary_sensor/{node}/person-at-door_active/config",
            f"{PREFIX}/sensor/{node}/person-at-door_probability/config",
            f"{PREFIX}/binary_sensor/{node}/parcel_active/config",
            f"{PREFIX}/sensor/{node}/parcel_probability/config",
            f"{PREFIX}/sensor/{node}/status/config",
            f"{PREFIX}/sensor/{node}/cost_per_hour/config",
            f"{PREFIX}/sensor/{node}/calls/config",
            f"{PREFIX}/event/{node}/trigger/config",
            f"{PREFIX}/camera/{node}/last_trigger/config",
            f"{PREFIX}/switch/{node}/watching/config",
        ]
    )
    device = {
        "identifiers": [node],
        "name": "Front door",
        "manufacturer": "ifseen",
        "model": "gemini watcher",
        "sw_version": VERSION,
    }
    common = {
        "availability_topic": "ifseen/front-door/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device,
        "origin": {
            "name": "ifseen",
            "sw_version": VERSION,
            "support_url": "https://github.com/KrishJoshi/ifseen",
        },
    }
    assert configs[f"{PREFIX}/binary_sensor/{node}/person-at-door_active/config"] == {
        "unique_id": "ifseen_front-door_person-at-door_active",
        "name": "Person at door",
        "state_topic": "ifseen/front-door/rule/person-at-door/active",
        "payload_on": "ON",
        "payload_off": "OFF",
        "json_attributes_topic": "ifseen/front-door/rule/person-at-door/probability",
        "device_class": "occupancy",
        **common,
    }
    parcel = configs[f"{PREFIX}/binary_sensor/{node}/parcel_active/config"]
    assert "device_class" not in parcel and parcel["icon"] == "mdi:eye"
    assert configs[f"{PREFIX}/sensor/{node}/parcel_probability/config"] == {
        "unique_id": "ifseen_front-door_parcel_probability",
        "name": "Parcel probability",
        "state_topic": "ifseen/front-door/rule/parcel/probability",
        "value_template": "{{ value_json.probability }}",
        "json_attributes_topic": "ifseen/front-door/rule/parcel/probability",
        "unit_of_measurement": "%",
        "state_class": "measurement",
        "suggested_display_precision": 0,
        "icon": "mdi:percent",
        **common,
    }
    assert configs[f"{PREFIX}/camera/{node}/last_trigger/config"] == {
        "unique_id": "ifseen_front-door_last_trigger",
        "name": "Last trigger",
        "topic": "ifseen/front-door/camera/fire",
        **common,
    }
    switch = configs[f"{PREFIX}/switch/{node}/watching/config"]
    assert switch["command_topic"] == "ifseen/front-door/watching/set"
    assert switch["state_topic"] == "ifseen/front-door/watching"
    event = configs[f"{PREFIX}/event/{node}/trigger/config"]
    assert event["event_types"] == ["person-at-door", "parcel"]
    assert configs[f"{PREFIX}/sensor/{node}/calls/config"]["state_class"] == "total_increasing"
    # every entity is available only while the watcher is online
    assert all(c["availability_topic"] == common["availability_topic"] for c in configs.values())
    assert len({c["unique_id"] for c in configs.values()}) == len(configs)


def test_discovery_options_change_the_entity_set():
    rules = load_config({"source": "screen", "rules": [_rule()]}).rules

    def topics(**kw):
        m = load_config({"source": "screen", "mqtt": {"host": "b", **kw}, "rules": [_rule()]})
        return {t.split("/")[-2] for t in discovery_configs(m.mqtt, "w", "W", rules)}

    assert "frame" not in topics()
    assert "frame" in topics(frame_every="5s")
    assert "last_trigger" not in topics(fire_image=False)
    assert "watching" not in topics(pause_switch=False)
    assert topics(discovery=False) == set()
    audio_only = load_config({"source": "mic", "mqtt": "b", "rules": [_rule()]})
    cams = discovery_configs(audio_only.mqtt, "w", "W", rules, has_image=False)
    assert not any("/camera/" in t for t in cams)
    prefixed = load_config(
        {"source": "screen", "mqtt": {"host": "b", "discovery_prefix": "ha"}, "rules": [_rule()]}
    )
    assert all(t.startswith("ha/") for t in discovery_configs(prefixed.mqtt, "w", "W", rules))


# -- bridge behaviour --------------------------------------------------------------------------


def test_connect_publishes_lwt_availability_discovery_and_state():
    engine, bridge, fake, _, _ = make_engine([], [])
    assert fake.will == ("ifseen/front-door/availability", "offline", 1, True)
    bridge.start()
    assert fake.connect_args == ("broker", 1883, 60) and fake.loop_started
    assert fake.published == []  # nothing before the broker accepts us
    fake.connect()
    assert fake.published[0] == ("ifseen/front-door/availability", b"online", 1, True)
    discovery = [p for p in fake.published if p[0].startswith(PREFIX)]
    assert len(discovery) == len(bridge.discovery) and all(p[2:] == (1, True) for p in discovery)
    assert fake.last("ifseen/front-door/rule/person/active") == b"OFF"
    assert fake.json("ifseen/front-door/rule/person/probability")["probability"] == 0.0
    assert fake.json("ifseen/front-door/state")["status"] == "watching"
    assert fake.last("ifseen/front-door/watching") == b"ON"
    assert fake.subscribed == [
        "homeassistant/+/ifseen_front-door/+/config",
        "ifseen/front-door/rule/#",
        "ifseen/front-door/watching/set",
    ]
    bridge.close()
    assert fake.last("ifseen/front-door/availability") == b"offline"
    assert fake.json("ifseen/front-door/state")["status"] == "stopped"
    assert fake.disconnected and fake.loop_stopped


def test_binary_sensor_follows_fire_and_rearm():
    # fire at 0.9, stay ON through 0.7 (above 0.8 - 0.15), OFF at 0.5, ON again at 0.95
    probs = [0.1, 0.9, 0.7, 0.5, 0.95]
    engine, bridge, fake, events, _ = make_engine([{"person": p} for p in probs], frames(5))
    bridge.start()
    fake.connect()
    engine.run()
    assert fake.all("ifseen/front-door/rule/person/active") == [b"OFF", b"ON", b"OFF", b"ON"]
    kinds = [(e["event"], e.get("rule")) for e in events if e["event"] in ("fire", "clear")]
    assert kinds == [("fire", "person"), ("clear", "person"), ("fire", "person")]
    attrs = fake.json("ifseen/front-door/rule/person/probability")
    assert attrs["probability"] == 95.0 and attrs["active"] is True and attrs["fires"] == 2
    assert attrs["threshold"] == 80.0 and attrs["last_fired"].endswith("+00:00")
    probs_published = [
        json.loads(p)["probability"] for p in fake.all("ifseen/front-door/rule/person/probability")
    ]
    assert probs_published == [0.0, 10.0, 90.0, 70.0, 50.0, 95.0]


def test_unchanged_states_are_not_republished():
    engine, bridge, fake, _, _ = make_engine([{"person": 0.2}] * 4, frames(4))
    bridge.start()
    fake.connect()
    engine.run()
    assert fake.all("ifseen/front-door/rule/person/active") == [b"OFF"]
    assert len(fake.all("ifseen/front-door/rule/person/probability")) == 2  # 0% then 20%


def test_fire_publishes_event_and_triggering_frame():
    red, blue = solid_jpeg((230, 20, 20)), solid_jpeg((20, 20, 230))
    engine, bridge, fake, _, _ = make_engine(
        [{"person": 0.1}, {"person": 0.95}, {"person": 0.95}],
        [Sample(jpeg=blue), Sample(jpeg=red), Sample(jpeg=blue)],
    )
    bridge.start()
    fake.connect()
    engine.run()
    images = [p for p in fake.published if p[0] == "ifseen/front-door/camera/fire"]
    assert images == [("ifseen/front-door/camera/fire", red, 1, True)]
    (event,) = [json.loads(p[1]) for p in fake.published if p[0] == "ifseen/front-door/event"]
    assert event["event_type"] == "person" and event["probability"] == 95.0
    assert not any(p[0] == "ifseen/front-door/camera/frame" for p in fake.published)


def test_latest_frame_is_rate_limited():
    engine, bridge, fake, _, _ = make_engine(
        [{"person": 0.1}] * 6, frames(6), mqtt=mqtt_cfg(frame_every="2s")
    )
    bridge.start()
    fake.connect()
    engine.run()
    frames_sent = [p for p in fake.published if p[0] == "ifseen/front-door/camera/frame"]
    assert len(frames_sent) == 3  # ticks at t=0, 2, 4 of 0..5
    assert all(p[2:] == (0, False) for p in frames_sent)


def test_stale_entities_are_removed():
    engine, bridge, fake, _, _ = make_engine([], [])
    bridge.start()
    fake.connect()
    fake.published.clear()
    stale = f"{PREFIX}/binary_sensor/ifseen_front-door/old-rule_active/config"
    ours = f"{PREFIX}/binary_sensor/ifseen_front-door/person_active/config"
    fake.message(stale, b'{"name": "Old"}', retain=True)
    fake.message(ours, b'{"name": "Person"}', retain=True)  # our own echo
    fake.message(stale, b"", retain=True)  # already cleared
    fake.message(f"{PREFIX}/sensor/ifseen_front-door/x/config", b"{}", retain=False)  # live
    # some brokers leak retained messages that don't match the filter: never touch those
    fake.message("ifseen/front-door/availability", b"online", retain=True)
    fake.message(f"{PREFIX}/sensor/ifseen_other/status/config", b"{}", retain=True)
    fake.message(f"{PREFIX}/sensor/ifseen_front-door/a/b/config", b"{}", retain=True)
    old_state = "ifseen/front-door/rule/old-rule/active"
    fake.message(old_state, b"ON", retain=True)
    fake.message("ifseen/front-door/rule/person/active", b"ON", retain=True)  # current rule
    assert fake.published == [(stale, b"", 1, True), (old_state, b"", 1, True)]


def test_discovery_off_clears_everything():
    engine, bridge, fake, _, _ = make_engine([], [], mqtt=mqtt_cfg(discovery=False))
    bridge.start()
    fake.connect()
    assert not any(p[0].startswith(PREFIX) for p in fake.published)
    old = f"{PREFIX}/sensor/ifseen_front-door/status/config"
    fake.message(old, b"{}", retain=True)
    assert fake.last(old) == b""
    assert fake.last("ifseen/front-door/rule/person/active") == b"OFF"  # state still published


def test_switch_pauses_and_resumes():
    engine, bridge, fake, events, _ = make_engine([{"person": 0.1}] * 3, frames(3))
    bridge.start()
    fake.connect()
    fake.message("ifseen/front-door/watching/set", b"OFF")
    assert engine.paused
    assert fake.last("ifseen/front-door/watching") == b"OFF"
    assert fake.json("ifseen/front-door/state")["status"] == "paused"
    fake.message("ifseen/front-door/watching/set", b"bogus")
    assert engine.paused
    fake.message("ifseen/front-door/watching/set", b"on")
    assert not engine.paused
    assert fake.last("ifseen/front-door/watching") == b"ON"
    assert [e["event"] for e in events] == ["pause", "resume"]


def test_paused_engine_skips_ticks_until_resumed():
    engine, bridge, fake, events, _ = make_engine([{"person": 0.9}], frames(1))
    calls = []

    def unpause_later(eng, sample):
        calls.append(sample)
        if len(calls) == 3:
            eng.resume()

    engine.observers.insert(0, unpause_later)
    engine.pause()
    engine.run()
    assert calls[:2] == [None, None]  # paused intervals: no capture, no provider call
    assert engine.provider.calls == 1
    assert [e["event"] for e in events][:3] == ["pause", "start", "resume"]


def test_disconnected_bridge_buffers_nothing_and_resyncs_on_reconnect():
    red = solid_jpeg((230, 20, 20))
    engine, bridge, fake, _, _ = make_engine(
        [{"person": 0.95}, {"person": 0.95}], [Sample(jpeg=red), Sample(jpeg=red)]
    )
    bridge.start()
    engine.run()  # never connected
    assert fake.published == []
    fake.connect()
    assert fake.last("ifseen/front-door/rule/person/active") == b"ON"
    assert fake.last("ifseen/front-door/camera/fire") == red
    attrs = fake.json("ifseen/front-door/rule/person/probability")
    assert attrs["fires"] == 1 and attrs["last_fired"] is not None
    fake.drop()
    count = len(fake.published)
    bridge.observe(engine, None)
    assert len(fake.published) == count
    fake.connect()  # full resync after a reconnect, even though nothing changed
    assert fake.all("ifseen/front-door/rule/person/active")[-1] == b"ON"
    assert len(fake.all("ifseen/front-door/availability")) == 2


def test_broker_failures_never_stop_the_loop():
    engine, bridge, fake, events, _ = make_engine([{"person": 0.9}] * 3, frames(3))
    logs = []
    bridge._log_fn = lambda level, msg: logs.append((level, msg))
    bridge.start()
    fake.connect()
    fake.fail_publish = True
    assert engine.run() == "done"
    assert engine.stats.calls == 3
    assert any("publish failed" in m for _, m in logs)
    assert all("hunter" not in m for _, m in logs)
    bridge.close()  # still closes cleanly
    assert fake.loop_stopped


def test_observer_exceptions_become_error_events():
    engine, _, _, events, _ = make_engine([{"person": 0.9}] * 2, frames(2))

    def boom(eng, sample):
        raise RuntimeError("nope")

    engine.observers.insert(0, boom)
    assert engine.run() == "done"
    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 1 and errors[0]["origin"] == "observer"


def test_auth_tls_and_client_id_settings(monkeypatch):
    monkeypatch.setenv("MQTT_PASSWORD", "hunter2")
    cfg = load_config(
        {
            "source": "screen",
            "rules": [_rule()],
            "mqtt": {
                "host": "b",
                "port": 8883,
                "username": "ha",
                "password": "${MQTT_PASSWORD}",
                "tls": {"ca_certs": "/ca.pem", "insecure": True},
                "client_id": "fixed",
            },
        }
    )
    seen = {}

    def factory(cid):
        seen["cid"] = cid
        return FakeClient(cid)

    bridge = MqttBridge(cfg.mqtt, cfg.rules, client_factory=factory)
    assert seen["cid"] == "fixed"
    assert bridge.client.auth == ("ha", "hunter2")
    assert bridge.client.tls == {
        "ca_certs": "/ca.pem",
        "certfile": None,
        "keyfile": None,
        "insecure": True,
    }
    auto = MqttBridge(
        cfg.mqtt.model_copy(update={"client_id": None}), cfg.rules, client_factory=FakeClient
    )
    assert auto.client.client_id.startswith("ifseen-ifseen-")


def test_missing_paho_is_a_config_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "paho", None)
    monkeypatch.setitem(sys.modules, "paho.mqtt", None)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", None)
    cfg = load_config({"source": "screen", "mqtt": "b", "rules": [_rule()]})
    with pytest.raises(ConfigError, match=r"ifseen\[mqtt\]"):
        MqttBridge(cfg.mqtt, cfg.rules)


# -- entry points ------------------------------------------------------------------------------


def test_watcher_api_publishes_and_exposes_active(clients, red_png):
    w = Watcher(
        source={"file": str(red_png)},
        provider="mock",
        every="100ms",
        rules=[{"name": "red", "when": "Red.", "threshold": 0.01, "cooldown": 0}],
        mqtt={"host": "broker", "name": "Garage"},
    )
    w.on("red")(lambda e: None)
    w.start(max_ticks=3)
    deadline = time.time() + 5
    while not clients and time.time() < deadline:
        time.sleep(0.01)
    fake = clients[0]
    fake.connect()
    w.join(5)
    assert not w.running
    assert fake.last("ifseen/garage/availability") == b"offline"
    assert fake.last("ifseen/garage/rule/red/active") in (b"ON", b"OFF")
    state = w.state()
    assert state["paused"] is False and "active" in state["rules"][0]
    discovery = fake.json(f"{PREFIX}/binary_sensor/ifseen_garage/red_active/config")
    assert discovery["device"]["name"] == "Garage"
    assert discovery["device"]["model"] == "mock watcher"


def test_watcher_pause_resume(red_png):
    w = Watcher(
        source={"file": str(red_png)},
        provider="mock",
        every="100ms",
        rules=[{"name": "red", "when": "Red."}],
    )
    w.on("red")(lambda e: None)
    w.pause()  # not running: no-op
    w.start()
    try:
        deadline = time.time() + 5
        while w._engine is None and time.time() < deadline:
            time.sleep(0.01)
        w.pause()
        assert w.paused and w.state()["paused"]
        ticks = w.state()["stats"]["ticks"]
        time.sleep(0.35)
        assert w.state()["stats"]["ticks"] <= ticks + 1
        w.resume()
        assert not w.paused
    finally:
        w.stop()


def test_from_yaml_uses_file_stem_as_watcher_id(clients, tmp_path, red_png):
    path = tmp_path / "porch.yaml"
    path.write_text(
        f"source: {{file: {red_png}}}\nprovider: mock\nevery: 100ms\nmqtt: broker\n"
        "rules:\n  - {name: red, when: Red.}\n"
    )
    w = Watcher.from_yaml(path)
    w.on("red")(lambda e: None)
    w.run(max_ticks=1)
    assert clients[0].will[0] == "ifseen/porch/availability"


def test_cli_watch_with_mqtt_block(clients, tmp_path, red_png, capsys):
    path = tmp_path / "doorstep.yaml"
    path.write_text(
        f"source: {{file: {red_png}}}\nevery: 100ms\nmqtt: {{host: broker, port: 1884}}\n"
        "rules:\n  - {name: red, when: Red., then: [log]}\n"
    )
    assert main(["watch", str(path), "--dry-run", "--json", "--max-ticks", "2"]) == 0
    fake = clients[0]
    assert fake.connect_args == ("broker", 1884, 60)
    assert fake.will[0] == "ifseen/doorstep/availability"
    assert fake.disconnected and fake.loop_stopped


def test_http_watchers_cannot_set_mqtt(red_png):
    cfg = watcher_config(red_png, "mock", mqtt={"host": "evil.example"})
    with running() as (_, client):
        r = post(client, "/v1/watchers", {"start": False, **cfg})
        assert r.status_code == 403 and r.json()["error"]["code"] == "mqtt_not_allowed"
    with running(allow_custom_endpoints=True) as (_, client):
        r = post(client, "/v1/watchers", {"start": False, **cfg})
        assert r.status_code == 201


def test_preloaded_serve_watcher_uses_its_id(clients, red_png):
    with running(dry_run=True) as (srv, client):
        srv.add_watcher(watcher_config(red_png, "mock", mqtt="broker"), "kitchen", trusted=True)
        deadline = time.time() + 5
        while not clients and time.time() < deadline:
            time.sleep(0.01)
        assert clients[0].will[0] == "ifseen/kitchen/availability"
        assert isinstance(client, httpx.Client)


def test_rules_without_then_dont_notify_when_mqtt_is_on(clients, red_png, monkeypatch):
    notified = []
    monkeypatch.setattr("ifseen.actions.desktop_notify", lambda *a: notified.append(a))
    w = Watcher.from_config(
        {
            "source": {"file": str(red_png)},
            "every": "100ms",
            "mqtt": "broker",
            "rules": [{"name": "red", "when": "Red.", "threshold": 0.01}],
        },
        provider=ConstProvider(0.95),
    )
    w.run(max_ticks=1)
    assert w.state()["rules"][0]["fires"] == 1
    assert notified == []
