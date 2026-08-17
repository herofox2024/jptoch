import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."
import "../components"

Page {
    id: taskPage
    padding: AppStyle.pagePadding
    background: Item {}

    property var cfg: null
    property var tbridge: null
    readonly property bool busy: tbridge ? tbridge.busy : false
    readonly property bool readyToStart: cfg && cfg.inp !== "" && cfg.out !== ""
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"
    property var taskHistory: []
    property var latestFailedBlocks: []
    property string recoveryAnalysisMessage: ""
    property string runtimeStatus: busy ? "翻译运行中" : "等待任务"
    property var latestUnfinishedTask: ({})
    property int failedBlockProviderModeIndex: 0
    property var glossaryProfiles: []
    signal navigateToStatus()
    signal navigateToApi()
    signal navigateToLogs()
    signal navigateToSettings()

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
                    font.weight: Font.Bold
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
            columns: taskPage.width >= AppStyle.bpMedium ? 4 : 2
            columnSpacing: AppStyle.spacingLarge
            rowSpacing: AppStyle.spacingLarge

            Repeater {
                model: [
                    { label: "总任务", value: taskPage.taskHistory.length, detail: "本地任务记录", tone: "accent" },
                    { label: "进行中", value: taskPage.taskCountByGroup("running"), detail: "运行或可继续", tone: "warning" },
                    { label: "已完成", value: taskPage.taskCountByGroup("completed"), detail: "已成功输出 EPUB", tone: "success" },
                    { label: "异常", value: taskPage.taskCountByGroup("failed"), detail: "失败或部分完成", tone: "error" }
                ]

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 104
                    radius: AppPalette.radiusLarge
                    color: AppPalette.cardBg
                    border.color: AppPalette.lineColor

                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
                        shadowBlur: 0.25
                        shadowVerticalOffset: AppPalette.shadowYOffset
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 15
                        spacing: AppStyle.spacingLarge

                        Rectangle {
                            Layout.preferredWidth: 34
                            Layout.preferredHeight: 34
                            radius: 8
                            color: taskPage.metricToneBg(modelData.tone)
                            Label {
                                anchors.centerIn: parent
                                text: modelData.tone === "success" ? "✓" : (modelData.tone === "error" ? "!" : (modelData.tone === "warning" ? "◷" : "▦"))
                                color: taskPage.metricToneColor(modelData.tone)
                                font.pixelSize: AppStyle.fontBodyLarge
                                font.weight: Font.DemiBold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label { text: modelData.label; color: AppPalette.mutedText; font.pixelSize: AppStyle.fontCaption }
                            Label { text: taskPage.formatMetricValue(modelData.value); color: AppPalette.textColor; font.pixelSize: 25; font.weight: Font.Bold }
                            Label { Layout.fillWidth: true; text: modelData.detail; color: AppPalette.mutedText; font.pixelSize: AppStyle.fontTiny; elide: Text.ElideRight }
                        }
                    }
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: taskPage.width > AppStyle.bpWide ? 2 : 1
            columnSpacing: 18
            rowSpacing: AppStyle.spacingXLarge

            Rectangle {
                id: dropCard
                Layout.fillWidth: true
                Layout.preferredHeight: taskPage.width > AppStyle.bpWide ? 280 : 300
                radius: AppPalette.radiusLarge
                color: AppPalette.cardBg
                border.color: dropCard.hovering ? AppPalette.amberColor : AppPalette.borderColor
                border.width: dropCard.hovering ? 2 : 1

                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
                    shadowBlur: 0.25
                    shadowVerticalOffset: AppPalette.shadowYOffset
                }

                property bool hovering: false

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
                            radius: AppPalette.radiusLarge
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
                        radius: AppPalette.radiusMedium
                        color: dropCard.hovering ? AppPalette.accentSoft : AppPalette.fieldBg
                        border.color: dropCard.hovering ? AppPalette.amberColor : AppPalette.lineColor
                        border.width: dropCard.hovering ? 2 : 1

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
                Layout.preferredHeight: taskPage.width > AppStyle.bpWide ? 280 : 300
                spacing: AppStyle.spacingLarge

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusLarge
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.borderColor

                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
                        shadowBlur: 0.25
                        shadowVerticalOffset: AppPalette.shadowYOffset
                    }

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
                            text: FilePathUtils.pathDisplay(cfg ? cfg.inp : "")
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

                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
                        shadowBlur: 0.25
                        shadowVerticalOffset: AppPalette.shadowYOffset
                    }

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
                            text: FilePathUtils.pathDisplay(cfg ? cfg.out : "")
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
            statusText: taskPage.runtimeStatus

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
            onStatusRequested: taskPage.navigateToStatus()
        }

        Rectangle {
            id: glossaryLayerCard
            Layout.fillWidth: true
            Layout.preferredHeight: glossaryLayerContent.implicitHeight + 32
            Layout.minimumHeight: glossaryLayerContent.implicitHeight + 32
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
                shadowBlur: 0.25
                shadowVerticalOffset: AppPalette.shadowYOffset
            }

            ColumnLayout {
                id: glossaryLayerContent
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 16
                spacing: AppStyle.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingTight

                        Label {
                            text: "术语设置"
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontSubHeader
                            font.weight: Font.DemiBold
                        }

                        Label {
                            Layout.fillWidth: true
                            text: "这里仅选择翻译时注入的术语 profile。提取术语、管理 profile、译后统一请到“术语表”页的“术语任务”。"
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontCaption
                            wrapMode: Text.WordWrap
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: 150
                        Layout.preferredHeight: AppStyle.buttonHeightSmall
                        radius: 16
                        color: taskPage.cfg && taskPage.cfg.enableLayeredGlossary ? AppStyle.statusAccentBg : AppPalette.fieldBg
                        border.color: taskPage.cfg && taskPage.cfg.enableLayeredGlossary ? AppPalette.accentColor : AppPalette.borderColor
                        Label {
                            anchors.centerIn: parent
                            text: taskPage.cfg && taskPage.cfg.enableLayeredGlossary ? "分层已启用" : "分层关闭"
                            color: taskPage.cfg && taskPage.cfg.enableLayeredGlossary ? AppPalette.accentColor : AppPalette.mutedText
                            font.pixelSize: AppStyle.fontSmall
                            font.weight: Font.DemiBold
                        }
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    Layout.preferredHeight: implicitHeight
                    spacing: AppStyle.spacingMedium

                    CheckBox {
                        text: "启用术语表"
                        checked: taskPage.cfg ? taskPage.cfg.enableGlossary : true
                        onCheckedChanged: { if (taskPage.cfg) taskPage.cfg.enableGlossary = checked }
                    }
                    CheckBox {
                        text: "启用分层术语"
                        checked: taskPage.cfg ? taskPage.cfg.enableLayeredGlossary : false
                        enabled: taskPage.cfg ? taskPage.cfg.enableGlossary : true
                        onCheckedChanged: { if (taskPage.cfg) taskPage.cfg.enableLayeredGlossary = checked }
                    }
                    CheckBox {
                        text: "合并全局"
                        checked: taskPage.cfg ? taskPage.cfg.useGlobalGlossary : true
                        enabled: taskPage.cfg ? (taskPage.cfg.enableGlossary && taskPage.cfg.enableLayeredGlossary) : true
                        onCheckedChanged: { if (taskPage.cfg) taskPage.cfg.useGlobalGlossary = checked }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: Math.max(94, Math.min(190, glossaryProfileSelectorContent.implicitHeight + 24))
                    radius: AppPalette.radiusMedium
                    color: AppPalette.cardBg
                    border.color: AppPalette.lineColor
                    clip: true

                    ColumnLayout {
                        id: glossaryProfileSelectorContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingSmall

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingTight

                                Label {
                                    text: "已提取术语（翻译时注入）"
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontCaption
                                    font.weight: Font.DemiBold
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: GlossaryProfileUtils.selectedGlossaryProfileCount(taskPage.cfg) > 0
                                          ? "已选 " + GlossaryProfileUtils.selectedGlossaryProfileCount(taskPage.cfg) + " 个 profile；开始翻译时生效。"
                                          : "未选择 profile；可到术语表页提取或勾选已有 profile。"
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontTiny
                                    elide: Text.ElideRight
                                }
                            }

                            Button {
                                text: "刷新术语"
                                onClicked: taskPage.refreshGlossaryProfiles()
                            }

                            Button {
                                text: "清空选择"
                                enabled: GlossaryProfileUtils.selectedGlossaryProfileCount(taskPage.cfg) > 0
                                onClicked: GlossaryProfileUtils.clearSelectedGlossaryProfiles(taskPage.cfg)
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            visible: taskPage.glossaryProfiles.length === 0
                            text: "暂无可选 profile。请到术语表页提取本书术语，或刷新后再勾选。"
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontTiny
                            wrapMode: Text.WordWrap
                        }

                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(42, Math.min(94, glossaryProfileFlow.implicitHeight + 8))
                            visible: taskPage.glossaryProfiles.length > 0
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical.policy: ScrollBar.AsNeeded

                            Flow {
                                id: glossaryProfileFlow
                                width: Math.max(0, parent.width)
                                spacing: AppStyle.spacingSmall

                                Repeater {
                                    model: taskPage.glossaryProfiles

                                    delegate: CheckBox {
                                        text: taskPage.glossaryProfileLabel(modelData)
                                        checked: GlossaryProfileUtils.isGlossaryProfileSelected(taskPage.cfg, modelData.profileId || modelData.id || "")
                                        enabled: !!taskPage.cfg && !!taskPage.cfg.enableGlossary
                                        onToggled: GlossaryProfileUtils.toggleGlossaryProfile(taskPage.cfg, modelData.profileId || modelData.id || "", checked)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: taskHistorySummaryRow.implicitHeight + 32
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor
            clip: true

            layer.enabled: true
            layer.effect: MultiEffect {
                shadowEnabled: true
                shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
                shadowBlur: 0.25
                shadowVerticalOffset: AppPalette.shadowYOffset
            }

            RowLayout {
                id: taskHistorySummaryRow
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingMedium

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 92
                    radius: AppPalette.radiusMedium
                    color: AppPalette.cardBg
                    border.color: AppPalette.lineColor

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingMedium

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingTight

                            Label {
                                text: "最近任务"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSubHeader
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                text: taskPage.taskHistory.length > 0
                                      ? "已有 " + taskPage.taskHistory.length + " 条历史记录；可在弹窗中载入或继续。"
                                      : "暂无任务历史。开始翻译后会记录可恢复任务。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideRight
                            }
                        }

                        Button {
                            text: "打开"
                            onClicked: taskHistoryDialog.open()
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 92
                    radius: AppPalette.radiusMedium
                    color: taskPage.latestFailedBlocks.length > 0 ? AppStyle.statusWarningBg : AppPalette.cardBg
                    border.color: taskPage.latestFailedBlocks.length > 0 ? AppPalette.amberColor : AppPalette.lineColor

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingMedium

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingTight

                            Label {
                                text: "失败块处理"
                                color: taskPage.latestFailedBlocks.length > 0 ? AppPalette.amberColor : AppPalette.textColor
                                font.pixelSize: AppStyle.fontSubHeader
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                text: taskPage.latestFailedBlocks.length > 0
                                      ? "发现 " + taskPage.latestFailedBlocks.length + " 条失败/残留块，可集中处理。"
                                      : "当前没有失败块或保存前残留记录。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideRight
                            }
                        }

                        Button {
                            text: "处理"
                            highlighted: taskPage.latestFailedBlocks.length > 0
                            onClicked: failedBlocksDialog.open()
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

    TaskHistoryDialog {
        id: taskHistoryDialog
        taskHistory: taskPage.taskHistory
        latestUnfinishedTask: taskPage.latestUnfinishedTask
        busy: taskPage.busy
        pageWidth: taskPage.width
        pageHeight: taskPage.height
        onRefreshRequested: taskPage.refreshTaskHistory()
        onClearRequested: taskPage.clearTaskHistory()
        onResumeLatestRequested: taskPage.resumeLatestTask()
        onLoadRecordRequested: function(record) { taskPage.applyTaskRecord(record) }
    }

    FailedBlocksDialog {
        id: failedBlocksDialog
        latestFailedBlocks: taskPage.latestFailedBlocks
        latestUnfinishedTask: taskPage.latestUnfinishedTask
        busy: taskPage.busy
        providerModeIndex: taskPage.failedBlockProviderModeIndex
        recoveryAnalysisMessage: taskPage.recoveryAnalysisMessage
        pageWidth: taskPage.width
        pageHeight: taskPage.height
        onAnalyzeRequested: taskPage.analyzeFailedBlocks()
        onProviderModeChanged: function(idx) { taskPage.failedBlockProviderModeIndex = idx }
        onRetranslateRequested: taskPage.retranslateFailedBlocks()
        onNavigateToLogsRequested: taskPage.navigateToLogs()
        onManualEditRequested: function(text, translation) { taskPage.openManualEdit(text, translation) }
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
        function onStatusChanged(message) {
            taskPage.runtimeStatus = message || (taskPage.busy ? "翻译运行中" : "等待任务")
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

    Connections {
        target: taskPage.cfg
        enabled: !!taskPage.cfg
        ignoreUnknownSignals: true

        function onGlossaryProfilesChanged() {
            taskPage.refreshGlossaryProfiles()
        }
    }

    function compactEstimateText(text) {
        if (!text || text === "预估字符: -") return "预估: -"
        return text.replace("预估字符:", "预估:")
    }

    function refreshGlossaryProfiles() {
        if (!taskPage.cfg || !taskPage.cfg.listGlossaryProfiles) {
            taskPage.glossaryProfiles = []
            return
        }
        var items = taskPage.cfg.listGlossaryProfiles("") || []
        taskPage.glossaryProfiles = items
    }

    function glossaryScopeLabel(scope) {
        var value = String(scope || "").toLowerCase()
        if (value === "genre") return "题材"
        if (value === "series") return "系列"
        if (value === "book") return "本书"
        return "术语"
    }

    function glossaryProfileLabel(profile) {
        var item = profile || {}
        var profileName = String(item.name || "未命名")
        var count = Number(item.termCount || 0)
        return taskPage.glossaryScopeLabel(item.scope) + " / " + profileName + " / " + count + " 条"
    }

    function refreshTaskHistory() {
        if (!taskPage.tbridge || !taskPage.tbridge.getTranslationTaskHistory) {
            taskPage.taskHistory = []
            taskPage.latestFailedBlocks = []
            taskPage.latestUnfinishedTask = ({})
            return
        }
        var rows = taskPage.tbridge.getTranslationTaskHistory(80)
        taskPage.taskHistory = rows || []
        if (taskPage.tbridge.getLatestUnfinishedTranslationTask) {
            taskPage.latestUnfinishedTask = taskPage.tbridge.getLatestUnfinishedTranslationTask() || ({})
        } else {
            taskPage.latestUnfinishedTask = ({})
        }
        if (taskPage.tbridge.getLatestFailedTranslationBlocks) {
            taskPage.latestFailedBlocks = taskPage.tbridge.getLatestFailedTranslationBlocks(50) || []
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
        if (taskPage.tbridge && taskPage.tbridge.loadTranslationTaskConfig && record.task_id) {
            var result = taskPage.tbridge.loadTranslationTaskConfig(String(record.task_id), cfg)
            if (result && !result.ok) {
                if (typeof ToastBridge !== "undefined" && ToastBridge) {
                    ToastBridge.showError(result.message || "载入任务配置失败")
                }
                return
            }
        } else {
            var inp = record.input_path || (record.config ? record.config.inp : "")
            var out = record.output_path || (record.config ? record.config.out : "")
            if (inp) cfg.inp = inp
            if (out) cfg.out = out
            else if (inp) cfg.out = FilePathUtils.defaultOutputPath(inp)
        }
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            ToastBridge.showInfo("已载入最近任务配置")
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

    function analyzeFailedBlocks() {
        if (!taskPage.tbridge || !taskPage.tbridge.analyzeLatestFailedBlocks) {
            if (typeof ToastBridge !== "undefined" && ToastBridge) ToastBridge.showError("失败块恢复服务不可用")
            return
        }
        var result = taskPage.tbridge.analyzeLatestFailedBlocks(cfg, 50)
        if (result && result.ok) {
            taskPage.recoveryAnalysisMessage = result.message || "已生成恢复建议"
            if (taskPage.tbridge.getLatestFailedTranslationBlocks) {
                taskPage.latestFailedBlocks = taskPage.tbridge.getLatestFailedTranslationBlocks(50) || []
            } else {
                taskPage.latestFailedBlocks = result.items || []
            }
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showSuccess(taskPage.recoveryAnalysisMessage)
            }
        } else {
            taskPage.recoveryAnalysisMessage = (result && result.message) || "生成恢复建议失败"
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showError(taskPage.recoveryAnalysisMessage)
            }
        }
    }

    function modelSummary() {
        if (!cfg) return "-"
        var provider = cfg.provider || "-"
        var model = cfg.model || "-"
        if (model === "-") return provider
        return provider + " / " + model
    }

    function taskCountByGroup(group) {
        var count = 0
        for (var i = 0; i < taskPage.taskHistory.length; i++) {
            var status = String(taskPage.taskHistory[i].status || "").toLowerCase()
            if (group === "completed" && status === "completed") count++
            else if (group === "running" && ["running", "pausing", "paused", "cancelling", "stopping"].indexOf(status) >= 0) count++
            else if (group === "failed" && ["failed", "partial", "cancelled", "stopped"].indexOf(status) >= 0) count++
        }
        return count
    }

    function metricToneColor(tone) {
        if (tone === "success") return AppPalette.successColor
        if (tone === "warning") return AppPalette.amberColor
        if (tone === "error") return AppPalette.errorColor
        return AppPalette.accentColor
    }

    function formatMetricValue(value) {
        var number = Number(value || 0)
        return number < 10 ? "0" + number : String(number)
    }

    function metricToneBg(tone) {
        if (tone === "success") return AppStyle.statusSuccessBg
        if (tone === "warning") return AppStyle.statusWarningBg
        if (tone === "error") return AppStyle.statusErrorBg
        return AppPalette.accentSoft
    }

    function setInputPath(path) {
        if (cfg) {
            cfg.inp = path
            cfg.out = FilePathUtils.defaultOutputPath(path)
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
        taskPage.refreshGlossaryProfiles()
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
    }

}


