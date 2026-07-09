import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import ".."

Item {
    id: root
    property var targetWindow
    property var targetContent
    property string fontFamily: "Microsoft YaHei UI"
    property bool expanded: true

    width: panel.width
    height: panel.implicitHeight

    function fmt(value) {
        if (value === undefined || value === null || isNaN(value)) {
            return "-"
        }
        return Number(value).toFixed(1)
    }

    function metricRows() {
        var win = targetWindow || root.Window.window
        var content = targetContent
        return [
            "window: " + fmt(win ? win.width : 0) + " x " + fmt(win ? win.height : 0),
            "minimum: " + fmt(win ? win.minimumWidth : 0) + " x " + fmt(win ? win.minimumHeight : 0),
            "content: " + fmt(content ? content.width : 0) + " x " + fmt(content ? content.height : 0),
            "screen: " + Screen.width + " x " + Screen.height,
            "available: " + Screen.desktopAvailableWidth + " x " + Screen.desktopAvailableHeight,
            "dpr: " + fmt(Screen.devicePixelRatio) + "  density: " + fmt(Screen.pixelDensity),
            "font: body " + AppStyle.fontBody + " / title " + AppStyle.fontPageTitle,
            "spacing: page " + AppStyle.pagePadding + " / card " + AppStyle.cardPadding,
            "buttons: normal " + AppStyle.buttonHeightNormal + " / nav " + AppStyle.navButtonHeight
        ]
    }

    Rectangle {
        id: panel
        width: root.expanded ? 330 : 134
        implicitHeight: root.expanded ? contentColumn.implicitHeight + 24 : 38
        radius: 16
        color: Qt.rgba(0.05, 0.08, 0.07, 0.82)
        border.color: Qt.rgba(1, 1, 1, 0.22)
        border.width: 1

        Behavior on width { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
        Behavior on implicitHeight { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }

        ColumnLayout {
            id: contentColumn
            anchors.fill: parent
            anchors.margins: root.expanded ? 12 : 8
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    Layout.fillWidth: true
                    text: "UI Metrics"
                    color: "#ffffff"
                    font.family: root.fontFamily
                    font.pixelSize: 12
                    font.bold: true
                    elide: Text.ElideRight
                }

                Text {
                    text: root.expanded ? "hide" : "show"
                    color: "#9fe8d2"
                    font.family: root.fontFamily
                    font.pixelSize: 11
                }
            }

            Repeater {
                model: root.expanded ? root.metricRows() : []
                delegate: Text {
                    Layout.fillWidth: true
                    text: modelData
                    color: "#d7eee8"
                    font.family: root.fontFamily
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.expanded = !root.expanded
        }
    }
}
