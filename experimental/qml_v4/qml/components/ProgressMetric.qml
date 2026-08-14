import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import QtQuick.Layouts
import ".."

Rectangle {
    id: root

    property string title: ""
    property string value: ""
    property string tone: ""
    property bool hovered: false

    Layout.fillWidth: true
    Layout.preferredHeight: 60
    radius: AppPalette.radiusMedium
    color: AppPalette.cardBg
    border.color: AppPalette.lineColor

    scale: hovered ? 1.02 : 1.0
    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    layer.enabled: true
    layer.effect: MultiEffect {
        shadowEnabled: true
        shadowColor: AppPalette.glass ? AppPalette.shadowColorGlass : AppPalette.shadowColor
        shadowBlur: 0.25
        shadowVerticalOffset: AppPalette.shadowYOffset
    }

    readonly property color toneColor: tone === "accent"
                                       ? AppPalette.accentColor
                                       : tone === "amber"
                                         ? AppPalette.amberColor
                                         : AppPalette.textColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: AppStyle.spacingTight

        Label {
            Layout.fillWidth: true
            text: root.title
            color: AppPalette.mutedText
            font.pixelSize: AppStyle.fontCaption
            elide: Text.ElideRight
        }

        Label {
            Layout.fillWidth: true
            text: root.value
            color: root.toneColor
            font.pixelSize: AppStyle.fontSection
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        onEntered: root.hovered = true
        onExited: root.hovered = false
    }
}
