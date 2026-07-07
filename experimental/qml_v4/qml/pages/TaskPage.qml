import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."
import "../components"

Page {
    id: taskPage
    padding: AppStyle.pagePadding
    background: Item {
        Rectangle {
            anchors.fill: parent
            color: "transparent"
        }
        Rectangle {
            width: 360
            height: 360
            radius: 180
            x: parent.width - width * 0.65
            y: -height * 0.45
            color: AppPalette.glass ? AppPalette.glassGlowCyan : AppPalette.accentSoft
            opacity: AppPalette.dark ? 0.16 : 0.24
        }
        Rectangle {
            width: 280
            height: 280
            radius: 140
            x: -width * 0.42
            y: parent.height - height * 0.58
            color: AppPalette.glass ? AppPalette.glassGlowAmber : AppPalette.backgroundAlt
            opacity: AppPalette.dark ? 0.16 : 0.32
        }
    }

    property var cfg: null
    property var tbridge: null
    readonly property bool busy: tbridge ? tbridge.busy : false
    readonly property bool readyToStart: cfg && cfg.inp !== "" && cfg.out !== ""
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    signal navigateToStatus()

    function openManualEdit(src, dst) {
        manualEditDialog.openWith(src, dst)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: AppStyle.sectionGap

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingXLarge

            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingTight
                Label {
                    text: "任务"
                    color: AppPalette.textColor
                    font.family: taskPage.titleFont
                    font.pixelSize: AppStyle.fontPageTitle
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "把 EPUB 放到工作台上，确认源文件和输出文件，然后开始翻译或断点续译。"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontBody
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Rectangle {
                Layout.preferredWidth: 128
                Layout.preferredHeight: AppStyle.buttonHeightSmall
                radius: 17
                color: AppPalette.accentSoft
                border.color: AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: taskPage.busy ? "翻译运行中" : "等待任务"
                    color: taskPage.busy ? AppPalette.accentColor : AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
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
                scale: dropCard.hovering ? 1.02 : 1.0
                y: dropCard.hovering ? -3 : 0
                opacity: dropCard.hovering ? 1.0 : 0.98

                property bool hovering: false

                Behavior on y {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }
                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }
                Behavior on opacity {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: AppStyle.spacingXXLarge

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingLarge

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
                                font.pixelSize: AppStyle.fontTiny
                                font.weight: Font.DemiBold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingTight
                            Label {
                                text: "把书放到工作台上"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontHeader
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: "拖入新文件会自动生成当前书名对应的 _zh.epub 输出路径。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
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
                        scale: dropCard.hovering ? 1.01 : 1.0
                        Behavior on scale {
                            NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                        }

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -5
                            radius: 27
                            color: "transparent"
                            border.color: AppPalette.amberColor
                            border.width: dropCard.hovering ? 2 : 0
                            opacity: dropCard.hovering ? 0.62 : 0
                            Behavior on opacity {
                                NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                            }
                        }

                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: AppStyle.spacingCompact
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: dropCard.hovering ? "释放 EPUB 文件" : "拖放 EPUB 文件到这里"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontHeader
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: "或使用右侧“选择源文件”按钮"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                            }
                        }

                        DropArea {
                            anchors.fill: parent
                            onEntered: dropCard.hovering = true
                            onExited: dropCard.hovering = false
                            onDropped: function(drop) {
                                dropCard.hovering = false
                                if (drop.urls.length > 0) {
                                    var path = FilePathUtils.normalizeFileUrl(drop.urls[0])
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
                spacing: AppStyle.spacingXLarge

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusLarge
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.borderColor

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: AppStyle.spacingMedium

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "源文件"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSection
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.preferredWidth: 150
                                text: taskPage.compactEstimateText(estimateLabel.text)
                                color: AppPalette.accentColor
                                font.pixelSize: AppStyle.fontCaption
                                font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: taskPage.pathDisplay(cfg ? cfg.inp : "")
                            color: (cfg && cfg.inp !== "") ? AppPalette.textColor : AppPalette.mutedText
                            font.pixelSize: AppStyle.fontBody
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingMedium
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
                        spacing: AppStyle.spacingMedium

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "输出文件"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSection
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: "EPUB"
                                color: AppPalette.amberColor
                                font.pixelSize: AppStyle.fontCaption
                                font.weight: Font.DemiBold
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: taskPage.pathDisplay(cfg ? cfg.out : "")
                            color: (cfg && cfg.out !== "") ? AppPalette.textColor : AppPalette.mutedText
                            font.pixelSize: AppStyle.fontBody
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingMedium
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

        TaskControlPanel {
            readyToStart: taskPage.readyToStart
            busy: taskPage.busy
            viewportWidth: taskPage.width
            modelSummary: taskPage.modelSummary()
            maxWorkers: cfg ? cfg.maxWorkers : 0
            batchSize: cfg ? cfg.batchSize : 0
            maxTextSizeForBatch: cfg ? cfg.maxTextSizeForBatch : 0

            onStartRequested: {
                if (taskPage.tbridge) {
                    taskPage.tbridge.startTranslation(cfg)
                    taskPage.navigateToStatus()
                }
            }
            onPauseRequested: { if (taskPage.tbridge) taskPage.tbridge.pauseTranslation() }
            onResumeRequested: {
                if (taskPage.tbridge) {
                    taskPage.tbridge.resumeTranslation(cfg)
                    taskPage.navigateToStatus()
                }
            }
            onStopRequested: { if (taskPage.tbridge) taskPage.tbridge.stopTranslation() }
            onClearCacheRequested: clearCacheDialog.open()
            onManualEditRequested: manualEditDialog.open()
        }

        Label {
            Layout.fillWidth: true
            text: "数据目录: " + (AppDir || "")
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontCaption
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
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
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
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                if (!p.toLowerCase().endsWith(".epub")) p += ".epub"
                if (cfg) cfg.out = p
            }
        }
    }

    ClearCacheDialog {
        id: clearCacheDialog
        cfg: taskPage.cfg
        tbridge: taskPage.tbridge
        anchors.centerIn: parent
    }
    ManualEditDialog {
        id: manualEditDialog
        tbridge: taskPage.tbridge
        anchors.centerIn: parent
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
        function onManualTranslationLookup(result) {
            if (typeof manualEditDialog !== "undefined") {
                manualEditDialog.setLookupResult(result)
            }
        }
        function onManualTranslationSaved(result) {
            if (typeof manualEditDialog !== "undefined") {
                manualEditDialog.showSaved()
            }
        }
        function onFailed(err) {
            if (typeof manualEditDialog !== "undefined") {
                manualEditDialog.showError(err)
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

}

