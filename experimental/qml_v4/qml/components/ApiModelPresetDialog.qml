import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import QtQuick.Effects
import ".."

// 模型 / Prompt 预设管理弹窗。
// 只负责展示与交互；实际的 cfg 读写由宿主页面通过信号完成，
// 这样本组件不直接依赖任何全局桥接对象，也便于单独预览。
Dialog {
    id: root

    property var presets: []
    property string resultText: ""
    property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    property string categoryFilter: "all"

    signal refreshRequested()
    signal applyRequested(string presetKey)
    signal deleteRequested(string presetKey)
    signal saveRequested(string label, string hint)
    signal importRequested(string path)
    signal exportCurrentRequested(string path, string label)
    signal exportUserRequested(string path)

    readonly property var categoryOptions: [
        { key: "all", label: "全部" },
        { key: "workflow", label: "组合" },
        { key: "model", label: "模型" },
        { key: "prompt", label: "Prompt" }
    ]

    title: "模型 / Prompt 预设"
    modal: true
    width: Math.max(760, Math.min(1080, (ApplicationWindow.window ? ApplicationWindow.window.width : 1200) - 48))
    height: Math.max(480, Math.min(720, (ApplicationWindow.window ? ApplicationWindow.window.height : 800) - 72))
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onOpened: root.refreshRequested()

    function presetSummaryText() {
        if (!root.presets || root.presets.length === 0) return "暂无可用预设"
        return "当前可用预设: " + root.presets.length + " 个"
    }

    function resultIsError() {
        return root.resultText.indexOf("失败") >= 0 || root.resultText.indexOf("不存在") >= 0
    }

    ScrollView {
        width: root.width - 48
        height: root.height - 96
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AsNeeded
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, root.width - 72)
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
                            onClicked: root.refreshRequested()
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
                            model: root.categoryOptions
                            delegate: Button {
                                text: modelData.label
                                highlighted: root.categoryFilter === modelData.key
                                onClicked: root.categoryFilter = modelData.key
                            }
                        }
                    }

                    Flow {
                        id: modelPresetFlow
                        Layout.fillWidth: true
                        width: parent.width
                        spacing: AppStyle.spacingSmall

                        Repeater {
                            model: root.presets
                            delegate: Rectangle {
                                visible: root.categoryFilter === "all" || modelData.category === root.categoryFilter
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
                                            onClicked: root.applyRequested(modelData.key)
                                        }
                                        Button {
                                            text: "删除"
                                            visible: modelData.user === true
                                            onClicked: root.deleteRequested(modelData.key)
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.resultText !== "" ? root.resultText : root.presetSummaryText()
                        color: root.resultIsError() ? AppPalette.errorColor : AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontTiny
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
        width: Math.max(360, Math.min(520, root.width - 48))

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
            root.saveRequested(savePresetName.text, savePresetHint.text)
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
            if (!selectedFile) return
            root.importRequested(FilePathUtils.normalizeFileUrl(selectedFile))
        }
    }

    FileDialog {
        id: presetExportCurrentDialog
        title: "导出当前模型 / Prompt 预设"
        nameFilters: ["JSON (*.json)", "全部文件 (*)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (!selectedFile) return
            var p = FilePathUtils.normalizeFileUrl(selectedFile)
            if (!p.toLowerCase().endsWith(".json")) p += ".json"
            root.exportCurrentRequested(p, savePresetName.text || "当前翻译配置")
        }
    }

    FileDialog {
        id: presetExportUserDialog
        title: "导出自定义模型 / Prompt 预设"
        nameFilters: ["JSON (*.json)", "全部文件 (*)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (!selectedFile) return
            var p = FilePathUtils.normalizeFileUrl(selectedFile)
            if (!p.toLowerCase().endsWith(".json")) p += ".json"
            root.exportUserRequested(p)
        }
    }
}
