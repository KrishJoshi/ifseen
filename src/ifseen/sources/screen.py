from __future__ import annotations

from PIL import Image

from ..config import ScreenSource as ScreenCfg
from ..media import Sample, image_to_sample
from .base import MissingDependency, Source, SourceError


class ScreenSource(Source):
    kind = "screen"
    provides = frozenset({"image"})

    def __init__(self, cfg: ScreenCfg):
        self.cfg = cfg
        self._sct = None

    def open(self) -> None:
        try:
            import mss
        except ImportError as e:
            raise MissingDependency("mss", "screen") from e
        self._sct = mss.mss()
        if self.cfg.monitor >= len(self._sct.monitors):
            raise SourceError(
                f"monitor {self.cfg.monitor} not found "
                f"({len(self._sct.monitors) - 1} available; 0 = all screens)"
            )

    def read(self) -> Sample:
        if self._sct is None:
            self.open()
        assert self._sct is not None
        if self.cfg.region:
            left, top, width, height = self.cfg.region
            area = {"left": left, "top": top, "width": width, "height": height}
        else:
            area = self._sct.monitors[self.cfg.monitor]
        shot = self._sct.grab(area)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return image_to_sample(img, label=self.describe())

    def close(self) -> None:
        if self._sct is not None:
            self._sct.close()
            self._sct = None

    def describe(self) -> str:
        if self.cfg.region:
            return f"screen region {self.cfg.region}"
        return "all screens" if self.cfg.monitor == 0 else f"screen {self.cfg.monitor}"
