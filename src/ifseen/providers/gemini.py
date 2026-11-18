"""Google Gemini Decisions API (gemini-decision-1). The only provider that hears audio."""

from __future__ import annotations

import httpx

from ..constants import GEMINI_DEFAULT_MODEL, GEMINI_URL, PRICE_PER_M_INPUT
from ..media import Sample
from .base import (
    Decision,
    Provider,
    ProviderError,
    Question,
    b64,
    clamp_prob,
    describe_capture,
)


class GeminiProvider(Provider):
    name = "gemini"
    supports = frozenset({"image", "audio"})
    price_per_m_input = PRICE_PER_M_INPUT["gemini"]

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        url: str | None = None,
        client: httpx.Client | None = None,
        extra_headers: dict[str, str] | None = None,
        resolution: str | None = None,
    ):
        super().__init__(model or GEMINI_DEFAULT_MODEL, client)
        self.resolution = resolution
        self.api_key = api_key
        self.url = url or GEMINI_URL
        self.extra_headers = extra_headers or {}

    def build_request(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> dict:
        blocks: list[dict] = [{"type": "text", "text": describe_capture(sample, context) + "\n"}]
        if sample.jpeg is not None:
            image = {"type": "image", "data": b64(sample.jpeg), "mime_type": "image/jpeg"}
            if self.resolution:
                image["resolution"] = self.resolution
            blocks.append(image)
        if sample.wav is not None:
            blocks.append({"type": "audio", "data": b64(sample.wav), "mime_type": "audio/wav"})
        qs: dict[str, dict] = {}
        for q in questions:
            item: dict = {"type": "noul", "instructions": q.statement}
            if q.true_means or q.false_means:
                item["criteria"] = {
                    k: v
                    for k, v in (
                        ("true_description", q.true_means),
                        ("false_description", q.false_means),
                    )
                    if v
                }
            qs[q.key] = item
        return {"model": self.model, "input": blocks, "questions": qs}

    def decide(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> Decision:
        self.check_sample(sample)
        body = self.build_request(sample, questions, context)
        headers = {"x-goog-api-key": self.api_key, **self.extra_headers}
        data, latency = self._post(self.url, body, headers)
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("gemini: response had no answers")
        probs = {q.key: clamp_prob((answers.get(q.key) or {}).get("noul")) for q in questions}
        usage = data.get("usage") or {}
        tokens = int(usage.get("total_input_tokens") or 0)
        return Decision(probs=probs, input_tokens=tokens, latency_ms=latency, model=self.model)
