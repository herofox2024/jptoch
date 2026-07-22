# -*- coding: utf-8 -*-
"""Cache helpers for model-scoped and cross-model translation caches."""

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

SHA256_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def cache_digest(text: str) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def text_cache_key(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def model_cache_key(
    provider: str,
    model: str,
    text: str,
    glossary_fingerprint: str = "",
) -> str:
    provider_model = f"{provider}:{model}".lower()
    digest = text_cache_key(text)
    suffix = f":g{glossary_fingerprint}" if glossary_fingerprint else ""
    return f"v2:{provider_model}{suffix}:{digest}"


def context_cache_key(
    provider: str,
    model: str,
    text: str,
    prev_text: Optional[str],
    next_text: Optional[str],
    preview_len: int,
    glossary_fingerprint: str = "",
) -> str:
    text_value = (text or "").strip()
    provider_model = f"{provider}:{model}".lower()
    text_digest = text_cache_key(text_value)
    prev_preview = (prev_text or "")[:preview_len]
    next_preview = (next_text or "")[:preview_len]
    context_digest = hashlib.sha256(
        f"{prev_preview}\n<<<TEXT>>>\n{text_value}\n<<<NEXT>>>\n{next_preview}".encode("utf-8")
    ).hexdigest()
    suffix = f":g{glossary_fingerprint}" if glossary_fingerprint else ""
    return f"v3ctx:{provider_model}{suffix}:{context_digest}:{text_digest}"


def parse_model_cache_key(key: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Return (kind, text_digest, context_digest) for v2/v3 cache keys."""
    value = str(key or "")
    parts = value.split(":")
    if value.startswith("v3ctx:") and len(parts) >= 4:
        context_digest = parts[-2]
        text_digest = parts[-1]
        if SHA256_DIGEST_RE.fullmatch(context_digest) and SHA256_DIGEST_RE.fullmatch(text_digest):
            return "context", text_digest, context_digest
    if value.startswith("v2:") and parts:
        text_digest = parts[-1]
        if SHA256_DIGEST_RE.fullmatch(text_digest):
            return "text", text_digest, None
    return "", None, None


def load_json_file(path: Union[str, Path], default: Any) -> Any:
    """Load a JSON file, returning *default* when it is missing or invalid."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default


def atomic_write_json(path: Union[str, Path], payload: Dict[str, Any]) -> None:
    """Atomically write JSON so interrupted saves do not corrupt cache files."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp_name, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, str(target))
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass
        raise
