pragma Singleton
import QtQuick

/* ============================================================
   AppPalette — 全局主题调色板（macOS 视觉体系）

   配色取自 macOS Sonoma / iOS 17 系统色板：
     系统蓝 #007AFF（浅色）/ #0A84FF（深色）
     系统绿 #34C759 / #30D158，系统红 #FF3B30 / #FF453A
     系统橙 #FF9500 / #FF9F0A
     分组背景 #F2F2F7，卡片 #FFFFFF，深色卡片 #1C1C1E / #2C2C2E
     次级文字 #86868B，分隔线 rgba(60,60,67,0.29)

   所有颜色和样式值统一从这里读取。
   主题切换通过 main.qml 中的 themeMode/darkMode Binding 驱动，
   AppPalette 的属性随 themeMode/darkMode 变化自动响应。

   三套主题：
     light  常规浅色
     dark   常规深色
     glass  毛玻璃质感（半透明层叠 + 高光描边）
   ============================================================ */

QtObject {
    // 主题元信息（由 main.qml 的 Binding 更新）
    property string themeMode: "light"
    property bool darkMode: false
    readonly property bool glass: themeMode === "glass"
    readonly property bool dark: themeMode === "dark" || (darkMode && !glass)

    // ---- 背景 ----
    // glass 走半透明浅蓝灰，模拟 macOS 侧边栏的 vibrancy 质感。
    readonly property color background: glass
        ? "#e8ecf2"
        : (dark ? "#1c1c1e" : "#f2f2f7")
    readonly property color backgroundAlt: glass
        ? "#eef2f7"
        : (dark ? "#232326" : "#ffffff")

    // ---- 导航栏（macOS 侧边栏：浅色偏灰，深色更深）----
    readonly property color navBg: glass
        ? Qt.rgba(0.96, 0.97, 0.99, 0.62)
        : (dark ? "#232326" : "#f7f7f9")
    readonly property color navBgAlt: glass
        ? Qt.rgba(0.90, 0.93, 0.97, 0.54)
        : (dark ? "#2c2c2e" : "#ececf0")
    // 选中项使用系统蓝的淡色底，与 macOS 侧边栏一致。
    readonly property color navActiveBg: glass
        ? Qt.rgba(0.0, 0.48, 1.0, 0.16)
        : (dark ? Qt.rgba(0.04, 0.52, 1.0, 0.26) : Qt.rgba(0.0, 0.48, 1.0, 0.10))

    // ---- 表面 / 卡片 ----
    readonly property color surface: glass
        ? Qt.rgba(1, 1, 1, 0.62)
        : (dark ? "#1c1c1e" : "#ffffff")
    readonly property color surfaceRaised: glass
        ? Qt.rgba(1, 1, 1, 0.80)
        : (dark ? "#2c2c2e" : "#ffffff")
    readonly property color cardBg: glass
        ? Qt.rgba(1, 1, 1, 0.68)
        : (dark ? "#2c2c2e" : "#ffffff")
    readonly property color cardAlt: glass
        ? Qt.rgba(0.94, 0.96, 0.99, 0.58)
        : (dark ? "#3a3a3c" : "#f2f2f7")
    readonly property color fieldBg: glass
        ? Qt.rgba(1, 1, 1, 0.72)
        : (dark ? "#2c2c2e" : "#ffffff")

    // ---- 文字 ----
    readonly property color textColor: glass
        ? "#1d1d1f"
        : (dark ? "#f5f5f7" : "#1d1d1f")
    // macOS 次级文字：浅色 60% 灰，深色 60% 白
    readonly property color mutedText: glass
        ? "#6e6e73"
        : (dark ? "#98989d" : "#86868b")
    readonly property color hintColor: mutedText

    // ---- 边框 / 分割线（Apple 的 separator 半透明灰）----
    readonly property color borderColor: glass
        ? Qt.rgba(1, 1, 1, 0.72)
        : (dark ? Qt.rgba(0.33, 0.33, 0.35, 0.65) : Qt.rgba(0.24, 0.24, 0.26, 0.12))
    readonly property color lineColor: glass
        ? Qt.rgba(0.36, 0.42, 0.52, 0.24)
        : (dark ? Qt.rgba(0.33, 0.33, 0.35, 0.45) : Qt.rgba(0.24, 0.24, 0.26, 0.09))

    // ---- 强调色（系统蓝）----
    readonly property color accentColor: glass
        ? "#007aff"
        : (dark ? "#0a84ff" : "#007aff")
    readonly property color accentSoft: glass
        ? Qt.rgba(0.0, 0.48, 1.0, 0.16)
        : (dark ? Qt.rgba(0.04, 0.52, 1.0, 0.24) : Qt.rgba(0.0, 0.48, 1.0, 0.10))
    readonly property color amberColor: glass
        ? "#ff9500"
        : (dark ? "#ff9f0a" : "#ff9500")
    readonly property color successColor: glass
        ? "#34c759"
        : (dark ? "#30d158" : "#34c759")
    readonly property color errorColor: glass
        ? "#ff3b30"
        : (dark ? "#ff453a" : "#ff3b30")

    // ---- 品牌渐变（logo / AI 徽章 / 进度条共用）----
    readonly property color brandGradientStart: glass
        ? "#007aff"
        : (dark ? "#0a84ff" : "#007aff")
    readonly property color brandGradientEnd: glass
        ? "#5ac8fa"
        : (dark ? "#64d2ff" : "#5ac8fa")

    // ---- 阴影（Apple 风格：极轻、大扩散）----
    readonly property color shadowColor: dark
        ? Qt.rgba(0, 0, 0, 0.40)
        : Qt.rgba(0, 0, 0, 0.08)
    readonly property color shadowColorGlass: Qt.rgba(0.10, 0.14, 0.20, 0.14)
    // MultiEffect 的 shadowVerticalOffset 是相对 source 高度的比例（0.01 = 1%）
    readonly property real shadowYOffset: 0.015

    // ---- 玻璃效果专用 ----
    readonly property color glassHighlight: Qt.rgba(1, 1, 1, glass ? 0.80 : 0.0)
    readonly property color glassShadow: glass ? Qt.rgba(0.10, 0.14, 0.20, 0.12) : Qt.rgba(0, 0, 0, 0)
    readonly property color glassGlowCyan: Qt.rgba(0.0, 0.48, 1.0, glass ? 0.20 : 0.0)
    readonly property color glassGlowAmber: Qt.rgba(1.0, 0.58, 0.0, glass ? 0.14 : 0.0)

    // ---- 圆角（Apple 体系：面板大圆角、卡片中圆角、小控件紧圆角）----
    readonly property int radiusLarge: glass ? 20 : 16
    readonly property int radiusMedium: glass ? 14 : 12
    readonly property int radiusSmall: glass ? 10 : 8
}
