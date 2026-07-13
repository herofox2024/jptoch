import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Dialogs
import QtQuick.Layouts
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
        "hymt2": "Hy-MT2：腾讯开源本地翻译模型，无需 API Key；可使用 Python 本地模式或 llama-server.exe 模式，默认使用并发1、批量1的稳定模式。",
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
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

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

    function applyLocalHyMt2Config() {
        if (!cfg || !page.localModel) return
        cfg.setProvider("hymt2")
        cfg.apiKey = "sk-local"
        cfg.apiUrl = page.localModel.localApiUrl
        cfg.model = page.localModel.modelName || "Hy-MT2-1.8B-Q4_K_M"
        page.currentProvider = "hymt2"
        page.isCustom = false
        page.isLocalProvider = true
        page.needsKey = false
        page.connectionResult = "已应用 Hy-MT2 本地配置，请启动服务后测试连接。"
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            ToastBridge.showSuccess("已应用 Hy-MT2 本地配置")
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
                font.weight: Font.DemiBold
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
            Layout.preferredHeight: localModelColumn.implicitHeight + 36
            Layout.minimumHeight: localModelColumn.implicitHeight + 36
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor
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
                    text: "可以由本软件下载 Hy-MT2 Q4_K_M GGUF 模型，也可以手动选择已下载的模型文件。1.25bit/2bit GGUF 当前 llama 不支持，默认不再推荐下载；请优先使用 Q4_K_M。"
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
                        enabled: page.localModel
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
}
