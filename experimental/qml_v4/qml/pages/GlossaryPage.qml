import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

Page {
    id: page
    padding: 24
    background: Item {}

    property var cfg: null
    property var gbridge: null

    property int totalCount: 0
    property int filteredCount: 0
    property int autoCount: 0
    property int manualCount: 0
    property int unknownCount: 0
    property bool dirty: false
    property bool loadedOnce: false
    property var selectedRows: []
    property string statusMessage: "暂无术语"
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    function clearSelection() {
        page.selectedRows = []
    }

    function toggleRowSelection(rowIndex) {
        var rows = page.selectedRows.slice()
        var pos = rows.indexOf(rowIndex)
        if (pos >= 0) rows.splice(pos, 1)
        else rows.push(rowIndex)
        page.selectedRows = rows
    }

    function refreshStats() {
        if (!page.gbridge) return
        var stats = page.gbridge.getStats()
        page.totalCount = stats.total || 0
        page.filteredCount = stats.filtered || 0
        page.autoCount = stats.auto || 0
        page.manualCount = stats.manual || 0
        page.unknownCount = stats.unknown || 0
        if (page.statusMessage === "" || page.statusMessage === "暂无术语" || page.statusMessage.indexOf("共 ") === 0) {
            page.statusMessage = page.totalCount > 0 ? "共 " + page.totalCount + " 条术语，当前显示 " + page.filteredCount + " 条" : "暂无术语"
        }
    }

    function applySearch() {
        page.clearSelection()
        if (page.gbridge) {
            page.gbridge.search(searchField.text, categoryCombo.currentText, sourceCombo.currentText)
            page.refreshStats()
        }
    }

    function scheduleSearch() {
        searchDebounceTimer.restart()
    }

    function ensureLoaded() {
        if (page.loadedOnce || !page.gbridge || !page.gbridge.model) return
        page.statusMessage = "正在加载术语表..."
        page.loadedOnce = true
        page.gbridge.load()
    }

    Timer {
        id: searchDebounceTimer
        interval: 220
        repeat: false
        onTriggered: page.applySearch()
    }

    Connections {
        target: page.gbridge
        function onLoaded(count) {
            page.loadedOnce = true
            page.statusMessage = count > 0 ? "共 " + count + " 条术语" : "暂无术语"
            page.clearSelection()
            page.refreshStats()
        }
        function onSaved(count) {
            page.dirty = false
            page.statusMessage = "已保存 " + count + " 条术语"
            page.clearSelection()
            page.refreshStats()
        }
        function onImportDone(added, skipped, conflicts, total) {
            page.statusMessage = "导入完成: +" + added + " | 跳过 " + skipped + " | 冲突 " + conflicts
            page.clearSelection()
            page.refreshStats()
        }
        function onExportDone(path, count) {
            page.statusMessage = "已导出 " + count + " 条术语"
            page.refreshStats()
        }
        function onRestoreDone(count) {
            page.statusMessage = "已恢复 " + count + " 条术语"
            page.clearSelection()
            page.refreshStats()
        }
        function onErrorOccurred(msg) {
            page.statusMessage = "错误: " + msg
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: "术语表"
                    color: AppPalette.textColor
                    font.family: page.titleFont
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                }
                Label {
                    text: page.statusMessage
                    color: AppPalette.mutedText
                    font.pixelSize: 13
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            Rectangle {
                Layout.preferredWidth: 120
                Layout.preferredHeight: 34
                radius: 17
                color: page.dirty ? (AppPalette.dark ? "#3b2d1c" : "#f2e4cf") : AppPalette.accentSoft
                border.color: page.dirty ? AppPalette.amberColor : AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: page.dirty ? "有未保存修改" : "已同步"
                    color: page.dirty ? AppPalette.amberColor : AppPalette.accentColor
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: page.width > 940 ? 4 : 2
            columnSpacing: 10
            rowSpacing: 10

            StatTile { title: "总术语"; value: page.totalCount; tone: "accent" }
            StatTile { title: "自动提取"; value: page.autoCount; tone: "amber" }
            StatTile { title: "手动添加"; value: page.manualCount; tone: "success" }
            StatTile { title: "未知来源"; value: page.unknownCount; tone: "neutral" }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 104
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            RowLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Rectangle {
                            id: searchField
                            Layout.fillWidth: true
                            Layout.preferredHeight: 50
                            radius: 18
                            color: AppPalette.fieldBg
                            border.color: searchInput.activeFocus ? AppPalette.accentColor : AppPalette.lineColor
                            border.width: searchInput.activeFocus ? 2 : 1
                            property alias text: searchInput.text

                            Label {
                                anchors.left: parent.left
                                anchors.leftMargin: 18
                                anchors.verticalCenter: parent.verticalCenter
                                visible: searchInput.text.length === 0 && !searchInput.activeFocus
                                text: "搜索术语、译名、备注或来源..."
                                color: AppPalette.mutedText
                                font.pixelSize: 13
                                elide: Text.ElideRight
                            }

                            TextInput {
                                id: searchInput
                                anchors.fill: parent
                                anchors.leftMargin: 18
                                anchors.rightMargin: 18
                                verticalAlignment: Text.AlignVCenter
                                color: AppPalette.textColor
                                selectedTextColor: "white"
                                selectionColor: AppPalette.accentColor
                                font.pixelSize: 14
                                clip: true
                                selectByMouse: true
                                onTextChanged: page.scheduleSearch()
                            }
                        }

                        ComboBox {
                            id: categoryCombo
                            Layout.preferredWidth: 148
                            model: ["全部分类", "Person", "Location", "Org", "Item", "Skill", "Creature"]
                            onCurrentTextChanged: page.scheduleSearch()
                        }

                        ComboBox {
                            id: sourceCombo
                            Layout.preferredWidth: 148
                            model: ["全部来源", "自动提取", "手动添加", "未知来源"]
                            onCurrentTextChanged: page.scheduleSearch()
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "当前显示 " + page.filteredCount + " / " + page.totalCount + " 条；选中 " + page.selectedRows.length + " 条。"
                        color: AppPalette.mutedText
                        font.pixelSize: 11
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            radius: AppPalette.radiusLarge
            color: AppPalette.cardBg
            border.color: AppPalette.borderColor

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 14
                spacing: 10

                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    Button {
                        text: "刷新"
                        onClicked: { if (page.gbridge) page.gbridge.load() }
                    }
                    Button {
                        text: "新增术语"
                        onClicked: {
                            if (page.gbridge) {
                                page.gbridge.addRow("Item")
                                page.statusMessage = "已新增一条手动术语，请填写后保存"
                                page.refreshStats()
                            }
                        }
                    }
                    Button {
                        text: "删除选中"
                        enabled: page.selectedRows.length > 0
                        onClicked: {
                            if (page.selectedRows.length > 0 && page.gbridge) {
                                page.gbridge.deleteRows(page.selectedRows)
                                page.selectedRows = []
                                page.statusMessage = "已删除选中术语，保存后写入文件"
                                page.refreshStats()
                            }
                        }
                    }
                    Button {
                        text: "保存修改"
                        highlighted: page.dirty
                        enabled: page.dirty
                        onClicked: { if (page.gbridge) page.gbridge.save() }
                    }
                    Button { text: "增量导入 JSON"; onClicked: importDialog.open() }
                    Button { text: "导出/备份 JSON"; onClicked: exportDialog.open() }
                    Button { text: "恢复备份"; onClicked: restoreDialog.open() }
                }

                CheckBox {
                    text: "启用术语表"
                    checked: cfg ? cfg.enableGlossary : true
                    onCheckedChanged: { if (cfg) cfg.enableGlossary = checked }
                }
                CheckBox {
                    text: "自动提取"
                    checked: cfg ? cfg.extractGlossary : false
                    enabled: cfg ? cfg.enableGlossary : false
                    onCheckedChanged: { if (cfg) cfg.extractGlossary = checked }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: AppPalette.radiusLarge
            color: AppPalette.cardBg
            border.color: AppPalette.borderColor
            clip: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    TableHeader { w: 56; text: "选择"; first: true }
                    TableHeader { w: 104; text: "分类" }
                    TableHeader { w: 240; text: "原文" }
                    TableHeader { w: 240; text: "译文" }
                    TableHeader { w: 132; text: "应用策略" }
                    TableHeader { w: -1; text: "备注/来源"; last: true }
                }

                ListView {
                    id: listView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    model: page.gbridge ? page.gbridge.model : null
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        id: rowDelegate
                        width: listView.width
                        height: 46
                        property bool isSelected: page.selectedRows.indexOf(index) >= 0
                        color: isSelected
                               ? (AppPalette.dark ? "#31463f" : "#d7ece5")
                               : (index % 2 === 0 ? AppPalette.surfaceRaised : AppPalette.cardBg)
                        border.color: isSelected ? AppPalette.amberColor : AppPalette.lineColor
                        border.width: isSelected ? 2 : 1

                        RowLayout {
                            anchors.fill: parent
                            spacing: 0

                            Rectangle {
                                Layout.preferredWidth: 56
                                Layout.fillHeight: true
                                color: "transparent"
                                Rectangle {
                                    width: 21
                                    height: 21
                                    radius: 6
                                    anchors.centerIn: parent
                                    color: rowDelegate.isSelected ? AppPalette.amberColor : "transparent"
                                    border.color: rowDelegate.isSelected ? AppPalette.amberColor : AppPalette.mutedText
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

                            CellEditor {
                                w: 104
                                value: category || ""
                                editable: cfg ? cfg.enableGlossary : true
                                onCommit: function(text) { model.category = text; page.dirty = true; page.refreshStats() }
                            }
                            CellEditor {
                                w: 240
                                value: original || ""
                                editable: cfg ? cfg.enableGlossary : true
                                onCommit: function(text) { model.original = text; page.dirty = true; page.refreshStats() }
                            }
                            CellEditor {
                                w: 240
                                value: translation || ""
                                editable: cfg ? cfg.enableGlossary : true
                                accent: true
                                onCommit: function(text) { model.translation = text; page.dirty = true; page.refreshStats() }
                            }
                            PolicySelector {
                                w: 132
                                value: policy || "默认策略"
                                editable: cfg ? cfg.enableGlossary : true
                                onCommit: function(text) { model.policy = text; page.dirty = true; page.refreshStats() }
                            }
                            CellEditor {
                                w: -1
                                value: note || ""
                                editable: false
                                muted: true
                            }
                        }
                    }

                    Rectangle {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 48, 420)
                        height: 128
                        radius: AppPalette.radiusLarge
                        visible: listView.count === 0
                        color: AppPalette.surfaceRaised
                        border.color: AppPalette.borderColor

                        ColumnLayout {
                            anchors.centerIn: parent
                            width: parent.width - 36
                            spacing: 8
                            Label {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: page.totalCount > 0 ? "没有匹配的术语" : "术语表为空"
                                color: AppPalette.textColor
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                text: page.totalCount > 0
                                      ? "请调整搜索关键词、分类或来源筛选。"
                                      : "可以新增术语，或通过“增量导入 JSON”导入已有术语表。"
                                color: AppPalette.mutedText
                                font.pixelSize: 12
                            }
                        }
                    }
                }
            }
        }
    }

    FileDialog {
        id: importDialog
        title: "导入术语表 JSON"
        nameFilters: ["JSON (*.json)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                page.gbridge.importJson(p)
            }
        }
    }

    FileDialog {
        id: exportDialog
        title: "导出术语表 JSON"
        nameFilters: ["JSON (*.json)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                if (!p.toLowerCase().endsWith(".json")) p += ".json"
                page.gbridge.exportJson(p)
            }
        }
    }

    FileDialog {
        id: restoreDialog
        title: "恢复术语表备份"
        nameFilters: ["JSON (*.json)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                page.gbridge.restoreBackup(p)
            }
        }
    }

    component StatTile: Rectangle {
        property string title: ""
        property var value: 0
        property string tone: "neutral"

        Layout.fillWidth: true
        Layout.preferredHeight: 72
        radius: AppPalette.radiusMedium
        color: AppPalette.surfaceRaised
        border.color: AppPalette.lineColor

        readonly property color toneColor: tone === "accent"
                                           ? AppPalette.accentColor
                                           : tone === "amber"
                                             ? AppPalette.amberColor
                                             : tone === "success"
                                               ? AppPalette.successColor
                                               : AppPalette.textColor

        Rectangle {
            width: 34
            height: 4
            radius: 2
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.topMargin: 12
            color: parent.toneColor
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            anchors.topMargin: 22
            anchors.bottomMargin: 10
            spacing: 2
            Label {
                Layout.fillWidth: true
                text: title
                color: AppPalette.mutedText
                font.pixelSize: 11
            }
            Label {
                Layout.fillWidth: true
                text: value !== undefined ? value.toString() : "0"
                color: parent.parent.toneColor
                font.pixelSize: 20
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
        }
    }

    component TableHeader: Rectangle {
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
            text: parent.text
            color: "white"
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
    }

    component CellEditor: Rectangle {
        id: cell
        property int w: 100
        property string value: ""
        property bool editable: true
        property bool accent: false
        property bool muted: false
        signal commit(string text)

        Layout.preferredWidth: w > 0 ? w : -1
        Layout.fillWidth: w < 0
        Layout.fillHeight: true
        color: "transparent"

        TextInput {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            verticalAlignment: Text.AlignVCenter
            text: cell.value
            font.pixelSize: 13
            clip: true
            selectByMouse: true
            readOnly: !cell.editable
            color: cell.accent ? AppPalette.accentColor : (cell.muted ? AppPalette.mutedText : AppPalette.textColor)
            selectedTextColor: "white"
            selectionColor: AppPalette.accentColor
            onEditingFinished: cell.commit(text)
        }
    }

    component PolicySelector: Rectangle {
        id: policyCell
        property int w: 132
        property string value: "默认策略"
        property bool editable: true
        signal commit(string text)

        Layout.preferredWidth: w > 0 ? w : -1
        Layout.fillWidth: w < 0
        Layout.fillHeight: true
        color: "transparent"

        ComboBox {
            id: policyCombo
            anchors.fill: parent
            anchors.leftMargin: 6
            anchors.rightMargin: 6
            anchors.topMargin: 5
            anchors.bottomMargin: 5
            enabled: policyCell.editable
            model: ["默认策略", "强制使用", "仅供参考", "上下文命中", "保留原文", "忽略校对"]
            currentIndex: Math.max(0, model.indexOf(policyCell.value))
            font.pixelSize: 12
            onActivated: function(index) {
                policyCell.commit(model[index])
            }
        }
    }
}
