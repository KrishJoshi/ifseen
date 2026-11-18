from __future__ import annotations

import threading
import time

from PIL import Image

from ..config import CameraSource as CameraCfg
from ..media import Sample, image_to_sample
from .base import MissingDependency, Source, SourceError

_FIRST_FRAME_TIMEOUT = 10.0


class CameraSource(Source):
    """Webcam index or network stream (RTSP/HTTP MJPEG).

    A background thread drains the stream continuously so `read()` always returns the
    newest frame. Without it, OpenCV's internal buffer hands back frames that are
    seconds old on RTSP cameras.
    """

    kind = "camera"
    provides = frozenset({"image"})

    def __init__(self, cfg: CameraCfg):
        self.cfg = cfg
        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None

    def open(self) -> None:
        try:
            import cv2
        except ImportError as e:
            raise MissingDependency("opencv-python-headless", "camera") from e
        device = self.cfg.device
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        self._cap = cv2.VideoCapture(device)
        if not self._cap.isOpened():
            raise SourceError(f"could not open camera {self.cfg.device!r}")
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, name="ifseen-camera", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + _FIRST_FRAME_TIMEOUT
        while time.monotonic() < deadline:
            with self._lock:
                if self._frame is not None or self._error:
                    break
            time.sleep(0.05)
        if self._error:
            raise SourceError(self._error)
        if self._frame is None:
            raise SourceError(f"camera {self.cfg.device!r} produced no frames")

    def _pump(self) -> None:
        import cv2

        failures = 0
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok:
                failures += 1
                if failures > 50:
                    self._error = f"camera {self.cfg.device!r} stopped producing frames"
                    return
                time.sleep(0.1)
                continue
            failures = 0
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            with self._lock:
                self._frame = rgb

    def read(self) -> Sample:
        if self._cap is None:
            self.open()
        if self._error:
            raise SourceError(self._error)
        with self._lock:
            frame = self._frame
        if frame is None:
            raise SourceError("no camera frame available")
        return image_to_sample(Image.fromarray(frame), label=self.describe())

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def describe(self) -> str:
        d = self.cfg.device
        if isinstance(d, str) and "://" in d:
            # never echo stream credentials (rtsp://user:pass@host)
            scheme, rest = d.split("://", 1)
            return f"camera {scheme}://{rest.split('@')[-1]}"
        return f"camera {d}"
