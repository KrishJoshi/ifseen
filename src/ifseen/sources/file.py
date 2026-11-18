from __future__ import annotations

import time
import wave
from pathlib import Path

from PIL import Image

from ..config import FileSource as FileCfg
from ..media import Sample, image_to_sample, wav_file_to_sample
from .base import MissingDependency, Source, SourceError, SourceExhausted

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
AUDIO_SUFFIXES = {".wav"}


class FileSource(Source):
    """An image (re-read every tick, so you can overwrite it), a WAV, or a video file.

    Videos advance by wall-clock time when `realtime` is true, or by `every` seconds of
    video per tick otherwise - handy for scanning recordings quickly.
    """

    kind = "file"

    def __init__(self, cfg: FileCfg, step_seconds: float = 2.0):
        self.cfg = cfg
        self.path = Path(cfg.path).expanduser()
        self.step_seconds = step_seconds
        suffix = self.path.suffix.lower()
        self.mode = (
            "image"
            if suffix in IMAGE_SUFFIXES
            else "audio"
            if suffix in AUDIO_SUFFIXES
            else "video"
        )
        self.provides = frozenset({"audio"}) if self.mode == "audio" else frozenset({"image"})
        self._cap = None
        self._started = 0.0
        self._video_pos = 0.0
        self._duration = 0.0
        self._audio_done = False

    def open(self) -> None:
        if not self.path.exists():
            raise SourceError(f"no such file: {self.path}")
        if self.mode != "video":
            return
        try:
            import cv2
        except ImportError as e:
            raise MissingDependency("opencv-python-headless", "camera") from e
        self._cap = cv2.VideoCapture(str(self.path))
        if not self._cap.isOpened():
            raise SourceError(f"could not open video {self.path}")
        fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        frames = self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        self._duration = frames / fps if frames else 0.0
        self._started = time.monotonic()
        self._video_pos = 0.0

    def read(self) -> Sample:
        if self.mode == "image":
            try:
                with Image.open(self.path) as img:
                    return image_to_sample(img, label=self.describe())
            except (OSError, ValueError) as e:  # missing, half-written or not an image
                raise SourceError(f"could not read {self.path.name}: {type(e).__name__}") from e
        if self.mode == "audio":
            if self._audio_done and not self.cfg.loop:
                raise SourceExhausted(f"finished {self.path.name}")
            self._audio_done = True
            try:
                return wav_file_to_sample(str(self.path))
            except (OSError, EOFError, wave.Error) as e:
                raise SourceError(f"could not read {self.path.name} as PCM WAV") from e
        return self._read_video()

    def _read_video(self) -> Sample:
        import cv2

        if self._cap is None:
            self.open()
        if self.cfg.realtime:
            pos = time.monotonic() - self._started
        else:
            pos = self._video_pos
            self._video_pos += self.step_seconds
        if self._duration and pos >= self._duration:
            if not self.cfg.loop:
                raise SourceExhausted(f"finished {self.path.name}")
            pos %= self._duration
            self._started = time.monotonic() - pos
            self._video_pos = pos + self.step_seconds
        self._cap.set(cv2.CAP_PROP_POS_MSEC, pos * 1000)
        ok, frame = self._cap.read()
        if not ok:
            raise SourceExhausted(f"finished {self.path.name}")
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        sample = image_to_sample(img, label=f"{self.path.name} @ {pos:0.1f}s")
        return sample

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def describe(self) -> str:
        return f"{self.mode} {self.path.name}"
