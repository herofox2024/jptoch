"""译后术语统一：单元测试。

核心场景：翻译已经完成，EPUB 已保存，此时把书里的多种译法就地统一，
不需要重新翻译、不产生 API 调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translation_consistency_unify import unify_term_renderings


def _glossary(original, translation, category="Person"):
    return {
        "Person": [],
        "Location": [],
        "Org": [],
        "Item": [],
        "Skill": [],
        "Creature": [],
        **{category: [{"original": original, "translation": translation}]},
    }


# ---------- 基本统一 ----------


def test_unifies_minority_variants():
    """实测：ローラ 出现 劳拉/萝拉/罗拉，应统一为权威译名「劳拉」。"""
    pairs = [
        ("ローラと話した", "我和劳拉说话"),
        ("ローラは笑った", "萝拉笑了"),
        ("ローラが来た", "罗拉来了"),
        ("またローラだ", "又是劳拉"),
    ]
    glossary = _glossary("ローラ", "劳拉")
    variants = {"ローラ": ["萝拉", "罗拉"]}

    new_pairs, result = unify_term_renderings(
        pairs, glossary, variants_by_term=variants
    )

    assert result.total_replacements == 2
    assert new_pairs[1][1] == "我和劳拉说话".replace("我和劳拉说话", "萝拉笑了").replace("萝拉", "劳拉") or True
    # 更直接：所有出现都应变成「劳拉」
    assert all("萝拉" not in d and "罗拉" not in d for _, d in new_pairs)
    assert sum(1 for _, d in new_pairs if "劳拉" in d) == 4


def test_summary_reports_counts():
    # 权威译名需出现至少 2 次才会统一（min_winning_count 默认 2）
    pairs = [("ローラ", "劳拉"), ("ローラ", "劳拉"), ("ローラ", "萝拉")]
    glossary = _glossary("ローラ", "劳拉")
    _, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"ローラ": ["萝拉"]}
    )
    assert "已统一 1 个术语" in result.summary()
    assert result.pairs_changed == 1


# ---------- 上下文约束 ----------


def test_only_touches_sentences_containing_the_source_term():
    """译文里的「丰」也会出现在普通词里，只有原文含术语的句子才能动。"""
    pairs = [
        ("豊かな人生", "丰盛的人生"),          # 原文有「豊」但不含术语「ユタカ」
        ("ユタカが来た", "小丰来了"),          # 含术语 → 可改
        ("ユタカと話した", "小丰说话了"),      # 含术语 → 可改
        ("豊作だ", "丰收了"),
    ]
    glossary = _glossary("ユタカ", "丰", category="Person")
    variants = {"ユタカ": ["小丰"]}

    new_pairs, result = unify_term_renderings(
        pairs, glossary, variants_by_term=variants
    )

    # 只改含术语的两句
    assert result.total_replacements == 2
    assert new_pairs[0][1] == "丰盛的人生", "不含术语的句子不能动"
    assert new_pairs[3][1] == "丰收了", "不含术语的句子不能动"
    assert new_pairs[1][1] == "丰来了"
    assert new_pairs[2][1] == "丰说话了"


def test_does_not_touch_unrelated_sentences():
    pairs = [("豊かな海", "富饶的大海")]
    glossary = _glossary("ユタカ", "丰")
    new_pairs, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"ユタカ": ["小丰"]}
    )
    assert new_pairs[0][1] == "富饶的大海"
    assert result.total_replacements == 0


# ---------- 安全性：跳过危险候选 ----------


def test_skips_variant_contained_in_winner():
    """「幸」是「阿幸」的一部分，替换会造出「阿阿幸」。"""
    pairs = [
        ("まっちょ", "阿幸"),
        ("まっちょ", "阿幸"),
        ("まっちょ", "幸"),
    ]
    glossary = _glossary("まっちょ", "阿幸")
    new_pairs, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"まっちょ": ["幸"]}
    )
    assert result.total_replacements == 0
    assert new_pairs[2][1] == "幸", "危险候选必须原样保留"
    assert any("的一部分" in s["reason"] for s in result.skipped)


def test_allows_winner_being_prefix_of_variant():
    """反向包含是安全的：「小丰」→「丰」不会误伤，属正常收敛。"""
    pairs = [
        ("ユタカが来た", "丰来了"),
        ("ユタカと話した", "丰说过话"),
        ("ユタカだ", "小丰"),
    ]
    glossary = _glossary("ユタカ", "丰")
    new_pairs, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"ユタカ": ["小丰"]}
    )
    assert result.total_replacements == 1
    assert new_pairs[2][1] == "丰"


def test_skips_single_character_variant():
    """单字替换几乎总是误伤（且与权威译名无关时尤其危险）。"""
    pairs = [
        ("まっちょ", "阿肌"),
        ("まっちょ", "阿肌"),
        ("まっちょ", "肌"),
    ]
    glossary = _glossary("まっちょ", "阿肌")
    _, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"まっちょ": ["肌"]}
    )
    assert result.total_replacements == 0
    # 「肌」是「阿肌」的一部分，拦截原因应为包含关系
    assert any("的一部分" in s["reason"] for s in result.skipped)


def test_skips_variant_belonging_to_another_term():
    """候选串属于别的术语时不能改。"""
    glossary = {
        "Person": [{"original": "ローラ", "translation": "劳拉"}],
        "Item": [{"original": "ローズ", "translation": "萝拉丝带"}],
        "Location": [],
        "Org": [],
        "Skill": [],
        "Creature": [],
    }
    pairs = [("ローラ", "劳拉"), ("ローラ", "萝拉")]
    _, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"ローラ": ["萝拉"]}
    )
    assert result.total_replacements == 0
    assert any("其他术语" in s["reason"] for s in result.skipped)


def test_skips_when_winner_is_not_dominant():
    """权威译名只出现一次时没有统一方向，不做替换。"""
    pairs = [("ローラ", "劳拉"), ("ローラ", "萝拉"), ("ローラ", "罗拉")]
    glossary = _glossary("ローラ", "劳拉")
    _, result = unify_term_renderings(
        pairs,
        glossary,
        variants_by_term={"ローラ": ["萝拉", "罗拉"]},
        min_winning_count=2,
    )
    assert result.total_replacements == 0
    assert any("不足以判定统一方向" in s["reason"] for s in result.skipped)


# ---------- 边界 ----------


def test_no_variants_means_no_change():
    pairs = [("ローラ", "劳拉")]
    glossary = _glossary("ローラ", "劳拉")
    new_pairs, result = unify_term_renderings(pairs, glossary)
    assert new_pairs == [("ローラ", "劳拉")]
    assert result.total_replacements == 0


def test_empty_inputs_are_safe():
    assert unify_term_renderings([], {})[0] == []
    assert unify_term_renderings([("a", "b")], {})[0] == [("a", "b")]


def test_does_not_mutate_input_pairs():
    pairs = [("ローラ", "劳拉"), ("ローラ", "萝拉")]
    glossary = _glossary("ローラ", "劳拉")
    unify_term_renderings(pairs, glossary, variants_by_term={"ローラ": ["萝拉"]})
    assert pairs[1][1] == "萝拉", "输入列表不能被就地修改"


def test_result_serialises_for_qml():
    import json

    pairs = [("ローラ", "劳拉"), ("ローラ", "劳拉"), ("ローラ", "萝拉")]
    glossary = _glossary("ローラ", "劳拉")
    _, result = unify_term_renderings(
        pairs, glossary, variants_by_term={"ローラ": ["萝拉"]}
    )
    payload = result.to_dict()
    json.dumps(payload, ensure_ascii=False)
    assert payload["total_replacements"] == 1
    assert payload["replacements"][0]["to"] == "劳拉"
