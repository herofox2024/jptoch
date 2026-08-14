import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: contactLink
    property string label: ""
    property string value: ""
    property string targetUrl: ""
    property bool glassMode: false
    property bool hovering: false

    Layout.fillWidth: true
    Layout.preferredHeight: AppStyle.buttonHeightCompact
    radius: 10
    color: contactLink.hovering || contactLink.activeFocus
           ? (AppPalette.dark || contactLink.glassMode ? Qt.rgba(1, 1, 1, 0.16) : AppPalette.accentSoft)
           : (AppPalette.dark || contactLink.glassMode ? Qt.rgba(1, 1, 1, 0.07) : AppPalette.cardAlt)
    border.color: contactLink.activeFocus
                  ? AppPalette.accentColor
                  : (AppPalette.dark || contactLink.glassMode ? Qt.rgba(255, 255, 255, 0.10) : AppPalette.lineColor)
    border.width: 1
    activeFocusOnTab: true

    function openTarget() {
        if (contactLink.targetUrl !== "") {
            Qt.openUrlExternally(contactLink.targetUrl)
            contactLink.forceActiveFocus()
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 9
        anchors.rightMargin: 9
        spacing: AppStyle.spacingInline

        Label {
            text: contactLink.label
            color: AppPalette.accentColor
            font.pixelSize: AppStyle.fontTiny
            font.weight: Font.DemiBold
            Layout.preferredWidth: 42
            elide: Text.ElideRight
        }

        Label {
            Layout.fillWidth: true
            text: contactLink.value
            color: AppPalette.textColor
            font.pixelSize: AppStyle.fontTiny
            elide: Text.ElideRight
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: contactLink.hovering = true
        onExited: contactLink.hovering = false
        onClicked: contactLink.openTarget()
    }

    Keys.onReturnPressed: contactLink.openTarget()
    Keys.onEnterPressed: contactLink.openTarget()
    Keys.onSpacePressed: contactLink.openTarget()
    Accessible.role: Accessible.Link
    Accessible.name: contactLink.label + " " + contactLink.value
}
