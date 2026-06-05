import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Page {
    id: taskPage
    padding: 24
    property var cfg: null
    property var tbridge: null  // kept for compatibility
    signal navigateToStatus()

    ColumnLayout {
        anchors.fill: parent
        spacing: 16

        Label { text: "任务"; font.pixelSize: 24; font.weight: Font.DemiBold }
        Label { text: "选择 EPUB 文件并开始翻译"; color: (Material.theme === Material.Dark ? "#999999" : "#666666"); font.pixelSize: 14 }

        Pane {
            id: dropArea
            Layout.fillWidth: true; Layout.preferredHeight: 120; Material.elevation: 2
            property bool hovering: false
            Rectangle {
                anchors.fill: parent; color: "transparent"; border.width: 2
                border.color: dropArea.hovering ? Material.accent : (Material.theme === Material.Dark ? "#444444" : "#cccccc"); radius: 8
            }
            ColumnLayout {
                anchors.centerIn: parent
                Label {
                    text: dropArea.hovering ? "释放以上传 EPUB" : "拖放 EPUB 文件到此处\n或点击下方按钮选择"
                    horizontalAlignment: Text.AlignHCenter; color: (Material.theme === Material.Dark ? "#999999" : "#666666")
                    Layout.alignment: Qt.AlignHCenter
                }
            }
            DropArea {
                anchors.fill: parent
                onEntered: dropArea.hovering = true
                onExited: dropArea.hovering = false
                onDropped: function(drop) {
                    dropArea.hovering = false
                    if (drop.urls.length > 0) {
                        var path = drop.urls[0].toString()
                        if (path.startsWith("file:///")) path = path.substring(8)
                        else if (path.startsWith("file://")) path = path.substring(7)
                        path = decodeURIComponent(path)
                        taskPage.setInputPath(path)
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true; spacing: 12
            TextField {
                id: inpField; Layout.fillWidth: true
                placeholderText: "输入 EPUB 路径"
                text: cfg ? cfg.inp : ""
                onTextChanged: {
                    if (cfg) cfg.inp = text
                    estimateTimer.restart()
                }
            }
            Button { text: "浏览..."; onClicked: inputDialog.open() }
        }

        RowLayout {
            Layout.fillWidth: true; spacing: 12
            TextField {
                id: outField; Layout.fillWidth: true
                placeholderText: "输出文件路径 (.epub)"
                text: cfg ? cfg.out : ""
                onTextChanged: { if (cfg) cfg.out = text }
            }
            Button { text: "浏览..."; onClicked: outputDialog.open() }
        }

        Label {
            id: estimateLabel
            text: "预估字符: —"
            font.pixelSize: 13; color: (Material.theme === Material.Dark ? "#999999" : "#666666")
        }

        RowLayout {
            spacing: 12
            Button {
                id: startBtn; text: "开始翻译"
                highlighted: true; Material.accent: Material.Indigo
                enabled: cfg && cfg.inp !== "" && cfg.out !== "" && !(tbridge ? TranslateBridge.busy : false)
                onClicked: {
                    if (tbridge) {
                        TranslateBridge.startTranslation(cfg)
                        taskPage.navigateToStatus()
                    }
                }
            }
            Button {
                text: "暂停"
                enabled: tbridge ? TranslateBridge.busy : false
                onClicked: { if (tbridge) TranslateBridge.pauseTranslation() }
            }
            Button {
                text: "恢复"
                enabled: tbridge ? !TranslateBridge.busy : false
                onClicked: { if (tbridge) TranslateBridge.resumeTranslation(cfg) }
            }
        }

        Label {
            text: "数据目录: " + (AppDir || "")
            font.pixelSize: 11; color: (Material.theme === Material.Dark ? "#999999" : "#666666")
        }

        Item { Layout.fillHeight: true }
    }

    // --- Dialogs ---
    FileDialog {
        id: inputDialog; title: "选择 EPUB 文件"
        nameFilters: ["EPUB 文件 (*.epub)"]; fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                taskPage.setInputPath(p)
            }
        }
    }

    FileDialog {
        id: outputDialog; title: "保存翻译后的 EPUB"
        nameFilters: ["EPUB 文件 (*.epub)"]; fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                if (!p.toLowerCase().endsWith(".epub")) p += ".epub"
                if (cfg) cfg.out = p
            }
        }
    }

    // --- Estimate timer (300ms debounce) ---
    Timer {
        id: estimateTimer; interval: 300
        onTriggered: {
            if (cfg && cfg.inp) {
                estimateLabel.text = "预估字符: 计算中..."
                if (tbridge) TranslateBridge.startEstimateChars(cfg.inp)
            }
        }
    }

    // --- Bridge signal handlers ---
    Connections {
        target: TranslateBridge
        enabled: true
        function onEstimateFinished(path, chars) {
            if (path === cfg.inp && chars >= 0) {
                estimateLabel.text = "预估字符: " + chars.toLocaleString()
            }
        }
        function onEstimateFailed(path, err) {
            if (path === cfg.inp) {
                estimateLabel.text = "预估字符: 读取失败"
            }
        }
    }

    // --- Helpers ---
    function setInputPath(path) {
        if (cfg) cfg.inp = path
        if (cfg && (!cfg.out || cfg.out === "")) {
            var dir = path.substring(0, path.lastIndexOf("/") + 1)
            var base = path.substring(path.lastIndexOf("/") + 1)
            base = base.replace(/\.epub$/i, "")
            cfg.out = dir + base + "_zh.epub"
        }
        estimateLabel.text = "预估字符: 计算中..."
        if (tbridge) TranslateBridge.startEstimateChars(path)
    }

    Component.onCompleted: {
        if (cfg && cfg.inp && tbridge) TranslateBridge.startEstimateChars(cfg.inp)
    }
}