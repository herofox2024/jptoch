import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Page {
    id: page
    padding: 24
    property var cfg: null
    property var gbridge: null

    property int totalCount: 0
    property int filteredCount: 0
    property bool dirty: false
    property var selectedRows: []

    function clearSelection() {
        page.selectedRows = []
    }

    function toggleRowSelection(rowIndex) {
        var rows = page.selectedRows.slice()
        var pos = rows.indexOf(rowIndex)
        if (pos >= 0) {
            rows.splice(pos, 1)
        } else {
            rows.push(rowIndex)
        }
        page.selectedRows = rows
    }

    Component.onCompleted: { if (page.gbridge && page.gbridge.model) page.gbridge.load() }

    Connections {
        target: page.gbridge
        function onLoaded(count) { page.totalCount = count; page.filteredCount = count; page.clearSelection() }
        function onSaved(count) { page.dirty = false; page.totalCount = count; page.clearSelection() }
        function onImportDone(added, skipped, conflicts, total) {
            page.totalCount = total
            page.clearSelection()
            statusLabel.text = "导入完成: +" + added + " | 跳过 " + skipped + " | 冲突 " + conflicts
        }
        function onExportDone(path, count) { statusLabel.text = "已导出 " + count + " 条术语" }
        function onRestoreDone(count) { page.totalCount = count; page.clearSelection(); statusLabel.text = "已恢复 " + count + " 条" }
        function onErrorOccurred(msg) { statusLabel.text = "错误: " + msg }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 16

        Label { text: "术语表"; font.pixelSize: 24; font.weight: Font.DemiBold }

        Label {
            id: statusLabel
            text: page.totalCount > 0 ? "共 " + page.totalCount + " 条术语" : "暂无术语"
            Layout.fillWidth: true
        }

        RowLayout {
            spacing: 8
            Button { text: "刷新"; onClicked: { if (page.gbridge) page.gbridge.load() } }
            Button { text: "新增术语"; onClicked: { if (page.gbridge) page.gbridge.addRow("Item") } }
            Button {
                text: "删除选中"
                onClicked: {
                    if (page.selectedRows.length > 0 && page.gbridge) {
                        page.gbridge.deleteRows(page.selectedRows)
                        page.selectedRows = []
                    }
                }
            }
            Button {
                text: "保存修改"; highlighted: page.dirty; enabled: page.dirty
                onClicked: { if (page.gbridge) page.gbridge.save() }
            }
        }

        RowLayout {
            spacing: 8
            Button { text: "增量导入 JSON"; onClicked: importDialog.open() }
            Button { text: "导出/备份 JSON"; onClicked: exportDialog.open() }
            Button { text: "恢复备份"; onClicked: restoreDialog.open() }
        }

        RowLayout {
            spacing: 16
            CheckBox {
                text: "启用术语表"
                checked: cfg ? cfg.enableGlossary : true
                onCheckedChanged: { if (cfg) cfg.enableGlossary = checked }
            }
            CheckBox {
                text: "自动提取术语（实验）"
                checked: cfg ? cfg.extractGlossary : false
                enabled: cfg ? cfg.enableGlossary : false
                onCheckedChanged: { if (cfg) cfg.extractGlossary = checked }
            }
        }

        RowLayout {
            spacing: 12
            TextField {
                id: searchField; Layout.fillWidth: true; placeholderText: "搜索术语..."
                onTextChanged: {
                    page.clearSelection()
                    if (page.gbridge) page.gbridge.search(text, categoryCombo.currentText, sourceCombo.currentText)
                }
            }
            ComboBox {
                id: categoryCombo; Layout.preferredWidth: 130
                model: ["全部分类","Person","Location","Org","Item","Skill","Creature"]
                onCurrentTextChanged: {
                    page.clearSelection()
                    if (page.gbridge) page.gbridge.search(searchField.text, currentText, sourceCombo.currentText)
                }
            }
            ComboBox {
                id: sourceCombo; Layout.preferredWidth: 130
                model: ["全部来源","自动提取","手动添加","未知来源"]
                onCurrentTextChanged: {
                    page.clearSelection()
                    if (page.gbridge) page.gbridge.search(searchField.text, categoryCombo.currentText, currentText)
                }
            }
        }

        // Column headers
        RowLayout {
            Layout.fillWidth: true
            spacing: 0
            Rectangle { Layout.preferredWidth: 48; height: 32; color: Material.primary
                Label { anchors.centerIn: parent; text: "选择"; font.pixelSize: 12; font.weight: Font.DemiBold; color: "white" }
            }
            Rectangle { Layout.preferredWidth: 90; height: 32; color: Material.primary
                Label { anchors.centerIn: parent; text: "分类"; font.pixelSize: 12; font.weight: Font.DemiBold; color: "white" }
            }
            Rectangle { Layout.preferredWidth: 220; height: 32; color: Material.primary
                Label { anchors.centerIn: parent; text: "原文"; font.pixelSize: 12; font.weight: Font.DemiBold; color: "white" }
            }
            Rectangle { Layout.preferredWidth: 220; height: 32; color: Material.primary
                Label { anchors.centerIn: parent; text: "译文"; font.pixelSize: 12; font.weight: Font.DemiBold; color: "white" }
            }
            Rectangle { Layout.fillWidth: true; height: 32; color: Material.primary
                Label { anchors.centerIn: parent; text: "备注/来源"; font.pixelSize: 12; font.weight: Font.DemiBold; color: "white" }
            }
        }

        // Table body using ListView
        ListView {
            id: listView
            Layout.fillWidth: true; Layout.fillHeight: true
            clip: true; spacing: 0

            model: page.gbridge ? page.gbridge.model : null

            delegate: Rectangle {
                id: rowDelegate
                width: listView.width; height: 36
                property bool isSelected: page.selectedRows.indexOf(index) >= 0
                color: isSelected
                    ? (Material.theme === Material.Dark ? "#263449" : "#e8f0ff")
                    : (index % 2 === 0 ? (Material.theme === Material.Dark ? "#1e1e1e" : "#fafafa") : "transparent")
                border.color: isSelected ? Material.accent : "transparent"
                border.width: isSelected ? 1 : 0

                RowLayout {
                    anchors.fill: parent; spacing: 0

                    // Selection
                    Rectangle {
                        Layout.preferredWidth: 48; Layout.fillHeight: true; color: "transparent"
                        Rectangle {
                            width: 18; height: 18; radius: 3
                            anchors.centerIn: parent
                            color: rowDelegate.isSelected ? Material.accent : "transparent"
                            border.color: rowDelegate.isSelected ? Material.accent : (Material.theme === Material.Dark ? "#777777" : "#999999")
                            border.width: 1
                            Label {
                                anchors.centerIn: parent
                                text: "✓"
                                visible: rowDelegate.isSelected
                                color: "white"
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.toggleRowSelection(index)
                        }
                    }

                    // Category
                    Rectangle {
                        Layout.preferredWidth: 90; Layout.fillHeight: true; color: "transparent"
                        TextInput {
                            anchors.fill: parent; anchors.margins: 6
                            verticalAlignment: Text.AlignVCenter
                            text: category || ""
                            font.pixelSize: 12; clip: true
                            readOnly: !(cfg ? cfg.enableGlossary : true)
                            onEditingFinished: { model.category = text; page.dirty = true }
                        }
                    }

                    // Original
                    Rectangle {
                        Layout.preferredWidth: 220; Layout.fillHeight: true; color: "transparent"
                        TextInput {
                            anchors.fill: parent; anchors.margins: 6
                            verticalAlignment: Text.AlignVCenter
                            text: original || ""
                            font.pixelSize: 12; clip: true
                            readOnly: !(cfg ? cfg.enableGlossary : true)
                            onEditingFinished: { model.original = text; page.dirty = true }
                        }
                    }

                    // Translation
                    Rectangle {
                        Layout.preferredWidth: 220; Layout.fillHeight: true; color: "transparent"
                        TextInput {
                            anchors.fill: parent; anchors.margins: 6
                            verticalAlignment: Text.AlignVCenter
                            text: translation || ""
                            font.pixelSize: 12; clip: true; color: Material.accent
                            readOnly: !(cfg ? cfg.enableGlossary : true)
                            onEditingFinished: { model.translation = text; page.dirty = true }
                        }
                    }

                    // Note
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true; color: "transparent"
                        TextInput {
                            anchors.fill: parent; anchors.margins: 6
                            verticalAlignment: Text.AlignVCenter
                            text: note || ""
                            font.pixelSize: 12; clip: true; color: (Material.theme === Material.Dark ? "#999999" : "#666666")
                            readOnly: true
                        }
                    }
                }
            }
        }
    }

    // Dialogs
    FileDialog {
        id: importDialog; title: "导入术语表 JSON"
        nameFilters: ["JSON (*.json)"]; fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                page.gbridge.importJson(decodeURIComponent(p))
            }
        }
    }
    FileDialog {
        id: exportDialog; title: "导出术语表 JSON"
        nameFilters: ["JSON (*.json)"]; fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                if (!p.toLowerCase().endsWith(".json")) p += ".json"
                page.gbridge.exportJson(p)
            }
        }
    }
    FileDialog {
        id: restoreDialog; title: "恢复术语表备份"
        nameFilters: ["JSON (*.json)"]; fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                page.gbridge.restoreBackup(decodeURIComponent(p))
            }
        }
    }
}
