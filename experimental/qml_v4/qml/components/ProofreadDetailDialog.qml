import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Dialog {
    id: root

    property var host: null

    title: "校对完整详情 " + (host ? host.detailIndexText : "")
    modal: true
    standardButtons: Dialog.Close
    width: Math.min((host ? host.width : 900) - 48, 900)
    height: Math.min((host ? host.height : 680) - 60, 680)

    contentItem: ScrollView {
        clip: true
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: root.availableWidth
            spacing: AppStyle.spacingLarge

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: detailHeaderColumn.implicitHeight + 28
                radius: AppPalette.radiusMedium
                color: AppPalette.surfaceRaised
                border.color: AppPalette.lineColor

                ColumnLayout {
                    id: detailHeaderColumn
                    anchors.fill: parent
                    anchors.margins: AppStyle.panelPadding
                    spacing: AppStyle.spacingSmall

                    Label {
                        Layout.fillWidth: true
                        text: (root.host ? root.host.detailTimeText : "") + "  \u00b7  " + (root.host ? root.host.detailReason : "")
                        color: AppPalette.textColor
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontBody
                        font.weight: Font.DemiBold
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingSmall
                        IssueChip {
                            title: root.host ? root.host.detailChanged : ""
                            tone: root.host && root.host.detailChanged === "有变化" ? "amber" : "accent"
                        }
                        IssueChip {
                            title: "日文残留: " + (root.host ? root.host.detailJapaneseResidue : "")
                            tone: root.host && root.host.detailJapaneseResidue === "是" ? "error" : "neutral"
                        }
                        IssueChip {
                            title: "术语不一致: " + (root.host ? root.host.detailGlossaryMismatch : "")
                            tone: root.host && root.host.detailGlossaryMismatch === "是" ? "amber" : "neutral"
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: root.host ? root.host.detailChangedHint : ""
                        color: AppPalette.mutedText
                        wrapMode: Text.WordWrap
                        font.pixelSize: AppStyle.fontSmall
                    }
                }
            }

            ReportField { title: "原文"; body: root.host ? root.host.detailOriginal : ""; tone: "normal" }
            ReportField { title: "初译"; body: root.host ? root.host.detailDraft : ""; tone: "normal" }
            ReportField { title: "校对后译文"; body: root.host ? root.host.detailRevised : ""; tone: "accent" }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button {
                    text: "人工修改此条"
                    enabled: root.host && root.host.detailOriginal !== ""
                    onClicked: {
                        if (!root.host) return
                        root.host.requestManualEdit(
                            root.host.detailOriginal,
                            root.host.detailRevised !== "" ? root.host.detailRevised : root.host.detailDraft
                        )
                    }
                }
            }
        }
    }
}
