import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import ".."

Page {
    id: page
    padding: AppStyle.pagePadding
    background: Item {}

    property var logBridge: null
    property bool paused: false
    property bool followTail: true
    property int maxLines: 900
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    function reloadRecent(forceFollow) {
        if (!page.logBridge) {
            logText.text = "日志模块未加载"
            return
        }
        logText.text = page.logBridge.readRecent(page.maxLines)
        if (forceFollow || page.followTail) Qt.callLater(page.scrollToBottom)
    }

    function appendLine(line) {
        if (!line || page.paused) return
        var nextText = logText.text ? (logText.text + "\n" + line) : line
        if (nextText.length > 260000) {
            nextText = "... 已截断较早日志，仅保留最新内容 ...\n" + nextText.slice(-220000)
        }
        logText.text = nextText
        if (page.followTail) Qt.callLater(page.scrollToBottom)
    }

    function scrollToBottom() {
        logText.cursorPosition = logText.text.length
    }

    Component.onCompleted: page.reloadRecent(true)
    onVisibleChanged: if (visible) page.reloadRecent(true)

    Connections {
        target: page.logBridge
        ignoreUnknownSignals: true

        function onEntryAppended(line) {
            if (page.visible) page.appendLine(line)
        }

        function onCurrentLogPathChanged() {
            if (page.visible) page.reloadRecent(true)
        }
    }

    Timer {
        interval: 2500
        running: page.visible && !page.paused
        repeat: true
        onTriggered: page.reloadRecent(false)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: AppStyle.spacingXLarge

        ColumnLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingNarrow

            Label {
                text: "日志"
                color: AppPalette.textColor
                font.family: page.titleFont
                font.pixelSize: AppStyle.fontPageTitle
                font.weight: Font.DemiBold
            }

            Label {
                text: "实时查看翻译过程、API 报错、限流、校对和保存诊断信息。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontBody
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 112
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingMedium

                    Label {
                        text: "当前日志"
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontBody
                        font.weight: Font.DemiBold
                    }

                    TextField {
                        id: pathText
                        Layout.fillWidth: true
                        readOnly: true
                        text: page.logBridge ? page.logBridge.currentLogPath : ""
                        selectByMouse: true
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontSmall
                        background: Rectangle {
                            radius: AppPalette.radiusMedium
                            color: AppPalette.fieldBg
                            border.color: AppPalette.lineColor
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingMedium

                    Button {
                        text: "刷新"
                        onClicked: page.reloadRecent(true)
                    }

                    Button {
                        text: "清空显示"
                        onClicked: logText.text = ""
                    }

                    Button {
                        text: "打开日志目录"
                        onClicked: if (page.logBridge) page.logBridge.openLogDirectory()
                    }

                    Item { Layout.fillWidth: true }

                    CheckBox {
                        text: "自动跟随"
                        checked: page.followTail
                        onToggled: {
                            page.followTail = checked
                            if (checked) page.scrollToBottom()
                        }
                    }

                    CheckBox {
                        text: "暂停刷新"
                        checked: page.paused
                        onToggled: page.paused = checked
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: AppPalette.radiusLarge
            color: AppPalette.cardBg
            border.color: AppPalette.borderColor
            clip: true

            ScrollView {
                anchors.fill: parent
                anchors.margins: 14
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                TextArea {
                    id: logText
                    width: Math.max(parent.width, implicitWidth)
                    height: Math.max(parent.height, implicitHeight)
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                    color: AppPalette.textColor
                    selectedTextColor: "white"
                    selectionColor: AppPalette.accentColor
                    font.family: "Consolas"
                    font.pixelSize: AppStyle.fontSmall
                    background: Rectangle {
                        color: AppPalette.fieldBg
                        radius: AppPalette.radiusMedium
                        border.color: AppPalette.lineColor
                    }
                }
            }
        }
    }
}
