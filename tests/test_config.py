import pytest

from ifseen.config import ConfigError, expand_env, load_config, load_config_file, parse_duration
from ifseen.constants import DEFAULT_PREFILTER_THRESHOLD
from ifseen.recipes import recipe_data, recipe_names


@pytest.mark.parametrize(
    "value,expected",
    [
        ("500ms", 0.5),
        ("2s", 2.0),
        ("5m", 300.0),
        ("1h", 3600.0),
        (3, 3.0),
        ("1.5", 1.5),
    ],
)
def test_parse_duration(value, expected):
    assert parse_duration(value) == expected


@pytest.mark.parametrize("bad", ["soon", "5 days", "", True])
def test_parse_duration_rejects(bad):
    with pytest.raises(ConfigError):
        parse_duration(bad)


def minimal(**over):
    data = {"source": "screen", "rules": [{"name": "r", "when": "something"}]}
    data.update(over)
    return data


def test_shorthands():
    cfg = load_config(
        minimal(
            source={"camera": "rtsp://cam/stream", "mic": True}, provider="gemini", every="500ms"
        )
    )
    assert cfg.source.camera.device == "rtsp://cam/stream"
    assert cfg.source.mic is not None
    assert cfg.source.visual_kind == "camera"
    assert cfg.provider.name == "gemini"
    assert cfg.every == 0.5


def test_screen_int_and_file_str():
    assert load_config(minimal(source={"screen": 2})).source.screen.monitor == 2
    assert load_config(minimal(source={"file": "a.mp4"})).source.file.path == "a.mp4"


def test_rule_defaults_and_actions():
    cfg = load_config(
        minimal(
            rules=[
                {
                    "name": "door",
                    "when": "a person at the door",
                    "for": 3,
                    "cooldown": "2m",
                    "then": ["notify", "say hello", {"ntfy": "topic"}, "exit"],
                }
            ]
        )
    )
    r = cfg.rules[0]
    assert r.consecutive == 3 and r.cooldown == 120 and r.threshold == 0.8
    assert r.then == [{"notify": True}, {"shell": "say hello"}, {"ntfy": "topic"}, {"exit": True}]


@pytest.mark.parametrize(
    "data,msg",
    [
        (minimal(source={"screen": {}, "camera": 0}), "pick one visual source"),
        (minimal(source={}), "source needs one of"),
        (minimal(rules=[]), "at least one rule"),
        (minimal(rules=[{"name": "a", "when": "x"}, {"name": "a", "when": "y"}]), "duplicate"),
        (minimal(rules=[{"name": "has space", "when": "x"}]), "rule name"),
        (minimal(rules=[{"name": "a", "when": "x", "threshold": 1.5}]), "threshold"),
        (minimal(rules=[{"name": "a", "when": "x", "then": [{"explode": 1}]}]), "unknown action"),
        (minimal(every="50ms"), "at least 100ms"),
        (minimal(provider="skynet"), "provider"),
        (minimal(bogus=1), "bogus"),
    ],
)
def test_validation_errors(data, msg):
    with pytest.raises(ConfigError, match=msg):
        load_config(data)


def test_expand_env():
    env = {"TOPIC": "abc"}
    assert expand_env({"a": ["${TOPIC}", "${MISSING:-dflt}", "x"]}, env) == {
        "a": ["abc", "dflt", "x"]
    }
    with pytest.raises(ConfigError, match="MISSING"):
        expand_env("${MISSING}", env)


def test_load_config_file_errors(tmp_path):
    with pytest.raises(ConfigError, match="no such file"):
        load_config_file(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n")
    with pytest.raises(ConfigError, match="mapping"):
        load_config_file(bad)


@pytest.mark.parametrize("name", recipe_names())
def test_every_recipe_is_valid(name):
    cfg = load_config(recipe_data(name))
    assert cfg.rules
    for rule in cfg.rules:
        assert rule.when.endswith(".")


def test_recipes_exist():
    assert {"doorbell", "build-watcher", "meeting-radar", "print-failure"} <= set(recipe_names())


def test_examples_are_valid(monkeypatch):
    from pathlib import Path

    for var in ("OCTOPRINT_URL", "NTFY_TOPIC", "HA_TOKEN", "MQTT_PASSWORD"):
        monkeypatch.setenv(var, "x")
    examples = sorted((Path(__file__).parent.parent / "examples").glob("*.yaml"))
    assert examples
    for path in examples:
        assert load_config_file(path).rules


def test_numeric_camera_and_screen_shorthands():
    assert load_config(minimal(source={"camera": 1})).source.camera.device == 1
    assert load_config(minimal(source={"camera": True})).source.camera.device == 0
    assert load_config(minimal(source={"screen": 0})).source.screen.monitor == 0
    assert load_config(minimal(source={"screen": 2})).source.screen.monitor == 2


def test_mic_seconds_and_hysteresis_validated():
    with pytest.raises(ConfigError, match="seconds"):
        load_config(minimal(source={"mic": {"seconds": -1}}))
    with pytest.raises(ConfigError, match="hysteresis"):
        load_config(minimal(rules=[{"name": "a", "when": "x", "hysteresis": -0.1}]))


def test_prefilter_config():
    cfg = load_config(minimal(prefilter={"provider": "mock", "when": "  A person is visible. "}))
    assert cfg.prefilter.provider.name == "mock"
    assert cfg.prefilter.when == "A person is visible."
    assert cfg.prefilter.threshold == DEFAULT_PREFILTER_THRESHOLD
    assert load_config(minimal()).prefilter is None
    cfg = load_config(
        minimal(prefilter={"provider": {"name": "mock", "seed": 1}, "when": "x", "threshold": 0.3})
    )
    assert cfg.prefilter.threshold == 0.3 and cfg.prefilter.provider.seed == 1


@pytest.mark.parametrize(
    "prefilter,msg",
    [
        ({"provider": "mock", "when": "x", "threshold": 1.0}, "threshold"),
        ({"provider": "mock", "when": "x", "threshold": 0}, "threshold"),
        ({"provider": "mock", "when": "   "}, "cannot be empty"),
        ({"provider": "auto", "when": "x"}, "explicit provider"),
        ({"when": "x"}, "provider"),
        ({"provider": "mock"}, "when"),
        ({"provider": "mock", "when": "x", "bogus": 1}, "bogus"),
    ],
)
def test_prefilter_validation(prefilter, msg):
    with pytest.raises(ConfigError, match=msg):
        load_config(minimal(prefilter=prefilter))
