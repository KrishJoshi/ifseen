"""Free, offline zero-shot provider: a CLIP-style model (SigLIP by default) on this machine.

It compares one image embedding with a text embedding per rule, so it's fast (tens of ms on
Apple Silicon) and costs nothing, but it only *matches pictures to captions*: it can't hear,
reads screen text poorly and has no idea about the capture context. Good as a prefilter or for
"is there a dog / person / parcel" rules; see benchmarks/hard-rules-results.md.
"""

from __future__ import annotations

import io
import math
import time
from typing import Protocol

from PIL import Image

from ..constants import LOCAL_DEFAULT_MODEL, LOCAL_GENERIC_LABELS, LOCAL_SIGLIP_LOGIT_OFFSET
from ..media import Sample
from .base import Decision, Provider, ProviderConfigError, Question


class Scorer(Protocol):
    """Image-text matching logits for one image against a list of captions."""

    # True when logits are SigLIP-style (sigmoid(logit) is already a match probability).
    calibrated: bool
    device: str

    def logits(self, image: Image.Image, labels: list[str]) -> list[float]: ...


class LocalProvider(Provider):
    name = "local"
    supports = frozenset({"image"})
    price_per_m_input = 0.0

    def __init__(self, model: str | None = None, scorer: Scorer | None = None):
        super().__init__(model or LOCAL_DEFAULT_MODEL)
        self.scorer = scorer or TransformersScorer(self.model)

    def describe(self) -> str:
        return f"{self.name} ({self.model.split('/')[-1]}, {self.scorer.device})"

    def check_sample(self, sample: Sample) -> None:
        super().check_sample(sample)
        if not sample.has_image:
            raise ProviderConfigError("local needs an image")

    def decide(
        self, sample: Sample, questions: list[Question], context: str | None = None
    ) -> Decision:
        self.check_sample(sample)
        with Image.open(io.BytesIO(sample.jpeg)) as img:  # type: ignore[arg-type]
            image = img.convert("RGB")
        labels = list(dict.fromkeys(label for q in questions for label in _labels(q)))
        generic = not self.scorer.calibrated and any(not q.false_means for q in questions)
        if generic:
            labels += [g for g in LOCAL_GENERIC_LABELS if g not in labels]
        start = time.perf_counter()
        logits = dict(zip(labels, self.scorer.logits(image, labels), strict=True))
        latency = (time.perf_counter() - start) * 1000
        probs = {q.key: score_question(q, logits, self.scorer.calibrated) for q in questions}
        return Decision(probs=probs, input_tokens=0, latency_ms=latency, model=self.model)


def _labels(q: Question) -> list[str]:
    return [q.statement, q.false_means] if q.false_means else [q.statement]


def score_question(q: Question, logits: dict[str, float], calibrated: bool) -> float:
    """Turn image-caption logits into a yes/no probability.

    With a contrast (false_means): two-way softmax, statement vs contrast. Best for states
    whose "no" looks like the "yes" (open vs closed door). Without one, SigLIP's own sigmoid
    match score shifted by a fixed offset, because raw SigLIP scores for true captions mostly
    sit around 0.01-0.3. CLIP has no such score, so it competes against generic captions.
    """
    s = logits[q.statement]
    if q.false_means:
        return _sigmoid(s - logits[q.false_means])
    if calibrated:
        return _sigmoid(s + LOCAL_SIGLIP_LOGIT_OFFSET)
    others = [logits[g] for g in LOCAL_GENERIC_LABELS if g != q.statement]
    top = max([s, *others])
    total = sum(math.exp(x - top) for x in [s, *others])
    return math.exp(s - top) / total


def _sigmoid(x: float) -> float:
    if x < -60:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


class TransformersScorer:
    """Hugging Face CLIP/SigLIP via transformers. Caption embeddings are cached, so each
    frame costs one image forward pass."""

    def __init__(self, model: str):
        try:
            import torch
            from transformers import AutoModel, AutoProcessor
        except ImportError as e:
            raise ProviderConfigError(
                "provider 'local' needs torch and transformers: pip install 'ifseen[local]'"
            ) from e
        self._torch = torch
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
        try:
            self._model = AutoModel.from_pretrained(model).to(self.device).eval()
            self._processor = AutoProcessor.from_pretrained(model)
        except (OSError, ValueError) as e:
            raise ProviderConfigError(
                f"local: could not load model {model!r} ({type(e).__name__}); use a Hugging "
                "Face CLIP or SigLIP model id, e.g. google/siglip-base-patch16-224"
            ) from e
        self.calibrated = getattr(self._model, "logit_bias", None) is not None
        self._text: dict[str, object] = {}

    def _text_features(self, labels: list[str]):
        torch = self._torch
        missing = [t for t in labels if t not in self._text]
        if missing:
            # SigLIP was trained on max_length padding; dynamic padding skews its scores.
            pad = {"padding": "max_length"} if self.calibrated else {"padding": True}
            inputs = self._processor(text=missing, return_tensors="pt", truncation=True, **pad).to(
                self.device
            )
            with torch.no_grad():
                feats = _tensor(self._model.get_text_features(**inputs))
            feats = feats / feats.norm(dim=-1, keepdim=True)
            for t, f in zip(missing, feats, strict=True):
                self._text[t] = f
        return torch.stack([self._text[t] for t in labels])  # type: ignore[misc]

    def logits(self, image: Image.Image, labels: list[str]) -> list[float]:
        torch = self._torch
        text = self._text_features(labels)
        inputs = self._processor(images=image, return_tensors="pt").to(self.device)
        with torch.no_grad():
            feats = _tensor(self._model.get_image_features(**inputs))
            feats = feats / feats.norm(dim=-1, keepdim=True)
            out = (feats @ text.T)[0] * self._model.logit_scale.exp()
            if self.calibrated:
                out = out + self._model.logit_bias
        return out.float().cpu().tolist()


def _tensor(out: object):
    # transformers 5 returns a ModelOutput from get_*_features; 4.x returned the tensor
    return getattr(out, "pooler_output", out)
