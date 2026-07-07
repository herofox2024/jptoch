# -*- coding: utf-8 -*-
"""Small OpenAI-compatible provider client helpers used by the translator."""

import re
from typing import Any, Dict, Optional

import requests


CONTENT_MODERATION_SNIPPETS = (
    "security_audit_fail",
    "security_error",
    "内容审核拦截",
    "内容审核未通过",
    "违规信息",
    "contentfilter",
    "content filter",
    "code\":\"1301",
    "不安全或敏感内容",
    "敏感内容",
    "content_moderation",
    "content moderation",
)


def create_session(max_workers: int) -> requests.Session:
    """Create a requests session sized for the translator worker pool."""
    session = requests.Session()
    pool_size = max(1, int(max_workers or 1))
    adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def apply_payload_options(payload: Dict[str, Any], provider: str, enable_thinking: bool) -> None:
    """Apply provider-specific OpenAI-compatible payload flags in-place."""
    active_provider = (provider or "").strip().lower()
    if (not enable_thinking) and active_provider in {"deepseek", "doubao", "glm", "longcat", "custom"}:
        payload["thinking"] = {"type": "disabled"}


def response_snippet(raw: str, limit: int = 240) -> str:
    """Compact API response content for local diagnostics."""
    text = re.sub(r"\s+", " ", (raw or "").strip())
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def is_content_moderation_http_error(error: requests.exceptions.HTTPError) -> bool:
    """Detect provider-side content moderation failures from HTTP responses."""
    resp = getattr(error, "response", None)
    if resp is None or resp.status_code != 400:
        return False
    try:
        body = (resp.text or "").lower()
    except Exception:
        return False
    if not body:
        return False
    return any(snippet in body for snippet in CONTENT_MODERATION_SNIPPETS)


def is_auth_http_error(error: requests.exceptions.HTTPError) -> bool:
    """Return True for authentication/authorization HTTP failures."""
    resp = getattr(error, "response", None)
    return bool(resp is not None and resp.status_code in (401, 403))
