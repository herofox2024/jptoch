import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property int completed: 0
    property int total: 0
    property int failed: 0
    property int warnings: 0
    property int maxCells: 720
    property string title: "文本块进度"

    readonly property real ratio: total > 0 ? Math.max(0, Math.min(1, completed / total)) : 0
    readonly property int displayCells: total > 0 ? Math.max(1, Math.min(maxCells, total)) : 0

    radius: AppPalette.radiusMedium
    color: AppPalette.surfaceRaised
    border.color: AppPalette.lineColor
    clip: true

    onCompletedChanged: blockCanvas.requestPaint()
    onTotalChanged: blockCanvas.requestPaint()
    onFailedChanged: blockCanvas.requestPaint()
    onWarningsChanged: blockCanvas.requestPaint()
    onWidthChanged: blockCanvas.requestPaint()
    onHeightChanged: blockCanvas.requestPaint()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: AppStyle.spacingLarge
        spacing: AppStyle.spacingMedium

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingMedium

            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingTight

                Label {
                    text: root.title
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontSubSection
                    font.weight: Font.DemiBold
                }

                Label {
                    Layout.fillWidth: true
                    text: root.total > 0
                          ? (root.completed + " / " + root.total + "，压缩显示 " + root.displayCells + " 个色块")
                          : "等待翻译任务开始"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    elide: Text.ElideRight
                }
            }

            Rectangle {
                Layout.preferredWidth: 84
                Layout.preferredHeight: AppStyle.buttonHeightSmall
                radius: 17
                color: AppPalette.accentSoft
                border.color: AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: Math.round(root.ratio * 100) + "%"
                    color: AppPalette.accentColor
                    font.pixelSize: AppStyle.fontSmall
                    font.weight: Font.DemiBold
                }
            }
        }

        Canvas {
            id: blockCanvas
            Layout.fillWidth: true
            Layout.fillHeight: true
            antialiasing: false

            onPaint: {
                var ctx = getContext("2d")
                ctx.clearRect(0, 0, width, height)

                var cells = root.displayCells
                if (cells <= 0) {
                    ctx.fillStyle = AppPalette.fieldBg
                    ctx.fillRect(0, 0, width, height)
                    return
                }

                var gap = width < 520 ? 3 : 4
                var minCell = width < 520 ? 7 : 9
                var columns = Math.max(1, Math.floor((width + gap) / (minCell + gap)))
                columns = Math.min(columns, cells)
                var rows = Math.ceil(cells / columns)
                var cellW = Math.max(4, Math.floor((width - gap * (columns - 1)) / columns))
                var cellH = Math.max(4, Math.floor((height - gap * (rows - 1)) / rows))
                var size = Math.max(4, Math.min(cellW, cellH, 15))
                var usedW = columns * size + (columns - 1) * gap
                var startX = Math.max(0, Math.floor((width - usedW) / 2))
                var doneCells = Math.floor(root.ratio * cells)
                var hasCurrent = root.completed > 0 && root.completed < root.total
                var failedCells = root.total > 0 ? Math.ceil(Math.min(root.failed, root.total) / root.total * cells) : 0
                var warningCells = root.total > 0 ? Math.ceil(Math.min(root.warnings, root.total) / root.total * cells) : 0

                for (var i = 0; i < cells; i++) {
                    var row = Math.floor(i / columns)
                    var col = i % columns
                    var x = startX + col * (size + gap)
                    var y = row * (size + gap)
                    var color = AppPalette.fieldBg

                    if (i < doneCells) color = AppPalette.successColor
                    if (hasCurrent && i === doneCells) color = AppPalette.accentColor
                    if (warningCells > 0 && i >= cells - warningCells - failedCells && i < cells - failedCells) color = AppPalette.amberColor
                    if (failedCells > 0 && i >= cells - failedCells) color = AppPalette.errorColor

                    ctx.fillStyle = color
                    ctx.globalAlpha = i < doneCells || (hasCurrent && i === doneCells) ? 0.95 : 0.55
                    ctx.fillRect(x, y, size, size)
                }
                ctx.globalAlpha = 1
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingLarge

            Repeater {
                model: [
                    {"label": "已完成", "color": AppPalette.successColor},
                    {"label": "当前", "color": AppPalette.accentColor},
                    {"label": "待处理", "color": AppPalette.fieldBg},
                    {"label": "警告", "color": AppPalette.amberColor},
                    {"label": "失败", "color": AppPalette.errorColor}
                ]

                RowLayout {
                    spacing: AppStyle.spacingInline
                    Rectangle {
                        Layout.preferredWidth: 10
                        Layout.preferredHeight: 10
                        radius: 2
                        color: modelData.color
                        border.color: AppPalette.lineColor
                    }
                    Label {
                        text: modelData.label
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontCaption
                    }
                }
            }

            Item { Layout.fillWidth: true }
        }
    }
}
