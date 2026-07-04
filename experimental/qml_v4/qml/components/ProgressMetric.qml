import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property string title: ""
    property string value: ""
    property string tone: ""

    Layout.fillWidth: true
    Layout.preferredHeight: 60
    radius: AppPalette.radiusMedium
    color: AppPalette.cardBg
    border.color: AppPalette.lineColor

    readonly property color toneColor: tone === "accent"
                                       ? AppPalette.accentColor
                                       : tone === "amber"
                                         ? AppPalette.amberColor
                                         : AppPalette.textColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 2

        Label {
            Layout.fillWidth: true
            text: root.title
            color: AppPalette.mutedText
            font.pixelSize: 11
            elide: Text.ElideRight
        }

        Label {
            Layout.fillWidth: true
            text: root.value
            color: root.toneColor
            font.pixelSize: 17
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }
}
