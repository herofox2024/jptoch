"""Orchestrate constrained recovery decisions and bounded execution.

The workflow is deliberately independent from QML and EPUB persistence.  A
caller may provide an already-confirmed decision (the current UI path), or let
the constrained agent produce one when recovery automation is explicitly
enabled.  Review/abort decisions never reach the executor.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from translation_models import RecoveryAction, RecoveryDecision, RecoveryExecutionResult, RecoveryIssue

from .recovery_agent import RecoveryAgent
from .recovery_executor import RecoveryExecutor


class RecoveryWorkflow:
    """Run recovery for one or more normalized failed-block issues."""

    def __init__(
        self,
        *,
        agent: RecoveryAgent,
        executor: RecoveryExecutor,
        translator: Any,
        fallback_translator: Optional[Any] = None,
    ):
        self.agent = agent
        self.executor = executor
        self.translator = translator
        self.fallback_translator = fallback_translator

    @staticmethod
    def _review(issue: RecoveryIssue, reason: str) -> RecoveryDecision:
        return RecoveryDecision(
            action=RecoveryAction.REQUIRE_USER_REVIEW.value,
            reason=reason,
            confidence=0.0,
            provider=issue.provider,
            model=issue.model,
            prompt_preset="failed_block_repair",
        )

    def decide(self, issue: RecoveryIssue) -> RecoveryDecision:
        """Ask the constrained agent for one validated decision."""

        return self.agent.decide(issue)

    def execute(self, issue: RecoveryIssue, decision: RecoveryDecision) -> RecoveryExecutionResult:
        """Execute only a validated, non-review decision."""
        return self.executor.execute(
            issue,
            decision,
            self.translator,
            fallback_translator=self.fallback_translator,
        )

    def run(self, issue: RecoveryIssue, decision: Optional[RecoveryDecision] = None) -> RecoveryExecutionResult:
        """Decide and execute one issue, or execute a user-confirmed decision."""

        selected = decision if decision is not None else self.decide(issue)
        return self.execute(issue, selected)

    def run_many(
        self,
        issues: Iterable[Tuple[str, RecoveryIssue, Optional[RecoveryDecision]]],
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, int]]:
        """Run bounded recovery serially and return item results plus counts."""

        results: Dict[str, Dict[str, Any]] = {}
        summary = {"attempted": 0, "success": 0, "needs_review": 0, "failed": 0}
        for source, issue, decision in issues:
            key = str(source or "").strip()
            if not key:
                continue
            summary["attempted"] += 1
            try:
                result = self.run(issue, decision)
            except Exception as exc:
                result = RecoveryExecutionResult(
                    status="needs_review",
                    action=RecoveryAction.REQUIRE_USER_REVIEW.value,
                    reason=f"恢复工作流异常: {type(exc).__name__}",
                    attempts=max(0, int(issue.attempts or 0)) + 1,
                )
            payload = result.to_dict()
            results[key] = payload
            status = str(payload.get("status") or "needs_review")
            if status == "success":
                summary["success"] += 1
            elif status == "needs_review":
                summary["needs_review"] += 1
            else:
                summary["failed"] += 1
        return results, summary
