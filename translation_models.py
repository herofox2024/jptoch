"""Shared translation results and public error types.

This module has no dependency on the translation engine. Provider, batch and UI
layers can import these contracts without creating a circular import through
``translator.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SingleChunkResult:
    """Result returned by a single translation API call."""

    content: str
    finish_reason: Optional[str] = None
    is_truncated: bool = False


@dataclass
class BatchJsonResult:
    """Result of a batch JSON request, including partial successes."""

    translations: Optional[List[Optional[str]]] = None
    new_terms: Optional[List[Dict[str, Any]]] = None
    missing_indices: List[int] = field(default_factory=list)
    finish_reason: Optional[str] = None
    is_truncated: bool = False
    raw_content: str = ""


class FastFailError(RuntimeError):
    """An unrecoverable request/configuration failure."""


class ContentModerationError(RuntimeError):
    """A provider rejected one or more source items during moderation."""

    def __init__(self, message: str, offending_indices: Optional[List[int]] = None):
        super().__init__(message)
        self.offending_indices = list(offending_indices or [])


class TranslationIncompleteError(RuntimeError):
    """Raised when one or more texts could not be translated safely."""

    def __init__(
        self,
        failed_texts: Optional[List[str]] = None,
        residue_texts: Optional[List[str]] = None,
        partial_results: Optional[Dict[str, str]] = None,
        failed_details: Optional[List[Dict[str, Any]]] = None,
        residue_details: Optional[List[Dict[str, Any]]] = None,
    ):
        self.failed_texts = list(dict.fromkeys(failed_texts or []))
        self.residue_texts = list(dict.fromkeys(residue_texts or []))
        self.partial_results = dict(partial_results or {})
        self.failed_details = self._normalize_failed_details(failed_details, self.failed_texts)
        self.residue_details = self._normalize_residue_details(residue_details, self.residue_texts)
        message = (
            f"翻译未完成：{len(self.failed_texts)} 条未成功翻译，"
            f"{len(self.residue_texts)} 条疑似仍有日文残留。"
            "已保留成功译文缓存，请降低并发/批量或切换模型后恢复续译。"
        )
        super().__init__(message)

    @staticmethod
    def _snippet(text: Any, limit: int = 220) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(value) <= limit:
            return value
        return value[:limit].rstrip() + "..."

    @classmethod
    def _normalize_failed_details(
        cls,
        details: Optional[List[Dict[str, Any]]],
        fallback_texts: List[str],
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        seen = set()
        for item in details or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("original") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(
                {
                    "text": text,
                    "reason": str(item.get("reason") or "未返回安全译文"),
                }
            )
        for text in fallback_texts:
            if text not in seen:
                seen.add(text)
                normalized.append({"text": text, "reason": "未返回安全译文"})
        return normalized

    @classmethod
    def _normalize_residue_details(
        cls,
        details: Optional[List[Dict[str, Any]]],
        fallback_texts: List[str],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for item in details or []:
            if not isinstance(item, dict):
                continue
            original = str(item.get("original") or item.get("text") or "").strip()
            if not original or original in seen:
                continue
            fragments = item.get("fragments") or []
            if isinstance(fragments, str):
                fragments = [fragments]
            fragments = [str(fragment).strip() for fragment in fragments if str(fragment).strip()]
            seen.add(original)
            normalized.append(
                {
                    "original": original,
                    "translated": str(item.get("translated") or ""),
                    "fragments": list(dict.fromkeys(fragments)),
                    "reason": str(item.get("reason") or "译文疑似仍有日文残留"),
                }
            )
        for text in fallback_texts:
            if text not in seen:
                seen.add(text)
                normalized.append(
                    {
                        "original": text,
                        "translated": "",
                        "fragments": [],
                        "reason": "译文疑似仍有日文残留",
                    }
                )
        return normalized

    def format_diagnostics(self, max_items: int = 5) -> str:
        """Format actionable diagnostics for logs and UI error panels."""

        lines = [
            (
                f"翻译未完成诊断：未成功翻译 {len(self.failed_texts)} 条，"
                f"疑似日文残留 {len(self.residue_texts)} 条。"
            )
        ]
        if self.failed_details:
            lines.append("[失败样例]")
            for index, detail in enumerate(self.failed_details[:max_items], 1):
                lines.append(f"{index}. 原文: {self._snippet(detail.get('text'))}")
                lines.append(f"   原因: {self._snippet(detail.get('reason'), 120)}")
        if self.residue_details:
            lines.append("[日文残留样例]")
            for index, detail in enumerate(self.residue_details[:max_items], 1):
                fragments = detail.get("fragments") or []
                fragment_text = "、".join(fragments[:8]) if fragments else "未知片段"
                lines.append(f"{index}. 残留片段: {self._snippet(fragment_text, 160)}")
                lines.append(f"   原文: {self._snippet(detail.get('original'))}")
                translated = self._snippet(detail.get("translated"))
                if translated:
                    lines.append(f"   译文: {translated}")
                reason = self._snippet(detail.get("reason"), 120)
                if reason:
                    lines.append(f"   原因: {reason}")
        return "\n".join(lines)
