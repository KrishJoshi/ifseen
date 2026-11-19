"""End-to-end against a real MQTT broker (amqtt, in-process). Skipped if it isn't installed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

pytest.importorskip("amqtt")
paho = pytest.importorskip("paho.mqtt.client")

from test_api import ConstProvider  # noqa: E402

from ifseen import Watcher  # noqa: E402

AVAIL = "ifseen/porch/availability"
NODE = "homeassistant/+/ifseen_porch/+/config"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def broker():
    from amqtt.broker import Broker

    port = _free_port()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    box: dict = {}

    def run() -> None:
        asyncio.set_event_loop(loop)
        try:
            b = Broker(
                {"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}}}, loop=loop
            )
            loop.run_until_complete(b.start())
            box["broker"] = b
        except Exception as e:  # pragma: no cover - environment specific
            box["error"] = e
        ready.set()
        if "broker" in box:
            loop.run_forever()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(10)
    if "error" in box:
        pytest.skip(f"amqtt broker failed to start: {box['error']!r}")
    yield port
    fut = asyncio.run_coroutine_threadsafe(box["broker"].shutdown(), loop)
    with contextlib.suppress(Exception):
        fut.result(5)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(5)


class Listener:
    """A plain paho client recording the latest payload per topic."""

    def __init__(self, port: int, *topics: str):
        self.latest: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.client = paho.Client(paho.CallbackAPIVersion.VERSION2)
        self.client.on_message = self._on_message
        self.client.connect("127.0.0.1", port)
        for t in topics:
            self.client.subscribe(t, qos=1)
        self.client.loop_start()

    def _on_message(self, client, userdata, msg) -> None:
        with self.lock:
            if msg.payload:
                self.latest[msg.topic] = msg.payload
            else:
                self.latest.pop(msg.topic, None)

    def wait(self, pred, timeout: float = 8.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if pred(self.latest):
                    return
            time.sleep(0.05)
        with self.lock:
            raise AssertionError(f"timed out; have {sorted(self.latest)}")

    def publish(self, topic: str, payload: str) -> None:
        self.client.publish(topic, payload, qos=1).wait_for_publish(3)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def _watcher(port: int, png, rules) -> Watcher:
    w = Watcher(
        source={"file": str(png)},
        provider=ConstProvider(0.95),
        every="100ms",
        rules=rules,
        mqtt={"host": "127.0.0.1", "port": port, "id": "porch", "name": "Porch"},
    )
    for r in rules:
        w.on(r["name"])(lambda e: None)
    return w


def test_real_broker_discovery_state_switch_and_cleanup(broker, red_png):
    live = Listener(broker, "ifseen/#", "homeassistant/#")
    try:
        rules = [
            {"name": "person", "when": "A person.", "ha_device_class": "occupancy"},
            {"name": "parcel", "when": "A parcel."},
        ]
        w = _watcher(broker, red_png, rules)
        w.start()
        try:
            live.wait(lambda m: m.get(AVAIL) == b"online")
            live.wait(lambda m: m.get("ifseen/porch/rule/person/active") == b"ON")
            live.wait(lambda m: "ifseen/porch/camera/fire" in m)
            cfg = json.loads(
                live.latest["homeassistant/binary_sensor/ifseen_porch/person_active/config"]
            )
            assert cfg["device_class"] == "occupancy" and cfg["device"]["name"] == "Porch"
            assert live.latest["ifseen/porch/camera/fire"][:2] == b"\xff\xd8"  # JPEG

            live.publish("ifseen/porch/watching/set", "OFF")
            live.wait(lambda m: m.get("ifseen/porch/watching") == b"OFF")
            assert w.paused
            live.publish("ifseen/porch/watching/set", "ON")
            live.wait(lambda m: m.get("ifseen/porch/watching") == b"ON")
        finally:
            w.stop()
        live.wait(lambda m: m.get(AVAIL) == b"offline")

        # restart with one rule removed: its retained discovery config must be cleared
        parcel_cfg = "homeassistant/sensor/ifseen_porch/parcel_probability/config"
        assert parcel_cfg in live.latest
        w2 = _watcher(broker, red_png, rules[:1])
        w2.start()
        try:
            live.wait(lambda m: parcel_cfg not in m)
            live.wait(lambda m: "ifseen/porch/rule/parcel/active" not in m)
            live.wait(lambda m: m.get(AVAIL) == b"online")
        finally:
            w2.stop()
    finally:
        live.close()

    # a fresh subscriber sees only the current retained configs
    fresh = Listener(broker, NODE)
    try:
        fresh.wait(lambda m: any("person_active" in t for t in m))
        time.sleep(0.3)
        assert not any("parcel" in t for t in fresh.latest if t.startswith("homeassistant/"))
    finally:
        fresh.close()


def test_unreachable_broker_does_not_block_watching(red_png):
    w = Watcher(
        source={"file": str(red_png)},
        provider=ConstProvider(0.95),
        every="100ms",
        rules=[{"name": "r", "when": "R."}],
        mqtt={"host": "127.0.0.1", "port": _free_port()},
    )
    w.on("r")(lambda e: None)
    t0 = time.time()
    assert w.run(max_ticks=3) == "done"
    assert time.time() - t0 < 5
    assert w.state()["rules"][0]["fires"] == 1
