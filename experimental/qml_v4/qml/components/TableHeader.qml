import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// 表头单元格。
//
// 关键约束：表头列宽必须与行内 delegate 的列宽完全一致，否则固定列之后的
// 弹性列会错位（表现为「应用策略」表头与下拉框对不齐）。
//
// 为此：
//   1. implicitWidth/implicitHeight 归零 —— Rectangle 自身隐式为 0，但内部
//      Label 会撑出隐式宽度；不清零则 RowLayout 的最小宽度被文本撑开。
//   2. 同时给出 preferredWidth 与 minimumWidth，固定列既不压缩也不扩张。
Rectangle {
    id: root
    property int w: 100
    property string text: ""
    property bool first: false
    property bool last: false

    implicitWidth: 0
    implicitHeight: 0
    Layout.preferredWidth: w > 0 ? w : -1
    Layout.minimumWidth: w > 0 ? w : 0
    Layout.fillWidth: w < 0
    Layout.fillHeight: true
    // 背景由外层整条色带提供，这里只做透明列容器 + 居中文字，
    // 避免逐列绘制矩形在列间留下缝隙。
    color: "transparent"

    Label {
        anchors.centerIn: parent
        text: root.text
        color: "white"
        font.pixelSize: AppStyle.fontSmall
        font.weight: Font.DemiBold
    }
}
