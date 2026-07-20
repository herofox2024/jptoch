import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property bool busy: false
    property bool readyToStart: false
    property string modelSummary: "-"
    property int failedBlockCount: 0
    property int recentTaskCount: 0

    signal openStatus()
    signal openApi()
    signal openLogs()
    signal openSettings()

    Layout.fillWidth: true
    Layout.preferredHeight: panelColumn.implicitHeight + 28
    radius: AppPalette.radiusLarge
    color: AppPalette.surfaceRaised
    border.color: AppPalette.borderColor

    ColumnLayout {
        id: panelColumn
        anchors.fill: parent
        anchors.margins: 14
        spacing: AppStyle.spacingSmall

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingSmall

            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingNone

                Label {
                    text: "工作流快捷入口"
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontSubHeader
                    font.weight: Font.DemiBold
                }

                Label {
                    Layout.fillWidth: true
                    text: "翻译前先确认模型配置；运行中看状态；失败或残留时看请求日志和设置。"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                Layout.preferredWidth: 118
                Layout.preferredHeight: AppStyle.buttonHeightSmall
                radius: 17
                color: root.busy ? AppStyle.statusAccentBg
                                 : (root.readyToStart ? AppStyle.statusSuccessBg : AppStyle.statusWarningBg)
                border.color: root.busy ? AppPalette.accentColor
                                        : (root.readyToStart ? AppPalette.successColor : AppPalette.amberColor)
                Label {
                    anchors.centerIn: parent
                    text: root.busy ? "运行中" : (root.readyToStart ? "可开始" : "待配置")
                    color: root.busy ? AppPalette.accentColor
                                     : (root.readyToStart ? AppPalette.successColor : AppPalette.amberColor)
                    font.pixelSize: AppStyle.fontCaption
                    font.weight: Font.DemiBold
                }
            }
        }

        Flow {
            Layout.fillWidth: true
            width: parent.width
            spacing: AppStyle.spacingSmall

            ShortcutCard {
                title: "1. 模型配置"
                value: root.modelSummary
                hint: "API、Hy-MT2、预设"
                tone: "accent"
                onClicked: root.openApi()
            }

            ShortcutCard {
                title: "2. 运行状态"
                value: root.busy ? "查看进度" : "准备完成"
                hint: "速度、Token、质量"
                tone: root.busy ? "accent" : "neutral"
                onClicked: root.openStatus()
            }

            ShortcutCard {
                title: "3. 请求日志"
                value: root.failedBlockCount > 0 ? root.failedBlockCount + " 个待处理" : "诊断记录"
                hint: "失败、超时、安全拒绝"
                tone: root.failedBlockCount > 0 ? "warning" : "neutral"
                onClicked: root.openLogs()
            }

            ShortcutCard {
                title: "4. 设置校对"
                value: root.recentTaskCount > 0 ? root.recentTaskCount + " 条任务记录" : "策略与白名单"
                hint: "残留、Prompt、版权页"
                tone: "neutral"
                onClicked: root.openSettings()
            }
        }
    }

    component ShortcutCard: Rectangle {
        id: card
        property string title: ""
        property string value: ""
        property string hint: ""
        property string tone: "neutral"
        property bool hovering: false

        signal clicked()

        width: Math.max(168, Math.min(260, (root.width - 42) / 4))
        height: 82
        radius: AppPalette.radiusMedium
        color: card.hovering ? AppPalette.accentSoft : AppPalette.cardBg
        border.color: card.tone === "warning" ? AppPalette.amberColor
                                             : (card.tone === "accent" ? AppPalette.accentColor : AppPalette.lineColor)
        scale: card.hovering ? 1.012 : 1.0

        Behavior on scale { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: AppStyle.spacingTight

            Label {
                Layout.fillWidth: true
                text: card.title
                color: card.tone === "warning" ? AppPalette.amberColor
                                               : (card.tone === "accent" ? AppPalette.accentColor : AppPalette.textColor)
                font.pixelSize: AppStyle.fontCaption
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Label {
                Layout.fillWidth: true
                text: card.value
                color: AppPalette.textColor
                font.pixelSize: AppStyle.fontBody
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }

            Label {
                Layout.fillWidth: true
                text: card.hint
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontTiny
                elide: Text.ElideRight
            }
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: card.hovering = true
            onExited: card.hovering = false
            onClicked: card.clicked()
        }
    }
}
