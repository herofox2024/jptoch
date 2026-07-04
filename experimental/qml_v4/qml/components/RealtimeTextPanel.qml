import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property alias text: realtimeText.text
    property string title: ""
    property string placeholder: ""
    property color textColor: AppPalette.textColor

    radius: AppPalette.radiusMedium
    color: AppPalette.fieldBg
    border.color: AppPalette.lineColor
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        Label {
            Layout.fillWidth: true
            text: root.title
            color: AppPalette.mutedText
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }

        TextArea {
            id: realtimeText
            Layout.fillWidth: true
            Layout.fillHeight: true
            readOnly: true
            placeholderText: root.placeholder
            font.pixelSize: 13
            wrapMode: Text.WordWrap
            color: root.textColor
            padding: 10
            leftPadding: 10
            rightPadding: 10
            topPadding: 8
            bottomPadding: 8
            clip: true
            selectByMouse: true
            background: Rectangle {
                radius: AppPalette.radiusSmall
                color: AppPalette.cardBg
                border.color: AppPalette.lineColor
            }
        }
    }
}
