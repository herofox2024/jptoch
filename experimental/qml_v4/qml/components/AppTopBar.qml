import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 窗口内顶部工具条。
//
// 说明：本应用使用系统原生标题栏，QML 无法向其中注入控件，
// 因此在内容区顶部留一条轻量工具条承载「关于」等全局入口。
// 工具条本身不拦截窗口拖拽：只有具体按钮会响应点击。
Rectangle {
    id: root

    property string appTitle: ""
    property string versionText: ""
    property bool glassMode: false
    property bool showDivider: true

    signal aboutRequested()

    implicitHeight: 44
    Layout.fillWidth: true

    color: "transparent"
    border.width: 0

    // 底部细分隔线，贴合 macOS 工具栏的视觉分隔。
    Rectangle {
        visible: root.showDivider
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: AppPalette.lineColor
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: AppStyle.spacingHuge
        anchors.rightMargin: AppStyle.spacingHuge
        spacing: AppStyle.spacingMedium

        Label {
            Layout.fillWidth: true
            text: root.appTitle
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            font.weight: Font.DemiBold
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
        }

        // 「关于」按钮：Apple 风格的行内文字按钮，悬停显示淡色底。
        Rectangle {
            id: aboutButton
            Layout.alignment: Qt.AlignVCenter
            implicitWidth: aboutRow.implicitWidth + 20
            implicitHeight: 28
            radius: AppStyle.radiusChip
            color: aboutMouse.containsMouse || aboutButton.activeFocus
                   ? (root.glassMode || AppPalette.dark
                      ? Qt.rgba(1, 1, 1, 0.14)
                      : AppPalette.accentSoft)
                   : "transparent"
            border.color: aboutButton.activeFocus ? AppPalette.accentColor : "transparent"
            border.width: 1
            activeFocusOnTab: true

            Accessible.role: Accessible.Button
            Accessible.name: "关于本软件"
            Accessible.description: root.versionText !== ""
                ? "查看版本 " + root.versionText + " 的详细信息"
                : "查看版本与运行环境信息"
            Accessible.onPressAction: root.aboutRequested()

            Keys.onReturnPressed: root.aboutRequested()
            Keys.onEnterPressed: root.aboutRequested()
            Keys.onSpacePressed: root.aboutRequested()

            RowLayout {
                id: aboutRow
                anchors.centerIn: parent
                spacing: AppStyle.spacingInline

                Label {
                    text: "关于"
                    color: aboutMouse.containsMouse || aboutButton.activeFocus
                           ? AppPalette.accentColor
                           : AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    font.weight: Font.DemiBold
                }

                Label {
                    visible: root.versionText !== ""
                    text: "v" + root.versionText
                    color: AppPalette.accentColor
                    font.pixelSize: AppStyle.fontTiny
                }
            }

            MouseArea {
                id: aboutMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    aboutButton.forceActiveFocus()
                    root.aboutRequested()
                }
            }
        }
    }
}
