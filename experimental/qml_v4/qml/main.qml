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
    width: 1180
    height: 780
    minimumWidth: 860
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
        // 主题过渡：在 color/opacity 变化时添加平滑动画
        Behavior on color { ColorAnimation { duration: 400; easing.type: Easing.OutCubic } }

        gradient: Gradient {
            GradientStop { position: 0.0; color: AppPalette.background }
            GradientStop { position: 1.0; color: AppPalette.backgroundAlt }
        }
        Rectangle {
            width: 520
            height: 520
            radius: 260
            x: parent.width - width * 0.42
            y: -180
            color: appWindow.glassMode ? AppPalette.glassGlowCyan : AppPalette.accentSoft
            opacity: appWindow.glassMode ? 0.72 : (AppPalette.dark ? 0.24 : 0.55)
        }
        Rectangle {
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
        height: 68
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
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            spacing: 12

            Rectangle {
                Layout.preferredWidth: 38
                Layout.preferredHeight: 38
                radius: 12
                color: appWindow.glassMode ? Qt.rgba(0.05, 0.43, 0.45, 0.88) : AppPalette.accentColor
                border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.48) : "transparent"
                Label {
                    anchors.centerIn: parent
                    text: "译"
                    color: "white"
                    font.family: appWindow.titleFont
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
            }

            ColumnLayout {
                spacing: 0
                Label {
                    text: "AI日译中（EPUB）V4.1"
                    color: AppPalette.textColor
                    font.family: appWindow.titleFont
                    font.pixelSize: 19
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "日系小说翻译工作台 · PySide6/QML V4.1"
                    color: AppPalette.mutedText
                    font.pixelSize: 12
                }
            }

            Item { Layout.fillWidth: true }

            Rectangle {
                Layout.preferredWidth: 150
                Layout.minimumWidth: 150
                Layout.preferredHeight: 32
                radius: 16
                color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.44) : AppPalette.accentSoft
                border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.62) : AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: appWindow.glassMode ? "V4.1 玻璃" : "V4.1"
                    color: AppPalette.accentColor
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.preferredWidth: 168
            Layout.fillHeight: true
            border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.26) : (AppPalette.dark ? "#223934" : "#244a4b")
            border.width: 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: AppPalette.navBg }
                GradientStop { position: 1.0; color: AppPalette.navBgAlt }
            }

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
                spacing: 12

                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    Label {
                        text: "Workflow"
                        color: "#d9eee7"
                        font.pixelSize: 12
                        font.letterSpacing: 1.2
                        opacity: 0.82
                    }
                    Label {
                        text: "翻译流程"
                        color: "white"
                        font.family: appWindow.titleFont
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 1
                    color: "#ffffff"
                    opacity: 0.16
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    NavButton { iconName: "task"; label: "任务"; desc: "导入书籍"; pageIndex: 0 }
                    NavButton { iconName: "status"; label: "状态"; desc: "实时进度"; pageIndex: 1 }
                    NavButton { iconName: "log"; label: "日志"; desc: "实时诊断"; pageIndex: 2 }
                    NavButton { iconName: "api"; label: "API"; desc: "模型接口"; pageIndex: 3 }
                    NavButton { iconName: "glossary"; label: "术语表"; desc: "名词统一"; pageIndex: 4 }
                    NavButton { iconName: "settings"; label: "设置"; desc: "性能校对"; pageIndex: 5 }
                }

                Item { Layout.fillHeight: true }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 108
                    radius: 20
                    color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.12) : Qt.rgba(1, 1, 1, 0.075)
                    border.color: appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.18) : Qt.rgba(255, 255, 255, 0.10)
                    clip: true

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 3
                        color: AppPalette.amberColor
                        opacity: 0.85
                    }

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: 7

                        Label {
                            Layout.fillWidth: true
                            text: "\u9879\u76ee\u4e0e\u8054\u7cfb"
                            color: "#eefcf8"
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            opacity: 0.92
                        }

                        ContactLink {
                            label: "GitHub"
                            value: "herofox2024/jptoch"
                            targetUrl: "https://github.com/herofox2024/jptoch"
                        }

                        ContactLink {
                            label: "Email"
                            value: "42845734@qq.com"
                            targetUrl: "mailto:42845734@qq.com"
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
    }

    component NavButton: Item {
        id: navBtn
        property string iconName: ""
        property string label: ""
        property string desc: ""
        property int pageIndex: 0
        property bool hovering: false
        readonly property bool active: pageStack.currentIndex === pageIndex

        Layout.fillWidth: true
        Layout.preferredHeight: 58
        activeFocusOnTab: true

        function activate() {
            appWindow.switchPage(navBtn.pageIndex)
            navBtn.forceActiveFocus()
        }

        Rectangle {
            anchors.fill: parent
            radius: 18
            color: navBtn.active
                   ? AppPalette.navActiveBg
                   : (appWindow.glassMode && navBtn.hovering ? Qt.rgba(1, 1, 1, 0.10) : "transparent")
            border.color: navBtn.active
                          ? (appWindow.glassMode ? Qt.rgba(1, 1, 1, 0.72) : AppPalette.amberColor)
                          : (navBtn.activeFocus ? AppPalette.amberColor : (appWindow.glassMode && navBtn.hovering ? Qt.rgba(1, 1, 1, 0.18) : "transparent"))
            border.width: navBtn.active || navBtn.activeFocus || (appWindow.glassMode && navBtn.hovering) ? 1 : 0
            Behavior on border.color { ColorAnimation { duration: 120 } }
        }

        Rectangle {
            visible: appWindow.glassMode && navBtn.active
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            height: 1
            color: Qt.rgba(1, 1, 1, 0.72)
        }

        Rectangle {
            width: 4
            height: 28
            radius: 2
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            color: AppPalette.amberColor
            visible: navBtn.active
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 12
            spacing: 10

            Item {
                Layout.preferredWidth: 34
                Layout.preferredHeight: 34
                Rectangle {
                    anchors.fill: parent
                    radius: 12
                    color: navBtn.active
                           ? (appWindow.glassMode ? AppPalette.accentColor : AppPalette.amberColor)
                           : "#ffffff"
                    opacity: navBtn.active ? 1.0 : (appWindow.glassMode ? 0.22 : 0.18)
                }
                NavIcon {
                    anchors.centerIn: parent
                    width: 21
                    height: 21
                    name: navBtn.iconName
                    lineColor: navBtn.active ? "white" : (appWindow.glassMode ? "#eefcf8" : "#d9eee7")
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label {
                    text: navBtn.label
                    color: navBtn.active ? AppPalette.textColor : "white"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                Label {
                    text: navBtn.desc
                    color: navBtn.active ? AppPalette.mutedText : "#c9e1d9"
                    font.pixelSize: 10
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: navBtn.hovering = true
            onExited: navBtn.hovering = false
            onClicked: navBtn.activate()
        }

        Keys.onReturnPressed: navBtn.activate()
        Keys.onEnterPressed: navBtn.activate()
        Keys.onSpacePressed: navBtn.activate()
        Accessible.role: Accessible.Button
        Accessible.name: navBtn.label
        Accessible.description: navBtn.desc
    }

    component ContactLink: Rectangle {
        id: contactLink
        property string label: ""
        property string value: ""
        property string targetUrl: ""
        property bool hovering: false

        Layout.fillWidth: true
        Layout.preferredHeight: 28
        radius: 10
        color: contactLink.hovering || contactLink.activeFocus
               ? Qt.rgba(1, 1, 1, 0.16)
               : Qt.rgba(1, 1, 1, 0.07)
        border.color: contactLink.activeFocus ? AppPalette.amberColor : Qt.rgba(255, 255, 255, 0.10)
        border.width: contactLink.activeFocus ? 1 : 0
        activeFocusOnTab: true

        function openTarget() {
            if (contactLink.targetUrl !== "") {
                Qt.openUrlExternally(contactLink.targetUrl)
                contactLink.forceActiveFocus()
            }
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 9
            anchors.rightMargin: 9
            spacing: 6

            Label {
                text: contactLink.label
                color: AppPalette.amberColor
                font.pixelSize: 10
                font.weight: Font.DemiBold
                Layout.preferredWidth: 42
                elide: Text.ElideRight
            }

            Label {
                Layout.fillWidth: true
                text: contactLink.value
                color: "#d7eee8"
                font.pixelSize: 10
                elide: Text.ElideRight
            }
        }

        MouseArea {
            id: mouseArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: contactLink.hovering = true
            onExited: contactLink.hovering = false
            onClicked: contactLink.openTarget()
        }

        Keys.onReturnPressed: contactLink.openTarget()
        Keys.onEnterPressed: contactLink.openTarget()
        Keys.onSpacePressed: contactLink.openTarget()
        Accessible.role: Accessible.Link
        Accessible.name: contactLink.label + " " + contactLink.value
    }

    component NavIcon: Item {
        id: navIcon
        property string name: "task"
        property color lineColor: "white"

        Canvas {
            id: iconCanvas
            anchors.fill: parent
            antialiasing: true

            function px(v) { return v * width / 24 }
            function py(v) { return v * height / 24 }

            function roundedRect(ctx, x, y, w, h, r) {
                ctx.beginPath()
                ctx.moveTo(px(x + r), py(y))
                ctx.lineTo(px(x + w - r), py(y))
                ctx.quadraticCurveTo(px(x + w), py(y), px(x + w), py(y + r))
                ctx.lineTo(px(x + w), py(y + h - r))
                ctx.quadraticCurveTo(px(x + w), py(y + h), px(x + w - r), py(y + h))
                ctx.lineTo(px(x + r), py(y + h))
                ctx.quadraticCurveTo(px(x), py(y + h), px(x), py(y + h - r))
                ctx.lineTo(px(x), py(y + r))
                ctx.quadraticCurveTo(px(x), py(y), px(x + r), py(y))
            }

            function line(ctx, x1, y1, x2, y2) {
                ctx.beginPath()
                ctx.moveTo(px(x1), py(y1))
                ctx.lineTo(px(x2), py(y2))
                ctx.stroke()
            }

            function circle(ctx, x, y, r, fill) {
                ctx.beginPath()
                ctx.arc(px(x), py(y), px(r), 0, Math.PI * 2)
                if (fill) ctx.fill()
                else ctx.stroke()
            }

            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.clearRect(0, 0, width, height)
                ctx.strokeStyle = navIcon.lineColor
                ctx.fillStyle = navIcon.lineColor
                ctx.lineWidth = Math.max(1.7, width / 13)
                ctx.lineCap = "round"
                ctx.lineJoin = "round"

                if (navIcon.name === "task") {
                    roundedRect(ctx, 5, 3.5, 12.5, 17, 2)
                    ctx.stroke()
                    line(ctx, 8, 9, 14, 9)
                    line(ctx, 8, 13, 15, 13)
                    line(ctx, 8, 17, 12, 17)
                    line(ctx, 14.5, 3.5, 18.5, 7.5)
                } else if (navIcon.name === "status") {
                    circle(ctx, 12, 12, 8, false)
                    ctx.beginPath()
                    ctx.arc(px(12), py(12), px(8), -Math.PI / 2, Math.PI / 5)
                    ctx.stroke()
                    line(ctx, 12, 12, 16, 9)
                    circle(ctx, 12, 12, 1.2, true)
                } else if (navIcon.name === "api") {
                    roundedRect(ctx, 3.5, 6, 17, 12, 2.5)
                    ctx.stroke()
                    line(ctx, 7, 12, 10, 12)
                    line(ctx, 14, 12, 17, 12)
                    circle(ctx, 12, 12, 1.4, true)
                    line(ctx, 12, 6, 12, 3.5)
                    line(ctx, 12, 18, 12, 20.5)
                } else if (navIcon.name === "log") {
                    roundedRect(ctx, 4.5, 3.5, 15, 17, 2.2)
                    ctx.stroke()
                    line(ctx, 8, 8, 16, 8)
                    line(ctx, 8, 12, 16, 12)
                    line(ctx, 8, 16, 13.5, 16)
                    circle(ctx, 6.8, 8, 0.45, true)
                    circle(ctx, 6.8, 12, 0.45, true)
                    circle(ctx, 6.8, 16, 0.45, true)
                } else if (navIcon.name === "glossary") {
                    ctx.beginPath()
                    ctx.moveTo(px(4), py(6))
                    ctx.quadraticCurveTo(px(8), py(4), px(12), py(6))
                    ctx.quadraticCurveTo(px(16), py(4), px(20), py(6))
                    ctx.lineTo(px(20), py(19))
                    ctx.quadraticCurveTo(px(16), py(17), px(12), py(19))
                    ctx.quadraticCurveTo(px(8), py(17), px(4), py(19))
                    ctx.closePath()
                    ctx.stroke()
                    line(ctx, 12, 6, 12, 19)
                    line(ctx, 7, 10, 10, 9.5)
                    line(ctx, 14, 9.5, 17, 10)
                } else {
                    circle(ctx, 12, 12, 4, false)
                    for (var i = 0; i < 8; i++) {
                        var a = i * Math.PI / 4
                        var x1 = 12 + Math.cos(a) * 7
                        var y1 = 12 + Math.sin(a) * 7
                        var x2 = 12 + Math.cos(a) * 9
                        var y2 = 12 + Math.sin(a) * 9
                        line(ctx, x1, y1, x2, y2)
                    }
                }
            }

            Component.onCompleted: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
        }

        onNameChanged: iconCanvas.requestPaint()
        onLineColorChanged: iconCanvas.requestPaint()
    }

    // ====== Toast 通知浮层 ======
    Loader {
        id: toastLoader
        anchors.fill: parent
        active: true
        sourceComponent: Toast { }
    }
}
