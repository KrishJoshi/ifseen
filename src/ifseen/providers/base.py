from __future__ import annotations

import base64
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from ..constants import HTTP_TIMEOUT_SECONDS
from ..media import Sample

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3


class ProviderError(RuntimeError):
    pass


class ProviderConfigError(ProviderError):
    """Missing key, unsupported modality, etc. Not worth retrying."""


@dataclass(frozen=True)
class Question:
    key: str
    statement: str
    true_means: str | None = None
    false_means: str | None = None


@dataclass
class Decision:
    probs: dict[str, float]
    input_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""


class Provider(ABC):
    name: str = "provider"
    supports: frozenset[str] = frozenset({"image"})
    price_per_m_input: float = 0.0

    def __init__(self, model: str, client: httpx.Client | None = None):
        self.model = model
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        return self._client

    def check_sample(self, sample: Sample) -> None:
        if sample.has_audio and "audio" not in self.supports:
            raise ProviderConfigError(
                f"{self.name} can't hear audio; use provider 'gemini' for mic sources"
            )
        if sample.has_image and "image" not in self.supports:
            raise ProviderConfigError(f"{self.name} can't see images")

    @abstractmethod
    def decide(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> Decision: ...

    def cost_usd(self, input_tokens: int) -> float:
        return input_tokens * self.price_per_m_input / 1_000_000

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
        self._client = None

    def describe(self) -> str:
        return f"{self.name} ({self.model})"

    # -- helpers ---------------------------------------------------------------------------

    def _post(self, url: str, json: dict, headers: dict[str, str]) -> tuple[dict, float]:
        """POST with small retry/backoff on rate limits and 5xx. Returns (json, latency_ms)."""
        last: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            start = time.perf_counter()
            try:
                r = self.client.post(url, json=json, headers=headers)
            except httpx.HTTPError as e:
                last = ProviderError(f"{self.name}: network error ({type(e).__name__})")
            else:
                latency = (time.perf_counter() - start) * 1000
                if r.status_code < 400:
                    try:
                        return r.json(), latency
                    except ValueError as e:
                        raise ProviderError(f"{self.name}: response was not JSON") from e
                last = ProviderError(f"{self.name}: HTTP {r.status_code}: {_error_text(r)}")
                if r.status_code in (401, 403):
                    raise ProviderConfigError(
                        f"{self.name}: authentication failed "
                        f"(HTTP {r.status_code}) - check your API key"
                    )
                if r.status_code == 402:
                    # out of credits / billing disabled: retrying can't help, stop the watcher
                    raise ProviderConfigError(
                        f"{self.name}: billing problem (HTTP 402): {_error_text(r)}"
                    )
                if r.status_code not in _RETRY_STATUSES:
                    raise last
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(0.5 * 2**attempt)
        assert last is not None
        raise last


def parse_noul_answers(
    name: str, data: object, questions: list[Question], usage_key: str
) -> tuple[dict[str, float], int]:
    """Pull noul probabilities and token usage out of a decision response, defensively."""
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        raise ProviderError(f"{name}: response had no answers")
    answers = data["answers"]
    probs = {}
    for q in questions:
        a = answers.get(q.key)
        probs[q.key] = clamp_prob(a.get("noul")) if isinstance(a, dict) else 0.0
    usage = data.get("usage")
    try:
        tokens = int(usage.get(usage_key) or 0) if isinstance(usage, dict) else 0
    except (TypeError, ValueError):
        tokens = 0
    return probs, tokens


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def clamp_prob(value: object) -> float:
    try:
        p = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if p != p:  # NaN
        return 0.0
    return min(1.0, max(0.0, p))


def describe_capture(sample: Sample, context: str | None) -> str:
    when = time.strftime("%H:%M:%S", time.localtime(sample.captured_at))
    what = []
    if sample.has_image:
        what.append("a still frame")
    if sample.has_audio:
        what.append("an audio clip")
    text = f"Live capture ({' and '.join(what)}) from {sample.label or 'a sensor'} at {when}."
    if context:
        text += f"\nContext: {context}"
    return text


def _error_text(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return r.text[:200]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if body.get("detail"):
            return str(body["detail"])[:300]
    return str(body)[:200]
