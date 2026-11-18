"""System One wire format: TypeSafe Jev, Microsoft-Decision (Azure Foundry), and
self-hosted Jev-compatible servers such as ollaya."""

from __future__ import annotations

import secrets

import httpx

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


class SystemOneProvider(Provider):
    supports = frozenset({"image"})

    def __init__(
        self,
        name: str,
        url: str,
        model: str,
        headers: dict[str, str],
        image_headers: dict[str, str] | None = None,
        price_per_m_input: float = 0.0,
        client: httpx.Client | None = None,
    ):
        super().__init__(model, client)
        self.name = name
        self.url = url
        self.headers = headers
        self.image_headers = image_headers or {}
        self.price_per_m_input = price_per_m_input

    def build_request(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> tuple[dict, dict[str, str]]:
        state = describe_capture(sample, context)
        body: dict = {"model": self.model}
        headers = dict(self.headers)
        if sample.jpeg is not None:
            # Jev swaps any plain-text occurrence of the asset key for the image; Azure
            # expects an "image:<key>" reference. "image:<key>" satisfies both.
            key = f"frame-{secrets.token_hex(6)}.jpg"
            state += f"\nFrame: image:{key}"
            body["assets"] = {
                key: {"type": "image", "format": "jpg", "data_base64": b64(sample.jpeg)}
            }
            headers.update(self.image_headers)
        body["state"] = state
        qs: dict[str, dict] = {}
        for q in questions:
            item: dict = {"type": "noul", "instructions": q.statement}
            if q.true_means or q.false_means:
                item["criteria"] = {
                    k: v for k, v in (("true", q.true_means), ("false", q.false_means)) if v
                }
            qs[q.key] = item
        body["questions"] = qs
        return body, headers

    def decide(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> Decision:
        self.check_sample(sample)
        body, headers = self.build_request(sample, questions, context)
        data, latency = self._post(self.url, body, headers)
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError(f"{self.name}: response had no answers")
        probs = {q.key: clamp_prob((answers.get(q.key) or {}).get("noul")) for q in questions}
        usage = data.get("usage") or {}
        tokens = int(usage.get("input_tokens") or 0)
        return Decision(
            probs=probs,
            input_tokens=tokens,
            latency_ms=latency,
            model=str(data.get("model") or self.model),
        )
