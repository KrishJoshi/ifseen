"""Publish a watcher's rule states to MQTT, with Home Assistant discovery.

The bridge is an engine observer: it runs on the engine thread at the end of every tick and
only enqueues publishes (paho's network loop runs on its own thread), so a slow or dead broker
never slows the watch loop. Every failure is logged and swallowed.
"""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .config import ConfigError, MqttConfig, Rule, WatchConfig
from .constants import (
    MQTT_CLOSE_FLUSH_SECONDS,
    MQTT_MAX_QUEUED_MESSAGES,
    MQTT_OFFLINE,
    MQTT_ONLINE,
    MQTT_PAYLOAD_OFF,
    MQTT_PAYLOAD_ON,
    MQTT_PROB_DECIMALS,
    MQTT_RECONNECT_MAX_SECONDS,
    MQTT_RECONNECT_MIN_SECONDS,
    MQTT_STATS_INTERVAL_SECONDS,
)
from .ha import (
    Topics,
    discovery_configs,
    discovery_wildcard,
    humanize,
    is_own_discovery_topic,
    resolve_watcher_id,
)

if TYPE_CHECKING:
    from .engine import Engine
    from .media import Sample

log = logging.getLogger("ifseen.mqtt")

Log = Callable[[str, str], None]  # (level, message), same as ActionRunner's
ClientFactory = Callable[[str], Any]  # client_id -> paho-compatible client


def paho_client_factory(client_id: str) -> Any:
    try:
        import paho.mqtt.client as paho
    except ImportError as e:
        raise ConfigError("the mqtt: section needs paho-mqtt: pip install 'ifseen[mqtt]'") from e
    return paho.Client(
        paho.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=paho.MQTTv311
    )


def _iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


class MqttBridge:
    """One MQTT connection per watcher. Lifecycle: ``bind(engine)``, ``start()``, the engine
    calls ``observe`` every tick, then ``close(status)``."""

    def __init__(
        self,
        cfg: MqttConfig,
        rules: list[Rule],
        *,
        fallback_id: str | None = None,
        has_image: bool = True,
        model: str = "watcher",
        log_fn: Log | None = None,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ):
        self.cfg = cfg
        self.rules = list(rules)
        self._rule_names = {r.name for r in self.rules}
        self.watcher_id = resolve_watcher_id(cfg, fallback_id)
        self.device_name = cfg.name or humanize(self.watcher_id)
        self.topics = Topics(cfg.base_topic, self.watcher_id)
        self.has_image = has_image
        self.discovery = discovery_configs(
            cfg, self.watcher_id, self.device_name, self.rules, model=model, has_image=has_image
        )
        self._log_fn = log_fn
        self._clock = clock
        self._wall = wall
        self._lock = threading.RLock()
        self._engine: Engine | None = None
        self._connected = False
        self._closed = False
        self._cache: dict[str, bytes] = {}  # retained topic -> last payload sent this session
        self._fires: dict[str, int] = {}
        self._last_fired: dict[str, float] = {}
        self._fire_jpeg: bytes | None = None
        self._last_frame_at: float | None = None
        self._last_stats_at: float | None = None
        self._status = "starting"
        factory = client_factory or paho_client_factory
        client_id = cfg.client_id or f"ifseen-{self.watcher_id}-{uuid.uuid4().hex[:6]}"
        self.client = factory(client_id)
        self._configure_client()

    # -- lifecycle -------------------------------------------------------------------------

    def bind(self, engine: Engine) -> None:
        self._engine = engine
        self._fires = {s.rule.name: s.fires for s in engine.states}

    def start(self) -> None:
        """Connect in the background; never blocks or raises for an unreachable broker."""
        self._status = "watching"
        try:
            self.client.connect_async(self.cfg.host, self.cfg.port, self.cfg.keepalive)
            self.client.loop_start()
        except Exception as e:
            self._warn(f"mqtt: could not start connecting to {self.cfg.host}: {type(e).__name__}")

    def close(self, status: str = "stopped") -> None:
        """Publish the final status and ``offline``, then disconnect."""
        with self._lock:
            if self._closed:
                return
            self._status = status
            info = None
            try:
                if self._connected:
                    self._publish_rules()
                    self._publish_device(force=True)
                    info = self.client.publish(
                        self.topics.availability, MQTT_OFFLINE, qos=1, retain=True
                    )
            except Exception as e:
                self._warn(f"mqtt: final publish failed: {type(e).__name__}")
            self._closed = True
        with contextlib.suppress(Exception):
            if info is not None:
                info.wait_for_publish(MQTT_CLOSE_FLUSH_SECONDS)
        with contextlib.suppress(Exception):
            self.client.disconnect()
        with contextlib.suppress(Exception):
            self.client.loop_stop()

    @property
    def connected(self) -> bool:
        return self._connected

    # -- engine observer -------------------------------------------------------------------

    def observe(self, engine: Engine, sample: Sample | None) -> None:
        try:
            with self._lock:
                if self._closed:
                    return
                self._engine = engine
                self._status = "paused" if engine.paused else "watching"
                self._note_fires(sample)
                if not self._connected:
                    return
                self._publish_rules()
                self._publish_device()
                self._maybe_publish_frame(sample)
        except Exception as e:
            self._warn(f"mqtt: publish failed: {type(e).__name__}")

    # -- internals -------------------------------------------------------------------------

    def _configure_client(self) -> None:
        c, cfg = self.client, self.cfg
        if cfg.username is not None:
            password = cfg.password.get_secret_value() if cfg.password is not None else None
            c.username_pw_set(cfg.username, password)
        if cfg.tls is not None:
            c.tls_set(ca_certs=cfg.tls.ca_certs, certfile=cfg.tls.certfile, keyfile=cfg.tls.keyfile)
            if cfg.tls.insecure:
                c.tls_insecure_set(True)
        c.will_set(self.topics.availability, MQTT_OFFLINE, qos=1, retain=True)
        c.reconnect_delay_set(MQTT_RECONNECT_MIN_SECONDS, MQTT_RECONNECT_MAX_SECONDS)
        c.max_queued_messages_set(MQTT_MAX_QUEUED_MESSAGES)
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason: Any, props: Any) -> None:
        if getattr(reason, "is_failure", False) or (isinstance(reason, int) and reason != 0):
            self._warn(f"mqtt: broker {self.cfg.host} refused the connection ({reason})")
            return
        try:
            with self._lock:
                if self._closed:
                    return
                self._connected = True
                self._cache.clear()  # resync everything: the broker may have lost retained state
                self._last_stats_at = None
                self._send(self.topics.availability, MQTT_ONLINE, qos=1, retain=True)
                for topic, payload in self.discovery.items():
                    self._send(topic, json.dumps(payload), qos=1, retain=True)
                client.subscribe(discovery_wildcard(self.cfg.discovery_prefix, self.watcher_id))
                client.subscribe(self.topics.rules_wildcard)
                if self.cfg.pause_switch:
                    client.subscribe(self.topics.watching_set)
                self._publish_rules()
                self._publish_device(force=True)
                if self._fire_jpeg is not None and self.has_image and self.cfg.fire_image:
                    self._send(self.topics.fire_image, self._fire_jpeg, qos=1, retain=True)
            self._info(f"mqtt: connected to {self.cfg.host}:{self.cfg.port} as {self.watcher_id}")
        except Exception as e:
            self._warn(f"mqtt: setup after connect failed: {type(e).__name__}")

    def _on_disconnect(
        self, client: Any, userdata: Any, flags: Any, reason: Any, props: Any
    ) -> None:
        was = self._connected
        self._connected = False
        if was and not self._closed:
            self._warn(f"mqtt: lost connection to {self.cfg.host}, reconnecting")

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            if msg.topic == self.topics.watching_set:
                self._command(msg.payload)
            elif msg.retain and msg.payload and self._is_stale(msg.topic):
                # a retained config/state for an entity we no longer have (rule removed or
                # renamed, camera or switch turned off): an empty retained payload deletes it
                with self._lock:
                    if self._connected and not self._closed:
                        self._send(msg.topic, b"", qos=1, retain=True)
                self._info(f"mqtt: removed stale retained topic {msg.topic}")
        except Exception as e:
            self._warn(f"mqtt: handling {msg.topic} failed: {type(e).__name__}")

    def _is_stale(self, topic: str) -> bool:
        if is_own_discovery_topic(self.cfg.discovery_prefix, self.watcher_id, topic):
            return topic not in self.discovery
        return self.topics.stale_rule_topic(topic, self._rule_names)

    def _command(self, payload: bytes) -> None:
        text = payload.decode("utf-8", "replace").strip().upper()
        engine = self._engine
        if engine is None or text not in (MQTT_PAYLOAD_ON, MQTT_PAYLOAD_OFF):
            return
        if text == MQTT_PAYLOAD_OFF:
            engine.pause()
        else:
            engine.resume()
        with self._lock:
            self._status = "paused" if engine.paused else "watching"
            if self._connected and not self._closed:
                self._publish_device(force=True)

    def _note_fires(self, sample: Sample | None) -> None:
        """Runs even while disconnected, so last_fired and the fire image stay correct."""
        engine = self._engine
        if engine is None:
            return
        for st in engine.states:
            name = st.rule.name
            if st.fires <= self._fires.get(name, 0):
                continue
            self._fires[name] = st.fires
            now = self._wall()
            self._last_fired[name] = now
            jpeg = sample.jpeg if sample is not None else None
            if jpeg is not None:
                self._fire_jpeg = jpeg
            if not self._connected:
                continue
            event = {
                "event_type": name,
                "probability": round(st.prob * 100, MQTT_PROB_DECIMALS),
                "time": _iso(now),
            }
            self._send(self.topics.event, json.dumps(event), qos=1, retain=False)
            if jpeg is not None and self.has_image and self.cfg.fire_image:
                self._send(self.topics.fire_image, jpeg, qos=1, retain=True)

    def _publish_rules(self) -> None:
        engine = self._engine
        if engine is None:
            return
        for st in engine.states:
            r = st.rule
            active = MQTT_PAYLOAD_ON if st.active else MQTT_PAYLOAD_OFF
            self._set(self.topics.rule_active(r.name), active)
            attrs = {
                "probability": round(st.prob * 100, MQTT_PROB_DECIMALS),
                "active": st.active,
                "threshold": round(r.threshold * 100, MQTT_PROB_DECIMALS),
                "streak": st.streak,
                "for": r.consecutive,
                "fires": st.fires,
                "last_fired": _iso(self._last_fired.get(r.name)),
                "when": r.when,
            }
            self._set(self.topics.rule_probability(r.name), json.dumps(attrs))

    def _publish_device(self, force: bool = False) -> None:
        engine = self._engine
        now = self._clock()
        last = self._cache.get(self.topics.state)
        status_changed = last is None or json.loads(last).get("status") != self._status
        due = self._last_stats_at is None or now - self._last_stats_at >= (
            MQTT_STATS_INTERVAL_SECONDS
        )
        if not (force or status_changed or due):
            return
        state: dict[str, Any] = {"status": self._status}
        if engine is not None:
            s = engine.stats
            state.update(
                {
                    "source": engine.source.describe(),
                    "provider": engine.provider.describe(),
                    "calls": s.calls,
                    "skipped": s.skipped,
                    "errors": s.errors,
                    "input_tokens": s.input_tokens,
                    "cost_usd": round(s.cost_usd, 6),
                    "cost_per_hour": round(s.cost_per_hour(), 6),
                }
            )
        self._last_stats_at = now
        self._set(self.topics.state, json.dumps(state))
        if self.cfg.pause_switch and engine is not None:
            paused = engine.paused or self._status in ("stopped", "error")
            self._set(self.topics.watching, MQTT_PAYLOAD_OFF if paused else MQTT_PAYLOAD_ON)

    def _maybe_publish_frame(self, sample: Sample | None) -> None:
        every = self.cfg.frame_every
        if not every or not self.has_image or sample is None or sample.jpeg is None:
            return
        now = self._clock()
        if self._last_frame_at is not None and now - self._last_frame_at < every:
            return
        self._last_frame_at = now
        self._send(self.topics.frame, sample.jpeg, qos=0, retain=False)

    def _set(self, topic: str, payload: str) -> None:
        """Publish a retained state only when it changed since the last (re)connect."""
        data = payload.encode()
        if self._cache.get(topic) == data:
            return
        if self._send(topic, data, qos=1, retain=True):
            self._cache[topic] = data

    def _send(self, topic: str, payload: str | bytes, qos: int, retain: bool) -> bool:
        if not self._connected:
            return False
        info = self.client.publish(topic, payload, qos=qos, retain=retain)
        rc = getattr(info, "rc", 0)
        return rc == 0

    def _info(self, message: str) -> None:
        if self._log_fn is not None:
            self._log_fn("info", message)
        else:
            log.info(message)

    def _warn(self, message: str) -> None:
        if self._log_fn is not None:
            self._log_fn("warn", message)
        else:
            log.warning(message)


def attach_bridge(
    cfg: WatchConfig,
    engine: Engine,
    *,
    fallback_id: str | None = None,
    log_fn: Log | None = None,
    client_factory: ClientFactory | None = None,
) -> MqttBridge | None:
    """Build a bridge for ``cfg.mqtt`` (None when there's no mqtt section) and register it as
    an engine observer. The caller still calls ``start()`` and ``close()``."""
    if cfg.mqtt is None:
        return None
    bridge = MqttBridge(
        cfg.mqtt,
        cfg.rules,
        fallback_id=fallback_id,
        has_image=cfg.source.visual_kind is not None,
        model=f"{engine.provider.name} watcher",
        log_fn=log_fn,
        client_factory=client_factory,
    )
    bridge.bind(engine)
    engine.observers.append(bridge.observe)
    return bridge
