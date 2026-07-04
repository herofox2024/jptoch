import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property string title: ""
    property string value: ""

    width: Math.min(240, Math.max(88, chipRow.implicitWidth + 22))
    height: AppStyle.buttonHeightCompact
    radius: 15
    color: AppPalette.cardBg
    border.color: AppPalette.lineColor

    RowLayout {
        id: chipRow
        anchors.centerIn: parent
        spacing: AppStyle.spacingXSmall + 1

        Label {
            text: root.title + ":"
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontCaption
        }

        Label {
            text: root.value
            color: AppPalette.textColor
            font.pixelSize: AppStyle.fontCaption
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }
}
