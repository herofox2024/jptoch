import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

/* ============================================================
   EmptyState — 空状态占位（图标 + 标题 + 引导文字）

   用法:
     EmptyState {
         iconName: "glossary"
         title: "暂无 profile"
         description: "可在任务页点击“提取本书术语”，或点击“保存当前术语表”生成 profile。"
     }
   ============================================================ */

ColumnLayout {
    id: root

    property string iconName: "task"
    property string title: ""
    property string description: ""

    spacing: AppStyle.spacingSmall

    Rectangle {
        Layout.alignment: Qt.AlignHCenter
        Layout.preferredWidth: 48
        Layout.preferredHeight: 48
        radius: 24
        color: AppPalette.accentSoft
        opacity: 0.85

        NavIcon {
            anchors.centerIn: parent
            width: 24
            height: 24
            name: root.iconName
            lineColor: AppPalette.accentColor
        }
    }

    Label {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: true
        visible: root.title !== ""
        text: root.title
        color: AppPalette.textColor
        font.pixelSize: AppStyle.fontSection
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
    }

    Label {
        Layout.alignment: Qt.AlignHCenter
        Layout.fillWidth: true
        visible: root.description !== ""
        text: root.description
        color: AppPalette.mutedText
        font.pixelSize: AppStyle.fontSmall
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
    }
}
