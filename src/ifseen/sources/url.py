from __future__ import annotations

import io
from urllib.parse import urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from ..config import UrlSource as UrlCfg
from ..constants import HTTP_TIMEOUT_SECONDS
from ..media import Sample, image_to_sample
from .base import Source, SourceError


class UrlSource(Source):
    """Polls an HTTP snapshot URL (IP cameras, Frigate, Home Assistant camera proxy...)."""

    kind = "url"
    provides = frozenset({"image"})

    def __init__(self, cfg: UrlCfg, client: httpx.Client | None = None):
        self.cfg = cfg
        self._client = client

    def open(self) -> None:
        if self._client is None:
            self._client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True)

    def read(self) -> Sample:
        if self._client is None:
            self.open()
        assert self._client is not None
        try:
            r = self._client.get(self.cfg.url, headers=self.cfg.headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise SourceError(f"snapshot request failed: {type(e).__name__}") from e
        try:
            with Image.open(io.BytesIO(r.content)) as img:
                return image_to_sample(img, label=self.describe())
        except UnidentifiedImageError as e:
            raise SourceError("snapshot URL did not return an image") from e

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def describe(self) -> str:
        parts = urlsplit(self.cfg.url)
        return f"url {parts.hostname}{parts.path}"
