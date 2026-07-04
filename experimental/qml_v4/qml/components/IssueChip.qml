import QtQuick
import QtQuick.Controls
import ".."

Rectangle {
    id: root

    property string title: ""
    property string tone: "neutral"

    width: Math.max(82, chipLabel.implicitWidth + 22)
    height: AppStyle.buttonHeightCompact
    radius: 14
    color: tone === "error"
           ? AppStyle.statusErrorBg
           : tone === "amber"
             ? AppStyle.statusWarningBg
             : tone === "accent"
               ? AppStyle.statusAccentBg
               : AppStyle.statusNeutralBg
    border.color: tone === "error"
                  ? AppPalette.errorColor
                  : tone === "amber"
                    ? AppPalette.amberColor
                    : tone === "accent"
                      ? AppPalette.accentColor
                      : AppPalette.lineColor

    Label {
        id: chipLabel
        anchors.centerIn: parent
        text: root.title
        color: root.border.color
        font.pixelSize: AppStyle.fontCaption
        font.weight: Font.DemiBold
    }
}
