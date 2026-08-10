"""Constrained recovery decision agent.

The class only prepares requests and validates responses. It has no default
network client and therefore cannot change an EPUB, cache, or configuration.
Execution is intentionally deferred to the next recovery stage.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from translation_json_parser import extract_json_object
from translation_models import RecoveryAction, RecoveryDecision, RecoveryIssue, RecoveryIssueType

from .recovery_prompts import build_recovery_prompt


class RecoveryAgent:
    """Create and validate one recovery decision for a failed block."""

    def __init__(
        self,
        *,
        provider: str = "",
        model: str = "",
        fallback_provider: str = "",
        fallback_model: str = "",
        min_confidence: float = 0.85,
        enabled: bool = False,
        request_executor: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self.provider = str(provider or "").strip()
        self.model = str(model or "").strip()
        self.fallback_provider = str(fallback_provider or "").strip()
        self.fallback_model = str(fallback_model or "").strip()
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.enabled = bool(enabled)
        self.request_executor = request_executor

    def build_request(self, issue: RecoveryIssue) -> Dict[str, Any]:
        """Build a provider-neutral request using the issue's actual route."""

        provider = issue.provider or self.provider
        model = issue.model or self.model
        return {
            "provider": provider,
            "model": model,
            "messages": build_recovery_prompt(issue),
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }

    @staticmethod
    def _review(reason: str, issue: RecoveryIssue) -> RecoveryDecision:
        return RecoveryDecision(
            action=RecoveryAction.REQUIRE_USER_REVIEW.value,
            reason=reason,
            confidence=0.0,
            provider=issue.provider,
            model=issue.model,
            prompt_preset="failed_block_repair",
        )

    def _validate(self, payload: Any, issue: RecoveryIssue) -> RecoveryDecision:
        if not isinstance(payload, dict):
            return self._review("恢复模型返回的 JSON 不是对象", issue)

        action = str(payload.get("action") or "").strip().upper()
        allowed = {item.value for item in RecoveryAction}
        if action not in allowed:
            return self._review("恢复模型返回了不支持的 action", issue)

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            return self._review("恢复模型返回了无效置信度", issue)
        if not 0.0 <= confidence <= 1.0:
            return self._review("恢复模型置信度超出范围", issue)

        reason = str(payload.get("reason") or "").strip()[:1000]
        prompt_preset = str(payload.get("prompt_preset") or "").strip()[:120]
        replacement = str(payload.get("replacement") or "")[:4000]
        provider = str(payload.get("provider") or issue.provider or self.provider).strip()
        model = str(payload.get("model") or issue.model or self.model).strip()

        if action == RecoveryAction.USE_FALLBACK_PROVIDER.value:
            if not self.fallback_provider or not self.fallback_model:
                return self._review("未配置备用模型，禁止切换 provider", issue)
            if (provider, model) != (self.fallback_provider, self.fallback_model):
                return self._review("恢复模型请求切换到未配置的备用模型", issue)
        elif (provider, model) != (issue.provider or self.provider, issue.model or self.model):
            return self._review("恢复模型修改了当前任务的 provider/model", issue)

        if issue.issue_type == RecoveryIssueType.CONTENT_MODERATION.value and action not in {
            RecoveryAction.REQUIRE_USER_REVIEW.value,
            RecoveryAction.ABORT.value,
        }:
            return self._review("内容审核问题不能自动放行或重复提交", issue)

        if confidence < self.min_confidence and action not in {
            RecoveryAction.REQUIRE_USER_REVIEW.value,
            RecoveryAction.ABORT.value,
        }:
            return self._review(f"置信度低于阈值 {self.min_confidence:.2f}", issue)

        if action == RecoveryAction.ALLOW_LOW_RISK.value and issue.issue_type != RecoveryIssueType.JAPANESE_RESIDUE_LOW.value:
            return self._review("ALLOW_LOW_RISK 只允许用于低风险残留", issue)

        return RecoveryDecision(
            action=action,
            reason=reason,
            confidence=confidence,
            provider=provider,
            model=model,
            prompt_preset=prompt_preset,
            replacement=replacement,
        )

    def parse_response(self, raw_response: Any, issue: RecoveryIssue) -> RecoveryDecision:
        """Parse and validate a raw model response with safe review fallback."""

        if isinstance(raw_response, dict):
            return self._validate(raw_response, issue)
        try:
            payload = extract_json_object(str(raw_response or ""))
        except Exception:
            return self._review("恢复模型返回内容不是有效 JSON", issue)
        return self._validate(payload, issue)

    def decide(self, issue: RecoveryIssue) -> RecoveryDecision:
        """Return a decision; without an injected executor, require review."""

        if not self.enabled:
            return self._review("智能失败恢复未启用", issue)
        if self.request_executor is None:
            return self._review("未配置恢复模型请求执行器", issue)
        try:
            raw_response = self.request_executor(self.build_request(issue))
        except Exception as exc:
            return self._review(f"恢复模型请求失败: {type(exc).__name__}", issue)
        return self.parse_response(raw_response, issue)
