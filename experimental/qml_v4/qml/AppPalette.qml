pragma Singleton
import QtQuick

/* ============================================================
   AppPalette — 全局主题调色板

   所有颜色和样式值统一从这里读取。
   主题切换通过 main.qml 中的 themeMode/darkMode Binding 驱动，
   AppPalette 的属性随 themeMode/darkMode 变化自动响应。

   添加新主题：在下面的三元表达式中新增条件分支即可。
   ============================================================ */

QtObject {
    // 主题元信息（由 main.qml 的 Binding 更新）
    property string themeMode: "light"
    property bool darkMode: false
    readonly property bool glass: themeMode === "glass"
    readonly property bool dark: themeMode === "dark" || (darkMode && !glass)

    // 背景
    readonly property color background: glass ? "#eef8fb" : (dark ? "#101614" : "#f8f9fa")
    readonly property color backgroundAlt: glass ? "#f6ecde" : (dark ? "#17211f" : "#f3f5f8")

    // 导航栏
    readonly property color navBg: glass ? Qt.rgba(0.05, 0.20, 0.23, 0.76) : (dark ? "#0e201d" : "#ffffff")
    readonly property color navBgAlt: glass ? Qt.rgba(0.09, 0.42, 0.38, 0.66) : (dark ? "#17302b" : "#ffffff")
    readonly property color navActiveBg: glass ? Qt.rgba(1, 1, 1, 0.78) : (dark ? "#25463f" : "#eef0ff")

    // 表面 / 卡片
    readonly property color surface: glass ? Qt.rgba(1, 1, 1, 0.56) : (dark ? "#17211f" : "#ffffff")
    readonly property color surfaceRaised: glass ? Qt.rgba(1, 1, 1, 0.68) : (dark ? "#1d2a27" : "#ffffff")
    readonly property color cardBg: glass ? Qt.rgba(1, 1, 1, 0.54) : (dark ? "#1a2522" : "#ffffff")
    readonly property color cardAlt: glass ? Qt.rgba(0.90, 0.96, 0.94, 0.46) : (dark ? "#202f2b" : "#f5f7fa")
    readonly property color fieldBg: glass ? Qt.rgba(1, 1, 1, 0.42) : (dark ? "#111a18" : "#fbfcfe")

    // 文字
    readonly property color textColor: glass ? "#153331" : (dark ? "#f5efe4" : "#182230")
    readonly property color mutedText: glass ? "#5e7470" : (dark ? "#b6c4bc" : "#718096")
    readonly property color hintColor: mutedText

    // 边框 / 分割线
    readonly property color borderColor: glass ? Qt.rgba(1, 1, 1, 0.62) : (dark ? "#31443f" : "#e3e8ef")
    readonly property color lineColor: glass ? Qt.rgba(0.36, 0.52, 0.50, 0.30) : (dark ? "#263833" : "#e9edf2")

    // 强调色
    readonly property color accentColor: glass ? "#0d6e72" : (dark ? "#8fd3c4" : "#635bff")
    readonly property color accentSoft: glass ? Qt.rgba(0.69, 0.90, 0.88, 0.56) : (dark ? "#203f3a" : "#eef0ff")
    readonly property color amberColor: glass ? "#d1882f" : (dark ? "#e0ad68" : "#c98118")
    readonly property color successColor: glass ? "#238c59" : (dark ? "#86d391" : "#2f8a46")
    readonly property color errorColor: glass ? "#c94a3f" : (dark ? "#ff8a80" : "#c83c32")

    // 玻璃效果专用
    readonly property color glassHighlight: Qt.rgba(1, 1, 1, glass ? 0.72 : 0.0)
    readonly property color glassShadow: glass ? Qt.rgba(0.08, 0.18, 0.20, 0.16) : Qt.rgba(0, 0, 0, 0)
    readonly property color glassGlowCyan: Qt.rgba(0.39, 0.84, 0.86, glass ? 0.34 : 0.0)
    readonly property color glassGlowAmber: Qt.rgba(0.95, 0.62, 0.24, glass ? 0.25 : 0.0)

    // 圆角
    readonly property int radiusLarge: glass ? 24 : 8
    readonly property int radiusMedium: glass ? 16 : 8
    readonly property int radiusSmall: glass ? 10 : 6
}
