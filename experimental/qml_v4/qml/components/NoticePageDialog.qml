import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    objectName: "noticePageDialog"
    id: dialog

    property var cfg: null
        // 调用方提供的可用尺寸上限（通常是所在页面的宽高）。
    // 注意：它**不是**弹窗自身尺寸 —— 布局判断请一律用 dialog.width / dialog.height，
    // 否则会把“放不下”误判成“放得下”，右侧内容被裁。
    property int maxWidth: 800
    property int maxHeight: 600
    signal batchAddRequested(var files, string noticeText)

    modal: true
    anchors.centerIn: parent
    width: Math.max(360, Math.min(dialog.maxWidth - 48, 920))
    height: Math.max(420, Math.min(dialog.maxHeight - 72, 760))
    title: "版权提示页管理"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    contentItem: ColumnLayout {
        width: dialog.availableWidth
        spacing: AppStyle.spacingMedium

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            NoticePageSettings {
                width: Math.max(0, dialog.availableWidth - 32)
                cfg: dialog.cfg
                onBatchAddRequested: function(files, noticeText) {
                    dialog.batchAddRequested(files, noticeText)
                }
            }
        }

        // 这个弹窗原先没有关闭按钮，只能按 Esc 或点遮罩退出，
        // 对触屏/不熟悉键盘的用户不友好。
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            Button {
                text: "关闭"
                onClicked: dialog.close()
            }
        }
    }
}
