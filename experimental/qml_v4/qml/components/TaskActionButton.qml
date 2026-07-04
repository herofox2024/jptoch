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
    implicitHeight: primary ? 64 : 40
    radius: primary ? 24 : 18
    color: !enabled
           ? AppPalette.cardAlt
           : (primary ? AppPalette.accentColor : (danger ? Qt.rgba(0.80, 0.24, 0.20, AppPalette.glass ? 0.18 : 0.10) : AppPalette.cardBg))
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
                   : (root.primary ? "#ffffff" : (root.danger ? AppPalette.errorColor : AppPalette.textColor))
            font.pixelSize: root.primary ? 18 : 13
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            maximumLineCount: 1
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            visible: root.hint !== ""
            text: root.hint
            color: root.primary ? Qt.rgba(1, 1, 1, 0.82) : AppPalette.mutedText
            font.pixelSize: root.primary ? 11 : 9
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
