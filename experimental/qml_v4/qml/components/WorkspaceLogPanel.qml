import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property var logBridge: null
    property string recentText: "等待新的运行日志"

    signal openFullLog()
    signal collapseRequested()

    color: AppPalette.surface
    border.color: AppPalette.lineColor
    border.width: 1

    function reload() {
        if (!root.logBridge || !root.logBridge.readRecent) {
            root.recentText = "日志服务未加载"
            return
        }
        root.recentText = root.logBridge.readRecent(18) || "等待新的运行日志"
    }

    Component.onCompleted: reload()

    Connections {
        target: root.logBridge
        ignoreUnknownSignals: true

        function onEntryAppended(line) {
            if (!line)
                return
            var merged = root.recentText === "等待新的运行日志"
                    ? line : root.recentText + "\n" + line
            var rows = merged.split("\n")
            root.recentText = rows.slice(Math.max(0, rows.length - 18)).join("\n")
        }

        function onCurrentLogPathChanged() {
            root.reload()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: AppStyle.spacingLarge

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Label {
                    text: "LIVE FEED"
                    color: AppPalette.accentColor
                    font.pixelSize: AppStyle.fontTiny
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.0
                }

                Label {
                    text: "实时日志"
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontSection
                    font.weight: Font.DemiBold
                }
            }

            ToolButton {
                text: "×"
                ToolTip.visible: hovered
                ToolTip.text: "收起日志面板"
                onClicked: root.collapseRequested()
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            radius: 6
            color: AppPalette.cardAlt

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                spacing: AppStyle.spacingSmall

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    color: AppPalette.successColor
                }

                Label {
                    Layout.fillWidth: true
                    text: "日志流已连接"
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontCaption
                    font.weight: Font.DemiBold
                }

                Label {
                    text: "实时"
                    color: AppPalette.successColor
                    font.pixelSize: AppStyle.fontTiny
                }
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

            TextArea {
                text: root.recentText
                readOnly: true
                selectByMouse: true
                wrapMode: Text.Wrap
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontTiny
                font.family: "Consolas"
                background: Item {}
            }
        }

        Button {
            Layout.fillWidth: true
            text: "查看完整日志"
            flat: true
            onClicked: root.openFullLog()
        }
    }
}
