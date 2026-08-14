import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog

    property var cfg: null
    property int pageWidth: 800
    property int pageHeight: 600
    readonly property var policyValues: ["balanced", "strict", "lenient"]
    readonly property var policyLabels: ["推荐模式（推荐）", "严格模式", "宽松模式"]

    function policyIndex(value) {
        var index = dialog.policyValues.indexOf(value || "balanced")
        return index >= 0 ? index : 0
    }

    function policyDescription(value) {
        if (value === "strict")
            return "严格模式：发现任何阻断级日文残留都会停止保存，适合最终精校。"
        if (value === "lenient")
            return "宽松模式：保存前只生成残留报告，不阻止保存，适合先拿到可打开的 EPUB。"
        return "推荐模式：整句或长句日文仍阻止保存；短标题、人名、机构名等低风险残留允许保存并生成报告。"
    }

    modal: true
    anchors.centerIn: parent
    width: Math.max(420, Math.min(dialog.pageWidth - 48, 760))
    height: Math.max(440, Math.min(dialog.pageHeight - 72, 620))
    title: "保存前日文残留策略"
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

            Label {
                Layout.fillWidth: true
                text: "选择保存前的日文残留拦截强度。规则修改会立即应用到后续翻译任务。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            GridLayout {
                Layout.fillWidth: true
                columns: dialog.width < 600 ? 1 : 2
                rowSpacing: AppStyle.spacingMedium
                columnSpacing: AppStyle.spacingLarge

                Label { text: "处理策略"; color: AppPalette.textColor }
                ComboBox {
                    Layout.fillWidth: true
                    model: dialog.policyLabels
                    currentIndex: dialog.policyIndex(dialog.cfg ? dialog.cfg.japaneseResiduePolicy : "balanced")
                    onActivated: function(index) {
                        if (dialog.cfg)
                            dialog.cfg.japaneseResiduePolicy = dialog.policyValues[index]
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: policySummary.implicitHeight + 28
                radius: AppPalette.radiusMedium
                color: AppPalette.cardAlt
                border.color: AppPalette.lineColor

                Label {
                    id: policySummary
                    anchors.fill: parent
                    anchors.margins: 14
                    text: dialog.policyDescription(dialog.cfg ? dialog.cfg.japaneseResiduePolicy : "balanced")
                    color: AppPalette.textColor
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontBody
                }
            }

            Label {
                Layout.fillWidth: true
                text: "风险分层：高风险为整句或长假名疑似未译；中风险为应翻译的短词；低风险为标题、人名、机构名或术语；弱风险为极短假名噪声。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }

            Label {
                Layout.fillWidth: true
                text: "保存前会先自动修复已知片假名词和地名振假名。明显应该翻译的内容应加入片假名修复词表，不应直接加入白名单。"
                color: AppPalette.amberColor
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
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
