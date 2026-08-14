import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog

    property var cfg: null
    property string knownKatakanaTermsPath: ""
    property string statusText: ""
    property int pageWidth: 800
    property int pageHeight: 600

    signal countChanged(int count)

    ListModel { id: termsModel }

    function refresh() {
        if (!dialog.cfg || !dialog.cfg.getKnownKatakanaTerms) {
            dialog.countChanged(0)
            return
        }
        var info = dialog.cfg.getKnownKatakanaTerms()
        dialog.knownKatakanaTermsPath = info.path || ""
        termsModel.clear()
        var items = info.items || []
        for (var i = 0; i < items.length; i++) {
            termsModel.append({
                "source": items[i].source || "",
                "target": items[i].target || "",
                "builtin": !!items[i].builtin
            })
        }
        dialog.countChanged(termsModel.count)
    }

    function addItem() {
        if (!dialog.cfg) return
        var source = sourceInput.text.trim()
        var target = targetInput.text.trim()
        var result = dialog.cfg.addKnownKatakanaTerm(source, target)
        dialog.statusText = result.message || ""
        if (result.ok) {
            sourceInput.text = ""
            targetInput.text = ""
        }
        dialog.refresh()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(dialog.statusText) : ToastBridge.showError(dialog.statusText)
        }
    }

    function removeItem(source) {
        if (!dialog.cfg || !source) return
        var result = dialog.cfg.removeKnownKatakanaTerm(source)
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
    height: Math.max(460, Math.min(dialog.pageHeight - 72, 780))
    title: "片假名术语修复词表"
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
                text: "用于处理模型已经翻译出中文解释、但仍残留片假名原词的情况。例如“チロリ的酒”会在保存前自动修复为“烫酒壶里的酒”。这类词应加入修复词表，不要加入日文残留白名单。"
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
                    text: dialog.knownKatakanaTermsPath
                    readOnly: true
                    selectByMouse: true
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontCaption
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: dialog.pageWidth > 820 ? 5 : 2
                rowSpacing: 8
                columnSpacing: 12

                Label { text: "片假名原词" }
                TextField {
                    id: sourceInput
                    Layout.fillWidth: true
                    placeholderText: "例如 チロリ"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }

                Label { text: "中文译名" }
                TextField {
                    id: targetInput
                    Layout.fillWidth: true
                    placeholderText: "例如 烫酒壶"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }

                Button {
                    text: "保存修复词"
                    highlighted: true
                    Layout.fillWidth: dialog.pageWidth <= 820
                    onClicked: dialog.addItem()
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.max(96, Math.min(220, termsModel.count * 40 + 18))
                radius: AppPalette.radiusMedium
                color: AppPalette.cardAlt
                border.color: AppPalette.lineColor
                clip: true

                ListView {
                    id: termsList
                    anchors.fill: parent
                    anchors.margins: 8
                    model: termsModel
                    spacing: AppStyle.spacingInline
                    clip: true

                    delegate: Rectangle {
                        width: termsList.width
                        height: 34
                        radius: 10
                        color: AppPalette.surfaceRaised
                        border.color: AppPalette.lineColor

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 6
                            spacing: AppStyle.spacingSmall

                            Label {
                                Layout.preferredWidth: 140
                                text: source
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontBody
                                elide: Text.ElideRight
                            }

                            Label {
                                text: "→"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                            }

                            Label {
                                Layout.fillWidth: true
                                text: target + (builtin ? "（内置）" : "")
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontBody
                                elide: Text.ElideRight
                            }

                            Button {
                                text: builtin ? "内置" : "删除"
                                flat: true
                                enabled: !builtin
                                onClicked: dialog.removeItem(source)
                            }
                        }
                    }
                }

                Label {
                    anchors.centerIn: parent
                    visible: termsModel.count === 0
                    text: "暂无修复词"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                }
            }

            Label {
                Layout.fillWidth: true
                text: dialog.statusText
                visible: dialog.statusText !== ""
                color: dialog.statusText.indexOf("失败") >= 0
                       || dialog.statusText.indexOf("请输入") >= 0
                       || dialog.statusText.indexOf("需要") >= 0
                       || dialog.statusText.indexOf("不能") >= 0
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
