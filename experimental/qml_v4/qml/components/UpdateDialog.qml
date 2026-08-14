import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: dialog

    property var updater: null
    property var updateInfo: ({})
    property bool hasAsset: false
    property int updateDownloadPercent: 0
    property string updateStatus: ""
    property int pageWidth: 800

    signal openReleaseRequested()
    signal startDownloadRequested()

    modal: true
    anchors.centerIn: parent
    width: Math.min(dialog.pageWidth - 64, 620)
    title: dialog.updateInfo && dialog.updateInfo.isNewer ? "发现新版本" : "软件更新"
    closePolicy: dialog.updater && dialog.updater.downloading ? Popup.NoAutoClose : Popup.CloseOnEscape | Popup.CloseOnPressOutside

    contentItem: ColumnLayout {
        width: dialog.width - 48
        spacing: AppStyle.spacingLarge

        Label {
            Layout.fillWidth: true
            text: "当前版本 V" + (dialog.updateInfo.currentVersion || (dialog.updater ? dialog.updater.currentVersion : "未知"))
                  + "，最新版本 V" + (dialog.updateInfo.latestVersion || "未知")
            color: AppPalette.textColor
            font.pixelSize: AppStyle.fontBodyXLarge
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
        }

        Label {
            Layout.fillWidth: true
            text: dialog.hasAsset
                  ? ("安装包：" + dialog.updateInfo.assetName + "（" + dialog.updateInfo.assetSizeText + "）")
                  : "该 Release 没有找到 .exe 安装包，可打开发布页手动查看。"
            color: AppPalette.mutedText
            wrapMode: Text.WordWrap
            font.pixelSize: AppStyle.fontSmall
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.preferredHeight: 180
            clip: true

            Label {
                width: dialog.width - 72
                text: dialog.updateInfo.releaseNotes || "没有发布说明。"
                color: AppPalette.textColor
                wrapMode: Text.WordWrap
                font.pixelSize: AppStyle.fontSmall
            }
        }

        ProgressBar {
            Layout.fillWidth: true
            visible: dialog.updater && dialog.updater.downloading
            from: 0
            to: 100
            value: dialog.updateDownloadPercent
        }

        Label {
            Layout.fillWidth: true
            visible: dialog.updater && dialog.updater.downloading
            text: dialog.updateStatus
            color: AppPalette.mutedText
            wrapMode: Text.WordWrap
            font.pixelSize: AppStyle.fontSmall
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingMedium

            Button {
                text: "稍后"
                enabled: !(dialog.updater && dialog.updater.downloading)
                onClicked: dialog.close()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "打开发布页"
                enabled: !(dialog.updater && dialog.updater.downloading)
                onClicked: dialog.openReleaseRequested()
            }

            Button {
                text: dialog.updater && dialog.updater.downloading
                      ? ("下载中 " + dialog.updateDownloadPercent + "%")
                      : "下载并安装"
                highlighted: true
                enabled: dialog.updater
                         && dialog.hasAsset
                         && !(dialog.updater && dialog.updater.downloading)
                onClicked: dialog.startDownloadRequested()
            }
        }
    }
}
