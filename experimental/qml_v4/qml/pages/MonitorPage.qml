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
    property var tbridge: null

    property int statCompleted: 0
    property int statTotal: 0
    property int statTerms: 0
    property int statApiTotal: 0
    property int statFailCount: 0
    property real statSuccessRate: 0
    property int statSpeed: 0
    property int statCharSpeed: 0
    property int statTranslatedChars: 0
    property int statTokenTotal: 0
    property int statTotalChars: 0
    property string statElapsed: "--:--"
    property string statStatus: "就绪"
    property string proofreadStyleText: "等待自动识别"
    property string proofreadStyleReason: ""
    property int proofreadStyleConfidence: 0
    property string proofreadStyleMode: ""
    property int proofreadCount: 0
    property int proofreadMaxItems: 300
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    property real startTs: 0

    ListModel { id: proofreadModel }

    function isBusy() {
        return page.tbridge ? page.tbridge.busy : false
    }

    function safeProgress() {
        var value = page.tbridge ? page.tbridge.progressValue : 0
        if (!isFinite(value) || value < 0) return 0
        return Math.min(1, value)
    }

    function progressPercentText() {
        return Math.round(page.safeProgress() * 100) + "%"
    }

    function charProgressText() {
        var done = Math.max(0, page.statTranslatedChars)
        var total = Math.max(0, page.statTotalChars)
        return done.toLocaleString() + " / " + (total > 0 ? total.toLocaleString() : "--")
    }

    function remainingTimeText() {
        var total = Math.max(0, page.statTotalChars)
        var done = Math.max(0, page.statTranslatedChars)
        var remaining = Math.max(0, total - done)
        if (total <= 0) return "--"
        if (remaining <= 0 && page.safeProgress() >= 0.999) return "00:00"
        if (page.statCharSpeed <= 0) return page.isBusy() ? "计算中" : "--"
        return page.formatDuration(remaining / page.statCharSpeed)
    }

    function promptStyleMetaText() {
        if (page.proofreadStyleConfidence > 0) {
            var modeText = page.proofreadStyleMode === "manual" ? "手动指定" : "自动识别"
            return modeText + " · 置信度 " + page.proofreadStyleConfidence + "%"
        }
        return "开始翻译后显示自动识别结果"
    }

    function promptStyleReasonText() {
        return page.proofreadStyleReason || "作品类型和叙事口吻会同时影响初译 Prompt 与译后校对 Prompt。"
    }

    function appendProofreadDetail(original, draft, revised, reason, japaneseResidue, glossaryMismatch, changed) {
        page.proofreadCount += 1
        proofreadModel.append({
            "indexText": "#" + page.proofreadCount,
            "timeText": new Date().toLocaleTimeString(),
            "reason": reason || "-",
            "japaneseResidue": japaneseResidue ? "是" : "否",
            "glossaryMismatch": glossaryMismatch ? "是" : "否",
            "changed": changed ? "有变化" : "无变化",
            "changedHint": changed ? "校对模型已修改初译。" : "校对模型判断无需修改，保留初译。",
            "original": original || "",
            "draft": draft || "",
            "revised": revised || ""
        })
        if (proofreadModel.count > page.proofreadMaxItems) {
            proofreadModel.remove(0, proofreadModel.count - page.proofreadMaxItems)
        }
        Qt.callLater(function() {
            proofreadList.positionViewAtEnd()
        })
    }

    function clearProofreadDetails() {
        page.proofreadCount = 0
        proofreadModel.clear()
    }

    function clearRuntimeState(statusText) {
        page.finishElapsedTimer()
        page.statCompleted = 0
        page.statTotal = 0
        page.statTerms = 0
        page.statApiTotal = 0
        page.statFailCount = 0
        page.statSuccessRate = 0
        page.statSpeed = 0
        page.statCharSpeed = 0
        page.statTranslatedChars = 0
        page.statTokenTotal = 0
        page.statTotalChars = 0
        page.statElapsed = "--:--"
        page.statStatus = statusText || "已停止，已清空本次译文缓存"
        page.proofreadStyleText = "等待自动识别"
        page.proofreadStyleReason = ""
        page.proofreadStyleConfidence = 0
        page.proofreadStyleMode = ""
        rtSrc.text = ""
        rtDst.text = ""
        page.clearProofreadDetails()
    }

    function formatDuration(totalSeconds) {
        var seconds = Math.max(0, Math.floor(totalSeconds))
        var hours = Math.floor(seconds / 3600)
        var mins = Math.floor((seconds % 3600) / 60)
        var secs = seconds % 60
        if (hours > 0) {
            return hours + ":" + (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs
        }
        return (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs
    }

    function updateElapsed() {
        if (page.startTs <= 0) {
            page.statElapsed = "00:00"
            return
        }
        page.statElapsed = page.formatDuration(Date.now() / 1000 - page.startTs)
    }

    function startElapsedTimer() {
        page.startTs = Date.now() / 1000
        page.statElapsed = "00:00"
        if (!elapsedTimer.running) elapsedTimer.start()
    }

    function finishElapsedTimer() {
        if (page.startTs > 0) {
            page.updateElapsed()
            page.startTs = 0
        }
        if (elapsedTimer.running) elapsedTimer.stop()
    }

    Timer {
        id: elapsedTimer
        interval: 1000
        repeat: true
        onTriggered: page.updateElapsed()
    }

    Connections {
        target: page.tbridge
        enabled: true

        function onStatusChanged(msg) { page.statStatus = msg }

        function onProgressChanged(completed, total, total_chars) {
            page.statTotalChars = total_chars
        }

        function onStatUpdate(completed, total, terms, apiTotal, failCount, successRate, speed, charSpeed, translatedChars, tokenTotal) {
            page.statCompleted = completed
            page.statTotal = total
            page.statTerms = terms
            page.statApiTotal = apiTotal
            page.statFailCount = failCount
            page.statSuccessRate = successRate
            page.statSpeed = speed
            page.statCharSpeed = charSpeed
            page.statTranslatedChars = translatedChars
            page.statTokenTotal = tokenTotal
            if (page.startTs <= 0 && page.isBusy()) {
                page.startElapsedTimer()
            } else if (page.startTs > 0) {
                page.updateElapsed()
            }
        }

        function onItemTranslated(src, dst) {
            rtSrc.text = src
            rtDst.text = dst
        }

        function onProofreadDetail(original, draft, revised, reason, japaneseResidue, glossaryMismatch, changed) {
            page.appendProofreadDetail(original, draft, revised, reason, japaneseResidue, glossaryMismatch, changed)
        }

        function onProofreadStyleDetected(styleText, reason, confidence, mode) {
            page.proofreadStyleText = styleText || "通用小说 + 中性口吻"
            page.proofreadStyleReason = reason || ""
            page.proofreadStyleConfidence = confidence || 0
            page.proofreadStyleMode = mode || "auto"
        }

        function onRuntimeCleared() {
            page.clearRuntimeState("已停止，已清空本次译文缓存")
        }

        function onErrorDetail(msg) {
            diagText.text += msg + "\n"
        }

        function onFailed(msg) {
            page.statStatus = "失败: " + msg.substring(0, 100)
            page.finishElapsedTimer()
        }

        function onFinished(path) {
            if (path === "__STOPPED__") {
                page.clearRuntimeState("已停止，已清空本次译文缓存")
            } else if (path === "__CANCELLED__") {
                page.statStatus = "已取消"
            } else {
                page.statStatus = "完成: " + path
                if (page.tbridge) page.tbridge.playCompletionVoice()
            }
            page.finishElapsedTimer()
        }

        function onBusyChanged() {
            if (page.isBusy()) {
                page.startElapsedTimer()
            } else {
                page.finishElapsedTimer()
                page.statSpeed = 0
                page.statCharSpeed = 0
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: "状态监控"
                    color: AppPalette.textColor
                    font.family: page.titleFont
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "集中查看进度、速度、实时译文、校对记录和错误诊断。"
                    color: AppPalette.mutedText
                    font.pixelSize: 13
                }
            }
            Rectangle {
                Layout.preferredWidth: 112
                Layout.preferredHeight: 34
                radius: 17
                color: page.isBusy() ? AppPalette.accentSoft : AppPalette.cardAlt
                border.color: AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: page.isBusy() ? "运行中" : "空闲"
                    color: page.isBusy() ? AppPalette.accentColor : AppPalette.mutedText
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 238
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 20

                ColumnLayout {
                    Layout.preferredWidth: 210
                    Layout.fillHeight: true
                    spacing: 8

                    Label {
                        text: "翻译进度"
                        color: AppPalette.mutedText
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: page.progressPercentText()
                        color: AppPalette.accentColor
                        font.pixelSize: 46
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: page.isBusy() ? "正在处理文本块" : "等待任务或已结束"
                        color: AppPalette.mutedText
                        font.pixelSize: 12
                        elide: Text.ElideRight
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 1
                    Layout.fillHeight: true
                    color: AppPalette.lineColor
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 12

                    GridLayout {
                        Layout.fillWidth: true
                        columns: page.width > 900 ? 3 : 1
                        columnSpacing: 10
                        rowSpacing: 10

                        ProgressMetric { title: "已翻译 / 总字数"; value: page.charProgressText(); tone: "accent" }
                        ProgressMetric { title: "预计剩余"; value: page.remainingTimeText(); tone: "amber" }
                        ProgressMetric { title: "已耗时"; value: page.statElapsed }
                    }

                    ProgressBar {
                        Layout.fillWidth: true
                        value: page.safeProgress()
                        indeterminate: page.isBusy() && page.safeProgress() < 0.001
                        Behavior on value {
                            NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        text: "状态: " + page.statStatus
                        color: AppPalette.mutedText
                        elide: Text.ElideRight
                        font.pixelSize: 12
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 62
                        radius: AppPalette.radiusMedium
                        color: AppPalette.cardBg
                        border.color: AppPalette.lineColor

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: 12

                            Rectangle {
                                Layout.preferredWidth: 4
                                Layout.fillHeight: true
                                radius: 2
                                color: AppPalette.amberColor
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: 8
                                    Label {
                                        text: "Prompt 风格识别结果"
                                        color: AppPalette.mutedText
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: page.promptStyleMetaText()
                                        color: AppPalette.amberColor
                                        font.pixelSize: 11
                                        elide: Text.ElideRight
                                    }
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: page.proofreadStyleText
                                    color: AppPalette.textColor
                                    font.pixelSize: 15
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: page.promptStyleReasonText()
                                    color: AppPalette.mutedText
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                }
                            }
                        }
                    }
                }
            }
        }

        TabBar {
            id: statusTabs
            Layout.fillWidth: true
            background: Rectangle {
                radius: 18
                color: AppPalette.cardAlt
                border.color: AppPalette.lineColor
            }
            TabButton { text: "运行概览" }
            TabButton { text: "实时翻译" }
            TabButton { text: "校对详情" }
            TabButton { text: "错误诊断" }
        }

        SwipeView {
            id: statusSwipe
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: statusTabs.currentIndex
            clip: true

            Rectangle {
                color: AppPalette.cardBg
                radius: AppPalette.radiusLarge
                border.color: AppPalette.borderColor

                GridLayout {
                    anchors.fill: parent
                    anchors.margins: 18
                    columns: page.width > 1060 ? 5 : (page.width > 760 ? 3 : 2)
                    rowSpacing: 10
                    columnSpacing: 10

                    StatCard { title: "速度"; value: page.statSpeed > 0 ? page.statSpeed + "条/分" : (page.isBusy() ? "0条/分" : "--") }
                    StatCard { title: "字符速度"; value: page.statCharSpeed > 0 ? page.statCharSpeed + "字/秒" : (page.isBusy() ? "0字/秒" : "--"); tone: "accent" }
                    StatCard { title: "API 次数"; value: page.statApiTotal > 0 ? page.statApiTotal : "--" }
                    StatCard { title: "Token"; value: page.statTokenTotal > 0 ? page.statTokenTotal : "--" }
                    StatCard { title: "失败数"; value: page.statFailCount > 0 ? page.statFailCount : "0"; tone: page.statFailCount > 0 ? "error" : "" }
                    StatCard { title: "成功率"; value: page.isBusy() && page.statApiTotal === 0 ? "--" : (page.statApiTotal === 0 && page.statCompleted === 0 ? "--" : page.statSuccessRate.toFixed(1) + "%"); tone: "success" }
                    StatCard { title: "新术语"; value: page.statTerms; tone: "amber" }
                    StatCard { title: "文本块"; value: page.statCompleted + " / " + (page.statTotal > 0 ? page.statTotal : "--") }
                    StatCard { title: "Prompt风格"; value: page.proofreadStyleText; tone: "amber" }
                }
            }

            Rectangle {
                color: AppPalette.cardBg
                radius: AppPalette.radiusLarge
                border.color: AppPalette.borderColor

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    RealtimeTextPanel {
                        id: rtSrc
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        title: "原文"
                        textColor: AppPalette.textColor
                    }
                    RealtimeTextPanel {
                        id: rtDst
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        title: "译文"
                        textColor: AppPalette.accentColor
                    }
                }
            }

            Rectangle {
                color: AppPalette.cardBg
                radius: AppPalette.radiusLarge
                border.color: AppPalette.borderColor

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 12

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(86, proofreadHeaderTitle.implicitHeight + proofreadHeaderText.paintedHeight + 36)
                        Layout.minimumHeight: Layout.preferredHeight
                        radius: AppPalette.radiusMedium
                        color: AppPalette.surfaceRaised
                        border.color: AppPalette.lineColor

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 14
                            spacing: 12

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 3
                                Label {
                                    id: proofreadHeaderTitle
                                    text: "质检报告时间线"
                                    color: AppPalette.textColor
                                    font.pixelSize: 16
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    id: proofreadHeaderText
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    color: AppPalette.mutedText
                                    font.pixelSize: 12
                                    text: cfg && cfg.enableProofread
                                          ? (proofreadModel.count > 0
                                             ? "已记录 " + proofreadModel.count + " 条可疑译文。仅在检测到日文残留、术语不一致等问题时生成报告。"
                                             : "译后校对已启用。检测到可疑译文后，这里会生成逐条质检报告。")
                                          : "译后校对未启用。请到“设置”页勾选“启用译后校对”。"
                                }
                            }

                            Rectangle {
                                Layout.preferredWidth: 92
                                Layout.preferredHeight: 34
                                Layout.alignment: Qt.AlignVCenter
                                radius: 17
                                color: AppPalette.accentSoft
                                border.color: AppPalette.borderColor
                                Label {
                                    anchors.centerIn: parent
                                    text: proofreadModel.count + " 条"
                                    color: AppPalette.accentColor
                                    font.pixelSize: 12
                                    font.weight: Font.DemiBold
                                }
                            }
                        }
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Label {
                            anchors.centerIn: parent
                            visible: proofreadModel.count === 0
                            text: "暂无校对记录"
                            color: AppPalette.mutedText
                        }

                        ListView {
                            id: proofreadList
                            anchors.fill: parent
                            visible: proofreadModel.count > 0
                            clip: true
                            spacing: 10
                            model: proofreadModel
                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            delegate: Item {
                                id: timelineItem
                                width: proofreadList.width
                                height: reportCard.height + 14
                                opacity: 0
                                x: 18

                                Component.onCompleted: entryAnim.start()

                                ParallelAnimation {
                                    id: entryAnim
                                    NumberAnimation { target: timelineItem; property: "opacity"; to: 1; duration: 180; easing.type: Easing.OutCubic }
                                    NumberAnimation { target: timelineItem; property: "x"; to: 0; duration: 220; easing.type: Easing.OutCubic }
                                }

                                Rectangle {
                                    x: 18
                                    y: 0
                                    width: 2
                                    height: parent.height
                                    color: AppPalette.lineColor
                                    opacity: 0.9
                                }

                                Rectangle {
                                    x: 9
                                    y: 22
                                    width: 20
                                    height: 20
                                    radius: 10
                                    color: changed === "有变化" ? AppPalette.amberColor : AppPalette.accentColor
                                    border.color: AppPalette.cardBg
                                    border.width: 3
                                }

                                Rectangle {
                                    id: reportCard
                                    anchors.left: parent.left
                                    anchors.leftMargin: 44
                                    anchors.right: parent.right
                                    anchors.top: parent.top
                                    anchors.topMargin: 4
                                    height: reportColumn.implicitHeight + 24
                                    radius: AppPalette.radiusMedium
                                    color: AppPalette.surfaceRaised
                                    border.color: changed === "有变化" ? AppPalette.amberColor : AppPalette.lineColor
                                    border.width: changed === "有变化" ? 1 : 1

                                    ColumnLayout {
                                        id: reportColumn
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.top: parent.top
                                        anchors.margins: 12
                                        spacing: 10

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: 10

                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: 2
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: indexText + "  译后质检"
                                                    color: AppPalette.textColor
                                                    font.pixelSize: 14
                                                    font.weight: Font.DemiBold
                                                }
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: timeText + "  ·  " + reason
                                                    color: AppPalette.mutedText
                                                    font.pixelSize: 11
                                                    elide: Text.ElideRight
                                                }
                                            }

                                            IssueChip {
                                                title: changed
                                                tone: changed === "有变化" ? "amber" : "accent"
                                            }
                                        }

                                        Flow {
                                            Layout.fillWidth: true
                                            width: parent.width
                                            spacing: 8
                                            IssueChip { title: "日文残留: " + japaneseResidue; tone: japaneseResidue === "是" ? "error" : "neutral" }
                                            IssueChip { title: "术语不一致: " + glossaryMismatch; tone: glossaryMismatch === "是" ? "amber" : "neutral" }
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: changedHint
                                            wrapMode: Text.WordWrap
                                            color: changed === "有变化" ? AppPalette.amberColor : AppPalette.mutedText
                                            font.pixelSize: 12
                                        }

                                        ReportField {
                                            title: "原文"
                                            body: original
                                            tone: "normal"
                                        }
                                        ReportField {
                                            title: "初译"
                                            body: draft
                                            tone: "normal"
                                        }
                                        ReportField {
                                            title: "校对后译文"
                                            body: revised
                                            tone: "accent"
                                        }
                                    }
                                }
                            }
                        }
                    }

                    Button {
                        text: "清空校对详情"
                        enabled: proofreadModel.count > 0
                        onClicked: page.clearProofreadDetails()
                    }
                }
            }

            Rectangle {
                color: AppPalette.cardBg
                radius: AppPalette.radiusLarge
                border.color: AppPalette.borderColor

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: 10
                    TextArea {
                        id: diagText
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        readOnly: true
                        placeholderText: "暂无错误"
                        font.pixelSize: 12
                        color: AppPalette.textColor
                        background: Rectangle {
                            radius: AppPalette.radiusMedium
                            color: AppPalette.fieldBg
                            border.color: AppPalette.lineColor
                        }
                    }
                    Button { text: "导出诊断包"; onClicked: diagExportDialog.open() }
                }
            }
        }
    }

    component StatCard: Rectangle {
        property string title: ""
        property var value: ""
        property string tone: ""

        Layout.fillWidth: true
        Layout.minimumWidth: 132
        Layout.preferredHeight: 92
        radius: AppPalette.radiusMedium
        color: AppPalette.surfaceRaised
        border.color: AppPalette.lineColor

        readonly property color toneColor: tone === "accent"
                                           ? AppPalette.accentColor
                                           : tone === "amber"
                                             ? AppPalette.amberColor
                                             : tone === "success"
                                               ? AppPalette.successColor
                                               : tone === "error"
                                                 ? AppPalette.errorColor
                                                 : AppPalette.textColor

        Rectangle {
            width: 36
            height: 4
            radius: 2
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.topMargin: 12
            color: parent.toneColor
            opacity: 0.85
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            anchors.topMargin: 22
            spacing: 4
            Label {
                text: title
                color: AppPalette.mutedText
                font.pixelSize: 11
            }
            Label {
                text: value !== undefined ? value.toString() : "0"
                color: parent.parent.toneColor
                font.pixelSize: 18
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
    }

    component ProgressMetric: Rectangle {
        property string title: ""
        property string value: ""
        property string tone: ""

        Layout.fillWidth: true
        Layout.preferredHeight: 60
        radius: AppPalette.radiusMedium
        color: AppPalette.cardBg
        border.color: AppPalette.lineColor

        readonly property color toneColor: tone === "accent"
                                           ? AppPalette.accentColor
                                           : tone === "amber"
                                             ? AppPalette.amberColor
                                             : AppPalette.textColor

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 2
            Label {
                Layout.fillWidth: true
                text: title
                color: AppPalette.mutedText
                font.pixelSize: 11
                elide: Text.ElideRight
            }
            Label {
                Layout.fillWidth: true
                text: value
                color: parent.parent.toneColor
                font.pixelSize: 17
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
        }
    }

    component RealtimeTextPanel: Rectangle {
        id: realtimePanel
        property alias text: realtimeText.text
        property string title: ""
        property string placeholder: ""
        property color textColor: AppPalette.textColor

        radius: AppPalette.radiusMedium
        color: AppPalette.fieldBg
        border.color: AppPalette.lineColor
        clip: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 8

            Label {
                Layout.fillWidth: true
                text: realtimePanel.title
                color: AppPalette.mutedText
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            TextArea {
                id: realtimeText
                Layout.fillWidth: true
                Layout.fillHeight: true
                readOnly: true
                placeholderText: realtimePanel.placeholder
                font.pixelSize: 13
                wrapMode: Text.WordWrap
                color: realtimePanel.textColor
                padding: 10
                leftPadding: 10
                rightPadding: 10
                topPadding: 8
                bottomPadding: 8
                clip: true
                selectByMouse: true
                background: Rectangle {
                    radius: AppPalette.radiusSmall
                    color: AppPalette.cardBg
                    border.color: AppPalette.lineColor
                }
            }
        }
    }

    component IssueChip: Rectangle {
        property string title: ""
        property string tone: "neutral"

        width: Math.max(82, chipLabel.implicitWidth + 22)
        height: 28
        radius: 14
        color: tone === "error"
               ? (AppPalette.dark ? "#3a2420" : "#f6ded9")
               : tone === "amber"
                 ? (AppPalette.dark ? "#3b2d1c" : "#f2e4cf")
                 : tone === "accent"
                   ? AppPalette.accentSoft
                   : AppPalette.cardAlt
        border.color: tone === "error"
                      ? AppPalette.errorColor
                      : tone === "amber"
                        ? AppPalette.amberColor
                        : tone === "accent"
                          ? AppPalette.accentColor
                          : AppPalette.lineColor

        Label {
            id: chipLabel
            anchors.centerIn: parent
            text: title
            color: parent.border.color
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }
    }

    component ReportField: Rectangle {
        property string title: ""
        property string body: ""
        property string tone: "normal"

        Layout.fillWidth: true
        Layout.preferredHeight: reportText.paintedHeight + reportTitle.implicitHeight + 24
        Layout.minimumHeight: Layout.preferredHeight
        radius: AppPalette.radiusSmall
        color: AppPalette.fieldBg
        border.color: tone === "accent" ? AppPalette.accentColor : AppPalette.lineColor

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 5

            Label {
                id: reportTitle
                Layout.fillWidth: true
                text: title
                color: tone === "accent" ? AppPalette.accentColor : AppPalette.mutedText
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }
            Label {
                id: reportText
                Layout.fillWidth: true
                text: body && body !== "" ? body : "-"
                color: tone === "accent" ? AppPalette.accentColor : AppPalette.textColor
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }
        }
    }

    FileDialog {
        id: diagExportDialog
        title: "导出诊断包"
        nameFilters: ["ZIP 文件 (*.zip)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile && page.tbridge) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                if (!p.toLowerCase().endsWith(".zip")) p += ".zip"
                page.tbridge.exportDiagnostic(p)
            }
        }
    }
}
