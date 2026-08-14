import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Effects
import ".."

Page {
    id: page
    padding: AppStyle.pagePadding
    background: Item {}

    property var cfg: null

    property var providerKeys: ["deepseek", "doubao", "sakura", "hymt2", "gemini", "glm", "wenxin", "longcat", "custom"]
    property var providerLabels: ["DeepSeek", "豆包 (火山引擎)", "Sakura (本地)", "Hy-MT2 (本地)", "Gemini", "GLM (智谱)", "文心一言 (千帆)", "LongCat 2.0 (美团)", "自定义"]
    property var providerHints: ({
        "deepseek": "DeepSeek：推荐主力翻译；付费版支持高并发批量。",
        "doubao": "Doubao：火山方舟 OpenAI 兼容接口。",
        "sakura": "Sakura：本地模型，无需 API Key。",
        "hymt2": "Hy-MT2：腾讯开源本地翻译模型，无需 API Key；Python 本地模式固定 CPU 默认 1/1；如需 CUDA，请使用 CUDA 版 llama-server.exe 外部模式，默认 4/4。",
        "gemini": "Gemini：不支持 thinking 参数；免费版易限流。",
        "glm": "GLM/智谱：免费版限流明显，建议用性能预设。",
        "wenxin": "文心一言/千帆：使用百度千帆 OpenAI 兼容接口；旧版 access_token RPC 接口不兼容。",
        "custom": "Custom：自定义 OpenAI 兼容接口。"
    })
    property string currentProvider: cfg ? cfg.provider : "deepseek"
    property string connectionResult: ""
    property bool isCustom: currentProvider === "custom"
    property bool isLocalProvider: currentProvider === "sakura" || currentProvider === "hymt2"
    property bool needsKey: !isLocalProvider
    property bool testing: false
    property var localModel: typeof LocalModelBridge !== "undefined" ? LocalModelBridge : null
    property var modelPromptPresets: []
    property string presetResult: ""
    property string presetCategoryFilter: "all"
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    onCfgChanged: page.refreshModelPromptPresets()

    Connections {
        target: TranslateBridge
        function onConnectionResult(msg) {
            page.connectionResult = msg
            page.testing = false
        }
    }

    function showLocalModelResult(result) {
        var message = result && result.message ? result.message : ""
        if (message === "") return
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(message) : ToastBridge.showError(message)
        }
    }

    function refreshModelPromptPresets() {
        if (!cfg || !cfg.getModelPromptPresets) {
            page.modelPromptPresets = []
            return
        }
        page.modelPromptPresets = cfg.getModelPromptPresets() || []
    }

    function currentModelPromptPresetText() {
        if (!cfg || !cfg.getCurrentModelPromptPresetMatch) return "当前配置未命中任何模型 / Prompt 预设。"
        var deps = [
            cfg.provider, cfg.apiUrl, cfg.model, cfg.maxWorkers, cfg.batchSize,
            cfg.maxBatchLength, cfg.maxTextSizeForBatch, cfg.apiTimeout,
            cfg.enableThinking, cfg.enableProofread, cfg.proofreadGenre, cfg.proofreadTone,
            cfg.proofreadProvider, cfg.proofreadApiUrl, cfg.proofreadModel,
            cfg.promptExtraInstruction, cfg.enablePromptExamples,
            cfg.enableLayeredGlossary, cfg.useGlobalGlossary, cfg.useGenreGlossary,
            cfg.useSeriesGlossary, cfg.useBookGlossary, cfg.seriesGlossaryName,
            cfg.bookGlossaryName, cfg.selectedGlossaryProfileIds, cfg.glossaryExtractionMode,
            cfg.hymt2GenerationMode, cfg.hymt2PromptMode, cfg.hymt2RuntimeMode,
            cfg.japaneseResiduePolicy
        ]
        var dependencyTracker = deps.length
        if (dependencyTracker < 0) return ""
        var match = cfg.getCurrentModelPromptPresetMatch()
        if (!match || !match.key) return "当前配置未命中任何模型 / Prompt 预设。"
        return "当前命中：" + (match.label || match.key) + " / " + (match.categoryLabel || "组合")
    }

    function applyModelPromptPreset(key) {
        if (!cfg || !cfg.applyModelPromptPreset) return
        var result = cfg.applyModelPromptPreset(key)
        page.currentProvider = cfg.provider
        page.isCustom = (page.currentProvider === "custom")
        page.isLocalProvider = (page.currentProvider === "sakura" || page.currentProvider === "hymt2")
        page.needsKey = !page.isLocalProvider
        page.connectionResult = result && result.ok
            ? ((result.message || "已应用模型/Prompt 预设") + "，请测试连接。")
            : ((result && result.message) || "应用模型/Prompt 预设失败")
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result && result.ok ? ToastBridge.showSuccess(result.message || "已应用模型/Prompt 预设")
                                : ToastBridge.showError((result && result.message) || "应用模型/Prompt 预设失败")
        }
    }

    function showPresetResult(result) {
        page.presetResult = (result && result.message) || ""
        if (typeof ToastBridge !== "undefined" && ToastBridge && page.presetResult !== "") {
            result && result.ok ? ToastBridge.showSuccess(page.presetResult)
                                : ToastBridge.showError(page.presetResult)
        }
        if (result && result.ok) page.refreshModelPromptPresets()
    }

    function saveCurrentModelPromptPreset(label, hint) {
        if (!cfg || !cfg.saveCurrentModelPromptPreset) return
        page.showPresetResult(cfg.saveCurrentModelPromptPreset(label || "", hint || ""))
    }

    function deleteModelPromptPreset(key) {
        if (!cfg || !cfg.deleteUserModelPromptPreset) return
        page.showPresetResult(cfg.deleteUserModelPromptPreset(key))
    }

    function localHyMt2UsesGpu() {
        if (!page.localModel) return false
        if (page.localModel.backendMode !== "server") return false
        if (page.localModel.gpuMode === "cuda") return true
        var status = String(page.localModel.gpuStatus || "")
        return page.localModel.gpuMode === "auto"
               && (status.indexOf("CUDA") >= 0 || status.indexOf("NVIDIA") >= 0 || status.indexOf("GPU") >= 0)
               && status.indexOf("未找到") < 0
               && status.indexOf("未检测到") < 0
               && status.indexOf("尚未检测") < 0
               && status.indexOf("回退") < 0
               && status.indexOf("CPU") < 0
    }

    function applyLocalHyMt2Config() {
        if (!cfg || !page.localModel) return
        var useGpu = page.localHyMt2UsesGpu()
        cfg.setProvider("hymt2")
        cfg.apiKey = "sk-local"
        cfg.apiUrl = page.localModel.localApiUrl
        cfg.model = page.localModel.modelName || "Hy-MT2-1.8B-Q4_K_M"
        cfg.hymt2RuntimeMode = useGpu ? "gpu" : "cpu"
        cfg.maxWorkers = useGpu ? 4 : 1
        cfg.batchSize = useGpu ? 4 : 1
        cfg.maxBatchLength = useGpu ? 1000 : 300
        cfg.maxTextSizeForBatch = useGpu ? 250 : 120
        cfg.apiTimeout = Math.max(cfg.apiTimeout || 0, 300)
        page.currentProvider = "hymt2"
        page.isCustom = false
        page.isLocalProvider = true
        page.needsKey = false
        page.connectionResult = useGpu
            ? "已应用 Hy-MT2 GPU 配置：并发4、批量4。请启动服务后测试连接。"
            : "已应用 Hy-MT2 CPU 配置：并发1、批量1。请启动服务后测试连接。"
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            ToastBridge.showSuccess(useGpu ? "已应用 Hy-MT2 GPU 配置" : "已应用 Hy-MT2 CPU 配置")
        }
    }

    function providerRatePresetKey(providerKey, runtimeMode) {
        var key = String(providerKey || "").toLowerCase()
        if (key !== "hymt2") return key
        var runtime = String(runtimeMode || (cfg ? cfg.hymt2RuntimeMode || "cpu" : "cpu")).toLowerCase()
        return runtime === "gpu" ? "hymt2_gpu" : "hymt2_cpu"
    }

    function providerRateTitle(providerKey, runtimeMode) {
        var key = page.providerRatePresetKey(providerKey, runtimeMode)
        if (key === "hymt2_gpu") return "当前预设：Hy-MT2 GPU"
        if (key === "hymt2_cpu") return "当前预设：Hy-MT2 CPU"
        if (key === "deepseek") return "当前预设：DeepSeek 推荐"
        if (key === "longcat") return "当前预设：LongCat 推荐"
        return "当前预设：通用性能参数"
    }

    function providerRateText(providerKey, runtimeMode) {
        if (!cfg || !cfg.getProviderRatePreset) return "暂无 provider 速率预设。"
        var key = page.providerRatePresetKey(providerKey, runtimeMode)
        var preset = cfg.getProviderRatePreset(key)
        if (!preset || Object.keys(preset).length === 0) {
            return "当前 provider 暂无独立速率预设，可继续沿用通用性能参数。"
        }
        var parts = []
        if (preset.hint) parts.push(preset.hint)
        if (preset.rpm || preset.tpm) {
            parts.push("RPM " + (preset.rpm || 0) + " / TPM " + (preset.tpm || 0))
        }
        if (preset.max_workers || preset.batch_size) {
            parts.push("并发 " + (preset.max_workers || 0) + " / 批量 " + (preset.batch_size || 0))
        }
        if (preset.api_timeout) {
            parts.push("超时 " + preset.api_timeout + " 秒")
        }
        return parts.join("；")
    }

    function applyProviderRatePreset(providerKey) {
        if (!cfg || !cfg.getProviderRatePreset || !cfg.getProviderDefaults) return
        var key = String(providerKey || "").toLowerCase()
        var preset = cfg.getProviderRatePreset(key)
        if (!preset || Object.keys(preset).length === 0) {
            return
        }
        var provider = key.indexOf("hymt2") === 0 ? "hymt2" : key
        cfg.setProvider(provider)
        if (provider === "hymt2") {
            cfg.apiKey = "sk-local"
        }
        var defaults = cfg.getProviderDefaults(provider)
        if (defaults && defaults.url !== undefined) {
            cfg.apiUrl = defaults.url || cfg.apiUrl
        }
        if (defaults && defaults.model !== undefined) {
            cfg.model = defaults.model || cfg.model
        }
        if (preset.max_workers !== undefined) cfg.maxWorkers = preset.max_workers
        if (preset.batch_size !== undefined) cfg.batchSize = preset.batch_size
        if (preset.max_batch_length !== undefined) cfg.maxBatchLength = preset.max_batch_length
        if (preset.max_text_size_for_batch !== undefined) cfg.maxTextSizeForBatch = preset.max_text_size_for_batch
        if (preset.api_timeout !== undefined) cfg.apiTimeout = preset.api_timeout
        if (provider === "hymt2" && preset.runtime_mode) {
            cfg.hymt2RuntimeMode = preset.runtime_mode
        }
        page.currentProvider = provider
        page.isCustom = (provider === "custom")
        page.isLocalProvider = (provider === "sakura" || provider === "hymt2")
        page.needsKey = !page.isLocalProvider
        page.connectionResult = (preset.label || provider) + " 已应用，请继续测试连接。"
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            ToastBridge.showSuccess(preset.label || "已应用 provider 预设")
        }
    }

    ScrollView {
        id: contentScroll
        anchors.fill: parent
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, contentScroll.availableWidth)
            spacing: AppStyle.spacingLarge

            ColumnLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingTight
            Label {
                text: "API 接口配置"
                color: AppPalette.textColor
                font.family: page.titleFont
                font.pixelSize: Math.max(30, AppStyle.fontPageTitle - 8)
                font.weight: Font.Bold
            }
            Label {
                text: "选择翻译模型供应商，并测试当前 API 配置是否可用。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontSmall
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: apiFormGrid.implicitHeight + 28
            Layout.minimumHeight: apiFormGrid.implicitHeight + 28
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

            GridLayout {
                id: apiFormGrid
                anchors.fill: parent
                anchors.margins: 14
                columns: 2
                rowSpacing: 10
                columnSpacing: 14

                FieldLabel { text: "供应商" }
                ComboBox {
                    id: providerCombo
                    Layout.fillWidth: true
                    model: providerLabels
                    currentIndex: Math.max(0, providerKeys.indexOf(page.currentProvider))
                    onCurrentIndexChanged: {
                        if (currentIndex < 0) return
                        var key = providerKeys[currentIndex]
                        if (cfg) cfg.setProvider(key)
                        page.currentProvider = key
                        page.isCustom = (key === "custom")
                        page.isLocalProvider = (key === "sakura" || key === "hymt2")
                        page.needsKey = !page.isLocalProvider
                        if (cfg && page.isLocalProvider) cfg.apiKey = "sk-local"
                        page.connectionResult = ""
                    }
                }

                FieldLabel {
                    text: "API Key"
                    visible: page.needsKey
                }
                TextField {
                    id: apiKeyField
                    Layout.fillWidth: true
                    visible: page.needsKey
                    echoMode: TextInput.Password
                    placeholderText: page.needsKey ? "请输入 API Key" : "本地模型无需 API Key"
                    text: cfg ? cfg.apiKey : ""
                    enabled: page.needsKey
                    selectByMouse: true
                    onTextChanged: { if (cfg) cfg.apiKey = text }
                }

                FieldLabel { text: "API URL" }
                TextField {
                    id: urlField
                    Layout.fillWidth: true
                    placeholderText: "https://api.xxx.com/chat/completions"
                    text: cfg ? cfg.apiUrl : ""
                    enabled: page.isCustom || page.currentProvider === "hymt2"
                    selectByMouse: true
                    onTextChanged: { if (cfg && (page.isCustom || page.currentProvider === "hymt2")) cfg.apiUrl = text }
                }

                FieldLabel { text: "Model" }
                TextField {
                    id: modelField
                    Layout.fillWidth: true
                    placeholderText: "model-name"
                    text: cfg ? cfg.model : ""
                    selectByMouse: true
                    onTextChanged: { if (cfg) cfg.model = text }
                }

                FieldLabel { text: "超时(秒)" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingLarge
                    SpinBox {
                        id: testTimeout
                        from: 1
                        to: 300
                        value: 15
                        editable: true
                    }
                    Button {
                        text: page.testing ? "测试中..." : "测试连接"
                        highlighted: true
                        enabled: !page.testing
                        onClicked: {
                            if (!cfg) return
                            page.connectionResult = "测试中..."
                            page.testing = true
                            TranslateBridge.testConnection(cfg.apiKey, cfg.apiUrl, cfg.model, testTimeout.value)
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: page.connectionResult !== "" ? 88 : 56
            radius: AppPalette.radiusLarge
            color: AppPalette.cardBg
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
                anchors.margins: 12
                spacing: AppStyle.spacingCompact

                Label {
                    Layout.fillWidth: true
                    text: page.providerHints[page.currentProvider] || ""
                    color: AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                }

                Label {
                    Layout.fillWidth: true
                    text: page.connectionResult
                    visible: page.connectionResult !== ""
                    color: page.connectionResult.includes("成功") ? AppPalette.successColor : AppPalette.errorColor
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                    font.weight: Font.DemiBold
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: providerRateColumn.implicitHeight + 32
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
                id: providerRateColumn
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingSmall

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    Label {
                        Layout.fillWidth: true
                        text: page.providerRateTitle(page.currentProvider, cfg ? cfg.hymt2RuntimeMode : "cpu")
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontSubHeader
                        font.weight: Font.DemiBold
                    }

                    Label {
                        text: "rpm / tpm / 并发 / 批量"
                        color: AppPalette.accentColor
                        font.pixelSize: AppStyle.fontTiny
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: providerRateText(page.currentProvider, cfg ? cfg.hymt2RuntimeMode : "cpu")
                    color: AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                }

                Flow {
                    Layout.fillWidth: true
                    width: parent.width
                    spacing: AppStyle.spacingSmall

                    Button {
                        text: "DeepSeek 推荐"
                        onClicked: applyProviderRatePreset("deepseek")
                    }
                    Button {
                        text: "LongCat 推荐"
                        onClicked: applyProviderRatePreset("longcat")
                    }
                    Button {
                        text: "Hy-MT2 CPU"
                        onClicked: applyProviderRatePreset("hymt2_cpu")
                    }
                    Button {
                        text: "Hy-MT2 GPU"
                        onClicked: applyProviderRatePreset("hymt2_gpu")
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: apiManagerSummaryRow.implicitHeight + 32
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

            RowLayout {
                id: apiManagerSummaryRow
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingMedium

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 96
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
                                text: "模型 / Prompt 预设"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSubHeader
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                text: page.modelPromptPresets && page.modelPromptPresets.length > 0
                                      ? "当前可用预设 " + page.modelPromptPresets.length + " 个；应用、导入、导出在弹窗中完成。"
                                      : "暂无可用预设；可保存当前配置为自定义预设。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: page.currentModelPromptPresetText()
                                color: AppPalette.accentColor
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideRight
                            }
                        }

                        Button {
                            text: "管理"
                            onClicked: modelPresetDialog.open()
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 96
                    radius: AppPalette.radiusMedium
                    color: page.localModel && page.localModel.running ? AppStyle.statusSuccessBg : AppPalette.cardBg
                    border.color: page.localModel && page.localModel.running ? AppPalette.successColor : AppPalette.lineColor
                    visible: page.localModel !== null

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingMedium

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingTight

                            Label {
                                text: "Hy-MT2 本地模型"
                                color: page.localModel && page.localModel.running ? AppPalette.successColor : AppPalette.textColor
                                font.pixelSize: AppStyle.fontSubHeader
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                text: page.localModel
                                      ? ((page.localModel.running ? "本地服务运行中；" : "本地服务未运行；") + (page.localModel.backendMode === "server" ? "llama-server 外部模式" : "Python CPU 模式"))
                                      : "本地模型模块未加载。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontCaption
                                elide: Text.ElideRight
                            }
                        }

                        Button {
                            text: "管理"
                            onClicked: localModelDialog.open()
                        }
                    }
                }
            }
        }

        }
    }

    Dialog {
        id: modelPresetDialog
        title: "模型 / Prompt 预设"
        modal: true
        width: Math.max(760, Math.min(1080, page.width - 48))
        height: Math.max(480, Math.min(720, page.height - 72))
        x: Math.round((page.width - width) / 2)
        y: Math.round((page.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: page.refreshModelPromptPresets()

        ScrollView {
            width: modelPresetDialog.width - 48
            height: modelPresetDialog.height - 96
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AsNeeded
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: Math.max(0, modelPresetDialog.width - 72)
                spacing: AppStyle.spacingMedium
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: modelPresetColumn.implicitHeight + 32
            Layout.minimumHeight: modelPresetColumn.implicitHeight + 32
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
                id: modelPresetColumn
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingSmall

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    Label {
                        Layout.fillWidth: true
                        text: "模型 / Prompt 预设"
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontSubHeader
                        font.weight: Font.DemiBold
                    }

                    Button {
                        text: "刷新"
                        onClicked: page.refreshModelPromptPresets()
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: "预设分为模型、Prompt、组合三类。应用预设会写入当前任务配置；导出和保存自定义预设时会自动排除 API Key。"
                    color: AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                }

                Flow {
                    Layout.fillWidth: true
                    width: parent.width
                    spacing: AppStyle.spacingSmall

                    Button {
                        text: "保存当前为预设"
                        onClicked: savePresetDialog.open()
                    }
                    Button {
                        text: "导入预设"
                        onClicked: presetImportDialog.open()
                    }
                    Button {
                        text: "导出当前"
                        onClicked: presetExportCurrentDialog.open()
                    }
                    Button {
                        text: "导出自定义"
                        onClicked: presetExportUserDialog.open()
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    width: parent.width
                    spacing: AppStyle.spacingSmall

                    Repeater {
                        model: [
                            { key: "all", label: "全部" },
                            { key: "workflow", label: "组合" },
                            { key: "model", label: "模型" },
                            { key: "prompt", label: "Prompt" }
                        ]
                        delegate: Button {
                            text: modelData.label
                            highlighted: page.presetCategoryFilter === modelData.key
                            onClicked: page.presetCategoryFilter = modelData.key
                        }
                    }
                }

                Flow {
                    id: modelPresetFlow
                    Layout.fillWidth: true
                    width: parent.width
                    spacing: AppStyle.spacingSmall

                    Repeater {
                        model: page.modelPromptPresets
                        delegate: Rectangle {
                            visible: page.presetCategoryFilter === "all" || modelData.category === page.presetCategoryFilter
                            width: modelPresetFlow.width >= 760 ? Math.floor((modelPresetFlow.width - 2 * AppStyle.spacingSmall) / 3)
                                                               : (modelPresetFlow.width >= 500 ? Math.floor((modelPresetFlow.width - AppStyle.spacingSmall) / 2)
                                                                                                : modelPresetFlow.width)
                            height: visible ? presetCardColumn.implicitHeight + 18 : 0
                            radius: AppPalette.radiusMedium
                            color: AppPalette.cardBg
                            border.color: AppPalette.borderColor

                            ColumnLayout {
                                id: presetCardColumn
                                anchors.fill: parent
                                anchors.margins: 9
                                spacing: 5

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Label {
                                        Layout.fillWidth: true
                                        text: modelData.label || modelData.key
                                        color: AppPalette.textColor
                                        elide: Text.ElideRight
                                        font.pixelSize: AppStyle.fontSmall
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        text: modelData.categoryLabel || "组合"
                                        color: AppPalette.accentColor
                                        font.pixelSize: AppStyle.fontTiny
                                    }
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: modelData.hint || ""
                                    color: AppPalette.mutedText
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                    font.pixelSize: AppStyle.fontTiny
                                }

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 6

                                    Button {
                                        Layout.fillWidth: true
                                        text: "应用"
                                        onClicked: page.applyModelPromptPreset(modelData.key)
                                    }
                                    Button {
                                        text: "删除"
                                        visible: modelData.user === true
                                        onClicked: page.deleteModelPromptPreset(modelData.key)
                                    }
                                }
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: page.presetResult !== "" ? page.presetResult
                                                     : (page.modelPromptPresets && page.modelPromptPresets.length > 0 ? "当前可用预设: " + page.modelPromptPresets.length + " 个" : "暂无可用预设")
                    color: page.presetResult.indexOf("失败") >= 0 || page.presetResult.indexOf("不存在") >= 0 ? AppPalette.errorColor : AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontTiny
                }
            }
        }
            }
        }
    }

    Dialog {
        id: localModelDialog
        title: "Hy-MT2 本地模型"
        modal: true
        width: Math.max(780, Math.min(1100, page.width - 48))
        height: Math.max(520, Math.min(760, page.height - 72))
        x: Math.round((page.width - width) / 2)
        y: Math.round((page.height - height) / 2)
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        ScrollView {
            width: localModelDialog.width - 48
            height: localModelDialog.height - 96
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AsNeeded
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: Math.max(0, localModelDialog.width - 72)
                spacing: AppStyle.spacingMedium
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: localModelColumn.implicitHeight + 36
            Layout.minimumHeight: localModelColumn.implicitHeight + 36
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
            visible: page.localModel !== null

            ColumnLayout {
                id: localModelColumn
                anchors.fill: parent
                anchors.margins: 18
                spacing: AppStyle.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    Label {
                        Layout.fillWidth: true
                        text: "Hy-MT2 本地模型"
                        color: AppPalette.textColor
                        font.family: page.titleFont
                        font.pixelSize: AppStyle.fontSubHeader
                        font.weight: Font.DemiBold
                    }

                    Label {
                        text: page.localModel && page.localModel.running ? "运行中" : "未运行"
                        color: page.localModel && page.localModel.running ? AppPalette.successColor : AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
                        font.weight: Font.DemiBold
                    }
                }

                Label {
                    Layout.fillWidth: true
                    text: "可以由本软件下载官方 Hy-MT2-1.8B-GGUF 仓库中的 Q4_K_M 模型，也可以手动选择已下载的模型文件。1.25bit/2bit GGUF 当前 llama 不支持，默认不再推荐下载；7B 模型仅建议在高配置电脑上手动选择。"
                    color: AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    rowSpacing: 10
                    columnSpacing: 12

                    FieldLabel { text: "模型下载" }
                    TextField {
                        id: modelDownloadUrlField
                        Layout.fillWidth: true
                        text: page.localModel ? page.localModel.defaultModelUrl : ""
                        selectByMouse: true
                        placeholderText: "Hy-MT2 GGUF 下载 URL"
                    }
                    RowLayout {
                        spacing: AppStyle.spacingSmall
                        Button {
                            text: "使用镜像"
                            enabled: page.localModel && !page.localModel.downloading
                            onClicked: {
                                if (!page.localModel) return
                                modelDownloadUrlField.text = page.localModel.mirrorModelUrl
                            }
                        }
                        Button {
                            text: page.localModel && page.localModel.downloading ? "下载中..." : "下载模型"
                            highlighted: true
                            enabled: page.localModel && !page.localModel.downloading
                            onClicked: {
                                if (!page.localModel) return
                                page.showLocalModelResult(page.localModel.startModelDownload(modelDownloadUrlField.text))
                            }
                        }
                        Button {
                            text: "取消"
                            enabled: page.localModel && page.localModel.downloading
                            onClicked: {
                                if (!page.localModel) return
                                page.showLocalModelResult(page.localModel.cancelModelDownload())
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall
                    visible: page.localModel && (page.localModel.downloading || page.localModel.downloadProgress > 0)

                    ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: page.localModel ? page.localModel.downloadProgress : 0
                    }

                    Label {
                        Layout.preferredWidth: 150
                        text: page.localModel ? (page.localModel.downloadProgress + "%  " + page.localModel.downloadBytesText) : ""
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
                        horizontalAlignment: Text.AlignRight
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    rowSpacing: 10
                    columnSpacing: 12

                    FieldLabel { text: "运行模式" }
                    ComboBox {
                        id: backendModeCombo
                        Layout.fillWidth: true
                        model: ["Python 本地模式", "llama-server.exe 模式"]
                        currentIndex: page.localModel && page.localModel.backendMode === "server" ? 1 : 0
                        onActivated: {
                            if (!page.localModel) return
                            page.showLocalModelResult(page.localModel.setBackendMode(currentIndex === 0 ? "python" : "server"))
                        }
                    }
                    Button {
                        text: "检测 GPU"
                        enabled: page.localModel && page.localModel.backendMode === "server"
                        onClicked: {
                            if (!page.localModel) return
                            page.showLocalModelResult(page.localModel.detectGpuBackend())
                        }
                    }

                    FieldLabel { text: "GPU 模式" }
                    ComboBox {
                        id: gpuModeCombo
                        Layout.fillWidth: true
                        model: ["自动", "CUDA", "CPU"]
                        enabled: page.localModel && page.localModel.backendMode === "server"
                        currentIndex: {
                            if (!page.localModel) return 0
                            if (page.localModel.gpuMode === "cuda") return 1
                            if (page.localModel.gpuMode === "cpu") return 2
                            return 0
                        }
                        onActivated: {
                            if (!page.localModel) return
                            var mode = currentIndex === 1 ? "cuda" : (currentIndex === 2 ? "cpu" : "auto")
                            page.showLocalModelResult(page.localModel.setGpuMode(mode))
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: page.localModel ? page.localModel.gpuStatus : ""
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontSmall
                    }

                    Item {}
                    Label {
                        Layout.fillWidth: true
                        Layout.columnSpan: 2
                        text: page.localModel && page.localModel.backendMode === "server"
                              ? "GPU 模式仅对 llama-server.exe 外部模式生效：CUDA 会追加 --gpu-layers 999，CPU 会追加 --gpu-layers 0。注意必须使用 CUDA 版 llama-server.exe，CPU 版程序不会真正调用显卡。"
                              : "Python 本地模式固定 CPU：当前 llama-cpp-python 不支持 CUDA，GPU 模式在此模式下不会生效。"
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontSmall
                    }

                    FieldLabel { text: "性能配置" }
                    Label {
                        Layout.fillWidth: true
                        text: page.localHyMt2UsesGpu()
                              ? "外部 CUDA 模式：默认并发4、批量4；翻译器最大允许并发6、批量8。超过 6/6 可能增加超时、OOM 或残留风险。"
                              : "CPU 模式：Python 本地模式固定 CPU；外部 CPU 模式会追加 --gpu-layers 0。默认并发1、批量1，优先稳定保存。"
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontSmall
                    }
                    Item {}

                    FieldLabel { text: "生成模式" }
                    ComboBox {
                        id: hymt2GenerationModeCombo
                        Layout.fillWidth: true
                        model: ["稳定模式", "官方推荐模式"]
                        currentIndex: cfg && cfg.hymt2GenerationMode === "official" ? 1 : 0
                        onActivated: {
                            if (!cfg) return
                            cfg.hymt2GenerationMode = currentIndex === 1 ? "official" : "stable"
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: cfg && cfg.hymt2GenerationMode === "official"
                              ? "temperature=0.7, top_p=0.6, top_k=20, repetition_penalty=1.05, max_tokens=4096；可能更贴近官方示例，但稳定性需自行测试。"
                              : "temperature=0.1, top_p=0.3；不传 top_k/repetition_penalty/max_tokens；默认推荐，优先减少超时、残留和格式失控。"
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontSmall
                    }

                    FieldLabel { text: "Prompt 模式" }
                    ComboBox {
                        id: hymt2PromptModeCombo
                        Layout.fillWidth: true
                        model: ["官方简洁模板", "项目文学模板"]
                        currentIndex: cfg && cfg.hymt2PromptMode === "project" ? 1 : 0
                        onActivated: {
                            if (!cfg) return
                            cfg.hymt2PromptMode = currentIndex === 1 ? "project" : "official"
                        }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: cfg && cfg.hymt2PromptMode === "project"
                              ? "使用 QML/V4 原有文学翻译长 Prompt；表达更细，但 Hy-MT2 小模型更容易残留或失控。"
                              : "使用 Hy-MT2 官方风格短 Prompt：只要求翻译为简体中文并输出结果，默认推荐。"
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontSmall
                    }

                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 3
                    rowSpacing: 10
                    columnSpacing: 12

                    FieldLabel { text: "GGUF 模型" }
                    TextField {
                        Layout.fillWidth: true
                        text: page.localModel ? page.localModel.modelPath : ""
                        readOnly: true
                        selectByMouse: true
                        placeholderText: "请选择 Hy-MT2 GGUF 模型文件"
                    }
                    Button {
                        text: "选择模型"
                        onClicked: modelFileDialog.open()
                    }

                    FieldLabel { text: "llama-server"; visible: page.localModel && page.localModel.backendMode === "server" }
                    TextField {
                        Layout.fillWidth: true
                        text: page.localModel ? page.localModel.serverPath : ""
                        readOnly: true
                        selectByMouse: true
                        placeholderText: "可自动查找 PATH，或手动选择 llama-server.exe"
                        visible: page.localModel && page.localModel.backendMode === "server"
                    }
                    RowLayout {
                        spacing: AppStyle.spacingSmall
                        visible: page.localModel && page.localModel.backendMode === "server"
                        Button {
                            text: "自动查找"
                            onClicked: {
                                if (!page.localModel) return
                                page.showLocalModelResult(page.localModel.findLlamaServer())
                            }
                        }
                        Button {
                            text: "手动选择"
                            onClicked: serverFileDialog.open()
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    Button {
                        text: page.localModel && page.localModel.running ? "停止本地服务" : "启动本地服务"
                        highlighted: !(page.localModel && page.localModel.running)
                        onClicked: {
                            if (!page.localModel) return
                            page.showLocalModelResult(page.localModel.running ? page.localModel.stopServer()
                                                                               : page.localModel.startServer())
                        }
                    }

                    Button {
                        text: "应用到 Hy-MT2 配置"
                        onClicked: page.applyLocalHyMt2Config()
                    }

                    Button {
                        text: "测试本地连接"
                        enabled: !page.testing
                        onClicked: {
                            if (!cfg || !page.localModel) return
                            page.applyLocalHyMt2Config()
                            page.connectionResult = "测试中..."
                            page.testing = true
                            TranslateBridge.testConnection(cfg.apiKey, cfg.apiUrl, cfg.model, testTimeout.value)
                        }
                    }

                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    text: page.localModel ? page.localModel.statusMessage : ""
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
        id: savePresetDialog
        title: "保存当前模型 / Prompt 预设"
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        width: Math.max(360, Math.min(520, page.width - 48))

        ColumnLayout {
            width: savePresetDialog.width - 48
            spacing: AppStyle.spacingSmall

            Label {
                Layout.fillWidth: true
                text: "将当前 provider、模型、并发批量、Prompt、校对与日文残留策略保存为自定义预设。API Key 不会保存。"
                wrapMode: Text.WordWrap
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontSmall
            }
            TextField {
                id: savePresetName
                Layout.fillWidth: true
                placeholderText: "预设名称，例如 DeepSeek 我的稳定配置"
                selectByMouse: true
            }
            TextField {
                id: savePresetHint
                Layout.fillWidth: true
                placeholderText: "备注，可选"
                selectByMouse: true
            }
        }

        onAccepted: {
            page.saveCurrentModelPromptPreset(savePresetName.text, savePresetHint.text)
            savePresetName.text = ""
            savePresetHint.text = ""
        }
    }

    FileDialog {
        id: presetImportDialog
        title: "导入模型 / Prompt 预设 JSON"
        nameFilters: ["JSON (*.json)", "全部文件 (*)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (!cfg || !selectedFile) return
            page.showPresetResult(cfg.importModelPromptPresets(FilePathUtils.normalizeFileUrl(selectedFile)))
        }
    }

    FileDialog {
        id: presetExportCurrentDialog
        title: "导出当前模型 / Prompt 预设"
        nameFilters: ["JSON (*.json)", "全部文件 (*)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (!cfg || !selectedFile) return
            var p = FilePathUtils.normalizeFileUrl(selectedFile)
            if (!p.toLowerCase().endsWith(".json")) p += ".json"
            page.showPresetResult(cfg.exportCurrentModelPromptPreset(p, savePresetName.text || "当前翻译配置"))
        }
    }

    FileDialog {
        id: presetExportUserDialog
        title: "导出自定义模型 / Prompt 预设"
        nameFilters: ["JSON (*.json)", "全部文件 (*)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (!cfg || !selectedFile) return
            var p = FilePathUtils.normalizeFileUrl(selectedFile)
            if (!p.toLowerCase().endsWith(".json")) p += ".json"
            page.showPresetResult(cfg.exportModelPromptPresets(p))
        }
    }

    FileDialog {
        id: modelFileDialog
        title: "选择 Hy-MT2 GGUF 模型文件"
        nameFilters: ["GGUF 模型 (*.gguf)", "全部文件 (*)"]
        onAccepted: {
            if (!page.localModel) return
            page.showLocalModelResult(page.localModel.setModelPath(FilePathUtils.normalizeFileUrl(selectedFile)))
        }
    }

    FileDialog {
        id: serverFileDialog
        title: "选择 llama-server 程序"
        nameFilters: ["可执行文件 (*.exe)", "全部文件 (*)"]
        onAccepted: {
            if (!page.localModel) return
            page.showLocalModelResult(page.localModel.setServerPath(FilePathUtils.normalizeFileUrl(selectedFile)))
        }
    }

    component FieldLabel: Label {
        Layout.preferredWidth: 90
        color: AppPalette.textColor
        font.pixelSize: AppStyle.fontBody
        font.weight: Font.DemiBold
        verticalAlignment: Text.AlignVCenter
    }

    Component.onCompleted: {
        page.refreshModelPromptPresets()
    }
}
