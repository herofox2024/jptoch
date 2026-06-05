pragma Singleton
import QtQuick
import QtQuick.Controls.Material

QtObject {
    readonly property color hintColor: Material.theme === Material.Dark ? "#999999" : "#666666"
    readonly property color accentColor: Material.accent
    readonly property color successColor: "#4caf50"
    readonly property color errorColor: "#e53935"
    readonly property color borderColor: Material.theme === Material.Dark ? "#444444" : "#cccccc"
    readonly property color cardBg: Material.theme === Material.Dark ? "#1e1e1e" : "#fafafa"
}