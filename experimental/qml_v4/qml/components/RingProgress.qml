import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

/* ============================================================
   RingProgress — 环形进度指示器（Canvas 绘制）

   用法:
     RingProgress { value: 0.42; centerText: "42%" }
   ============================================================ */

Item {
    id: root

    property real value: 0.0          // 0-1
    property real size: 96
    property real strokeWidth: 10
    property string centerText: ""
    property color ringColor: AppPalette.accentColor

    width: size
    height: size

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)

            var cx = width / 2
            var cy = height / 2
            var radius = (width - root.strokeWidth) / 2
            var start = -Math.PI / 2

            // 背景圆环
            ctx.strokeStyle = AppPalette.cardAlt
            ctx.lineWidth = root.strokeWidth
            ctx.lineCap = "round"
            ctx.beginPath()
            ctx.arc(cx, cy, radius, 0, Math.PI * 2)
            ctx.stroke()

            // 进度弧
            if (root.value > 0) {
                var clamped = Math.min(1, Math.max(0, root.value))
                var end = start + Math.PI * 2 * clamped
                ctx.strokeStyle = root.ringColor
                ctx.beginPath()
                ctx.arc(cx, cy, radius, start, end)
                ctx.stroke()
            }
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    Label {
        anchors.centerIn: parent
        text: root.centerText
        color: AppPalette.textColor
        font.pixelSize: AppStyle.fontSubHeader
        font.weight: Font.Bold
    }

    onValueChanged: canvas.requestPaint()
    onRingColorChanged: canvas.requestPaint()
}
