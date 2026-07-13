# -*- coding: utf-8 -*-
"""Provider defaults and small provider-related helpers."""

import os
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class ProviderDefaults:
    api_url: str
    model: str
    env_keys: Tuple[str, ...] = ()
    requires_api_key: bool = True


PROVIDER_DEFAULTS: Dict[str, ProviderDefaults] = {
    "deepseek": ProviderDefaults(
        api_url="https://api.deepseek.com/chat/completions",
        model="deepseek-v4-flash",
        env_keys=("DEEPSEEK_API_KEY",),
    ),
    "doubao": ProviderDefaults(
        api_url="https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        model="Doubao-Seed-1.6-flash",
        env_keys=("DOUBAO_API_KEY", "ARK_API_KEY"),
    ),
    "sakura": ProviderDefaults(
        api_url="http://127.0.0.1:8080/v1/chat/completions",
        model="sakura-v1.0",
        requires_api_key=False,
    ),
    "gemini": ProviderDefaults(
        api_url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        model="gemini-2.5-flash",
    ),
    "glm": ProviderDefaults(
        api_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model="glm-4-flash",
        env_keys=("GLM_API_KEY", "ZHIPU_API_KEY"),
    ),
    "wenxin": ProviderDefaults(
        api_url="https://qianfan.baidubce.com/v2/chat/completions",
        model="ernie-4.5-turbo-128k",
        env_keys=("WENXIN_API_KEY", "QIANFAN_API_KEY"),
    ),
    "longcat": ProviderDefaults(
        api_url="https://api.longcat.chat/openai/v1/chat/completions",
        model="LongCat-2.0",
        env_keys=("LONGCAT_API_KEY",),
    ),
    "hymt2": ProviderDefaults(
        api_url="http://127.0.0.1:8080/v1/chat/completions",
        model="Hy-MT2-1.8B-Q4_K_M",
        requires_api_key=False,
    ),
    "custom": ProviderDefaults(api_url="", model=""),
}

SUPPORTED_PROVIDERS = frozenset(PROVIDER_DEFAULTS)
API_KEY_REQUIRED_PROVIDERS = frozenset(
    key for key, value in PROVIDER_DEFAULTS.items() if value.requires_api_key
)


def provider_default_url(provider: str) -> str:
    return PROVIDER_DEFAULTS.get((provider or "").strip().lower(), ProviderDefaults("", "")).api_url


def provider_default_model(provider: str) -> str:
    return PROVIDER_DEFAULTS.get((provider or "").strip().lower(), ProviderDefaults("", "")).model


def provider_env_api_key(provider: str) -> str:
    defaults = PROVIDER_DEFAULTS.get((provider or "").strip().lower())
    if not defaults:
        return ""
    for env_key in defaults.env_keys:
        value = os.getenv(env_key, "")
        if value:
            return value
    return ""


def normalize_api_url(url: str) -> str:
    """Normalize OpenAI-compatible base URLs to /chat/completions."""
    value = (url or "").strip()
    if not value:
        return value
    value = value.rstrip("/")
    lower = value.lower()
    if lower.endswith("/chat/completions"):
        return value
    if lower.endswith("/v1"):
        return value + "/chat/completions"
    if lower.endswith("/v1/chat"):
        return value + "/completions"
    return value + "/chat/completions"
