import QtQuick
import QtQuick.Controls
import ".."

Rectangle {
    id: root

    property string title: ""
    property string tone: "neutral"

    width: Math.max(82, chipLabel.implicitWidth + 22)
    height: 28
    radius: 14
    color: tone === "error"
           ? (AppPalette.dark ? "#3a2420" : "#f6ded9")
           : tone === "amber"
             ? (AppPalette.dark ? "#3b2d1c" : "#f2e4cf")
             : tone === "accent"
               ? AppPalette.accentSoft
               : AppPalette.cardAlt
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
        font.pixelSize: 11
        font.weight: Font.DemiBold
    }
}
