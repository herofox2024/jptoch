import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

Page {
    id: page
    padding: AppStyle.pagePadding
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
    property string glossaryProfileStatus: ""
    property var glossaryProfileScopeValues: ["all", "genre", "series", "book"]
    property var glossaryProfileScopeLabels: ["全部", "题材", "系列", "本书"]
    property var glossaryProfileTargetScopeValues: ["genre", "series", "book"]
    property var glossaryProfileTargetScopeLabels: ["题材", "系列", "本书"]
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    ListModel { id: glossaryProfileModel }

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

    function glossaryProfileScopeValue(index) {
        return page.glossaryProfileScopeValues[index] || ""
    }

    function glossaryProfileTargetScopeValue(index) {
        return page.glossaryProfileTargetScopeValues[index] || "book"
    }

    function glossaryProfileScopeIndex(value) {
        var idx = page.glossaryProfileScopeValues.indexOf(value || "all")
        return idx >= 0 ? idx : 0
    }

    function glossaryProfileTargetScopeIndex(value) {
        var idx = page.glossaryProfileTargetScopeValues.indexOf(value || "book")
        return idx >= 0 ? idx : 2
    }

    function glossaryProfileScopeLabel(value) {
        var idx = page.glossaryProfileScopeValues.indexOf(value || "all")
        return idx >= 0 ? page.glossaryProfileScopeLabels[idx] : "全部"
    }

    function formatTimestamp(ts) {
        if (!ts) return "-"
        var value = new Date(ts * 1000)
        if (isNaN(value.getTime())) return "-"
        return Qt.formatDateTime(value, "yyyy-MM-dd hh:mm")
    }

    function refreshGlossaryProfiles() {
        if (!page.cfg || !page.cfg.listGlossaryProfiles) return
        var scope = page.glossaryProfileScopeValue(profileFilterCombo.currentIndex)
        var items = page.cfg.listGlossaryProfiles(scope === "all" ? "" : scope)
        glossaryProfileModel.clear()
        for (var i = 0; i < items.length; i++) {
            var item = items[i] || {}
            glossaryProfileModel.append({
                "profileId": item.profileId || item.id || "",
                "name": item.name || "",
                "scope": item.scope || "",
                "description": item.description || "",
                "sourceBook": item.sourceBook || "",
                "termCount": item.termCount || 0,
                "createdAt": item.createdAt || 0,
                "updatedAt": item.updatedAt || 0
            })
        }
        page.glossaryProfileStatus = glossaryProfileModel.count > 0
                ? "共 " + glossaryProfileModel.count + " 个 profile"
                : "暂无 profile"
    }

    function saveCurrentGlossaryProfile() {
        if (!page.cfg || !page.cfg.saveCurrentGlossaryAsProfile) return
        var name = glossaryProfileNameField.text.trim()
        if (!name) {
            page.glossaryProfileStatus = "请输入 profile 名称"
            return
        }
        var scope = page.glossaryProfileTargetScopeValue(profileTargetCombo.currentIndex)
        var sourceBook = glossaryProfileSourceField.text.trim()
        var result = page.cfg.saveCurrentGlossaryAsProfile(scope, name, sourceBook)
        page.glossaryProfileStatus = result.message || ""
        if (result.ok) {
            page.refreshGlossaryProfiles()
        }
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(page.glossaryProfileStatus) : ToastBridge.showError(page.glossaryProfileStatus)
        }
    }

    function deleteGlossaryProfile(profileId) {
        if (!page.cfg || !page.cfg.deleteGlossaryProfile || !profileId) return
        var result = page.cfg.deleteGlossaryProfile(profileId)
        page.glossaryProfileStatus = result.message || ""
        page.refreshGlossaryProfiles()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(page.glossaryProfileStatus) : ToastBridge.showError(page.glossaryProfileStatus)
        }
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

    Connections {
        target: page.cfg
        ignoreUnknownSignals: true

        function onGlossaryProfilesChanged() {
            page.refreshGlossaryProfiles()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: AppStyle.spacingXXLarge

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingXLarge

            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingTight
                Label {
                    text: "术语表"
                    color: AppPalette.textColor
                    font.family: page.titleFont
                    font.pixelSize: AppStyle.fontPageTitle
                    font.weight: Font.DemiBold
                }
                Label {
                    text: page.statusMessage
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontBody
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            Rectangle {
                Layout.preferredWidth: 120
                Layout.preferredHeight: AppStyle.buttonHeightSmall
                radius: 17
                color: page.dirty ? AppStyle.statusWarningBg : AppStyle.statusAccentBg
                border.color: page.dirty ? AppPalette.amberColor : AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: page.dirty ? "有未保存修改" : "已同步"
                    color: page.dirty ? AppPalette.amberColor : AppPalette.accentColor
                    font.pixelSize: AppStyle.fontSmall
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
            StatTile { title: "模型提取"; value: page.autoCount; tone: "amber" }
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
                spacing: AppStyle.spacingLarge

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingInline

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingMedium

                        Rectangle {
                            id: searchField
                            Layout.fillWidth: true
                            Layout.preferredHeight: AppStyle.fieldHeight
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
                                font.pixelSize: AppStyle.fontBody
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
                                font.pixelSize: AppStyle.fontBodyLarge
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
                            model: ["全部来源", "模型提取", "手动添加", "未知来源"]
                            onCurrentTextChanged: page.scheduleSearch()
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "当前显示 " + page.filteredCount + " / " + page.totalCount + " 条；选中 " + page.selectedRows.length + " 条。"
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontCaption
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: toolbarContent.implicitHeight + 28
            radius: AppPalette.radiusLarge
            color: AppPalette.cardBg
            border.color: AppPalette.borderColor

            ColumnLayout {
                id: toolbarContent
                anchors.fill: parent
                anchors.margins: 14
                spacing: AppStyle.spacingSmall

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingInline

                    Flow {
                        id: primaryActions
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingSmall
                        readonly property real actionButtonWidth: Math.max(112, Math.min(150, Math.floor((width - spacing * 3) / 4)))

                        Button {
                            text: "刷新"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 76
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: { if (page.gbridge) page.gbridge.load() }
                        }
                        Button {
                            text: "新增术语"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
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
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
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
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            highlighted: page.dirty
                            enabled: page.dirty
                            onClicked: { if (page.gbridge) page.gbridge.save() }
                        }
                        Button {
                            text: "导入 JSON"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: importDialog.open()
                        }
                        Button {
                            text: "导入 CSV"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: importCsvDialog.open()
                        }
                        Button {
                            text: "导出 JSON"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 96
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: exportDialog.open()
                        }
                        Button {
                            text: "导出 CSV"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: exportCsvDialog.open()
                        }
                        Button {
                            text: "恢复备份"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 92
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: restoreDialog.open()
                        }
                        Button {
                            text: "Profile 管理"
                            width: primaryActions.actionButtonWidth
                            Layout.minimumWidth: 104
                            height: AppStyle.buttonHeightSmall
                            leftPadding: 6
                            rightPadding: 6
                            font.pixelSize: AppStyle.fontSmall
                            onClicked: {
                                page.refreshGlossaryProfiles()
                                glossaryProfileDialog.open()
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    CheckBox {
                        text: "启用术语表"
                        checked: cfg ? cfg.enableGlossary : true
                        onCheckedChanged: { if (cfg) cfg.enableGlossary = checked }
                    }
                    Label {
                        Layout.fillWidth: true
                        text: "术语提取已改为任务页的独立功能；这里仅管理全局术语表。"
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontCaption
                        elide: Text.ElideRight
                    }
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
                spacing: AppStyle.spacingNone

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingNone
                    TableHeader { w: 56; text: "选择"; first: true }
                    TableHeader { w: 104; text: "分类" }
                    TableHeader { w: 210; text: "原文" }
                    TableHeader { w: 210; text: "译文" }
                    TableHeader { w: 220; text: "中文别名" }
                    TableHeader { w: 120; text: "应用策略" }
                    TableHeader { w: -1; text: "备注/来源"; last: true }
                }

                ListView {
                    id: listView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: AppStyle.spacingTight
                    model: page.gbridge ? page.gbridge.model : null
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: Rectangle {
                        id: rowDelegate
                        width: listView.width
                        height: 46
                        property bool isSelected: page.selectedRows.indexOf(index) >= 0
                        color: isSelected
                               ? AppStyle.statusAccentBg
                               : (index % 2 === 0 ? AppPalette.surfaceRaised : AppPalette.cardBg)
                        border.color: isSelected ? AppPalette.amberColor : AppPalette.lineColor
                        border.width: isSelected ? 2 : 1

                        RowLayout {
                            anchors.fill: parent
                            spacing: AppStyle.spacingNone

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
                                        font.pixelSize: AppStyle.fontBody
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
                                w: 210
                                value: original || ""
                                editable: cfg ? cfg.enableGlossary : true
                                onCommit: function(text) { model.original = text; page.dirty = true; page.refreshStats() }
                            }
                            CellEditor {
                                w: 210
                                value: translation || ""
                                editable: cfg ? cfg.enableGlossary : true
                                accent: true
                                onCommit: function(text) { model.translation = text; page.dirty = true; page.refreshStats() }
                            }
                            CellEditor {
                                w: 220
                                value: aliases || ""
                                editable: cfg ? cfg.enableGlossary : true
                                onCommit: function(text) { model.aliases = text; page.dirty = true; page.refreshStats() }
                            }
                            PolicySelector {
                                w: 120
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
                            spacing: AppStyle.spacingSmall
                            Label {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                text: page.totalCount > 0 ? "没有匹配的术语" : "术语表为空"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSection
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.fillWidth: true
                                horizontalAlignment: Text.AlignHCenter
                                wrapMode: Text.WordWrap
                                text: page.totalCount > 0
                                      ? "请调整搜索关键词、分类或来源筛选。"
                                      : "可以新增术语，或通过“导入 JSON/CSV”导入已有术语表。"
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontSmall
                            }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: glossaryProfileDialog
        modal: true
        anchors.centerIn: parent
        width: Math.max(760, Math.min(page.width - 48, 1040))
        height: Math.max(520, Math.min(page.height - 72, 820))
        title: "术语 Profile 管理"
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: page.refreshGlossaryProfiles()

        contentItem: ScrollView {
            width: glossaryProfileDialog.width
            height: glossaryProfileDialog.height
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: Math.max(0, glossaryProfileDialog.width - 32)
                spacing: AppStyle.spacingLarge

                Label {
                    Layout.fillWidth: true
                    text: "把不同题材、系列或单本书的术语保存为独立 profile。任务页可独立提取当前书术语；翻译时是否使用 profile 由任务页的分层术语开关决定。"
                    color: AppPalette.mutedText
                    wrapMode: Text.WordWrap
                    font.pixelSize: AppStyle.fontSmall
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    Label {
                        text: "存放目录"
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontSmall
                        font.weight: Font.DemiBold
                    }
                    TextField {
                        Layout.fillWidth: true
                        text: page.cfg ? page.cfg.glossaryProfilesPath : ""
                        readOnly: true
                        selectByMouse: true
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontCaption
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: page.width > 920 ? 4 : 2
                    rowSpacing: 8
                    columnSpacing: 12

                    Label { text: "过滤范围" }
                    ComboBox {
                        id: profileFilterCombo
                        Layout.fillWidth: true
                        model: page.glossaryProfileScopeLabels
                        currentIndex: page.glossaryProfileScopeIndex("all")
                        onActivated: page.refreshGlossaryProfiles()
                    }

                    Label { text: "保存范围" }
                    ComboBox {
                        id: profileTargetCombo
                        Layout.fillWidth: true
                        model: page.glossaryProfileTargetScopeLabels
                        currentIndex: page.glossaryProfileTargetScopeIndex("book")
                    }

                    Label { text: "profile 名称" }
                    TextField {
                        id: glossaryProfileNameField
                        Layout.fillWidth: true
                        placeholderText: "例如：某系列术语 / 某题材术语 / 本书术语"
                        selectByMouse: true
                    }

                    Label { text: "来源书名" }
                    TextField {
                        id: glossaryProfileSourceField
                        Layout.fillWidth: true
                        placeholderText: "可留空；独立提取时会自动写入"
                        selectByMouse: true
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingSmall

                    Button {
                        text: "保存当前术语表"
                        highlighted: true
                        onClicked: page.saveCurrentGlossaryProfile()
                    }

                    Button {
                        text: "刷新"
                        onClicked: page.refreshGlossaryProfiles()
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: page.glossaryProfileStatus
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
                        elide: Text.ElideRight
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 420
                    radius: AppPalette.radiusLarge
                    color: AppPalette.cardBg
                    border.color: AppPalette.borderColor
                    clip: true

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: AppStyle.spacingNone

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingNone
                            TableHeader { w: 92; text: "范围"; first: true }
                            TableHeader { w: 220; text: "名称" }
                            TableHeader { w: 110; text: "术语数" }
                            TableHeader { w: 180; text: "来源书名" }
                            TableHeader { w: 170; text: "更新时间" }
                            TableHeader { w: -1; text: "说明 / 操作"; last: true }
                        }

                        ListView {
                            id: profileListView
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            spacing: AppStyle.spacingTight
                            model: glossaryProfileModel
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            delegate: Rectangle {
                                width: profileListView.width
                                height: 52
                                color: index % 2 === 0 ? AppPalette.surfaceRaised : AppPalette.cardBg
                                border.color: AppPalette.lineColor

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 8
                                    spacing: AppStyle.spacingSmall

                                    Label {
                                        Layout.preferredWidth: 92
                                        text: page.glossaryProfileScopeLabel(scope)
                                        color: AppPalette.accentColor
                                        font.pixelSize: AppStyle.fontCaption
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.preferredWidth: 220
                                        text: name || "-"
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontCaption
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.preferredWidth: 110
                                        text: (termCount || 0) + " 条"
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontCaption
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.preferredWidth: 180
                                        text: sourceBook || "-"
                                        color: AppPalette.mutedText
                                        font.pixelSize: AppStyle.fontCaption
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.preferredWidth: 170
                                        text: page.formatTimestamp(updatedAt || createdAt)
                                        color: AppPalette.mutedText
                                        font.pixelSize: AppStyle.fontTiny
                                        elide: Text.ElideRight
                                    }

                                    Label {
                                        Layout.fillWidth: true
                                        text: description || "-"
                                        color: AppPalette.mutedText
                                        font.pixelSize: AppStyle.fontTiny
                                        elide: Text.ElideRight
                                    }

                                    Button {
                                        text: "删除"
                                        onClicked: page.deleteGlossaryProfile(profileId)
                                    }
                                }
                            }

                            Rectangle {
                                anchors.centerIn: parent
                                width: Math.min(parent.width - 48, 420)
                                height: 112
                                radius: AppPalette.radiusLarge
                                visible: glossaryProfileModel.count === 0
                                color: AppPalette.surfaceRaised
                                border.color: AppPalette.borderColor

                                ColumnLayout {
                                    anchors.centerIn: parent
                                    width: parent.width - 36
                                    spacing: AppStyle.spacingSmall
                                    Label {
                                        Layout.fillWidth: true
                                        horizontalAlignment: Text.AlignHCenter
                                        text: "暂无 profile"
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontSection
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        horizontalAlignment: Text.AlignHCenter
                                        wrapMode: Text.WordWrap
                                        text: "可在任务页点击“提取本书术语”，或点击“保存当前术语表”生成题材/系列/本书 profile。"
                                        color: AppPalette.mutedText
                                        font.pixelSize: AppStyle.fontSmall
                                    }
                                }
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
        id: importCsvDialog
        title: "导入术语表 CSV"
        nameFilters: ["CSV (*.csv)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                page.gbridge.importCsv(p)
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
        id: exportCsvDialog
        title: "导出术语表 CSV"
        nameFilters: ["CSV (*.csv)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile && page.gbridge) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                if (!p.toLowerCase().endsWith(".csv")) p += ".csv"
                page.gbridge.exportCsv(p)
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
            spacing: AppStyle.spacingTight
            Label {
                Layout.fillWidth: true
                text: title
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontCaption
            }
            Label {
                Layout.fillWidth: true
                text: value !== undefined ? value.toString() : "0"
                color: parent.parent.toneColor
                font.pixelSize: AppStyle.fontMetric
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
            font.pixelSize: AppStyle.fontSmall
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
            font.pixelSize: AppStyle.fontBody
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
            font.pixelSize: AppStyle.fontSmall
            onActivated: function(index) {
                policyCell.commit(model[index])
            }
        }
    }
}
