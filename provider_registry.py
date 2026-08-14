# -*- coding: utf-8 -*-
"""Provider defaults and small provider-related helpers."""

import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class RateLimit:
    """保守的并发/批量/超时上限（0 表示不限制）。"""

    max_workers: int = 0
    batch_size: int = 0
    max_batch_length: int = 0
    max_text_size_for_batch: int = 0
    min_timeout: int = 0


@dataclass(frozen=True)
class ProviderDefaults:
    api_url: str
    model: str
    env_keys: Tuple[str, ...] = ()
    requires_api_key: bool = True
    # 采样参数默认值（None 表示请求中不传）
    default_temperature: Optional[float] = 0.3
    default_top_p: Optional[float] = None
    default_frequency_penalty: Optional[float] = None
    # 速率/并发预设（0 表示不限制）
    rpm: int = 0
    tpm: int = 0
    max_workers: int = 0
    batch_size: int = 0


PROVIDER_DEFAULTS: Dict[str, ProviderDefaults] = {
    "deepseek": ProviderDefaults(
        api_url="https://api.deepseek.com/chat/completions",
        model="deepseek-v4-flash",
        env_keys=("DEEPSEEK_API_KEY",),
        rpm=36,
        tpm=120000,
        max_workers=6,
        batch_size=6,
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
        default_temperature=0.1,
        default_top_p=0.3,
        default_frequency_penalty=0.1,
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
        rpm=24,
        tpm=90000,
        max_workers=4,
        batch_size=4,
    ),
    "hymt2": ProviderDefaults(
        api_url="http://127.0.0.1:8080/v1/chat/completions",
        model="Hy-MT2-1.8B-Q4_K_M",
        requires_api_key=False,
        default_temperature=0.1,
        default_top_p=0.3,
    ),
    "custom": ProviderDefaults(api_url="", model=""),
}

_EMPTY_DEFAULTS = ProviderDefaults("", "")

SUPPORTED_PROVIDERS = frozenset(PROVIDER_DEFAULTS)
API_KEY_REQUIRED_PROVIDERS = frozenset(
    key for key, value in PROVIDER_DEFAULTS.items() if value.requires_api_key
)

# --- 条件性限流（依赖模型名 / 运行模式 / endpoint 等运行时信息） ---

# 智谱免费/轻量模型（模型名含 flash/free）的保守并发上限。
GLM_FREE_MODEL_RATE_LIMIT = RateLimit(
    max_workers=2,
    batch_size=2,
    max_batch_length=500,
    max_text_size_for_batch=150,
)
GLM_FREE_MODEL_MARKERS = ("flash", "free")

# Hy-MT2 本地模型按运行模式（CPU/GPU）分档。
HYMT2_RUNTIME_RATE_LIMITS: Dict[str, RateLimit] = {
    "cpu": RateLimit(
        max_workers=1,
        batch_size=1,
        max_batch_length=300,
        max_text_size_for_batch=120,
        min_timeout=300,
    ),
    "gpu": RateLimit(
        max_workers=6,
        batch_size=8,
        max_batch_length=1000,
        max_text_size_for_batch=250,
        min_timeout=300,
    ),
}

# LongCat 稳定性保护：endpoint 命中 marker 时收紧并发/批量。
LONGCAT_RATE_LIMIT = RateLimit(max_workers=4, batch_size=4)
LONGCAT_ENDPOINT_MARKER = "longcat"


def provider_default_url(provider: str) -> str:
    return PROVIDER_DEFAULTS.get((provider or "").strip().lower(), _EMPTY_DEFAULTS).api_url


def provider_default_model(provider: str) -> str:
    return PROVIDER_DEFAULTS.get((provider or "").strip().lower(), _EMPTY_DEFAULTS).model


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
