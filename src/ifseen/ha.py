"""Home Assistant MQTT discovery: topic layout and entity config payloads (pure functions)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import MqttConfig, Rule
from .constants import (
    HA_ORIGIN_URL,
    MQTT_DEFAULT_WATCHER_ID,
    MQTT_OFFLINE,
    MQTT_ONLINE,
    MQTT_PAYLOAD_OFF,
    MQTT_PAYLOAD_ON,
    VERSION,
)

Payload = dict[str, Any]


def resolve_watcher_id(cfg: MqttConfig, fallback: str | None = None) -> str:
    """`mqtt.id`, else a slug of `mqtt.name`, else of the caller's label (file stem, watcher
    name, serve id), else "ifseen". It's baked into topics and unique_ids, so keep it stable."""
    if cfg.id:
        return cfg.id
    for text in (cfg.name, fallback):
        if text:
            slug = re.sub(r"[^a-z0-9_]+", "-", text.lower()).strip("-")[:64].strip("-")
            if slug:
                return slug
    return MQTT_DEFAULT_WATCHER_ID


def humanize(name: str) -> str:
    """'person-at-door' -> 'Person at door'."""
    words = re.sub(r"[-_]+", " ", name).strip()
    return words[:1].upper() + words[1:] if words else name


@dataclass(frozen=True)
class Topics:
    """Every topic one watcher uses: ``<base_topic>/<watcher_id>/...``."""

    base_topic: str
    watcher_id: str

    @property
    def root(self) -> str:
        return f"{self.base_topic}/{self.watcher_id}"

    @property
    def availability(self) -> str:
        return f"{self.root}/availability"

    @property
    def state(self) -> str:
        return f"{self.root}/state"

    @property
    def event(self) -> str:
        return f"{self.root}/event"

    @property
    def fire_image(self) -> str:
        return f"{self.root}/camera/fire"

    @property
    def frame(self) -> str:
        return f"{self.root}/camera/frame"

    @property
    def watching(self) -> str:
        return f"{self.root}/watching"

    @property
    def watching_set(self) -> str:
        return f"{self.root}/watching/set"

    @property
    def rules_wildcard(self) -> str:
        return f"{self.root}/rule/#"

    def stale_rule_topic(self, topic: str, rules: set[str]) -> bool:
        """A retained ``rule/<name>/...`` state topic for a rule that no longer exists."""
        head = f"{self.root}/rule/"
        if not topic.startswith(head):
            return False
        parts = topic[len(head) :].split("/")
        return len(parts) == 2 and parts[1] in ("active", "probability") and parts[0] not in rules

    def rule_active(self, rule: str) -> str:
        return f"{self.root}/rule/{rule}/active"

    def rule_probability(self, rule: str) -> str:
        return f"{self.root}/rule/{rule}/probability"


def node_id(watcher_id: str) -> str:
    return f"ifseen_{watcher_id}"


def unique_id(watcher_id: str, obj: str) -> str:
    return f"ifseen_{watcher_id}_{obj}"


def discovery_topic(prefix: str, component: str, watcher_id: str, obj: str) -> str:
    return f"{prefix}/{component}/{node_id(watcher_id)}/{obj}/config"


def discovery_wildcard(prefix: str, watcher_id: str) -> str:
    """Matches every discovery config this watcher could have published, for cleanup."""
    return f"{prefix}/+/{node_id(watcher_id)}/+/config"


def is_own_discovery_topic(prefix: str, watcher_id: str, topic: str) -> bool:
    """Does `topic` match :func:`discovery_wildcard`? Checked explicitly because some brokers
    deliver retained messages that don't match the subscription filter, and the cleanup must
    never clear anything outside this watcher's discovery configs."""
    head = f"{prefix}/"
    if not topic.startswith(head):
        return False
    parts = topic[len(head) :].split("/")
    return (
        len(parts) == 4 and parts[1] == node_id(watcher_id) and parts[3] == "config" and all(parts)
    )


def device_payload(watcher_id: str, device_name: str, model: str) -> Payload:
    return {
        "identifiers": [node_id(watcher_id)],
        "name": device_name,
        "manufacturer": "ifseen",
        "model": model,
        "sw_version": VERSION,
    }


def origin_payload() -> Payload:
    return {"name": "ifseen", "sw_version": VERSION, "support_url": HA_ORIGIN_URL}


def discovery_configs(
    cfg: MqttConfig,
    watcher_id: str,
    device_name: str,
    rules: list[Rule],
    *,
    model: str = "watcher",
    has_image: bool = True,
) -> dict[str, Payload]:
    """{discovery topic: config payload} for every entity this watcher should have.

    Empty when discovery is off, so a cleanup pass removes anything published earlier.
    """
    if not cfg.discovery:
        return {}
    t = Topics(cfg.base_topic, watcher_id)
    prefix = cfg.discovery_prefix
    common = {
        "availability_topic": t.availability,
        "payload_available": MQTT_ONLINE,
        "payload_not_available": MQTT_OFFLINE,
        "device": device_payload(watcher_id, device_name, model),
        "origin": origin_payload(),
    }
    out: dict[str, Payload] = {}

    def add(component: str, obj: str, payload: Payload) -> None:
        out[discovery_topic(prefix, component, watcher_id, obj)] = {
            "unique_id": unique_id(watcher_id, obj),
            **payload,
            **common,
        }

    for rule in rules:
        label = humanize(rule.name)
        binary: Payload = {
            "name": label,
            "state_topic": t.rule_active(rule.name),
            "payload_on": MQTT_PAYLOAD_ON,
            "payload_off": MQTT_PAYLOAD_OFF,
            "json_attributes_topic": t.rule_probability(rule.name),
        }
        if rule.ha_device_class:
            binary["device_class"] = rule.ha_device_class
        else:
            binary["icon"] = "mdi:eye"
        add("binary_sensor", f"{rule.name}_active", binary)
        add(
            "sensor",
            f"{rule.name}_probability",
            {
                "name": f"{label} probability",
                "state_topic": t.rule_probability(rule.name),
                "value_template": "{{ value_json.probability }}",
                "json_attributes_topic": t.rule_probability(rule.name),
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "suggested_display_precision": 0,
                "icon": "mdi:percent",
            },
        )

    add(
        "sensor",
        "status",
        {
            "name": "Status",
            "state_topic": t.state,
            "value_template": "{{ value_json.status }}",
            "json_attributes_topic": t.state,
            "entity_category": "diagnostic",
            "icon": "mdi:eye-check",
        },
    )
    add(
        "sensor",
        "cost_per_hour",
        {
            "name": "Cost per hour",
            "state_topic": t.state,
            "value_template": "{{ value_json.cost_per_hour }}",
            "unit_of_measurement": "$/h",
            "state_class": "measurement",
            "suggested_display_precision": 4,
            "entity_category": "diagnostic",
            "icon": "mdi:cash",
        },
    )
    add(
        "sensor",
        "calls",
        {
            "name": "Model calls",
            "state_topic": t.state,
            "value_template": "{{ value_json.calls }}",
            "state_class": "total_increasing",
            "entity_category": "diagnostic",
            "icon": "mdi:counter",
        },
    )
    add(
        "event",
        "trigger",
        {
            "name": "Trigger",
            "state_topic": t.event,
            "event_types": [r.name for r in rules],
            "icon": "mdi:bell-ring",
        },
    )
    if has_image and cfg.fire_image:
        add("camera", "last_trigger", {"name": "Last trigger", "topic": t.fire_image})
    if has_image and cfg.frame_every > 0:
        add("camera", "frame", {"name": "Latest frame", "topic": t.frame})
    if cfg.pause_switch:
        add(
            "switch",
            "watching",
            {
                "name": "Watching",
                "state_topic": t.watching,
                "command_topic": t.watching_set,
                "payload_on": MQTT_PAYLOAD_ON,
                "payload_off": MQTT_PAYLOAD_OFF,
                "entity_category": "config",
                "icon": "mdi:eye",
            },
        )
    return out
