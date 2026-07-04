import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import ".."

GroupBox {
    id: root

    property var cfg: null
    readonly property string defaultNoticeText: "本书由 AI日译中(EPUB) V4.1 辅助翻译。\n译文仅供个人学习、研究与阅读辅助使用，请勿传播或用于商业用途。\n请支持并购买正版书籍。"

    signal batchAddRequested(var files, string noticeText)

    title: "版权提示页"
    Layout.fillWidth: true

    ColumnLayout {
        width: parent.width
        spacing: AppStyle.spacingLarge

        CheckBox {
            text: "在输出 EPUB 开头添加版权提示页"
            checked: root.cfg ? root.cfg.enableNoticePage : false
            onCheckedChanged: {
                if (root.cfg) {
                    root.cfg.enableNoticePage = checked
                }
            }
        }

        Rectangle {
            id: noticePageTextBox
            Layout.fillWidth: true
            Layout.preferredHeight: 184
            Layout.minimumHeight: 168
            enabled: root.cfg ? root.cfg.enableNoticePage : false
            clip: true
            radius: AppPalette.radiusMedium
            color: AppPalette.cardAlt
            border.color: noticePageTextEdit.activeFocus ? AppPalette.accentColor : AppPalette.lineColor
            border.width: noticePageTextEdit.activeFocus ? 2 : 1
            opacity: enabled ? 1.0 : 0.72

            ScrollView {
                anchors.fill: parent
                anchors.margins: AppStyle.panelPadding
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                TextEdit {
                    id: noticePageTextEdit
                    width: Math.max(0, noticePageTextBox.width - 36)
                    text: root.cfg ? root.cfg.noticePageText : ""
                    enabled: noticePageTextBox.enabled
                    wrapMode: TextEdit.WordWrap
                    selectByMouse: true
                    color: enabled ? AppPalette.textColor : AppPalette.mutedText
                    selectedTextColor: AppPalette.surfaceRaised
                    selectionColor: AppPalette.accentColor
                    font.pixelSize: AppStyle.fontBody
                    textFormat: TextEdit.PlainText
                    onTextChanged: {
                        if (root.cfg && root.cfg.noticePageText !== text) {
                            root.cfg.noticePageText = text
                        }
                    }
                }
            }

            Label {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: AppStyle.spacingXXLarge
                visible: !noticePageTextEdit.text && !noticePageTextEdit.activeFocus
                text: root.defaultNoticeText
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontBody
                wrapMode: Text.WordWrap
            }
        }

        Button {
            text: "恢复默认提示"
            enabled: root.cfg ? root.cfg.enableNoticePage : false
            Layout.alignment: Qt.AlignLeft
            onClicked: {
                noticePageTextEdit.text = root.defaultNoticeText
                if (root.cfg) {
                    root.cfg.noticePageText = noticePageTextEdit.text
                }
            }
        }

        Button {
            text: "批量添加到已有 EPUB"
            highlighted: true
            Layout.alignment: Qt.AlignLeft
            onClicked: noticeBatchDialog.open()
        }

        Label {
            Layout.fillWidth: true
            text: "提示页会作为独立 XHTML 页面写入，不修改正文内容。批量处理会在原文件旁生成 _notice.epub 副本。"
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            wrapMode: Text.WordWrap
        }
    }

    FileDialog {
        id: noticeBatchDialog
        title: "选择需要添加版权提示页的 EPUB"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.OpenFiles
        onAccepted: root.batchAddRequested(selectedFiles, noticePageTextEdit.text)
    }
}
