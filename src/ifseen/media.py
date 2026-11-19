"""Frames, audio chunks and the small amount of image/audio maths ifseen needs."""

from __future__ import annotations

import io
import struct
import time
import wave
from dataclasses import dataclass, field

from PIL import Image, ImageChops

from .constants import (
    CHANGE_PIXEL_DELTA,
    CHANGE_THUMBNAIL_SIZE,
    IMAGE_MAX_SIDE,
    IMAGE_MIN_SIDE,
    JPEG_QUALITY,
)


@dataclass
class Sample:
    """One moment of the world: an optional still frame plus an optional audio chunk."""

    jpeg: bytes | None = None
    width: int = 0
    height: int = 0
    wav: bytes | None = None
    audio_rms: float = 0.0
    captured_at: float = field(default_factory=time.time)
    label: str = ""

    @property
    def has_image(self) -> bool:
        return self.jpeg is not None

    @property
    def has_audio(self) -> bool:
        return self.wav is not None

    @property
    def is_empty(self) -> bool:
        return not self.has_image and not self.has_audio


def fit_image(img: Image.Image, max_side: int = IMAGE_MAX_SIDE, min_side: int = IMAGE_MIN_SIDE):
    """Scale an image so both sides land inside [min_side, max_side] where possible."""
    img = img.convert("RGB")
    w, h = img.size
    scale = 1.0
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
    if min(w, h) * scale < min_side:
        scale = min_side / min(w, h)
        # Extremely thin images can't satisfy both bounds; cap the long side and pad later.
        if max(w, h) * scale > max_side:
            scale = max_side / max(w, h)
    if scale != 1.0:
        img = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
    w, h = img.size
    if min(w, h) < min_side:
        padded = Image.new("RGB", (max(w, min_side), max(h, min_side)), (0, 0, 0))
        padded.paste(img, (0, 0))
        img = padded
    return img


def image_to_sample(img: Image.Image, label: str = "") -> Sample:
    img = fit_image(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return Sample(jpeg=buf.getvalue(), width=img.width, height=img.height, label=label)


def thumbnail_signature(jpeg: bytes) -> bytes:
    """Small RGB fingerprint used for cheap change detection."""
    size = (CHANGE_THUMBNAIL_SIZE, CHANGE_THUMBNAIL_SIZE)
    with Image.open(io.BytesIO(jpeg)) as img:
        return img.convert("RGB").resize(size, Image.BILINEAR).tobytes()


def signature_distance(a: bytes, b: bytes) -> float:
    """Percentage (0-100) of thumbnail pixels that changed noticeably in any channel."""
    if len(a) != len(b) or not a:
        return 100.0
    size = (CHANGE_THUMBNAIL_SIZE, CHANGE_THUMBNAIL_SIZE)
    if len(a) != size[0] * size[1] * 3:
        return 100.0
    diff = ImageChops.difference(Image.frombytes("RGB", size, a), Image.frombytes("RGB", size, b))
    r, g, bl = diff.split()
    strongest = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    changed = strongest.point(lambda v: 255 if v > CHANGE_PIXEL_DELTA else 0).histogram()[255]
    return 100.0 * changed / (size[0] * size[1])


def pcm16_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def pcm16_rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


def wav_file_to_sample(path: str) -> Sample:
    with open(path, "rb") as f:
        return wav_bytes_to_sample(f.read(), label=path)


def wav_bytes_to_sample(raw: bytes, label: str = "") -> Sample:
    with wave.open(io.BytesIO(raw), "rb") as w:
        pcm = w.readframes(w.getnframes())
        width = w.getsampwidth()
    # Interleaved 16-bit samples give a fine loudness estimate regardless of channel count.
    # Other sample widths are rare here; treat them as "not silent".
    rms = pcm16_rms(pcm) if width == 2 else 1000.0
    return Sample(wav=raw, audio_rms=rms, label=label)
