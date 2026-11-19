"""Tests for cross-chapter glossary consistency checks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translation_consistency import (
    check_term_consistency,
    collect_variant_suspects,
)


def _glossary(**kwargs):
    base = {"Person": [], "Location": [], "Org": [], "Item": [], "Skill": [], "Creature": []}
    for key, value in kwargs.items():
        base[key] = value
    return base


def test_variant_extraction_does_not_glue_verbs():
    """变体提取不能把动词粘进译名。

    回归点：早期用「预期译名长度 + 2」做上限，2 字的「劳拉」允许到 4 字，
    于是「萝拉笑了」被提取成「萝拉笑」，后续替换把原句改成「劳拉了」——
    丢掉了动词。现在按权威译名长度精确截断。
    """
    glossary = _glossary(Person=[{"original": "ローラ", "translation": "劳拉"}])
    pairs = [
        ("ローラは笑った。", "萝拉笑了。"),
        ("ローラが来た。", "劳拉来了。"),
        ("ローラと話した。", "我和劳拉说过话。"),
        ("またローラだ。", "又是劳拉。"),
    ]

    report = check_term_consistency(pairs, glossary)
    assert report.divergent_count == 1

    issue = report.issues[0]
    rendered = {v.translation for v in issue.variants}
    assert "萝拉" in rendered, f"应提取出干净的「萝拉」，实际: {rendered}"
    # 关键：不能出现「萝拉笑」这种带动词的脏数据
    assert not any(v.startswith("萝拉") and len(v) > 2 for v in rendered), rendered


def test_unify_preserves_surrounding_words():
    """统一译名时不能吞掉译名后面的文字。"""
    from translation_consistency_unify import unify_term_renderings

    glossary = _glossary(Person=[{"original": "ローラ", "translation": "劳拉"}])
    pairs = [
        ("ローラは笑った。", "萝拉笑了。"),
        ("ローラが来た。", "劳拉来了。"),
        ("またローラだ。", "又是劳拉。"),
    ]

    new_pairs, _ = unify_term_renderings(
        pairs, glossary, variants_by_term={"ローラ": ["萝拉"]}
    )
    assert new_pairs[0][1] == "劳拉笑了。", "「笑了」必须保留"


def test_detects_multiple_renderings_of_same_term():
    """同一术语出现多种译法是本书的核心缺陷，必须能被检出。"""
    glossary = _glossary(Person=[{"original": "まっちょ", "translation": "阿肌"}])
    pairs = [
        ("まっちょ、もう一つくらいハンバーガー食べるでしょ？", "阿肌，你还要再吃一个汉堡吧？"),
        ("でもまっちょの話、さっきからまとまりがなくて", "可阿肌你说的话，从刚才起就乱七八糟的"),
        # 这里模型换成了「小真」——正是实测中出现的错法
        ("まっちょはどこのガンプラマニアに告白されたのよ？", "小真是被哪里的高达模型迷告白的？"),
    ]

    report = check_term_consistency(pairs, glossary)
    assert report.scanned_pairs == 3
    assert report.divergent_count == 1, report.summary()

    issue = report.issues[0]
    assert issue.original == "まっちょ"
    assert issue.verdict == "divergent"
    # 期望译法与另一种译法都应被列出
    rendered = {v.translation for v in issue.variants}
    assert "阿肌" in rendered


def test_reports_missing_when_glossary_translation_unused():
    """术语表译名完全没被使用时，应报 missing 而不是静默通过。

    注意：单次出现不足以判定（术语表混有其他书的条目），
    因此这里模拟真实情况——该术语在书中反复出现却始终没采用术语表译名。
    """
    glossary = _glossary(Location=[{"original": "日の下町", "translation": "日之下町"}])
    pairs = [
        ("この日の下町で、おそらくはいくつもの恋模様が展開されたんだ", "在这座小镇里，恐怕上演了好几段恋情。"),
        ("日の下町の警察が特殊な計画を立ち上げた", "小镇的警察提出了一项特殊计划。"),
        ("俺たちは日の下町で出会った", "我们是在小镇相遇的。"),
    ]

    report = check_term_consistency(pairs, glossary)
    assert report.missing_count == 1
    issue = report.issues[0]
    assert issue.verdict == "missing"
    assert issue.expected == "日之下町"


def test_consistent_book_passes_cleanly():
    """所有译名一致时不应产生任何问题。"""
    glossary = _glossary(Person=[{"original": "翔子", "translation": "翔子"}])
    pairs = [
        ("翔子はゆっくりと顔を上げた", "翔子缓缓抬起头"),
        ("俺は翔子の目を見つめた", "我凝视着翔子的眼睛"),
    ]

    report = check_term_consistency(pairs, glossary)
    assert not report.has_issues, report.summary()
    assert report.scanned_pairs == 2


def test_free_rendering_policy_is_not_flagged():
    """标注为「仅供参考/上下文命中」的术语允许按语境处理，不应报错。"""
    glossary = _glossary(
        Item=[{"original": "チロリ", "translation": "烫酒壶", "policy": "context"}]
    )
    pairs = [
        ("チロリの酒を飲んだ", "喝了那壶酒"),
        ("チロリを持ってきた", "把烧酒壶拿了过来"),
    ]

    report = check_term_consistency(pairs, glossary)
    assert not report.has_issues, report.summary()


def test_chapter_labels_are_recorded():
    """应记录问题出现在哪些章节，便于人工复核。"""
    glossary = _glossary(Person=[{"original": "まっちょ", "translation": "阿肌"}])
    pairs = [
        ("まっちょの話", "阿肌的话"),
        ("まっちょの話", "小真的话"),
    ]
    chapters = ["第一话", "第三话"]

    report = check_term_consistency(pairs, glossary, chapter_of=chapters)
    assert report.divergent_count == 1
    issue = report.issues[0]
    all_chapters = [c for v in issue.variants for c in v.chapters]
    assert "第一话" in all_chapters or "第三话" in all_chapters


def test_short_terms_are_skipped():
    """单字符术语会大量误报，应跳过。"""
    glossary = _glossary(Item=[{"original": "酒", "translation": "酒"}])
    pairs = [("酒を飲む", "喝酒")]
    report = check_term_consistency(pairs, glossary)
    assert not report.has_issues


def test_empty_inputs_are_safe():
    assert not check_term_consistency([], {}).has_issues
    assert not check_term_consistency([("原文", "译文")], {}).has_issues
    assert not check_term_consistency([], _glossary()).has_issues


def test_report_serialises_for_qml():
    """报告要能转成 QVariantMap 交给界面展示。"""
    glossary = _glossary(Person=[{"original": "まっちょ", "translation": "阿肌"}])
    pairs = [
        ("まっちょの話", "阿肌的话"),
        ("まっちょの話", "小真的话"),
    ]
    payload = check_term_consistency(pairs, glossary).to_dict()

    assert payload["scanned_pairs"] == 2
    assert payload["scanned_terms"] == 1
    assert isinstance(payload["summary"], str)
    assert payload["counts"]["divergent"] == 1
    assert payload["issues"][0]["original"] == "まっちょ"
    # 必须可 JSON 序列化（QML 桥接的前提）
    import json

    json.dumps(payload, ensure_ascii=False)


def test_collect_variant_suspects_returns_only_divergent():
    glossary = _glossary(
        Person=[{"original": "まっちょ", "translation": "阿肌"}],
        Location=[{"original": "日の下町", "translation": "日之下町"}],
    )
    pairs = [
        ("まっちょの話", "阿肌的话"),
        ("まっちょの話", "小真的话"),
        ("日の下町で", "在小镇里"),
    ]
    suspects = collect_variant_suspects(pairs, glossary)
    assert len(suspects) == 1
    assert suspects[0]["original"] == "まっちょ"
    assert suspects[0]["verdict"] == "divergent"


def test_categories_filter_limits_scope():
    glossary = _glossary(
        Person=[{"original": "まっちょ", "translation": "阿肌"}],
        Location=[{"original": "日の下町", "translation": "日之下町"}],
    )
    pairs = [
        ("まっちょの話", "阿肌的话"),
        ("まっちょの話", "小真的话"),
        ("日の下町で", "在小镇里"),
        ("日の下町の警察", "小镇的警察"),
        ("日の下町を歩く", "走在小镇上"),
    ]
    report = check_term_consistency(pairs, glossary, categories=["Location"])
    # 只扫描 Location，Person 的「阿肌/小真」不一致不应出现
    assert report.divergent_count == 0
    assert report.missing_count == 1
