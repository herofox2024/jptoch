# -*- coding: utf-8 -*-
"""Diagnostic bundle helpers shared by QML/V4 backend code."""

import json
import time
from pathlib import Path
from typing import Any, Mapping

SENSITIVE_CONFIG_KEYS = {"api_key", "proofread_api_key"}


def mask_secret(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}***{text[-4:]}"


def build_redacted_config_snapshot(config: Mapping[str, Any]) -> dict:
    snapshot = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    for key, value in dict(config or {}).items():
        if key in SENSITIVE_CONFIG_KEYS:
            snapshot[f"{key}_masked"] = mask_secret(value)
            continue
        snapshot[key] = value
    for key in SENSITIVE_CONFIG_KEYS:
        snapshot.setdefault(f"{key}_masked", "")
    return snapshot


def load_redacted_config_snapshot(config_path: Path) -> dict:
    data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        data = {}
    return build_redacted_config_snapshot(data)
