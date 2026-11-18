from __future__ import annotations

from abc import ABC, abstractmethod

from ..media import Sample


class SourceError(RuntimeError):
    pass


class SourceExhausted(SourceError):
    """Raised by finite sources (files) when there is nothing left to read."""


class MissingDependency(SourceError):
    def __init__(self, package: str, extra: str):
        super().__init__(
            f"this source needs the '{package}' package: pip install 'ifseen[{extra}]'"
        )


class Source(ABC):
    kind: str = "source"
    provides: frozenset[str] = frozenset()

    def open(self) -> None:  # noqa: B027 - optional hook
        pass

    @abstractmethod
    def read(self) -> Sample: ...

    def close(self) -> None:  # noqa: B027 - optional hook
        pass

    def describe(self) -> str:
        return self.kind

    def __enter__(self) -> Source:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class CompositeSource(Source):
    """A visual source and an audio source read together into one sample."""

    kind = "composite"

    def __init__(self, visual: Source, audio: Source):
        self.visual = visual
        self.audio = audio
        self.provides = visual.provides | audio.provides

    def open(self) -> None:
        self.visual.open()
        self.audio.open()

    def read(self) -> Sample:
        v = self.visual.read()
        a = self.audio.read()
        v.wav, v.audio_rms = a.wav, a.audio_rms
        return v

    def close(self) -> None:
        self.visual.close()
        self.audio.close()

    def describe(self) -> str:
        return f"{self.visual.describe()} + {self.audio.describe()}"
