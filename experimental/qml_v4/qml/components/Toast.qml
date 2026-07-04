import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

/* ============================================================
   Toast 通知组件 — 非阻塞浮层消息，自动消失
   ============================================================
   用法:
     Toast.info("文件已保存")           // 信息
     Toast.success("连接成功")          // 成功
     Toast.warning("请填写 API Key")    // 警告
     Toast.error("翻译失败")            // 错误
     Toast.show(msg, type, duration)   // 自定义类型/时长(ms)
   ============================================================ */

Item {
    id: root
    anchors.fill: parent
    z: 9999

    // 消息队列
    property var queue: []
    property int displayDuration: 3500
    property bool showing: false
    readonly property bool active: queue.length > 0 || showing

    // 类型配置
    readonly property var typeConfig: ({
        info:     { bg: "infoBg",     fg: "infoFg",     icon: "i"  },
        success:  { bg: "successBg",  fg: "successFg",  icon: "\u2713" },
        warning:  { bg: "warningBg",  fg: "warningFg",  icon: "!" },
        error:    { bg: "errorBg",    fg: "errorFg",    icon: "\u2717" },
    })

    // ====== 类型色值 ======
    readonly property color infoBg:     AppPalette.accentSoft
    readonly property color infoFg:     AppPalette.accentColor
    readonly property color successBg:  AppStyle.statusSuccessBg
    readonly property color successFg:  AppPalette.successColor
    readonly property color warningBg:  AppStyle.statusWarningBg
    readonly property color warningFg:  AppPalette.amberColor
    readonly property color errorBg:    AppStyle.statusErrorBg
    readonly property color errorFg:    AppPalette.errorColor

    // ====== 公开方法 ======
    function info(msg, duration)    { _enqueue(msg, "info",    duration || displayDuration) }
    function success(msg, duration) { _enqueue(msg, "success", duration || displayDuration) }
    function warning(msg, duration) { _enqueue(msg, "warning", duration || displayDuration) }
    function error(msg, duration)   { _enqueue(msg, "error",   duration || displayDuration) }
    function show(msg, type, duration) { _enqueue(msg, type || "info", duration || displayDuration) }

    function _enqueue(msg, type, duration) {
        if (!msg) return
        // 合并重复消息
        for (var i = queue.length - 1; i >= 0; i--) {
            if (queue[i].msg === msg) return
        }
        queue.push({ msg: msg, type: type, duration: duration })
        if (!showing) _showNext()
    }

    function _showNext() {
        if (queue.length === 0) { showing = false; return }
        showing = true
        var entry = queue.shift()
        var cfg = typeConfig[entry.type] || typeConfig.info
        popup.msgText     = entry.msg
        popup.bgColor     = root[cfg.bg]
        popup.fgColor     = root[cfg.fg]
        popup.iconText    = cfg.icon
        popup.restart(entry.duration)
    }

    // ====== Toast Popup ======
    Rectangle {
        id: popup
        property string msgText: ""
        property string iconText: ""
        property color bgColor: "transparent"
        property color fgColor: "black"
        property int timerDuration: 3500

        x: (parent.width  - width)  / 2
        y: Math.max(24, (parent.height - height) * 0.12)
        width: Math.min(parent.width - 48, Math.max(240, label.implicitWidth + 72))
        height: Math.max(42, label.implicitHeight + 22)
        radius: AppPalette.radiusMedium
        color: bgColor
        opacity: 0
        visible: opacity > 0.01
        border.width: 1
        border.color: Qt.rgba(fgColor.r, fgColor.g, fgColor.b, 0.26)

        // 入场动画
        SequentialAnimation on opacity {
            id: enterAnim
            running: false
            NumberAnimation { from: 0; to: 1.0; duration: 260; easing.type: Easing.OutCubic }
        }

        // 离场动画
        SequentialAnimation on opacity {
            id: leaveAnim
            running: false
            NumberAnimation { from: 1.0; to: 0; duration: 240; easing.type: Easing.InCubic }
            ScriptAction { script: root._showNext() }
        }

        // 自动消失计时器
        Timer {
            id: dismissTimer
            interval: popup.timerDuration
            running: false
            repeat: false
            onTriggered: leaveAnim.start()
        }

        function restart(duration) {
            dismissTimer.stop()
            leaveAnim.stop()
            popup.timerDuration = duration
            popup.y = Qt.binding(function() {
                return Math.max(24, (root.parent.height - popup.height) * 0.12)
            })
            enterAnim.start()
            dismissTimer.interval = duration
            dismissTimer.start()
        }

        // 悬停时暂停计时
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: dismissTimer.stop()
            onExited:  dismissTimer.start()
            onClicked: leaveAnim.start()
        }

        RowLayout {
            anchors.centerIn: parent
            anchors.leftMargin: 20
            anchors.rightMargin: 20
            spacing: AppStyle.spacingMedium

            // 图标
            Rectangle {
                Layout.preferredWidth: 26
                Layout.preferredHeight: 26
                radius: 13
                color: popup.fgColor
                opacity: 0.12
                visible: popup.iconText !== ""
                Label {
                    anchors.centerIn: parent
                    text: popup.iconText
                    color: popup.fgColor
                    font.pixelSize: AppStyle.fontBodyLarge + 1
                    font.weight: Font.Bold
                }
            }

            // 消息文本
            Label {
                id: label
                text: popup.msgText
                color: popup.fgColor
                font.pixelSize: AppStyle.fontBodyLarge
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                Layout.maximumWidth: root.parent ? root.parent.width - 140 : 400
            }
        }
    }

    // ====== 从 Python 接收消息 ======
    Connections {
        target: typeof ToastBridge !== "undefined" ? ToastBridge : null
        enabled: typeof ToastBridge !== "undefined"
        ignoreUnknownSignals: true

        function onShowInfo(msg)    { root.info(msg) }
        function onShowSuccess(msg) { root.success(msg) }
        function onShowWarning(msg) { root.warning(msg) }
        function onShowError(msg)   { root.error(msg) }
    }
}
