"""ifseen command line.

ifseen "a person is at the door" --camera 0 --then "say someone is here"
ifseen watch rules.yaml
ifseen test rules.yaml --image photo.jpg
ifseen recipes | ifseen init doorbell | ifseen doctor
"""

from __future__ import annotations

import argparse
import os
import sys
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from .actions import ActionRunner
from .config import ConfigError, WatchConfig, load_config, load_config_file
from .constants import PREFILTER_DEFAULT_PROVIDER, PREFILTER_KEY, VERSION
from .engine import Engine
from .providers import Provider, ProviderConfigError, ProviderError, Question, build_provider
from .recipes import recipe_names, recipe_summary, recipe_text
from .runtime import build_prefilter, build_runtime, load_target, questions_for, slugify
from .sources import SourceError, build_source
from .ui import Dashboard, JsonLines, PlainLog

SUBCOMMANDS = {"watch", "test", "recipes", "init", "doctor", "serve"}
err = Console(stderr=True, highlight=False)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        _print_help()
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"ifseen {VERSION}")
        return 0
    try:
        typo = _subcommand_typo(argv[0])
        if typo:
            err.print(
                f"[red]error:[/] unknown command {escape(argv[0])!r} - did you mean "
                f"[cyan]ifseen {typo}[/]? (quote multi-word conditions)"
            )
            return 2
        if argv[0] in SUBCOMMANDS:
            cmd, rest = argv[0], argv[1:]
            return {
                "watch": cmd_watch,
                "test": cmd_test,
                "recipes": cmd_recipes,
                "init": cmd_init,
                "doctor": cmd_doctor,
                "serve": cmd_serve,
            }[cmd](rest)
        return cmd_oneliner(argv)
    except (ConfigError, ProviderConfigError, SourceError) as e:
        err.print(f"[red]error:[/] {escape(str(e))}")
        return 2
    except KeyboardInterrupt:
        return 130


def _subcommand_typo(word: str) -> str | None:
    """'ifseen recipe' should not silently start watching for the condition 'recipe'."""
    import difflib

    if word in SUBCOMMANDS or word.startswith("-") or " " in word.strip():
        return None
    match = difflib.get_close_matches(word.lower(), sorted(SUBCOMMANDS), n=1, cutoff=0.75)
    return match[0] if match else None


# -- shared options --------------------------------------------------------------------------


def _add_run_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("running")
    g.add_argument(
        "--provider", help="gemini | jev | azure | systemone | openai | ollama | local | mock"
    )
    g.add_argument("--model", help="override the provider's model")
    g.add_argument("--base-url", help="custom endpoint (self-hosted / proxies)")
    g.add_argument("--every", help="how often to look, e.g. 500ms, 2s, 1m")
    g.add_argument(
        "--dry-run",
        action="store_true",
        help="offline: fake probabilities, print actions instead of running them",
    )
    g.add_argument("--json", action="store_true", help="emit JSON lines instead of the dashboard")
    g.add_argument("--plain", action="store_true", help="plain log lines instead of the dashboard")
    g.add_argument("--max-ticks", type=int, help=argparse.SUPPRESS)


def _apply_overrides(data: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    provider = data.get("provider") or {}
    if isinstance(provider, str):
        provider = {"name": provider}
    provider = dict(provider)
    if args.provider:
        provider["name"] = args.provider
    if args.model:
        provider["model"] = args.model
    if args.base_url:
        provider["base_url"] = args.base_url
    if args.dry_run:
        provider = {"name": "mock"}
        if isinstance(data.get("prefilter"), dict):
            data = {**data, "prefilter": {**data["prefilter"], "provider": "mock"}}
    data = {**data, "provider": provider}
    if args.every:
        data["every"] = args.every
    return data


def run_config(cfg: WatchConfig, args: argparse.Namespace) -> int:
    rt = build_runtime(cfg)
    interactive = sys.stdout.isatty() and not (args.json or args.plain)
    view: Any = JsonLines() if args.json else Dashboard() if interactive else PlainLog()
    actions = ActionRunner(log=view.add, dry_run=args.dry_run)
    engine = Engine(cfg, rt.source, rt.provider, actions, listener=view, prefilter=rt.prefilter)
    if args.dry_run:
        view.add("dry", "dry run: probabilities are random and actions are only printed")
    try:
        with rt.source:
            if isinstance(view, Dashboard):
                view.attach(engine)
                with view:
                    reason = engine.run(max_ticks=args.max_ticks)
            else:
                reason = engine.run(max_ticks=args.max_ticks)
    finally:
        actions.close()
        rt.close()
    return 130 if reason == "interrupted" else 0


# -- commands ----------------------------------------------------------------------------------


def cmd_watch(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ifseen watch", description="Run a rules file or recipe.")
    p.add_argument("target", help="rules.yaml or a recipe name (see `ifseen recipes`)")
    _add_run_options(p)
    args = p.parse_args(argv)
    cfg = load_config(_apply_overrides(load_target(args.target), args))
    return run_config(cfg, args)


def build_oneliner_config(args: argparse.Namespace) -> dict[str, Any]:
    source: dict[str, Any] = {}
    if args.camera is not None:
        source["camera"] = args.camera
    elif args.url:
        source["url"] = args.url
    elif args.file:
        source["file"] = args.file
    elif args.screen is not None:
        source["screen"] = args.screen
    if args.mic:
        source["mic"] = {}
    if not source:
        source["screen"] = 1

    then: list[Any] = []
    then += [{"shell": c} for c in args.then or []]
    if args.notify:
        then.append("notify")
    if args.say is not None:
        then.append({"say": args.say or "{rule}"})
    if args.ntfy:
        then.append({"ntfy": args.ntfy})
    if args.webhook:
        then.append({"webhook": args.webhook})
    if args.snapshot is not None:
        then.append({"snapshot": args.snapshot or "ifseen-captures"})
    if not then:
        then = ["notify", {"log": "{when} ({percent})"}]
    if args.once:
        then.append("exit")

    taken: set[str] = set()
    rules = []
    for cond in args.conditions:
        rule: dict[str, Any] = {"name": slugify(cond, taken), "when": cond, "then": then}
        if args.threshold is not None:
            rule["threshold"] = args.threshold
        if args.consecutive is not None:
            rule["for"] = args.consecutive
        if args.cooldown is not None:
            rule["cooldown"] = args.cooldown
        rules.append(rule)
    data: dict[str, Any] = {"source": source, "rules": rules}
    if args.prefilter:
        data["prefilter"] = {"provider": PREFILTER_DEFAULT_PROVIDER, "when": args.prefilter}
    if args.context:
        data["context"] = args.context
    return data


def cmd_oneliner(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="ifseen",
        description="Watch your screen, camera or mic and act when something is true.",
        epilog='example: ifseen "the kettle is boiling" --camera 0 --say "tea time" --once',
    )
    p.add_argument(
        "conditions", nargs="+", metavar="CONDITION", help="plain-English statement(s) to watch for"
    )
    src = p.add_argument_group("source (default: --screen)")
    src.add_argument(
        "--screen", nargs="?", const=1, type=int, metavar="N", help="monitor number (0=all)"
    )
    src.add_argument(
        "--camera", nargs="?", const="0", metavar="DEV", help="webcam index or rtsp:// URL"
    )
    src.add_argument("--url", help="HTTP snapshot URL to poll")
    src.add_argument("--file", help="image, .wav or video file")
    src.add_argument("--mic", action="store_true", help="also listen (gemini only)")
    act = p.add_argument_group("actions (default: --notify)")
    act.add_argument("--then", action="append", metavar="CMD", help="shell command (repeatable)")
    act.add_argument("--notify", action="store_true", help="desktop notification")
    act.add_argument("--say", nargs="?", const="", metavar="TEXT", help="speak out loud")
    act.add_argument("--ntfy", metavar="TOPIC", help="push to your phone via ntfy.sh")
    act.add_argument("--webhook", metavar="URL", help="POST JSON to a URL")
    act.add_argument("--snapshot", nargs="?", const="", metavar="DIR", help="save the frame")
    act.add_argument("--once", action="store_true", help="exit after the first trigger")
    tune = p.add_argument_group("tuning")
    tune.add_argument("--threshold", type=float, help="probability needed to fire (default 0.8)")
    tune.add_argument("--for", dest="consecutive", type=int, help="consecutive hits required")
    tune.add_argument("--cooldown", help="min time between triggers, e.g. 30s")
    tune.add_argument("--context", help="extra context sent with every capture")
    tune.add_argument(
        "--prefilter",
        metavar="TEXT",
        help="cheap free local check; the main provider is only asked when it's true",
    )
    _add_run_options(p)
    args = p.parse_args(argv)
    data = _apply_overrides(build_oneliner_config(args), args)
    cfg = load_config(data)
    return run_config(cfg, args)


def cmd_test(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="ifseen test",
        description="Ask every rule once against a single capture and print the probabilities. "
        "Use it to tune thresholds.",
    )
    p.add_argument("target", help="rules.yaml or recipe name")
    p.add_argument("--image", help="image file to test with")
    p.add_argument("--audio", help=".wav file to test with")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    data = load_target(args.target)
    if args.image or args.audio:
        src: dict[str, Any] = {}
        if args.image:
            src["file"] = args.image
        elif args.audio:
            src["file"] = args.audio
        data = {**data, "source": src}
    ns = argparse.Namespace(
        provider=args.provider, model=args.model, base_url=args.base_url, every=None, dry_run=False
    )
    cfg = load_config(_apply_overrides(data, ns))
    provider = build_provider(cfg.provider)
    source = build_source(cfg.source, every=cfg.every)
    prefilter: Provider | None = None
    gate = None
    try:
        with source:
            sample = source.read()
        if args.image and args.audio:
            from .media import wav_file_to_sample

            try:
                a = wav_file_to_sample(args.audio)
            except (OSError, EOFError, wave.Error) as e:
                raise SourceError(f"could not read {args.audio} as PCM WAV") from e
            sample.wav, sample.audio_rms = a.wav, a.audio_rms
        questions = questions_for(cfg.rules)
        try:
            prefilter = build_prefilter(cfg, source.provides)
            if prefilter is not None and cfg.prefilter is not None:
                pf = cfg.prefilter
                pre_sample = sample
                if sample.has_audio and "audio" not in prefilter.supports:
                    pre_sample = replace(sample, wav=None, audio_rms=0.0)
                q = Question(PREFILTER_KEY, pf.when, pf.true_means, pf.false_means)
                gate = prefilter.decide(pre_sample, [q], cfg.context).probs.get(PREFILTER_KEY, 0.0)
            decision = provider.decide(sample, questions, cfg.context)
        except ProviderError as e:
            err.print(f"[red]error:[/] {escape(str(e))}")
            return 1
    finally:
        provider.close()
        if prefilter is not None:
            prefilter.close()

    if args.json:
        import json

        print(
            json.dumps(
                {
                    "probs": decision.probs,
                    "tokens": decision.input_tokens,
                    "latency_ms": round(decision.latency_ms, 1),
                    **({"prefilter": gate} if gate is not None else {}),
                }
            )
        )
        return 0
    out = Console(highlight=False)
    table = Table(title=f"{source.describe()} → {provider.describe()}", title_justify="left")
    table.add_column("rule", style="bold")
    table.add_column("probability", justify="right")
    table.add_column("threshold", justify="right")
    table.add_column("would fire")
    for r in cfg.rules:
        prob = decision.probs.get(r.name, 0.0)
        fires = prob >= r.threshold
        table.add_row(
            r.name,
            f"{prob * 100:.1f}%",
            f"{r.threshold * 100:.0f}%",
            "[green]yes[/]" if fires else "[grey50]no[/]",
        )
    out.print(table)
    cost = provider.cost_usd(decision.input_tokens)
    out.print(
        f"[grey50]{decision.input_tokens} input tokens · ${cost:.6f} · "
        f"{decision.latency_ms:.0f} ms[/]"
    )
    if gate is not None and cfg.prefilter is not None:
        passed = gate >= cfg.prefilter.threshold
        verdict = "main provider would be called" if passed else "main provider would be skipped"
        out.print(
            f"prefilter {escape(repr(cfg.prefilter.when))} {gate * 100:.1f}% "
            f"(threshold {cfg.prefilter.threshold * 100:.0f}%) → "
            + ("[green]" if passed else "[yellow]")
            + f"{verdict}[/]"
            + ("" if passed else " [grey50](all rules would read 0%)[/]")
        )
    return 0


def cmd_recipes(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ifseen recipes", description="List or print recipes.")
    p.add_argument("name", nargs="?")
    args = p.parse_args(argv)
    if args.name:
        try:
            sys.stdout.write(recipe_text(args.name))
        except KeyError as e:
            raise ConfigError(f"no recipe named {args.name!r}") from e
        return 0
    out = Console(highlight=False)
    table = Table(box=None, show_header=False, pad_edge=False)
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    for name in recipe_names():
        table.add_row(name, recipe_summary(name))
    out.print(table)
    out.print(
        "\n[grey50]run one:[/] ifseen watch <name>    [grey50]customise:[/] ifseen init <name>"
    )
    return 0


def cmd_init(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ifseen init", description="Write a starter rules file.")
    p.add_argument("recipe", nargs="?", default="build-watcher")
    p.add_argument("-o", "--output", default="ifseen.yaml")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    try:
        text = recipe_text(args.recipe)
    except KeyError as e:
        raise ConfigError(f"no recipe named {args.recipe!r} (see `ifseen recipes`)") from e
    out = Path(args.output)
    if out.exists() and not args.force:
        raise ConfigError(f"{out} already exists (use --force to overwrite)")
    out.write_text(text)
    load_config_file(out)  # sanity check
    print(f"wrote {out} - edit it, then: ifseen watch {out}")
    return 0


def cmd_doctor(argv: list[str]) -> int:
    from importlib.util import find_spec

    from .constants import (
        AZURE_ENDPOINT_ENV,
        GEMINI_KEY_ENVS,
        JEV_KEY_ENV,
        LOCAL_DEFAULT_MODEL,
        LOCAL_MODULES,
        OPENAI_KEY_ENV,
    )
    from .providers import detect_provider_name

    out = Console(highlight=False)
    ok, bad = "[green]✓[/]", "[red]✗[/]"
    out.print(f"[bold]ifseen {VERSION}[/] on Python {sys.version.split()[0]}\n")
    out.print("[bold]keys[/]")
    for env in (*GEMINI_KEY_ENVS, JEV_KEY_ENV, AZURE_ENDPOINT_ENV, OPENAI_KEY_ENV):
        out.print(f"  {ok if os.environ.get(env) else '[grey50]-[/]'} {env}")
    try:
        out.print(f"  → auto provider: [cyan]{detect_provider_name()}[/]")
    except ProviderConfigError:
        out.print(
            f"  {bad} no key found - try [cyan]--dry-run[/], or get a free Gemini key at "
            "https://aistudio.google.com/apikey"
        )
    out.print("\n[bold]free offline provider[/]")
    missing = [m for m in LOCAL_MODULES if find_spec(m) is None]
    if missing:
        hint = escape("pip install 'ifseen[local]'")
        out.print(f"  [grey50]- local (needs {', '.join(missing)}): {hint}[/]")
    else:
        out.print(f"  {ok} local: [cyan]--provider local[/] ({LOCAL_DEFAULT_MODEL}, images only)")
    out.print("\n[bold]sources[/]")
    for label, module, extra in (
        ("screen", "mss", "screen"),
        ("camera/video", "cv2", "camera"),
        ("mic", "sounddevice", "mic"),
    ):
        have = find_spec(module) is not None
        hint = "" if have else f"  [grey50]{escape(f'pip install ifseen[{extra}]')}[/]"
        out.print(f"  {ok if have else bad} {label}{hint}")
    if find_spec("mss") is not None:
        try:
            from .config import ScreenSource as ScreenCfg
            from .sources.screen import ScreenSource

            with ScreenSource(ScreenCfg()) as s:
                sample = s.read()
            out.print(f"  {ok} screen capture works ({sample.width}x{sample.height} sent)")
            if sys.platform == "darwin":
                out.print(
                    "  [grey50]macOS: if captures only show your wallpaper, grant your "
                    "terminal Screen Recording permission in System Settings.[/]"
                )
        except Exception as e:
            out.print(f"  {bad} screen capture failed: {escape(str(e))}")
    return 0


def cmd_serve(argv: list[str]) -> int:
    from .constants import SERVER_DEFAULT_HOST, SERVER_DEFAULT_PORT, SERVER_TOKEN_ENV
    from .server import serve

    p = argparse.ArgumentParser(
        prog="ifseen serve",
        description="Local HTTP API: one-shot checks, watchers and a live event stream. "
        "See docs/api.md.",
    )
    p.add_argument(
        "targets", nargs="*", metavar="FILE|RECIPE", help="rules files or recipes to start"
    )
    p.add_argument("--host", default=SERVER_DEFAULT_HOST, help="default: %(default)s")
    p.add_argument("--port", type=int, default=SERVER_DEFAULT_PORT, help="default: %(default)s")
    p.add_argument(
        "--token",
        help=f"require 'Authorization: Bearer TOKEN' (or set ${SERVER_TOKEN_ENV}); "
        "required for non-loopback hosts",
    )
    p.add_argument(
        "--allow-shell",
        action="store_true",
        help="accept shell actions in configs sent over HTTP (remote code execution!)",
    )
    p.add_argument(
        "--allow-custom-endpoints",
        action="store_true",
        help="accept provider base_url / api_key_env in configs sent over HTTP",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="mock provider for everything; actions are printed instead of run",
    )
    args = p.parse_args(argv)
    token = args.token or os.environ.get(SERVER_TOKEN_ENV) or None

    preload: list[tuple[str, dict[str, Any]]] = []
    taken: set[str] = set()
    for target in args.targets:
        data = load_target(target)
        if args.dry_run:
            data = _apply_overrides(
                data,
                argparse.Namespace(
                    provider=None, model=None, base_url=None, every=None, dry_run=True
                ),
            )
        load_config(data)
        preload.append((slugify(Path(target).stem, taken), data))

    import logging

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    def ready(server: Any) -> None:
        auth = "bearer token" if server.token else "none (loopback only)"
        err.print(f"[bold]ifseen serve[/] on [cyan]{server.url}[/]  auth: {auth}")
        for wid, _ in preload:
            err.print(f"  started watcher [cyan]{escape(wid)}[/]")
        if args.allow_shell:
            err.print("[yellow]warning:[/] shell actions are accepted over HTTP")

    try:
        return serve(
            args.host,
            args.port,
            token=token,
            allow_shell=args.allow_shell,
            allow_custom_endpoints=args.allow_custom_endpoints,
            dry_run=args.dry_run,
            preload=preload,
            on_ready=ready,
        )
    except OSError as e:
        raise ConfigError(f"could not listen on {args.host}:{args.port}: {e.strerror}") from e


def _print_help() -> None:
    out = Console(highlight=False)
    out.print(f"""[bold]ifseen {VERSION}[/] - if seen (or heard), then do.

[bold]quick start[/]
  ifseen "a CI build on screen has failed" --say "build broke"
  ifseen "a person is at the door" --camera 0 --ntfy my-topic
  ifseen "someone says my name" --mic --notify --provider gemini

[bold]commands[/]
  ifseen CONDITION... \\[options]   watch for plain-English conditions (see --help)
  ifseen watch FILE|RECIPE        run a rules file or a built-in recipe
  ifseen test FILE --image IMG    print each rule's probability for one capture
  ifseen recipes [NAME]           list built-in recipes, or print one
  ifseen init [RECIPE]            write a starter ifseen.yaml
  ifseen doctor                   check keys, dependencies and permissions
  ifseen serve [FILE|RECIPE...]   local HTTP API + event stream (see docs/api.md)

[bold]providers[/] (auto-detected from env)
  GEMINI_API_KEY      Gemini Decision 1 - images [italic]and audio[/], free tier
  TYPESAFE_API_KEY    Jev
  AZURE_DECISION_*    Microsoft-Decision-1.1 on Azure Foundry
  OPENAI_API_KEY      any OpenAI-compatible vision model (or --provider ollama, fully local)
  --provider local    free offline SigLIP, images only (pip install 'ifseen[local]')
  --dry-run           no key needed: fake probabilities, actions printed not run
""")


if __name__ == "__main__":
    sys.exit(main())
