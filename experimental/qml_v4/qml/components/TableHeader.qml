import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    property int w: 100
    property string text: ""
    property bool first: false
    property bool last: false

    Layout.preferredWidth: w > 0 ? w : -1
    Layout.fillWidth: w < 0
    height: 38
    color: AppPalette.accentColor
    Label {
        anchors.centerIn: parent
        text: root.text
        color: "white"
        font.pixelSize: AppStyle.fontSmall
        font.weight: Font.DemiBold
    }
}
