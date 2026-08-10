"""Execute validated recovery actions on one failed translation block."""

from __future__ import annotations

from typing import Any, Optional

import translation_quality as tq
from translation_models import RecoveryAction, RecoveryDecision, RecoveryExecutionResult, RecoveryIssue


class RecoveryExecutor:
    """Execute only safe, bounded actions; never writes task or EPUB data."""

    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max(1, int(max_attempts or 2))

    def _review(self, action: str, reason: str, attempts: int) -> RecoveryExecutionResult:
        return RecoveryExecutionResult(
            status="needs_review",
            action=action,
            reason=reason,
            attempts=attempts,
        )

    @staticmethod
    def _translate(translator: Any, source: str) -> str:
        results = translator.translate_batch([source], batch_size=1)
        return str((dict(results or {})).get(source) or "").strip()

    def execute(
        self,
        issue: RecoveryIssue,
        decision: RecoveryDecision,
        translator: Any,
        *,
        fallback_translator: Optional[Any] = None,
    ) -> RecoveryExecutionResult:
        """Execute one validated decision and return a result for the caller."""

        attempts = max(0, int(issue.attempts or 0)) + 1
        if attempts > self.max_attempts:
            return self._review(decision.action, "已达到单块最大恢复次数", attempts - 1)

        action = str(decision.action or "").strip().upper()
        source = str(issue.original or "").strip()
        if not source:
            return self._review(action, "失败块缺少原文", attempts)
        if action in {
            RecoveryAction.REQUIRE_USER_REVIEW.value,
            RecoveryAction.ABORT.value,
            RecoveryAction.PRESERVE_QUOTED_JAPANESE.value,
        }:
            return self._review(action, decision.reason or "需要人工确认", attempts)

        try:
            if action == RecoveryAction.RETRANSLATE.value:
                translation = self._translate(translator, source)
            elif action == RecoveryAction.USE_FALLBACK_PROVIDER.value:
                if fallback_translator is None:
                    return self._review(action, "未提供备用模型实例", attempts)
                translation = self._translate(fallback_translator, source)
            elif action == RecoveryAction.APPLY_TERM_REPAIR.value:
                translation = tq.repair_save_time_japanese_residue(source, issue.translation)
            elif action == RecoveryAction.REMOVE_FURIGANA.value:
                translation = tq.repair_furigana_reading_residue(issue.translation)
            elif action == RecoveryAction.ALLOW_LOW_RISK.value:
                if issue.issue_type != "JAPANESE_RESIDUE_LOW":
                    return self._review(action, "只有低风险残留允许此动作", attempts)
                translation = issue.translation
            else:
                return self._review(action, "未实现的恢复动作", attempts)
        except Exception as exc:
            return self._review(action, f"恢复执行失败: {type(exc).__name__}", attempts)

        translation = str(translation or "").strip()
        if not translation:
            return self._review(action, "恢复结果为空", attempts)
        if action not in {RecoveryAction.ALLOW_LOW_RISK.value} and translator._is_incomplete_translation(source, translation):
            return self._review(action, "恢复结果仍未通过安全检查", attempts)
        return RecoveryExecutionResult(
            status="success",
            action=action,
            translation=translation,
            reason=decision.reason,
            attempts=attempts,
        )
