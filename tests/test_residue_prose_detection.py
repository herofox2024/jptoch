"""日文残留检测：成句日文 vs 零散假名的区分。

背景（真实缺陷）：
  《一千零一夜馆杀人事件》有一处标题漏译，
  译文保存后仍是「数理情報工学の権威、久珠場俊隆博士死去」。

  这条文本只有一个假名（「の」），旧逻辑据此判定为「弱残留」直接放行。
  但整句其实都是日文——问题的关键不是假名数量，而是：
  1. 假名夹在汉字之间（「学の権」），是日文语法结构
  2. 句子里含日文特有汉字（権、場），中文译文不该出现

  修复后要同时满足：
  - 真实漏译必须被拦（blocking=True）
  - 中文里混入个别日文词仍放行（如「小さ」），不能一刀切
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translation_quality import (
    classify_japanese_residue,
    has_blocking_japanese_residue,
    has_kana_free_japanese_residue,
    has_weak_japanese_residue,
    mark_authorized_japanese,
)

# 实际漏译的两处（正文标题、目录条目）
REAL_LEAKS = [
    "数理情報工学の権威、久珠場俊隆博士死去",
    "久珠场俊隆学の権威、久珠場俊隆博士死去",
]


def test_real_untranslated_title_is_blocking():
    """真实漏译必须被判定为阻塞，不能当弱残留放行。

    回归点：这条标题曾完整保存进成书，读者直接看到日文。
    """
    for text in REAL_LEAKS:
        assert has_blocking_japanese_residue(text), f"应拦截：{text}"
        assert not has_weak_japanese_residue(text), f"不应视为弱残留：{text}"


def test_real_leak_classified_as_low_or_higher():
    """分类结果至少要 low，balanced 策略下会阻塞保存。"""
    for text in REAL_LEAKS:
        result = classify_japanese_residue(text)
        assert result["risk"] in {"low", "medium", "high"}, (
            f"风险等级过低：{text} → {result['risk']}"
        )
        assert result["blocking"] is True


def test_correct_translation_passes():
    """正确译文不应有任何残留告警。"""
    text = "数理信息工程学权威、久珠场俊隆博士去世"
    assert not has_blocking_japanese_residue(text)
    assert not has_weak_japanese_residue(text)
    assert classify_japanese_residue(text)["risk"] == "none"


def test_chinese_with_one_foreign_term_still_allowed():
    """中文句子里混一个日文词（「小さ」）不能一刀切拦截。

    回归点：加严判定后曾把这条误判为 low 而阻塞保存，打坏了既有测试。
    这里只断言「不阻塞」——具体归类会随 allowlist 内容变化，
    但「不该挡住用户保存」这个行为必须稳定。
    """
    text = "这句话里有一处小さ假名。"
    assert not has_blocking_japanese_residue(text), "不应拦截轻微噪音"
    assert classify_japanese_residue(text)["blocking"] is False


def test_short_stray_kana_is_not_blocking():
    """短句里的偶发假名仍按弱残留处理。"""
    assert not has_blocking_japanese_residue("这是の测试")


def test_pure_kana_sentence_is_blocking():
    """整句假名是明确未翻译。"""
    assert has_blocking_japanese_residue("ありがとう")
    assert not has_weak_japanese_residue("ありがとう")


def test_japanese_kanji_plus_kana_between_kanji_is_the_signal():
    """判定依赖两个信号同时成立：日文特有汉字 + 假名夹汉字。

    去掉任一条件都不该判为成句日文：
    - 只有日文汉字、无夹击假名 → 可能是专有名词
    - 只有夹击假名、无日文汉字 → 可能是中文里混的日文词
    """
    # 两个信号都满足
    assert has_blocking_japanese_residue("学術の権威")
    # 只有夹击假名，无日文特有汉字
    assert not has_blocking_japanese_residue("这是の测试")


def test_kana_free_japanese_is_not_silently_passed():
    """零假名的日文短句不能被判成「无残留」。

    回归点：原判定的入口是 `JAPANESE_KANA_RE.search()`，没有假名就直接返回
    「no_japanese_residue」。于是纯汉字日文既不进分类器、也不进残留下报告，
    整条质检链路对它完全失明。

    真实故障（《一千零一夜馆杀人事件》成书）：目录与正文里的
    「久珠場俊隆博士死去」保存后仍是日文，读者直接看到。
    """
    assert has_kana_free_japanese_residue("日々是好日")
    assert has_kana_free_japanese_residue("久珠場俊隆博士死去。日々是好日")

    result = classify_japanese_residue("日々是好日")
    assert result["reason"] == "kana_free_japanese_residue", result
    assert result["blocking"] is True
    # 记为 low：进报告让用户看见，但 balanced 策略下不硬拦正常译稿。
    # 实测唯一误报是「佐々木」这类日文专有名词，若记 medium 会打断正常保存。
    assert result["risk"] == "low"
    assert has_blocking_japanese_residue("日々是好日")


def test_kana_free_detection_does_not_touch_normal_chinese():
    """收窄判定的回归保护：普通中文不得被新规则命中。

    这里只锁「々」是刻意的：`JAPANESE_SPECIFIC_KANJI` 里混着大量繁体中文标准字
    （學/實/會/報…），实测台繁译本每本 5～15 行纯汉字会被它命中；
    若改成按「日文特有汉字」判定就会大面积误伤繁体书。故仅用「々」这一强信号。
    """
    for text in (
        "今天是个好日子",
        "数理信息工程学权威、久珠场俊隆博士去世",
        "那句话写得很好",
    ):
        assert not has_kana_free_japanese_residue(text), text
        assert not has_blocking_japanese_residue(text), text
        assert classify_japanese_residue(text)["risk"] == "none", text


def test_kana_free_residue_can_be_allowlisted():
    """新规则必须能被既有的「授权日文标记」放行，否则会卡住正当引用。"""
    marked = mark_authorized_japanese("日々是好日")
    assert not has_blocking_japanese_residue(marked)
    assert classify_japanese_residue(marked)["blocking"] is False
