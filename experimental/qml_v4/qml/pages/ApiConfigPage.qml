import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts

Page {
    id: page
    padding: 24
    property var cfg: null

    property var providerKeys: ["deepseek", "doubao", "sakura", "gemini", "glm", "custom"]
    property var providerLabels: ["DeepSeek", "豆包 (火山引擎)", "Sakura (本地)", "Gemini", "GLM (智谱)", "自定义"]
    property var providerHints: ({
        "deepseek": "DeepSeek：推荐主力翻译；付费版支持高并发批量。",
        "doubao": "Doubao：火山方舟 OpenAI 兼容接口。",
        "sakura": "Sakura：本地模型，无需 API Key。",
        "gemini": "Gemini：不支持 thinking 参数；免费版易限流。",
        "glm": "GLM/智谱：免费版限流明显，建议用性能预设。",
        "custom": "Custom：自定义 OpenAI 兼容接口。"
    })
    property string currentProvider: cfg ? cfg.provider : "deepseek"
    property string connectionResult: ""
    property bool isCustom: currentProvider === "custom"
    property bool needsKey: currentProvider !== "sakura"
    property bool testing: false

    Connections {
        target: TranslateBridge
        function onConnectionResult(msg) {
            page.connectionResult = msg
            page.testing = false
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 16

        Label { text: "API 接口配置"; font.pixelSize: 24; font.weight: Font.DemiBold }

        RowLayout {
            Layout.fillWidth: true
            Label { text: "供应商:"; Layout.preferredWidth: 80 }
            ComboBox {
                id: providerCombo; Layout.fillWidth: true
                model: providerLabels
                currentIndex: providerKeys.indexOf(page.currentProvider)
                onCurrentIndexChanged: {
                    var key = providerKeys[currentIndex]
                    if (cfg) cfg.setProvider(key)
                    page.currentProvider = key
                    page.isCustom = (key === "custom")
                    page.needsKey = (key !== "sakura")
                    page.connectionResult = ""
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label { text: "API Key:"; Layout.preferredWidth: 80 }
            TextField {
                id: apiKeyField
                Layout.fillWidth: true; echoMode: TextInput.Password
                placeholderText: page.needsKey ? "请输入 API Key" : "本地模型无需 API Key"
                text: cfg ? cfg.apiKey : ""
                enabled: page.needsKey
                onTextChanged: { if (cfg) cfg.apiKey = text }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label { text: "API URL:"; Layout.preferredWidth: 80 }
            TextField {
                id: urlField
                Layout.fillWidth: true; placeholderText: "https://api.xxx.com/chat/completions"
                text: cfg ? cfg.apiUrl : ""
                enabled: page.isCustom
                onTextChanged: { if (cfg && page.isCustom) cfg.apiUrl = text }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Label { text: "Model:"; Layout.preferredWidth: 80 }
            TextField {
                id: modelField
                Layout.fillWidth: true; placeholderText: "model-name"
                text: cfg ? cfg.model : ""
                onTextChanged: { if (cfg) cfg.model = text }
            }
        }

        RowLayout {
            spacing: 12
            Label { text: "超时(秒):"; Layout.preferredWidth: 80 }
            SpinBox { id: testTimeout; from: 1; to: 300; value: 15 }
            Button {
                text: page.testing ? "测试中..." : "测试连接"
                highlighted: true; enabled: !page.testing
                onClicked: {
                    if (!cfg) return
                    page.connectionResult = "测试中..."
                    page.testing = true
                    TranslateBridge.testConnection(cfg.apiKey, cfg.apiUrl, cfg.model, testTimeout.value)
                }
            }
        }

        Label {
            text: page.connectionResult
            visible: page.connectionResult !== ""
            font.pixelSize: 13
            color: page.connectionResult.includes("成功") ? "#4caf50" : "#e53935"
            wrapMode: Text.WordWrap; Layout.fillWidth: true
        }

        Label {
            text: page.providerHints[page.currentProvider] || ""
            font.pixelSize: 12; color: (Material.theme === Material.Dark ? "#999999" : "#666666"); wrapMode: Text.WordWrap; Layout.fillWidth: true
        }

        Item { Layout.fillHeight: true }
    }
}