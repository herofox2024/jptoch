import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 「关于」弹窗：展示版本、运行环境与项目信息。
// 所有数据由宿主通过属性注入，本组件不直接依赖后端桥接对象。
Dialog {
    id: root

    property string appName: ""
    property string displayVersion: ""
    property string fullVersion: ""
    property string pythonVersion: ""
    property string qtVersion: ""
    property string copyright: ""
    property string repoUrl: "https://github.com/herofox2024/jptoch"
    property string contactEmail: "42845734@qq.com"
    property int parentWidth: 900
    property int parentHeight: 700

    title: "关于 " + (root.appName !== "" ? root.appName : "本软件")
    modal: true
    anchors.centerIn: parent
    width: Math.max(420, Math.min(root.parentWidth - 120, 620))
    height: Math.max(420, Math.min(root.parentHeight - 120, 620))
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    readonly property var infoRows: [
        { label: "显示版本", value: root.displayVersion },
        { label: "内部版本", value: root.fullVersion },
        { label: "运行环境", value: root.pythonVersion },
        { label: "界面框架", value: root.qtVersion }
    ]

    function openExternal(url) {
        if (typeof Qt !== "undefined" && Qt.openUrlExternally) {
            Qt.openUrlExternally(url)
        }
    }

    contentItem: ScrollView {
        width: root.width
        height: root.height
        clip: true
        ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
        ScrollBar.vertical.policy: ScrollBar.AsNeeded

        ColumnLayout {
            width: Math.max(0, root.width - 32)
            spacing: AppStyle.spacingXLarge

            // ---- 品牌区 ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingInline

                Label {
                    Layout.fillWidth: true
                    text: root.appName
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontSubHeader
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }

                Label {
                    Layout.fillWidth: true
                    text: "版本 " + root.displayVersion
                    color: AppPalette.accentColor
                    font.pixelSize: AppStyle.fontBodyLarge
                    font.weight: Font.DemiBold
                    horizontalAlignment: Text.AlignHCenter
                }

                Label {
                    Layout.fillWidth: true
                    text: "基于大模型 API 的日文 EPUB 自动翻译工具"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            // ---- 版本与环境信息 ----
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: infoColumn.implicitHeight + 24
                radius: AppPalette.radiusMedium
                color: AppPalette.cardAlt
                border.color: AppPalette.lineColor

                ColumnLayout {
                    id: infoColumn
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: AppStyle.spacingCompact

                    Repeater {
                        model: root.infoRows
                        delegate: RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingMedium

                            Label {
                                Layout.preferredWidth: 88
                                text: modelData.label
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                                elide: Text.ElideRight
                            }
                            Label {
                                Layout.fillWidth: true
                                text: modelData.value !== "" ? modelData.value : "--"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                                elide: Text.ElideRight
                                Accessible.name: modelData.label + ": " + modelData.value
                            }
                        }
                    }
                }
            }

            // ---- 项目链接 ----
            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                Label {
                    Layout.fillWidth: true
                    text: "项目与反馈"
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontSmall
                    font.weight: Font.DemiBold
                }

                ContactLink {
                    Layout.fillWidth: true
                    label: "GitHub"
                    value: root.repoUrl.replace("https://github.com/", "")
                    targetUrl: root.repoUrl
                    glassMode: AppPalette.glass
                }

                ContactLink {
                    Layout.fillWidth: true
                    label: "Email"
                    value: root.contactEmail
                    targetUrl: "mailto:" + root.contactEmail
                    glassMode: AppPalette.glass
                }
            }

            // ---- 许可提示 ----
            Label {
                Layout.fillWidth: true
                text: root.copyright
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontTiny
                wrapMode: Text.WordWrap
                lineHeight: 1.3
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                Item { Layout.fillWidth: true }

                Button {
                    text: "关闭"
                    highlighted: true
                    onClicked: root.close()
                }
            }
        }
    }
}
