import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import ".."

Page {
    id: page
    padding: AppStyle.pagePadding
    background: Item {}

    property var logBridge: null
    property bool paused: false
    property bool followTail: true
    property int maxLines: 900
    property int activeTab: 0
    property var requestRows: []
    property var selectedRequest: null
    readonly property var requestCategoryCodes: ["all", "failed", "timeout", "security", "format", "residue", "rate_limit", "ok"]
    readonly property bool compactRequestLayout: page.width < 1040
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    function reloadRecent(forceFollow) {
        if (!page.logBridge) {
            logText.text = "日志模块未加载"
            return
        }
        logText.text = page.logBridge.readRecent(page.maxLines)
        if (forceFollow || page.followTail) Qt.callLater(page.scrollToBottom)
    }

    function appendLine(line) {
        if (!line || page.paused || page.activeTab !== 0) return
        var nextText = logText.text ? (logText.text + "\n" + line) : line
        if (nextText.length > 260000) {
            nextText = "... 已截断较早日志，仅保留最新内容 ...\n" + nextText.slice(-220000)
        }
        logText.text = nextText
        if (page.followTail) Qt.callLater(page.scrollToBottom)
    }

    function scrollToBottom() {
        logText.cursorPosition = logText.text.length
    }

    function requestCategoryCode() {
        var index = requestCategory.currentIndex
        if (index < 0 || index >= page.requestCategoryCodes.length) return "all"
        return page.requestCategoryCodes[index]
    }

    function reloadRequestLogs() {
        if (!page.logBridge || !page.logBridge.readRequestLogs) {
            page.requestRows = []
            page.selectedRequest = null
            return
        }
        page.requestRows = page.logBridge.readRequestLogs(350, page.requestCategoryCode(), requestSearch.text || "")
        page.selectedRequest = page.requestRows.length > 0 ? page.requestRows[0] : null
    }

    function openRequestLogs() {
        page.activeTab = 1
        page.reloadRequestLogs()
    }

    function clearRequestLogs() {
        if (!page.logBridge || !page.logBridge.clearRequestLogs) return
        page.logBridge.clearRequestLogs()
        page.reloadRequestLogs()
    }

    function clearRecentLog() {
        if (!page.logBridge || !page.logBridge.clearCurrentLog) {
            logText.text = ""
            return
        }
        var result = page.logBridge.clearCurrentLog()
        logText.text = result && result.ok ? "" : (result && result.message ? result.message : "清空运行日志失败")
    }

    function formatRequest(row) {
        if (!row) return "请选择一条请求日志"
        return "时间: " + (row.ts || "-")
            + "\n分类: " + (row.category || "-")
            + "\n上下文: " + (row.context || "-")
            + "\nProvider: " + (row.provider || "-")
            + "\nModel: " + (row.model || "-")
            + "\nURL: " + (row.url || "-")
            + "\nHTTP: " + (row.status_code === undefined || row.status_code === null ? "-" : row.status_code)
            + "\n结果: " + (row.outcome || "-")
            + "\n耗时: " + (row.elapsed_ms || 0) + " ms"
            + "\n批量: " + (row.batch_size === undefined || row.batch_size === null ? "-" : row.batch_size)
            + "\nToken估算/实际: " + (row.token_total || 0)
            + "\n\nPrompt摘要:\n" + (row.prompt_summary || "-")
            + "\n\n原文/请求摘要:\n" + (row.source_summary || "-")
            + "\n\n响应摘要:\n" + (row.response_summary || "-")
            + "\n\n错误:\n" + (row.error || "-")
    }

    function openRequestDetail(row) {
        if (row) page.selectedRequest = row
        requestDetailDialog.open()
    }

    Component.onCompleted: {
        page.reloadRecent(true)
        page.reloadRequestLogs()
    }
    onVisibleChanged: if (visible) {
        if (page.activeTab === 0) page.reloadRecent(true)
        else page.reloadRequestLogs()
    }

    Connections {
        target: page.logBridge
        ignoreUnknownSignals: true

        function onEntryAppended(line) {
            if (page.visible) page.appendLine(line)
        }

        function onCurrentLogPathChanged() {
            if (page.visible && page.activeTab === 0) page.reloadRecent(true)
        }

        function onRequestLogChanged() {
            if (page.visible && page.activeTab === 1) page.reloadRequestLogs()
        }
    }

    Timer {
        interval: 2500
        running: page.visible && !page.paused && page.activeTab === 0
        repeat: true
        onTriggered: page.reloadRecent(false)
    }

    Timer {
        interval: 5000
        running: page.visible && page.activeTab === 1
        repeat: true
        onTriggered: page.reloadRequestLogs()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: AppStyle.spacingLarge

        ColumnLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingNarrow

            Label {
                text: "日志"
                color: AppPalette.textColor
                font.family: page.titleFont
                font.pixelSize: AppStyle.fontPageTitle
                font.weight: Font.DemiBold
            }

            Label {
                text: "运行日志用于看整体流程；请求日志用于定位 API 请求、模型响应、超时、安全拒绝和日文残留。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontBody
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: AppStyle.spacingSmall

            Button {
                text: "运行日志"
                highlighted: page.activeTab === 0
                onClicked: {
                    page.activeTab = 0
                    page.reloadRecent(true)
                }
            }

            Button {
                text: "请求日志"
                highlighted: page.activeTab === 1
                onClicked: {
                    page.activeTab = 1
                    page.reloadRequestLogs()
                }
            }

            Item { Layout.fillWidth: true }
        }

        Rectangle {
            visible: page.activeTab === 0
            Layout.fillWidth: true
            Layout.preferredHeight: 112
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingMedium

                    Label {
                        text: "当前日志"
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontBody
                        font.weight: Font.DemiBold
                    }

                    TextField {
                        Layout.fillWidth: true
                        readOnly: true
                        text: page.logBridge ? page.logBridge.currentLogPath : ""
                        selectByMouse: true
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontSmall
                        background: Rectangle {
                            radius: AppPalette.radiusMedium
                            color: AppPalette.fieldBg
                            border.color: AppPalette.lineColor
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingMedium

                    Button { text: "刷新"; onClicked: page.reloadRecent(true) }
                    Button { text: "清空日志"; onClicked: page.clearRecentLog() }
                    Button { text: "打开日志目录"; onClicked: if (page.logBridge) page.logBridge.openLogDirectory() }

                    Item { Layout.fillWidth: true }

                    CheckBox {
                        text: "自动跟随"
                        checked: page.followTail
                        onToggled: {
                            page.followTail = checked
                            if (checked) page.scrollToBottom()
                        }
                    }

                    CheckBox {
                        text: "暂停刷新"
                        checked: page.paused
                        onToggled: page.paused = checked
                    }
                }
            }
        }

        Rectangle {
            visible: page.activeTab === 1
            Layout.fillWidth: true
            Layout.preferredHeight: 116
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 16
                spacing: AppStyle.spacingMedium

                RowLayout {
                    Layout.fillWidth: true
                    spacing: AppStyle.spacingMedium

                    ComboBox {
                        id: requestCategory
                        Layout.preferredWidth: 148
                        model: ["全部", "失败", "超时", "安全拒绝", "格式错误", "日文残留", "限流", "成功"]
                        onActivated: page.reloadRequestLogs()
                    }

                    TextField {
                        id: requestSearch
                        Layout.fillWidth: true
                        placeholderText: "搜索原文、响应、错误、provider、model"
                        selectByMouse: true
                        onAccepted: page.reloadRequestLogs()
                    }

                    Button { text: "搜索"; onClicked: page.reloadRequestLogs() }
                    Button { text: "刷新"; onClicked: page.reloadRequestLogs() }
                    Button { text: "清空请求日志"; onClicked: page.clearRequestLogs() }
                    Button { text: "打开目录"; onClicked: if (page.logBridge) page.logBridge.openRequestLogDirectory() }
                }

                Label {
                    text: "仅记录诊断摘要并自动脱敏 API Key；默认保留最近 14 天、每天最多 2000 条。当前显示 " + page.requestRows.length + " 条。"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
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

            ScrollView {
                visible: page.activeTab === 0
                anchors.fill: parent
                anchors.margins: 14
                clip: true
                ScrollBar.horizontal.policy: ScrollBar.AsNeeded
                ScrollBar.vertical.policy: ScrollBar.AsNeeded

                TextArea {
                    id: logText
                    width: Math.max(parent.width, implicitWidth)
                    height: Math.max(parent.height, implicitHeight)
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.NoWrap
                    textFormat: TextEdit.PlainText
                    color: AppPalette.textColor
                    selectedTextColor: "white"
                    selectionColor: AppPalette.accentColor
                    font.family: "Consolas"
                    font.pixelSize: AppStyle.fontSmall
                    background: Rectangle {
                        color: AppPalette.fieldBg
                        radius: AppPalette.radiusMedium
                        border.color: AppPalette.lineColor
                    }
                }
            }

            GridLayout {
                visible: page.activeTab === 1
                anchors.fill: parent
                anchors.margins: 14
                columns: page.compactRequestLayout ? 1 : 2
                rowSpacing: AppStyle.spacingMedium
                columnSpacing: AppStyle.spacingMedium

                ListView {
                    id: requestList
                    Layout.fillWidth: page.compactRequestLayout
                    Layout.preferredWidth: page.compactRequestLayout ? parent.width : Math.min(520, parent.width * 0.48)
                    Layout.preferredHeight: page.compactRequestLayout ? Math.max(180, parent.height * 0.36) : -1
                    Layout.fillHeight: !page.compactRequestLayout
                    clip: true
                    spacing: AppStyle.spacingSmall
                    model: page.requestRows

                    delegate: Rectangle {
                        width: requestList.width
                        height: Math.max(96, requestSummary.implicitHeight + 28)
                        radius: AppPalette.radiusMedium
                        color: modelData === page.selectedRequest ? AppPalette.accentSoft : AppPalette.fieldBg
                        border.color: modelData === page.selectedRequest ? AppPalette.accentColor : AppPalette.lineColor

                        MouseArea {
                            anchors.fill: parent
                            onClicked: page.selectedRequest = modelData
                            onDoubleClicked: page.openRequestDetail(modelData)
                        }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: AppStyle.spacingCompact

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingSmall

                                Label {
                                    text: "[" + (modelData.category || "-") + "] " + (modelData.context || "-")
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontSmall
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                    Layout.fillWidth: true
                                }

                                Label {
                                    text: (modelData.elapsed_ms || 0) + " ms"
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontTiny
                                }
                            }

                            Label {
                                id: requestSummary
                                Layout.fillWidth: true
                                text: (modelData.ts || "-") + " | " + (modelData.provider || "-") + "/" + (modelData.model || "-")
                                      + " | HTTP " + (modelData.status_code === undefined || modelData.status_code === null ? "-" : modelData.status_code)
                                      + "\n" + ((modelData.error || modelData.source_summary || modelData.response_summary || "-"))
                                color: AppPalette.mutedText
                                font.pixelSize: AppStyle.fontTiny
                                wrapMode: Text.WordWrap
                                maximumLineCount: 3
                                elide: Text.ElideRight
                            }
                        }
                    }

                    Label {
                        anchors.centerIn: parent
                        visible: page.requestRows.length === 0
                        text: "暂无请求日志"
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontBody
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusMedium
                    color: AppPalette.fieldBg
                    border.color: AppPalette.lineColor

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 14
                        spacing: AppStyle.spacingMedium

                        Label {
                            Layout.fillWidth: true
                            text: page.selectedRequest
                                  ? "[" + (page.selectedRequest.category || "-") + "] " + (page.selectedRequest.context || "-")
                                  : "请选择一条请求日志"
                            color: AppPalette.textColor
                            font.pixelSize: AppStyle.fontBodyLarge
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }

                        GridLayout {
                            Layout.fillWidth: true
                            columns: page.compactRequestLayout ? 2 : 4
                            rowSpacing: AppStyle.spacingSmall
                            columnSpacing: AppStyle.spacingMedium

                            Label { text: "Provider"; color: AppPalette.mutedText; font.pixelSize: AppStyle.fontTiny }
                            Label {
                                Layout.fillWidth: true
                                text: page.selectedRequest ? ((page.selectedRequest.provider || "-") + " / " + (page.selectedRequest.model || "-")) : "-"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                                elide: Text.ElideRight
                            }

                            Label { text: "HTTP"; color: AppPalette.mutedText; font.pixelSize: AppStyle.fontTiny }
                            Label {
                                Layout.fillWidth: true
                                text: page.selectedRequest ? (page.selectedRequest.status_code === undefined || page.selectedRequest.status_code === null ? "-" : page.selectedRequest.status_code) : "-"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                            }

                            Label { text: "耗时"; color: AppPalette.mutedText; font.pixelSize: AppStyle.fontTiny }
                            Label {
                                Layout.fillWidth: true
                                text: page.selectedRequest ? ((page.selectedRequest.elapsed_ms || 0) + " ms") : "-"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                            }

                            Label { text: "Token"; color: AppPalette.mutedText; font.pixelSize: AppStyle.fontTiny }
                            Label {
                                Layout.fillWidth: true
                                text: page.selectedRequest ? (page.selectedRequest.token_total || 0) : "-"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                            }
                        }

                        ScrollView {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical.policy: ScrollBar.AsNeeded

                            Label {
                                width: parent.width
                                text: page.selectedRequest
                                      ? ("原文/请求摘要:\n" + (page.selectedRequest.source_summary || "-")
                                         + "\n\n响应摘要:\n" + (page.selectedRequest.response_summary || "-")
                                         + "\n\n错误:\n" + (page.selectedRequest.error || "-"))
                                      : "暂无详情"
                                color: AppPalette.textColor
                                font.pixelSize: AppStyle.fontSmall
                                wrapMode: Text.WordWrap
                            }
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            Button {
                                text: "查看完整详情"
                                highlighted: true
                                enabled: !!page.selectedRequest
                                onClicked: page.openRequestDetail(page.selectedRequest)
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: requestDetailDialog
        modal: true
        anchors.centerIn: parent
        width: Math.max(420, Math.min(page.width - 48, 980))
        height: Math.max(460, Math.min(page.height - 72, 780))
        title: page.selectedRequest ? ("请求日志详情 [" + (page.selectedRequest.category || "-") + "]") : "请求日志详情"
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: ColumnLayout {
            width: requestDetailDialog.width - 48
            height: requestDetailDialog.height - 96
            spacing: AppStyle.spacingMedium

            RowLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingSmall

                Label {
                    Layout.fillWidth: true
                    text: page.selectedRequest
                          ? ((page.selectedRequest.ts || "-") + "  ·  "
                             + (page.selectedRequest.provider || "-") + " / " + (page.selectedRequest.model || "-"))
                          : "未选择请求日志"
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontBody
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Button {
                    text: "关闭"
                    onClicked: requestDetailDialog.close()
                }
            }

            TextArea {
                Layout.fillWidth: true
                Layout.fillHeight: true
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                text: page.formatRequest(page.selectedRequest)
                color: AppPalette.textColor
                selectedTextColor: "white"
                selectionColor: AppPalette.accentColor
                font.family: "Consolas"
                font.pixelSize: AppStyle.fontSmall
                background: Rectangle {
                    color: AppPalette.fieldBg
                    radius: AppPalette.radiusMedium
                    border.color: AppPalette.lineColor
                }
            }
        }
    }
}
