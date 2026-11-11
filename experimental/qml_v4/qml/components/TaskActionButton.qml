import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 自绘按钮。
//
// 项目整体使用 Material 风格（main.py 里 QQuickStyle.setStyle("Material")），
// 但这个按钮是手绘的，早期实现用了偏大的圆角、琥珀色悬停描边和放大动画，
// 与同屏的 Material Button 明显不同。这里按 Material 的状态层（state layer）
// 约定重写：悬停/按下用叠加层表达，而不是换描边色或整体缩放。
Rectangle {
    id: root

    property string label: ""
    property string hint: ""
    property bool primary: false
    property bool danger: false
    readonly property bool hovered: actionMouse.containsMouse && root.enabled
    readonly property bool pressed: actionMouse.pressed && root.enabled

    signal clicked()

    implicitWidth: primary ? 320 : 132
    implicitHeight: primary ? AppStyle.buttonHeightPrimary : AppStyle.buttonHeightNormal
    radius: root.primary ? AppStyle.radiusCard : AppStyle.radiusButton
    color: !enabled
           ? AppPalette.cardAlt
           : (primary ? AppPalette.accentColor : (danger ? AppStyle.dangerButtonBg : AppPalette.cardBg))
    border.color: !enabled
                  ? AppPalette.lineColor
                  : (primary ? "transparent" : (danger ? AppPalette.errorColor : AppPalette.borderColor))
    border.width: primary ? 0 : 1

    // Material 的状态层：悬停 8%、按下 12%。主按钮用白叠加，
    // 普通按钮用强调色叠加，这样在任何主题下都不会串色。
    readonly property color stateLayerColor: root.primary ? "#ffffff" : AppPalette.accentColor
    readonly property real stateLayerOpacity: root.pressed ? 0.12 : (root.hovered ? 0.08 : 0.0)

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: root.stateLayerColor
        opacity: root.stateLayerOpacity
        Behavior on opacity { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
    }

    ColumnLayout {
        anchors.centerIn: parent
        width: parent.width - 20
        spacing: root.primary ? AppStyle.spacingChip : 1

        Label {
            Layout.alignment: Qt.AlignHCenter
            text: root.label
            // 禁用时背景会变成 cardAlt（浅灰），此时不能再用“主按钮白字”，
            // 否则白字落在浅灰底上等于不可见。
            color: !root.enabled
                   ? AppPalette.mutedText
                   : (root.primary
                      ? AppStyle.primaryOnAccent
                      : (root.danger ? AppPalette.errorText : AppPalette.textColor))
            font.pixelSize: root.primary ? AppStyle.fontHeader : AppStyle.fontBody
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            maximumLineCount: 1
        }

        Label {
            Layout.alignment: Qt.AlignHCenter
            visible: root.hint !== ""
            text: root.hint
            color: !root.enabled
                   ? AppPalette.mutedText
                   : (root.primary ? AppStyle.primaryOnAccentMuted : AppPalette.mutedText)
            font.pixelSize: root.primary ? AppStyle.fontCaption : AppStyle.fontTiny
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            maximumLineCount: 1
        }
    }

    MouseArea {
        id: actionMouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    // 自定义按钮需要显式声明无障碍信息，否则屏幕阅读器只能读到一个矩形。
    Accessible.role: Accessible.Button
    Accessible.name: root.label
    Accessible.description: root.hint
    Accessible.onPressAction: {
        if (root.enabled) root.clicked()
    }

    // 支持键盘聚焦与激活，与原生 Button 一致。
    activeFocusOnTab: true
    focus: false
    Keys.onReturnPressed: {
        if (root.enabled) root.clicked()
    }
    Keys.onEnterPressed: {
        if (root.enabled) root.clicked()
    }
    Keys.onSpacePressed: {
        if (root.enabled) root.clicked()
    }

    // 键盘聚焦时显示与 Material 一致的强调色描边。
    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        color: "transparent"
        border.color: root.activeFocus ? AppPalette.accentColor : "transparent"
        border.width: root.activeFocus ? AppStyle.borderWidthEmphasis : 0
        visible: root.activeFocus
    }
}
