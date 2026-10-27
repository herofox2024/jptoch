import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Effects
import ".."
import "../components"

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
            cfg.enablePolish,
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

    ApiModelPresetDialog {
        id: modelPresetDialog
        presets: page.modelPromptPresets
        resultText: page.presetResult
        categoryFilter: page.presetCategoryFilter
        titleFont: page.titleFont
        onRefreshRequested: page.refreshModelPromptPresets()
        onApplyRequested: function(presetKey) { page.applyModelPromptPreset(presetKey) }
        onDeleteRequested: function(presetKey) { page.deleteModelPromptPreset(presetKey) }
        onSaveRequested: function(label, hint) { page.saveCurrentModelPromptPreset(label, hint) }
        onImportRequested: function(path) {
            if (!cfg) return
            page.showPresetResult(cfg.importModelPromptPresets(path))
        }
        onExportCurrentRequested: function(path, label) {
            if (!cfg) return
            page.showPresetResult(cfg.exportCurrentModelPromptPreset(path, label))
        }
        onExportUserRequested: function(path) {
            if (!cfg) return
            page.showPresetResult(cfg.exportModelPromptPresets(path))
        }
    }

    ApiLocalModelDialog {
        id: localModelDialog
        localModel: page.localModel
        cfg: page.cfg
        testing: page.testing
        titleFont: page.titleFont
        onApplyConfigRequested: page.applyLocalHyMt2Config()
        onTestConnectionRequested: {
            if (!cfg || !page.localModel) return
            page.applyLocalHyMt2Config()
            page.connectionResult = "测试中..."
            page.testing = true
            TranslateBridge.testConnection(cfg.apiKey, cfg.apiUrl, cfg.model, testTimeout.value)
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
