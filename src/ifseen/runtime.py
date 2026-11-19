"""Building blocks shared by the CLI, the Python API and `ifseen serve`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError, Rule, WatchConfig
from .providers import Provider, ProviderConfigError, Question, build_provider, env_with_key
from .recipes import recipe_data, recipe_names
from .sources import Source, build_source


def load_target(target: str | Path) -> dict[str, Any]:
    """A path to a YAML rules file, or the name of a built-in recipe, as a raw config dict."""
    path = Path(target).expanduser()
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise ConfigError(f"{path}: invalid YAML: {e}") from e
        if not isinstance(data, dict):
            raise ConfigError(f"{path}: expected a mapping at the top level")
        return data
    if str(target) in recipe_names():
        return recipe_data(str(target))
    raise ConfigError(f"no such file or recipe: {target} (see `ifseen recipes`)")


def slugify(text: str, taken: set[str]) -> str:
    """A unique rule name derived from a statement. Adds the result to `taken`."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-") or "rule"
    name, n = base, 2
    while name in taken:
        name = f"{base[:36]}-{n}"
        n += 1
    taken.add(name)
    return name


def questions_for(rules: list[Rule]) -> list[Question]:
    return [Question(r.name, r.when, r.true_means, r.false_means) for r in rules]


def build_prefilter(cfg: WatchConfig, provides: frozenset[str]) -> Provider | None:
    if cfg.prefilter is None:
        return None
    prefilter = build_provider(cfg.prefilter.provider)
    # An image-only prefilter just ignores the audio of a camera + mic source, but it has
    # nothing to look at with a mic-only source.
    if not provides & prefilter.supports:
        prefilter.close()
        raise ProviderConfigError(
            f"prefilter provider {prefilter.name} can't handle {', '.join(sorted(provides))} input"
        )
    return prefilter


@dataclass
class Runtime:
    """The live objects a config needs: a source and the providers to ask."""

    source: Source
    provider: Provider
    prefilter: Provider | None = None
    owns_provider: bool = True

    def close(self) -> None:
        if self.owns_provider:
            self.provider.close()
        if self.prefilter is not None:
            self.prefilter.close()


def build_runtime(
    cfg: WatchConfig, provider: Provider | None = None, api_key: str | None = None
) -> Runtime:
    """Build source and providers for a config, checking the provider can handle the input.

    Pass `provider` to use an existing instance instead of `cfg.provider`; it is not closed.
    """
    owns = provider is None
    main = (
        build_provider(cfg.provider, env=env_with_key(cfg.provider, api_key))
        if provider is None
        else provider
    )
    try:
        source = build_source(cfg.source, every=cfg.every)
        missing = source.provides - main.supports
        if missing:
            raise ProviderConfigError(
                f"{main.name} can't handle {', '.join(sorted(missing))} input"
                + ("; use --provider gemini for mic sources" if "audio" in missing else "")
            )
        prefilter = build_prefilter(cfg, source.provides)
    except Exception:
        if owns:
            main.close()
        raise
    return Runtime(source, main, prefilter, owns_provider=owns)
