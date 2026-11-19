from __future__ import annotations

import io

from PIL import Image, ImageDraw

from ifseen.media import image_to_sample, signature_distance, thumbnail_signature


def status_page(colour) -> bytes:
    """A mostly-white page where only a small status line differs."""
    img = Image.new("RGB", (1280, 800), (246, 248, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1280, 60], fill=(36, 41, 47))
    for i in range(4):
        d.rectangle([40, 260 + i * 80, 400, 300 + i * 80], fill=colour)
    return image_to_sample(img).jpeg


def test_green_to_red_status_counts_as_changed():
    # same brightness, different hue - the case a greyscale diff misses
    a, b = status_page((26, 127, 55)), status_page((207, 34, 46))
    assert signature_distance(thumbnail_signature(a), thumbnail_signature(b)) > 1.0


def test_jpeg_reencode_noise_counts_as_unchanged():
    a = status_page((26, 127, 55))
    again = image_to_sample(Image.open(io.BytesIO(a))).jpeg
    assert signature_distance(thumbnail_signature(a), thumbnail_signature(again)) < 0.25


def test_mismatched_signatures_are_fully_changed():
    assert signature_distance(b"", b"") == 100.0
    assert signature_distance(b"abc", b"abcd") == 100.0
