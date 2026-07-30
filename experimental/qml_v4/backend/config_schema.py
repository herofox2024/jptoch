"""Typed validation for persisted QML/V4 application settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Tuple
from urllib.parse import urlparse


CONFIG_DEFAULTS: Dict[str, Any] = {
    "inp": "",
    "out": "",
    "api_key": "",
    "provider": "deepseek",
    "api_url": "https://api.deepseek.com/chat/completions",
    "model": "deepseek-v4-flash",
    "extract_glossary": False,
    "enable_glossary": True,
    "enable_layered_glossary": False,
    "use_global_glossary": True,
    "use_genre_glossary": False,
    "use_series_glossary": False,
    "use_book_glossary": False,
    "pre_extract_glossary": False,
    "series_glossary_name": "",
    "book_glossary_name": "",
    "selected_glossary_profile_ids": [],
    "glossary_extraction_mode": "lite",
    "max_workers": 5,
    "batch_size": 4,
    "max_batch_length": 800,
    "max_text_size_for_batch": 200,
    "api_timeout": 120,
    "direction": "zh",
    "enable_thinking": False,
    "enable_proofread": True,
    "proofread_genre": "auto",
    "proofread_tone": "auto",
    "proofread_provider": "",
    "proofread_api_key": "",
    "proofread_api_url": "",
    "proofread_model": "",
    "allow_text_cache_reuse": True,
    "prompt_extra_instruction": "",
    "enable_prompt_examples": True,
    "theme": "light",
    "enable_notice_page": False,
    "notice_page_text": "",
    "hymt2_generation_mode": "stable",
    "hymt2_prompt_mode": "official",
    "hymt2_runtime_mode": "cpu",
    "japanese_residue_policy": "balanced",
}

INT_RANGES = {
    "max_workers": (1, 64),
    "batch_size": (1, 32),
    "max_batch_length": (100, 50_000),
    "max_text_size_for_batch": (20, 10_000),
    "api_timeout": (10, 1_800),
}

BOOL_KEYS = {
    "extract_glossary",
    "enable_glossary",
    "enable_layered_glossary",
    "use_global_glossary",
    "use_genre_glossary",
    "use_series_glossary",
    "use_book_glossary",
    "pre_extract_glossary",
    "enable_thinking",
    "enable_proofread",
    "allow_text_cache_reuse",
    "enable_prompt_examples",
    "enable_notice_page",
}

ENUM_VALUES = {
    "provider": {"deepseek", "doubao", "sakura", "gemini", "glm", "wenxin", "longcat", "hymt2", "custom"},
    "proofread_provider": {"", "deepseek", "doubao", "sakura", "gemini", "glm", "wenxin", "longcat", "hymt2", "custom"},
    "glossary_extraction_mode": {"novel", "lite"},
    "direction": {"zh"},
    "proofread_genre": {"auto", "general", "mystery", "historical_mystery", "scifi", "fantasy"},
    "proofread_tone": {"auto", "neutral", "light", "literary"},
    "theme": {"light", "dark", "glass"},
    "hymt2_generation_mode": {"stable", "official"},
    "hymt2_prompt_mode": {"official", "project"},
    "hymt2_runtime_mode": {"cpu", "gpu"},
    "japanese_residue_policy": {"strict", "balanced", "lenient"},
}

URL_KEYS = {"api_url", "proofread_api_url"}
LIST_KEYS = {"selected_glossary_profile_ids"}
LONG_TEXT_LIMITS = {
    "inp": 32_767,
    "out": 32_767,
    "api_key": 8_192,
    "proofread_api_key": 8_192,
    "prompt_extra_instruction": 20_000,
    "notice_page_text": 20_000,
}


@dataclass(frozen=True)
class ConfigIssue:
    key: str
    message: str


@dataclass(frozen=True)
class ConfigValidationResult:
    values: Dict[str, Any]
    issues: Tuple[ConfigIssue, ...]
    unknown_keys: Tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.issues and not self.unknown_keys


def _default_for(key: str, defaults: Mapping[str, Any]) -> Any:
    if key in defaults:
        value = defaults[key]
    else:
        value = CONFIG_DEFAULTS[key]
    return list(value) if isinstance(value, list) else value


def _coerce_bool(value: Any) -> tuple[bool, bool]:
    if isinstance(value, bool):
        return value, True
    if value in (0, 1):
        return bool(value), True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True, True
        if normalized in {"false", "0", "no", "off"}:
            return False, True
    return False, False


def _coerce_int(value: Any) -> tuple[int, bool]:
    if isinstance(value, bool):
        return 0, False
    if isinstance(value, int):
        return value, True
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("+-").isdigit():
            return int(stripped), True
    return 0, False


def _clean_list(value: Any) -> tuple[list[str], bool]:
    if not isinstance(value, (list, tuple)):
        return [], False
    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:160])
        if len(result) >= 100:
            break
    return result, True


def _valid_url(value: str) -> bool:
    if not value:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_config(
    payload: Any,
    *,
    defaults: Mapping[str, Any] | None = None,
    allowed_keys: Iterable[str] | None = None,
) -> ConfigValidationResult:
    """Validate known settings while preserving compatibility with old files."""
    source = payload if isinstance(payload, dict) else {}
    defaults = defaults or CONFIG_DEFAULTS
    allowed = set(allowed_keys or CONFIG_DEFAULTS)
    issues = []
    values: Dict[str, Any] = {}
    unknown = tuple(sorted(str(key) for key in source if key not in allowed))

    if not isinstance(payload, dict):
        issues.append(ConfigIssue("<root>", "配置根节点不是 JSON 对象，已使用默认值"))

    for key, raw_value in source.items():
        if key not in allowed or key not in CONFIG_DEFAULTS:
            continue
        fallback = _default_for(key, defaults)
        if key in BOOL_KEYS:
            value, ok = _coerce_bool(raw_value)
            if not ok:
                value = fallback
                issues.append(ConfigIssue(key, "布尔值无效，已回退默认值"))
        elif key in INT_RANGES:
            value, ok = _coerce_int(raw_value)
            if not ok:
                value = fallback
                issues.append(ConfigIssue(key, "整数值无效，已回退默认值"))
            else:
                lower, upper = INT_RANGES[key]
                bounded = max(lower, min(upper, value))
                if bounded != value:
                    issues.append(ConfigIssue(key, f"超出允许范围 {lower}-{upper}，已自动限制"))
                value = bounded
        elif key in LIST_KEYS:
            value, ok = _clean_list(raw_value)
            if not ok:
                value = fallback
                issues.append(ConfigIssue(key, "列表值无效，已回退默认值"))
        else:
            if isinstance(raw_value, (dict, list, tuple)) or raw_value is None:
                value = fallback
                issues.append(ConfigIssue(key, "文本值无效，已回退默认值"))
            else:
                value = str(raw_value).strip()
            if key in ENUM_VALUES:
                value = value.lower()
                if value not in ENUM_VALUES[key]:
                    value = fallback
                    issues.append(ConfigIssue(key, "选项值不受支持，已回退默认值"))
            if key in URL_KEYS and not _valid_url(value):
                value = ""
                issues.append(ConfigIssue(key, "URL 必须使用 http/https，已清空"))
            limit = LONG_TEXT_LIMITS.get(key, 1_024)
            if isinstance(value, str) and len(value) > limit:
                value = value[:limit]
                issues.append(ConfigIssue(key, f"文本超过 {limit} 字符，已截断"))
        values[key] = value

    if "max_batch_length" in values and "max_text_size_for_batch" in values:
        if values["max_text_size_for_batch"] > values["max_batch_length"]:
            values["max_text_size_for_batch"] = values["max_batch_length"]
            issues.append(ConfigIssue("max_text_size_for_batch", "不能大于批量总长度，已自动限制"))

    return ConfigValidationResult(values, tuple(issues), unknown)
