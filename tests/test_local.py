from __future__ import annotations

import math
import sys

import pytest
from conftest import solid_jpeg

from ifseen.config import ProviderConfig, load_config
from ifseen.constants import LOCAL_DEFAULT_MODEL, LOCAL_GENERIC_LABELS, LOCAL_SIGLIP_LOGIT_OFFSET
from ifseen.media import Sample
from ifseen.providers import LocalProvider, ProviderConfigError, Question, build_provider
from ifseen.providers.local import score_question


class FakeScorer:
    device = "cpu"

    def __init__(self, logits: dict[str, float], calibrated: bool = True):
        self.table = logits
        self.calibrated = calibrated
        self.calls: list[list[str]] = []

    def logits(self, image, labels):
        assert image.size == (640, 480)
        self.calls.append(labels)
        return [self.table.get(label, -10.0) for label in labels]


def image_sample() -> Sample:
    return Sample(jpeg=solid_jpeg((230, 20, 20)), width=640, height=480)


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def test_contrast_is_a_two_way_softmax():
    scorer = FakeScorer({"The door is open.": -2.0, "The door is closed.": -5.0})
    p = LocalProvider(scorer=scorer)
    d = p.decide(
        image_sample(), [Question("open", "The door is open.", None, "The door is closed.")]
    )
    assert d.probs["open"] == pytest.approx(sigmoid(3.0))
    assert d.input_tokens == 0 and p.cost_usd(10_000) == 0.0
    assert scorer.calls == [["The door is open.", "The door is closed."]]


def test_siglip_without_contrast_uses_offset_sigmoid():
    scorer = FakeScorer({"A dog is on the sofa.": -1.0})
    d = LocalProvider(scorer=scorer).decide(
        image_sample(), [Question("dog", "A dog is on the sofa.")]
    )
    assert d.probs["dog"] == pytest.approx(sigmoid(-1.0 + LOCAL_SIGLIP_LOGIT_OFFSET))
    assert not any(g in scorer.calls[0] for g in LOCAL_GENERIC_LABELS)


def test_clip_without_contrast_competes_with_generic_captions():
    logits = {"A cat.": 30.0, **{g: 20.0 for g in LOCAL_GENERIC_LABELS}}
    scorer = FakeScorer(logits, calibrated=False)
    d = LocalProvider(scorer=scorer).decide(image_sample(), [Question("cat", "A cat.")])
    expected = 1 / (1 + len(LOCAL_GENERIC_LABELS) * math.exp(-10.0))
    assert d.probs["cat"] == pytest.approx(expected)
    assert set(LOCAL_GENERIC_LABELS) <= set(scorer.calls[0])


def test_shared_captions_are_scored_once_per_frame():
    scorer = FakeScorer({})
    qs = [
        Question("a", "A person is visible.", None, "An empty room."),
        Question("b", "A dog is visible.", None, "An empty room."),
    ]
    LocalProvider(scorer=scorer).decide(image_sample(), qs)
    assert scorer.calls == [["A person is visible.", "An empty room.", "A dog is visible."]]


def test_probabilities_stay_in_range_for_extreme_logits():
    q = Question("x", "x")
    assert score_question(q, {"x": -1e6}, calibrated=True) == 0.0
    assert score_question(q, {"x": 1e6}, calibrated=True) == 1.0


def test_audio_is_rejected():
    p = LocalProvider(scorer=FakeScorer({}))
    with pytest.raises(ProviderConfigError, match="can't hear"):
        p.decide(Sample(wav=b"RIFF", audio_rms=500), [Question("q", "Someone speaks.")])
    with pytest.raises(ProviderConfigError, match="gemini"):
        p.decide(
            Sample(jpeg=solid_jpeg((0, 0, 0)), wav=b"RIFF", audio_rms=500),
            [Question("q", "Someone speaks.")],
        )


def test_missing_torch_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    with pytest.raises(ProviderConfigError, match=r"ifseen\[local\]"):
        build_provider(ProviderConfig(name="local"), env={})


def test_config_accepts_local_provider():
    cfg = load_config(
        {
            "source": {"file": "x.jpg"},
            "provider": {"name": "local", "model": "openai/clip-vit-base-patch32"},
            "rules": [{"name": "open", "when": "The door is open.", "false_means": "Closed."}],
        }
    )
    assert cfg.provider.name == "local"
    assert cfg.provider.model == "openai/clip-vit-base-patch32"


def test_describe_and_default_model():
    p = LocalProvider(scorer=FakeScorer({}))
    assert p.model == LOCAL_DEFAULT_MODEL
    assert p.describe() == "local (siglip-base-patch16-224, cpu)"


def _model_cached(model: str) -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    return isinstance(try_to_load_from_cache(model, "config.json"), str)


@pytest.mark.skipif(
    not _model_cached(LOCAL_DEFAULT_MODEL), reason="needs ifseen[local] and a cached SigLIP model"
)
def test_real_siglip_tells_red_from_blue():
    pytest.importorskip("torch")
    p = LocalProvider()
    q = [Question("red", "A plain red square.", None, "A plain blue square.")]
    red = p.decide(Sample(jpeg=solid_jpeg((230, 20, 20)), width=640, height=480), q)
    blue = p.decide(Sample(jpeg=solid_jpeg((20, 20, 230)), width=640, height=480), q)
    assert red.probs["red"] > 0.5 > blue.probs["red"]
