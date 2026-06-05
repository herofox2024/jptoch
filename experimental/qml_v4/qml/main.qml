import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "pages"

ApplicationWindow {
    id: appWindow
    visible: true
    width: 1100; height: 750
    minimumWidth: 900; minimumHeight: 600
    title: "EPUB 日译中 V4.0"

    property var cfg: ConfigBridge
    property var tbridge: TranslateBridge
    property var gbridge: GlossaryBridge

    Material.theme: cfg && cfg.theme === "dark" ? Material.Dark : Material.Light
    Material.accent: Material.Indigo; Material.primary: Material.Indigo

    Connections {
        target: cfg
        function onThemeChanged() { if (cfg) cfg.saveToDisk() }
        ignoreUnknownSignals: true
    }

    readonly property color hintColor: Material.theme === Material.Dark ? "#aaaaaa" : "#888888"

    // --- Page switch animation ---
    function switchPage(index) {
        if (pageStack.currentIndex === index) return
        var wasVisible = false
        var oldPage = pageStack.children[pageStack.currentIndex]
        if (oldPage && oldPage.opacity !== undefined) {
            wasVisible = (oldPage.opacity > 0.5)
            if (wasVisible) {
                fadeOutAnim.target = oldPage
                fadeOutAnim.start()
            }
        }
        pageStack.currentIndex = index
        var newPage = pageStack.children[index]
        if (newPage && newPage.opacity !== undefined) {
            newPage.opacity = 0.0
            fadeInAnim.target = newPage
            fadeInAnim.start()
        } else if (!wasVisible) {
            // First load: just show
            var np = pageStack.children[index]
            if (np && np.opacity !== undefined) np.opacity = 1.0
        }
    }

    NumberAnimation { id: fadeOutAnim; property: "opacity"; to: 0.0; duration: 120; easing.type: Easing.OutCubic }
    NumberAnimation { id: fadeInAnim; property: "opacity"; to: 1.0; duration: 180; easing.type: Easing.OutCubic }

    header: ToolBar {
        Material.elevation: 2
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 16
            Label { text: "EPUB 日译中"; font.pixelSize: 18; font.weight: Font.DemiBold; color: Material.accent }
            Label { text: "V4.0 · Material 3"; font.pixelSize: 12; color: hintColor; Layout.leftMargin: 8 }
            Item { Layout.fillWidth: true }
        }
    }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Pane {
            Layout.preferredWidth: 80; Layout.fillHeight: true; padding: 0; Material.elevation: 1
            ColumnLayout {
                anchors.centerIn: parent; spacing: 4
                NavButton { iconText: "📄"; label: "任务"; pageIndex: 0 }
                NavButton { iconText: "📊"; label: "状态"; pageIndex: 1 }
                NavButton { iconText: "☁️"; label: "API"; pageIndex: 2 }
                NavButton { iconText: "📖"; label: "术语表"; pageIndex: 3 }
                NavButton { iconText: "⚙️"; label: "设置"; pageIndex: 4 }
            }
        }
        StackLayout {
            id: pageStack; Layout.fillWidth: true; Layout.fillHeight: true; currentIndex: 0
            TaskPage { cfg: appWindow.cfg; tbridge: appWindow.tbridge; onNavigateToStatus: appWindow.switchPage(1) }
            MonitorPage { cfg: appWindow.cfg; tbridge: appWindow.tbridge }
            ApiConfigPage { cfg: appWindow.cfg }
            GlossaryPage { cfg: appWindow.cfg; gbridge: appWindow.gbridge }
            OptionsPage { cfg: appWindow.cfg }
        }
    }

    component NavButton: RoundButton {
        id: navBtn
        property string iconText: ""
        property string label: ""
        property int pageIndex: 0
        implicitWidth: 60; implicitHeight: 64
        checkable: true
        checked: pageStack.currentIndex === pageIndex
        flat: !checked
        highlighted: checked
        onClicked: appWindow.switchPage(pageIndex)
        contentItem: Column {
            anchors.centerIn: parent; spacing: 2
            Text { text: navBtn.iconText; font.pixelSize: 22; anchors.horizontalCenter: parent.horizontalCenter }
            Text { text: navBtn.label; font.pixelSize: 10; anchors.horizontalCenter: parent.horizontalCenter; color: navBtn.checked ? Material.accent : appWindow.hintColor }
        }
        Behavior on highlighted { ColorAnimation { duration: 150 } }
    }
}
