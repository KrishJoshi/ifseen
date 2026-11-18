from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))

from fake_server import FakeDecisionServer  # noqa: E402


def solid_jpeg(colour: tuple[int, int, int], size=(640, 480)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def fake_server():
    with FakeDecisionServer() as server:
        yield server


@pytest.fixture
def red_png(tmp_path) -> Path:
    p = tmp_path / "red.png"
    Image.new("RGB", (800, 600), (230, 20, 20)).save(p)
    return p


@pytest.fixture
def blue_png(tmp_path) -> Path:
    p = tmp_path / "blue.png"
    Image.new("RGB", (800, 600), (20, 20, 230)).save(p)
    return p


@pytest.fixture
def blue_then_red_video(tmp_path) -> Path:
    """4s @ 10fps: 2s blue, then 2s red."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (640, 480))
    assert writer.isOpened()
    for i in range(40):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (230, 20, 20) if i < 20 else (20, 20, 230)  # BGR: blue, then red
        writer.write(frame)
    writer.release()
    return path
