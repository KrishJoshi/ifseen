"""Decision providers and auto-detection."""

from __future__ import annotations

import os

import httpx

from ..config import ProviderConfig
from ..constants import (
    AZURE_DEFAULT_MODEL,
    AZURE_DEPLOYMENT_ENV,
    AZURE_ENDPOINT_ENV,
    AZURE_KEY_ENV,
    AZURE_PATH,
    GEMINI_KEY_ENVS,
    JEV_DEFAULT_MODEL,
    JEV_IMAGE_HEADER,
    JEV_KEY_ENV,
    JEV_URL,
    OLLAMA_DEFAULT_BASE,
    OPENAI_BASE_ENV,
    OPENAI_DEFAULT_BASE,
    OPENAI_KEY_ENV,
    PRICE_PER_M_INPUT,
)
from .base import Decision, Provider, ProviderConfigError, ProviderError, Question
from .gemini import GeminiProvider
from .llm import OpenAICompatProvider
from .local import LocalProvider
from .mock import MockProvider
from .systemone import SystemOneProvider


def detect_provider_name(env: dict[str, str] | None = None) -> str:
    env = dict(os.environ) if env is None else env
    if any(env.get(k) for k in GEMINI_KEY_ENVS):
        return "gemini"
    if env.get(JEV_KEY_ENV):
        return "jev"
    if env.get(AZURE_ENDPOINT_ENV) and env.get(AZURE_KEY_ENV):
        return "azure"
    if env.get(OPENAI_KEY_ENV):
        return "openai"
    raise ProviderConfigError(
        "no decision-model key found. Set one of GEMINI_API_KEY (recommended - free tier "
        "at https://aistudio.google.com/apikey), TYPESAFE_API_KEY, AZURE_DECISION_ENDPOINT + "
        "AZURE_DECISION_KEY, or OPENAI_API_KEY. Or run free and offline with --provider local "
        "(pip install 'ifseen[local]'), or try it with --dry-run."
    )


def _key(
    env: dict[str, str], cfg: ProviderConfig, defaults: tuple[str, ...], required: bool = True
) -> str | None:
    names = (cfg.api_key_env,) if cfg.api_key_env else defaults
    for n in names:
        if env.get(n):
            return env[n]
    if required:
        raise ProviderConfigError(f"provider '{cfg.name}' needs ${' or $'.join(names)} set")
    return None


def build_provider(
    cfg: ProviderConfig, client: httpx.Client | None = None, env: dict[str, str] | None = None
) -> Provider:
    env = dict(os.environ) if env is None else env
    name = cfg.name if cfg.name != "auto" else detect_provider_name(env)

    if name == "mock":
        return MockProvider(seed=cfg.seed)

    if name == "local":
        return LocalProvider(model=cfg.model)

    if name == "gemini":
        key = _key(env, cfg, GEMINI_KEY_ENVS)
        assert key
        return GeminiProvider(
            key,
            model=cfg.model,
            url=cfg.base_url,
            client=client,
            extra_headers=cfg.headers,
            resolution=cfg.resolution,
        )

    if name == "jev":
        key = _key(env, cfg, (JEV_KEY_ENV,))
        return SystemOneProvider(
            name="jev",
            url=cfg.base_url or JEV_URL,
            model=cfg.model or JEV_DEFAULT_MODEL,
            headers={"Authorization": f"Bearer {key}", **cfg.headers},
            image_headers={JEV_IMAGE_HEADER: "true"},
            price_per_m_input=PRICE_PER_M_INPUT["jev"],
            client=client,
        )

    if name == "azure":
        endpoint = cfg.base_url or env.get(AZURE_ENDPOINT_ENV)
        if not endpoint:
            raise ProviderConfigError(
                f"provider 'azure' needs ${AZURE_ENDPOINT_ENV} "
                "(your Foundry resource endpoint) or base_url"
            )
        key = _key(env, cfg, (AZURE_KEY_ENV,))
        url = endpoint.rstrip("/")
        if not url.endswith("/systemone"):
            url += AZURE_PATH
        model = cfg.model or env.get(AZURE_DEPLOYMENT_ENV) or AZURE_DEFAULT_MODEL
        return SystemOneProvider(
            name="azure",
            url=url,
            model=model,
            headers={"api-key": key or "", **cfg.headers},
            price_per_m_input=PRICE_PER_M_INPUT["azure"],
            client=client,
        )

    if name == "systemone":
        if not cfg.base_url:
            raise ProviderConfigError(
                "provider 'systemone' needs base_url, e.g. "
                "http://localhost:8080 for a local ollaya server"
            )
        url = cfg.base_url.rstrip("/")
        if not url.endswith("/systemone"):
            url += "/v1/systemone"
        key = _key(env, cfg, (JEV_KEY_ENV,), required=False)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return SystemOneProvider(
            name="systemone",
            url=url,
            model=cfg.model or JEV_DEFAULT_MODEL,
            headers={**headers, **cfg.headers},
            image_headers={JEV_IMAGE_HEADER: "true"},
            client=client,
        )

    if name == "openai":
        if not cfg.model:
            raise ProviderConfigError(
                "provider 'openai' needs a vision model, e.g. model: gpt-4.1-mini"
            )
        key = _key(env, cfg, (OPENAI_KEY_ENV,), required=cfg.base_url is None)
        base = cfg.base_url or env.get(OPENAI_BASE_ENV) or OPENAI_DEFAULT_BASE
        return OpenAICompatProvider("openai", base, cfg.model, key, client, cfg.headers)

    if name == "ollama":
        if not cfg.model:
            raise ProviderConfigError(
                "provider 'ollama' needs a local vision model, e.g. "
                "model: gemma3 (run `ollama pull gemma3` first)"
            )
        return OpenAICompatProvider(
            "ollama", cfg.base_url or OLLAMA_DEFAULT_BASE, cfg.model, None, client, cfg.headers
        )

    raise ProviderConfigError(f"unknown provider {name!r}")


__all__ = [
    "Decision",
    "GeminiProvider",
    "LocalProvider",
    "MockProvider",
    "OpenAICompatProvider",
    "Provider",
    "ProviderConfigError",
    "ProviderError",
    "Question",
    "SystemOneProvider",
    "build_provider",
    "detect_provider_name",
]
