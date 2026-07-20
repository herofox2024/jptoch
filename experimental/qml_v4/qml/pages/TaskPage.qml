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
    property var taskHistory: []
    property var latestFailedBlocks: []
    property var latestUnfinishedTask: ({})
    property int failedBlockProviderModeIndex: 0

    signal navigateToStatus()

    function openManualEdit(src, dst) {
        manualEditDialog.openWith(src, dst)
    }

    ScrollView {
        id: contentScroll
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, contentScroll.availableWidth)
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
            rowSpacing: AppStyle.spacingXLarge

            Rectangle {
                id: dropCard
                Layout.fillWidth: true
                Layout.preferredHeight: taskPage.width > 980 ? 280 : 300
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
                    anchors.margins: 18
                    spacing: AppStyle.spacingLarge

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingLarge

                        Rectangle {
                            Layout.preferredWidth: 42
                            Layout.preferredHeight: 42
                            radius: 14
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
                Layout.preferredHeight: taskPage.width > 980 ? 280 : 300
                spacing: AppStyle.spacingLarge

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

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: (taskPage.taskHistory.length > 0 ? (taskPage.width > 900 ? 188 : 236) : 112)
                                    + (taskPage.latestFailedBlocks.length > 0 ? (taskPage.width > 900 ? 168 : 232) : 0)
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingSmall

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingMedium

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingNone
                        Label {
                            text: "最近任务"
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontSubHeader
                            font.weight: Font.DemiBold
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "记录最近翻译任务的状态、进度和输入输出路径；API Key 不会写入历史。"
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontCaption
                            elide: Text.ElideRight
                        }
                    }

                    Button {
                        text: "继续上次"
                        enabled: !taskPage.busy && taskPage.latestUnfinishedTask && taskPage.latestUnfinishedTask.task_id
                        onClicked: taskPage.resumeLatestTask()
                    }
                    Button {
                        text: "刷新"
                        onClicked: taskPage.refreshTaskHistory()
                    }
                    Button {
                        text: "清空"
                        enabled: taskPage.taskHistory.length > 0 && !taskPage.busy
                        onClicked: taskPage.clearTaskHistory()
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: taskPage.taskHistory.length === 0
                    text: "暂无任务历史。开始一次翻译后，这里会显示可追踪记录。"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: taskPage.taskHistory
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: taskPage.width > 900 ? 38 : 54
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
                                radius: 4
                                color: taskPage.taskStatusColor(modelData.status)
                            }

                            Label {
                                Layout.preferredWidth: 72
                                text: taskPage.taskStatusLabel(modelData.status)
                                color: taskPage.taskStatusColor(modelData.status)
                                font.pixelSize: AppStyle.fontCaption
                                font.weight: Font.DemiBold
                                elide: Text.ElideRight
                            }

                            Label {
                                Layout.preferredWidth: 68
                                text: taskPage.taskProgressText(modelData)
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideRight
                            }

                            Label {
                                Layout.fillWidth: true
                                text: taskPage.fileName(modelData.input_path || "")
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideMiddle
                            }

                            Label {
                                visible: taskPage.width > 900
                                Layout.preferredWidth: 190
                                text: (modelData.provider || "-") + " / " + (modelData.model || "-")
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontTiny
                                elide: Text.ElideRight
                            }

                            Label {
                                visible: taskPage.width > 980
                                Layout.preferredWidth: 108
                                text: taskPage.taskTimeText(modelData.updated_at || modelData.started_at || modelData.created_at)
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontTiny
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight
                            }

                            Button {
                                text: "载入"
                                enabled: !taskPage.busy
                                onClicked: taskPage.applyTaskRecord(modelData)
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: taskPage.width > 900 ? 150 : 214
                    visible: taskPage.latestFailedBlocks.length > 0
                    radius: AppPalette.radiusMedium
                    color: AppPalette.fieldBg
                    border.color: AppPalette.amberColor
                    clip: true

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 10
                        spacing: AppStyle.spacingTight

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingNone

                                Label {
                                    text: "失败块 / 日文残留"
                                    color: AppPalette.amberColor
                                    font.pixelSize: AppStyle.fontCaption
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: "可自动重译未译/残留块；保存前残留样例仍建议人工定位或继续整本续译。"
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontTiny
                                    elide: Text.ElideRight
                                }
                            }

                            ComboBox {
                                Layout.preferredWidth: 116
                                model: ["当前模型", "校对模型"]
                                currentIndex: taskPage.failedBlockProviderModeIndex
                                onActivated: taskPage.failedBlockProviderModeIndex = currentIndex
                            }

                            Button {
                                text: "重译失败块"
                                enabled: !taskPage.busy && taskPage.latestFailedBlocks.length > 0
                                onClicked: taskPage.retranslateFailedBlocks()
                            }
                        }

                        Repeater {
                            model: taskPage.latestFailedBlocks
                            delegate: Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: taskPage.width > 900 ? 25 : 42
                                radius: AppPalette.radiusSmall
                                color: AppPalette.surfaceRaised
                                border.color: AppPalette.lineColor

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 6
                                    spacing: AppStyle.spacingSmall

                                    Label {
                                        Layout.preferredWidth: 76
                                        text: taskPage.failedBlockKindLabel(modelData.kind)
                                        color: modelData.kind === "save_residue" ? AppPalette.errorColor : AppPalette.amberColor
                                        font.pixelSize: AppStyle.fontTiny
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: taskPage.failedBlockText(modelData)
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontTiny
                                        elide: Text.ElideRight
                                    }

                                    Button {
                                        text: modelData.kind === "save_residue" ? "定位" : "人工修正"
                                        enabled: !taskPage.busy
                                        onClicked: taskPage.openManualEdit(modelData.text || "", modelData.translation || "")
                                    }
                                }
                            }
                        }
                    }
                }
            }
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
        function onTranslationTaskHistoryChanged() {
            taskPage.refreshTaskHistory()
        }
        function onFailedBlocksRetranslated(result) {
            taskPage.refreshTaskHistory()
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

    function refreshTaskHistory() {
        if (!taskPage.tbridge || !taskPage.tbridge.getTranslationTaskHistory) {
            taskPage.taskHistory = []
            taskPage.latestFailedBlocks = []
            taskPage.latestUnfinishedTask = ({})
            return
        }
        var rows = taskPage.tbridge.getTranslationTaskHistory(3)
        taskPage.taskHistory = rows || []
        if (taskPage.tbridge.getLatestUnfinishedTranslationTask) {
            taskPage.latestUnfinishedTask = taskPage.tbridge.getLatestUnfinishedTranslationTask() || ({})
        } else {
            taskPage.latestUnfinishedTask = ({})
        }
        if (taskPage.tbridge.getLatestFailedTranslationBlocks) {
            taskPage.latestFailedBlocks = taskPage.tbridge.getLatestFailedTranslationBlocks(3) || []
        } else {
            taskPage.latestFailedBlocks = []
        }
    }

    function clearTaskHistory() {
        if (!taskPage.tbridge || !taskPage.tbridge.clearTranslationTaskHistory) return
        var result = taskPage.tbridge.clearTranslationTaskHistory()
        taskPage.refreshTaskHistory()
        taskPage.latestFailedBlocks = []
        taskPage.latestUnfinishedTask = ({})
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            if (result && result.ok) ToastBridge.showSuccess(result.message || "任务历史已清空")
            else ToastBridge.showError((result && result.message) || "清空任务历史失败")
        }
    }

    function applyTaskRecord(record) {
        if (!cfg || !record) return
        var inp = record.input_path || (record.config ? record.config.inp : "")
        var out = record.output_path || (record.config ? record.config.out : "")
        if (inp) cfg.inp = inp
        if (out) cfg.out = out
        else if (inp) cfg.out = taskPage.defaultOutputPath(inp)
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            ToastBridge.showInfo("已载入最近任务路径")
        }
    }

    function resumeLatestTask() {
        if (!taskPage.tbridge || !taskPage.tbridge.resumeLatestTranslation) return
        taskPage.tbridge.resumeLatestTranslation(cfg)
        taskPage.navigateToStatus()
    }

    function retranslateFailedBlocks() {
        if (!taskPage.tbridge || !taskPage.tbridge.retranslateLatestFailedBlocks) return
        var mode = taskPage.failedBlockProviderModeIndex === 1 ? "proofread" : "current"
        taskPage.tbridge.retranslateLatestFailedBlocks(cfg, mode, 50)
    }

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

    function failedBlockKindLabel(kind) {
        var value = String(kind || "")
        if (value === "failed") return "未译"
        if (value === "residue") return "残留"
        if (value === "save_residue") return "保存前"
        return "问题"
    }

    function failedBlockText(block) {
        if (!block) return "-"
        var fragments = block.fragments && block.fragments.length > 0 ? (" [" + block.fragments.join(" / ") + "] ") : ""
        var text = block.text || block.translation || "-"
        return fragments + text
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
        taskPage.refreshTaskHistory()
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
    }

}

