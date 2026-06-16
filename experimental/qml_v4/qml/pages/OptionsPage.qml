import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import ".."

Page {
    id: page
    padding: 0
    background: Item {}
    property var cfg: null

    property string activePreset: "custom"
    property bool applyingPreset: false
    property var proofreadGenreValues: ["auto", "general", "mystery", "scifi", "fantasy"]
    property var proofreadGenreLabels: ["自动识别（推荐）", "通用小说", "推理小说", "科幻小说", "奇幻小说"]
    property var proofreadToneValues: ["auto", "neutral", "light", "literary"]
    property var proofreadToneLabels: ["自动识别（推荐）", "中性口吻", "轻小说口吻", "文学化口吻"]
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    Flickable {
        id: settingsScroll
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: settingsColumn.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        ColumnLayout {
            id: settingsColumn
            x: 24
            y: 24
            width: Math.max(settingsScroll.width - 48, 640)
            spacing: 14

            Label {
                text: "翻译设置"
                color: AppPalette.textColor
                font.family: page.titleFont
                font.pixelSize: 28
                font.weight: Font.DemiBold
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
                            to: 300
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
                    spacing: 8

                    Flow {
                        Layout.fillWidth: true
                        width: parent.width
                        spacing: 8

                        Repeater {
                            model: [
                                { key: "default", label: "默认" },
                                { key: "balanced", label: "适中" },
                                { key: "extreme", label: "极端" },
                                { key: "glm_free", label: "智谱免费版" },
                                { key: "gemini_free", label: "Gemini 免费版" },
                                { key: "deepseek_paid", label: "DeepSeek 付费版" }
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
                        font.pixelSize: 12
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }

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

            GroupBox {
                title: "翻译与校对 Prompt 风格"
                Layout.fillWidth: true

                ColumnLayout {
                    width: parent.width
                    spacing: 10

                    CheckBox {
                        text: "启用译后校对"
                        checked: cfg ? cfg.enableProofread : true
                        onCheckedChanged: {
                            if (cfg) {
                                cfg.enableProofread = checked
                                cfg.saveToDisk()
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
                                    cfg.saveToDisk()
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
                                    cfg.saveToDisk()
                                }
                            }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "作品类型和叙事口吻会影响初译 Prompt；启用译后校对后，也会影响校对 Prompt。自动识别会在开始翻译后根据书名、目录和样本文本生成结果，识别不确定时回退到“通用小说 + 中性口吻”。"
                        color: AppPalette.mutedText
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                }
            }

            GroupBox {
                title: "界面与推理"
                Layout.fillWidth: true

                Flow {
                    width: parent.width
                    spacing: 16

                    Label { text: "主题:" }
                    ComboBox {
                        model: ["浅色纸感", "深色墨色", "iOS26 玻璃"]
                        currentIndex: page.themeIndex(cfg ? cfg.theme : "light")
                        onActivated: function(index) {
                            if (cfg) cfg.theme = page.themeFromIndex(index)
                        }
                    }
                    CheckBox {
                        text: "开启深度思考"
                        checked: cfg ? cfg.enableThinking : false
                        onCheckedChanged: { if (cfg) cfg.enableThinking = checked }
                    }
                }
            }

            Item { Layout.preferredHeight: 24 }
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
            "deepseek_paid": "DeepSeek 付费版：较高并发和批量"
        }
        presetHint.text = labels[key] || ("已应用: " + key)
    }

    function markCustom() {
        page.activePreset = "custom"
        presetHint.text = "参数已手动修改，当前为自定义性能参数"
    }

    function themeIndex(theme) {
        if (theme === "dark") return 1
        if (theme === "glass") return 2
        return 0
    }

    function themeFromIndex(index) {
        if (index === 1) return "dark"
        if (index === 2) return "glass"
        return "light"
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
}
