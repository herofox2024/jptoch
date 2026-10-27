import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 翻译设置 → 性能：并发/批量/字符上限/超时参数与性能预设。
// SettingsPane 自带 ScrollView 与 ColumnLayout，因此这里只放子内容。
SettingsPane {
    id: root

    property var cfg: null
    property string activePreset: "custom"
    property bool applyingPreset: false

    signal markCustomRequested()
    signal presetApplyRequested(string presetKey)

    readonly property var presetOptions: [
        { key: "default", label: "默认" },
        { key: "balanced", label: "适中" },
        { key: "extreme", label: "极端" },
        { key: "glm_free", label: "智谱免费版" },
        { key: "gemini_free", label: "Gemini 免费版" },
        { key: "deepseek_paid", label: "DeepSeek 付费版" },
        { key: "hymt2_local", label: "Hy-MT2 CPU" },
        { key: "hymt2_gpu", label: "Hy-MT2 GPU" }
    ]

    // 参数变更的统一入口：应用预设过程中不触发，避免覆盖预设值。
    function writeValue(key, value) {
        if (!root.cfg || root.applyingPreset) return
        root.cfg[key] = value
        root.markCustomRequested()
    }

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
                    Accessible.name: "最大并发数滑块"
                    from: 1
                    to: 25
                    value: root.cfg ? root.cfg.maxWorkers : 5
                    Layout.fillWidth: true
                    onMoved: root.writeValue("maxWorkers", value)
                }
                SpinBox {
                    id: maxWorkersSpin
                    Accessible.name: "最大并发数"
                    from: 1
                    to: 25
                    value: root.cfg ? root.cfg.maxWorkers : 5
                    editable: true
                    onValueChanged: root.writeValue("maxWorkers", value)
                }
            }

            Label { text: "批次大小" }
            RowLayout {
                Layout.fillWidth: true
                Slider {
                    id: batchSizeSlider
                    Accessible.name: "批次大小滑块"
                    from: 1
                    to: 15
                    value: root.cfg ? root.cfg.batchSize : 4
                    Layout.fillWidth: true
                    onMoved: root.writeValue("batchSize", value)
                }
                SpinBox {
                    id: batchSizeSpin
                    Accessible.name: "批次大小"
                    from: 1
                    to: 15
                    value: root.cfg ? root.cfg.batchSize : 4
                    editable: true
                    onValueChanged: root.writeValue("batchSize", value)
                }
            }

            Label { text: "批次最大长度" }
            RowLayout {
                Layout.fillWidth: true
                Slider {
                    id: maxBatchLengthSlider
                    Accessible.name: "批次最大长度滑块"
                    from: 1
                    to: 8000
                    stepSize: 100
                    value: root.cfg ? root.cfg.maxBatchLength : 800
                    Layout.fillWidth: true
                    onMoved: root.writeValue("maxBatchLength", value)
                }
                SpinBox {
                    id: maxBatchLengthSpin
                    Accessible.name: "批次最大长度"
                    from: 1
                    to: 8000
                    stepSize: 100
                    value: root.cfg ? root.cfg.maxBatchLength : 800
                    editable: true
                    onValueChanged: root.writeValue("maxBatchLength", value)
                }
            }

            Label { text: "单条上限" }
            RowLayout {
                Layout.fillWidth: true
                Slider {
                    id: maxTextSizeSlider
                    Accessible.name: "单条字符上限滑块"
                    from: 1
                    to: 1000
                    value: root.cfg ? root.cfg.maxTextSizeForBatch : 200
                    Layout.fillWidth: true
                    onMoved: root.writeValue("maxTextSizeForBatch", value)
                }
                SpinBox {
                    id: maxTextSizeSpin
                    Accessible.name: "单条字符上限"
                    from: 1
                    to: 1000
                    value: root.cfg ? root.cfg.maxTextSizeForBatch : 200
                    editable: true
                    onValueChanged: root.writeValue("maxTextSizeForBatch", value)
                }
            }

            Label { text: "API 超时(秒)" }
            RowLayout {
                Layout.fillWidth: true
                Slider {
                    id: apiTimeoutSlider
                    Accessible.name: "API 超时滑块"
                    from: 1
                    to: 300
                    value: root.cfg ? root.cfg.apiTimeout : 120
                    Layout.fillWidth: true
                    onMoved: root.writeValue("apiTimeout", value)
                }
                SpinBox {
                    id: apiTimeoutSpin
                    Accessible.name: "API 超时（秒）"
                    from: 1
                    to: 600
                    value: root.cfg ? root.cfg.apiTimeout : 120
                    editable: true
                    onValueChanged: root.writeValue("apiTimeout", value)
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
                    model: root.presetOptions
                    delegate: Button {
                        text: modelData.label
                        checkable: true
                        checked: root.activePreset === modelData.key
                        onClicked: root.presetApplyRequested(modelData.key)
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
