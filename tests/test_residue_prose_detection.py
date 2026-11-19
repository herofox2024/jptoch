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
    has_weak_japanese_residue,
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
