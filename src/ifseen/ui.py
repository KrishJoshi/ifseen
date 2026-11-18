"""Terminal output: a live dashboard for humans, JSON lines for machines."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections import deque
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .engine import Engine

_SPARK = "▁▂▃▄▅▆▇█"
_LEVEL_STYLE = {
    "error": "red",
    "warn": "yellow",
    "fire": "bold green",
    "info": "cyan",
    "dry": "magenta",
}


def sparkline(values: list[float], width: int = 20) -> str:
    vals = values[-width:]
    return "".join(_SPARK[min(len(_SPARK) - 1, int(v * len(_SPARK)))] for v in vals)


def bar(p: float, threshold: float, width: int = 14) -> Text:
    filled = round(p * width)
    style = "bold green" if p >= threshold else "yellow" if p >= threshold * 0.6 else "grey50"
    t = Text("█" * filled, style=style)
    t.append("░" * (width - filled), style="grey23")
    t.append(f" {p * 100:3.0f}%", style=style)
    return t


class Dashboard:
    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self.engine: Engine | None = None
        self.log: deque[tuple[float, str, str]] = deque(maxlen=8)
        self.live: Live | None = None
        self.header = ""
        # actions log from worker threads while the engine renders from the main thread
        self._lock = threading.RLock()

    # listener protocol
    def __call__(self, event: dict[str, Any]) -> None:
        kind = event["event"]
        if kind == "start":
            self.header = f"{event['source']}  →  {event['provider']}"
        elif kind == "fire":
            self.add(
                "fire", f"🔔 {event['rule']}: {event['when']} ({event['probability'] * 100:.0f}%)"
            )
        elif kind == "error":
            msg = event["message"]
            if event.get("retry_in"):
                msg += f" (retrying in {event['retry_in']}s)"
            self.add("error", msg)
        elif kind == "stop":
            self.add("info", f"stopped: {event['reason']}")
        self.refresh()

    def add(self, level: str, message: str) -> None:
        with self._lock:
            self.log.append((time.time(), level, message))
            self.refresh()

    def attach(self, engine: Engine) -> None:
        self.engine = engine

    def __enter__(self) -> Dashboard:
        self.live = Live(self.render(), console=self.console, refresh_per_second=8, transient=False)
        self.live.__enter__()
        return self

    def __exit__(self, *exc: object) -> None:
        if self.live:
            self.live.update(self.render())
            self.live.__exit__(*exc)  # type: ignore[arg-type]
            self.live = None

    def refresh(self) -> None:
        with self._lock:
            if self.live:
                self.live.update(self.render())

    def render(self) -> Panel:
        # Below ~110 columns the "when" text is dropped; rule names are slugs of it anyway.
        wide = self.console.width >= 110
        table = Table(expand=True, box=None, pad_edge=False, show_edge=False)
        table.add_column("rule", style="bold", no_wrap=True, max_width=28, overflow="ellipsis")
        if wide:
            table.add_column("when", ratio=3, min_width=24, overflow="ellipsis", no_wrap=True)
        table.add_column("now", no_wrap=True)
        table.add_column("trend", no_wrap=True, style="cyan")
        table.add_column("status", no_wrap=True)
        table.add_column("fired", justify="right")
        if self.engine:
            for st in self.engine.states:
                status_style = "green" if st.armed and not st.streak else "yellow"
                cells: list = [st.rule.name]
                if wide:
                    cells.append(st.rule.when)
                cells += [
                    bar(st.prob, st.rule.threshold, width=14 if wide else 8),
                    sparkline(st.history, width=20 if wide else 10),
                    Text(st.status, style=status_style),
                    str(st.fires),
                ]
                table.add_row(*cells)
        events = Text()
        with self._lock:
            entries = list(self.log)
        for ts, level, msg in entries:
            events.append(time.strftime("%H:%M:%S ", time.localtime(ts)), style="grey50")
            events.append(msg + "\n", style=_LEVEL_STYLE.get(level, ""))
        footer = Text(style="grey62")
        if self.engine:
            s = self.engine.stats
            footer.append(
                f"calls {s.calls}  skipped {s.skipped}  errors {s.errors}  "
                f"latency {s.last_latency_ms:.0f}ms  tokens {s.input_tokens:,}  "
                f"spent ${s.cost_usd:.4f}  (~${s.cost_per_hour():.3f}/h)"
            )
        body = Group(table, Text(""), events, footer)
        return Panel(
            body,
            title=f"[bold]ifseen[/]  {self.header}",
            title_align="left",
            subtitle="ctrl+c to stop",
            subtitle_align="right",
            border_style="blue",
        )


class JsonLines:
    """One JSON object per event on stdout - pipe into jq, a log shipper, or Home Assistant."""

    def __init__(self, stream=None, include_decisions: bool = True):
        self.stream = stream or sys.stdout
        self.include_decisions = include_decisions

    def __call__(self, event: dict[str, Any]) -> None:
        if event["event"] == "decision" and not self.include_decisions:
            return
        self.stream.write(json.dumps(event) + "\n")
        self.stream.flush()

    def add(self, level: str, message: str) -> None:
        self({"event": "log", "level": level, "message": message, "time": round(time.time(), 3)})


class PlainLog:
    """Readable line-per-event output for non-interactive terminals."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console(stderr=False, highlight=False)

    def __call__(self, event: dict[str, Any]) -> None:
        kind = event["event"]
        if kind == "start":
            self.add(
                "info",
                f"watching {event['source']} with {event['provider']}: {', '.join(event['rules'])}",
            )
        elif kind == "fire":
            self.add(
                "fire",
                f"FIRED {event['rule']} ({event['probability'] * 100:.0f}%) - {event['when']}",
            )
        elif kind == "error":
            self.add("error", event["message"])
        elif kind == "stop":
            self.add("info", f"stopped: {event['reason']}")

    def add(self, level: str, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        style = _LEVEL_STYLE.get(level) or "default"
        self.console.print(f"[grey50]{stamp}[/] [{style}]{escape(message)}[/]")
