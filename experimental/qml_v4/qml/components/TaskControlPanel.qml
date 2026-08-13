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
    property real progressValue: 0
    property string statusText: "等待任务"

    signal startRequested()
    signal pauseRequested()
    signal resumeRequested()
    signal stopRequested()
    signal clearCacheRequested()
    signal manualEditRequested()

    Layout.fillWidth: true
    Layout.preferredHeight: viewportWidth > 900 ? 370 : 452
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
            Layout.preferredHeight: root.viewportWidth > 900 ? 168 : 256
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

            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingInline
                RowLayout {
                    Layout.fillWidth: true
                    Label {
                        Layout.fillWidth: true
                        text: root.statusText
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontCaption
                        elide: Text.ElideRight
                    }
                    Label {
                        text: Math.round(Math.max(0, Math.min(1, root.progressValue)) * 100) + "%"
                        color: AppPalette.accentColor
                        font.pixelSize: AppStyle.fontCaption
                        font.weight: Font.DemiBold
                    }
                }
                ProgressBar {
                    Layout.fillWidth: true
                    from: 0
                    to: 1
                    value: Math.max(0, Math.min(1, root.progressValue))
                    background: Rectangle { implicitHeight: 6; radius: 3; color: AppPalette.cardAlt }
                    contentItem: Item {
                        implicitHeight: 6
                        Rectangle {
                            width: parent.width * root.progressValue
                            height: parent.height
                            radius: 3
                            gradient: Gradient {
                                orientation: Gradient.Horizontal
                                GradientStop { position: 0.0; color: "#635bff" }
                                GradientStop { position: 1.0; color: "#0088ff" }
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingMedium

                GridLayout {
                    Layout.fillWidth: true
                    columns: root.viewportWidth > 980 ? 5 : (root.viewportWidth > 680 ? 3 : 2)
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

                    TaskActionButton {
                        Layout.fillWidth: true
                        Layout.preferredHeight: AppStyle.buttonHeightNormal
                        label: "停止"
                        hint: "取消并清空本次缓存"
                        danger: true
                        enabled: root.busy
                        onClicked: root.stopRequested()
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
                    visible: root.viewportWidth > 880
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
}
