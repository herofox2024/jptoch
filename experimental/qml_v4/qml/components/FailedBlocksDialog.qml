import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog

    property var latestFailedBlocks: []
    property var latestUnfinishedTask: ({})
    property bool busy: false
    property int providerModeIndex: 0
    property string recoveryAnalysisMessage: ""
    property int pageWidth: 800
    property int pageHeight: 600

    signal analyzeRequested()
    signal providerModeChanged(int index)
    signal retranslateRequested()
    signal navigateToLogsRequested()
    signal manualEditRequested(string text, string translation)

    onOpened: dialog.analyzeRequested()
    title: "失败块 / 日文残留"
    modal: true
    width: Math.max(760, Math.min(1040, dialog.pageWidth - 48))
    height: Math.max(460, Math.min(700, dialog.pageHeight - 72))
    x: Math.round((dialog.pageWidth - width) / 2)
    y: Math.round((dialog.pageHeight - height) / 2)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function failedBlockKindLabel(kind) {
        var value = String(kind || "")
        if (value === "failed") return "未译"
        if (value === "residue") return "残留"
        if (value === "save_residue") return "保存前"
        return "问题"
    }

    function failedBlockText(block) {
        if (!block) return "-"
        var fragments = block.fragments && block.fragments.length > 0 ? (" [" + block.fragments.join(" / ") + "] ") : ""
        var text = block.text || block.translation || "-"
        return fragments + text
    }

    ColumnLayout {
        width: dialog.width - 48
        spacing: AppStyle.spacingSmall

        Label {
            Layout.fillWidth: true
            text: "可自动重译未译/残留块；保存前残留样例仍建议人工定位或继续整本续译。"
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            wrapMode: Text.WordWrap
        }

        Label {
            Layout.fillWidth: true
            text: {
                var summary = (dialog.latestUnfinishedTask || {}).recovery_summary || {}
                return "恢复统计：尝试 " + Number(summary.attempted || 0) +
                       "，成功 " + Number(summary.success || 0) +
                       "，待复核 " + Number(summary.needs_review || 0) +
                       "，失败 " + Number(summary.failed || 0)
            }
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontTiny
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingSmall

            Button {
                text: "生成恢复建议"
                enabled: !dialog.busy && dialog.latestFailedBlocks.length > 0
                onClicked: dialog.analyzeRequested()
            }

            ComboBox {
                Layout.preferredWidth: 116
                model: ["当前模型", "校对模型"]
                currentIndex: dialog.providerModeIndex
                onActivated: dialog.providerModeChanged(currentIndex)
            }

            Button {
                text: "重译失败块"
                enabled: !dialog.busy && dialog.latestFailedBlocks.length > 0
                highlighted: enabled
                onClicked: dialog.retranslateRequested()
            }

            Button {
                text: "查看请求日志"
                onClicked: dialog.navigateToLogsRequested()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "关闭"
                onClicked: dialog.close()
            }
        }

        Label {
            Layout.fillWidth: true
            visible: dialog.recoveryAnalysisMessage !== ""
            text: dialog.recoveryAnalysisMessage
            color: AppPalette.accentColor
            font.pixelSize: AppStyle.fontSmall
            wrapMode: Text.WordWrap
        }

        Label {
            Layout.fillWidth: true
            visible: dialog.latestFailedBlocks.length === 0
            text: "当前没有失败块或保存前残留记录。"
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            wrapMode: Text.WordWrap
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AsNeeded
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ListView {
                width: parent.width
                height: Math.max(0, contentHeight)
                spacing: AppStyle.spacingSmall
                model: dialog.latestFailedBlocks

                delegate: Rectangle {
                    width: ListView.view.width
                    height: dialog.pageWidth > AppStyle.bpSmall ? 60 : 78
                    radius: AppPalette.radiusSmall
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.lineColor

                    RowLayout {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        height: 32
                        anchors.leftMargin: 8
                        anchors.rightMargin: 6
                        spacing: AppStyle.spacingSmall

                        Label {
                            Layout.preferredWidth: 76
                            text: dialog.failedBlockKindLabel(modelData.kind)
                            color: modelData.kind === "save_residue" ? AppPalette.errorColor : AppPalette.amberColor
                            font.pixelSize: AppStyle.fontTiny
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Label {
                            Layout.fillWidth: true
                            text: dialog.failedBlockText(modelData)
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontTiny
                            elide: Text.ElideRight
                        }

                        Button {
                            text: modelData.kind === "save_residue" ? "定位" : "人工修正"
                            enabled: !dialog.busy
                            onClicked: dialog.manualEditRequested(modelData.text || "", modelData.translation || "")
                        }
                    }

                    Label {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 8
                        anchors.rightMargin: 8
                        anchors.bottomMargin: 5
                        text: {
                            var issue = modelData.recovery_issue || {}
                            var decision = modelData.recovery_decision || {}
                            var attempts = Number(modelData.recovery_attempts || 0)
                            return (issue.issue_type || "未分类") + " | " +
                                   (decision.action || "未分析") + " | " +
                                   (modelData.recovery_recommendation || "等待人工确认") +
                                   " | 已尝试 " + attempts + " 次"
                        }
                        color: modelData.recovery_status === "success" ? AppPalette.successColor : AppPalette.mutedText
                        font.pixelSize: AppStyle.fontTiny
                        elide: Text.ElideRight
                    }
                }
            }
        }
    }
}
