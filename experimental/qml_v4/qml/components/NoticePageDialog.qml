import QtQuick
import QtQuick.Controls
import ".."

Dialog {
    id: dialog

    property var cfg: null
    property int pageWidth: 800
    property int pageHeight: 600
    signal batchAddRequested(var files, string noticeText)

    modal: true
    anchors.centerIn: parent
    width: Math.max(360, Math.min(dialog.pageWidth - 48, 920))
    height: Math.max(420, Math.min(dialog.pageHeight - 72, 760))
    title: "版权提示页管理"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    contentItem: ScrollView {
        width: dialog.width
        height: dialog.height
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        NoticePageSettings {
            width: Math.max(0, dialog.width - 32)
            cfg: dialog.cfg
            onBatchAddRequested: function(files, noticeText) {
                dialog.batchAddRequested(files, noticeText)
            }
        }
    }
}
