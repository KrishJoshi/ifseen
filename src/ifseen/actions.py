"""What happens when a rule fires."""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

import httpx

from .config import Action, Rule
from .constants import HTTP_TIMEOUT_SECONDS, NTFY_DEFAULT_SERVER
from .media import Sample

Log = Callable[[str, str], None]  # (level, message)

_SHELL_GRACE_SECONDS = 10.0


@dataclass
class FireEvent:
    rule: Rule
    probability: float
    fired_at: float
    sample: Sample
    source: str
    snapshot: Path | None = None

    def fields(self) -> dict[str, str]:
        return {
            "rule": self.rule.name,
            "when": self.rule.when,
            "prob": f"{self.probability:.2f}",
            "percent": f"{self.probability * 100:.0f}%",
            "time": time.strftime("%H:%M:%S", time.localtime(self.fired_at)),
            "source": self.source,
            "snapshot": str(self.snapshot or ""),
        }


class _SafeFormatter(Formatter):
    """str.format that leaves unknown {placeholders} untouched instead of raising."""

    def get_value(self, key, args, kwargs):  # type: ignore[override]
        if isinstance(key, str) and key in kwargs:
            return str(kwargs[key])
        return "{" + str(key) + "}"

    def format_field(self, value, format_spec):  # type: ignore[override]
        return str(value)


def render(template: str, event: FireEvent) -> str:
    try:
        return _SafeFormatter().format(template, **event.fields())
    except (ValueError, IndexError):
        return template


class ActionRunner:
    def __init__(
        self,
        log: Log,
        dry_run: bool = False,
        client: httpx.Client | None = None,
        background: bool = True,
    ):
        self.log = log
        self.dry_run = dry_run
        self._client = client
        self._tmpdir: Path | None = None
        self._procs: list[subprocess.Popen] = []
        self._procs_lock = threading.Lock()
        self._pool = (
            ThreadPoolExecutor(max_workers=4, thread_name_prefix="ifseen-action")
            if background
            else None
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        return self._client

    def run(self, actions: list[Action], event: FireEvent) -> bool:
        """Run a rule's actions. Returns True if an `exit` action asked the watcher to stop."""
        if event.sample.jpeg is not None and event.snapshot is None:
            event.snapshot = self._temp_snapshot(event)
        if not actions:
            actions = [{"notify": True}]
        stop = False
        for action in actions:
            ((kind, opts),) = action.items()
            if kind == "exit":
                stop = True
                continue
            if self.dry_run and kind not in ("log",):
                self.log("dry", f"[{event.rule.name}] would run {kind}: {_describe(kind, opts)}")
                continue
            if self._pool is None:
                self._safe(kind, opts, event)
            else:
                self._pool.submit(self._safe, kind, opts, event)
        return stop

    def _temp_snapshot(self, event: FireEvent) -> Path | None:
        try:
            if self._tmpdir is None:
                # private per-run dir: a shared, predictable /tmp path invites symlink attacks
                self._tmpdir = Path(tempfile.mkdtemp(prefix="ifseen-"))
            path = self._tmpdir / f"{event.rule.name}-latest.jpg"
            path.write_bytes(event.sample.jpeg or b"")
            return path
        except OSError as e:
            self.log("warn", f"could not write temp snapshot: {e.strerror}")
            return None

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=False)
        # Shell commands may still be reading $IFSEEN_SNAPSHOT (e.g. a rule ending in
        # `exit`), so give them a moment before deleting the frames.
        deadline = time.monotonic() + _SHELL_GRACE_SECONDS
        for proc in self._procs:
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=max(0.0, deadline - time.monotonic()))
        if self._tmpdir is not None:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None
        if self._client is not None:
            self._client.close()

    # -- individual actions ----------------------------------------------------------------

    def _safe(self, kind: str, opts: Any, event: FireEvent) -> None:
        try:
            getattr(self, f"_do_{kind}")(opts, event)
        except httpx.HTTPStatusError as e:
            # never echo the URL: webhook and ntfy URLs are effectively secrets
            self.log(
                "error",
                f"[{event.rule.name}] {kind} failed: HTTP {e.response.status_code} "
                f"from {e.request.url.host}",
            )
        except httpx.HTTPError as e:
            host = e.request.url.host if _has_request(e) else "?"
            self.log("error", f"[{event.rule.name}] {kind} failed: {type(e).__name__} ({host})")
        except Exception as e:  # an action failing must never kill the watcher
            self.log("error", f"[{event.rule.name}] {kind} failed: {type(e).__name__}: {e}")

    def _do_log(self, opts: Any, event: FireEvent) -> None:
        msg = opts if isinstance(opts, str) else "{when} ({percent})"
        self.log("info", f"[{event.rule.name}] {render(msg, event)}")

    def _do_notify(self, opts: Any, event: FireEvent) -> None:
        title, message = "ifseen: {rule}", "{when} ({percent})"
        if isinstance(opts, str):
            message = opts
        elif isinstance(opts, dict):
            title = opts.get("title", title)
            message = opts.get("message", message)
        desktop_notify(render(title, event), render(message, event))

    def _do_say(self, opts: Any, event: FireEvent) -> None:
        text = render(opts if isinstance(opts, str) else "{rule}", event)
        speak(text)

    def _do_shell(self, opts: Any, event: FireEvent) -> None:
        cmd = opts if isinstance(opts, str) else opts.get("cmd") if isinstance(opts, dict) else None
        if not cmd:
            raise ValueError("shell action needs a command")
        wait = isinstance(opts, dict) and bool(opts.get("wait"))
        env = {**os.environ, **{f"IFSEEN_{k.upper()}": v for k, v in event.fields().items()}}
        # Values reach the command only as IFSEEN_* env vars, never spliced into the command
        # text, so file names, URLs or rule text can't inject shell syntax.
        proc = subprocess.Popen(cmd, shell=True, env=env)
        with self._procs_lock:
            self._procs = [p for p in self._procs if p.poll() is None] + [proc]
        if wait:
            code = proc.wait()
            if code:
                self.log("warn", f"[{event.rule.name}] shell exited with {code}")

    def _do_webhook(self, opts: Any, event: FireEvent) -> None:
        if isinstance(opts, str):
            opts = {"url": opts}
        url = render(opts["url"], event)
        payload: dict[str, Any] = {
            "rule": event.rule.name,
            "when": event.rule.when,
            "probability": round(event.probability, 4),
            "fired_at": event.fired_at,
            "source": event.source,
        }
        if opts.get("image") and event.sample.jpeg is not None:
            import base64

            payload["image_base64"] = base64.b64encode(event.sample.jpeg).decode("ascii")
        r = self.client.request(
            opts.get("method", "POST"), url, json=payload, headers=opts.get("headers") or {}
        )
        r.raise_for_status()

    def _do_ntfy(self, opts: Any, event: FireEvent) -> None:
        if isinstance(opts, str):
            opts = {"topic": opts}
        server = opts.get("server", NTFY_DEFAULT_SERVER).rstrip("/")
        url = f"{server}/{render(opts['topic'], event)}"
        params = {
            "title": render(opts.get("title", "ifseen: {rule}"), event),
            "message": render(opts.get("message", "{when} ({percent})"), event),
        }
        if opts.get("priority"):
            params["priority"] = str(opts["priority"])
        if opts.get("tags"):
            params["tags"] = (
                ",".join(opts["tags"]) if isinstance(opts["tags"], list) else str(opts["tags"])
            )
        headers = {}
        if opts.get("token"):
            headers["Authorization"] = f"Bearer {opts['token']}"
        if opts.get("image", True) and event.sample.jpeg is not None:
            params["filename"] = f"{event.rule.name}.jpg"
            r = self.client.put(url, params=params, content=event.sample.jpeg, headers=headers)
        else:
            r = self.client.post(url, params=params, content=b"", headers=headers)
        r.raise_for_status()

    def _do_snapshot(self, opts: Any, event: FireEvent) -> None:
        if event.sample.jpeg is None:
            self.log("warn", f"[{event.rule.name}] snapshot skipped: source has no image")
            return
        folder = Path(opts if isinstance(opts, str) else "ifseen-captures").expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(event.fired_at))
        path = folder / f"{event.rule.name}-{stamp}.jpg"
        path.write_bytes(event.sample.jpeg)
        self.log("info", f"[{event.rule.name}] saved {path}")


def _describe(kind: str, opts: Any) -> str:
    """Dry-run description that never prints URLs, topics or tokens."""
    if kind in ("webhook", "ntfy"):
        return "(destination hidden)"
    s = str(opts)
    return s if len(s) < 60 else s[:57] + "..."


def _has_request(e: httpx.HTTPError) -> bool:
    try:
        e.request  # noqa: B018 - raises RuntimeError when unset
    except RuntimeError:
        return False
    return True


def desktop_notify(title: str, message: str) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                "display notification (item 2 of argv) with title (item 1 of argv)",
                "-e",
                "end run",
                title,
                message,
            ],
            check=False,
            capture_output=True,
        )
    elif system == "Linux" and shutil.which("notify-send"):
        subprocess.run(["notify-send", title, message], check=False, capture_output=True)
    elif system == "Windows":
        ps = (
            "[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,"
            "ContentType=WindowsRuntime];$t=[Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent(1);$n=$t.GetElementsByTagName('text');"
            "$n.Item(0).AppendChild($t.CreateTextNode($args[0]))|Out-Null;"
            "$n.Item(1).AppendChild($t.CreateTextNode($args[1]))|Out-Null;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ifseen')"
            ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps, title, message],
            check=False,
            capture_output=True,
        )
    else:
        sys.stderr.write(f"\a{title}: {message}\n")


def speak(text: str) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["say", text], check=False)
    elif shutil.which("spd-say"):
        subprocess.run(["spd-say", text], check=False)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", text], check=False)
    elif system == "Windows":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Add-Type -AssemblyName System.Speech;"
                "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak($args[0])",
                text,
            ],
            check=False,
        )
    else:
        sys.stderr.write("\a")
