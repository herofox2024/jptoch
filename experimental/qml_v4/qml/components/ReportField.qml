import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property string title: ""
    property string body: ""
    property string tone: "normal"
    property int maxLines: 0

    Layout.fillWidth: true
    Layout.preferredHeight: reportText.paintedHeight + reportTitle.implicitHeight + 24
    Layout.minimumHeight: Layout.preferredHeight
    radius: AppPalette.radiusSmall
    color: AppPalette.fieldBg
    border.color: tone === "accent" ? AppPalette.accentColor : AppPalette.lineColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 5

        Label {
            id: reportTitle
            Layout.fillWidth: true
            text: root.title
            color: root.tone === "accent" ? AppPalette.accentColor : AppPalette.mutedText
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }

        Label {
            id: reportText
            Layout.fillWidth: true
            text: root.body && root.body !== "" ? root.body : "-"
            color: root.tone === "accent" ? AppPalette.accentColor : AppPalette.textColor
            wrapMode: Text.WordWrap
            maximumLineCount: root.maxLines > 0 ? root.maxLines : 1000000
            elide: root.maxLines > 0 ? Text.ElideRight : Text.ElideNone
            font.pixelSize: 12
        }
    }
}
