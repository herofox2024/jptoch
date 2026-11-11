import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import ".."

Dialog {
    objectName: "knownKatakanaDialog"
    id: dialog

    property var cfg: null
    property string knownKatakanaTermsPath: ""
    property string statusText: ""
        // 调用方提供的可用尺寸上限（通常是所在页面的宽高）。
    // 注意：它**不是**弹窗自身尺寸 —— 布局判断请一律用 dialog.width / dialog.height，
    // 否则会把“放不下”误判成“放得下”，右侧内容被裁。
    property int maxWidth: 800
    property int maxHeight: 600

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

    // 单行 / 双行两套输入框，取当前可见的那一组。
    function activeSourceField() {
        return dialog.singleRowLayout ? sourceInputWide : sourceInputNarrow
    }

    function activeTargetField() {
        return dialog.singleRowLayout ? targetInputWide : targetInputNarrow
    }

    function addItem() {
        if (!dialog.cfg) return
        var sourceField = dialog.activeSourceField()
        var targetField = dialog.activeTargetField()
        var source = sourceField.text.trim()
        var target = targetField.text.trim()
        var result = dialog.cfg.addKnownKatakanaTerm(source, target)
        dialog.statusText = result.message || ""
        if (result.ok) {
            sourceField.text = ""
            targetField.text = ""
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
    width: Math.max(360, Math.min(dialog.maxWidth - 48, 920))
    height: Math.max(460, Math.min(dialog.maxHeight - 72, 780))
    title: "片假名术语修复词表"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    padding: 0
    topPadding: 0
    bottomPadding: 0
    leftPadding: 0
    rightPadding: 0
    // Dialog 默认有 padding，会把 contentItem 挤小；这里全部归零，
    // 由 contentItem 自己控制内距，避免出现「width=920 但实际只有 720」。

    // 是否单行布局，看的是**弹窗自己的宽度**，不是调用方给的 maxWidth。
    // 原来用 maxWidth（整页宽，约 1240）判断 > 820 走单行，
    // 但弹窗最宽只有 920，减去边距后放不下「原词+译名+按钮」，
    // 结果最右侧的「保存修复词」被裁掉。
    readonly property bool singleRowLayout: dialog.width >= 760

    contentItem: ScrollView {
        // 尺寸交给 Dialog 的 contentWidth/contentHeight 管理，
        // 自己写 width/height = dialog.width 会与 Dialog 的 padding 打架。
        id: knownKatakanaScroll
            implicitWidth: dialog.availableWidth
        implicitHeight: dialog.availableHeight
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        // 宽度取 ScrollView 的可用宽度，而不是 dialog.width 减写死值：
        // 垂直滚动条出现时会再占十几像素，写死会让内容比可视区宽、右侧被裁。
        ColumnLayout {
            width: Math.max(0, knownKatakanaScroll.availableWidth)
            x: 16
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

            // 单行：原词 | 译名 | 按钮
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: dialog.singleRowLayout ? implicitHeight : 0
                visible: dialog.singleRowLayout
                spacing: AppStyle.spacingSmall

                Label { text: "片假名原词"; Layout.alignment: Qt.AlignVCenter }
                TextField {
                    id: sourceInputWide
                    Layout.fillWidth: true
                    Layout.minimumWidth: 120
                    placeholderText: "例如 チロリ"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }
                Label { text: "中文译名"; Layout.alignment: Qt.AlignVCenter }
                TextField {
                    id: targetInputWide
                    Layout.fillWidth: true
                    Layout.minimumWidth: 120
                    placeholderText: "例如 烫酒壶"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }
                Button {
                    text: "保存修复词"
                    // 主操作需要强调色。Dialog 不在 ApplicationWindow 的
                    // Material 作用域内，highlighted 会退回 Material 默认品红；
                    // 这里显式给出 Material.accent，让 highlighted 用品牌青绿。
                    highlighted: true
                    Material.accent: AppPalette.accentColor
                    Material.foreground: AppStyle.primaryOnAccent
                    Layout.preferredWidth: Math.max(96, implicitWidth)
                    onClicked: dialog.addItem()
                }
            }

            // 窄弹窗：标签与输入框两列，按钮独占一行。
            GridLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: !dialog.singleRowLayout ? implicitHeight : 0
                visible: !dialog.singleRowLayout
                columns: 2
                rowSpacing: 8
                columnSpacing: 12

                Label { text: "片假名原词"; Layout.alignment: Qt.AlignVCenter }
                TextField {
                    id: sourceInputNarrow
                    Layout.fillWidth: true
                    Layout.minimumWidth: 120
                    placeholderText: "例如 チロリ"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }

                Label { text: "中文译名"; Layout.alignment: Qt.AlignVCenter }
                TextField {
                    id: targetInputNarrow
                    Layout.fillWidth: true
                    Layout.minimumWidth: 120
                    placeholderText: "例如 烫酒壶"
                    selectByMouse: true
                    onAccepted: dialog.addItem()
                }

                Button {
                    text: "保存修复词"
                    Layout.fillWidth: true
                    Layout.columnSpan: 2
                    // 同单行布局：补上 Material.accent，让 highlighted 用品牌色。
                    highlighted: true
                    Material.accent: AppPalette.accentColor
                    Material.foreground: AppStyle.primaryOnAccent
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
                        radius: AppStyle.radiusButton
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
