"""The watch loop: capture -> (skip if unchanged) -> ask every rule in one call -> fire."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from .actions import ActionRunner, FireEvent
from .config import Rule, WatchConfig
from .constants import PREFILTER_KEY, PREFILTER_SKIP_REASON
from .media import Sample, signature_distance, thumbnail_signature
from .providers import Decision, Provider, ProviderConfigError, ProviderError, Question
from .sources import Source, SourceError, SourceExhausted

_MAX_CONSECUTIVE_SOURCE_ERRORS = 10
_MAX_BACKOFF_SECONDS = 60.0

Listener = Callable[[dict[str, Any]], None]


@dataclass
class RuleState:
    rule: Rule
    prob: float = 0.0
    streak: int = 0
    armed: bool = True
    last_fired: float | None = None
    fires: int = 0
    history: list[float] = field(default_factory=list)

    def update(self, prob: float, now: float) -> bool:
        """Feed one probability. Returns True if the rule should fire now."""
        r = self.rule
        self.prob = prob
        self.history = (self.history + [prob])[-40:]
        if prob >= r.threshold:
            self.streak += 1
        else:
            self.streak = 0
            # never let the re-arm level reach 0, or a low-threshold rule could never re-arm
            if prob < max(r.threshold - r.hysteresis, r.threshold / 2):
                self.armed = True
        cooled = self.last_fired is None or now - self.last_fired >= r.cooldown
        if self.armed and self.streak >= r.consecutive and cooled:
            self.armed = False
            self.last_fired = now
            self.fires += 1
            return True
        return False

    @property
    def status(self) -> str:
        if self.streak and self.streak < self.rule.consecutive:
            return f"confirming {self.streak}/{self.rule.consecutive}"
        if not self.armed:
            return "fired, clearing"
        return "watching"


@dataclass
class Stats:
    started: float = field(default_factory=time.time)
    ticks: int = 0
    calls: int = 0
    skipped: int = 0
    errors: int = 0
    input_tokens: int = 0
    cost_usd: float = 0.0
    last_latency_ms: float = 0.0
    last_skip_reason: str = ""
    prefilter_calls: int = 0
    prefiltered: int = 0
    last_prefilter_prob: float | None = None

    def cost_per_hour(self) -> float:
        elapsed = max(1.0, time.time() - self.started)
        return self.cost_usd * 3600 / elapsed


class Engine:
    def __init__(
        self,
        cfg: WatchConfig,
        source: Source,
        provider: Provider,
        actions: ActionRunner,
        listener: Listener | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        prefilter: Provider | None = None,
    ):
        if (prefilter is None) != (cfg.prefilter is None):
            raise ValueError("pass a prefilter provider exactly when the config has a prefilter")
        self.cfg = cfg
        self.source = source
        self.provider = provider
        self.prefilter = prefilter
        self.prefilter_question = (
            Question(
                PREFILTER_KEY,
                cfg.prefilter.when,
                cfg.prefilter.true_means,
                cfg.prefilter.false_means,
            )
            if cfg.prefilter is not None
            else None
        )
        self.actions = actions
        self.listener = listener or (lambda e: None)
        self.clock = clock
        self.sleep = sleep
        self.states = [RuleState(r) for r in cfg.rules]
        self.questions = [Question(r.name, r.when, r.true_means, r.false_means) for r in cfg.rules]
        self.stats = Stats()
        self.stopped = False
        self.stop_reason = ""
        self._last_sig: bytes | None = None
        self._last_call_at: float | None = None
        self._last_probs: dict[str, float] = {}
        self._backoff = 0.0
        self._source_errors = 0

    # -- public ----------------------------------------------------------------------------

    def run(self, max_ticks: int | None = None) -> str:
        self._emit(
            "start",
            source=self.source.describe(),
            provider=self.provider.describe(),
            rules=[r.name for r in self.cfg.rules],
            **({"prefilter": self.prefilter.describe()} if self.prefilter else {}),
        )
        try:
            while not self.stopped and (max_ticks is None or self.stats.ticks < max_ticks):
                t0 = self.clock()
                self.tick()
                if self.stopped:
                    break
                wait = self.cfg.every + self._backoff - (self.clock() - t0)
                if wait > 0:
                    self.sleep(wait)
        except KeyboardInterrupt:
            self.stop("interrupted")
        if not self.stop_reason:
            self.stop_reason = "done"
        self._emit("stop", reason=self.stop_reason)
        return self.stop_reason

    def stop(self, reason: str) -> None:
        self.stopped = True
        self.stop_reason = reason

    def tick(self) -> None:
        self.stats.ticks += 1
        now = self.clock()
        try:
            sample = self.source.read()
            self._source_errors = 0
        except SourceExhausted as e:
            self.stop(str(e))
            return
        except Exception as e:  # a flaky camera or half-written file shouldn't kill the watcher
            self._source_errors += 1
            self.stats.errors += 1
            message = (
                str(e) if isinstance(e, SourceError) else f"capture failed: {type(e).__name__}"
            )
            self._emit("error", message=message)
            if self._source_errors >= _MAX_CONSECUTIVE_SOURCE_ERRORS:
                if isinstance(e, SourceError):
                    raise
                raise SourceError(
                    f"{message} ({_MAX_CONSECUTIVE_SOURCE_ERRORS} times in a row)"
                ) from e
            return

        probs = self._decide(sample, now)
        if probs is None:
            return
        self._apply(probs, sample, now)

    # -- internals -------------------------------------------------------------------------

    def _decide(self, sample: Sample, now: float) -> dict[str, float] | None:
        skip = self._skip_reason(sample, now)
        if skip == "silence":
            self.stats.skipped += 1
            self.stats.last_skip_reason = skip
            # Silence is evidence that sound-based conditions are false.
            return {q.key: 0.0 for q in self.questions}
        if skip:
            self.stats.skipped += 1
            self.stats.last_skip_reason = skip
            return dict(self._last_probs)
        gate: float | None = None
        tokens = 0
        if self.prefilter is not None:
            pre = self._ask_prefilter(sample)
            if pre is None:
                return None
            gate = pre.probs.get(PREFILTER_KEY, 0.0)
            tokens = pre.input_tokens
            if gate < self.cfg.prefilter.threshold:  # type: ignore[union-attr]
                # Fail closed: nothing fires unless the cheap check lets the main model look.
                zeros = {q.key: 0.0 for q in self.questions}
                self.stats.skipped += 1
                self.stats.prefiltered += 1
                self.stats.last_skip_reason = PREFILTER_SKIP_REASON
                self.stats.last_latency_ms = pre.latency_ms
                self._remember(sample, now, zeros)
                self._emit(
                    "decision",
                    probs=zeros,
                    latency_ms=round(pre.latency_ms, 1),
                    tokens=tokens,
                    prefilter=round(gate, 4),
                    skipped=PREFILTER_SKIP_REASON,
                )
                return zeros
        decision = self._call(self.provider, sample, self.questions)
        if decision is None:
            return None
        self.stats.calls += 1
        self.stats.input_tokens += decision.input_tokens
        self.stats.cost_usd += self.provider.cost_usd(decision.input_tokens)
        self.stats.last_latency_ms = decision.latency_ms
        self._remember(sample, now, decision.probs)
        extra = {} if gate is None else {"prefilter": round(gate, 4)}
        self._emit(
            "decision",
            probs={k: round(v, 4) for k, v in decision.probs.items()},
            latency_ms=round(decision.latency_ms, 1),
            tokens=decision.input_tokens + tokens,
            **extra,
        )
        return decision.probs

    def _ask_prefilter(self, sample: Sample) -> Decision | None:
        assert self.prefilter is not None and self.prefilter_question is not None
        if sample.has_audio and "audio" not in self.prefilter.supports:
            sample = replace(sample, wav=None, audio_rms=0.0)
        decision = self._call(self.prefilter, sample, [self.prefilter_question])
        if decision is None:
            return None
        self.stats.prefilter_calls += 1
        self.stats.input_tokens += decision.input_tokens
        self.stats.cost_usd += self.prefilter.cost_usd(decision.input_tokens)
        self.stats.last_prefilter_prob = decision.probs.get(PREFILTER_KEY, 0.0)
        return decision

    def _call(
        self, provider: Provider, sample: Sample, questions: list[Question]
    ) -> Decision | None:
        try:
            decision = provider.decide(sample, questions, self.cfg.context)
        except ProviderConfigError:
            raise
        except ProviderError as e:
            self.stats.errors += 1
            self._backoff = min(_MAX_BACKOFF_SECONDS, max(self.cfg.every, self._backoff * 2))
            self._emit("error", message=str(e), retry_in=round(self._backoff, 1))
            return None
        self._backoff = 0.0
        return decision

    def _remember(self, sample: Sample, now: float, probs: dict[str, float]) -> None:
        self._last_call_at = now
        self._last_probs = probs
        if sample.jpeg is not None:
            self._last_sig = thumbnail_signature(sample.jpeg)

    def _skip_reason(self, sample: Sample, now: float) -> str:
        if not self.cfg.skip_unchanged:
            return ""
        silent = sample.has_audio and sample.audio_rms < self._silence_rms()
        if silent and not sample.has_image:
            return "silence"
        if self._last_call_at is None or now - self._last_call_at >= self.cfg.max_skip:
            return ""
        if sample.has_image:
            sig = thumbnail_signature(sample.jpeg)  # type: ignore[arg-type]
            unchanged = (
                self._last_sig is not None
                and signature_distance(sig, self._last_sig) < self.cfg.change_threshold
            )
            if unchanged and (not sample.has_audio or silent):
                return "unchanged"
            return ""
        return ""

    def _silence_rms(self) -> float:
        mic = self.cfg.source.mic
        return mic.silence_rms if mic is not None else 0.0

    def _apply(self, probs: dict[str, float], sample: Sample, now: float) -> None:
        for state in self.states:
            if not state.update(probs.get(state.rule.name, 0.0), now):
                continue
            event = FireEvent(state.rule, state.prob, time.time(), sample, self.source.describe())
            self._emit(
                "fire", rule=state.rule.name, when=state.rule.when, probability=round(state.prob, 4)
            )
            if self.actions.run(state.rule.then, event):
                self.stop(f"rule '{state.rule.name}' fired")

    def _emit(self, kind: str, **data: Any) -> None:
        self.listener({"event": kind, "time": round(time.time(), 3), **data})
