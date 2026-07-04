import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import ".."

Page {
    id: page
    padding: AppStyle.pagePadding
    background: Item {}

    property var cfg: null

    property var providerKeys: ["deepseek", "doubao", "sakura", "gemini", "glm", "wenxin", "longcat", "custom"]
    property var providerLabels: ["DeepSeek", "豆包 (火山引擎)", "Sakura (本地)", "Gemini", "GLM (智谱)", "文心一言 (千帆)", "LongCat 2.0 (美团)", "自定义"]
    property var providerHints: ({
        "deepseek": "DeepSeek：推荐主力翻译；付费版支持高并发批量。",
        "doubao": "Doubao：火山方舟 OpenAI 兼容接口。",
        "sakura": "Sakura：本地模型，无需 API Key。",
        "gemini": "Gemini：不支持 thinking 参数；免费版易限流。",
        "glm": "GLM/智谱：免费版限流明显，建议用性能预设。",
        "wenxin": "文心一言/千帆：使用百度千帆 OpenAI 兼容接口；旧版 access_token RPC 接口不兼容。",
        "custom": "Custom：自定义 OpenAI 兼容接口。"
    })
    property string currentProvider: cfg ? cfg.provider : "deepseek"
    property string connectionResult: ""
    property bool isCustom: currentProvider === "custom"
    property bool needsKey: currentProvider !== "sakura"
    property bool testing: false
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    Connections {
        target: TranslateBridge
        function onConnectionResult(msg) {
            page.connectionResult = msg
            page.testing = false
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: AppStyle.sectionGap

        ColumnLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingTight
            Label {
                text: "API 接口配置"
                color: AppPalette.textColor
                font.family: page.titleFont
                font.pixelSize: AppStyle.fontPageTitle
                font.weight: Font.DemiBold
            }
            Label {
                text: "选择翻译模型供应商，并测试当前 API 配置是否可用。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontBody
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: apiFormGrid.implicitHeight + 44
            Layout.minimumHeight: apiFormGrid.implicitHeight + 44
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            GridLayout {
                id: apiFormGrid
                anchors.fill: parent
                anchors.margins: 22
                columns: 2
                rowSpacing: 14
                columnSpacing: 16

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
                        page.needsKey = (key !== "sakura")
                        page.connectionResult = ""
                    }
                }

                FieldLabel { text: "API Key" }
                TextField {
                    id: apiKeyField
                    Layout.fillWidth: true
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
                    enabled: page.isCustom
                    selectByMouse: true
                    onTextChanged: { if (cfg && page.isCustom) cfg.apiUrl = text }
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
            Layout.preferredHeight: page.connectionResult !== "" ? 104 : 74
            radius: AppPalette.radiusLarge
            color: AppPalette.cardBg
            border.color: AppPalette.borderColor

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingSmall

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
                    font.pixelSize: AppStyle.fontBody
                    font.weight: Font.DemiBold
                }
            }
        }

        Item { Layout.fillHeight: true }
    }

    component FieldLabel: Label {
        Layout.preferredWidth: 90
        color: AppPalette.textColor
        font.pixelSize: AppStyle.fontBody
        font.weight: Font.DemiBold
        verticalAlignment: Text.AlignVCenter
    }
}
