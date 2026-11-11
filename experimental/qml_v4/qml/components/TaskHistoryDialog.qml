import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    objectName: "taskHistoryDialog"
    id: dialog

    property var taskHistory: []
    property var latestUnfinishedTask: ({})
    property bool busy: false
    property int pageWidth: 800
    property int pageHeight: 600

    signal refreshRequested()
    signal clearRequested()
    signal resumeLatestRequested()
    signal loadRecordRequested(var record)

    title: "最近任务"
    modal: true
    // 用 anchors.centerIn 让 Controls 自己处理居中（它会挂在 Overlay 上）。
    // 不要再手算 x/y：pageWidth 传进来的是页面宽度而非窗口宽度，手算会偏。
    anchors.centerIn: parent
    // 最小宽度必须让位于窗口：窄窗口下 720 会把弹窗撑出屏幕边界。
    width: Math.max(360, Math.min(980, dialog.pageWidth - 48))
    height: Math.max(360, Math.min(640, dialog.pageHeight - 72))
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function taskStatusLabel(status) {
        var value = String(status || "")
        if (value === "completed") return "已完成"
        if (value === "running") return "运行中"
        if (value === "paused") return "可续译"
        if (value === "pausing") return "暂停中"
        if (value === "stopping") return "停止中"
        if (value === "stopped") return "已停止"
        if (value === "cancelled") return "已取消"
        if (value === "cancelling") return "取消中"
        if (value === "failed") return "失败"
        return value || "-"
    }

    function taskStatusColor(status) {
        var value = String(status || "")
        if (value === "completed") return AppPalette.successColor
        if (value === "running" || value === "pausing" || value === "stopping" || value === "cancelling") return AppPalette.accentColor
        if (value === "paused") return AppPalette.amberColor
        if (value === "failed") return AppPalette.errorColor
        return AppPalette.mutedText
    }

    function taskProgressText(record) {
        if (!record) return "-"
        var completed = Number(record.completed_texts || 0)
        var total = Number(record.total_texts || 0)
        if (total > 0) return completed + "/" + total
        var progress = Number(record.progress || 0)
        if (progress > 0) return Math.round(progress * 100) + "%"
        return "-"
    }

    function taskTimeText(seconds) {
        var value = Number(seconds || 0)
        if (value <= 0) return "-"
        return Qt.formatDateTime(new Date(value * 1000), "MM-dd hh:mm")
    }

    ColumnLayout {
        width: dialog.width - 48
        spacing: AppStyle.spacingSmall

        Label {
            Layout.fillWidth: true
            text: "记录最近翻译任务的状态、进度和输入输出路径；API Key 不会写入历史。"
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            wrapMode: Text.WordWrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingSmall

            Button {
                text: "刷新"
                onClicked: dialog.refreshRequested()
            }

            Button {
                text: "清空"
                enabled: dialog.taskHistory.length > 0 && !dialog.busy
                onClicked: dialog.clearRequested()
            }

            Button {
                text: "继续上次"
                enabled: !dialog.busy && !!(dialog.latestUnfinishedTask && dialog.latestUnfinishedTask.task_id)
                highlighted: enabled
                onClicked: dialog.resumeLatestRequested()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "关闭"
                onClicked: dialog.close()
            }
        }

        EmptyState {
            Layout.fillWidth: true
            visible: dialog.taskHistory.length === 0
            iconName: "task"
            description: "暂无任务历史。开始一次翻译后，这里会显示可追踪记录。"
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
                model: dialog.taskHistory

                delegate: Rectangle {
                    width: ListView.view.width
                    // 行高取决于列是否收成两行，跟随弹窗自身宽度。
                    height: dialog.width > 720 ? 42 : 58
                    radius: AppPalette.radiusMedium
                    color: AppPalette.fieldBg
                    border.color: AppPalette.lineColor

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 8
                        spacing: AppStyle.spacingSmall

                        Rectangle {
                            Layout.preferredWidth: 8
                            Layout.preferredHeight: 8
                            radius: AppStyle.radiusTiny
                            color: dialog.taskStatusColor(modelData.status)
                        }

                        Label {
                            Layout.preferredWidth: 72
                            text: dialog.taskStatusLabel(modelData.status)
                            color: dialog.taskStatusColor(modelData.status)
                            font.pixelSize: AppStyle.fontCaption
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        Label {
                            Layout.preferredWidth: 68
                            text: dialog.taskProgressText(modelData)
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontCaption
                            elide: Text.ElideRight
                        }

                        Label {
                            Layout.fillWidth: true
                            text: FilePathUtils.fileName(modelData.input_path || "")
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontCaption
                            elide: Text.ElideMiddle
                        }

                        // 用弹窗自身宽度判断，而不是 pageWidth（宿主窗口宽）。
                        // pageWidth 通常远大于弹窗实际宽度，会把本该收起的列判成
                        // “放得下”，导致右侧列被挤压甚至裁切。
                        Label {
                            visible: dialog.width > 720
                            Layout.preferredWidth: 190
                            text: (modelData.provider || "-") + " / " + (modelData.model || "-")
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontTiny
                            elide: Text.ElideRight
                        }

                        Label {
                            visible: dialog.width > 860
                            Layout.preferredWidth: 108
                            text: dialog.taskTimeText(modelData.updated_at || modelData.started_at || modelData.created_at)
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontTiny
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideRight
                        }

                        Button {
                            text: "载入"
                            enabled: !dialog.busy
                            onClicked: dialog.loadRecordRequested(modelData)
                        }
                    }
                }
            }
        }
    }
}
