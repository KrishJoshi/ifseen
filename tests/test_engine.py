from __future__ import annotations

import pytest
from conftest import solid_jpeg

from ifseen.actions import ActionRunner
from ifseen.config import load_config
from ifseen.engine import Engine
from ifseen.media import Sample
from ifseen.providers import Decision, Provider, ProviderConfigError, ProviderError
from ifseen.sources import Source, SourceExhausted


class ScriptedProvider(Provider):
    name = "scripted"
    supports = frozenset({"image", "audio"})
    price_per_m_input = 1.0

    def __init__(self, script):
        super().__init__("script")
        self.script = list(script)
        self.calls = 0

    def decide(self, sample, questions, context=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else {}
        if isinstance(item, Exception):
            raise item
        return Decision(
            probs={q.key: item.get(q.key, 0.0) for q in questions}, input_tokens=1000, latency_ms=5
        )


class ListSource(Source):
    kind = "list"
    provides = frozenset({"image"})

    def __init__(self, samples):
        self.samples = list(samples)

    def read(self):
        if not self.samples:
            raise SourceExhausted("done")
        return self.samples.pop(0)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def frames(n, colours=None):
    colours = colours or [(i * 9 % 255, 100, 200 - i * 7 % 200) for i in range(n)]
    return [Sample(jpeg=solid_jpeg(c)) for c in colours[:n]]


def make(rules, script, samples, **cfg):
    clock = FakeClock()
    config = load_config({"source": "screen", "rules": rules, "every": "1s", **cfg})
    events = []
    log = []
    provider = ScriptedProvider(script)
    runner = ActionRunner(log=lambda lvl, m: log.append((lvl, m)), background=False)
    engine = Engine(
        config,
        ListSource(samples),
        provider,
        runner,
        listener=events.append,
        clock=clock,
        sleep=clock.sleep,
    )
    return engine, events, provider, log, clock


def fires(events):
    return [e["rule"] for e in events if e["event"] == "fire"]


def test_fires_once_per_occurrence_then_rearms():
    probs = [0.1, 0.9, 0.95, 0.9, 0.7, 0.5, 0.9]
    engine, events, *_ = make(
        [{"name": "r", "when": "x", "cooldown": 0, "then": ["log"]}],
        [{"r": p} for p in probs],
        frames(len(probs)),
        skip_unchanged=False,
    )
    engine.run()
    # fires at 0.9 (tick 2); stays disarmed through 0.95/0.9/0.7 (0.7 > 0.8-0.15);
    # re-arms at 0.5; fires again at the last 0.9
    assert fires(events) == ["r", "r"]


def test_consecutive_requirement():
    probs = [0.9, 0.1, 0.9, 0.9, 0.9]
    engine, events, *_ = make(
        [{"name": "r", "when": "x", "for": 3, "then": ["log"]}],
        [{"r": p} for p in probs],
        frames(5),
        skip_unchanged=False,
    )
    engine.run()
    assert fires(events) == ["r"]
    fire_index = next(i for i, e in enumerate(events) if e["event"] == "fire")
    decisions_before = [e for e in events[:fire_index] if e["event"] == "decision"]
    assert len(decisions_before) == 5


def test_cooldown_blocks_refire():
    probs = [0.9, 0.1, 0.9, 0.1, 0.9]
    engine, events, *_ = make(
        [{"name": "r", "when": "x", "cooldown": "2.5s", "then": ["log"]}],
        [{"r": p} for p in probs],
        frames(5),
        skip_unchanged=False,
    )
    engine.run()
    # t=0 fire, t=2 blocked by 2.5s cooldown, t=4 fires
    assert fires(events) == ["r", "r"]


def test_exit_action_stops_engine():
    engine, events, provider, *_ = make(
        [{"name": "r", "when": "x", "then": ["exit"]}],
        [{"r": 0.1}, {"r": 0.95}, {"r": 0.95}],
        frames(3),
        skip_unchanged=False,
    )
    reason = engine.run()
    assert reason == "rule 'r' fired"
    assert provider.calls == 2


def test_unchanged_frames_skip_api_calls():
    same = [Sample(jpeg=solid_jpeg((10, 200, 10))) for _ in range(5)]
    engine, events, provider, *_ = make(
        [{"name": "r", "when": "x", "for": 3, "then": ["log"]}], [{"r": 0.9}], same
    )
    engine.run()
    assert provider.calls == 1
    assert engine.stats.skipped == 4
    # reused answers still count toward the consecutive requirement
    assert fires(events) == ["r"]


def test_max_skip_forces_refresh():
    same = [Sample(jpeg=solid_jpeg((10, 200, 10))) for _ in range(6)]
    engine, _, provider, *_ = make(
        [{"name": "r", "when": "x"}], [{"r": 0.1}] * 6, same, max_skip="2s"
    )
    engine.run()
    assert provider.calls == 3  # t=0, t=2, t=4 - not 6


def test_silent_audio_counts_as_no_and_skips():
    quiet = [Sample(wav=b"RIFF....", audio_rms=5.0) for _ in range(3)]
    clock = FakeClock()
    config = load_config(
        {"source": {"mic": {"silence_rms": 100}}, "rules": [{"name": "r", "when": "crying"}]}
    )
    provider = ScriptedProvider([{"r": 0.99}] * 3)
    engine = Engine(
        config,
        ListSource(quiet),
        provider,
        ActionRunner(log=lambda *_: None, background=False),
        clock=clock,
        sleep=clock.sleep,
    )
    engine.run()
    assert provider.calls == 0
    assert engine.states[0].prob == 0.0


def test_provider_errors_back_off_and_recover():
    script = [ProviderError("boom"), ProviderError("boom"), {"r": 0.9}]
    engine, events, provider, _, clock = make(
        [{"name": "r", "when": "x", "then": ["log"]}], script, frames(3), skip_unchanged=False
    )
    engine.run()
    assert [e["event"] for e in events].count("error") == 2
    assert fires(events) == ["r"]
    assert engine.stats.errors == 2
    assert clock.t > 3  # backoff added waiting time


def test_config_errors_are_fatal():
    engine, *_ = make([{"name": "r", "when": "x"}], [ProviderConfigError("no key")], frames(2))
    with pytest.raises(ProviderConfigError):
        engine.run()


def test_cost_tracking():
    engine, *_ = make(
        [{"name": "r", "when": "x"}], [{"r": 0.1}] * 3, frames(3), skip_unchanged=False
    )
    engine.run()
    assert engine.stats.input_tokens == 3000
    assert engine.stats.cost_usd == pytest.approx(0.003)


def test_many_rules_one_call_per_tick():
    rules = [{"name": f"r{i}", "when": f"thing {i}"} for i in range(50)]
    engine, _, provider, *_ = make(rules, [{}] * 4, frames(4), skip_unchanged=False)
    engine.run()
    assert provider.calls == 4


def test_low_threshold_rule_can_rearm():
    probs = [0.2, 0.01, 0.2]
    engine, events, *_ = make(
        [{"name": "r", "when": "x", "threshold": 0.1, "cooldown": 0, "then": ["log"]}],
        [{"r": p} for p in probs],
        frames(3),
        skip_unchanged=False,
    )
    engine.run()
    assert fires(events) == ["r", "r"]


class BrokenSource(ListSource):
    def read(self):
        raise OSError("half-written file")


def test_unexpected_source_errors_are_reported_then_fatal():
    from ifseen.sources import SourceError

    clock = FakeClock()
    config = load_config({"source": "screen", "rules": [{"name": "r", "when": "x"}]})
    events = []
    engine = Engine(
        config,
        BrokenSource([]),
        ScriptedProvider([]),
        ActionRunner(log=lambda *_: None, background=False),
        listener=events.append,
        clock=clock,
        sleep=clock.sleep,
    )
    with pytest.raises(SourceError, match="10 times in a row"):
        engine.run()
    errors = [e for e in events if e["event"] == "error"]
    assert len(errors) == 10 and errors[0]["message"] == "capture failed: OSError"
