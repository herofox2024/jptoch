import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    objectName: "clearCacheDialog"
    id: root

    property var cfg: null
    property var tbridge: null

    title: "清理当前 EPUB 缓存"
    modal: true
    // 没有 anchors.centerIn 时 Controls 会把弹窗放在 Overlay 左上角。
    standardButtons: Dialog.Ok | Dialog.Cancel
    anchors.centerIn: parent
    // 固定宽度在窄窗口下会溢出，这里跟随窗口但保留上下限。
    width: Math.max(
        320,
        Math.min(460, (ApplicationWindow.window ? ApplicationWindow.window.width : 800) - 64)
    )

    // 用 contentItem 而不是直接放子项：直接放子项时 Dialog 会把内容
    // 靠左上摆放，右侧留白不均；contentItem 会按 availableWidth 正确撑开。
    contentItem: ColumnLayout {
        width: root.availableWidth
        spacing: AppStyle.spacingMedium

        Label {
            Layout.fillWidth: true
            text: "将清理当前源文件对应的 SQLite 翻译缓存，包括所有模型缓存、跨模型文本缓存和人工译文缓存。旧 JSON 迁移文件不会被删除。"
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
