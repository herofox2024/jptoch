"""提示词质量规则与标点归一化的回归测试。

这些规则全部来自真实译本的对照实测（《黄金色的祈祷》两版对比），
不是泛泛的风格偏好，因此每条都要能追溯到具体证据。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from translation_quality import (
    mark_authorized_japanese,
    normalize_chinese_punctuation,
    postprocess_translation,
)

TEMPLATE = (ROOT / "dict" / "system_prompt_hq_format.yaml").read_text(encoding="utf-8")


# ---------- 规则 1：少用书面连接词 ----------


def test_rules_forbid_formal_connectives():
    """实测：我方「然而」27 次 vs 对照本 3 次，是"翻译腔"的主要来源。"""
    for corpus in (TEMPLATE,):
        assert "然而" in corpus and "因此" in corpus
        assert "书面连接词" in corpus, "规则应明确点出「书面连接词」这个类别"
        # 必须给出替代方案，否则模型不知道该怎么写
        assert "所以" in corpus and "就是" in corpus


# ---------- 规则 2：放开语气词 ----------


def test_rules_encourage_modal_particles():
    """实测：对照本「嘛」83 次 vs 我方 33 次，语气词是对话的生命力。"""
    assert "放开语气词" in TEMPLATE
    # 必须列出常用语气词，模型才知道要保留
    for particle in ("嘛", "呀", "呢", "吧"):
        assert particle in TEMPLATE, f"规则应包含语气词「{particle}」"
    # 必须说明这些词不该被回避，否则模型会继续写得干巴巴
    assert "不要刻意回避" in TEMPLATE or "生命力" in TEMPLATE


# ---------- 规则 3：昵称按本名取字 ----------


def test_rules_require_nickname_from_real_name():
    """实测：「タカボウ」来自「孝義」，译「孝哥」优于音译「高坊」。"""
    assert "昵称" in TEMPLATE
    assert "本名" in TEMPLATE, "规则应要求回溯本名用字"
    assert "音译" in TEMPLATE, "规则应明确排除音译做法"
    # 具体例子能让模型理解意图
    assert "孝哥" in TEMPLATE


# ---------- 规则 4：引号统一 ----------


def test_rules_require_chinese_quotes():
    assert "「」" in TEMPLATE and "“”" in TEMPLATE
    assert "引号" in TEMPLATE


def test_prompt_template_and_fallback_stay_in_sync():
    """模板与代码里的兜底常量必须一致，否则启用模板时规则会丢失。"""
    from translator import DEFAULT_BATCH_QUALITY_RULES

    for phrase in (
        "少用书面连接词",
        "放开语气词",
        "昵称按本名取字",
        "引号统一用中文双引号",
    ):
        assert phrase in TEMPLATE, f"模板缺少规则：{phrase}"
        assert phrase in DEFAULT_BATCH_QUALITY_RULES, f"兜底常量缺少规则：{phrase}"

    # 此前已生效的规则不能被覆盖掉
    for phrase in ("只用现代汉语，避免文言残留", "不堆砌四字成语"):
        assert phrase in TEMPLATE
        assert phrase in DEFAULT_BATCH_QUALITY_RULES


# ---------- 标点归一化（规则 4 的代码兜底） ----------


def test_normalize_converts_japanese_corner_quotes():
    assert normalize_chinese_punctuation("「你好」他说") == "“你好”他说"


def test_normalize_converts_double_corner_quotes():
    assert normalize_chinese_punctuation("『双重』引号") == "“双重”引号"


def test_normalize_leaves_valid_chinese_quotes_untouched():
    text = "正常“中文”引号"
    assert normalize_chinese_punctuation(text) == text


def test_normalize_preserves_authorized_japanese_span():
    """授权保留的日文引文本身不能被改坏，但外层引号要转。"""
    inner = mark_authorized_japanese("テスト")
    result = normalize_chinese_punctuation(f"原文「{inner}」中间")
    assert "[[ja:テスト]]" in result, "授权片段必须原样保留"
    assert "“" in result and "「" not in result


def test_normalize_handles_empty_and_plain_text():
    assert normalize_chinese_punctuation("") == ""
    assert normalize_chinese_punctuation("没有引号的句子") == "没有引号的句子"


def test_postprocess_applies_punctuation_normalization():
    """标点修复必须挂在后处理链上，否则模型输出会直接落盘。"""
    result = postprocess_translation("テスト", "「そうか」と言った")
    assert "「" not in result
    assert "”" in result


def test_postprocess_keeps_normal_text_unchanged():
    text = "他说：“走吧。”"
    assert postprocess_translation("テスト", text) == text
