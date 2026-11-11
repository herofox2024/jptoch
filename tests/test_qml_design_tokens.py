"""设计令牌（配色 / 阴影 / 圆角 / 文案 / 配置）回归测试。

覆盖第二批：
1. 小字号文字必须满足 WCAG AA（4.5:1）——旧的 #86868b / #ff9500 / #34c759
   只有 2.2~3.6:1，而 fontTiny/fontCaption(10~11px) 大量使用它们。
2. 阴影必须按主题/视口宽度条件开启，不能无条件 layer.enabled。
3. 任务页状态必须只有一个权威来源，不再出现三个语义重复的胶囊。
4. 顶栏不得重复展示版本号。
5. FileDialog 必须记住上次目录。

覆盖第三批：
6. 圆角只能来自 AppStyle 一套 token，不得再出现裸数字外观圆角。
7. 品牌色必须取自 logo（青绿），不得回退成 iOS 蓝。
8. 结构性文案必须从 Strings 单例取，不得散落在页面里硬编码。
9. 配置写入必须原子化（tmp + os.replace），避免截断配置。
10. 窗口几何必须持久化，且还原时做屏幕边界校验。

运行：
    python -m pytest tests/test_qml_design_tokens.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QML_DIR = PROJECT_ROOT / "experimental" / "qml_v4" / "qml"

# WCAG 2.1 AA：普通字号正文 4.5:1
AA_NORMAL = 4.5


def _srgb_to_linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_to_linear(c / 255.0) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    high, low = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def _palette_source() -> str:
    return (QML_DIR / "AppPalette.qml").read_text(encoding="utf-8")


def _palette_colors() -> dict[str, dict[str, str]]:
    """从 AppPalette.qml 解析出 {属性名: {light/dark/glass: 颜色}}。"""
    source = _palette_source()
    result: dict[str, dict[str, str]] = {}
    # 形如：readonly property color mutedText: glass \\n ? "#5f5f63" : (dark ? "#98989d" : "#66666b")
    pattern = re.compile(
        r"property color (\w+):(.*?)(?=\n\s*(?:readonly )?property |\n\s*//|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(source):
        name, body = match.group(1), match.group(2)
        colors = re.findall(r'"#[0-9a-fA-F]{6}"', body)
        colors = [c.strip('"') for c in colors]
        if len(colors) == 3:
            # glass ? A : (dark ? B : C)
            result[name] = {"glass": colors[0], "dark": colors[1], "light": colors[2]}
        elif len(colors) == 2:
            # dark ? A : B
            result[name] = {"dark": colors[0], "light": colors[1], "glass": colors[0]}
    return result


PALETTE = _palette_colors()
WHITE = (255, 255, 255)
CARD_LIGHT = hex_to_rgb("#ffffff")
PAGE_LIGHT = hex_to_rgb("#f2f2f7")
DARK_BG = hex_to_rgb("#1c1c1e")
DARK_CARD = hex_to_rgb("#2c2c2e")
GLASS_BG = hex_to_rgb("#e8ecf2")


def test_palette_parsed_expected_tokens():
    """保证解析器本身没退化，否则下面的对比度断言会静默失效。"""
    for token in ("mutedText", "accentColor", "amberColor", "successColor", "errorColor",
                  "accentText", "amberText", "successText", "errorText"):
        assert token in PALETTE, f"AppPalette 缺少 {token}"
        assert len(PALETTE[token]) == 3, f"{token} 未解析出三套主题取值"


def test_text_tokens_meet_wcag_aa_in_light_theme():
    """浅色主题下，正文/标签用的文字色必须达到 4.5:1。"""
    failures = []
    for token in ("mutedText", "accentText", "amberText", "successText", "errorText"):
        color = PALETTE[token]["light"]
        for bg_name, bg in (("卡片白", CARD_LIGHT), ("页面底", PAGE_LIGHT)):
            ratio = contrast(hex_to_rgb(color), bg)
            if ratio < AA_NORMAL:
                failures.append(f"{token}={color} on {bg_name} -> {ratio:.2f}:1")
    assert not failures, "浅色主题对比度不达标：\n" + "\n".join(failures)


def test_text_tokens_meet_wcag_aa_in_dark_theme():
    failures = []
    for token in ("mutedText", "accentText", "amberText", "successText", "errorText"):
        color = PALETTE[token]["dark"]
        for bg_name, bg in (("页面底", DARK_BG), ("卡片", DARK_CARD)):
            ratio = contrast(hex_to_rgb(color), bg)
            if ratio < AA_NORMAL:
                failures.append(f"{token}={color} on {bg_name} -> {ratio:.2f}:1")
    assert not failures, "深色主题对比度不达标：\n" + "\n".join(failures)


def test_text_tokens_meet_wcag_aa_in_glass_theme():
    failures = []
    for token in ("mutedText", "accentText", "amberText", "successText", "errorText"):
        color = PALETTE[token]["glass"]
        ratio = contrast(hex_to_rgb(color), GLASS_BG)
        if ratio < AA_NORMAL:
            failures.append(f"{token}={color} -> {ratio:.2f}:1")
    assert not failures, "glass 主题对比度不达标：\n" + "\n".join(failures)


def test_primary_button_text_is_readable():
    """主按钮上的文字必须可读（>=4.5:1），文字色随主题取白或深墨。"""
    style = (QML_DIR / "AppStyle.qml").read_text(encoding="utf-8")
    # primaryOnAccent 在深色主题改用深墨色（青绿底配白字只有 3.11:1）
    assert 'AppPalette.dark ? "#08211f" : "#ffffff"' in style, (
        "primaryOnAccent 必须随主题切换：深色主题的青绿底要配深色文字"
    )

    on_accent = {"light": hex_to_rgb("#ffffff"), "glass": hex_to_rgb("#ffffff"),
                 "dark": hex_to_rgb("#08211f")}
    for theme in ("light", "dark"):
        fill = PALETTE["accentColor"][theme]
        ratio = contrast(on_accent[theme], hex_to_rgb(fill))
        assert ratio >= AA_NORMAL, (
            f"{theme} 主题主按钮文字对比度仅 {ratio:.2f}:1（底色 {fill}）"
        )


def test_no_small_text_uses_vivid_status_colors():
    """鲜艳状态色只能用于图标/描边/填充块，不能直接当文字颜色。

    回归点：fontTiny(10px)/fontCaption(11px) 的 Label 曾直接用
    amberColor(#ff9500)=2.2:1、successColor(#34c759)=2.2:1。
    """
    vivid = ("amberColor", "successColor", "errorColor", "accentColor")
    offenders = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        stack: list[tuple[int, str]] = []
        for lineno, line in enumerate(lines, 1):
            if not line.strip():
                continue
            indent = len(line) - len(line.lstrip())
            while stack and stack[-1][0] >= indent:
                stack.pop()
            opening = re.match(r"\s*([A-Z][A-Za-z0-9_.]*)\s*\{", line)
            if opening:
                stack.append((indent, opening.group(1)))
                continue
            color_line = re.match(r"\s*color:\s*(.+)", line)
            if color_line and stack and stack[-1][1] in {"Label", "Text"}:
                for token in vivid:
                    if f"AppPalette.{token}" in color_line.group(1):
                        offenders.append(
                            f"{path.relative_to(QML_DIR)}:{lineno} 用了 AppPalette.{token}"
                        )
    assert not offenders, (
        "以下文本颜色使用了鲜艳状态色（对比度不足，应改用 *Text 变体）：\n"
        + "\n".join(offenders)
    )


def test_shadows_are_conditional_not_always_on():
    """阴影必须受 AppStyle.shadowsEnabled 控制，不能无条件 layer.enabled。"""
    unconditional = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        text = path.read_text(encoding="utf-8")
        if "layer.enabled: true" in text:
            unconditional.append(str(path.relative_to(QML_DIR)))
    assert not unconditional, (
        "以下文件仍在无条件开启离屏图层（应改为 AppStyle.shadowsEnabled）：\n"
        + "\n".join(unconditional)
    )

    style = (QML_DIR / "AppStyle.qml").read_text(encoding="utf-8")
    assert "shadowsEnabled" in style, "AppStyle 缺少 shadowsEnabled 开关"
    assert "viewportWidth" in style, "AppStyle 缺少 viewportWidth，无法按窗口宽度降级"


def test_workbench_state_has_single_source_of_truth():
    """任务页只能有一个状态胶囊来源，不再出现三个重复指示器。"""
    panel = (QML_DIR / "components" / "TaskControlPanel.qml").read_text(encoding="utf-8")
    page = (QML_DIR / "pages" / "TaskPage.qml").read_text(encoding="utf-8")

    assert "workbenchState" in panel, "TaskControlPanel 缺少统一状态派生"
    for label in ("翻译运行中", "等待任务"):
        # 这些文案只应出现在派生逻辑里，不应再散落在页面标题区
        if label == "等待任务":
            assert label not in page, f"TaskPage 仍在重复展示状态文案：{label}"

    # 底栏不应再有独立的第三个胶囊矩形（原来用 buttonHeightCompact + radius 14）
    info_bar = panel.split("root.stateDot", 1)[1] if "root.stateDot" in panel else ""
    assert "Layout.preferredHeight: AppStyle.buttonHeightCompact" not in info_bar, (
        "底栏仍在渲染第三个状态胶囊"
    )


def test_top_bar_does_not_repeat_version():
    """顶栏左侧只显示产品名，版本号只在「关于」入口出现一次。"""
    top_bar = (QML_DIR / "components" / "AppTopBar.qml").read_text(encoding="utf-8")
    assert "productName" in top_bar, "AppTopBar 缺少 productName"
    assert "text: root.appTitle" not in top_bar, "顶栏左侧仍展示含版本号的 appTitle"

    main = (QML_DIR / "main.qml").read_text(encoding="utf-8")
    assert "productName:" in main, "main.qml 未把不含版本号的产品名传给顶栏"


def test_file_dialogs_remember_last_directory():
    page = (QML_DIR / "pages" / "TaskPage.qml").read_text(encoding="utf-8")
    assert "rememberedFolder(" in page, "FileDialog 未使用上次目录"
    assert "rememberFolderFromFile(" in page, "选择文件后未记录目录"
    assert page.count("currentFolder:") >= 2, "输入/输出对话框都应设置 currentFolder"
    assert 'defaultSuffix: "epub"' in page, "保存对话框应设置 defaultSuffix"

    utils = (QML_DIR / "FilePathUtils.qml").read_text(encoding="utf-8")
    assert "function directoryOf" in utils
    assert "function toFolderUrl" in utils


def test_schema_knows_new_directory_keys():
    """新增的配置键必须同时出现在持久化白名单与校验 schema 中，否则会被静默丢弃。"""
    import sys

    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(PROJECT_ROOT / "experimental" / "qml_v4") not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT / "experimental" / "qml_v4"))

    from backend.config_schema import CONFIG_DEFAULTS, LONG_TEXT_LIMITS, validate_config

    for key in ("last_input_dir", "last_output_dir"):
        assert key in CONFIG_DEFAULTS, f"config_schema 缺少 {key}"
        assert key in LONG_TEXT_LIMITS, f"{key} 缺少长度上限"

    result = validate_config({"last_input_dir": "E:/books", "last_output_dir": "E:/out"})
    assert result.values["last_input_dir"] == "E:/books"
    assert result.values["last_output_dir"] == "E:/out"
    assert not result.issues, [f"{i.key}: {i.message}" for i in result.issues]


# ---------------------------------------------------------------- 第三批


def _import_backend():
    import sys

    for path in (str(PROJECT_ROOT), str(PROJECT_ROOT / "experimental" / "qml_v4")):
        if path not in sys.path:
            sys.path.insert(0, path)


# 允许保留裸数字的“几何圆角”：圆形装饰与圆点（半径 = 尺寸一半）。
# main.qml 的背景光斑是纯装饰圆，其 radius 等于宽高的一半，不属于外观 token。
_GEOMETRY_RADIUS_FILES = {"main.qml"}


def test_radii_come_from_single_token_source():
    """外观圆角只能来自 AppStyle 一套 token，不能再出现裸数字。

    回归点：AppStyle 与 AppPalette 曾各有一套圆角定义（其中 AppStyle 的
    5 个 token 引用数为 0），另有 37 处裸数字，导致同类卡片出现 8/12/14/16/22。
    """
    offenders = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        if path.name in _GEOMETRY_RADIUS_FILES:
            continue
        if path.name in {"AppStyle.qml", "AppPalette.qml"}:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"\s*radius:\s*(\d+)\s*$", line)
            if match:
                offenders.append(f"{path.relative_to(QML_DIR)}:{lineno} radius: {match.group(1)}")
    assert not offenders, (
        "以下外观圆角仍是裸数字，应改用 AppStyle.radius* token：\n" + "\n".join(offenders)
    )

    style = (QML_DIR / "AppStyle.qml").read_text(encoding="utf-8")
    for token in ("radiusTiny", "radiusSmall", "radiusChip", "radiusButton",
                  "radiusCard", "radiusDialog", "radiusPill"):
        assert f"property int {token}" in style, f"AppStyle 缺少 {token}"

    # AppPalette 不得再定义第二套圆角值，只能指向 AppStyle
    palette = (QML_DIR / "AppPalette.qml").read_text(encoding="utf-8")
    for legacy in ("radiusLarge", "radiusMedium", "radiusSmall"):
        line = next((l for l in palette.splitlines() if f"property int {legacy}" in l), "")
        assert "AppStyle." in line, f"AppPalette.{legacy} 必须指向 AppStyle，不能自带第二套值"


def test_brand_color_comes_from_logo_teal():
    """主色必须取自 logo 青绿，不得回退成 iOS 系统蓝。"""
    palette = (QML_DIR / "AppPalette.qml").read_text(encoding="utf-8")
    assert "#297f84" in palette.lower(), "accentColor 应使用 logo 青绿 #297f84"

    # 不允许再出现旧蓝色系作为强调色
    for legacy_blue in ("#007aff", "#0a84ff", "#0060df", "#1a73e8"):
        for lineno, line in enumerate(palette.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            assert legacy_blue not in stripped.lower(), (
                f"AppPalette:{lineno} 仍使用旧蓝色 {legacy_blue}"
            )


def test_structural_copy_lives_in_strings_singleton():
    """页面标题、导航项、主按钮文案必须从 Strings 取，不得硬编码。"""
    strings = (QML_DIR / "Strings.qml").read_text(encoding="utf-8")
    for token in ("pageTask", "pageMonitor", "pageLog", "pageApi",
                  "pageGlossary", "pageOptions",
                  "navWorkspace", "navStatus", "navLog", "navApi",
                  "navGlossary", "navSettings",
                  "actionStart", "actionPause", "actionResume", "actionStop"):
        assert token in strings, f"Strings 缺少 {token}"

    # 页面标题不得再硬编码在页面文件里
    hardcoded_titles = ['text: "任务"', 'text: "状态监控"', 'text: "翻译设置"',
                        'text: "API 接口配置"', 'text: "术语表"']
    offenders = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        content = path.read_text(encoding="utf-8")
        for needle in hardcoded_titles:
            if needle in content:
                offenders.append(f"{path.relative_to(QML_DIR)}: {needle}")
    assert not offenders, "以下页面仍硬编码标题：\n" + "\n".join(offenders)

    # 导航文案也不能硬编码
    main = (QML_DIR / "main.qml").read_text(encoding="utf-8")
    for needle in ('label: "工作台"', 'label: "术语表"', 'label: "设置"'):
        assert needle not in main, f"main.qml 导航仍硬编码：{needle}"
    assert main.count("Strings.nav") >= 6, "六个导航项都应使用 Strings.nav*"


def test_config_save_is_atomic():
    """配置写入必须走 tmp + os.replace，避免中途被杀留下截断文件。"""
    source = (PROJECT_ROOT / "experimental" / "qml_v4" / "backend" / "config_bridge.py").read_text(
        encoding="utf-8"
    )
    save_block = source.split("def saveToDisk", 1)[1].split("def _current_config_json", 1)[0]
    assert "os.replace(" in save_block, "saveToDisk 必须用 os.replace 原子替换"
    assert ".tmp" in save_block, "saveToDisk 应先写临时文件"
    assert "path.write_text(" not in save_block, "saveToDisk 不得直接覆盖写入目标文件"


def test_disabled_button_text_stays_readable():
    """禁用态按钮的文字色不能沿用主按钮的白字。

    回归点：TaskActionButton 在禁用时背景切成 `AppPalette.cardAlt`（浅灰），
    但文字色仍取 `primaryOnAccent`（白），导致「开始翻译」在未选文件时几乎不可见。
    """
    button = (QML_DIR / "components" / "TaskActionButton.qml").read_text(encoding="utf-8")
    # 主标签必须对 !enabled 单独分支
    label_block = button.split("text: root.label", 1)[1][:400]
    assert "!root.enabled" in label_block, (
        "主标签缺少 !enabled 分支：禁用时背景变浅灰，白字会不可见"
    )
    assert "AppPalette.mutedText" in label_block, "禁用态文字应使用 mutedText"

    # 禁用背景是浅灰，mutedText 在其上必须达标
    ratio = contrast(hex_to_rgb(PALETTE["mutedText"]["light"]), hex_to_rgb("#f2f2f7"))
    assert ratio >= AA_NORMAL, f"禁用态文字对比度不足：{ratio:.2f}:1"


def test_page_transition_bindings_are_not_broken():
    """页面转场的 x/opacity 绑定不能失效。

    两处真实缺陷（实测导致点导航后页面不切换）：
    1. Loader 同时写 `anchors.fill: parent` 和 `x: pageX(i)`：锚点接管 x，
       QML 会断开与锚点冲突的绑定，转场位移永不生效。
    2. Loader 的 `opacity` 上挂 `Behavior on opacity`：Behavior 在首次赋值时
       接管写入，使 `opacity: currentPageIndex === N ? 1 : 0` 这条绑定失效，
       切页时 opacity 永远停在初始值（页面既不淡入也不淡出）。
    """
    main = (QML_DIR / "main.qml").read_text(encoding="utf-8")

    # 1. 页面 Loader 不得同时用 anchors.fill 与 x:
    loader_blocks = re.findall(
        r"Loader \{(.*?)\n                \}", main, re.DOTALL
    )
    offenders = [
        block for block in loader_blocks
        if "anchors.fill: parent" in block and re.search(r"^\s*x: appWindow\.pageX", block, re.M)
    ]
    assert not offenders, (
        "以下页面 Loader 同时设置了 anchors.fill 与 x，x 绑定会被锚点打断：\n"
        + "\n---\n".join(b.strip()[:200] for b in offenders)
    )

    # 2. opacity 上不得挂 Behavior（只看生效代码，忽略注释行）
    active_behavior = [
        f"{lineno}: {line.strip()}"
        for lineno, line in enumerate(main.splitlines(), 1)
        if "Behavior on opacity" in line and not line.strip().startswith("//")
    ]
    assert not active_behavior, (
        "页面 Loader 的 opacity 不能挂 Behavior：会接管写入并让绑定失效，导致切页不生效\n"
        + "\n".join(active_behavior)
    )

    # 3. 保留每个 Loader 的 opacity 绑定与 x 位移
    for index in range(6):
        assert f"opacity: appWindow.currentPageIndex === {index} ? 1 : 0" in main, (
            f"Loader {index} 缺少 opacity 绑定"
        )


def test_glossary_table_header_aligns_with_rows():
    """术语表表头与行内列必须严格同宽、同列宽。

    回归点：表头是 ColumnLayout 的直接子项（fillWidth，实测宽 920），
    而行内 delegate 用 `width: listView.width`（实测 1012），相差 92px；
    固定列从左排布，差值全压在右侧弹性列上，于是「应用策略」下的
    下拉框比表头右移一大截。

    另有两点会单独造成错位：
      - 行内 RowLayout 用 anchors.fill 会被 delegate 边框内缩；
      - 表头/单元格的 implicitWidth 若被内部文本撑开，列宽分配会变。
    """
    page = (QML_DIR / "pages" / "GlossaryPage.qml").read_text(encoding="utf-8")
    header = (QML_DIR / "components" / "TableHeader.qml").read_text(encoding="utf-8")

    # 表头整体宽度必须与列表内容宽度绑定，而不是只依赖 fillWidth
    header_block = page.split("TableHeader {", 1)[0][-900:]
    assert "Layout.preferredWidth: listView.width" in header_block, (
        "表头容器宽度必须绑定 listView.width，否则与行内 delegate 宽度不一致"
    )

    # 行内 RowLayout 不能用 anchors.fill（会被边框内缩）
    row_block = page.split("delegate: Rectangle", 1)[1][:1200]
    assert "anchors.fill: parent" not in row_block.split("RowLayout", 1)[1][:400], (
        "行内 RowLayout 不能用 anchors.fill：会被 delegate 边框内缩，导致首列起点偏移"
    )

    # 表头与单元格都要归零隐式尺寸
    assert "implicitWidth: 0" in header, "TableHeader 需要把 implicitWidth 归零"
    assert "implicitWidth: 0" in page, "CellEditor / PolicySelector 需要把 implicitWidth 归零"

    # 表头列宽定义与行内列宽必须一一对应
    header_widths = re.findall(r"TableHeader \{.*?w: ([^;]+);", page)
    assert len(header_widths) >= 8, f"表头列定义异常，解析到 {len(header_widths)} 列"
    for token in ("56", "104", "210", "220", "120"):
        assert token in "".join(header_widths), f"表头列宽缺少 {token}"


def test_glossary_header_text_aligns_with_cell_text():
    """表头文字必须与单元格文字左对齐、同内距。

    回归点有两个：
      1. 表头原来是居中排版，而单元格左对齐 + 10px 内距，视觉上完全对不齐。
      2. 更隐蔽的一个：曾用两个 Label（居中版/左对齐版）各写 visible 条件，
         结果**两个都渲染**了——实测同一列出现 x=272 和 x=308 两个 Label。
         正确做法是单个 Label + horizontalAlignment 切换。
    """
    page = (QML_DIR / "pages" / "GlossaryPage.qml").read_text(encoding="utf-8")
    header = (QML_DIR / "components" / "TableHeader.qml").read_text(encoding="utf-8")

    # 只能有一个 Label，用 horizontalAlignment 区分对齐方式
    assert header.count("Label {") == 1, (
        "TableHeader 只能有一个 Label：两个 Label 各写 visible 会同时渲染"
    )
    assert "horizontalAlignment:" in header, "表头应通过 horizontalAlignment 切换对齐方式"
    assert "Text.AlignLeft" in header, "数据列表头必须左对齐"

    # 表头内距必须与 CellEditor 的 leftMargin 相同
    cell_editor = page.split("component CellEditor", 1)[1].split("component PolicySelector", 1)[0]
    cell_padding = re.search(r"anchors\.leftMargin:\s*(\d+)", cell_editor)
    assert cell_padding, "未找到 CellEditor 的 leftMargin"
    header_padding = re.search(r"anchors\.leftMargin:\s*root\.centered \? 0 : (\d+)", header)
    assert header_padding, "未找到表头 leftMargin"
    assert header_padding.group(1) == cell_padding.group(1), (
        f"表头内距 {header_padding.group(1)} 与单元格内距 {cell_padding.group(1)} 不一致，"
        "文字会左右错开"
    )


def test_all_dialogs_are_centered_and_not_wider_than_window():
    """所有 Dialog 必须居中，且最小宽度不能让弹窗超出窗口。

    扫全部 22 个 Dialog 后总结出的三类缺陷：
      1. 有些 Dialog 既没有 anchors.centerIn 也没有 x/y —— Controls 会把它们
         摆在 Overlay 左上角，看起来像“弹窗跑出画面”。
      2. 手写 `x: (maxWidth - width) / 2` 的写法不可靠：maxWidth 只是调用方
         给的可用宽度上限，不等于窗口可视区，居中会偏。
      3. 最小宽度（Math.max 的第一个参数）写死成 720/760/780 时，窄窗口下
         弹窗比窗口还宽，右侧内容被裁到屏幕外。
    """
    problems = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        source = path.read_text(encoding="utf-8")
        if not re.search(r"^\s*Dialog\s*\{", source, re.M):
            continue
        rel = str(path.relative_to(QML_DIR))

        # 只检查顶层 Dialog 的宽度与定位
        if "anchors.centerIn: parent" not in source and not re.search(
            r"^\s{4}x:\s*\S", source, re.M
        ):
            problems.append(f"{rel}: 既没有 anchors.centerIn 也没有 x，会挂在左上角")

        # 手算居中不可靠
        if re.search(r"^\s*x:\s*Math\.round\(\(.*(?:maxWidth|pageWidth)", source, re.M):
            problems.append(f"{rel}: 用 maxWidth 手算 x 居中不可靠")

        # 最小宽度不得过大
        for match in re.finditer(r"width:\s*Math\.max\(\s*(\d+)", source):
            min_width = int(match.group(1))
            if min_width > 640:
                problems.append(
                    f"{rel}: 最小宽度 {min_width} 过大，窄窗口下会超出边界"
                )

    assert not problems, "弹窗布局问题：\n" + "\n".join(problems)


def test_dialog_action_button_lives_outside_scroll_area():
    """弹窗的主操作按钮必须固定在底部，不能放在滚动内容里。

    回归点（关于弹窗）：
      1. 关闭按钮原先在 ScrollView 内的 ColumnLayout 末尾，
         内容一长就会被滚出可视区。
      2. 该 ColumnLayout 用 `root.width - 32` 算宽度，忽略 Dialog 的
         padding(24×2)，算出 588 而可视区只有 572，右边界超出 16px，
         按钮被裁掉（实测「项目与反馈」右边界 922 vs ScrollView 右缘 906）。
      3. 用 DialogButtonBox 包 footer 会接管按钮样式，让 highlighted 失效、
         按钮变浅灰，与“主操作”语义不符。
    """
    about = (QML_DIR / "components" / "AboutDialog.qml").read_text(encoding="utf-8")

    # 1. 主操作在 footer 里
    assert "footer: Item {" in about, "关闭按钮应放在 Dialog 的 footer 中，固定在底部"
    # 只看生效代码，注释里解释“为何不用 DialogButtonBox”是允许的
    active_box = [
        line for line in about.splitlines()
        if "DialogButtonBox" in line and not line.strip().startswith("//")
    ]
    assert not active_box, (
        "不要用 DialogButtonBox 包 footer：它会接管按钮样式，令 highlighted 失效\n"
        + "\n".join(active_box)
    )

    # 2. 滚动内容宽度必须跟随 ScrollView，而不是减一个写死值
    assert "width: Math.max(0, aboutScroll.availableWidth)" in about, (
        "滚动内容宽度必须用 ScrollView.availableWidth，不能写 root.width - 32"
    )
    stale_width = [
        line for line in about.splitlines()
        if "root.width - 32" in line and not line.strip().startswith("//")
    ]
    assert not stale_width, (
        "不能用 root.width - 32 计算内容宽度：会忽略 Dialog padding\n"
        + "\n".join(stale_width)
    )

    # 3. footer 里的按钮要有品牌色
    assert "Material.accent: AppPalette.accentColor" in about, (
        "footer 主按钮需要显式 Material.accent，否则退回 Material 默认色"
    )


def test_dialogs_use_explicit_max_size_props():
    """弹窗尺寸入参必须叫 maxWidth/maxHeight，不得回退成 pageWidth/pageHeight。

    名字带 page 会让人以为它是“窗口宽度”，历史上正是因为按它做布局判断，
    才把放不下的内容判成放得下，导致右侧按钮被裁。改名后语义明确：
    maxWidth 只是调用方给的**可用尺寸上限**，布局判断一律用 dialog.width。
    """
    offenders = []
    for path in sorted(QML_DIR.rglob("*.qml")):
        source = path.read_text(encoding="utf-8")
        for prop in ("pageWidth", "pageHeight"):
            if re.search(rf"\b{prop}\b", source):
                offenders.append(f"{path.relative_to(QML_DIR)}: 仍在使用 {prop}")
    assert not offenders, "弹窗尺寸入参应改名为 maxWidth/maxHeight：\n" + "\n".join(offenders)

    # 使用 maxWidth 做宽度计算的弹窗，必须声明 maxWidth；
    # 同理 maxHeight。只校验“用到了就必须声明”，不强制无用的属性。
    for path in sorted(QML_DIR.rglob("*.qml")):
        source = path.read_text(encoding="utf-8")
        rel = path.relative_to(QML_DIR)
        if re.search(r"\bdialog\.maxWidth\b", source):
            assert "property int maxWidth:" in source, f"{rel} 使用了 maxWidth 但未声明"
        if re.search(r"\bdialog\.maxHeight\b", source):
            assert "property int maxHeight:" in source, f"{rel} 使用了 maxHeight 但未声明"


def test_dialog_buttons_are_not_clipped():
    """弹窗里的主按钮不得被裁切。

    回归点（片假名词表弹窗）：
      1. 布局列数用 `maxWidth`（调用方给的整页宽，约 1240）判断，而不是弹窗
         自身宽度（最宽 920），导致右侧「保存修复词」被挤出可视区。
      2. contentItem 写死 `width: dialog.width`，而 Dialog 带默认 padding，
         实际可视宽度更小，内容右侧继续溢出。
      3. `highlighted` 在脱离 ApplicationWindow 的弹窗里会退回 Material
         默认品红，与品牌色不一致，需要显式补 Material.accent。
    """
    dialog = (QML_DIR / "components" / "KnownKatakanaTermsDialog.qml").read_text(encoding="utf-8")

    # 1. 布局阈值必须基于弹窗自身宽度，不能用 maxWidth 这类上限值
    assert "dialog.maxWidth > 820" not in dialog, (
        "布局列数不能用 maxWidth 判断：它是可用宽度上限，比弹窗宽得多"
    )
    assert "readonly property bool singleRowLayout: dialog.width >=" in dialog, (
        "单行/双行判定必须基于 dialog.width"
    )

    # 2. contentItem 尺寸交给 Dialog 管理，并归零 padding
    assert "implicitWidth: dialog.availableWidth" in dialog, (
        "contentItem 应用 availableWidth，而不是写死 dialog.width"
    )
    for side in ("top", "bottom", "left", "right"):
        assert f"{side}Padding: 0" in dialog, f"Dialog 的 {side}Padding 应归零"

    # 3. 主按钮既要有强调色，又不能退回 Material 默认品红
    assert "Material.accent: AppPalette.accentColor" in dialog, (
        "弹窗内 highlighted 按钮需要显式 Material.accent，否则用默认品红"
    )
    assert "import QtQuick.Controls.Material" in dialog, (
        "使用 Material 附着属性必须 import QtQuick.Controls.Material"
    )


def test_window_geometry_is_persisted_and_validated():
    """窗口几何必须持久化，且还原时校验是否落在可见屏幕内。"""
    main = (QML_DIR / "main.qml").read_text(encoding="utf-8")
    assert "function restoreWindowGeometry" in main
    assert "function saveWindowGeometry" in main
    assert "function windowIsOnScreen" in main, "还原前必须校验窗口是否在屏幕内"
    assert "onWidthChanged" in main and "onHeightChanged" in main

    _import_backend()
    from backend.config_schema import BOOL_KEYS, CONFIG_DEFAULTS, INT_RANGES, validate_config

    for key in ("window_x", "window_y", "window_w", "window_h"):
        assert key in CONFIG_DEFAULTS, f"config_schema 缺少 {key}"
        assert key in INT_RANGES, f"{key} 缺少取值范围"
    assert "window_maximized" in BOOL_KEYS

    # 负坐标（副屏在左侧）必须被接受，不能被夹到 0
    result = validate_config({"window_x": -1_200, "window_y": -300,
                              "window_w": 1400, "window_h": 900,
                              "window_maximized": False})
    assert result.values["window_x"] == -1_200
    assert result.values["window_y"] == -300
    assert result.values["window_w"] == 1400
    assert result.values["window_h"] == 900
    assert not result.issues, [f"{i.key}: {i.message}" for i in result.issues]
