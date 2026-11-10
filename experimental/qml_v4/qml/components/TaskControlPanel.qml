import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property bool readyToStart: false
    property bool busy: false
    property int maxWorkers: 0
    property int batchSize: 0
    property int maxTextSizeForBatch: 0
    property real viewportWidth: width
    property string modelSummary: "--"
    property string statusText: "等待任务"

    signal startRequested()
    signal pauseRequested()
    signal resumeRequested()
    signal stopRequested()
    signal clearCacheRequested()
    signal manualEditRequested()
    signal statusRequested()

    // 供窗口级快捷键（Ctrl+Shift+X）调用：与「停止」按钮共用同一套确认流程，
    // 避免快捷键绕过二次确认直接清空缓存。
    function requestStop() {
        if (!root.busy) return
        stopConfirmDialog.open()
    }

    // 暴露确认框状态，便于自动化测试断言（Dialog 会被挂到 Overlay，findChild 找不到）。
    property alias stopConfirmVisible: stopConfirmDialog.visible

    Layout.fillWidth: true
    Layout.preferredHeight: viewportWidth > AppStyle.bpSmall ? 336 : 418
    radius: AppPalette.radiusLarge
    color: AppPalette.glass ? Qt.rgba(1, 1, 1, 0.48) : AppPalette.surfaceRaised
    border.color: AppPalette.borderColor
    clip: true

    function valueOrDash(value) {
        return value !== undefined && value !== null && value !== "" ? value : "--"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: AppStyle.spacingSmall

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingMedium

            Label {
                Layout.fillWidth: true
                text: "准备翻译"
                color: AppPalette.textColor
                font.pixelSize: AppStyle.fontSubHeader
                font.weight: Font.DemiBold
            }

            Rectangle {
                Layout.preferredWidth: 86
                Layout.preferredHeight: 24
                radius: 12
                color: root.readyToStart ? AppPalette.cardBg : AppStyle.statusNeutralBg
                border.color: AppPalette.lineColor

                Label {
                    anchors.centerIn: parent
                    text: root.readyToStart ? "可开始" : "待选择"
                    color: root.readyToStart ? AppPalette.successColor : AppPalette.mutedText
                    font.pixelSize: AppStyle.fontCaption
                    font.weight: Font.DemiBold
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: root.viewportWidth > AppStyle.bpSmall ? 180 : 240
            spacing: AppStyle.spacingMedium

            TaskActionButton {
                Layout.fillWidth: true
                Layout.preferredHeight: AppStyle.buttonHeightPrimary
                primary: true
                label: root.busy ? "翻译中..." : "开始翻译"
                hint: root.readyToStart ? "使用当前模型与参数启动任务" : "请先选择源文件和输出文件"
                enabled: root.readyToStart && !root.busy
                onClicked: root.startRequested()
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                RowLayout {
                    Layout.fillWidth: true

                    Label {
                        Layout.fillWidth: true
                        text: root.statusText
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontCaption
                        elide: Text.ElideRight
                    }
                    ToolButton {
                        text: "查看状态"
                        onClicked: root.statusRequested()
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingMedium

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.viewportWidth > AppStyle.bpWide ? 5 : (root.viewportWidth > AppStyle.bpCompact ? 3 : 2)
                    columnSpacing: AppStyle.spacingMedium
                    rowSpacing: AppStyle.spacingMedium

                    TaskActionButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: AppStyle.buttonHeightNormal
                        label: "暂停"
                        hint: "保留已写入缓存"
                        enabled: root.busy
                        onClicked: root.pauseRequested()
                    }

                    TaskActionButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: AppStyle.buttonHeightNormal
                        label: "恢复"
                        hint: "继续断点任务"
                        enabled: root.readyToStart && !root.busy
                        onClicked: root.resumeRequested()
                    }

                    // 「停止」会取消任务并丢弃本次已翻译缓存，属于不可撤销操作，
                    // 因此必须先确认；Ctrl+Shift+X 快捷键同样走这里。
                    TaskActionButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: AppStyle.buttonHeightNormal
                        label: "停止"
                        hint: "取消并清空本次缓存"
                        danger: true
                        enabled: root.busy
                        onClicked: stopConfirmDialog.open()
                    }

                    TaskActionButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: AppStyle.buttonHeightNormal
                        label: "清缓存"
                        hint: "重新翻译当前书"
                        enabled: root.readyToStart && !root.busy
                        onClicked: root.clearCacheRequested()
                    }

                    TaskActionButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: AppStyle.buttonHeightNormal
                        label: "人工修改"
                        hint: "编辑单条译文"
                        enabled: !root.busy
                        onClicked: root.manualEditRequested()
                    }
                }
            }

            Flow {
                Layout.fillWidth: true
                spacing: AppStyle.spacingInline

                SummaryChip { title: "模型"; value: root.modelSummary }
                SummaryChip { title: "并发"; value: root.valueOrDash(root.maxWorkers) }
                SummaryChip { title: "批量"; value: root.valueOrDash(root.batchSize) }
                SummaryChip { title: "单条上限"; value: root.valueOrDash(root.maxTextSizeForBatch) }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(AppStyle.infoBarHeight, infoBarText.paintedHeight + 18)
            Layout.bottomMargin: 2
            radius: 22
            color: AppPalette.fieldBg
            border.color: AppPalette.lineColor

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 10
                anchors.topMargin: 6
                anchors.bottomMargin: 6
                spacing: AppStyle.spacingMedium

                Rectangle {
                    Layout.preferredWidth: 8
                    Layout.preferredHeight: 8
                    radius: 4
                    color: root.readyToStart ? AppPalette.successColor : AppPalette.amberColor
                }

                Label {
                    id: infoBarText
                    Layout.fillWidth: true
                    text: "暂停会保留已写入缓存的内容，切换模型后点“恢复”可续译；停止会取消任务并清空本次已翻译缓存。"
                    color: AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontCaption
                    maximumLineCount: 2
                    elide: Text.ElideRight
                }

                Rectangle {
                    visible: root.viewportWidth > AppStyle.bpNarrow
                    Layout.preferredWidth: 104
                    Layout.preferredHeight: AppStyle.buttonHeightCompact
                    radius: 14
                    color: root.readyToStart ? AppPalette.accentSoft : AppStyle.statusNeutralBg
                    border.color: AppPalette.lineColor

                    Label {
                        anchors.centerIn: parent
                        text: root.readyToStart ? "工作台已就绪" : "等待文件"
                        color: root.readyToStart ? AppPalette.successColor : AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
                        font.weight: Font.DemiBold
                    }
                }
            }
        }
    }

    // 「停止」二次确认：该操作会丢弃本次已翻译缓存，无法撤销。
    Dialog {
        id: stopConfirmDialog
        objectName: "stopConfirmDialog"
        modal: true
        anchors.centerIn: parent
        width: Math.min(root.width - 96, 460)
        title: "确认停止翻译？"
        closePolicy: Popup.CloseOnEscape

        contentItem: ColumnLayout {
            width: stopConfirmDialog.availableWidth
            spacing: AppStyle.spacingLarge

            Label {
                Layout.fillWidth: true
                text: "停止会立即取消当前任务，并清空本次已翻译的缓存内容。"
                color: AppPalette.textColor
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontBody
            }

            Label {
                Layout.fillWidth: true
                text: "已保存到输出 EPUB 的部分不受影响；如需保留进度，请改用“暂停”。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingMedium

                Item { Layout.fillWidth: true }

                Button {
                    text: "继续翻译"
                    onClicked: stopConfirmDialog.close()
                }

                Button {
                    text: "停止并清空缓存"
                    highlighted: true
                    onClicked: {
                        stopConfirmDialog.close()
                        root.stopRequested()
                    }
                }
            }
        }
    }
}
