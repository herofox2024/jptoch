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
    // 默认尺寸；启动后用配置里记录的几何覆盖（见 restoreWindowGeometry）。
    width: 1420
    height: 860
    minimumWidth: 980
    minimumHeight: 640
    title: typeof AppDisplayName !== "undefined" ? AppDisplayName : "AI日译中（EPUB）"
    font.family: typeof AppFontSans !== "undefined" ? AppFontSans : "Microsoft YaHei UI"

    // 是否已经从配置还原过窗口几何（避免用户在拖动时被重复覆盖）。
    property bool geometryRestored: false
    // 防止窗口几何变化频繁触发配置写入。
    property bool geometrySaveEnabled: false

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
    property int previousPageIndex: 0
    property bool taskPageLoaded: true
    property bool monitorPageLoaded: false
    property bool logPageLoaded: false
    property bool apiPageLoaded: false
    property bool glossaryPageLoaded: false
    property bool optionsPageLoaded: false
    property bool workspaceLogExpanded: true
    readonly property bool showWorkspaceLog: workspaceLogExpanded && width >= AppStyle.bpLogVisible

    // Material 主题跟随 AppPalette 的最终明暗判定，
    // 保证 glass 等半透明主题下控件与页面底色一致。
    Material.theme: AppPalette.dark ? Material.Dark : Material.Light
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

    // 把窗口宽度暴露给 AppStyle，用于按视口宽度决定是否开启卡片阴影。
    Binding {
        target: AppStyle
        property: "viewportWidth"
        value: appWindow.width
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

    // ---- 窗口级快捷键：与任务页按钮语义一致，任意页面可用 ----
    Shortcut {
        sequences: ["Ctrl+Return", "Ctrl+Enter"]
        enabled: taskLoader.item !== null && taskLoader.item.canStart
        context: Qt.WindowShortcut
        onActivated: {
            if (taskLoader.item) taskLoader.item.triggerStart()
        }
    }

    Shortcut {
        sequence: "Ctrl+P"
        enabled: taskLoader.item !== null && taskLoader.item.canPause
        context: Qt.WindowShortcut
        onActivated: {
            if (taskLoader.item) taskLoader.item.triggerPause()
        }
    }

    Shortcut {
        sequence: "Ctrl+R"
        enabled: taskLoader.item !== null && !taskLoader.item.busy && taskLoader.item.readyToStart
        context: Qt.WindowShortcut
        onActivated: {
            if (taskLoader.item) taskLoader.item.triggerResume()
        }
    }

    Shortcut {
        sequence: "Ctrl+Shift+X"
        enabled: taskLoader.item !== null && taskLoader.item.canStop
        context: Qt.WindowShortcut
        onActivated: {
            if (taskLoader.item) taskLoader.item.triggerStop()
        }
    }

    Shortcut {
        sequence: "Ctrl+1"
        context: Qt.WindowShortcut
        onActivated: appWindow.switchPage(0)
    }

    Shortcut {
        sequence: "Ctrl+2"
        context: Qt.WindowShortcut
        onActivated: appWindow.switchPage(1)
    }

    Shortcut {
        sequence: "Ctrl+3"
        context: Qt.WindowShortcut
        onActivated: appWindow.switchPage(2)
    }

    function switchPage(index) {
        if (appWindow.currentPageIndex === index) return
        appWindow.previousPageIndex = appWindow.currentPageIndex
        appWindow.markPageLoaded(index)
        appWindow.currentPageIndex = index
        Qt.callLater(appWindow.activateCurrentPage)
    }

    // ===== 窗口几何持久化 =====
    // 还原时做边界校验：如果记录的几何落在当前所有屏幕之外（例如拔掉了副屏），
    // 就退回默认尺寸，避免窗口出现在看不见的位置。
    function restoreWindowGeometry() {
        if (!cfg || appWindow.geometryRestored) return
        var w = cfg.windowW
        var h = cfg.windowH
        if (w > 0 && h > 0) {
            appWindow.width = Math.max(appWindow.minimumWidth, Math.min(w, screen ? screen.width : w))
            appWindow.height = Math.max(appWindow.minimumHeight, Math.min(h, screen ? screen.height : h))
            var x = cfg.windowX
            var y = cfg.windowY
            if (appWindow.windowIsOnScreen(x, y, appWindow.width, appWindow.height)) {
                appWindow.x = x
                appWindow.y = y
            }
        }
        if (cfg.windowMaximized) appWindow.visibility = Window.Maximized
        appWindow.geometryRestored = true
        appWindow.geometrySaveEnabled = true
    }

    // 判断某个矩形是否与任一屏幕有足够重叠（至少露出标题栏区域）。
    function windowIsOnScreen(x, y, w, h) {
        var screens = Qt.application.screens
        for (var i = 0; i < screens.length; i++) {
            var s = screens[i]
            var overlapX = Math.min(x + w, s.virtualX + s.width) - Math.max(x, s.virtualX)
            var overlapY = Math.min(y + h, s.virtualY + s.height) - Math.max(y, s.virtualY)
            if (overlapX >= 120 && overlapY >= 80) return true
        }
        return false
    }

    function saveWindowGeometry() {
        if (!cfg || !appWindow.geometrySaveEnabled) return
        // 最大化/全屏时不覆盖普通状态的几何，只记录标志位。
        var maximized = appWindow.visibility === Window.Maximized
        if (maximized !== cfg.windowMaximized) cfg.windowMaximized = maximized
        if (maximized) return
        if (cfg.windowX !== appWindow.x) cfg.windowX = appWindow.x
        if (cfg.windowY !== appWindow.y) cfg.windowY = appWindow.y
        if (cfg.windowW !== appWindow.width) cfg.windowW = appWindow.width
        if (cfg.windowH !== appWindow.height) cfg.windowH = appWindow.height
    }

    onXChanged: Qt.callLater(appWindow.saveWindowGeometry)
    onYChanged: Qt.callLater(appWindow.saveWindowGeometry)
    onWidthChanged: Qt.callLater(appWindow.saveWindowGeometry)
    onHeightChanged: Qt.callLater(appWindow.saveWindowGeometry)
    onVisibilityChanged: Qt.callLater(appWindow.saveWindowGeometry)

    Component.onCompleted: Qt.callLater(appWindow.restoreWindowGeometry)

    function pageX(i) {
        if (appWindow.currentPageIndex === i) return 0
        var dir = appWindow.currentPageIndex >= appWindow.previousPageIndex ? 1 : -1
        if (appWindow.previousPageIndex === i) return -dir * pageStack.width * 0.25
        return dir * pageStack.width * 0.25
    }

    function openRequestLogsPage() {
        appWindow.previousPageIndex = appWindow.currentPageIndex
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
        appWindow.previousPageIndex = appWindow.currentPageIndex
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

    // 顶部工具条 + 主内容区。使用系统原生标题栏，QML 无法向标题栏注入控件，
    // 因此「关于」等全局入口统一放在内容区顶部。
    ColumnLayout {
        anchors.fill: parent
        spacing: AppStyle.spacingNone

        AppTopBar {
            Layout.fillWidth: true
            appTitle: typeof AppDisplayName !== "undefined" ? AppDisplayName : "AI日译中（EPUB）"
            // 左侧只显示不含版本号的产品名，避免与系统标题栏、关于按钮三处重复。
            productName: typeof AppName !== "undefined" ? AppName : "AI日译中（EPUB）"
            versionText: typeof AppDisplayVersion !== "undefined" ? AppDisplayVersion : ""
            glassMode: appWindow.glassMode
            onAboutRequested: aboutDialog.open()
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
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
                        color: AppPalette.accentText
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
                        label: Strings.navWorkspace
                        desc: Strings.navWorkspaceDesc
                        pageIndex: 0
                        active: pageStack.currentIndex === 0
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "status"
                        label: Strings.navStatus
                        desc: Strings.navStatusDesc
                        pageIndex: 1
                        active: pageStack.currentIndex === 1
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "log"
                        label: Strings.navLog
                        desc: Strings.navLogDesc
                        pageIndex: 2
                        active: pageStack.currentIndex === 2
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "api"
                        label: Strings.navApi
                        desc: Strings.navApiDesc
                        pageIndex: 3
                        active: pageStack.currentIndex === 3
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "glossary"
                        label: Strings.navGlossary
                        desc: Strings.navGlossaryDesc
                        pageIndex: 4
                        active: pageStack.currentIndex === 4
                        glassMode: appWindow.glassMode
                        onActivated: function(idx) { appWindow.switchPage(idx) }
                    }
                    NavButton {
                        iconName: "settings"
                        label: Strings.navSettings
                        desc: Strings.navSettingsDesc
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

                // 页面转场用 x 位移 + 淡入淡出。
                // 这里不能用 anchors.fill —— 锚点会接管 x，使 `x: pageX(i)` 这条
                // 绑定失效（QML 会断开与锚点冲突的绑定），于是切页时页面既不动也不淡入。
                // 因此用 y/height 撑满、width 跟随父宽，只把 x 留给动画。
                Loader {
                    id: taskLoader
                    y: 0
                    height: pageStack.height
                    width: pageStack.width
                    active: appWindow.taskPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 0
                    opacity: appWindow.currentPageIndex === 0 ? 1 : 0
                    x: appWindow.pageX(0)
                    sourceComponent: TaskPage {
                        cfg: appWindow.cfg
                        tbridge: appWindow.tbridge
                        onNavigateToStatus: appWindow.switchPage(1)
                        onNavigateToLogs: appWindow.openRequestLogsPage()
                        onNavigateToApi: appWindow.switchPage(3)
                        onNavigateToSettings: appWindow.switchPage(5)
                        onNavigateToGlossary: appWindow.switchPage(4)
                    }
                    // 不要在这里加 Behavior on opacity：它会接管写入并让上面的 opacity 绑定失效，切页将完全不生效。
                    Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: monitorLoader
                    y: 0
                    height: pageStack.height
                    width: pageStack.width
                    active: appWindow.monitorPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 1
                    opacity: appWindow.currentPageIndex === 1 ? 1 : 0
                    x: appWindow.pageX(1)
                    sourceComponent: MonitorPage {
                        cfg: appWindow.cfg
                        tbridge: appWindow.tbridge
                        onRequestManualEdit: function(original, translation) {
                            appWindow.openManualEditFromMonitor(original, translation)
                        }
                    }
                    // 不要在这里加 Behavior on opacity：它会接管写入并让上面的 opacity 绑定失效，切页将完全不生效。
                    Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: apiLoader
                    y: 0
                    height: pageStack.height
                    width: pageStack.width
                    active: appWindow.apiPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 3
                    opacity: appWindow.currentPageIndex === 3 ? 1 : 0
                    x: appWindow.pageX(3)
                    sourceComponent: ApiConfigPage {
                        cfg: appWindow.cfg
                    }
                    // 不要在这里加 Behavior on opacity：它会接管写入并让上面的 opacity 绑定失效，切页将完全不生效。
                    Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: logLoader
                    y: 0
                    height: pageStack.height
                    width: pageStack.width
                    active: appWindow.logPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 2
                    opacity: appWindow.currentPageIndex === 2 ? 1 : 0
                    x: appWindow.pageX(2)
                    sourceComponent: LogPage {
                        logBridge: appWindow.logBridge
                    }
                    // 不要在这里加 Behavior on opacity：它会接管写入并让上面的 opacity 绑定失效，切页将完全不生效。
                    Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: glossaryLoader
                    y: 0
                    height: pageStack.height
                    width: pageStack.width
                    active: appWindow.glossaryPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 4
                    opacity: appWindow.currentPageIndex === 4 ? 1 : 0
                    x: appWindow.pageX(4)
                    sourceComponent: GlossaryPage {
                        cfg: appWindow.cfg
                        gbridge: appWindow.gbridge
                        tbridge: appWindow.tbridge
                    }
                    onLoaded: appWindow.activateCurrentPage()
                    // 不要在这里加 Behavior on opacity：它会接管写入并让上面的 opacity 绑定失效，切页将完全不生效。
                    Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                }

                Loader {
                    id: optionsLoader
                    y: 0
                    height: pageStack.height
                    width: pageStack.width
                    active: appWindow.optionsPageLoaded
                    visible: opacity > 0.01
                    enabled: appWindow.currentPageIndex === 5
                    opacity: appWindow.currentPageIndex === 5 ? 1 : 0
                    x: appWindow.pageX(5)
                    sourceComponent: OptionsPage {
                        cfg: appWindow.cfg
                        tbridge: appWindow.tbridge
                        updater: appWindow.updater
                    }
                    // 不要在这里加 Behavior on opacity：它会接管写入并让上面的 opacity 绑定失效，切页将完全不生效。
                    Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
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
    // 必须挂到 Overlay 上：模态 Dialog 会被 Controls 重新挂进 Overlay（z≈1000001），
    // 如果 Toast 留在 contentItem 里，弹窗内的成功/失败提示会被遮罩层完全盖住，
    // 用户看不到任何反馈。Toast 自身的 z 在 Overlay 内已经高于普通弹窗。
    Toast {
        id: toastOverlay
        parent: Overlay.overlay
    }

    // ====== 关于 ======
    AboutDialog {
        id: aboutDialog
        appName: typeof AppDisplayName !== "undefined" ? AppDisplayName : "AI日译中（EPUB）"
        displayVersion: typeof AppDisplayVersion !== "undefined" ? AppDisplayVersion : "--"
        fullVersion: typeof AppVersion !== "undefined" ? AppVersion : "--"
        pythonVersion: typeof AppPythonVersion !== "undefined" ? AppPythonVersion : "--"
        qtVersion: typeof AppQtVersion !== "undefined" ? AppQtVersion : "--"
        parentWidth: appWindow.width
        parentHeight: appWindow.height
        copyright: "译文仅供个人学习、研究与阅读辅助使用，请勿传播或用于商业用途。\n请支持并购买正版书籍。本项目遵循原书版权与各 API 服务商条款。"
    }
}
