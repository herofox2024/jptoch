import QtQuick

Item {
    id: navIcon
    property string name: "task"
    property color lineColor: "white"

    Canvas {
        id: iconCanvas
        anchors.fill: parent
        antialiasing: true

        function px(v) { return v * width / 24 }
        function py(v) { return v * height / 24 }

        function roundedRect(ctx, x, y, w, h, r) {
            ctx.beginPath()
            ctx.moveTo(px(x + r), py(y))
            ctx.lineTo(px(x + w - r), py(y))
            ctx.quadraticCurveTo(px(x + w), py(y), px(x + w), py(y + r))
            ctx.lineTo(px(x + w), py(y + h - r))
            ctx.quadraticCurveTo(px(x + w), py(y + h), px(x + w - r), py(y + h))
            ctx.lineTo(px(x + r), py(y + h))
            ctx.quadraticCurveTo(px(x), py(y + h), px(x), py(y + h - r))
            ctx.lineTo(px(x), py(y + r))
            ctx.quadraticCurveTo(px(x), py(y), px(x + r), py(y))
        }

        function line(ctx, x1, y1, x2, y2) {
            ctx.beginPath()
            ctx.moveTo(px(x1), py(y1))
            ctx.lineTo(px(x2), py(y2))
            ctx.stroke()
        }

        function circle(ctx, x, y, r, fill) {
            ctx.beginPath()
            ctx.arc(px(x), py(y), px(r), 0, Math.PI * 2)
            if (fill) ctx.fill()
            else ctx.stroke()
        }

        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = navIcon.lineColor
            ctx.fillStyle = navIcon.lineColor
            ctx.lineWidth = Math.max(1.7, width / 13)
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            if (navIcon.name === "task") {
                roundedRect(ctx, 5, 3.5, 12.5, 17, 2)
                ctx.stroke()
                line(ctx, 8, 9, 14, 9)
                line(ctx, 8, 13, 15, 13)
                line(ctx, 8, 17, 12, 17)
                line(ctx, 14.5, 3.5, 18.5, 7.5)
            } else if (navIcon.name === "status") {
                circle(ctx, 12, 12, 8, false)
                ctx.beginPath()
                ctx.arc(px(12), py(12), px(8), -Math.PI / 2, Math.PI / 5)
                ctx.stroke()
                line(ctx, 12, 12, 16, 9)
                circle(ctx, 12, 12, 1.2, true)
            } else if (navIcon.name === "api") {
                roundedRect(ctx, 3.5, 6, 17, 12, 2.5)
                ctx.stroke()
                line(ctx, 7, 12, 10, 12)
                line(ctx, 14, 12, 17, 12)
                circle(ctx, 12, 12, 1.4, true)
                line(ctx, 12, 6, 12, 3.5)
                line(ctx, 12, 18, 12, 20.5)
            } else if (navIcon.name === "log") {
                roundedRect(ctx, 4.5, 3.5, 15, 17, 2.2)
                ctx.stroke()
                line(ctx, 8, 8, 16, 8)
                line(ctx, 8, 12, 16, 12)
                line(ctx, 8, 16, 13.5, 16)
                circle(ctx, 6.8, 8, 0.45, true)
                circle(ctx, 6.8, 12, 0.45, true)
                circle(ctx, 6.8, 16, 0.45, true)
            } else if (navIcon.name === "glossary") {
                ctx.beginPath()
                ctx.moveTo(px(4), py(6))
                ctx.quadraticCurveTo(px(8), py(4), px(12), py(6))
                ctx.quadraticCurveTo(px(16), py(4), px(20), py(6))
                ctx.lineTo(px(20), py(19))
                ctx.quadraticCurveTo(px(16), py(17), px(12), py(19))
                ctx.quadraticCurveTo(px(8), py(17), px(4), py(19))
                ctx.closePath()
                ctx.stroke()
                line(ctx, 12, 6, 12, 19)
                line(ctx, 7, 10, 10, 9.5)
                line(ctx, 14, 9.5, 17, 10)
            } else {
                circle(ctx, 12, 12, 4, false)
                for (var i = 0; i < 8; i++) {
                    var a = i * Math.PI / 4
                    var x1 = 12 + Math.cos(a) * 7
                    var y1 = 12 + Math.sin(a) * 7
                    var x2 = 12 + Math.cos(a) * 9
                    var y2 = 12 + Math.sin(a) * 9
                    line(ctx, x1, y1, x2, y2)
                }
            }
        }

        Component.onCompleted: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    onNameChanged: iconCanvas.requestPaint()
    onLineColorChanged: iconCanvas.requestPaint()
}
