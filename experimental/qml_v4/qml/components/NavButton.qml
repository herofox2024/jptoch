import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Item {
    id: navBtn
    property string iconName: ""
    property string label: ""
    property string desc: ""
    property int pageIndex: 0
    property bool active: false
    property bool glassMode: false
    property bool hovering: false
    signal activated(int pageIndex)

    Layout.fillWidth: true
    Layout.preferredHeight: AppStyle.navButtonHeight
    activeFocusOnTab: true

    function activate() {
        navBtn.activated(navBtn.pageIndex)
        navBtn.forceActiveFocus()
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: navBtn.active
               ? AppPalette.navActiveBg
               : (navBtn.glassMode && navBtn.hovering ? Qt.rgba(1, 1, 1, 0.10) : "transparent")
        border.color: navBtn.active
                      ? (navBtn.glassMode ? Qt.rgba(1, 1, 1, 0.72) : AppPalette.accentColor)
                      : (navBtn.activeFocus ? AppPalette.amberColor : (navBtn.glassMode && navBtn.hovering ? Qt.rgba(1, 1, 1, 0.18) : "transparent"))
        border.width: navBtn.active || navBtn.activeFocus || (navBtn.glassMode && navBtn.hovering) ? 1 : 0
        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    Rectangle {
        visible: navBtn.glassMode && navBtn.active
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        height: 1
        color: Qt.rgba(1, 1, 1, 0.72)
    }

    Rectangle {
        width: 4
        height: 28
        radius: 2
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        color: AppPalette.accentColor
        visible: navBtn.active
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 12
        spacing: AppStyle.spacingMedium

        Item {
            Layout.preferredWidth: 34
            Layout.preferredHeight: AppStyle.buttonHeightSmall
            Rectangle {
                anchors.fill: parent
                radius: 7
                color: navBtn.active
                       ? AppPalette.accentColor
                       : AppPalette.cardAlt
                opacity: 1.0
            }
            NavIcon {
                anchors.centerIn: parent
                width: 21
                height: 21
                name: navBtn.iconName
                lineColor: navBtn.active ? "white" : AppPalette.mutedText
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingNone
            Label {
                text: navBtn.label
                color: navBtn.active ? AppPalette.accentColor : AppPalette.textColor
                font.pixelSize: AppStyle.fontBodyLarge
                font.weight: Font.DemiBold
            }
            Label {
                text: navBtn.desc
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontTiny
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onEntered: navBtn.hovering = true
        onExited: navBtn.hovering = false
        onClicked: navBtn.activate()
    }

    Keys.onReturnPressed: navBtn.activate()
    Keys.onEnterPressed: navBtn.activate()
    Keys.onSpacePressed: navBtn.activate()
    Accessible.role: Accessible.Button
    Accessible.name: navBtn.label
    Accessible.description: navBtn.desc
}
