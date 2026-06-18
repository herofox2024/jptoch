import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

Page {
    id: taskPage
    padding: 24
    background: Item {}

    property var cfg: null
    property var tbridge: null
    readonly property bool busy: tbridge ? tbridge.busy : false
    readonly property bool readyToStart: cfg && cfg.inp !== "" && cfg.out !== ""
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    signal navigateToStatus()

    ColumnLayout {
        anchors.fill: parent
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: "任务"
                    color: AppPalette.textColor
                    font.family: taskPage.titleFont
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "把 EPUB 放到工作台上，确认源文件和输出文件，然后开始翻译或断点续译。"
                    color: AppPalette.mutedText
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Rectangle {
                Layout.preferredWidth: 128
                Layout.preferredHeight: 34
                radius: 17
                color: AppPalette.accentSoft
                border.color: AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: taskPage.busy ? "翻译运行中" : "等待任务"
                    color: taskPage.busy ? AppPalette.accentColor : AppPalette.mutedText
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: taskPage.width > 980 ? 2 : 1
            columnSpacing: 18
            rowSpacing: 18

            Rectangle {
                id: dropCard
                Layout.fillWidth: true
                Layout.preferredHeight: 320
                radius: AppPalette.radiusLarge
                color: AppPalette.cardBg
                border.color: dropCard.hovering ? AppPalette.amberColor : AppPalette.borderColor
                border.width: dropCard.hovering ? 2 : 1
                scale: dropCard.hovering ? 1.012 : 1.0

                property bool hovering: false

                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 16

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 48
                            Layout.preferredHeight: 48
                            radius: 16
                            color: AppPalette.accentSoft
                            border.color: AppPalette.lineColor
                            Label {
                                anchors.centerIn: parent
                                text: "EPUB"
                                color: AppPalette.accentColor
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                text: "把书放到工作台上"
                                color: AppPalette.textColor
                                font.pixelSize: 19
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: "拖入新文件会自动生成当前书名对应的 _zh.epub 输出路径。"
                                color: AppPalette.mutedText
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }

                    Rectangle {
                        id: dropArea
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 22
                        color: dropCard.hovering ? AppPalette.accentSoft : AppPalette.fieldBg
                        border.color: dropCard.hovering ? AppPalette.amberColor : AppPalette.lineColor
                        border.width: dropCard.hovering ? 2 : 1

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -5
                            radius: 27
                            color: "transparent"
                            border.color: AppPalette.amberColor
                            border.width: dropCard.hovering ? 1 : 0
                            opacity: dropCard.hovering ? 0.45 : 0
                        }

                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: 7
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: dropCard.hovering ? "释放 EPUB 文件" : "拖放 EPUB 文件到这里"
                                color: AppPalette.textColor
                                font.pixelSize: 19
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: "或使用右侧“选择源文件”按钮"
                                color: AppPalette.mutedText
                                font.pixelSize: 12
                            }
                        }

                        DropArea {
                            anchors.fill: parent
                            onEntered: dropCard.hovering = true
                            onExited: dropCard.hovering = false
                            onDropped: function(drop) {
                                dropCard.hovering = false
                                if (drop.urls.length > 0) {
                                    var path = drop.urls[0].toString()
                                    if (path.startsWith("file:///")) path = path.substring(8)
                                    else if (path.startsWith("file://")) path = path.substring(7)
                                    path = decodeURIComponent(path)
                                    taskPage.setInputPath(path)
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 320
                spacing: 14

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusLarge
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.borderColor

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "源文件"
                                color: AppPalette.textColor
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.preferredWidth: 150
                                text: taskPage.compactEstimateText(estimateLabel.text)
                                color: AppPalette.accentColor
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: taskPage.pathDisplay(cfg ? cfg.inp : "")
                            color: (cfg && cfg.inp !== "") ? AppPalette.textColor : AppPalette.mutedText
                            font.pixelSize: 13
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            TextField {
                                id: inpField
                                Layout.fillWidth: true
                                placeholderText: "输入 EPUB 路径"
                                text: cfg ? cfg.inp : ""
                                selectByMouse: true
                                onTextChanged: {
                                    if (cfg) cfg.inp = text
                                    if (!activeFocus) cursorPosition = 0
                                    if (activeFocus) estimateTimer.restart()
                                }
                                onEditingFinished: {
                                    if (text !== "") taskPage.setInputPath(text)
                                }
                                Component.onCompleted: cursorPosition = 0
                            }
                            Button {
                                text: "选择源文件"
                                onClicked: inputDialog.open()
                            }
                        }

                        Label {
                            id: estimateLabel
                            visible: false
                            text: "预估字符: -"
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusLarge
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.borderColor

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "输出文件"
                                color: AppPalette.textColor
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: "EPUB"
                                color: AppPalette.amberColor
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: taskPage.pathDisplay(cfg ? cfg.out : "")
                            color: (cfg && cfg.out !== "") ? AppPalette.textColor : AppPalette.mutedText
                            font.pixelSize: 13
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            TextField {
                                id: outField
                                Layout.fillWidth: true
                                placeholderText: "输出文件路径 (.epub)"
                                text: cfg ? cfg.out : ""
                                selectByMouse: true
                                onTextChanged: {
                                    if (cfg) cfg.out = text
                                    if (!activeFocus) cursorPosition = 0
                                }
                                Component.onCompleted: cursorPosition = 0
                            }
                            Button {
                                text: "选择输出"
                                onClicked: outputDialog.open()
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 142
            radius: AppPalette.radiusLarge
            color: AppPalette.accentSoft
            border.color: AppPalette.borderColor

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Label {
                        text: "准备翻译"
                        color: AppPalette.textColor
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Rectangle {
                        Layout.preferredWidth: 86
                        Layout.preferredHeight: 24
                        radius: 12
                        color: taskPage.readyToStart ? AppPalette.cardBg : AppPalette.cardAlt
                        border.color: AppPalette.lineColor
                        Label {
                            anchors.centerIn: parent
                            text: taskPage.readyToStart ? "可开始" : "待选择"
                            color: taskPage.readyToStart ? AppPalette.successColor : AppPalette.mutedText
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10

                    Button {
                        id: startBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        text: taskPage.busy ? "翻译中..." : "开始翻译"
                        highlighted: true
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                        enabled: taskPage.readyToStart && !taskPage.busy
                        onClicked: {
                            if (taskPage.tbridge) {
                                taskPage.tbridge.startTranslation(cfg)
                                taskPage.navigateToStatus()
                            }
                        }
                    }

                    Button {
                        id: pauseBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        text: "暂停"
                        enabled: taskPage.busy
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        onClicked: { if (taskPage.tbridge) taskPage.tbridge.pauseTranslation() }
                    }

                    Button {
                        id: resumeBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        text: "恢复"
                        enabled: taskPage.readyToStart && !taskPage.busy
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        onClicked: {
                            if (taskPage.tbridge) {
                                taskPage.tbridge.resumeTranslation(cfg)
                                taskPage.navigateToStatus()
                            }
                        }
                    }

                    Button {
                        id: stopBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        text: "停止"
                        enabled: taskPage.busy
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        onClicked: {
                            if (taskPage.tbridge) {
                                taskPage.tbridge.stopTranslation()
                            }
                        }
                    }

                    Button {
                        id: clearCacheBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 56
                        text: "清缓存"
                        enabled: taskPage.readyToStart && !taskPage.busy
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                        onClicked: clearCacheDialog.open()
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Label {
                        Layout.fillWidth: true
                        text: "暂停会保留已写入缓存的内容，切换模型后点\"恢复\"可续译；停止会取消任务并清空本次已翻译缓存。"
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: 12
                    }
                    Flow {
                        Layout.preferredWidth: taskPage.width > 800 ? 340 : 0
                        spacing: 6
                        visible: taskPage.width > 800
                        SummaryChip { title: "模型"; value: taskPage.modelSummary() }
                        SummaryChip { title: "并发"; value: taskPage.valueOrDash(cfg ? cfg.maxWorkers : "") }
                        SummaryChip { title: "批量"; value: taskPage.valueOrDash(cfg ? cfg.batchSize : "") }
                        SummaryChip { title: "单条上限"; value: taskPage.valueOrDash(cfg ? cfg.maxTextSizeForBatch : "") }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: "数据目录: " + (AppDir || "")
            color: AppPalette.mutedText
            font.pixelSize: 11
            elide: Text.ElideMiddle
        }

        Item { Layout.fillHeight: true }
    }

    FileDialog {
        id: inputDialog
        title: "选择 EPUB 文件"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                taskPage.setInputPath(p)
            }
        }
    }

    FileDialog {
        id: outputDialog
        title: "保存翻译后的 EPUB"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                if (!p.toLowerCase().endsWith(".epub")) p += ".epub"
                if (cfg) cfg.out = p
            }
        }
    }

    Dialog {
        id: clearCacheDialog
        title: "清理当前 EPUB 缓存"
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: parent

        ColumnLayout {
            width: 420
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: "将清理当前源文件对应的翻译缓存，包括所有模型下的 cache.json 条目和跨模型 text_cache.json 条目。"
                color: AppPalette.textColor
                wrapMode: Text.WordWrap
            }
            Label {
                Layout.fillWidth: true
                text: "不会删除 EPUB 文件，也不会清空术语表。清理后再次翻译会重新请求 API。"
                color: AppPalette.mutedText
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
        }

        onAccepted: {
            if (taskPage.tbridge) {
                taskPage.tbridge.clearCurrentBookCache(cfg)
            }
        }
    }

    Timer {
        id: estimateTimer
        interval: 300
        onTriggered: {
            if (cfg && cfg.inp) {
                estimateLabel.text = "预估字符: 计算中..."
                if (taskPage.tbridge) taskPage.tbridge.startEstimateChars(cfg.inp)
            }
        }
    }

    Connections {
        target: taskPage.tbridge
        enabled: true
        function onEstimateFinished(path, chars) {
            if (cfg && path === cfg.inp && chars >= 0) {
                estimateLabel.text = "预估字符: " + chars.toLocaleString()
            }
        }
        function onEstimateFailed(path, err) {
            if (cfg && path === cfg.inp) {
                estimateLabel.text = "预估字符: 读取失败"
            }
        }
    }

    function defaultOutputPath(path) {
        var normalized = (path || "").replace(/\\/g, "/")
        var slash = normalized.lastIndexOf("/")
        var dir = slash >= 0 ? normalized.substring(0, slash + 1) : ""
        var base = slash >= 0 ? normalized.substring(slash + 1) : normalized
        base = base.replace(/\.epub$/i, "")
        return dir + base + "_zh.epub"
    }

    function fileName(path) {
        if (!path || path === "") return "未选择"
        var normalized = path.replace(/\\/g, "/")
        var slash = normalized.lastIndexOf("/")
        return slash >= 0 ? normalized.substring(slash + 1) : normalized
    }

    function pathDisplay(path) {
        if (!path || path === "") return "未选择"
        return path.replace(/\\/g, "/")
    }

    function compactEstimateText(text) {
        if (!text || text === "预估字符: -") return "预估: -"
        return text.replace("预估字符:", "预估:")
    }

    function valueOrDash(value) {
        if (value === undefined || value === null || value === "") return "-"
        return value.toString()
    }

    function modelSummary() {
        if (!cfg) return "-"
        var provider = cfg.provider || "-"
        var model = cfg.model || "-"
        if (model === "-") return provider
        return provider + " / " + model
    }

    function setInputPath(path) {
        if (cfg) {
            cfg.inp = path
            cfg.out = taskPage.defaultOutputPath(path)
        }
        estimateLabel.text = "预估字符: 计算中..."
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
        if (taskPage.tbridge) taskPage.tbridge.startEstimateChars(path)
    }

    Component.onCompleted: {
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
    }

    component SummaryChip: Rectangle {
        property string title: ""
        property string value: ""

        width: Math.min(240, Math.max(88, chipRow.implicitWidth + 22))
        height: 30
        radius: 15
        color: AppPalette.cardBg
        border.color: AppPalette.lineColor

        RowLayout {
            id: chipRow
            anchors.centerIn: parent
            spacing: 5
            Label {
                text: title + ":"
                color: AppPalette.mutedText
                font.pixelSize: 11
            }
            Label {
                text: value
                color: AppPalette.textColor
                font.pixelSize: 11
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }
    }
}
