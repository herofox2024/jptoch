"""Fault-tolerant parsers for structured model responses."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

try:
    import json_repair
except Exception:  # pragma: no cover - optional dependency
    json_repair = None


TRANSLATION_VALUE_KEYS = (
    "zh",
    "translation",
    "translated",
    "text",
    "cn",
    "中文",
    "dst",
    "revised",
)


def _looks_like_translation_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for item in value[:3]:
        if isinstance(item, str):
            return True
        if isinstance(item, dict) and (
            any(key in item for key in TRANSLATION_VALUE_KEYS)
            or any(key in item for key in ("idx", "index", "id"))
        ):
            return True
    return False


def _looks_like_glossary_terms_list(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    return any(
        isinstance(item, dict)
        and any(key in item for key in ("src", "original", "dst", "translation", "category", "policy", "info"))
        for item in value[:3]
    )


def extract_json_object(raw: str, prefer_new_terms: bool = False) -> Optional[dict]:
    """Extract a batch JSON object from arrays, code fences or surrounding prose."""

    if not raw:
        return None
    text = raw.strip()

    def coerce(value: Any, allow_list: bool = True) -> Optional[dict]:
        if isinstance(value, dict):
            return value
        if allow_list and prefer_new_terms and _looks_like_glossary_terms_list(value):
            return {"new_terms": value}
        if allow_list and _looks_like_translation_list(value):
            return {"translations": value, "new_terms": []}
        return None

    def is_batch_container(value: Optional[dict]) -> bool:
        return isinstance(value, dict) and any(key in value for key in ("translations", "items", "new_terms"))

    def parse_candidate(candidate: str) -> Optional[dict]:
        candidate = (candidate or "").strip()
        if not candidate:
            return None
        try:
            parsed = json.loads(candidate)
            coerced = coerce(parsed, allow_list=True)
            if coerced is not None:
                return coerced
        except (json.JSONDecodeError, ValueError):
            if json_repair is not None:
                try:
                    parsed = json_repair.loads(candidate)
                    coerced = coerce(parsed, allow_list=True)
                    if coerced is not None:
                        return coerced
                except Exception:
                    pass
        decoder = json.JSONDecoder()
        fallback = None
        for match in re.finditer(r"[\{\[]", candidate):
            try:
                parsed, _ = decoder.raw_decode(candidate[match.start():])
            except (json.JSONDecodeError, ValueError):
                if json_repair is not None:
                    try:
                        parsed = json_repair.loads(candidate[match.start():])
                    except Exception:
                        continue
                else:
                    continue
            allow_list = True
            if isinstance(parsed, list):
                prefix = candidate[max(0, match.start() - 40):match.start()]
                allow_list = match.start() == 0 or bool(
                    re.search(r'"(?:translations|items)"\s*:\s*$', prefix)
                )
            coerced = coerce(parsed, allow_list=allow_list)
            if is_batch_container(coerced):
                return coerced
            if fallback is None:
                fallback = coerced
        return fallback if is_batch_container(fallback) else None

    parsed = parse_candidate(text)
    if parsed is not None:
        return parsed
    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
        parsed = parse_candidate(match.group(1))
        if parsed is not None:
            return parsed
    return None


def extract_lenient_indexed_items(
    raw: str,
    value_keys: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Recover indexed values from JSON-like output with unescaped quotes."""

    if not raw:
        return []
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text).strip()
    active_value_keys = value_keys or list(TRANSLATION_VALUE_KEYS)
    idx_matches = list(re.finditer(r'"(?:idx|index|id)"\s*:\s*"?(\d+)"?', text))
    if not idx_matches:
        return []

    def extract_value(chunk: str) -> Optional[str]:
        key_pattern = "|".join(re.escape(key) for key in active_value_keys)
        key_match = re.search(rf'"(?:{key_pattern})"\s*:', chunk)
        if not key_match:
            return None
        pos = key_match.end()
        while pos < len(chunk) and chunk[pos].isspace():
            pos += 1
        if pos >= len(chunk):
            return None
        if chunk[pos] == '"':
            start = pos + 1
            tail = chunk[start:]
            end_match = re.search(
                r'"\s*(?:,\s*"(?:idx|index|id|new_terms|src|dst|category)"\s*:|\}\s*,?\s*(?:\{|\]|,?\s*"new_terms"|$))',
                tail,
                flags=re.DOTALL,
            )
            if end_match:
                value = tail[:end_match.start()]
            else:
                last_quote = tail.rfind('"')
                value = tail[:last_quote] if last_quote >= 0 else tail
        else:
            end_match = re.search(r'\s*(?:,\s*"|\}\s*,?\s*(?:\{|\]|$))', chunk[pos:], flags=re.DOTALL)
            value = chunk[pos:pos + end_match.start()] if end_match else chunk[pos:]
        value = value.strip()
        if not value:
            return None
        return value.replace('\\"', '"').replace("\\n", "\n")

    items: List[Dict[str, Any]] = []
    for position, match in enumerate(idx_matches):
        idx = int(match.group(1))
        chunk_start = text.rfind("{", 0, match.start())
        if chunk_start < 0:
            chunk_start = match.start()
        next_start = idx_matches[position + 1].start() if position + 1 < len(idx_matches) else len(text)
        value = extract_value(text[chunk_start:next_start])
        if value is not None:
            items.append({"idx": idx, "zh": value})
    return items
