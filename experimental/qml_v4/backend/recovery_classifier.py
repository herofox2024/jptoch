"""Deterministic classification for failed translation blocks.

This module has no model, network, cache, or EPUB side effects. It prepares
stable issue records for the optional recovery workflow introduced later.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

import translation_quality as tq
from translation_models import RecoveryIssue, RecoveryIssueType


def _text(value: Any) -> str:
    return str(value or "").strip()


def _joined_reason(reason: Any, error: Optional[BaseException]) -> str:
    parts = [_text(reason)]
    if error is not None:
        parts.extend([type(error).__name__, _text(error)])
    return " ".join(part for part in parts if part).lower()


def _contains_any(value: str, terms: Iterable[str]) -> bool:
    return any(term in value for term in terms)


def _is_json_error(reason: str, error: Optional[BaseException]) -> bool:
    if isinstance(error, (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError)):
        return True
    return _contains_any(reason, ("json", "解析失败", "格式错误", "missing index", "invalid response"))


def _is_moderation_error(reason: str) -> bool:
    return _contains_any(
        reason,
        ("moderation", "contentmoderation", "security_audit_fail", "内容审核", "违规", "security_error"),
    )


def _is_timeout_error(reason: str) -> bool:
    return _contains_any(reason, ("timeout", "timed out", "超时", "连接失败"))


def _is_glossary_conflict(reason: str) -> bool:
    return _contains_any(reason, ("glossary conflict", "术语冲突", "术语不一致", "术语不匹配"))


def classify_recovery_issue(
    *,
    original: Any = "",
    translation: Any = "",
    reason: Any = "",
    fragments: Any = None,
    provider: Any = "",
    model: Any = "",
    attempts: int = 0,
    context_before: Any = "",
    context_after: Any = "",
    error: Optional[BaseException] = None,
) -> RecoveryIssue:
    """Build one normalized issue using deterministic precedence rules."""

    original_text = _text(original)
    translation_text = _text(translation)
    reason_text = _text(reason)
    signal = _joined_reason(reason, error)
    issue_type = RecoveryIssueType.PROVIDER_ERROR

    if _is_moderation_error(signal):
        issue_type = RecoveryIssueType.CONTENT_MODERATION
    elif _is_timeout_error(signal):
        issue_type = RecoveryIssueType.TIMEOUT
    elif _is_glossary_conflict(signal):
        issue_type = RecoveryIssueType.GLOSSARY_CONFLICT
    elif _is_json_error(signal, error):
        issue_type = RecoveryIssueType.JSON_PARSE_ERROR
    elif not translation_text:
        issue_type = RecoveryIssueType.EMPTY_RESPONSE
    else:
        residue = tq.classify_japanese_residue(translation_text)
        risk = str(residue.get("risk") or "none")
        issue_type = {
            "high": RecoveryIssueType.JAPANESE_RESIDUE_HIGH,
            "medium": RecoveryIssueType.JAPANESE_RESIDUE_MEDIUM,
            "low": RecoveryIssueType.JAPANESE_RESIDUE_LOW,
        }.get(risk, RecoveryIssueType.PROVIDER_ERROR)

    normalized_fragments = fragments
    if normalized_fragments is None and translation_text:
        normalized_fragments = tq.extract_japanese_residue_fragments(translation_text)
    if isinstance(normalized_fragments, str):
        normalized_fragments = [normalized_fragments]

    return RecoveryIssue(
        issue_type=issue_type.value,
        original=original_text,
        translation=translation_text,
        fragments=list(dict.fromkeys(_text(item) for item in (normalized_fragments or []) if _text(item))),
        provider=_text(provider),
        model=_text(model),
        attempts=max(0, int(attempts or 0)),
        context_before=_text(context_before),
        context_after=_text(context_after),
        reason=reason_text,
    )


def classify_failed_detail(
    detail: dict[str, Any],
    *,
    provider: Any = "",
    model: Any = "",
    attempts: int = 0,
    context_before: Any = "",
    context_after: Any = "",
) -> RecoveryIssue:
    """Convert a translator failed/residue detail into a RecoveryIssue."""

    item = dict(detail or {})
    return classify_recovery_issue(
        original=item.get("original") or item.get("text") or "",
        translation=item.get("translated") or item.get("translation") or "",
        reason=item.get("reason") or "",
        fragments=item.get("fragments"),
        provider=provider,
        model=model,
        attempts=attempts,
        context_before=context_before,
        context_after=context_after,
    )
