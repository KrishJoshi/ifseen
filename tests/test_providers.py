from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from conftest import solid_jpeg
from PIL import Image

from ifseen.config import ProviderConfig
from ifseen.media import Sample, image_to_sample
from ifseen.providers import (
    MockProvider,
    ProviderConfigError,
    ProviderError,
    Question,
    build_provider,
    detect_provider_name,
)
from ifseen.providers.llm import parse_probabilities

Q = [
    Question("is-red", "The frame is mostly red."),
    Question("is-blue", "The frame is mostly blue.", true_means="blue", false_means="other"),
]


def red_sample():
    return Sample(jpeg=solid_jpeg((230, 20, 20)), width=640, height=480, label="test")


def test_detect_provider_order():
    assert detect_provider_name({"GEMINI_API_KEY": "x", "TYPESAFE_API_KEY": "y"}) == "gemini"
    assert detect_provider_name({"TYPESAFE_API_KEY": "y"}) == "jev"
    assert (
        detect_provider_name({"AZURE_DECISION_ENDPOINT": "e", "AZURE_DECISION_KEY": "k"}) == "azure"
    )
    assert detect_provider_name({"OPENAI_API_KEY": "k"}) == "openai"
    with pytest.raises(ProviderConfigError, match="dry-run"):
        detect_provider_name({})


def test_missing_key_is_config_error():
    with pytest.raises(ProviderConfigError, match="GEMINI_API_KEY"):
        build_provider(ProviderConfig(name="gemini"), env={})
    with pytest.raises(ProviderConfigError, match="model"):
        build_provider(ProviderConfig(name="ollama"), env={})


def test_gemini_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "answers": {
                    "is-red": {"type": "noul", "noul": 0.97, "confidence": 0.97},
                    "is-blue": {"type": "noul", "noul": 0.02, "confidence": 0.98},
                },
                "usage": {"total_input_tokens": 312, "total_output_tokens": 0},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = build_provider(
        ProviderConfig(name="gemini", resolution="low"), client=client, env={"GEMINI_API_KEY": "k"}
    )
    sample = red_sample()
    sample.wav = b"RIFFfake"
    d = p.decide(sample, Q, context="kitchen camera")
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/decisions"
    assert seen["headers"]["x-goog-api-key"] == "k"
    body = seen["body"]
    assert body["model"] == "gemini-decision-1"
    types = [b["type"] for b in body["input"]]
    assert types == ["text", "image", "audio"]
    assert "kitchen camera" in body["input"][0]["text"]
    assert body["input"][1]["mime_type"] == "image/jpeg"
    assert body["input"][1]["resolution"] == "low"
    assert base64.b64decode(body["input"][1]["data"]) == sample.jpeg
    assert body["questions"]["is-red"] == {"type": "noul", "instructions": Q[0].statement}
    assert body["questions"]["is-blue"]["criteria"] == {
        "true_description": "blue",
        "false_description": "other",
    }
    assert d.probs == {"is-red": 0.97, "is-blue": 0.02}
    assert d.input_tokens == 312
    assert p.cost_usd(1_000_000) == pytest.approx(0.10)


def test_jev_request_shape_and_image_header():
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "jev-1.14.0",
                "answers": {"is-red": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 77, "output_tokens": 0},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    p = build_provider(ProviderConfig(name="jev"), client=client, env={"TYPESAFE_API_KEY": "t"})
    d = p.decide(red_sample(), Q)
    h, body = seen["headers"], seen["body"]
    assert h["authorization"] == "Bearer t"
    assert h["typesafe-danger-zone-images"] == "true"
    (key,) = body["assets"]
    assert f"image:{key}" in body["state"]
    assert body["assets"][key]["format"] == "jpg"
    assert body["questions"]["is-blue"]["criteria"] == {"true": "blue", "false": "other"}
    assert d.probs == {"is-red": 0.9, "is-blue": 0.0}  # missing answer fails closed
    assert d.model == "jev-1.14.0" and d.input_tokens == 77


def test_azure_url_and_key():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"answers": {}, "usage": {"input_tokens": 1, "output_tokens": 0}}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    env = {
        "AZURE_DECISION_ENDPOINT": "https://res.services.ai.azure.com/",
        "AZURE_DECISION_KEY": "ak",
        "AZURE_DECISION_DEPLOYMENT": "my-dep",
    }
    build_provider(ProviderConfig(name="azure"), client=client, env=env).decide(red_sample(), Q)
    assert seen["url"] == "https://res.services.ai.azure.com/providers/microsoft/v1/systemone"
    assert seen["headers"]["api-key"] == "ak"
    assert seen["body"]["model"] == "my-dep"


def test_audio_rejected_by_image_only_providers():
    p = build_provider(ProviderConfig(name="jev"), env={"TYPESAFE_API_KEY": "t"})
    with pytest.raises(ProviderConfigError, match="gemini"):
        p.decide(Sample(wav=b"x"), Q)


def test_auth_failure_is_config_error_and_400_is_provider_error():
    responses = iter(
        [
            httpx.Response(401, json={"detail": "nope"}),
            httpx.Response(400, json={"error": {"message": "bad question"}}),
        ]
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))
    p = build_provider(ProviderConfig(name="gemini"), client=client, env={"GEMINI_API_KEY": "k"})
    with pytest.raises(ProviderConfigError, match="authentication"):
        p.decide(red_sample(), Q)
    with pytest.raises(ProviderError, match="bad question"):
        p.decide(red_sample(), Q)


def test_retries_on_429(monkeypatch):
    monkeypatch.setattr("ifseen.providers.base.time.sleep", lambda s: None)
    responses = iter(
        [
            httpx.Response(429, json={}),
            httpx.Response(503, json={}),
            httpx.Response(200, json={"answers": {"is-red": {"noul": 0.5}}}),
        ]
    )
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))
    p = build_provider(ProviderConfig(name="gemini"), client=client, env={"GEMINI_API_KEY": "k"})
    assert p.decide(red_sample(), Q).probs["is-red"] == 0.5


@pytest.mark.parametrize(
    "text,expected",
    [
        ('{"a": 0.9, "b": 0.1}', {"a": 0.9, "b": 0.1}),
        ('Sure!\n```json\n{"a": 0.3}\n```', {"a": 0.3}),
        ('{"a": {"probability": 0.7}, "b": "high", "c": true}', {"a": 0.7}),
        ("no json here", {}),
        ("{broken", {}),
    ],
)
def test_parse_probabilities(text, expected):
    assert parse_probabilities(text) == expected


def test_mock_provider_is_deterministic_with_seed():
    a = MockProvider(seed=1).decide(red_sample(), Q).probs
    b = MockProvider(seed=1).decide(red_sample(), Q).probs
    assert a == b and all(0 < v < 1 for v in a.values())


def test_image_bounds_respected():
    for size in [(4000, 3000), (100, 80), (3000, 200), (500, 500)]:
        s = image_to_sample(Image.new("RGB", size, (1, 2, 3)))
        w, h = Image.open(io.BytesIO(s.jpeg)).size
        assert max(w, h) <= 1568 and min(w, h) >= 280, (size, (w, h))


# -- real HTTP against the local fake server -----------------------------------------------


@pytest.mark.parametrize(
    "name,env",
    [
        ("gemini", {"GEMINI_API_KEY": "test-key"}),
        ("systemone", {"TYPESAFE_API_KEY": "test-key"}),
        ("openai", {"OPENAI_API_KEY": "test-key"}),
    ],
)
def test_providers_over_http(fake_server, name, env):
    if name == "gemini":
        cfg = ProviderConfig(name="gemini", base_url=f"{fake_server.url}/v1beta/decisions")
    elif name == "systemone":
        cfg = ProviderConfig(name="systemone", base_url=fake_server.url)
    else:
        cfg = ProviderConfig(name="openai", base_url=f"{fake_server.url}/v1", model="vision")
    p = build_provider(cfg, env=env)
    try:
        d = p.decide(red_sample(), Q)
    finally:
        p.close()
    assert d.probs["is-red"] > 0.9
    assert d.probs["is-blue"] < 0.1


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"answers": []},
        {"answers": {"is-red": "yes"}},
        {"answers": {"is-red": {"noul": "high"}}, "usage": {"total_input_tokens": "lots"}},
    ],
)
def test_malformed_responses_never_crash(payload):
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    )
    p = build_provider(ProviderConfig(name="gemini"), client=client, env={"GEMINI_API_KEY": "k"})
    try:
        d = p.decide(red_sample(), Q)
    except ProviderError:
        return
    assert d.probs == {"is-red": 0.0, "is-blue": 0.0}
    assert d.input_tokens == 0
