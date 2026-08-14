import QtQuick
import QtQuick.Controls
    import QtQuick.Controls.Material
    import QtQuick.Layouts
    import "."
    import "pages"
    import "components"

ApplicationWindow {
    id: appWindow
    visible: false
    width: 1420
    height: 860
    minimumWidth: 980
    minimumHeight: 640
    title: "AI日译中（EPUB）V4.1"
    font.family: typeof AppFontSans !== "undefined" ? AppFontSans : "Microsoft YaHei UI"

    readonly property string uiFont: typeof AppFontSans !== "undefined" ? AppFontSans : "Microsoft YaHei UI"
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : uiFont

    // 主题系统：通过 cfg.theme 驱动，Binding 同步到 AppPalette
    readonly property string themeMode: cfg ? cfg.theme : "light"
    readonly property bool glassMode: themeMode === "glass"
    readonly property bool darkMode: themeMode === "dark"

    property var cfg: ConfigBridge
    property var tbridge: TranslateBridge
    property var gbridge: GlossaryBridge
    property var updater: UpdateBridge
    property var logBridge: LogBridge
    property var toast: typeof ToastBridge !== "undefined" ? ToastBridge : null
    property int currentPageIndex: 0
    property bool taskPageLoaded: true
    property bool monitorPageLoaded: false
    property bool logPageLoaded: false
    property bool apiPageLoaded: false
    property bool glossaryPageLoaded: false
    property bool optionsPageLoaded: false
    property bool workspaceLogExpanded: true
    readonly property bool showWorkspaceLog: workspaceLogExpanded && width >= AppStyle.bpLogVisible

    Material.theme: appWindow.darkMode ? Material.Dark : Material.Light
    Material.accent: AppPalette.accentColor
    Material.primary: AppPalette.accentColor

    // 主题同步：将 main.qml 的 themeMode/darkMode 绑定到 AppPalette
    Binding {
        target: AppPalette
        property: "themeMode"
        value: appWindow.themeMode
        restoreMode: Binding.RestoreNone
    }

    Binding {
        target: AppPalette
        property: "darkMode"
        value: appWindow.darkMode
        restoreMode: Binding.RestoreNone
    }

    // 监听主题变化 → 保存到磁盘 + Toast 通知
    Connections {
        target: cfg
        function onThemeChanged() {
            if (typeof ToastBridge !== "undefined" && ToastBridge !== null) {
                var label = typeof ThemeRegistry !== "undefined"
                    ? ThemeRegistry.labelFor(cfg.theme) : cfg.theme
                // 直接 emit 信号，QML Toast 组件通过 Connections 接收
                ToastBridge.showInfo("主题已切换: " + label)
            }
        }
        ignoreUnknownSignals: true
    }

    readonly property color hintColor: AppPalette.mutedText

    function switchPage(index) {
        if (appWindow.currentPageIndex === index) return
        appWindow.markPageLoaded(index)
        appWindow.currentPageIndex = index
        Qt.callLater(appWindow.activateCurrentPage)
    }

    function openRequestLogsPage() {
        appWindow.markPageLoaded(2)
        appWindow.currentPageIndex = 2
        Qt.callLater(function() {
            if (logLoader.item && logLoader.item.openRequestLogs) {
                logLoader.item.openRequestLogs()
            }
        })
    }

    function markPageLoaded(index) {
        if (index === 0) appWindow.taskPageLoaded = true
        else if (index === 1) appWindow.monitorPageLoaded = true
        else if (index === 2) appWindow.logPageLoaded = true
        else if (index === 3) appWindow.apiPageLoaded = true
        else if (index === 4) appWindow.glossaryPageLoaded = true
        else if (index === 5) appWindow.optionsPageLoaded = true
    }

    function activateCurrentPage() {
        if (appWindow.currentPageIndex === 4
                && glossaryLoader.item
                && glossaryLoader.item.ensureLoaded) {
            glossaryLoader.item.ensureLoaded()
        }
    }

    function openManualEditFromMonitor(original, translation) {
        appWindow.markPageLoaded(0)
        appWindow.currentPageIndex = 0
        Qt.callLater(function() {
            if (taskLoader.item && taskLoader.item.openManualEdit) {
                taskLoader.item.openManualEdit(original || "", translation || "")
            }
        })
    }

    background: Rectangle {
        id: bgRoot
        Behavior on color { ColorAnimation { duration: 400; easing.type: Easing.OutCubic } }
        color: AppPalette.background
        Rectangle {
            visible: appWindow.glassMode
            width: 520
            height: 520
            radius: 260
            x: parent.width - width * 0.42
            y: -180
            color: appWindow.glassMode ? AppPalette.glassGlowCyan : AppPalette.accentSoft
            opacity: appWindow.glassMode ? 0.72 : (AppPalette.dark ? 0.24 : 0.55)
        }
        Rectangle {
            visible: appWindow.glassMode
            width: 360
            height: 360
            radius: 180
            x: -150
            y: parent.height - 230
            color: appWindow.glassMode ? AppPalette.glassGlowAmber : AppPalette.amberColor
            opacity: appWindow.glassMode ? 0.62 : (AppPalette.dark ? 0.08 : 0.12)
        }
        Rectangle {
            visible: appWindow.glassMode
            width: 420
            height: 420
            radius: 210
            x: parent.width * 0.46
            y: parent.height * 0.18
            rotation: -18
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.48) }
                GradientStop { position: 1.0; color: Qt.rgba(0.74, 0.91, 0.95, 0.04) }
            }
            opacity: 0.54
        }
    }

    header: Rectangle {
        height: 64
        color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.52) : AppPalette.surface
        border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.72) : AppPalette.lineColor
        border.width: 1

        Rectangle {
            visible: appWindow.glassMode
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 1
            color: Qt.rgba(1, 1, 1, 0.80)
        }

        Rectangle {
            visible: appWindow.glassMode
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: Qt.rgba(0.20, 0.42, 0.43, 0.18)
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            spacing: AppStyle.spacingLarge

            Rectangle {
                Layout.preferredWidth: 36
                Layout.preferredHeight: 36
                radius: 8
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: AppPalette.brandGradientStart }
                    GradientStop { position: 1.0; color: AppPalette.brandGradientEnd }
                }
                border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.48) : "transparent"
                Label {
                    anchors.centerIn: parent
                    text: "译"
                    color: "white"
                    font.family: appWindow.titleFont
                    font.pixelSize: AppStyle.fontSection
                    font.weight: Font.DemiBold
                }
            }

            ColumnLayout {
                spacing: AppStyle.spacingNone
                Label {
                    text: "AI日译中（EPUB）V4.1"
                    color: AppPalette.textColor
                    font.family: appWindow.titleFont
                    font.pixelSize: AppStyle.fontSection
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "桌面翻译工作台"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                }
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                Layout.preferredWidth: 174
                Layout.minimumWidth: 150
                Layout.preferredHeight: 32
                radius: 8
                color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.44) : AppPalette.cardAlt
                border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.62) : AppPalette.borderColor
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 7
                    Rectangle { width: 7; height: 7; radius: 4; color: AppPalette.successColor }
                    Label {
                        Layout.fillWidth: true
                        text: cfg && cfg.model ? cfg.model : "翻译模型"
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontTiny
                        elide: Text.ElideRight
                    }
                    Label { text: "就绪"; color: AppPalette.successColor; font.pixelSize: AppStyle.fontTiny }
                }
            }

            Rectangle {
                Layout.preferredWidth: 32
                Layout.preferredHeight: 32
                radius: 16
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0.0; color: AppPalette.brandGradientStart }
                    GradientStop { position: 1.0; color: AppPalette.brandGradientEnd }
                }
                Label {
                    anchors.centerIn: parent
                    text: "AI"
                    color: "white"
                    font.pixelSize: AppStyle.fontTiny
                    font.weight: Font.Bold
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: AppStyle.spacingNone

        Rectangle {
            Layout.preferredWidth: 184
            Layout.fillHeight: true
            border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.26) : AppPalette.lineColor
            border.width: 1
            color: AppPalette.navBg

            Rectangle {
                visible: appWindow.glassMode
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.15) }
                    GradientStop { position: 0.38; color: Qt.rgba(1, 1, 1, 0.03) }
                    GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.10) }
                }
            }

            Rectangle {
                visible: appWindow.glassMode
                width: 130
                height: 130
                radius: 65
                x: -42
                y: 64
                color: Qt.rgba(1, 1, 1, 0.12)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: AppStyle.spacingLarge

                ColumnLayout {
                    spacing: AppStyle.spacingTight
                    Layout.fillWidth: true
                    Label {
                        text: "WORKSPACE"
                        color: AppPalette.accentColor
                        font.pixelSize: AppStyle.fontSmall
                        font.letterSpacing: 1.2
                        opacity: 0.82
                    }
                    Label {
                        text: "功能导航"
                        color: AppPalette.textColor
                        font.family: appWindow.titleFont
                        font.pixelSize: AppStyle.fontSubHeader
                        font.weight: Font.DemiBold
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: AppPalette.lineColor
                    opacity: 1
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall
                    NavButton {
                        iconName: "task"
                        label: "工作台"
                        desc: "翻译与任务"
                        pageIndex: 0
                        active: pageStack.currentIndex === 0
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "status"
                        label: "状态"
                        desc: "实时进度"
                        pageIndex: 1
                        active: pageStack.currentIndex === 1
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "log"
                        label: "日志"
                        desc: "实时诊断"
                        pageIndex: 2
                        active: pageStack.currentIndex === 2
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "api"
                        label: "API"
                        desc: "模型接口"
                        pageIndex: 3
                        active: pageStack.currentIndex === 3
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "glossary"
                        label: "术语表"
                        desc: "名词统一"
                        pageIndex: 4
                        active: pageStack.currentIndex === 4
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "settings"
                        label: "设置"
                        desc: "性能校对"
                        pageIndex: 5
                        active: pageStack.currentIndex === 5
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 108
                    radius: AppPalette.radiusLarge
                    color: appWindow.glassMode
                           ? Qt.rgba(1, 1, 1, 0.12)
                           : (AppPalette.dark ? Qt.rgba(1, 1, 1, 0.075) : AppPalette.cardBg)
                    border.color: appWindow.glassMode
                                  ? Qt.rgba(1, 1, 1, 0.18)
                                  : (AppPalette.dark ? Qt.rgba(255, 255, 255, 0.10) : AppPalette.borderColor)
                    clip: true

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 3
                        color: AppPalette.accentColor
                        opacity: 0.85
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingCompact

                        Label {
                            Layout.fillWidth: true
                            text: "\u9879\u76ee\u4e0e\u8054\u7cfb"
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontSmall
                            font.weight: Font.DemiBold
                            opacity: 0.92
                        }

                        ContactLink {
                            label: "GitHub"
                            value: "herofox2024/jptoch"
                            targetUrl: "https://github.com/herofox2024/jptoch"
                            glassMode: appWindow.glassMode
                        }

                        ContactLink {
                            label: "Email"
                            value: "42845734@qq.com"
                            targetUrl: "mailto:42845734@qq.com"
                            glassMode: appWindow.glassMode
                        }
                    }
                }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            Item {
                id: pageStack
                anchors.fill: parent
                property int currentIndex: appWindow.currentPageIndex

                Loader {
                    id: taskLoader
                    anchors.fill: parent
                    active: appWindow.taskPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 0
                    opacity: appWindow.currentPageIndex === 0 ? 1 : 0
                    scale: appWindow.currentPageIndex === 0 ? 1.0 : 0.992
                    sourceComponent: TaskPage {
                        cfg: appWindow.cfg
                        tbridge: appWindow.tbridge
                        onNavigateToStatus: appWindow.switchPage(1)
                        onNavigateToLogs: appWindow.openRequestLogsPage()
                        onNavigateToApi: appWindow.switchPage(3)
                        onNavigateToSettings: appWindow.switchPage(5)
                    }
                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: monitorLoader
                    anchors.fill: parent
                    active: appWindow.monitorPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 1
                    opacity: appWindow.currentPageIndex === 1 ? 1 : 0
                    scale: appWindow.currentPageIndex === 1 ? 1.0 : 0.992
                    sourceComponent: MonitorPage {
                        cfg: appWindow.cfg
                        tbridge: appWindow.tbridge
                        onRequestManualEdit: function(original, translation) {
                            appWindow.openManualEditFromMonitor(original, translation)
                        }
                    }
                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: apiLoader
                    anchors.fill: parent
                    active: appWindow.apiPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 3
                    opacity: appWindow.currentPageIndex === 3 ? 1 : 0
                    scale: appWindow.currentPageIndex === 3 ? 1.0 : 0.992
                    sourceComponent: ApiConfigPage {
                        cfg: appWindow.cfg
                    }
                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: logLoader
                    anchors.fill: parent
                    active: appWindow.logPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 2
                    opacity: appWindow.currentPageIndex === 2 ? 1 : 0
                    scale: appWindow.currentPageIndex === 2 ? 1.0 : 0.992
                    sourceComponent: LogPage {
                        logBridge: appWindow.logBridge
                    }
                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: glossaryLoader
                    anchors.fill: parent
                    active: appWindow.glossaryPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 4
                    opacity: appWindow.currentPageIndex === 4 ? 1 : 0
                    scale: appWindow.currentPageIndex === 4 ? 1.0 : 0.992
                    sourceComponent: GlossaryPage {
                        cfg: appWindow.cfg
                        gbridge: appWindow.gbridge
                        tbridge: appWindow.tbridge
                    }
                    onLoaded: appWindow.activateCurrentPage()
                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: optionsLoader
                    anchors.fill: parent
                    active: appWindow.optionsPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 5
                    opacity: appWindow.currentPageIndex === 5 ? 1 : 0
                    scale: appWindow.currentPageIndex === 5 ? 1.0 : 0.992
                    sourceComponent: OptionsPage {
                        cfg: appWindow.cfg
                        tbridge: appWindow.tbridge
                        updater: appWindow.updater
                    }
                    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                }
            }
        }

        WorkspaceLogPanel {
            Layout.preferredWidth: appWindow.showWorkspaceLog ? 286 : 0
            Layout.minimumWidth: appWindow.showWorkspaceLog ? 250 : 0
            Layout.fillHeight: true
            visible: appWindow.showWorkspaceLog
            logBridge: appWindow.logBridge
            onOpenFullLog: appWindow.switchPage(2)
            onCollapseRequested: appWindow.workspaceLogExpanded = false
        }

        ToolButton {
            visible: !appWindow.workspaceLogExpanded && appWindow.width >= AppStyle.bpLogVisible
            Layout.preferredWidth: 36
            Layout.alignment: Qt.AlignTop
            text: ">"
            ToolTip.visible: hovered
            ToolTip.text: "展开实时日志"
            onClicked: appWindow.workspaceLogExpanded = true
        }
    }

    UiMetricsOverlay {
        visible: typeof UiMetricsDebug !== "undefined" && UiMetricsDebug
        z: 1000
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 18
        targetWindow: appWindow
        targetContent: pageStack
        fontFamily: appWindow.uiFont
    }

    // ====== Toast 通知浮层 ======
    Loader {
        id: toastLoader
        anchors.fill: parent
        active: true
        sourceComponent: Toast { }
    }
}
