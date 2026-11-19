"""Rules-file schema. A rules file is YAML; see README for the full reference."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .constants import (
    ACTION_KINDS,
    BARE_ACTIONS,
    DEFAULT_CHANGE_THRESHOLD,
    DEFAULT_CONSECUTIVE,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_EVERY_SECONDS,
    DEFAULT_HYSTERESIS,
    DEFAULT_MAX_SKIP_SECONDS,
    DEFAULT_MIC_SECONDS,
    DEFAULT_PREFILTER_THRESHOLD,
    DEFAULT_SILENCE_RMS,
    DEFAULT_THRESHOLD,
)

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(ms|s|m|h)?\s*$")
_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, None: 1.0}
_RULE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

ProviderName = Literal[
    "auto", "gemini", "jev", "azure", "systemone", "openai", "ollama", "local", "mock"
]


class ConfigError(ValueError):
    pass


def parse_duration(value: Any) -> float:
    """'500ms' | '2s' | '5m' | '1h' | 3 -> seconds."""
    if isinstance(value, bool):
        raise ConfigError(f"invalid duration: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    m = _DURATION.match(str(value))
    if not m:
        raise ConfigError(f"invalid duration {value!r} (try '500ms', '2s', '5m', '1h')")
    return float(m.group(1)) * _UNITS[m.group(2)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ScreenSource(_Strict):
    monitor: int = 1
    region: tuple[int, int, int, int] | None = None  # left, top, width, height


class CameraSource(_Strict):
    device: int | str = 0  # index, or rtsp:// / http:// stream URL


class FileSource(_Strict):
    path: str
    loop: bool = False
    realtime: bool = True  # False = step through a video as fast as the API allows


class UrlSource(_Strict):
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


class MicSource(_Strict):
    seconds: float = Field(DEFAULT_MIC_SECONDS, gt=0, le=60)
    device: int | str | None = None
    silence_rms: float = DEFAULT_SILENCE_RMS


class SourceConfig(_Strict):
    screen: ScreenSource | None = None
    camera: CameraSource | None = None
    file: FileSource | None = None
    url: UrlSource | None = None
    mic: MicSource | None = None

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        # Accept "source: screen", "source: {camera: 0}", "source: {mic: true}", etc.
        if isinstance(data, str):
            data = {data: {}}
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if "screen" in out and (out["screen"] is True or out["screen"] is None):
            out["screen"] = {}
        if "screen" in out and isinstance(out["screen"], int):
            out["screen"] = {"monitor": out["screen"]}
        if "camera" in out and not isinstance(out["camera"], dict):
            cam = out["camera"]
            out["camera"] = {} if cam is True or cam is None else {"device": cam}
        if "file" in out and isinstance(out["file"], str):
            out["file"] = {"path": out["file"]}
        if "url" in out and isinstance(out["url"], str):
            out["url"] = {"url": out["url"]}
        if "mic" in out:
            if out["mic"] is False:
                out.pop("mic")
            elif out["mic"] is True or out["mic"] is None:
                out["mic"] = {}
        return out

    @model_validator(mode="after")
    def _one_visual(self) -> SourceConfig:
        visual = [n for n in ("screen", "camera", "file", "url") if getattr(self, n) is not None]
        if len(visual) > 1:
            raise ValueError(f"pick one visual source, got {visual}")
        if not visual and self.mic is None:
            raise ValueError("source needs one of: screen, camera, file, url, mic")
        return self

    @property
    def visual_kind(self) -> str | None:
        for n in ("screen", "camera", "file", "url"):
            if getattr(self, n) is not None:
                return n
        return None


class ProviderConfig(_Strict):
    name: ProviderName = "auto"
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    seed: int | None = None  # mock provider only
    resolution: Literal["low", "medium", "high", "ultra_high"] | None = None  # gemini only

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"name": data}
        return data


Action = dict[str, Any]


class Rule(_Strict):
    name: str
    when: str
    threshold: float = DEFAULT_THRESHOLD
    consecutive: int = Field(DEFAULT_CONSECUTIVE, alias="for", ge=1)
    cooldown: float = DEFAULT_COOLDOWN_SECONDS
    hysteresis: float = Field(DEFAULT_HYSTERESIS, ge=0, lt=1)
    then: list[Action] = Field(default_factory=list)
    true_means: str | None = None
    false_means: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _RULE_NAME.match(v):
            raise ValueError("rule name must be 1-64 chars of letters, digits, '_' or '-'")
        return v

    @field_validator("when")
    @classmethod
    def _when(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("'when' cannot be empty")
        return v.strip()

    @field_validator("threshold")
    @classmethod
    def _threshold(cls, v: float) -> float:
        if not 0.0 < v < 1.0:
            raise ValueError("threshold must be between 0 and 1 (exclusive)")
        return v

    @field_validator("cooldown", mode="before")
    @classmethod
    def _cooldown(cls, v: Any) -> float:
        return parse_duration(v)

    @field_validator("then", mode="before")
    @classmethod
    def _then(cls, v: Any) -> list[Action]:
        if v is None:
            return []
        if isinstance(v, (str, dict)):
            v = [v]
        out: list[Action] = []
        for item in v:
            if isinstance(item, str):
                # bare strings are action names with no options ("notify", "exit") or shell commands
                out.append({item: True} if item in BARE_ACTIONS else {"shell": item})
            elif isinstance(item, dict) and len(item) == 1:
                out.append(item)
            else:
                raise ValueError(f"each action must be a one-key mapping, got {item!r}")
        for a in out:
            (kind,) = a.keys()
            if kind not in ACTION_KINDS:
                raise ValueError(f"unknown action {kind!r}; expected one of {sorted(ACTION_KINDS)}")
        return out


class Prefilter(_Strict):
    """A cheap gating question; the main provider is only asked when it passes."""

    when: str
    provider: ProviderConfig
    threshold: float = DEFAULT_PREFILTER_THRESHOLD
    true_means: str | None = None
    false_means: str | None = None

    @field_validator("when")
    @classmethod
    def _when(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("'when' cannot be empty")
        return v.strip()

    @field_validator("threshold")
    @classmethod
    def _threshold(cls, v: float) -> float:
        if not 0.0 < v < 1.0:
            raise ValueError("threshold must be between 0 and 1 (exclusive)")
        return v

    @field_validator("provider")
    @classmethod
    def _explicit(cls, v: ProviderConfig) -> ProviderConfig:
        if v.name == "auto":
            raise ValueError("prefilter needs an explicit provider, e.g. 'provider: local'")
        return v


class WatchConfig(_Strict):
    source: SourceConfig
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    prefilter: Prefilter | None = None
    every: float = DEFAULT_EVERY_SECONDS
    skip_unchanged: bool = True
    change_threshold: float = DEFAULT_CHANGE_THRESHOLD
    max_skip: float = DEFAULT_MAX_SKIP_SECONDS
    context: str | None = None  # extra text sent alongside each sample
    rules: list[Rule]

    @field_validator("every", "max_skip", mode="before")
    @classmethod
    def _dur(cls, v: Any) -> float:
        return parse_duration(v)

    @field_validator("every")
    @classmethod
    def _every_min(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError("'every' must be at least 100ms")
        return v

    @model_validator(mode="after")
    def _unique(self) -> WatchConfig:
        if not self.rules:
            raise ValueError("at least one rule is required")
        if len(self.rules) > 1000:
            raise ValueError("decision APIs accept at most 1000 questions per call")
        names = [r.name for r in self.rules]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"duplicate rule names: {sorted(dupes)}")
        return self


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env(value: Any, env: dict[str, str] | None = None) -> Any:
    """Replace ${VAR} / ${VAR:-default} in every string, so secrets stay out of rule files."""
    import os

    env = os.environ if env is None else env
    if isinstance(value, str):

        def sub(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            if name in env:
                return env[name]
            if default is not None:
                return default
            raise ConfigError(f"environment variable ${{{name}}} is not set")

        return _ENV_REF.sub(sub, value)
    if isinstance(value, list):
        return [expand_env(v, env) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v, env) for k, v in value.items()}
    return value


def load_config(data: dict[str, Any]) -> WatchConfig:
    data = expand_env(data)
    try:
        return WatchConfig.model_validate(data)
    except Exception as e:  # pydantic.ValidationError, ConfigError
        raise ConfigError(_pretty(e)) from e


def load_config_file(path: str | Path) -> WatchConfig:
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"no such file: {p}") from e
    except yaml.YAMLError as e:
        raise ConfigError(f"{p}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{p}: expected a mapping at the top level")
    return load_config(data)


def _pretty(e: Exception) -> str:
    errors = getattr(e, "errors", None)
    if not callable(errors):
        return str(e)
    lines = []
    for err in errors():
        loc = ".".join(str(x) for x in err.get("loc", ()))
        msg = err.get("msg", "invalid").removeprefix("Value error, ")
        lines.append(f"  {loc or '<root>'}: {msg}")
    return "invalid config:\n" + "\n".join(lines)
