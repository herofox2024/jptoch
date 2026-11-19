"""术语提取规则的回归测试。

改造依据（《黄金色的祈祷》实测）：
  原文 282 次的「コーちゃん」、201 次的「教子」、74 次的「ローラ」全部漏收，
  而只出现 1 次的动漫作品名被提取。根因是旧规则的三个缺陷：
    1. 「移除敬称后缀」让模型以为昵称不是专名
    2. 「每批最多 5 条」让高频昵称挤不进返回
    3. 举例全是汉字词，模型因此忽略假名人名
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXTRACTION_TEMPLATE = (
    ROOT / "dict" / "glossary_extraction_prompt.yaml"
).read_text(encoding="utf-8")

STYLE_TEMPLATE = (ROOT / "dict" / "system_prompt_hq_format.yaml").read_text(encoding="utf-8")


# ---------- 假名昵称必须提取 ----------


def test_extraction_requires_kana_nicknames():
    """片假名昵称是旧版最大的漏收来源，规则必须明确点名。"""
    assert "片假名昵称必须提取" in EXTRACTION_TEMPLATE
    # 用实测漏收的具体词作为例子，模型更容易理解
    for example in ("コーちゃん", "タカボウ", "ユタカ"):
        assert example in EXTRACTION_TEMPLATE, f"应包含实测漏收例子「{example}」"


def test_extraction_requires_foreign_names():
    """片假名外来语人名同样不能因为像外来语就跳过。"""
    assert "片假名外来语人名必须提取" in EXTRACTION_TEMPLATE
    assert "ローラ" in EXTRACTION_TEMPLATE


def test_extraction_requires_hiragana_nicknames():
    """平假名谐音昵称（如「まっちょ」）也要提取。"""
    assert "平假名昵称" in EXTRACTION_TEMPLATE
    assert "まっちょ" in EXTRACTION_TEMPLATE


# ---------- 昵称与敬称的区分 ----------


def test_extraction_keeps_nickname_with_suffix():
    """旧规则「移除敬称后缀」被误解成删掉整个昵称，新规则要澄清。"""
    assert "带后缀的整体昵称要提取" in EXTRACTION_TEMPLATE

    # 旧表述不能出现在「规则正文」里。
    # 文件顶部的注释会记录这个历史缺陷，所以要跳过注释行再判断。
    body = "\n".join(
        line for line in EXTRACTION_TEMPLATE.splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "移除敬称后缀" not in body, "规则正文不应再有会被误读的「移除敬称后缀」"


def test_extraction_requires_name_linked_translation():
    """昵称译法要与本名用字呼应，不是音译。"""
    assert "本名用字" in EXTRACTION_TEMPLATE
    assert "孝哥" in EXTRACTION_TEMPLATE
    # 明确反对音译
    assert "不要音译成" in EXTRACTION_TEMPLATE or "不要音译" in EXTRACTION_TEMPLATE


# ---------- 数量上限 ----------


def test_extraction_batch_limit_raised():
    """5 条上限会让高频昵称挤不进来，必须放宽到 12。"""
    assert "12 条" in EXTRACTION_TEMPLATE
    assert "每批最多返回 5 条" not in EXTRACTION_TEMPLATE


def test_extraction_prioritises_frequency():
    """判断标准应是「会不会被反复提到」，而非「看起来像不像人名」。"""
    assert "会不会被反复提到" in EXTRACTION_TEMPLATE
    assert "优先返回高频词" in EXTRACTION_TEMPLATE


# ---------- 不该提取的边界 ----------


def test_extraction_still_excludes_common_words():
    """放宽昵称不等于什么都收，普通词仍要排除。"""
    assert "普通名词" in EXTRACTION_TEMPLATE
    assert "学校" in EXTRACTION_TEMPLATE
    assert "猫" in EXTRACTION_TEMPLATE


# ---------- 各处副本必须同步 ----------


def test_style_template_extraction_rules_updated():
    """翻译时随批抽取用的规则同样要更新。"""
    assert "每批最多返回 12 条" in STYLE_TEMPLATE
    assert "每批最多返回 5 条" not in STYLE_TEMPLATE
    assert "昵称" in STYLE_TEMPLATE


def test_builtin_template_stays_in_sync():
    """打包 exe 时用的是内嵌模板，必须与 dict/ 下的文件一致。"""
    from translator import _BUILTIN_TEMPLATES

    builtin = _BUILTIN_TEMPLATES["glossary_extraction_prompt.yaml"]
    for phrase in (
        "片假名昵称必须提取",
        "带后缀的整体昵称要提取",
        "本名用字",
        "12 条",
    ):
        assert phrase in builtin, f"内嵌模板缺少「{phrase}」"

    # 旧的错误表述不能残留
    assert "移除敬称后缀" not in builtin
    assert "每批最多返回 5 条" not in builtin


def test_builtin_style_template_updated():
    from translator import _BUILTIN_TEMPLATES

    builtin = _BUILTIN_TEMPLATES["system_prompt_hq_format.yaml"]
    assert "每批最多返回 12 条" in builtin
    assert "每批最多返回 5 条" not in builtin


# ---------- 提示词能正确组装 ----------


def test_extraction_prompt_resolves_placeholders():
    """占位符要被替换掉，不能把 {{{ }}} 原样发给模型。"""
    import translator as tr

    t = tr.JaZhTranslator.__new__(tr.JaZhTranslator)
    t._extraction_prompt_data = None
    t.glossary_extraction_mode = "novel"
    prompt = t._build_glossary_extraction_system_prompt()

    assert "{{{target_lang}}}" not in prompt
    assert "简体中文" in prompt
    # 模式说明也要带上昵称要求
    assert "昵称" in prompt


def test_lite_mode_mentions_kana_nicknames():
    """精简模式也不能把假名昵称当噪声排掉。"""
    import translator as tr

    t = tr.JaZhTranslator.__new__(tr.JaZhTranslator)
    t._extraction_prompt_data = None
    t.glossary_extraction_mode = "lite"
    prompt = t._build_glossary_extraction_system_prompt(extraction_mode="lite")

    assert "片假名昵称" in prompt
    assert "コーちゃん" in prompt


def test_assembled_prompt_contains_key_rules():
    """检查最终发给模型的提示词，而不只是模板文件。

    实测教训：模板写对了不代表生效——真正决定输出的是组装后的字符串。
    """
    import translator as tr

    data = tr.load_prompt_template(ROOT / "dict", "glossary_extraction_prompt")
    t = tr.JaZhTranslator.__new__(tr.JaZhTranslator)
    t._extraction_prompt_data = data
    t.glossary_extraction_mode = "novel"
    prompt = t._build_glossary_extraction_system_prompt()

    # 模板里的占位符必须已被替换
    assert "{{{" not in prompt, "占位符未被替换"

    required = [
        "片假名昵称必须提取",
        "片假名外来语人名必须提取",
        "带后缀的整体昵称要提取",
        "本名用字",
        "12 条",
    ]
    missing = [r for r in required if r not in prompt]
    assert not missing, f"实际提示词缺少规则: {missing}"

