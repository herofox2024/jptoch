import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property string title: ""
    property var value: ""
    property string tone: ""
    property real cardWidth: 112
    property real viewportWidth: 800

    Layout.fillWidth: true
    Layout.preferredWidth: cardWidth
    Layout.minimumWidth: 96
    Layout.preferredHeight: viewportWidth > 760 ? 76 : 70
    radius: AppPalette.radiusMedium
    color: AppPalette.surfaceRaised
    border.color: AppPalette.lineColor

    readonly property color toneColor: tone === "accent"
                                       ? AppPalette.accentColor
                                       : tone === "amber"
                                         ? AppPalette.amberColor
                                         : tone === "success"
                                           ? AppPalette.successColor
                                           : tone === "error"
                                             ? AppPalette.errorColor
                                             : AppPalette.textColor

    Rectangle {
        width: 26
        height: 3
        radius: 2
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 10
        anchors.topMargin: 9
        color: root.toneColor
        opacity: 0.85
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: AppStyle.spacingMedium
        anchors.topMargin: AppStyle.sectionGap
        spacing: AppStyle.spacingXSmall

        Label {
            Layout.fillWidth: true
            text: root.title
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontTiny
            elide: Text.ElideRight
        }

        Label {
            Layout.fillWidth: true
            text: root.value !== undefined ? root.value.toString() : "0"
            color: root.toneColor
            font.pixelSize: root.viewportWidth > 760 ? AppStyle.fontBodyLarge + 1 : AppStyle.fontBodyLarge
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }
}
