from __future__ import annotations

import threading
from collections import deque

from ..config import MicSource as MicCfg
from ..constants import MIC_SAMPLE_RATE
from ..media import Sample, pcm16_rms, pcm16_to_wav
from .base import MissingDependency, Source, SourceError


class MicSource(Source):
    """Records continuously into a ring buffer; each read returns the last N seconds."""

    kind = "mic"
    provides = frozenset({"audio"})

    def __init__(self, cfg: MicCfg):
        self.cfg = cfg
        self._stream = None
        self._lock = threading.Lock()
        max_blocks = int(cfg.seconds * MIC_SAMPLE_RATE / 1024) + 2
        self._blocks: deque[bytes] = deque(maxlen=max_blocks)

    def open(self) -> None:
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            raise MissingDependency("sounddevice", "mic") from e

        def callback(indata, frames, time_info, status):  # noqa: ARG001
            with self._lock:
                self._blocks.append(bytes(indata))

        try:
            self._stream = sd.RawInputStream(
                samplerate=MIC_SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=1024,
                device=self.cfg.device,
                callback=callback,
            )
            self._stream.start()
        except Exception as e:  # PortAudioError and friends
            raise SourceError(f"could not open microphone: {e}") from e

    def read(self) -> Sample:
        if self._stream is None:
            self.open()
        with self._lock:
            pcm = b"".join(self._blocks)
        want = int(self.cfg.seconds * MIC_SAMPLE_RATE) * 2
        pcm = pcm[-want:]
        return Sample(
            wav=pcm16_to_wav(pcm, MIC_SAMPLE_RATE),
            audio_rms=pcm16_rms(pcm),
            label=self.describe(),
        )

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def describe(self) -> str:
        dev = "default mic" if self.cfg.device is None else f"mic {self.cfg.device}"
        return f"{dev} (last {self.cfg.seconds:g}s)"
