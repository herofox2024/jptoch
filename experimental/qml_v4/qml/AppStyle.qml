pragma Singleton
import QtQuick

QtObject {
    // Shared visual tokens. Colors stay in AppPalette; sizing, typography and
    // state backgrounds live here so page files do not repeat the same values.

    readonly property int pagePadding: 24
    readonly property int pageGap: 16
    readonly property int sectionGap: 18
    readonly property int cardPadding: 18
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

    readonly property color statusNeutralBg: AppPalette.cardAlt
    readonly property color statusAccentBg: AppPalette.accentSoft
    readonly property color statusWarningBg: AppPalette.dark ? "#3b2d1c" : "#f2e4cf"
    readonly property color statusErrorBg: AppPalette.dark ? "#3a2420" : "#f6ded9"
    readonly property color statusSuccessBg: AppPalette.glass
                                             ? Qt.rgba(0.30, 0.72, 0.48, 0.18)
                                             : (AppPalette.dark ? "#203f2a" : "#dcefdc")

    readonly property color dangerButtonBg: Qt.rgba(0.80, 0.24, 0.20, AppPalette.glass ? 0.18 : 0.10)
    readonly property color primaryOnAccent: "#ffffff"
    readonly property color primaryOnAccentMuted: Qt.rgba(1, 1, 1, 0.82)
}
