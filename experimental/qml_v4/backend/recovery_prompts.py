"""Prompt templates for the constrained recovery decision stage."""

from __future__ import annotations

import json

from translation_models import RecoveryIssue


RECOVERY_SYSTEM_PROMPT = """你是翻译失败块诊断器，只负责返回恢复建议，不执行任何文件、缓存或配置操作。
只能从以下 action 中选择一个：
RETRANSLATE、USE_FALLBACK_PROVIDER、APPLY_TERM_REPAIR、REMOVE_FURIGANA、
PRESERVE_QUOTED_JAPANESE、ALLOW_LOW_RISK、REQUIRE_USER_REVIEW、ABORT。
必须只返回 JSON，不要输出 Markdown 或解释文字：
{"action":"REQUIRE_USER_REVIEW","reason":"...","confidence":0.0,
"provider":"","model":"","prompt_preset":"","replacement":""}
当无法确定、内容审核拒绝或涉及高风险原文时，选择 REQUIRE_USER_REVIEW。
"""


def build_recovery_prompt(issue: RecoveryIssue) -> list[dict[str, str]]:
    """Build a model-neutral request body without including API credentials."""

    return [
        {"role": "system", "content": RECOVERY_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(issue.to_dict(), ensure_ascii=False, separators=(",", ":")),
        },
    ]
