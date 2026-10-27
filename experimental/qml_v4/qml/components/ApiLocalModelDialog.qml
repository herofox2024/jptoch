import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Effects
import ".."

// Hy-MT2 本地模型管理弹窗。
// 数据全部来自传入的 localModel 后端对象；本组件不直接引用全局桥接，
// 通过信号把用户的显式动作交给宿主页面处理。
Dialog {
    id: root

    property var localModel: null
    property var cfg: null
    property bool testing: false
    property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    // 宿主页面提供的动作
    signal applyConfigRequested()
    signal testConnectionRequested()

    readonly property bool compactLayout: width < 900

    title: "Hy-MT2 本地模型"
    modal: true
    width: Math.max(780, Math.min(1100, (ApplicationWindow.window ? ApplicationWindow.window.width : 1200) - 48))
    height: Math.max(520, Math.min(760, (ApplicationWindow.window ? ApplicationWindow.window.height : 800) - 72))
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    function showResult(result) {
        var message = result && result.message ? result.message : ""
        if (message === "") return
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(message) : ToastBridge.showError(message)
        }
    }

    function usesGpu() {
        if (!root.localModel) return false
        if (root.localModel.backendMode !== "server") return false
        if (root.localModel.gpuMode === "cuda") return true
        var status = String(root.localModel.gpuStatus || "")
        return root.localModel.gpuMode === "auto"
               && (status.indexOf("CUDA") >= 0 || status.indexOf("NVIDIA") >= 0 || status.indexOf("GPU") >= 0)
               && status.indexOf("未找到") < 0
               && status.indexOf("未检测到") < 0
               && status.indexOf("尚未检测") < 0
               && status.indexOf("回退") < 0
               && status.indexOf("CPU") < 0
    }

    ScrollView {
        width: root.width - 48
        height: root.height - 96
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, root.width - 72)
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
                visible: root.localModel !== null

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
                            font.family: root.titleFont
                            font.pixelSize: AppStyle.fontSubHeader
                            font.weight: Font.DemiBold
                        }

                        Label {
                            text: root.localModel && root.localModel.running ? "运行中" : "未运行"
                            color: root.localModel && root.localModel.running ? AppPalette.successColor : AppPalette.mutedText
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
                        columns: root.compactLayout ? 1 : 3
                        rowSpacing: 10
                        columnSpacing: 12

                        FieldLabel { text: "模型下载" }
                        TextField {
                            id: modelDownloadUrlField
                            Layout.fillWidth: true
                            text: root.localModel ? root.localModel.defaultModelUrl : ""
                            selectByMouse: true
                            placeholderText: "Hy-MT2 GGUF 下载 URL"
                        }
                        RowLayout {
                            spacing: AppStyle.spacingSmall
                            Button {
                                text: "使用镜像"
                                enabled: root.localModel && !root.localModel.downloading
                                onClicked: {
                                    if (!root.localModel) return
                                    modelDownloadUrlField.text = root.localModel.mirrorModelUrl
                                }
                            }
                            Button {
                                text: root.localModel && root.localModel.downloading ? "下载中..." : "下载模型"
                                highlighted: true
                                enabled: root.localModel && !root.localModel.downloading
                                onClicked: {
                                    if (!root.localModel) return
                                    root.showResult(root.localModel.startModelDownload(modelDownloadUrlField.text))
                                }
                            }
                            Button {
                                text: "取消"
                                enabled: root.localModel && root.localModel.downloading
                                onClicked: {
                                    if (!root.localModel) return
                                    root.showResult(root.localModel.cancelModelDownload())
                                }
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingSmall
                        visible: root.localModel && (root.localModel.downloading || root.localModel.downloadProgress > 0)

                        ProgressBar {
                            Layout.fillWidth: true
                            from: 0
                            to: 100
                            value: root.localModel ? root.localModel.downloadProgress : 0
                        }

                        Label {
                            Layout.preferredWidth: 150
                            text: root.localModel ? (root.localModel.downloadProgress + "%  " + root.localModel.downloadBytesText) : ""
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontSmall
                            horizontalAlignment: Text.AlignRight
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.compactLayout ? 1 : 3
                        rowSpacing: 10
                        columnSpacing: 12

                        FieldLabel { text: "运行模式" }
                        ComboBox {
                            id: backendModeCombo
                            Layout.fillWidth: true
                            model: ["Python 本地模式", "llama-server.exe 模式"]
                            currentIndex: root.localModel && root.localModel.backendMode === "server" ? 1 : 0
                            onActivated: {
                                if (!root.localModel) return
                                root.showResult(root.localModel.setBackendMode(currentIndex === 0 ? "python" : "server"))
                            }
                        }
                        Button {
                            text: "检测 GPU"
                            enabled: root.localModel && root.localModel.backendMode === "server"
                            onClicked: {
                                if (!root.localModel) return
                                root.showResult(root.localModel.detectGpuBackend())
                            }
                        }

                        FieldLabel { text: "GPU 模式" }
                        ComboBox {
                            id: gpuModeCombo
                            Layout.fillWidth: true
                            model: ["自动", "CUDA", "CPU"]
                            enabled: root.localModel && root.localModel.backendMode === "server"
                            currentIndex: {
                                if (!root.localModel) return 0
                                if (root.localModel.gpuMode === "cuda") return 1
                                if (root.localModel.gpuMode === "cpu") return 2
                                return 0
                            }
                            onActivated: {
                                if (!root.localModel) return
                                var mode = currentIndex === 1 ? "cuda" : (currentIndex === 2 ? "cpu" : "auto")
                                root.showResult(root.localModel.setGpuMode(mode))
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: root.localModel ? root.localModel.gpuStatus : ""
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }

                        Item { visible: !root.compactLayout }
                        Label {
                            Layout.fillWidth: true
                            Layout.columnSpan: root.compactLayout ? 1 : 2
                            text: root.localModel && root.localModel.backendMode === "server"
                                  ? "GPU 模式仅对 llama-server.exe 外部模式生效：CUDA 会追加 --gpu-layers 999，CPU 会追加 --gpu-layers 0。注意必须使用 CUDA 版 llama-server.exe，CPU 版程序不会真正调用显卡。"
                                  : "Python 本地模式固定 CPU：当前 llama-cpp-python 不支持 CUDA，GPU 模式在此模式下不会生效。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }

                        FieldLabel { text: "性能配置" }
                        Label {
                            Layout.fillWidth: true
                            text: root.usesGpu()
                                  ? "外部 CUDA 模式：默认并发4、批量4；翻译器最大允许并发6、批量8。超过 6/6 可能增加超时、OOM 或残留风险。"
                                  : "CPU 模式：Python 本地模式固定 CPU；外部 CPU 模式会追加 --gpu-layers 0。默认并发1、批量1，优先稳定保存。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }
                        Item { visible: !root.compactLayout }

                        FieldLabel { text: "生成模式" }
                        ComboBox {
                            id: hymt2GenerationModeCombo
                            Layout.fillWidth: true
                            model: ["稳定模式", "官方推荐模式"]
                            currentIndex: root.cfg && root.cfg.hymt2GenerationMode === "official" ? 1 : 0
                            onActivated: {
                                if (!root.cfg) return
                                root.cfg.hymt2GenerationMode = currentIndex === 1 ? "official" : "stable"
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: root.cfg && root.cfg.hymt2GenerationMode === "official"
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
                            currentIndex: root.cfg && root.cfg.hymt2PromptMode === "project" ? 1 : 0
                            onActivated: {
                                if (!root.cfg) return
                                root.cfg.hymt2PromptMode = currentIndex === 1 ? "project" : "official"
                            }
                        }
                        Label {
                            Layout.fillWidth: true
                            text: root.cfg && root.cfg.hymt2PromptMode === "project"
                                  ? "使用 QML/V4 原有文学翻译长 Prompt；表达更细，但 Hy-MT2 小模型更容易残留或失控。"
                                  : "使用 Hy-MT2 官方风格短 Prompt：只要求翻译为简体中文并输出结果，默认推荐。"
                            color: AppPalette.mutedText
                            wrapMode: Text.WordWrap
                            font.pixelSize: AppStyle.fontSmall
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        columns: root.compactLayout ? 1 : 3
                        rowSpacing: 10
                        columnSpacing: 12

                        FieldLabel { text: "GGUF 模型" }
                        TextField {
                            Layout.fillWidth: true
                            text: root.localModel ? root.localModel.modelPath : ""
                            readOnly: true
                            selectByMouse: true
                            placeholderText: "请选择 Hy-MT2 GGUF 模型文件"
                        }
                        Button {
                            text: "选择模型"
                            onClicked: modelFileDialog.open()
                        }

                        FieldLabel { text: "llama-server"; visible: root.localModel && root.localModel.backendMode === "server" }
                        TextField {
                            Layout.fillWidth: true
                            text: root.localModel ? root.localModel.serverPath : ""
                            readOnly: true
                            selectByMouse: true
                            placeholderText: "可自动查找 PATH，或手动选择 llama-server.exe"
                            visible: root.localModel && root.localModel.backendMode === "server"
                        }
                        RowLayout {
                            spacing: AppStyle.spacingSmall
                            visible: root.localModel && root.localModel.backendMode === "server"
                            Button {
                                text: "自动查找"
                                onClicked: {
                                    if (!root.localModel) return
                                    root.showResult(root.localModel.findLlamaServer())
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
                            text: root.localModel && root.localModel.running ? "停止本地服务" : "启动本地服务"
                            highlighted: !(root.localModel && root.localModel.running)
                            onClicked: {
                                if (!root.localModel) return
                                root.showResult(root.localModel.running ? root.localModel.stopServer()
                                                                       : root.localModel.startServer())
                            }
                        }

                        Button {
                            text: "应用到 Hy-MT2 配置"
                            onClicked: root.applyConfigRequested()
                        }

                        Button {
                            text: "测试本地连接"
                            enabled: !root.testing
                            onClicked: root.testConnectionRequested()
                        }

                        Item { Layout.fillWidth: true }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.localModel ? root.localModel.statusMessage : ""
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
            if (!root.localModel) return
            root.showResult(root.localModel.setModelPath(FilePathUtils.normalizeFileUrl(selectedFile)))
        }
    }

    FileDialog {
        id: serverFileDialog
        title: "选择 llama-server 程序"
        nameFilters: ["可执行文件 (*.exe)", "全部文件 (*)"]
        onAccepted: {
            if (!root.localModel) return
            root.showResult(root.localModel.setServerPath(FilePathUtils.normalizeFileUrl(selectedFile)))
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
