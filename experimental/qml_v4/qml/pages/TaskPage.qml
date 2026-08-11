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

        WorkflowShortcutPanel {
            busy: taskPage.busy
            readyToStart: taskPage.readyToStart
            modelSummary: taskPage.modelSummary()
            failedBlockCount: taskPage.latestFailedBlocks.length
            recentTaskCount: taskPage.taskHistory.length
            onOpenStatus: taskPage.navigateToStatus()
            onOpenApi: taskPage.navigateToApi()
            onOpenLogs: taskPage.navigateToLogs()
            onOpenSettings: taskPage.navigateToSettings()
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
            id: glossaryLayerCard
            Layout.fillWidth: true
            Layout.preferredHeight: glossaryLayerContent.implicitHeight + 32
            Layout.minimumHeight: glossaryLayerContent.implicitHeight + 32
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

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
                                    text: taskPage.selectedGlossaryProfileCount() > 0
                                          ? "已选 " + taskPage.selectedGlossaryProfileCount() + " 个 profile；开始翻译时生效。"
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
                                enabled: taskPage.selectedGlossaryProfileCount() > 0
                                onClicked: taskPage.clearSelectedGlossaryProfiles()
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
                                        checked: taskPage.isGlossaryProfileSelected(modelData.profileId || modelData.id || "")
                                        enabled: !!taskPage.cfg && !!taskPage.cfg.enableGlossary
                                        onToggled: taskPage.toggleGlossaryProfile(modelData.profileId || modelData.id || "", checked)
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

    Dialog {
        id: taskHistoryDialog
        title: "最近任务"
        modal: true
        width: Math.max(720, Math.min(980, taskPage.width - 48))
        height: Math.max(420, Math.min(640, taskPage.height - 72))
        x: Math.round((taskPage.width - width) / 2)
        y: Math.round((taskPage.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        ColumnLayout {
            width: taskHistoryDialog.width - 48
            spacing: AppStyle.spacingSmall

            Label {
                Layout.fillWidth: true
                text: "记录最近翻译任务的状态、进度和输入输出路径；API Key 不会写入历史。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontSmall
                wrapMode: Text.WordWrap
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                Button {
                    text: "刷新"
                    onClicked: taskPage.refreshTaskHistory()
                }

                Button {
                    text: "清空"
                    enabled: taskPage.taskHistory.length > 0 && !taskPage.busy
                    onClicked: taskPage.clearTaskHistory()
                }

                Button {
                    text: "继续上次"
                    enabled: !taskPage.busy && !!(taskPage.latestUnfinishedTask && taskPage.latestUnfinishedTask.task_id)
                    highlighted: enabled
                    onClicked: taskPage.resumeLatestTask()
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: "关闭"
                    onClicked: taskHistoryDialog.close()
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

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                ListView {
                    width: parent.width
                    height: Math.max(0, contentHeight)
                    spacing: AppStyle.spacingSmall
                    model: taskPage.taskHistory

                    delegate: Rectangle {
                        width: ListView.view.width
                        height: taskPage.width > 900 ? 42 : 58
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
            }
        }
    }

    Dialog {
        id: failedBlocksDialog
        onOpened: taskPage.analyzeFailedBlocks()
        title: "失败块 / 日文残留"
        modal: true
        width: Math.max(760, Math.min(1040, taskPage.width - 48))
        height: Math.max(460, Math.min(700, taskPage.height - 72))
        x: Math.round((taskPage.width - width) / 2)
        y: Math.round((taskPage.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        ColumnLayout {
            width: failedBlocksDialog.width - 48
            spacing: AppStyle.spacingSmall

            Label {
                Layout.fillWidth: true
                text: "可自动重译未译/残留块；保存前残留样例仍建议人工定位或继续整本续译。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontSmall
                wrapMode: Text.WordWrap
            }

            Label {
                Layout.fillWidth: true
                text: {
                    var summary = (taskPage.latestUnfinishedTask || {}).recovery_summary || {}
                    return "恢复统计：尝试 " + Number(summary.attempted || 0) +
                           "，成功 " + Number(summary.success || 0) +
                           "，待复核 " + Number(summary.needs_review || 0) +
                           "，失败 " + Number(summary.failed || 0)
                }
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontTiny
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                Button {
                    text: "生成恢复建议"
                    enabled: !taskPage.busy && taskPage.latestFailedBlocks.length > 0
                    onClicked: taskPage.analyzeFailedBlocks()
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
                    highlighted: enabled
                    onClicked: taskPage.retranslateFailedBlocks()
                }

                Button {
                    text: "查看请求日志"
                    onClicked: taskPage.navigateToLogs()
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: "关闭"
                    onClicked: failedBlocksDialog.close()
                }
            }

            Label {
                Layout.fillWidth: true
                visible: taskPage.latestFailedBlocks.length === 0
                text: "当前没有失败块或保存前残留记录。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontSmall
                wrapMode: Text.WordWrap
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                ListView {
                    width: parent.width
                    height: Math.max(0, contentHeight)
                    spacing: AppStyle.spacingSmall
                    model: taskPage.latestFailedBlocks

                    delegate: Rectangle {
                        width: ListView.view.width
                        height: taskPage.width > 900 ? 60 : 78
                        radius: AppPalette.radiusSmall
                        color: AppPalette.surfaceRaised
                        border.color: AppPalette.lineColor

                        RowLayout {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 32
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

                        Label {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.leftMargin: 8
                            anchors.rightMargin: 8
                            anchors.bottomMargin: 5
                            text: {
                                var issue = modelData.recovery_issue || {}
                                var decision = modelData.recovery_decision || {}
                                var attempts = Number(modelData.recovery_attempts || 0)
                                return (issue.issue_type || "未分类") + " | " +
                                       (decision.action || "未分析") + " | " +
                                       (modelData.recovery_recommendation || "等待人工确认") +
                                       " | 已尝试 " + attempts + " 次"
                            }
                            color: modelData.recovery_status === "success" ? AppPalette.successColor : AppPalette.mutedText
                            font.pixelSize: AppStyle.fontTiny
                            elide: Text.ElideRight
                        }
                    }
                }
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

    Connections {
        target: taskPage.cfg
        enabled: !!taskPage.cfg
        ignoreUnknownSignals: true

        function onGlossaryProfilesChanged() {
            taskPage.refreshGlossaryProfiles()
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

    function refreshGlossaryProfiles() {
        if (!taskPage.cfg || !taskPage.cfg.listGlossaryProfiles) {
            taskPage.glossaryProfiles = []
            return
        }
        var items = taskPage.cfg.listGlossaryProfiles("") || []
        taskPage.glossaryProfiles = items
    }

    function selectedGlossaryProfileIds() {
        if (!taskPage.cfg) return []
        var raw = taskPage.cfg.selectedGlossaryProfileIds || []
        var ids = []
        for (var i = 0; i < raw.length; i++) {
            var value = String(raw[i] || "").trim()
            if (value !== "" && ids.indexOf(value) < 0) ids.push(value)
        }
        return ids
    }

    function selectedGlossaryProfileCount() {
        return taskPage.selectedGlossaryProfileIds().length
    }

    function setSelectedGlossaryProfileIds(ids) {
        if (!taskPage.cfg) return
        var cleaned = []
        for (var i = 0; i < (ids || []).length; i++) {
            var value = String(ids[i] || "").trim()
            if (value !== "" && cleaned.indexOf(value) < 0) cleaned.push(value)
        }
        taskPage.cfg.selectedGlossaryProfileIds = cleaned
        if (cleaned.length > 0) {
            taskPage.cfg.enableGlossary = true
            taskPage.cfg.enableLayeredGlossary = true
        }
    }

    function clearSelectedGlossaryProfiles() {
        taskPage.setSelectedGlossaryProfileIds([])
    }

    function isGlossaryProfileSelected(profileId) {
        var value = String(profileId || "").trim()
        if (value === "") return false
        return taskPage.selectedGlossaryProfileIds().indexOf(value) >= 0
    }

    function toggleGlossaryProfile(profileId, checked) {
        var value = String(profileId || "").trim()
        if (value === "" || !taskPage.cfg) return
        var ids = taskPage.selectedGlossaryProfileIds()
        var index = ids.indexOf(value)
        if (checked && index < 0) ids.push(value)
        if (!checked && index >= 0) ids.splice(index, 1)
        taskPage.setSelectedGlossaryProfileIds(ids)
    }

    function addSelectedGlossaryProfileIds(ids) {
        if (!ids || ids.length === 0) return
        var merged = taskPage.selectedGlossaryProfileIds()
        for (var i = 0; i < ids.length; i++) {
            var value = String(ids[i] || "").trim()
            if (value !== "" && merged.indexOf(value) < 0) merged.push(value)
        }
        taskPage.setSelectedGlossaryProfileIds(merged)
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
        var rows = taskPage.tbridge.getTranslationTaskHistory(12)
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
            else if (inp) cfg.out = taskPage.defaultOutputPath(inp)
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
        if (!taskPage.tbridge || !taskPage.tbridge.analyzeLatestFailedBlocks) return
        var result = taskPage.tbridge.analyzeLatestFailedBlocks(cfg, 50)
        if (result && result.ok) taskPage.latestFailedBlocks = result.items || []
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
        taskPage.refreshGlossaryProfiles()
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
    }

}


