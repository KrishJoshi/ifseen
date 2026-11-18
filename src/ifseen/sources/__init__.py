"""Capture sources. Each produces a `Sample` on demand."""

from __future__ import annotations

from ..config import SourceConfig
from .base import CompositeSource, MissingDependency, Source, SourceError, SourceExhausted


def build_source(cfg: SourceConfig, every: float = 2.0) -> Source:
    visual: Source | None = None
    if cfg.screen is not None:
        from .screen import ScreenSource

        visual = ScreenSource(cfg.screen)
    elif cfg.camera is not None:
        from .camera import CameraSource

        visual = CameraSource(cfg.camera)
    elif cfg.file is not None:
        from .file import FileSource

        visual = FileSource(cfg.file, step_seconds=every)
    elif cfg.url is not None:
        from .url import UrlSource

        visual = UrlSource(cfg.url)

    audio: Source | None = None
    if cfg.mic is not None:
        from .mic import MicSource

        audio = MicSource(cfg.mic)

    if visual and audio:
        return CompositeSource(visual, audio)
    assert visual or audio
    return visual or audio  # type: ignore[return-value]


__all__ = [
    "CompositeSource",
    "MissingDependency",
    "Source",
    "SourceError",
    "SourceExhausted",
    "build_source",
]
