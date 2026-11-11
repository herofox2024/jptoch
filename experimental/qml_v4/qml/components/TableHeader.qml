import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 表头单元格。
//
// 两条硬约束，都是踩过坑总结出来的：
//
// 一、列宽必须与行内 delegate 完全一致
//   否则固定列之后的弹性列会错位（「应用策略」表头与下拉框对不齐）。
//   因此把 implicitWidth/Height 归零（Rectangle 自身为 0，但内部 Label 会撑出
//   隐式宽度），并同时给出 preferredWidth 与 minimumWidth。
//
// 二、文字必须左对齐，且内距与单元格一致
//   原实现是居中排版，而单元格是左对齐 + 内距，视觉上完全不对齐。
//   这里用**单个 Label + horizontalAlignment** 实现两种对齐，
//   不要写成两个 Label 各自 visible —— 那样两个都会渲染。
Rectangle {
    id: root
    property int w: 100
    property string text: ""
    property bool first: false
    property bool last: false
    // 仅「选择」这类无数据、行内也是居中控件的列使用居中排版。
    property bool centered: false

    implicitWidth: 0
    implicitHeight: 0
    Layout.preferredWidth: w > 0 ? w : -1
    Layout.minimumWidth: w > 0 ? w : 0
    Layout.fillWidth: w < 0
    Layout.fillHeight: true
    // 背景由外层整条色带提供，这里只做透明列容器，
    // 避免逐列绘制矩形在列间留下缝隙。
    color: "transparent"

    Label {
        anchors.fill: parent
        // 与 CellEditor 的 TextInput 保持同一个左内距（那边写的是 leftMargin: 10）。
        // 实测：表头用 4 时，表头文字比数据文字左偏 6px；改成 10 后两者重合。
        anchors.leftMargin: root.centered ? 0 : 10
        anchors.rightMargin: root.centered ? 0 : 10
        horizontalAlignment: root.centered ? Text.AlignHCenter : Text.AlignLeft
        verticalAlignment: Text.AlignVCenter
        text: root.text
        color: "white"
        font.pixelSize: AppStyle.fontSmall
        font.weight: Font.DemiBold
        elide: Text.ElideRight
    }
}
