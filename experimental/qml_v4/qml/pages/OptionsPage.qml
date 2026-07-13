import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
import ".."
import "../components"

Page {
    id: page
    padding: 0
    background: Item {}
    property var cfg: null
    property var tbridge: null
    property var updater: null

    property string activePreset: "custom"
    property bool applyingPreset: false
    property var updateInfo: ({})
    property string updateStatus: updater ? ("当前版本 V" + updater.currentVersion) : "更新模块未加载"
    property int updateDownloadPercent: 0
    property var proofreadGenreValues: ["auto", "general", "mystery", "historical_mystery", "scifi", "fantasy"]
    property var proofreadGenreLabels: ["自动识别（推荐）", "通用小说", "推理小说", "历史推理", "科幻小说", "奇幻小说"]
    property var proofreadToneValues: ["auto", "neutral", "light", "literary"]
    property var proofreadToneLabels: ["自动识别（推荐）", "中性口吻", "轻小说口吻", "文学化口吻"]
    property var proofreadProviderValues: ["", "deepseek", "doubao", "sakura", "hymt2", "gemini", "glm", "wenxin", "longcat", "custom"]
    property var proofreadProviderLabels: ["跟随翻译模型", "DeepSeek", "豆包 Doubao", "Sakura 本地", "Hy-MT2 本地", "Gemini", "智谱 GLM", "文心一言", "LongCat 2.0", "自定义"]
    property string residueAllowlistPath: cfg ? cfg.japaneseResidueAllowlistPath : ""
    property string residueAllowlistStatus: ""
    property string knownKatakanaTermsPath: cfg ? cfg.knownKatakanaTermsPath : ""
    property string knownKatakanaTermsStatus: ""
    property string promptPreviewText: "点击“刷新 Prompt 预览”查看当前初译和校对提示词片段。"
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"
    readonly property bool updaterBusy: updater ? (updater.checking || updater.downloading) : false

    ListModel { id: residueAllowlistModel }
    ListModel { id: knownKatakanaTermsModel }

    function refreshJapaneseResidueAllowlist() {
        if (!cfg || !cfg.getJapaneseResidueAllowlist) return
        var info = cfg.getJapaneseResidueAllowlist()
        page.residueAllowlistPath = info.path || ""
        residueAllowlistModel.clear()
        var items = info.quoted || []
        for (var i = 0; i < items.length; i++) {
            residueAllowlistModel.append({ "fragment": items[i] })
        }
    }

    function addJapaneseResidueAllowItem() {
        if (!cfg) return
        var value = residueAllowInput.text.trim()
        if (!value) {
            page.residueAllowlistStatus = "请输入要放行的片段"
            return
        }
        var result = cfg.addJapaneseResidueAllowQuoted(value)
        page.residueAllowlistStatus = result.message || ""
        residueAllowInput.text = ""
        page.refreshJapaneseResidueAllowlist()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(page.residueAllowlistStatus) : ToastBridge.showError(page.residueAllowlistStatus)
        }
    }

    function removeJapaneseResidueAllowItem(value) {
        if (!cfg || !value) return
        var result = cfg.removeJapaneseResidueAllowQuoted(value)
        page.residueAllowlistStatus = result.message || ""
        page.refreshJapaneseResidueAllowlist()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(page.residueAllowlistStatus) : ToastBridge.showError(page.residueAllowlistStatus)
        }
    }

    function refreshKnownKatakanaTerms() {
        if (!cfg || !cfg.getKnownKatakanaTerms) return
        var info = cfg.getKnownKatakanaTerms()
        page.knownKatakanaTermsPath = info.path || ""
        knownKatakanaTermsModel.clear()
        var items = info.items || []
        for (var i = 0; i < items.length; i++) {
            knownKatakanaTermsModel.append({
                "source": items[i].source || "",
                "target": items[i].target || "",
                "builtin": !!items[i].builtin
            })
        }
    }

    function addKnownKatakanaTermItem() {
        if (!cfg) return
        var source = katakanaSourceInput.text.trim()
        var target = katakanaTargetInput.text.trim()
        var result = cfg.addKnownKatakanaTerm(source, target)
        page.knownKatakanaTermsStatus = result.message || ""
        if (result.ok) {
            katakanaSourceInput.text = ""
            katakanaTargetInput.text = ""
        }
        page.refreshKnownKatakanaTerms()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(page.knownKatakanaTermsStatus) : ToastBridge.showError(page.knownKatakanaTermsStatus)
        }
    }

    function removeKnownKatakanaTermItem(source) {
        if (!cfg || !source) return
        var result = cfg.removeKnownKatakanaTerm(source)
        page.knownKatakanaTermsStatus = result.message || ""
        page.refreshKnownKatakanaTerms()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(page.knownKatakanaTermsStatus) : ToastBridge.showError(page.knownKatakanaTermsStatus)
        }
    }

    function refreshPromptPreview() {
        if (!cfg || !cfg.buildPromptPreview) return
        page.promptPreviewText = cfg.buildPromptPreview()
    }

    function batchAddNoticePages(files, noticeText) {
        if (!page.tbridge || !files || files.length === 0) return
        var paths = []
        for (var i = 0; i < files.length; i++) {
            paths.push(FilePathUtils.normalizeFileUrl(files[i]))
        }
        var result = page.tbridge.addNoticePageToBooks(paths, noticeText || "")
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(result.message || "批量处理完成")
                      : ToastBridge.showError(result.message || "批量处理失败")
        }
    }

    Component.onCompleted: {
        page.refreshJapaneseResidueAllowlist()
        page.refreshKnownKatakanaTerms()
    }

    Connections {
        target: page.cfg
        ignoreUnknownSignals: true

        function onJapaneseResidueAllowlistChanged() {
            page.refreshJapaneseResidueAllowlist()
        }

        function onKnownKatakanaTermsChanged() {
            page.refreshKnownKatakanaTerms()
        }
    }

    Connections {
        target: page.updater
        ignoreUnknownSignals: true

        function onCheckStarted() {
            page.updateDownloadPercent = 0
            page.updateStatus = "正在检查 GitHub 最新版本..."
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showInfo("正在检查更新")
            }
        }

        function onUpdateAvailable(info) {
            page.updateInfo = info || ({})
            page.updateStatus = "发现新版本 V" + (page.updateInfo.latestVersion || "")
                    + "，可下载 " + (page.updateInfo.assetName || "安装包")
            updateDialog.open()
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showInfo("发现新版本 V" + (page.updateInfo.latestVersion || ""))
            }
        }

        function onNoUpdate(info) {
            page.updateInfo = info || ({})
            page.updateStatus = "当前已是最新版本 V" + (page.updateInfo.currentVersion || "")
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showSuccess("当前已是最新版本")
            }
        }

        function onCheckFailed(message) {
            page.updateStatus = "检查更新失败：" + message
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showError("检查更新失败")
            }
        }

        function onDownloadStarted(fileName) {
            page.updateDownloadPercent = 0
            page.updateStatus = "正在下载安装包：" + fileName
            if (!updateDialog.opened) updateDialog.open()
        }

        function onDownloadProgress(received, total, percent) {
            page.updateDownloadPercent = percent
            if (total > 0) {
                page.updateStatus = "正在下载：" + percent + "%"
            } else {
                page.updateStatus = "正在下载：" + page.formatBytes(received)
            }
        }

        function onDownloadFinished(path) {
            page.updateDownloadPercent = 100
            page.updateStatus = "下载完成，正在启动安装程序..."
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showSuccess("安装包下载完成")
            }
            Qt.callLater(function() {
                if (page.updater) page.updater.launchInstaller(path)
            })
        }

        function onDownloadFailed(message) {
            page.updateStatus = "下载更新失败：" + message
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showError("下载更新失败")
            }
        }

        function onInstallerLaunched(path) {
            page.updateStatus = "安装程序已启动，当前软件即将退出。"
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showInfo("安装程序已启动")
            }
        }

        function onInstallFailed(message) {
            page.updateStatus = message
            if (typeof ToastBridge !== "undefined" && ToastBridge) {
                ToastBridge.showError("启动安装程序失败")
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: AppStyle.spacingXLarge

        Label {
            text: "翻译设置"
            color: AppPalette.textColor
            font.family: page.titleFont
            font.pixelSize: AppStyle.fontPageTitle
            font.weight: Font.DemiBold
        }

        TabBar {
            id: settingsTabs
            Layout.fillWidth: true
            background: Rectangle {
                radius: 18
                color: AppPalette.cardAlt
                border.color: AppPalette.lineColor
            }
            TabButton { text: "性能" }
            TabButton { text: "输出" }
            TabButton { text: "风格" }
            TabButton { text: "校对" }
            TabButton { text: "缓存" }
            TabButton { text: "界面" }
            TabButton { text: "更新" }
        }

        StackLayout {
            id: settingsStack
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: settingsTabs.currentIndex

            SettingsPane {
                GroupBox {
                    title: "性能参数"
                    Layout.fillWidth: true

                    GridLayout {
                        width: parent.width
                        columns: 2
                        rowSpacing: 10
                        columnSpacing: 16

                        Label { text: "最大并发数" }
                        RowLayout {
                            Layout.fillWidth: true
                            Slider {
                                id: maxWorkersSlider
                                from: 1
                                to: 25
                                value: cfg ? cfg.maxWorkers : 5
                                Layout.fillWidth: true
                                onMoved: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.maxWorkers = value
                                        page.markCustom()
                                    }
                                }
                            }
                            SpinBox {
                                id: maxWorkersSpin
                                from: 1
                                to: 25
                                value: cfg ? cfg.maxWorkers : 5
                                editable: true
                                onValueChanged: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.maxWorkers = value
                                        page.markCustom()
                                    }
                                }
                            }
                        }

                        Label { text: "批次大小" }
                        RowLayout {
                            Layout.fillWidth: true
                            Slider {
                                id: batchSizeSlider
                                from: 1
                                to: 15
                                value: cfg ? cfg.batchSize : 4
                                Layout.fillWidth: true
                                onMoved: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.batchSize = value
                                        page.markCustom()
                                    }
                                }
                            }
                            SpinBox {
                                id: batchSizeSpin
                                from: 1
                                to: 15
                                value: cfg ? cfg.batchSize : 4
                                editable: true
                                onValueChanged: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.batchSize = value
                                        page.markCustom()
                                    }
                                }
                            }
                        }

                        Label { text: "批次最大长度" }
                        RowLayout {
                            Layout.fillWidth: true
                            Slider {
                                id: maxBatchLengthSlider
                                from: 1
                                to: 8000
                                stepSize: 100
                                value: cfg ? cfg.maxBatchLength : 800
                                Layout.fillWidth: true
                                onMoved: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.maxBatchLength = value
                                        page.markCustom()
                                    }
                                }
                            }
                            SpinBox {
                                id: maxBatchLengthSpin
                                from: 1
                                to: 8000
                                stepSize: 100
                                value: cfg ? cfg.maxBatchLength : 800
                                editable: true
                                onValueChanged: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.maxBatchLength = value
                                        page.markCustom()
                                    }
                                }
                            }
                        }

                        Label { text: "单条上限" }
                        RowLayout {
                            Layout.fillWidth: true
                            Slider {
                                id: maxTextSizeSlider
                                from: 1
                                to: 1000
                                value: cfg ? cfg.maxTextSizeForBatch : 200
                                Layout.fillWidth: true
                                onMoved: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.maxTextSizeForBatch = value
                                        page.markCustom()
                                    }
                                }
                            }
                            SpinBox {
                                id: maxTextSizeSpin
                                from: 1
                                to: 1000
                                value: cfg ? cfg.maxTextSizeForBatch : 200
                                editable: true
                                onValueChanged: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.maxTextSizeForBatch = value
                                        page.markCustom()
                                    }
                                }
                            }
                        }

                        Label { text: "API 超时(秒)" }
                        RowLayout {
                            Layout.fillWidth: true
                            Slider {
                                id: apiTimeoutSlider
                                from: 1
                                to: 300
                                value: cfg ? cfg.apiTimeout : 120
                                Layout.fillWidth: true
                                onMoved: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.apiTimeout = value
                                        page.markCustom()
                                    }
                                }
                            }
                            SpinBox {
                                id: apiTimeoutSpin
                                from: 1
                                to: 600
                                value: cfg ? cfg.apiTimeout : 120
                                editable: true
                                onValueChanged: {
                                    if (!page.applyingPreset) {
                                        if (cfg) cfg.apiTimeout = value
                                        page.markCustom()
                                    }
                                }
                            }
                        }
                    }
                }

                GroupBox {
                    title: "性能预设"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingSmall

                        Flow {
                            Layout.fillWidth: true
                            width: parent.width
                            spacing: AppStyle.spacingSmall

                            Repeater {
                                model: [
                                    { key: "default", label: "默认" },
                                    { key: "balanced", label: "适中" },
                                    { key: "extreme", label: "极端" },
                                    { key: "glm_free", label: "智谱免费版" },
                                    { key: "gemini_free", label: "Gemini 免费版" },
                                    { key: "deepseek_paid", label: "DeepSeek 付费版" },
                                    { key: "hymt2_local", label: "Hy-MT2 本地" }
                                ]
                                Button {
                                    text: modelData.label
                                    checkable: true
                                    checked: page.activePreset === modelData.key
                                    onClicked: page.applyPreset(modelData.key)
                                }
                            }
                        }

                        Label {
                            id: presetHint
                            text: "点击上方预设应用推荐参数"
                            font.pixelSize: AppStyle.fontSmall
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }

            }

            SettingsPane {
                GroupBox {
                    title: "阅读方向"
                    Layout.fillWidth: true

                    RowLayout {
                        RadioButton {
                            text: "中文习惯"
                            checked: cfg ? cfg.direction === "zh" : true
                            onClicked: { if (cfg) cfg.direction = "zh" }
                        }
                        RadioButton {
                            text: "保持原版"
                            checked: cfg ? cfg.direction === "ja" : false
                            onClicked: { if (cfg) cfg.direction = "ja" }
                        }
                    }
                }

                NoticePageSettings {
                    cfg: page.cfg
                    onBatchAddRequested: function(files, noticeText) {
                        page.batchAddNoticePages(files, noticeText)
                    }
                }
            }

            SettingsPane {
                GroupBox {
                    title: "翻译与校对 Prompt 风格"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingMedium

                        CheckBox {
                            text: "启用译后校对"
                            checked: cfg ? cfg.enableProofread : true
                            onCheckedChanged: {
                                if (cfg) {
                                    cfg.enableProofread = checked
                                }
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: page.width > 820 ? 4 : 2
                            rowSpacing: 8
                            columnSpacing: 12

                            Label { text: "作品类型" }
                            ComboBox {
                                id: proofreadGenreCombo
                                Layout.fillWidth: true
                                model: page.proofreadGenreLabels
                                currentIndex: page.proofreadGenreIndex(cfg ? cfg.proofreadGenre : "auto")
                                onActivated: function(index) {
                                    if (cfg) {
                                        cfg.proofreadGenre = page.proofreadGenreValue(index)
                                    }
                                }
                            }

                            Label { text: "叙事口吻" }
                            ComboBox {
                                id: proofreadToneCombo
                                Layout.fillWidth: true
                                model: page.proofreadToneLabels
                                currentIndex: page.proofreadToneIndex(cfg ? cfg.proofreadTone : "auto")
                                onActivated: function(index) {
                                    if (cfg) {
                                        cfg.proofreadTone = page.proofreadToneValue(index)
                                    }
                                }
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: "作品类型和叙事口吻会影响初译 Prompt；启用译后校对后，也会影响校对 Prompt。自动识别会在开始翻译后根据书名、目录和样本文本生成结果，识别不确定时回退到“通用小说 + 中性口吻”。"
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontSmall
                            wrapMode: Text.WordWrap
                        }

                        CheckBox {
                            text: "启用风格示例引导（会少量增加 Prompt 长度）"
                            checked: cfg ? cfg.enablePromptExamples : true
                            onCheckedChanged: {
                                if (cfg) {
                                    cfg.enablePromptExamples = checked
                                }
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: "自定义补充要求"
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontBody
                            font.weight: Font.DemiBold
                        }

                        TextArea {
                            id: promptExtraArea
                            Layout.fillWidth: true
                            Layout.preferredHeight: 96
                            text: cfg ? cfg.promptExtraInstruction : ""
                            placeholderText: "例如：历史捕物小说请保留时代称谓，不要改成现代网络口吻。"
                            wrapMode: TextEdit.WordWrap
                            selectByMouse: true
                            clip: true
                            leftPadding: 14
                            rightPadding: 14
                            topPadding: 12
                            bottomPadding: 12
                            color: AppPalette.textColor
                            selectedTextColor: AppPalette.surfaceRaised
                            selectionColor: AppPalette.accentColor
                            font.pixelSize: AppStyle.fontBody
                            background: Rectangle {
                                radius: AppPalette.radiusMedium
                                color: AppPalette.cardAlt
                                border.color: promptExtraArea.activeFocus ? AppPalette.accentColor : AppPalette.lineColor
                                border.width: promptExtraArea.activeFocus ? 2 : 1
                            }
                            onTextChanged: {
                                if (cfg && cfg.promptExtraInstruction !== text) {
                                    cfg.promptExtraInstruction = text
                                }
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            Button {
                                text: "刷新 Prompt 预览"
                                highlighted: true
                                onClicked: page.refreshPromptPreview()
                            }

                            Button {
                                text: "清空补充要求"
                                onClicked: {
                                    promptExtraArea.text = ""
                                    if (cfg) {
                                        cfg.promptExtraInstruction = ""
                                    }
                                }
                            }

                            Label {
                                Layout.fillWidth: true
                                text: "预览只在本地生成，不调用 API。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                                elide: Text.ElideRight
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 220
                            radius: AppPalette.radiusMedium
                            color: AppPalette.cardAlt
                            border.color: AppPalette.lineColor
                            clip: true

                            ScrollView {
                                anchors.fill: parent
                                anchors.margins: 10
                                clip: true
                                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                                TextArea {
                                    width: parent.availableWidth
                                    text: page.promptPreviewText
                                    readOnly: true
                                    wrapMode: TextEdit.WordWrap
                                    selectByMouse: true
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontSmall
                                    background: Item {}
                                }
                            }
                        }
                    }
                }
            }

            SettingsPane {
                GroupBox {
                    title: "校对模型"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingMedium

                        Label {
                            text: "校对可使用独立供应商和模型；切换翻译模型后，恢复续译会优先复用已通过安全校验的旧译文缓存。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                            Layout.fillWidth: true
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: page.width > 820 ? 4 : 2
                            rowSpacing: 8
                            columnSpacing: 12

                            Label {
                                text: "校对供应商"
                            }
                            ComboBox {
                                id: proofreadProviderCombo
                                Layout.fillWidth: true
                                model: page.proofreadProviderLabels
                                currentIndex: page.proofreadProviderIndex(cfg ? cfg.proofreadProvider : "")
                                onActivated: function(index) {
                                    if (!cfg) return
                                    var provider = page.proofreadProviderValue(index)
                                    cfg.proofreadProvider = provider
                                    if (provider === "") {
                                        cfg.proofreadApiUrl = ""
                                        cfg.proofreadModel = ""
                                    } else {
                                        var defaults = cfg.getProviderDefaults(provider)
                                        cfg.proofreadApiUrl = defaults.url || ""
                                        cfg.proofreadModel = defaults.model || ""
                                    }
                                }
                            }

                            Label {
                                text: "校对 API Key"
                            }
                            TextField {
                                id: proofreadApiKeyField
                                Layout.fillWidth: true
                                placeholderText: "留空则使用翻译 API Key"
                                text: cfg ? cfg.proofreadApiKey : ""
                                echoMode: TextInput.Password
                                selectByMouse: true
                                onTextChanged: { if (cfg) cfg.proofreadApiKey = text }
                            }

                            Label {
                                text: "校对 Base URL"
                            }
                            TextField {
                                id: proofreadApiUrlField
                                Layout.fillWidth: true
                                placeholderText: "留空则使用翻译 Base URL"
                                text: cfg ? cfg.proofreadApiUrl : ""
                                selectByMouse: true
                                onTextChanged: { if (cfg) cfg.proofreadApiUrl = text }
                            }

                            Label {
                                text: "校对模型名"
                            }
                            TextField {
                                id: proofreadModelField
                                Layout.fillWidth: true
                                placeholderText: "留空则使用翻译模型"
                                text: cfg ? cfg.proofreadModel : ""
                                selectByMouse: true
                                onTextChanged: { if (cfg) cfg.proofreadModel = text }
                            }
                        }
                    }
                }

                GroupBox {
                    title: "片假名术语修复词表"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingMedium

                        Label {
                            Layout.fillWidth: true
                            text: "用于处理模型已经翻译出中文解释、但仍残留片假名原词的情况。例如“チロリ的酒”会在保存前自动修复为“烫酒壶里的酒”。这类词应加入修复词表，不要加入日文残留白名单。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            Label {
                                text: "文件"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                                font.weight: Font.DemiBold
                            }

                            TextField {
                                Layout.fillWidth: true
                                text: page.knownKatakanaTermsPath
                                readOnly: true
                                selectByMouse: true
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontCaption
                            }
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: page.width > 820 ? 5 : 2
                            rowSpacing: 8
                            columnSpacing: 12

                            Label { text: "片假名原词" }
                            TextField {
                                id: katakanaSourceInput
                                Layout.fillWidth: true
                                placeholderText: "例如 チロリ"
                                selectByMouse: true
                                onAccepted: page.addKnownKatakanaTermItem()
                            }

                            Label { text: "中文译名" }
                            TextField {
                                id: katakanaTargetInput
                                Layout.fillWidth: true
                                placeholderText: "例如 烫酒壶"
                                selectByMouse: true
                                onAccepted: page.addKnownKatakanaTermItem()
                            }

                            Button {
                                text: "保存修复词"
                                highlighted: true
                                Layout.fillWidth: page.width <= 820
                                onClicked: page.addKnownKatakanaTermItem()
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(96, Math.min(220, knownKatakanaTermsModel.count * 40 + 18))
                            radius: AppPalette.radiusMedium
                            color: AppPalette.cardAlt
                            border.color: AppPalette.lineColor
                            clip: true

                            ListView {
                                id: knownKatakanaTermsList
                                anchors.fill: parent
                                anchors.margins: 8
                                model: knownKatakanaTermsModel
                                spacing: AppStyle.spacingInline
                                clip: true

                                delegate: Rectangle {
                                    width: knownKatakanaTermsList.width
                                    height: 34
                                    radius: 10
                                    color: AppPalette.surfaceRaised
                                    border.color: AppPalette.lineColor

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 6
                                        spacing: AppStyle.spacingSmall

                                        Label {
                                            Layout.preferredWidth: 140
                                            text: source
                                            color: AppPalette.textColor
                                            font.pixelSize: AppStyle.fontBody
                                            elide: Text.ElideRight
                                        }

                                        Label {
                                            text: "→"
                                            color: AppPalette.mutedText
                                            font.pixelSize: AppStyle.fontSmall
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: target + (builtin ? "（内置）" : "")
                                            color: AppPalette.textColor
                                            font.pixelSize: AppStyle.fontBody
                                            elide: Text.ElideRight
                                        }

                                        Button {
                                            text: builtin ? "内置" : "删除"
                                            flat: true
                                            enabled: !builtin
                                            onClicked: page.removeKnownKatakanaTermItem(source)
                                        }
                                    }
                                }
                            }

                            Label {
                                anchors.centerIn: parent
                                visible: knownKatakanaTermsModel.count === 0
                                text: "暂无修复词"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: page.knownKatakanaTermsStatus
                            visible: page.knownKatakanaTermsStatus !== ""
                            color: page.knownKatakanaTermsStatus.indexOf("失败") >= 0
                                   || page.knownKatakanaTermsStatus.indexOf("请输入") >= 0
                                   || page.knownKatakanaTermsStatus.indexOf("需要") >= 0
                                   || page.knownKatakanaTermsStatus.indexOf("不能") >= 0
                                   ? AppPalette.errorColor : AppPalette.successColor
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }
                    }
                }

                GroupBox {
                    title: "日文残留白名单"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingMedium

                        Label {
                            Layout.fillWidth: true
                            text: "仅在确认片段确实需要保留日文时使用。这里添加的是“引号内片段白名单”，例如译文中的 “レディス” 会放行，但正文其他位置的日文仍会继续被拦截。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            Label {
                                text: "文件"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                                font.weight: Font.DemiBold
                            }

                            TextField {
                                Layout.fillWidth: true
                                text: page.residueAllowlistPath
                                readOnly: true
                                selectByMouse: true
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontCaption
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            TextField {
                                id: residueAllowInput
                                Layout.fillWidth: true
                                placeholderText: "输入保存前提示里的片段，例如 レディス"
                                selectByMouse: true
                                onAccepted: page.addJapaneseResidueAllowItem()
                            }

                            Button {
                                text: "加入白名单"
                                highlighted: true
                                onClicked: page.addJapaneseResidueAllowItem()
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(86, Math.min(190, residueAllowlistModel.count * 38 + 18))
                            radius: AppPalette.radiusMedium
                            color: AppPalette.cardAlt
                            border.color: AppPalette.lineColor
                            clip: true

                            ListView {
                                id: residueAllowList
                                anchors.fill: parent
                                anchors.margins: 8
                                model: residueAllowlistModel
                                spacing: AppStyle.spacingInline
                                clip: true

                                delegate: Rectangle {
                                    width: residueAllowList.width
                                    height: 32
                                    radius: 10
                                    color: AppPalette.surfaceRaised
                                    border.color: AppPalette.lineColor

                                    RowLayout {
                                        anchors.fill: parent
                                        anchors.leftMargin: 10
                                        anchors.rightMargin: 6
                                        spacing: AppStyle.spacingSmall

                                        Label {
                                            Layout.fillWidth: true
                                            text: fragment
                                            color: AppPalette.textColor
                                            font.pixelSize: AppStyle.fontBody
                                            elide: Text.ElideRight
                                        }

                                        Button {
                                            text: "删除"
                                            flat: true
                                            onClicked: page.removeJapaneseResidueAllowItem(fragment)
                                        }
                                    }
                                }
                            }

                            Label {
                                anchors.centerIn: parent
                                visible: residueAllowlistModel.count === 0
                                text: "暂无白名单片段"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: page.residueAllowlistStatus
                            visible: page.residueAllowlistStatus !== ""
                            color: page.residueAllowlistStatus.indexOf("失败") >= 0 || page.residueAllowlistStatus.indexOf("请输入") >= 0
                                   ? AppPalette.errorColor : AppPalette.successColor
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }
                    }
                }
            }

            SettingsPane {
                GroupBox {
                    title: "缓存策略"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingMedium

                        Label {
                            Layout.fillWidth: true
                            text: "跨模型缓存用于切换大模型后继续续译：已通过安全校验的旧模型译文会直接复用。需要完全用新模型重译当前 EPUB 时，请到任务页使用“清理当前 EPUB 缓存”。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }

                        CheckBox {
                            text: "允许切换模型后复用已翻译缓存"
                            checked: cfg ? cfg.allowTextCacheReuse : true
                            onCheckedChanged: {
                                if (cfg) {
                                    cfg.allowTextCacheReuse = checked
                                }
                            }
                        }
                    }
                }
            }

            SettingsPane {
                GroupBox {
                    title: "界面与推理"
                    Layout.fillWidth: true

                    Flow {
                        width: parent.width
                        spacing: AppStyle.spacingXXLarge

                        Label { text: "主题:" }
                        ComboBox {
                            model: ThemeRegistry.labels()
                            currentIndex: ThemeRegistry.indexFromName(cfg ? cfg.theme : "light")
                            onActivated: function(index) {
                                var name = ThemeRegistry.nameFromIndex(index)
                                if (cfg) cfg.theme = name
                            }
                        }
                        CheckBox {
                            text: "开启深度思考"
                            checked: cfg ? cfg.enableThinking : false
                            onCheckedChanged: { if (cfg) cfg.enableThinking = checked }
                        }
                    }
                }
            }

            SettingsPane {
                GroupBox {
                    title: "软件更新"
                    Layout.fillWidth: true

                    ColumnLayout {
                        width: parent.width
                        spacing: AppStyle.spacingMedium

                        Label {
                            Layout.fillWidth: true
                            text: "当前版本：V" + (page.updater ? page.updater.currentVersion : "未知")
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontBodyLarge
                            font.weight: Font.DemiBold
                        }

                        Label {
                            Layout.fillWidth: true
                            text: page.updateStatus
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }

                        ProgressBar {
                            Layout.fillWidth: true
                            visible: page.updater && page.updater.downloading
                            from: 0
                            to: 100
                            value: page.updateDownloadPercent
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingMedium

                            Button {
                                text: page.updater && page.updater.checking ? "检查中..." : "检查更新"
                                enabled: page.updater && !page.updaterBusy
                                onClicked: page.startUpdateCheck()
                            }

                            Button {
                                text: "打开发布页"
                                enabled: page.updater && !page.updater.downloading
                                onClicked: page.openUpdateRelease()
                            }

                            Button {
                                text: page.updater && page.updater.downloading
                                      ? ("下载中 " + page.updateDownloadPercent + "%")
                                      : "下载并安装"
                                highlighted: page.hasInstallerAsset() && page.updateInfo.isNewer
                                enabled: page.updater
                                         && page.hasInstallerAsset()
                                         && page.updateInfo.isNewer
                                         && !page.updaterBusy
                                onClicked: page.startUpdateDownload()
                            }

                            Item { Layout.fillWidth: true }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: "说明：检查更新不需要登录 GitHub；下载完成后会启动安装程序，并退出当前软件。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: updateDialog
        modal: true
        anchors.centerIn: parent
        width: Math.min(page.width - 64, 620)
        title: page.updateInfo && page.updateInfo.isNewer ? "发现新版本" : "软件更新"
        closePolicy: page.updater && page.updater.downloading ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: ColumnLayout {
            width: updateDialog.width - 48
            spacing: AppStyle.spacingLarge

            Label {
                Layout.fillWidth: true
                text: "当前版本 V" + (page.updateInfo.currentVersion || (page.updater ? page.updater.currentVersion : "未知"))
                      + "，最新版本 V" + (page.updateInfo.latestVersion || "未知")
                color: AppPalette.textColor
                font.pixelSize: AppStyle.fontBodyXLarge
                font.weight: Font.DemiBold
                wrapMode: Text.WordWrap
            }

            Label {
                Layout.fillWidth: true
                text: page.hasInstallerAsset()
                      ? ("安装包：" + page.updateInfo.assetName + "（" + page.updateInfo.assetSizeText + "）")
                      : "该 Release 没有找到 .exe 安装包，可打开发布页手动查看。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 180
                clip: true

                Label {
                    width: updateDialog.width - 72
                    text: page.updateInfo.releaseNotes || "没有发布说明。"
                    color: AppPalette.textColor
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                }
            }

            ProgressBar {
                Layout.fillWidth: true
                visible: page.updater && page.updater.downloading
                from: 0
                to: 100
                value: page.updateDownloadPercent
            }

            Label {
                Layout.fillWidth: true
                visible: page.updater && page.updater.downloading
                text: page.updateStatus
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingMedium

                Button {
                    text: "稍后"
                    enabled: !(page.updater && page.updater.downloading)
                    onClicked: updateDialog.close()
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: "打开发布页"
                    enabled: !(page.updater && page.updater.downloading)
                    onClicked: page.openUpdateRelease()
                }

                Button {
                    text: page.updater && page.updater.downloading
                          ? ("下载中 " + page.updateDownloadPercent + "%")
                          : "下载并安装"
                    highlighted: true
                    enabled: page.updater
                             && page.hasInstallerAsset()
                             && !(page.updater && page.updater.downloading)
                    onClicked: page.startUpdateDownload()
                }
            }
        }
    }

    function applyPreset(key) {
        if (!cfg) return
        page.activePreset = key
        page.applyingPreset = true
        var vals = cfg.getPerfPreset(key)
        if (vals.max_workers !== undefined) {
            cfg.maxWorkers = vals.max_workers
            cfg.batchSize = vals.batch_size
            cfg.maxBatchLength = vals.max_batch_length
            cfg.maxTextSizeForBatch = vals.max_text_size_for_batch
            cfg.apiTimeout = vals.api_timeout
        }
        page.applyingPreset = false

        var labels = {
            "default": "默认：稳定安全，适合所有账户",
            "balanced": "适中：推荐配置，效率与稳定性兼顾",
            "extreme": "极端：极限速度，高风险",
            "glm_free": "智谱免费版：低并发低批量，降低限流概率",
            "gemini_free": "Gemini 免费版：保守参数避免限流",
            "deepseek_paid": "DeepSeek 付费版：较高并发和批量",
            "hymt2_local": "Hy-MT2 本地：并发1、批量1、超时300，优先保证稳定保存"
        }
        presetHint.text = labels[key] || ("已应用: " + key)
    }

    function markCustom() {
        page.activePreset = "custom"
        presetHint.text = "参数已手动修改，当前为自定义性能参数"
    }

    function formatBytes(value) {
        var size = Number(value || 0)
        if (size <= 0) return "0 B"
        var units = ["B", "KB", "MB", "GB"]
        var idx = 0
        while (size >= 1024 && idx < units.length - 1) {
            size = size / 1024
            idx += 1
        }
        return (idx === 0 ? Math.round(size) : size.toFixed(1)) + " " + units[idx]
    }

    function hasInstallerAsset() {
        return !!(page.updateInfo && page.updateInfo.assetUrl && page.updateInfo.assetName)
    }

    function startUpdateCheck() {
        if (!page.updater) {
            page.updateStatus = "更新模块未加载。"
            return
        }
        page.updater.checkForUpdates()
    }

    function openUpdateRelease() {
        if (!page.updater) return
        var url = page.updateInfo && page.updateInfo.releaseUrl ? page.updateInfo.releaseUrl : page.updater.releasesUrl
        page.updater.openReleasePage(url)
    }

    function startUpdateDownload() {
        if (!page.updater) return
        if (!page.hasInstallerAsset()) {
            page.updateStatus = "没有找到可下载的 .exe 安装包，请打开发布页查看。"
            page.openUpdateRelease()
            return
        }
        page.updater.downloadInstaller(page.updateInfo.assetUrl, page.updateInfo.assetName)
    }

    function proofreadGenreIndex(value) {
        var idx = page.proofreadGenreValues.indexOf(value)
        return idx >= 0 ? idx : 0
    }

    function proofreadGenreValue(index) {
        return page.proofreadGenreValues[Math.max(0, Math.min(index, page.proofreadGenreValues.length - 1))]
    }

    function proofreadToneIndex(value) {
        var idx = page.proofreadToneValues.indexOf(value)
        return idx >= 0 ? idx : 0
    }

    function proofreadToneValue(index) {
        return page.proofreadToneValues[Math.max(0, Math.min(index, page.proofreadToneValues.length - 1))]
    }

    function proofreadProviderIndex(value) {
        var idx = page.proofreadProviderValues.indexOf(value)
        return idx >= 0 ? idx : 0
    }

    function proofreadProviderValue(index) {
        return page.proofreadProviderValues[Math.max(0, Math.min(index, page.proofreadProviderValues.length - 1))]
    }
}
