pragma Singleton
import QtQuick

QtObject {
    // Shared visual tokens. Colors stay in AppPalette; sizing, typography and
    // state backgrounds live here so page files do not repeat the same values.

    readonly property int pagePadding: 22
    readonly property int pageGap: 16
    readonly property int sectionGap: 18
    readonly property int cardPadding: 16
    readonly property int panelPadding: 14
    readonly property int fieldPadding: 14

    readonly property int spacingNone: 0
    readonly property int spacingTight: 2
    readonly property int spacingNarrow: 3
    readonly property int spacingXSmall: 4
    readonly property int spacingChip: 5
    readonly property int spacingInline: 6
    readonly property int spacingCompact: 7
    readonly property int spacingSmall: 8
    readonly property int spacingMedium: 10
    readonly property int spacingLarge: 12
    readonly property int spacingXLarge: 14
    readonly property int spacingXXLarge: 16
    readonly property int spacingHuge: 20

    readonly property int fontTiny: 10
    readonly property int fontCaption: 11
    readonly property int fontSmall: 12
    readonly property int fontBody: 13
    readonly property int fontBodyLarge: 14
    readonly property int fontBodyXLarge: 15
    readonly property int fontSubSection: 16
    readonly property int fontSection: 17
    readonly property int fontSubHeader: 18
    readonly property int fontHeader: 19
    readonly property int fontPageTitle: 28
    readonly property int fontHero: 46
    readonly property int fontMetric: 20

    readonly property int buttonHeightCompact: 28
    readonly property int buttonHeightSmall: 34
    readonly property int buttonHeightNormal: 40
    readonly property int buttonHeightPrimary: 64
    readonly property int fieldHeight: 50
    readonly property int statusPillHeight: 34
    readonly property int infoBarHeight: 44
    readonly property int navButtonHeight: 58

    // 圆角 token —— 全项目唯一来源。
    // 之前 AppPalette 里还有一套 radiusLarge/Medium/Small，两套并存导致
    // 同一个卡片在不同页面出现 8/12/14/16/22 混用。现在统一为 7 档语义值，
    // 外观类圆角一律引用这里的 token；只有“圆点/胶囊”这类几何值（= 尺寸一半）
    // 才允许写表达式，不再写裸数字。
    readonly property int radiusTiny: 4        // 进度条、细分隔条
    readonly property int radiusSmall: 6       // 小标签、日志条
    readonly property int radiusChip: 8        // 标签、状态胶囊、小图标块
    readonly property int radiusButton: 10     // 普通按钮、输入框
    readonly property int radiusField: 10      // 输入框、下拉框
    readonly property int radiusCard: 14       // 卡片、面板
    readonly property int radiusDialog: 18     // 弹窗、抽屉、页签底槽
    readonly property int radiusPill: 999      // 完全圆角

    // 兼容别名：历史代码大量使用 AppPalette.radiusLarge/Medium/Small，
    // 保留同名 token 会继续造成两套体系，因此全部指向上面这一套。
    readonly property int radiusLarge: radiusCard
    readonly property int radiusMedium: radiusButton
    readonly property int radiusSmallToken: radiusSmall

    // 边框 token
    readonly property int borderWidthHairline: 1
    readonly property int borderWidthEmphasis: 2
    readonly property color borderSubtle: AppPalette.lineColor

    // 响应式布局断点（视口/窗口宽度，px）
    readonly property int bpCompact: 680      // 紧凑：操作按钮 2 列
    readonly property int bpNarrow: 880       // 窄屏：隐藏次要状态
    readonly property int bpSmall: 900        // 小屏：列表单行 / 布局收窄
    readonly property int bpMedium: 920       // 中屏：统计卡片 2 列
    readonly property int bpWide: 980         // 宽屏：双栏 / 按钮 5 列
    readonly property int bpLogVisible: 1360   // 侧边实时日志可见

    // 当前窗口宽度，由 main.qml 的 Binding 写入，供全局按视口宽度做取舍。
    property real viewportWidth: 1420

    // 卡片阴影开关。
    // 开启离屏图层（layer.enabled）加 MultiEffect 会让该子树先渲染到离屏缓冲
    // 再合成，每个带阴影的卡片都是一次额外 FBO 往返；状态页 12 张统计卡尤其明显。
    // 深色主题下阴影几乎不可见，窄窗口下用户更在意流畅度，因此都关闭。
    readonly property bool shadowsEnabled: !AppPalette.dark && viewportWidth >= bpWide

    readonly property color statusNeutralBg: AppPalette.cardAlt
    readonly property color statusAccentBg: AppPalette.accentSoft
    // 状态底色采用 Apple 系统色的低透明度填充（浅色 / 深色分别取色）。
    readonly property color statusWarningBg: AppPalette.glass
                                             ? Qt.rgba(1.0, 0.58, 0.0, 0.16)
                                             : (AppPalette.dark ? Qt.rgba(1.0, 0.62, 0.04, 0.20)
                                                                : Qt.rgba(1.0, 0.58, 0.0, 0.12))
    readonly property color statusErrorBg: AppPalette.glass
                                           ? Qt.rgba(1.0, 0.23, 0.19, 0.14)
                                           : (AppPalette.dark ? Qt.rgba(1.0, 0.27, 0.23, 0.20)
                                                              : Qt.rgba(1.0, 0.23, 0.19, 0.10))
    readonly property color statusSuccessBg: AppPalette.glass
                                             ? Qt.rgba(0.20, 0.78, 0.35, 0.16)
                                             : (AppPalette.dark ? Qt.rgba(0.19, 0.82, 0.35, 0.20)
                                                                : Qt.rgba(0.20, 0.78, 0.35, 0.12))

    readonly property color dangerButtonBg: Qt.rgba(1.0, 0.23, 0.19, AppPalette.glass ? 0.18 : 0.10)
    // 主按钮文字色。品牌青绿在浅色下足够深（#297f84 配白字 4.71:1），
    // 深色主题的青绿更亮（#3aa0a5），白字只有 3.11:1，必须改用深色文字（5.41:1）。
    readonly property color primaryOnAccent: AppPalette.dark ? "#08211f" : "#ffffff"
    // 主按钮副标题：浅色主题用 90% 白（4.85:1）；深色主题用 78% 深墨（约 4.5:1）。
    readonly property color primaryOnAccentMuted: AppPalette.dark
        ? Qt.rgba(0.03, 0.13, 0.12, 0.78)
        : Qt.rgba(1, 1, 1, 0.90)
}
