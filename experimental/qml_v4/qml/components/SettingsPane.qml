import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ScrollView {
    id: root

    default property alias paneChildren: paneColumn.data

    clip: true
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical.policy: ScrollBar.AsNeeded

    ColumnLayout {
        id: paneColumn
        width: Math.max(0, root.availableWidth)
        spacing: AppStyle.spacingXLarge
    }
}
