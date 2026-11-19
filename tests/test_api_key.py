"""`api_key=` in the Python API: an explicit key instead of an env var, never echoed back."""

from __future__ import annotations

import json

import pytest

from ifseen import Watcher, check, check_detailed
from ifseen.providers import ProviderConfigError

KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TYPESAFE_API_KEY", "OPENAI_API_KEY")


@pytest.fixture(autouse=True)
def no_env_keys(monkeypatch):
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def gemini(fake_server):
    return {"name": "gemini", "base_url": f"{fake_server.url}/v1beta/decisions"}


def test_check_with_explicit_key(fake_server, red_png):
    probs = check(
        red_png, ["The image is mostly red."], provider=gemini(fake_server), api_key="test-key"
    )
    assert probs["the-image-is-mostly-red"] > 0.9
    sent = fake_server.requests[-1]["headers"]
    assert sent.get("x-goog-api-key") == "test-key"


def test_wrong_explicit_key_is_an_auth_error(fake_server, red_png):
    with pytest.raises(ProviderConfigError, match="authentication"):
        check(red_png, ["Red."], provider=gemini(fake_server), api_key="nope")


def test_explicit_key_overrides_env(fake_server, red_png, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "wrong-from-env")
    result = check_detailed(
        red_png, ["The image is mostly red."], provider=gemini(fake_server), api_key="test-key"
    )
    assert result.probs["the-image-is-mostly-red"] > 0.9


def test_systemone_key_goes_in_bearer_header(fake_server, red_png):
    check(
        red_png,
        ["The frame is mostly red."],
        provider={"name": "systemone", "base_url": fake_server.url},
        api_key="test-key",
    )
    assert fake_server.requests[-1]["headers"]["Authorization"] == "Bearer test-key"


def test_api_key_needs_explicit_provider(red_png):
    with pytest.raises(ProviderConfigError, match="explicit provider"):
        check(red_png, ["Red."], api_key="k")


def test_missing_key_still_explains_env_var(red_png):
    with pytest.raises(ProviderConfigError, match="GEMINI_API_KEY"):
        check(red_png, ["Red."], provider="gemini")


def test_watcher_uses_explicit_key_and_never_exposes_it(fake_server, red_png):
    w = Watcher(
        source={"file": str(red_png)},
        provider=gemini(fake_server),
        every="100ms",
        api_key="test-key",
    )
    seen = []
    w.add_rule("The image is mostly red.", name="red", then=[])
    w.on_decision(seen.append)
    w.run(max_ticks=1)
    assert seen and seen[0]["probs"]["red"] > 0.9
    assert "test-key" not in json.dumps(w.state(), default=str)
    assert "test-key" not in repr(w)


def test_watcher_from_config_with_key(fake_server, red_png):
    w = Watcher.from_config(
        {
            "source": {"file": str(red_png)},
            "provider": gemini(fake_server),
            "rules": [{"name": "red", "when": "The image is mostly red.", "then": []}],
        },
        api_key="test-key",
    )
    seen = []
    w.on_decision(seen.append)
    w.run(max_ticks=1)
    assert seen[0]["probs"]["red"] > 0.9
