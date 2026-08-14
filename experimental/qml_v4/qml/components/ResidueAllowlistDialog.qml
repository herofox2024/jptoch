import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog

    property var cfg: null
    property string residueAllowlistPath: ""
    property string statusText: ""
    property int pageWidth: 800
    property int pageHeight: 600

    signal countChanged(int count)

    ListModel { id: allowlistModel }

    function refresh() {
        if (!dialog.cfg || !dialog.cfg.getJapaneseResidueAllowlist) {
            dialog.countChanged(0)
            return
        }
        var info = dialog.cfg.getJapaneseResidueAllowlist()
        dialog.residueAllowlistPath = info.path || ""
        allowlistModel.clear()
        var items = info.quoted || []
        for (var i = 0; i < items.length; i++) {
            allowlistModel.append({ "fragment": items[i] })
        }
        dialog.countChanged(allowlistModel.count)
    }

    function addItem() {
        if (!dialog.cfg) return
        var value = residueInput.text.trim()
        if (!value) {
            dialog.statusText = "请输入要放行的片段"
            return
        }
        var result = dialog.cfg.addJapaneseResidueAllowQuoted(value)
        dialog.statusText = result.message || ""
        residueInput.text = ""
        dialog.refresh()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(dialog.statusText) : ToastBridge.showError(dialog.statusText)
        }
    }

    function removeItem(value) {
        if (!dialog.cfg || !value) return
        var result = dialog.cfg.removeJapaneseResidueAllowQuoted(value)
        dialog.statusText = result.message || ""
        dialog.refresh()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(dialog.statusText) : ToastBridge.showError(dialog.statusText)
        }
    }

    onOpened: dialog.refresh()

    modal: true
    anchors.centerIn: parent
    width: Math.max(360, Math.min(dialog.pageWidth - 48, 920))
    height: Math.max(420, Math.min(dialog.pageHeight - 72, 720))
    title: "日文残留白名单"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    contentItem: ScrollView {
        width: dialog.width
        height: dialog.height
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, dialog.width - 32)
            spacing: AppStyle.spacingLarge

            Label {
                Layout.fillWidth: true
                text: "仅在确认片段确实需要保留日文时使用。这里添加的是“引号内片段白名单”，例如译文中的 “レディス” 会放行，但正文其他位置的日文仍会继续被拦截。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                Label {
                    text: "文件"
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontSmall
                    font.weight: Font.DemiBold
                }

                TextField {
                    Layout.fillWidth: true
                    text: dialog.residueAllowlistPath
                    readOnly: true
                    selectByMouse: true
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontCaption
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                TextField {
                    id: residueInput
                    Layout.fillWidth: true
                    placeholderText: "输入保存前提示里的片段，例如 レディス"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }

                Button {
                    text: "加入白名单"
                    highlighted: true
                    onClicked: dialog.addItem()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(86, Math.min(190, allowlistModel.count * 38 + 18))
                radius: AppPalette.radiusMedium
                color: AppPalette.cardAlt
                border.color: AppPalette.lineColor
                clip: true

                ListView {
                    id: allowList
                    anchors.fill: parent
                    anchors.margins: 8
                    model: allowlistModel
                    spacing: AppStyle.spacingInline
                    clip: true

                    delegate: Rectangle {
                        width: allowList.width
                        height: 32
                        radius: 10
                        color: AppPalette.surfaceRaised
                        border.color: AppPalette.lineColor

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 6
                            spacing: AppStyle.spacingSmall

                            Label {
                                Layout.fillWidth: true
                                text: fragment
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontBody
                                elide: Text.ElideRight
                            }

                            Button {
                                text: "删除"
                                flat: true
                                onClicked: dialog.removeItem(fragment)
                            }
                        }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: allowlistModel.count === 0
                    text: "暂无白名单片段"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                }
            }

            Label {
                Layout.fillWidth: true
                text: dialog.statusText
                visible: dialog.statusText !== ""
                color: dialog.statusText.indexOf("失败") >= 0 || dialog.statusText.indexOf("请输入") >= 0
                       ? AppPalette.errorColor : AppPalette.successColor
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

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
}
