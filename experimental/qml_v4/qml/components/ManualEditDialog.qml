import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: root

    property var tbridge: null
    property string srcText: ""
    property string dstText: ""
    property bool keepPreset: false

    title: "人工修改译文"
    modal: true
    standardButtons: Dialog.Ok | Dialog.Cancel
    width: 640

    function openWith(src, dst) {
        root.srcText = (src || "").trim()
        root.dstText = (dst || "").trim()
        srcSearchField.text = root.srcText
        dstEditField.text = root.dstText
        manualEditStatus.text = ""
        root.keepPreset = true
        root.open()
    }

    function setLookupResult(result) {
        if (root.visible && result) {
            dstEditField.text = result
            manualEditStatus.text = ""
        }
    }

    function showSaved() {
        if (!root.visible) return
        manualEditStatus.text = "已保存，恢复续译或下次翻译时会优先使用"
        manualEditStatus.color = AppPalette.successColor
    }

    function showError(message) {
        if (!root.visible) return
        manualEditStatus.text = message || ""
        manualEditStatus.color = AppPalette.errorColor
    }

    ColumnLayout {
        width: parent.width - 40
        spacing: AppStyle.spacingXLarge

        Label {
            Layout.fillWidth: true
            text: "输入日文原文查找已缓存译文，也可以直接填写中文译文。保存后写入人工译文缓存，恢复续译或下次翻译时优先使用，不会直接修改已经生成的 EPUB。"
            color: AppPalette.mutedText
            wrapMode: Text.WordWrap
            font.pixelSize: AppStyle.fontSmall
        }

        Label {
            text: "日文原文（必须与 EPUB 中的原文一致）:"
            color: AppPalette.textColor
            font.pixelSize: AppStyle.fontBody
            font.weight: Font.DemiBold
        }

        TextField {
            id: srcSearchField
            Layout.fillWidth: true
            placeholderText: "输入日文原文来查找或保存人工译文..."
            selectByMouse: true
        }

        Button {
            text: "查找译文"
            Layout.alignment: Qt.AlignLeft
            onClicked: {
                root.srcText = srcSearchField.text.trim()
                if (root.tbridge && root.srcText) {
                    root.tbridge.lookupTranslation(root.srcText)
                }
            }
        }

        Label {
            text: "中文译文（可直接编辑）"
            color: AppPalette.textColor
            font.pixelSize: AppStyle.fontBody
            font.weight: Font.DemiBold
        }

        TextArea {
            id: dstEditField
            Layout.fillWidth: true
            Layout.preferredHeight: 120
            placeholderText: "点击“查找译文”后，译文会显示在这里；也可以直接输入人工译文。"
            wrapMode: TextArea.Wrap
            selectByMouse: true
        }

        Label {
            id: manualEditStatus
            Layout.fillWidth: true
            text: ""
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            visible: text !== ""
        }
    }

    onOpened: {
        if (!root.keepPreset) {
            srcSearchField.text = ""
            dstEditField.text = ""
            root.srcText = ""
            root.dstText = ""
        }
        root.keepPreset = false
        manualEditStatus.text = ""
    }

    onAccepted: {
        var src = srcSearchField.text.trim()
        var dst = dstEditField.text.trim()
        if (!src || !dst) {
            root.showError("原文和译文不能为空")
            return
        }
        root.srcText = src
        if (root.tbridge) {
            root.tbridge.saveManualTranslation(src, dst)
            root.showSaved()
        }
    }
}
