import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: root

    property var cfg: null
    property var tbridge: null

    title: "清理当前 EPUB 缓存"
    modal: true
    standardButtons: Dialog.Ok | Dialog.Cancel

    ColumnLayout {
        width: 420
        spacing: AppStyle.spacingMedium

        Label {
            Layout.fillWidth: true
            text: "将清理当前源文件对应的翻译缓存，包括所有模型下的 cache.json 条目和跨模型 text_cache.json 条目。"
            color: AppPalette.textColor
            wrapMode: Text.WordWrap
        }

        Label {
            Layout.fillWidth: true
            text: "不会删除 EPUB 文件，也不会清空术语表。清理后再次翻译会重新请求 API。"
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontSmall
            wrapMode: Text.WordWrap
        }
    }

    onAccepted: {
        if (root.tbridge) {
            root.tbridge.clearCurrentBookCache(root.cfg)
        }
    }
}
