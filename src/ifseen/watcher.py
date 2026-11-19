"""The long-running Python API: watch a source and call back when rules come true."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import dataclasses
import inspect
import logging
import queue
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .actions import Action, ActionRunner, FireEvent
from .config import (
    ConfigError,
    ProviderConfig,
    Rule,
    WatchConfig,
    expand_env,
    load_config,
    load_config_file,
    parse_duration,
    pretty_error,
)
from .constants import DEFAULT_EVERY_SECONDS, WATCHER_STOP_TIMEOUT_SECONDS
from .engine import Engine
from .media import Sample
from .oneshot import ProviderSpec
from .providers import Provider, ProviderConfigError
from .runtime import build_runtime, slugify
from .sources import Source, SourceError

log = logging.getLogger("ifseen")

Event = dict[str, Any]
"""An engine event: {"event": "start"|"decision"|"fire"|"error"|"stop"|"log", "time": ...}."""

RuleCallback = Callable[[FireEvent], Awaitable[None] | None]
EventCallback = Callable[[Event], Awaitable[None] | None]

_PLACEHOLDER_RULE = {"name": "placeholder", "when": "placeholder"}


class _Dispatcher:
    """Runs callbacks off the engine thread, in order. Async callbacks go to an event loop."""

    _STOP = object()

    def __init__(self, on_failure: Callable[[str, BaseException], None]):
        self._on_failure = on_failure
        self._queue: queue.SimpleQueue[Any] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._futures: list[concurrent.futures.Future[Any]] = []

    def start(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop
        self._futures = []
        self._thread = threading.Thread(target=self._work, name="ifseen-callbacks", daemon=True)
        self._thread.start()

    def submit(self, fn: Callable[[Any], Any], arg: Any, label: str) -> None:
        if self._thread is None:
            self.call(fn, arg, label)
        else:
            self._queue.put((fn, arg, label))

    def close(self) -> list[concurrent.futures.Future[Any]]:
        """Drain queued callbacks; returns futures of async callbacks still running on the loop."""
        if self._thread is not None:
            self._queue.put(self._STOP)
            self._thread.join()
            self._thread = None
        futures, self._futures = self._futures, []
        return futures

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def is_callback_thread(self, thread: threading.Thread) -> bool:
        return thread is self._thread

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._STOP:
                return
            self.call(*item)

    def call(self, fn: Callable[[Any], Any], arg: Any, label: str) -> None:
        try:
            result = fn(arg)
            if not inspect.isawaitable(result):
                return

            async def wait() -> Any:
                return await result

            loop = self._loop
            if loop is not None and loop.is_running():
                fut = asyncio.run_coroutine_threadsafe(wait(), loop)
                fut.add_done_callback(lambda f: self._check(f, label))
                self._futures.append(fut)
            else:
                asyncio.run(wait())
        except Exception as e:
            self._on_failure(label, e)

    def _check(self, fut: concurrent.futures.Future[Any], label: str) -> None:
        if not fut.cancelled() and fut.exception() is not None:
            self._on_failure(label, fut.exception())  # type: ignore[arg-type]


class _CallbackRunner(ActionRunner):
    """YAML actions plus Python callbacks. Rules with callbacks don't default to `notify`."""

    def __init__(
        self,
        callbacks: Mapping[str, list[RuleCallback]],
        dispatch: Callable[[Callable[[Any], Any], Any, str], None],
        log: Callable[[str, str], None],
        dry_run: bool,
        notify_by_default: bool,
    ):
        super().__init__(log=log, dry_run=dry_run)
        self.callbacks = callbacks
        self.dispatch = dispatch
        self.notify_by_default = notify_by_default

    def default_actions(self, event: FireEvent) -> list[Action]:
        if not self.notify_by_default or self.callbacks.get(event.rule.name):
            return []
        return super().default_actions(event)

    def run(self, actions: list[Action], event: FireEvent) -> bool:
        stop = super().run(actions, event)
        for cb in self.callbacks.get(event.rule.name, ()):
            self.dispatch(cb, event, f"callback for rule '{event.rule.name}'")
        return stop


class _RecordingSource(Source):
    """Wraps a source and keeps the latest JPEG for snapshots."""

    def __init__(self, inner: Source):
        self.inner = inner
        self.kind = inner.kind
        self.provides = inner.provides
        self.last_jpeg: bytes | None = None

    def open(self) -> None:
        self.inner.open()

    def read(self) -> Sample:
        sample = self.inner.read()
        if sample.jpeg is not None:
            self.last_jpeg = sample.jpeg
        return sample

    def close(self) -> None:
        self.inner.close()

    def describe(self) -> str:
        return self.inner.describe()


@dataclass
class _Subscriber:
    fn: EventCallback
    kinds: frozenset[str] | None


@dataclass
class _RunInfo:
    running: bool = False
    stop_reason: str | None = None
    error: str | None = None
    last_fired: dict[str, float] = field(default_factory=dict)
    stop_emitted: bool = False


class Watcher:
    """Watch a source and run callbacks (and YAML actions) when plain-English rules come true.

    ``source``, ``provider``, ``prefilter`` and ``rules`` take the same shapes as the YAML
    rules file, and the whole thing is validated by the same schema. Rules can be added with
    :meth:`when` / :meth:`add_rule` until the watcher is started.

    Example::

        w = Watcher(source={"camera": 0}, provider="gemini", every="2s")

        @w.when("A person is at the front door.", threshold=0.85, for_=2, name="person")
        def person(event: FireEvent) -> None:
            print(event.name, event.probability)

        w.run()
    """

    def __init__(
        self,
        source: str | Mapping[str, Any],
        provider: ProviderSpec = "auto",
        every: str | float | None = None,
        *,
        rules: list[Mapping[str, Any]] | None = None,
        prefilter: Mapping[str, Any] | None = None,
        context: str | None = None,
        skip_unchanged: bool | None = None,
        change_threshold: float | None = None,
        max_skip: str | float | None = None,
        dry_run: bool = False,
        name: str | None = None,
    ):
        """
        Args:
            source: e.g. ``"screen"``, ``{"camera": 0}``, ``{"url": "http://cam/snap.jpg"}``,
                ``{"file": "clip.mp4"}``, ``{"camera": 0, "mic": True}``.
            provider: a provider name, a provider config dict, or a ``Provider`` instance
                (used as-is and never closed by the watcher).
            every: how often to look, e.g. ``"500ms"``, ``"2s"``, ``3``.
            rules: rule dicts as in YAML (``then:`` actions included).
            prefilter: a cheap first check, as in YAML.
            context: extra text sent with every capture.
            skip_unchanged, change_threshold, max_skip: as in YAML.
            dry_run: use the mock provider and print YAML actions instead of running them.
                Python callbacks still run.
            name: optional label, included in :meth:`state`.
        """
        data: dict[str, Any] = {"source": source}
        provider_instance = provider if isinstance(provider, Provider) else None
        if provider_instance is None:
            data["provider"] = (
                provider.model_dump(exclude_defaults=True)
                if isinstance(provider, ProviderConfig)
                else provider
            )
        optional = {
            "every": every,
            "prefilter": prefilter,
            "context": context,
            "skip_unchanged": skip_unchanged,
            "change_threshold": change_threshold,
            "max_skip": max_skip,
        }
        data.update({k: v for k, v in optional.items() if v is not None})
        data["rules"] = [dict(r) for r in rules or []]
        self._setup(data, provider_instance, dry_run, name, expand=True)

    @classmethod
    def from_config(
        cls,
        data: Mapping[str, Any],
        *,
        provider: Provider | None = None,
        dry_run: bool = False,
        expand_env: bool = True,
        name: str | None = None,
        notify_by_default: bool = True,
    ) -> Watcher:
        """Build a watcher from a config dict shaped exactly like a YAML rules file.

        ``expand_env=False`` leaves ``${VAR}`` references as literal text (use it for configs
        from untrusted sources so they can't read your environment).
        ``notify_by_default=False`` makes rules without ``then:`` run no actions at all,
        instead of a desktop notification.
        """
        obj = cls.__new__(cls)
        obj._setup(dict(data), provider, dry_run, name, expand=expand_env)
        obj._notify_by_default = notify_by_default
        return obj

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        *,
        provider: Provider | None = None,
        dry_run: bool = False,
        name: str | None = None,
    ) -> Watcher:
        """Build a watcher from a YAML rules file (``${VAR}`` references are expanded)."""
        import yaml

        load_config_file(path)  # same errors as `ifseen watch`
        data = yaml.safe_load(Path(path).expanduser().read_text())
        return cls.from_config(data, provider=provider, dry_run=dry_run, name=name)

    def _setup(
        self,
        data: dict[str, Any],
        provider: Provider | None,
        dry_run: bool,
        name: str | None,
        expand: bool,
    ) -> None:
        data = expand_env(data) if expand else data
        if dry_run:
            data["provider"] = {"name": "mock"}
            if isinstance(data.get("prefilter"), dict):
                data["prefilter"] = {**data["prefilter"], "provider": "mock"}
            provider = None
        rules = data.get("rules")
        if rules is None:
            rules = []
        if not isinstance(rules, list):
            raise ConfigError("invalid config:\n  rules: must be a list")
        data["rules"] = list(rules)
        # validate everything now; only "at least one rule" waits until start
        load_config({**data, "rules": data["rules"] or [_PLACEHOLDER_RULE]}, expand=False)
        self.name = name
        self._data = data
        self._provider = provider
        self._dry_run = dry_run
        self._notify_by_default = True
        self._callbacks: dict[str, list[RuleCallback]] = {}
        self._subscribers: list[_Subscriber] = []
        self._lock = threading.RLock()
        self._info = _RunInfo()
        self._engine: Engine | None = None
        self._recorder: _RecordingSource | None = None
        self._cfg: WatchConfig | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._dispatcher = _Dispatcher(self._callback_failed)

    # -- rules -----------------------------------------------------------------------------

    def when(
        self,
        statement: str,
        *,
        threshold: float | None = None,
        for_: int | None = None,
        cooldown: str | float | None = None,
        hysteresis: float | None = None,
        name: str | None = None,
        then: list[Any] | None = None,
        true_means: str | None = None,
        false_means: str | None = None,
    ) -> Callable[[RuleCallback], RuleCallback]:
        """Decorator: add a rule and call the decorated function each time it fires."""

        def decorator(fn: RuleCallback) -> RuleCallback:
            self.add_rule(
                statement,
                fn,
                threshold=threshold,
                for_=for_,
                cooldown=cooldown,
                hysteresis=hysteresis,
                name=name,
                then=then,
                true_means=true_means,
                false_means=false_means,
            )
            return fn

        return decorator

    def add_rule(
        self,
        statement: str | Mapping[str, Any],
        callback: RuleCallback | None = None,
        *,
        threshold: float | None = None,
        for_: int | None = None,
        cooldown: str | float | None = None,
        hysteresis: float | None = None,
        name: str | None = None,
        then: list[Any] | None = None,
        true_means: str | None = None,
        false_means: str | None = None,
    ) -> str:
        """Add a rule; returns its name.

        ``statement`` is the plain-English condition, or a full rule dict as in YAML. ``then``
        takes YAML actions. A rule with a callback and no ``then`` runs only the callback
        (YAML rules without ``then`` default to a desktop notification).
        """
        self._require_stopped()
        if isinstance(statement, Mapping):
            rule = dict(statement)
        else:
            rule = {"when": statement}
            options = {
                "threshold": threshold,
                "for": for_,
                "cooldown": cooldown,
                "hysteresis": hysteresis,
                "name": name,
                "then": then,
                "true_means": true_means,
                "false_means": false_means,
            }
            rule.update({k: v for k, v in options.items() if v is not None})
        taken = {r.get("name") for r in self._data["rules"] if isinstance(r, dict)}
        if not rule.get("name"):
            rule["name"] = slugify(str(rule.get("when", "")), set(taken))  # type: ignore[arg-type]
        if rule["name"] in taken:
            raise ConfigError(f"duplicate rule name: {rule['name']!r}")
        try:
            Rule.model_validate(rule)
        except Exception as e:
            raise ConfigError(pretty_error(e)) from e
        self._data["rules"].append(rule)
        if callback is not None:
            self.on(rule["name"])(callback)
        return rule["name"]

    def on(self, rule: str) -> Callable[[RuleCallback], RuleCallback]:
        """Decorator: call the function when an existing rule (e.g. from YAML) fires."""
        names = {r.get("name") for r in self._data["rules"]}
        if rule not in names:
            raise ConfigError(f"no rule named {rule!r}")

        def decorator(fn: RuleCallback) -> RuleCallback:
            self._require_stopped()
            self._callbacks.setdefault(rule, []).append(fn)
            return fn

        return decorator

    # -- event stream ----------------------------------------------------------------------

    def on_event(
        self, fn: EventCallback, kinds: list[str] | tuple[str, ...] | None = None
    ) -> EventCallback:
        """Subscribe to engine events (all kinds, or only ``kinds``). Returns ``fn``.

        Event dicts are documented in docs/api.md. Subscribers run on a callback thread in
        event order; async functions run on the event loop under :meth:`run_async`.
        """
        with self._lock:
            self._subscribers.append(_Subscriber(fn, frozenset(kinds) if kinds else None))
        return fn

    def on_decision(self, fn: EventCallback) -> EventCallback:
        """Subscribe to ``decision`` events (one per model call or skipped tick)."""
        return self.on_event(fn, ("decision",))

    def on_fire(self, fn: EventCallback) -> EventCallback:
        """Subscribe to ``fire`` events for every rule."""
        return self.on_event(fn, ("fire",))

    def on_error(self, fn: EventCallback) -> EventCallback:
        """Subscribe to ``error`` events (provider/source/callback failures)."""
        return self.on_event(fn, ("error",))

    def remove_listener(self, fn: EventCallback) -> None:
        """Unsubscribe a function added with :meth:`on_event` and friends."""
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s.fn is not fn]

    # -- running ---------------------------------------------------------------------------

    @property
    def config(self) -> WatchConfig:
        """The validated config (raises ConfigError if there are no rules yet)."""
        return load_config(self._data, expand=False)

    @property
    def rule_names(self) -> list[str]:
        return [r["name"] for r in self._data["rules"]]

    @property
    def running(self) -> bool:
        return self._info.running

    def run(self, max_ticks: int | None = None) -> str:
        """Watch until stopped, an ``exit`` action fires, the source ends or ``max_ticks``.

        Blocks. Ctrl+C stops cleanly and returns ``"interrupted"``. Returns the stop reason.
        Raises ProviderConfigError / SourceError for fatal problems (bad key, no camera).
        """
        self._claim()
        return self._run(max_ticks, loop=None)

    async def run_async(self, max_ticks: int | None = None) -> str:
        """Like :meth:`run`, but awaitable: the loop runs in a worker thread and async
        callbacks are scheduled on the current event loop. Cancelling stops the watcher."""
        self._claim()
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(None, self._run, max_ticks, loop)
        try:
            reason = await asyncio.shield(future)
        except asyncio.CancelledError:
            self.stop(wait=False)
            raise
        futures, self._pending = self._pending, []
        if futures:
            await asyncio.gather(*(asyncio.wrap_future(f) for f in futures), return_exceptions=True)
        return reason

    def start(self, max_ticks: int | None = None) -> None:
        """Run in a background thread. Fatal errors end the run and show up in :meth:`state`
        (``error``) and as an ``error`` event."""
        self._claim()
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        def target() -> None:
            # fatal errors are already reported as an error event and in state()
            with contextlib.suppress(Exception):
                self._run(max_ticks, loop)

        self._thread = threading.Thread(target=target, name="ifseen-watcher", daemon=True)
        self._thread.start()

    def stop(self, wait: bool = True, timeout: float | None = WATCHER_STOP_TIMEOUT_SECONDS) -> None:
        """Ask the watcher to stop; with ``wait``, join a background thread started by
        :meth:`start`. Safe to call from callbacks and other threads."""
        self._stop_event.set()
        engine = self._engine
        if engine is not None and not engine.stopped:
            engine.stop("stopped")
        thread = self._thread
        current = threading.current_thread()
        # from a callback, joining would deadlock: the run waits for callbacks to drain
        if current is thread or self._dispatcher.is_callback_thread(current):
            return
        if wait and thread is not None:
            thread.join(timeout)

    def join(self, timeout: float | None = None) -> None:
        """Wait for a background run started with :meth:`start` to finish."""
        if self._thread is not None:
            self._thread.join(timeout)

    def snapshot(self) -> bytes | None:
        """The latest captured frame as JPEG bytes, or None before the first image."""
        rec = self._recorder
        return rec.last_jpeg if rec is not None else None

    def state(self) -> dict[str, Any]:
        """A JSON-safe snapshot of the watcher: per-rule probability/streak/armed/fires and
        loop stats. Rule state resets on each start."""
        engine = self._engine
        info = self._info
        rules = []
        for i, raw in enumerate(self._data["rules"]):
            st = engine.states[i] if engine is not None and i < len(engine.states) else None
            rule = st.rule if st is not None else Rule.model_validate(raw)
            rules.append(
                {
                    "name": rule.name,
                    "when": rule.when,
                    "threshold": rule.threshold,
                    "for": rule.consecutive,
                    "cooldown": rule.cooldown,
                    "prob": round(st.prob, 4) if st else 0.0,
                    "streak": st.streak if st else 0,
                    "armed": st.armed if st else True,
                    "fires": st.fires if st else 0,
                    "last_fired": info.last_fired.get(rule.name),
                    "status": st.status if st else "idle",
                    "actions": [next(iter(a)) for a in rule.then],
                    "callbacks": len(self._callbacks.get(rule.name, ())),
                }
            )
        stats: dict[str, Any] | None = None
        if engine is not None:
            s = engine.stats
            stats = {k: _round(v) for k, v in dataclasses.asdict(s).items()}
            stats["cost_per_hour"] = round(s.cost_per_hour(), 6)
        return {
            "name": self.name,
            "running": info.running,
            "stop_reason": info.stop_reason,
            "error": info.error,
            "source": engine.source.describe() if engine else _source_kind(self._data),
            "provider": engine.provider.describe() if engine else _provider_name(self._data),
            "every": _every(self._data),
            "rules": rules,
            "stats": stats,
        }

    # -- internals -------------------------------------------------------------------------

    def _require_stopped(self) -> None:
        if self._info.running:
            raise RuntimeError("stop the watcher before changing its rules")

    def _claim(self) -> None:
        with self._lock:
            if self._info.running:
                raise RuntimeError("watcher is already running")
            cfg = self.config
            self._info = _RunInfo(running=True)
            self._cfg = cfg
            self._stop_event.clear()
            self._pending: list[concurrent.futures.Future[Any]] = []

    def _run(self, max_ticks: int | None, loop: asyncio.AbstractEventLoop | None) -> str:
        cfg = self._cfg
        assert cfg is not None
        self._dispatcher.start(loop)
        runner: _CallbackRunner | None = None
        rt = None
        reason = "error"
        try:
            rt = build_runtime(cfg, provider=self._provider)
            self._recorder = _RecordingSource(rt.source)
            runner = _CallbackRunner(
                self._callbacks,
                self._dispatcher.submit,
                self._action_log,
                self._dry_run,
                self._notify_by_default,
            )
            engine = Engine(
                cfg,
                self._recorder,
                rt.provider,
                runner,
                listener=self._on_engine_event,
                sleep=self._stop_event.wait,
                prefilter=rt.prefilter,
            )
            self._engine = engine
            if self._stop_event.is_set():
                engine.stop("stopped")
            with self._recorder:
                reason = engine.run(max_ticks=max_ticks)
            return reason
        except BaseException as e:
            known = isinstance(e, (ConfigError, ProviderConfigError, SourceError))
            self._info.error = str(e) if known else f"{type(e).__name__}: {e}"
            reason = "error"
            self._on_engine_event(
                {
                    "event": "error",
                    "time": round(time.time(), 3),
                    "message": self._info.error,
                    "fatal": True,
                }
            )
            raise
        finally:
            if not self._info.stop_emitted:
                self._on_engine_event(
                    {"event": "stop", "time": round(time.time(), 3), "reason": reason}
                )
            self._info.stop_reason = reason
            if runner is not None:
                runner.close()
            if rt is not None:
                rt.close()
            # async callbacks still running on the loop: run_async awaits them
            self._pending = self._dispatcher.close()
            self._info.running = False

    def _on_engine_event(self, event: Event) -> None:
        kind = event.get("event")
        if kind == "fire":
            self._info.last_fired[event["rule"]] = event["time"]
        elif kind == "stop":
            self._info.stop_emitted = True
        with self._lock:
            subscribers = list(self._subscribers)
        for sub in subscribers:
            if sub.kinds is None or kind in sub.kinds:
                self._dispatcher.submit(sub.fn, event, f"event listener {_label(sub.fn)}")

    def _action_log(self, level: str, message: str) -> None:
        getattr(log, {"warn": "warning", "dry": "info"}.get(level, level), log.info)(message)
        self._on_engine_event(
            {"event": "log", "time": round(time.time(), 3), "level": level, "message": message}
        )

    def _callback_failed(self, label: str, exc: BaseException) -> None:
        log.error("%s failed", label, exc_info=exc)
        event = {
            "event": "error",
            "time": round(time.time(), 3),
            "message": f"{label} failed: {type(exc).__name__}: {exc}",
            "origin": "callback",
        }
        # deliver inline: we're on the callback thread (or the loop), and an error listener
        # that itself raises must not loop forever
        with self._lock:
            subscribers = [s for s in self._subscribers if s.kinds is None or "error" in s.kinds]
        for sub in subscribers:
            try:
                result = sub.fn(event)
                if inspect.isawaitable(result):
                    loop = self._dispatcher.loop
                    if loop is not None and loop.is_running():
                        asyncio.run_coroutine_threadsafe(_await(result), loop)
                    else:
                        asyncio.run(_await(result))
            except Exception:
                log.exception("error listener %s failed", _label(sub.fn))


async def _await(result: Awaitable[Any]) -> Any:
    return await result


def _label(fn: Callable[..., Any]) -> str:
    return getattr(fn, "__qualname__", None) or repr(fn)


def _round(v: Any) -> Any:
    return round(v, 6) if isinstance(v, float) else v


def _source_kind(data: Mapping[str, Any]) -> str:
    src = data.get("source")
    if isinstance(src, str):
        return src
    if isinstance(src, Mapping):
        return " + ".join(str(k) for k in src)
    return "?"


def _provider_name(data: Mapping[str, Any]) -> str:
    p = data.get("provider") or "auto"
    if isinstance(p, Mapping):
        return str(p.get("name", "auto"))
    return str(p)


def _every(data: Mapping[str, Any]) -> float:
    return parse_duration(data.get("every", DEFAULT_EVERY_SECONDS))
