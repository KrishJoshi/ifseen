"""Offline provider for trying ifseen without a key (`--dry-run`) and for demos.

Probabilities drift as a seeded random walk, nudged by how much the frame changed, so
rules visibly rise and fall without any network calls.
"""

from __future__ import annotations

import random
import time

from ..media import Sample, signature_distance, thumbnail_signature
from .base import Decision, Provider, Question


class MockProvider(Provider):
    name = "mock"
    supports = frozenset({"image", "audio"})

    def __init__(self, seed: int | None = None):
        super().__init__("random-walk")
        self._rng = random.Random(seed)
        self._probs: dict[str, float] = {}
        self._last_sig: bytes | None = None

    def decide(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> Decision:
        start = time.perf_counter()
        motion = 0.0
        if sample.jpeg is not None:
            sig = thumbnail_signature(sample.jpeg)
            if self._last_sig is not None:
                motion = min(1.0, signature_distance(sig, self._last_sig) / 40)
            self._last_sig = sig
        out = {}
        for q in questions:
            p = self._probs.get(q.key, self._rng.uniform(0.05, 0.4))
            p += self._rng.gauss(0, 0.12) + motion * self._rng.uniform(-0.3, 0.6)
            p = min(0.99, max(0.01, p))
            self._probs[q.key] = p
            out[q.key] = p
        return Decision(
            probs=out,
            input_tokens=0,
            latency_ms=(time.perf_counter() - start) * 1000,
            model=self.model,
        )
