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
        anchors.margins: AppStyle.spacingLarge
        spacing: AppStyle.spacingSmall

        Label {
            Layout.fillWidth: true
            text: root.title
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            font.weight: Font.DemiBold
        }

        TextArea {
            id: realtimeText
            Layout.fillWidth: true
            Layout.fillHeight: true
            readOnly: true
            placeholderText: root.placeholder
            font.pixelSize: AppStyle.fontBody
            wrapMode: Text.WordWrap
            color: root.textColor
            padding: AppStyle.spacingMedium
            leftPadding: AppStyle.spacingMedium
            rightPadding: AppStyle.spacingMedium
            topPadding: AppStyle.spacingSmall
            bottomPadding: AppStyle.spacingSmall
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
