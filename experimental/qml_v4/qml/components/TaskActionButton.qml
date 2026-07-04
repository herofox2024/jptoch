import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property string label: ""
    property string hint: ""
    property bool primary: false
    property bool danger: false

    signal clicked()

    implicitWidth: primary ? 320 : 132
    implicitHeight: primary ? AppStyle.buttonHeightPrimary : AppStyle.buttonHeightNormal
    radius: primary ? 24 : 18
    color: !enabled
           ? AppPalette.cardAlt
           : (primary ? AppPalette.accentColor : (danger ? AppStyle.dangerButtonBg : AppPalette.cardBg))
    border.color: !enabled
                  ? AppPalette.lineColor
                  : (primary ? AppPalette.accentColor : (danger ? AppPalette.errorColor : AppPalette.borderColor))
    border.width: primary ? 0 : 1
    opacity: enabled ? 1.0 : 0.52
    scale: actionMouse.containsMouse && enabled ? 1.012 : 1.0

    Behavior on scale {
        NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: "transparent"
        border.color: actionMouse.containsMouse && root.enabled ? AppPalette.amberColor : "transparent"
        border.width: 1
        opacity: actionMouse.containsMouse ? 0.7 : 0
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: parent.width - 20
        spacing: root.primary ? 5 : 1

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: root.label
            color: !root.enabled
                   ? AppPalette.mutedText
                   : (root.primary ? AppStyle.primaryOnAccent : (root.danger ? AppPalette.errorColor : AppPalette.textColor))
            font.pixelSize: root.primary ? AppStyle.fontHeader : AppStyle.fontBody
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            maximumLineCount: 1
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            visible: root.hint !== ""
            text: root.hint
            color: root.primary ? AppStyle.primaryOnAccentMuted : AppPalette.mutedText
            font.pixelSize: root.primary ? AppStyle.fontCaption : AppStyle.fontTiny
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }

    MouseArea {
        id: actionMouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }
}
