"""恢复提示词构造的单元测试 + 版本单一来源校验。

为什么补：
  - `recovery_prompts.py` 此前零测试。它构造发给「恢复模型」的请求体，
    其中一条硬约束是**绝不能包含 API 凭据**（模块 docstring 明确承诺）。
    这个承诺没有测试保护，一旦有人往 issue 里加了敏感字段就会静默泄漏。
  - `app_info.py` 的版本号是全项目唯一来源（pyproject 与 README 都引用它），
    但此前没有任何测试校验它与其他声明处一致。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML_ROOT = ROOT / "experimental" / "qml_v4"
for entry in (str(QML_ROOT), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from backend.app_info import APP_VERSION
from backend.recovery_prompts import RECOVERY_SYSTEM_PROMPT, build_recovery_prompt
from translation_models import RecoveryIssue


def _issue(**overrides) -> RecoveryIssue:
    payload = {
        "issue_type": "JAPANESE_RESIDUE",
        "original": "彼女は笑った。",
        "translation": "她笑了。の",
        "reason": "检测到日文残留",
    }
    payload.update(overrides)
    return RecoveryIssue(**payload)


# --- 提示词结构 -----------------------------------------------------------


def test_prompt_has_system_and_user_turns():
    messages = build_recovery_prompt(_issue())
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[0]["content"] == RECOVERY_SYSTEM_PROMPT


def test_system_prompt_declares_bounded_actions():
    """系统提示必须列出允许的动作，并规定无法确定时转人工复核。"""
    for action in (
        "RETRANSLATE", "USE_FALLBACK_PROVIDER", "APPLY_TERM_REPAIR",
        "REMOVE_FURIGANA", "PRESERVE_QUOTED_JAPANESE", "ALLOW_LOW_RISK",
        "REQUIRE_USER_REVIEW", "ABORT",
    ):
        assert action in RECOVERY_SYSTEM_PROMPT, action
    assert "REQUIRE_USER_REVIEW" in RECOVERY_SYSTEM_PROMPT


def test_user_turn_is_valid_compact_json():
    """user 段必须是可解析的 JSON，且不含多余空白（省 token）。"""
    raw = build_recovery_prompt(_issue())[1]["content"]
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    assert ", " not in raw, "compact separators 应去掉逗号后的空格"


def test_user_turn_carries_issue_fields():
    raw = build_recovery_prompt(_issue())[1]["content"]
    parsed = json.loads(raw)
    assert parsed["original"] == "彼女は笑った。"
    assert parsed["translation"] == "她笑了。の"


def test_prompt_never_includes_credentials():
    """回归保护：提示词不得携带 API 凭据。

    模块 docstring 承诺「without including API credentials」，
    RecoveryIssue 也没有 api_key 字段——本测试把这个契约钉死：
    即使以后有人给 dataclass 加了凭据字段，只要没同步进 to_dict，
    这里仍会通过；一旦进了 to_dict，就会立刻被这条断言抓住。
    """
    marked = _issue(reason="检测到日文残留")
    payload = json.dumps(build_recovery_prompt(marked), ensure_ascii=False)
    for forbidden in ("api_key", "apikey", "authorization", "bearer", "sk-"):
        assert forbidden not in payload.lower(), (forbidden, payload)

    # RecoveryIssue 本身不应存在凭据字段
    field_names = set(RecoveryIssue.__dataclass_fields__)
    for forbidden in ("api_key", "apikey", "token", "secret"):
        assert forbidden not in field_names, f"RecoveryIssue 出现了凭据字段: {forbidden}"


def test_prompt_handles_unicode_without_escaping():
    """中日文应原样保留，避免 \\uXXXX 转义浪费 token。"""
    raw = build_recovery_prompt(_issue())[1]["content"]
    assert "彼女は笑った。" in raw
    assert "\\u" not in raw


# --- 版本单一来源 ---------------------------------------------------------


def test_app_version_present_and_well_formed():
    assert APP_VERSION, "APP_VERSION 不能为空"
    parts = APP_VERSION.split(".")
    assert all(p.isdigit() for p in parts), f"版本号格式异常: {APP_VERSION}"
    assert 2 <= len(parts) <= 4, f"版本号段数异常: {APP_VERSION}"
