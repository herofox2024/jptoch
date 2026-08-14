import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog

    property var cfg: null
    property int pageWidth: 800
    property int pageHeight: 600
    readonly property var providerValues: ["", "deepseek", "longcat", "hymt2", "custom"]
    readonly property var providerLabels: ["不使用", "DeepSeek", "LongCat", "Hy-MT2", "自定义"]
    readonly property bool compactLayout: width < 640

    modal: true
    anchors.centerIn: parent
    width: Math.max(440, Math.min(dialog.pageWidth - 48, 820))
    height: Math.max(500, Math.min(dialog.pageHeight - 72, 720))
    title: "智能失败恢复"
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    contentItem: ScrollView {
        width: dialog.width - 48
        height: dialog.height - 96
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, dialog.width - 72)
            spacing: AppStyle.spacingLarge

            CheckBox {
                text: "启用智能失败恢复"
                checked: dialog.cfg ? dialog.cfg.enableRecoveryAgent : false
                onToggled: if (dialog.cfg) dialog.cfg.enableRecoveryAgent = checked
            }

            Label {
                Layout.fillWidth: true
                text: "恢复流程只生成失败块建议，不会直接修改 EPUB。高风险残留、内容审核和谜题中的日文引用仍需要人工确认。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            GridLayout {
                Layout.fillWidth: true
                columns: dialog.compactLayout ? 1 : 2
                columnSpacing: AppStyle.spacingLarge
                rowSpacing: AppStyle.spacingMedium
                enabled: dialog.cfg ? dialog.cfg.enableRecoveryAgent : false

                Label { text: "最低执行置信度" }
                RowLayout {
                    Layout.fillWidth: true
                    Slider {
                        id: confidenceSlider
                        Layout.fillWidth: true
                        from: 0.50
                        to: 1.00
                        stepSize: 0.05
                        value: dialog.cfg ? dialog.cfg.recoveryMinConfidence : 0.85
                        onMoved: if (dialog.cfg) dialog.cfg.recoveryMinConfidence = value
                    }
                    Label { text: Math.round((confidenceSlider.value || 0.85) * 100) + "%" }
                }

                Label { text: "单块最大恢复次数" }
                SpinBox {
                    from: 1
                    to: 5
                    value: dialog.cfg ? dialog.cfg.recoveryMaxAttempts : 2
                    onValueModified: if (dialog.cfg) dialog.cfg.recoveryMaxAttempts = value
                }

                Label { text: "备用模型 Provider" }
                ComboBox {
                    Layout.fillWidth: true
                    model: dialog.providerLabels
                    currentIndex: Math.max(0, dialog.providerValues.indexOf(dialog.cfg ? dialog.cfg.recoveryFallbackProvider : ""))
                    onActivated: function(index) {
                        if (!dialog.cfg)
                            return
                        var provider = dialog.providerValues[index] || ""
                        dialog.cfg.recoveryFallbackProvider = provider
                        if (provider === "") {
                            dialog.cfg.recoveryFallbackApiUrl = ""
                            dialog.cfg.recoveryFallbackModel = ""
                        } else {
                            var defaults = dialog.cfg.getProviderDefaults(provider)
                            dialog.cfg.recoveryFallbackApiUrl = defaults.url || ""
                            dialog.cfg.recoveryFallbackModel = defaults.model || ""
                        }
                    }
                }

                Label { text: "备用 Base URL" }
                TextField {
                    Layout.fillWidth: true
                    text: dialog.cfg ? dialog.cfg.recoveryFallbackApiUrl : ""
                    placeholderText: "留空表示不使用备用模型"
                    selectByMouse: true
                    onTextChanged: if (dialog.cfg) dialog.cfg.recoveryFallbackApiUrl = text
                }

                Label { text: "备用模型名" }
                TextField {
                    Layout.fillWidth: true
                    text: dialog.cfg ? dialog.cfg.recoveryFallbackModel : ""
                    selectByMouse: true
                    onTextChanged: if (dialog.cfg) dialog.cfg.recoveryFallbackModel = text
                }

                Label { text: "备用 API Key" }
                TextField {
                    Layout.fillWidth: true
                    echoMode: TextInput.Password
                    text: dialog.cfg ? dialog.cfg.recoveryFallbackApiKey : ""
                    selectByMouse: true
                    onTextChanged: if (dialog.cfg) dialog.cfg.recoveryFallbackApiKey = text
                }
            }

            Item { Layout.fillHeight: true }

            Button {
                Layout.alignment: Qt.AlignRight
                text: "关闭"
                onClicked: dialog.close()
            }
        }
    }
}
