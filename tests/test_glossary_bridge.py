"""术语表桥接器的纯逻辑单元测试。

为什么补这些测试：
  `glossary_bridge.py`（602 行）此前**没有任何测试导入**，但它是「术语闭环」的
  数据层：用户在界面上编辑的每一格都要经过它转换成 `glossary.json` 的存储结构。
  转换一旦出错，症状是「术语表看起来改了，实际没生效」或「重新打开又变回去」，
  这类问题很难从界面直接定位。

  这里只测不依赖 Qt 实例的纯转换函数——它们承载全部语义，却完全没有覆盖：
  - `_policy_value` / `_policy_label`：策略值↔中文标签的双向映射
  - `_parse_note_source` / `_make_note`：备注与来源的合并/拆分（可逆性）
  - `_aliases_text`：别名列表 ↔ 顿号分隔文本
  - `_make_row`：行结构的规范化与默认值
"""

from __future__ import annotations

import sys
from pathlib import Path

QML_ROOT = Path(__file__).resolve().parents[1] / "experimental" / "qml_v4"
if str(QML_ROOT) not in sys.path:
    sys.path.insert(0, str(QML_ROOT))

from backend.glossary_bridge import GlossaryModel


# --- 策略映射 -------------------------------------------------------------


def test_policy_value_accepts_english_and_chinese_aliases():
    """策略列接受多种写法，必须归一成三个内部值之一。"""
    for raw in ("force", "forced", "强制", "强制使用", " FORCE "):
        assert GlossaryModel._policy_value(raw) == "force", raw
    for raw in ("reference", "ref", "weak", "参考", "仅供参考"):
        assert GlossaryModel._policy_value(raw) == "reference", raw
    for raw in ("ignore", "ignored", "忽略", "忽略校对"):
        assert GlossaryModel._policy_value(raw) == "ignore", raw


def test_policy_value_rejects_unknown_as_empty():
    """无法识别时归为空串（默认策略），不能猜测成某个强制值。"""
    for raw in ("", None, "随便", "banana"):
        assert GlossaryModel._policy_value(raw) == "", raw


def test_policy_label_round_trips():
    """标签展示必须与内部值一致，且默认值不能误显示成某个策略。"""
    assert GlossaryModel._policy_label("force") == "强制使用"
    assert GlossaryModel._policy_label("reference") == "仅供参考"
    assert GlossaryModel._policy_label("ignore") == "忽略校对"
    assert GlossaryModel._policy_label("") == "默认策略"
    # 标签函数自身也要能吃中文别名
    assert GlossaryModel._policy_label("强制") == "强制使用"


# --- 备注与来源 -----------------------------------------------------------


def test_make_note_joins_info_and_source_label():
    assert GlossaryModel._make_note("第3章出现", "auto") == "第3章出现；模型提取"
    assert GlossaryModel._make_note("", "manual") == "手动添加"
    assert GlossaryModel._make_note("", "") == "未知来源"


def test_parse_note_source_splits_info_and_source():
    info, source = GlossaryModel._parse_note_source("第3章出现；模型提取")
    assert info == "第3章出现"
    assert source == "auto"


def test_note_round_trip_preserves_info_for_each_source():
    """写入再读回必须仍得到同一来源，且 info 不被吞掉。

    回归点：界面上编辑备注后，来源列会跟着变。若这里的解析不对称，
    用户改一次备注就会莫名其妙丢掉「模型提取 / 手动添加」标记。
    """
    for source in ("auto", "manual", ""):
        info = "角色名，第12话登场"
        note = GlossaryModel._make_note(info, source)
        parsed_info, parsed_source = GlossaryModel._parse_note_source(note)
        assert parsed_source == source, (source, note, parsed_source)
        assert parsed_info == info, (source, note, parsed_info)


def test_parse_note_source_handles_explicit_source_markers():
    """两种显式来源写法都要能识别。"""
    assert GlossaryModel._parse_note_source("说明;source=custom")[1] == "custom"
    assert GlossaryModel._parse_note_source("说明；来源：deepseek")[1] == "deepseek"


def test_parse_note_source_accepts_fullwidth_and_halfwidth_separators():
    """中文输入法常打出全角分号，不能只认半角。"""
    for sep in (";", "；"):
        info, source = GlossaryModel._parse_note_source(f"备注{sep}手动添加")
        assert info == "备注", (sep, info)
        assert source == "manual", (sep, source)


def test_parse_note_source_ignores_empty_parts():
    assert GlossaryModel._parse_note_source("") == ("", "")
    assert GlossaryModel._parse_note_source(";;；") == ("", "")


# --- 别名 -----------------------------------------------------------------


def test_aliases_text_joins_with_enumeration_comma():
    """别名在界面上用顿号分隔展示。"""
    assert GlossaryModel._aliases_text(["阿辽", "小辽"]) == "阿辽、小辽"


def test_aliases_text_accepts_string_and_empty():
    """输入可能是字符串、None 或空列表，都不能抛异常。"""
    assert GlossaryModel._aliases_text(None) == ""
    assert GlossaryModel._aliases_text([]) == ""
    assert isinstance(GlossaryModel._aliases_text("阿辽"), str)


# --- 行结构 ---------------------------------------------------------------


def test_make_row_normalizes_defaults():
    row = GlossaryModel._make_row("", "原文", "译文")
    assert row["category"] == "Item", "空分类应回落为 Item，否则界面上是空白格"
    assert row["original"] == "原文"
    assert row["translation"] == "译文"
    assert row["policy"] == ""
    assert row["aliases"] == ""
    assert row["note"] == "未知来源"


def test_make_row_normalizes_policy_and_aliases():
    row = GlossaryModel._make_row("Person", "アリア", "艾莉亚", policy="强制", aliases=["阿莉亚"])
    assert row["policy"] == "force"
    assert row["aliases"] == "阿莉亚"


def test_make_row_keeps_all_expected_keys():
    """行结构是界面与存储的契约，键缺失会导致 QML 端某列变空。"""
    row = GlossaryModel._make_row("Item", "a", "b")
    assert set(row) == {
        "category", "original", "translation", "info", "source", "policy", "aliases", "note",
    }


def test_source_label_marks_known_sources():
    assert GlossaryModel._source_label("auto") == "模型提取"
    assert GlossaryModel._source_label("preextract") == "模型提取"
    assert GlossaryModel._source_label("manual") == "手动添加"
    assert GlossaryModel._source_label("") == "未知来源"
    # 未知来源名称要保留原文，便于排查
    assert "deepseek" in GlossaryModel._source_label("deepseek")
