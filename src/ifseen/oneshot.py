"""One-shot checks: ask a decision model about a single image and/or audio clip."""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from .config import ConfigError, ProviderConfig, Rule, pretty_error
from .constants import MAX_QUESTIONS
from .media import Sample, image_to_sample, wav_bytes_to_sample, wav_file_to_sample
from .providers import Provider, build_provider, env_with_key
from .runtime import questions_for, slugify

MediaInput = str | Path | bytes | Image.Image
ProviderSpec = str | Mapping[str, Any] | ProviderConfig | Provider
Statements = list[str] | Mapping[str, str | Mapping[str, Any]]

_RIFF = b"RIFF"


@dataclass
class CheckResult:
    """The full answer of a one-shot check."""

    probs: dict[str, float]
    input_tokens: int
    latency_ms: float
    cost_usd: float
    provider: str


def check(
    media: MediaInput | None,
    statements: Statements,
    *,
    audio: str | Path | bytes | None = None,
    provider: ProviderSpec = "auto",
    model: str | None = None,
    context: str | None = None,
    api_key: str | None = None,
) -> dict[str, float]:
    """Ask a decision model how likely each statement is for one image and/or audio clip.

    Args:
        media: an image path, image bytes, a PIL image, a ``.wav`` path / WAV bytes, or None
            when only ``audio`` is given.
        statements: a list of plain-English statements (keys become slugs, e.g.
            ``"a-parcel-is-on-the-doorstep"``), or ``{name: statement}``. A value may also be
            ``{"when": ..., "true_means": ..., "false_means": ...}``.
        audio: a ``.wav`` path or WAV bytes to send alongside the image.
        provider: a provider name, a provider config dict (same shape as YAML), or a
            :class:`~ifseen.providers.Provider` instance (not closed afterwards).
        model: override the provider's model.
        context: extra text sent with the capture.
        api_key: the provider's API key. Defaults to its env var (e.g. ``GEMINI_API_KEY``).
            Needs an explicit ``provider``.

    Returns:
        ``{name: probability}`` in the order the statements were given.

    Raises:
        ConfigError: bad statements or media.
        ProviderConfigError: missing key, or the provider can't handle the input.
        ProviderError: the provider call failed.
    """
    return check_detailed(
        media,
        statements,
        audio=audio,
        provider=provider,
        model=model,
        context=context,
        api_key=api_key,
    ).probs


def check_detailed(
    media: MediaInput | None,
    statements: Statements,
    *,
    audio: str | Path | bytes | None = None,
    provider: ProviderSpec = "auto",
    model: str | None = None,
    context: str | None = None,
    api_key: str | None = None,
) -> CheckResult:
    """Like :func:`check`, but also returns tokens, latency, cost and the provider used."""
    rules = statement_rules(statements)
    sample = make_sample(media, audio)
    owns = not isinstance(provider, Provider)
    if owns:
        cfg = provider_config(provider, model)
        prov = build_provider(cfg, env=env_with_key(cfg, api_key))
    else:
        prov = provider  # type: ignore[assignment]
    try:
        prov.check_sample(sample)
        decision = prov.decide(sample, questions_for(rules), context)
        return CheckResult(
            probs={r.name: decision.probs.get(r.name, 0.0) for r in rules},
            input_tokens=decision.input_tokens,
            latency_ms=decision.latency_ms,
            cost_usd=prov.cost_usd(decision.input_tokens),
            provider=prov.describe(),
        )
    finally:
        if owns:
            prov.close()


def statement_rules(statements: Statements) -> list[Rule]:
    """Validate statements given as a list or a ``{name: statement}`` mapping."""
    if isinstance(statements, str):
        statements = [statements]
    items: list[dict[str, Any]] = []
    if isinstance(statements, Mapping):
        for name, value in statements.items():
            spec = dict(value) if isinstance(value, Mapping) else {"when": value}
            items.append({"name": name, **spec})
    elif isinstance(statements, (list, tuple)):
        taken: set[str] = set()
        for s in statements:
            if not isinstance(s, str):
                raise ConfigError(f"statements must be strings, got {type(s).__name__}")
            items.append({"name": slugify(s, taken), "when": s})
    else:
        raise ConfigError("statements must be a list of strings or a {name: statement} mapping")
    if not items:
        raise ConfigError("at least one statement is required")
    if len(items) > MAX_QUESTIONS:
        raise ConfigError(f"at most {MAX_QUESTIONS} statements per call")
    allowed = {"name", "when", "true_means", "false_means"}
    rules = []
    for item in items:
        extra = set(item) - allowed
        if extra:
            raise ConfigError(f"statement {item.get('name')!r}: unknown keys {sorted(extra)}")
        try:
            rules.append(Rule.model_validate(item))
        except Exception as e:
            raise ConfigError(pretty_error(e)) from e
    return rules


def make_sample(media: MediaInput | None, audio: str | Path | bytes | None = None) -> Sample:
    """Turn user input (paths, bytes, PIL images, WAV) into a Sample."""
    sample = Sample()
    if media is not None:
        sample = _media_sample(media)
    if audio is not None:
        a = _audio_sample(audio)
        sample.wav, sample.audio_rms = a.wav, a.audio_rms
    if sample.is_empty:
        raise ConfigError("give an image and/or audio")
    return sample


def _media_sample(media: MediaInput) -> Sample:
    if isinstance(media, Image.Image):
        return image_to_sample(media, label="image")
    if isinstance(media, (bytes, bytearray)):
        data = bytes(media)
        if data[:4] == _RIFF:
            return _audio_sample(data)
        try:
            with Image.open(io.BytesIO(data)) as img:
                return image_to_sample(img, label="image")
        except (OSError, ValueError) as e:
            raise ConfigError("could not read the bytes as an image or WAV") from e
    if isinstance(media, (str, Path)):
        path = Path(media).expanduser()
        if path.suffix.lower() == ".wav":
            return _audio_sample(path)
        try:
            with Image.open(path) as img:
                return image_to_sample(img, label=path.name)
        except FileNotFoundError as e:
            raise ConfigError(f"no such file: {path}") from e
        except (OSError, ValueError) as e:
            raise ConfigError(f"could not read {path.name} as an image") from e
    raise ConfigError(f"unsupported media type {type(media).__name__}")


def _audio_sample(audio: str | Path | bytes) -> Sample:
    import wave

    try:
        if isinstance(audio, (bytes, bytearray)):
            return wav_bytes_to_sample(bytes(audio), label="audio")
        return wav_file_to_sample(str(Path(audio).expanduser()))
    except FileNotFoundError as e:
        raise ConfigError(f"no such file: {audio}") from e
    except (OSError, EOFError, wave.Error) as e:
        raise ConfigError("could not read audio as PCM WAV") from e


def provider_config(spec: ProviderSpec, model: str | None = None) -> ProviderConfig:
    """Validate a provider name / dict / ProviderConfig, optionally overriding the model."""
    if isinstance(spec, ProviderConfig):
        cfg = spec
    else:
        try:
            cfg = ProviderConfig.model_validate(dict(spec) if isinstance(spec, Mapping) else spec)
        except Exception as e:
            raise ConfigError(pretty_error(e)) from e
    return cfg.model_copy(update={"model": model}) if model else cfg
