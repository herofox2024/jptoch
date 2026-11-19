"""一致性检查结果写回术语表：单元测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translation_consistency_apply import (
    apply_updates_to_terms,
    build_glossary_updates,
)


def _report(issues):
    return {"scanned_pairs": 10, "scanned_terms": 5, "issues": issues}


def _divergent(original, variants, category="Person"):
    return {
        "original": original,
        "category": category,
        "verdict": "divergent",
        "expected": variants[0][0],
        "detail": "出现多种译法",
        "variants": [{"translation": t, "count": c, "chapters": []} for t, c in variants],
    }


# ---------- divergent：取最高频 ----------


def test_divergent_picks_most_frequent_variant():
    """实测：ローラ 出现 劳拉37/萝拉27/罗拉6，应取「劳拉」。"""
    report = _report([_divergent("ローラ", [("劳拉", 37), ("萝拉", 27), ("罗拉", 6)])])
    plan = build_glossary_updates(report)

    assert len(plan.updates) == 1
    update = plan.updates[0]
    assert update.original == "ローラ"
    assert update.translation == "劳拉"
    assert update.reason == "most_frequent"
    assert update.winning_count == 37
    assert set(update.alternatives) == {"萝拉", "罗拉"}


def test_divergent_records_alternatives_as_aliases():
    """落选译法应记为 aliases，方便后续识别旧译名。"""
    report = _report([_divergent("まっちょ", [("阿肌", 5), ("小真", 2)])])
    plan = build_glossary_updates(report)
    terms = plan.to_terms()

    entry = terms["Person"][0]
    assert entry["original"] == "まっちょ"
    assert entry["translation"] == "阿肌"
    assert entry["aliases"] == ["小真"]
    assert entry["source"] == "consistency_fix"


def test_divergent_with_tie_keeps_first_seen_order():
    """次数相同时保持扫描器给的顺序（通常先出现者），避免随机结果。"""
    report = _report([_divergent("テスト", [("甲", 3), ("乙", 3)])])
    plan = build_glossary_updates(report)
    assert plan.updates[0].translation == "甲"


# ---------- 证据不足时不自动写入 ----------


def test_low_occurrence_divergence_goes_to_review():
    """只出现一两次的术语，证据太薄，不该自动覆盖术语表。"""
    report = _report([_divergent("稀", [("甲", 1), ("乙", 1)])])
    plan = build_glossary_updates(report)

    assert not plan.updates
    assert len(plan.needs_review) == 1
    assert "证据不足" in plan.needs_review[0]["reason"]


def test_min_occurrences_is_configurable():
    report = _report([_divergent("测试", [("甲", 2), ("乙", 1)])])
    assert build_glossary_updates(report, min_occurrences=10).updates == []
    assert len(build_glossary_updates(report, min_occurrences=2).updates) == 1


# ---------- missing / deviating 只提示 ----------


def test_missing_goes_to_review_not_updates():
    """missing 无法判断是术语表错还是译文对，只提示人工确认。"""
    report = _report(
        [
            {
                "original": "日の下町",
                "category": "Location",
                "verdict": "missing",
                "expected": "日之下町",
                "detail": "原文出现 3 次但未使用术语表译名",
            }
        ]
    )
    plan = build_glossary_updates(report)

    assert not plan.updates
    assert len(plan.needs_review) == 1
    assert plan.needs_review[0]["verdict"] == "missing"
    assert plan.needs_review[0]["expected"] == "日之下町"


def test_empty_report_is_safe():
    plan = build_glossary_updates({})
    assert not plan.has_updates
    assert plan.summary() == "术语一致性检查未发现需要写回的内容"


def test_malformed_issues_are_skipped():
    report = {"issues": [None, "x", {}, {"verdict": "divergent"}]}
    plan = build_glossary_updates(report)
    assert not plan.updates


# ---------- 合并时不覆盖人工条目 ----------


def test_apply_does_not_overwrite_existing_entry_by_default():
    """人工整理的译名优先，不能被统计推断覆盖。"""
    plan = build_glossary_updates(
        _report([_divergent("ローラ", [("劳拉", 10), ("萝拉", 2)])])
    )
    existing = {
        "Person": [{"original": "ローラ", "translation": "萝拉", "source": "manual"}]
    }

    merged = apply_updates_to_terms(plan, existing, overwrite=False)

    assert merged["Person"][0]["translation"] == "萝拉"
    assert merged["Person"][0]["source"] == "manual"


def test_apply_overwrites_when_explicitly_allowed():
    plan = build_glossary_updates(
        _report([_divergent("ローラ", [("劳拉", 10), ("萝拉", 2)])])
    )
    existing = {"Person": [{"original": "ローラ", "translation": "萝拉"}]}

    merged = apply_updates_to_terms(plan, existing, overwrite=True)

    assert merged["Person"][0]["translation"] == "劳拉"
    assert merged["Person"][0]["source"] == "consistency_fix"


def test_apply_adds_new_entry_when_absent():
    plan = build_glossary_updates(
        _report([_divergent("タカボウ", [("孝哥", 53), ("高坊", 55)])])
    )
    merged = apply_updates_to_terms(plan, {})

    assert len(merged["Person"]) == 1
    # 高坊 55 次 > 孝哥 53 次，按最高频应取「高坊」
    assert merged["Person"][0]["translation"] == "高坊"


def test_apply_does_not_mutate_input():
    existing = {"Person": [{"original": "A", "translation": "甲"}]}
    plan = build_glossary_updates(_report([_divergent("B", [("乙", 5), ("丙", 1)])]))
    apply_updates_to_terms(plan, existing)
    assert len(existing["Person"]) == 1


def test_plan_serialises_for_qml():
    plan = build_glossary_updates(
        _report(
            [
                _divergent("ローラ", [("劳拉", 37), ("萝拉", 27), ("罗拉", 6)]),
                {"original": "X", "category": "Item", "verdict": "missing", "detail": "未使用"},
            ]
        )
    )
    payload = plan.to_dict()

    import json

    json.dumps(payload, ensure_ascii=False)  # 必须可序列化
    assert payload["updates"][0]["original"] == "ローラ"
    assert len(payload["needs_review"]) == 1
    assert "可写回 1 条" in payload["summary"]


def test_summary_reports_both_buckets():
    plan = build_glossary_updates(
        _report(
            [
                _divergent("A", [("甲", 5), ("乙", 1)]),
                {"original": "B", "category": "Item", "verdict": "missing"},
            ]
        )
    )
    summary = plan.summary()
    assert "可写回 1 条" in summary
    assert "需人工确认 1 条" in summary


# ---------- 闭环的作用范围 ----------


def test_write_back_fixes_future_translation_not_existing_text():
    """写回术语表只影响下一次翻译，不会改写已完成的文本。

    这是重要的语义边界：用户看到"写回成功"后，重新扫描同一本书
    仍会看到问题——因为旧译文里确实残留着另一种译法。
    新翻译才会通过。
    """
    from translation_consistency import check_term_consistency

    glossary = {
        "Person": [{"original": "まっちょ", "translation": "阿肌"}],
        "Location": [],
        "Org": [],
        "Item": [],
        "Skill": [],
        "Creature": [],
    }

    # 已完成文本里同时存在两种译法
    old_pairs = [("まっちょの話", "阿肌的话"), ("まっちょの話", "小真的话")]
    assert check_term_consistency(old_pairs, glossary).has_issues

    # 按统一译名重新翻译后，检查应当通过
    fresh_pairs = [("まっちょの話", "阿肌的话"), ("まっちょの話", "阿肌的话")]
    assert not check_term_consistency(fresh_pairs, glossary).has_issues
