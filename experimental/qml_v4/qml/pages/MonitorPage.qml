import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."
import "../components"

Page {
    id: page
    padding: AppStyle.pagePadding
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
    property int statDynamicLimitEvents: 0
    property int statRateLimitEvents: 0
    property int statDynamicWorkers: 0
    property int statDynamicBatchSize: 0
    property int statProofreadBatchRequests: 0
    property int statProofreadBatchSuccess: 0
    property int statProofreadSuspicious: 0
    property int statProofreadFixed: 0
    property int statQualityRetranslate: 0
    property int statJapaneseResidueRemaining: 0
    property int statTotalChars: 0
    property string statElapsed: "--:--"
    property string statStatus: "就绪"
    property string proofreadStyleText: "等待自动识别"
    property string proofreadStyleReason: ""
    property int proofreadStyleConfidence: 0
    property string proofreadStyleMode: ""
    property int proofreadCount: 0
    property int proofreadMaxItems: 300
    property bool qualityReportAvailable: false
    property string qualityReportStatus: "等待完成"
    property string qualityReportSummary: "翻译完成后自动生成本次质量自检报告。"
    property string qualityReportMetrics: ""
    property string qualityReportWarnings: ""
    property string qualityReportSuggestions: ""
    property string qualityReportGeneratedAt: ""
    property string diagnosticsText: ""
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    property real startTs: 0

    signal requestManualEdit(string original, string translation)

    property string detailIndexText: ""
    property string detailTimeText: ""
    property string detailReason: ""
    property string detailJapaneseResidue: ""
    property string detailGlossaryMismatch: ""
    property string detailChanged: ""
    property string detailChangedHint: ""
    property string detailOriginal: ""
    property string detailDraft: ""
    property string detailRevised: ""
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

    function openProofreadDetail(indexText, timeText, reason, japaneseResidue, glossaryMismatch, changed, changedHint, original, draft, revised) {
        page.detailIndexText = indexText || ""
        page.detailTimeText = timeText || ""
        page.detailReason = reason || "-"
        page.detailJapaneseResidue = japaneseResidue || "\u5426"
        page.detailGlossaryMismatch = glossaryMismatch || "\u5426"
        page.detailChanged = changed || ""
        page.detailChangedHint = changedHint || ""
        page.detailOriginal = original || ""
        page.detailDraft = draft || ""
        page.detailRevised = revised || ""
        proofreadDetailDialog.open()
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

    function clearRunStats() {
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
        page.statDynamicLimitEvents = 0
        page.statRateLimitEvents = 0
        page.statDynamicWorkers = 0
        page.statDynamicBatchSize = 0
        page.statProofreadBatchRequests = 0
        page.statProofreadBatchSuccess = 0
        page.statProofreadSuspicious = 0
        page.statProofreadFixed = 0
        page.statQualityRetranslate = 0
        page.statJapaneseResidueRemaining = 0
        page.statTotalChars = 0
        page.clearQualityReport()
    }

    function clearQualityReport() {
        page.qualityReportAvailable = false
        page.qualityReportStatus = "等待完成"
        page.qualityReportSummary = "翻译完成后自动生成本次质量自检报告。"
        page.qualityReportMetrics = ""
        page.qualityReportWarnings = ""
        page.qualityReportSuggestions = ""
        page.qualityReportGeneratedAt = ""
    }

    function applyQualityReport(report) {
        report = report || ({})
        page.qualityReportAvailable = true
        page.qualityReportStatus = report.status || "已生成"
        page.qualityReportSummary = report.summary || "质量自检报告已生成。"
        page.qualityReportMetrics = report.metricsText || ""
        page.qualityReportWarnings = report.warningsText || "未发现需要阻塞保存的问题。"
        page.qualityReportSuggestions = report.suggestionsText || ""
        page.qualityReportGeneratedAt = report.generatedAt || ""
    }

    function clearRuntimeState(statusText) {
        page.finishElapsedTimer()
        page.clearRunStats()
        page.statElapsed = "--:--"
        page.statStatus = statusText || "已停止，已清空本次译文缓存"
        page.proofreadStyleText = "等待自动识别"
        page.proofreadStyleReason = ""
        page.proofreadStyleConfidence = 0
        page.proofreadStyleMode = ""
        page.diagnosticsText = ""
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

        function onQualityStatUpdate(dynamicLimitEvents, rateLimitEvents, dynamicWorkers, dynamicBatchSize, proofreadBatchRequests, proofreadBatchSuccess, proofreadSuspicious, proofreadFixed, qualityRetranslate, japaneseResidueRemaining) {
            page.statDynamicLimitEvents = dynamicLimitEvents
            page.statRateLimitEvents = rateLimitEvents
            page.statDynamicWorkers = dynamicWorkers
            page.statDynamicBatchSize = dynamicBatchSize
            page.statProofreadBatchRequests = proofreadBatchRequests
            page.statProofreadBatchSuccess = proofreadBatchSuccess
            page.statProofreadSuspicious = proofreadSuspicious
            page.statProofreadFixed = proofreadFixed
            page.statQualityRetranslate = qualityRetranslate
            page.statJapaneseResidueRemaining = japaneseResidueRemaining
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

        function onQualityReportReady(report) {
            page.applyQualityReport(report)
        }

        function onRuntimeCleared() {
            page.clearRuntimeState("已停止，已清空本次译文缓存")
        }

        function onErrorDetail(msg) {
            page.diagnosticsText += msg + "\n"
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
                page.clearRunStats()
                page.clearProofreadDetails()
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
        spacing: AppStyle.spacingXXLarge

        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: AppStyle.spacingTight
                Label {
                    text: "状态监控"
                    color: AppPalette.textColor
                    font.family: page.titleFont
                    font.pixelSize: AppStyle.fontPageTitle
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "集中查看进度、速度、实时译文、校对记录和错误诊断。"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontBody
                }
            }
            Rectangle {
                Layout.preferredWidth: 112
                Layout.preferredHeight: AppStyle.buttonHeightSmall
                radius: 17
                color: page.isBusy() ? AppStyle.statusAccentBg : AppStyle.statusNeutralBg
                border.color: AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: page.isBusy() ? "运行中" : "空闲"
                    color: page.isBusy() ? AppPalette.accentColor : AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    font.weight: Font.DemiBold
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 268
            radius: AppPalette.radiusLarge
            color: AppPalette.surfaceRaised
            border.color: AppPalette.borderColor

            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: AppStyle.spacingHuge

                ColumnLayout {
                    Layout.preferredWidth: 210
                    Layout.fillHeight: true
                    spacing: AppStyle.spacingSmall

                    Label {
                        text: "翻译进度"
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
                        font.weight: Font.DemiBold
                    }
                    Label {
                        text: page.progressPercentText()
                        color: AppPalette.accentColor
                        font.pixelSize: AppStyle.fontHero
                        font.weight: Font.DemiBold
                    }
                    Label {
                        Layout.fillWidth: true
                        text: page.isBusy() ? "正在处理文本块" : "等待任务或已结束"
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
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
                    spacing: AppStyle.spacingMedium

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
                        font.pixelSize: AppStyle.fontSmall
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 90
                        radius: AppPalette.radiusMedium
                        color: AppPalette.cardBg
                        border.color: AppPalette.lineColor
                        clip: true

                        RowLayout {
                            anchors.fill: parent
                            anchors.margins: 12
                            spacing: AppStyle.spacingLarge

                            Rectangle {
                                Layout.preferredWidth: 4
                                Layout.fillHeight: true
                                radius: 2
                                color: AppPalette.amberColor
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                spacing: AppStyle.spacingNarrow

                                RowLayout {
                                    Layout.fillWidth: true
                                    spacing: AppStyle.spacingSmall
                                    Label {
                                        text: "Prompt 风格识别结果"
                                        color: AppPalette.mutedText
                                        font.pixelSize: AppStyle.fontCaption
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: page.promptStyleMetaText()
                                        color: AppPalette.amberColor
                                        font.pixelSize: AppStyle.fontCaption
                                        elide: Text.ElideRight
                                    }
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: page.proofreadStyleText
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontBodyXLarge
                                    font.weight: Font.DemiBold
                                    elide: Text.ElideRight
                                }

                                Label {
                                    Layout.fillWidth: true
                                    text: page.promptStyleReasonText()
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontCaption
                                    wrapMode: Text.WordWrap
                                    maximumLineCount: 2
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
            TabButton { text: "质量自检" }
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

                ScrollView {
                    id: overviewScroll
                    anchors.fill: parent
                    anchors.margins: 12
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                    ColumnLayout {
                        id: overviewGrid
                        width: overviewScroll.availableWidth
                        spacing: AppStyle.spacingLarge

                        Item {
                            id: overviewCards
                            Layout.fillWidth: true
                            Layout.preferredWidth: overviewGrid.width
                            Layout.minimumWidth: overviewGrid.width
                            Layout.preferredHeight: implicitHeight
                            implicitHeight: rowCount * cardHeight + Math.max(0, rowCount - 1) * rowGap

                            readonly property int cardCount: 12
                            readonly property real layoutWidth: Math.max(0, overviewGrid.width)
                            readonly property int cardsPerRow: layoutWidth > 980 ? 5 : (layoutWidth > 760 ? 4 : (layoutWidth > 520 ? 3 : (layoutWidth > 300 ? 2 : 1)))
                            readonly property int rowCount: Math.ceil(cardCount / cardsPerRow)
                            readonly property real columnGap: AppStyle.spacingLarge
                            readonly property real rowGap: AppStyle.spacingLarge
                            readonly property real itemWidth: Math.max(132, Math.floor((layoutWidth - columnGap * (cardsPerRow - 1)) / cardsPerRow))
                            readonly property real cardHeight: page.width > 760 ? 76 : 70

                            function cardX(index) { return (index % cardsPerRow) * (itemWidth + columnGap) }
                            function cardY(index) { return Math.floor(index / cardsPerRow) * (cardHeight + rowGap) }

                            StatCard { property int cardIndex: 0; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "速度"; value: page.statSpeed > 0 ? page.statSpeed + "条/分" : (page.isBusy() ? "0条/分" : "--") }
                            StatCard { property int cardIndex: 1; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "字符速度"; value: page.statCharSpeed > 0 ? page.statCharSpeed + "字/秒" : (page.isBusy() ? "0字/秒" : "--"); tone: "accent" }
                            StatCard { property int cardIndex: 2; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "API 次数"; value: page.statApiTotal > 0 ? page.statApiTotal : "--" }
                            StatCard { property int cardIndex: 3; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "Token"; value: page.statTokenTotal > 0 ? page.statTokenTotal : "--" }
                            StatCard { property int cardIndex: 4; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "失败数"; value: page.statFailCount > 0 ? page.statFailCount : "0"; tone: page.statFailCount > 0 ? "error" : "" }
                            StatCard { property int cardIndex: 5; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "成功率"; value: page.isBusy() && page.statApiTotal === 0 ? "--" : (page.statApiTotal === 0 && page.statCompleted === 0 ? "--" : page.statSuccessRate.toFixed(1) + "%"); tone: "success" }
                            StatCard { property int cardIndex: 6; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "新术语"; value: page.statTerms; tone: "amber" }
                            StatCard { property int cardIndex: 7; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "文本块"; value: page.statCompleted + " / " + (page.statTotal > 0 ? page.statTotal : "--") }
                            StatCard { property int cardIndex: 8; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "限流事件"; value: page.statDynamicLimitEvents > 0 ? page.statDynamicLimitEvents : "0"; tone: page.statDynamicLimitEvents > 0 ? "error" : "" }
                            StatCard { property int cardIndex: 9; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "运行并发"; value: page.statDynamicWorkers > 0 ? page.statDynamicWorkers : "--"; tone: page.statRateLimitEvents > 0 ? "amber" : "" }
                            StatCard { property int cardIndex: 10; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "运行批量"; value: page.statDynamicBatchSize > 0 ? page.statDynamicBatchSize : "--"; tone: page.statRateLimitEvents > 0 ? "amber" : "" }
                            StatCard { property int cardIndex: 11; x: overviewCards.cardX(cardIndex); y: overviewCards.cardY(cardIndex); viewportWidth: page.width; cardWidth: overviewCards.itemWidth; title: "批量校对"; value: page.statProofreadBatchRequests > 0 ? (page.statProofreadBatchSuccess + " / " + page.statProofreadBatchRequests) : "--"; tone: "accent" }
                        }
                    }
                }
            }

            Rectangle {
                color: AppPalette.cardBg
                radius: AppPalette.radiusLarge
                border.color: AppPalette.borderColor

                ScrollView {
                    anchors.fill: parent
                    anchors.margins: 16
                    clip: true
                    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                    ScrollBar.vertical.policy: ScrollBar.AsNeeded

                    ColumnLayout {
                        width: parent.availableWidth
                        spacing: AppStyle.spacingLarge

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(96, qualitySummaryColumn.implicitHeight + 28)
                            radius: AppPalette.radiusMedium
                            color: page.qualityReportAvailable
                                   ? (page.qualityReportStatus === "通过" ? AppStyle.statusAccentBg : AppStyle.statusWarningBg)
                                   : AppStyle.statusNeutralBg
                            border.color: page.qualityReportStatus === "通过" ? AppPalette.accentColor : (page.qualityReportAvailable ? AppPalette.amberColor : AppPalette.lineColor)

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: AppStyle.spacingLarge

                                Rectangle {
                                    Layout.preferredWidth: 4
                                    Layout.fillHeight: true
                                    radius: 2
                                    color: page.qualityReportStatus === "通过" ? AppPalette.accentColor : AppPalette.amberColor
                                }

                                ColumnLayout {
                                    id: qualitySummaryColumn
                                    Layout.fillWidth: true
                                    spacing: AppStyle.spacingChip

                                    Label {
                                        text: "本次质量自检"
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontSection
                                        font.weight: Font.DemiBold
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: page.qualityReportSummary
                                        color: AppPalette.textColor
                                        wrapMode: Text.WordWrap
                                        font.pixelSize: AppStyle.fontBody
                                    }
                                    Label {
                                        Layout.fillWidth: true
                                        text: page.qualityReportGeneratedAt ? ("生成时间：" + page.qualityReportGeneratedAt) : "等待翻译完成后生成"
                                        color: AppPalette.mutedText
                                        font.pixelSize: AppStyle.fontCaption
                                    }
                                }

                                IssueChip {
                                    title: page.qualityReportStatus
                                    tone: page.qualityReportStatus === "通过" ? "accent" : (page.qualityReportAvailable ? "amber" : "neutral")
                                }
                            }
                        }

                        ReportField {
                            title: "关键指标"
                            body: page.qualityReportMetrics
                            tone: "normal"
                        }
                        ReportField {
                            title: "提醒"
                            body: page.qualityReportWarnings
                            tone: page.qualityReportStatus === "通过" ? "normal" : "accent"
                        }
                        ReportField {
                            title: "建议"
                            body: page.qualityReportSuggestions
                            tone: "accent"
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingMedium

                            Button {
                                text: "查看完整报告"
                                highlighted: true
                                enabled: page.qualityReportAvailable
                                onClicked: qualityReportDialog.open()
                            }

                            Item { Layout.fillWidth: true }
                        }
                    }
                }
            }

            Rectangle {
                color: AppPalette.cardBg
                radius: AppPalette.radiusLarge
                border.color: AppPalette.borderColor

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 16
                    spacing: AppStyle.spacingLarge

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
                    spacing: AppStyle.spacingLarge

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
                            spacing: AppStyle.spacingLarge

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingNarrow
                                Label {
                                    id: proofreadHeaderTitle
                                    text: "质检报告时间线"
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontSubSection
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    id: proofreadHeaderText
                                    Layout.fillWidth: true
                                    wrapMode: Text.WordWrap
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontSmall
                                    text: cfg && cfg.enableProofread
                                          ? (proofreadModel.count > 0
                                             ? "已记录 " + proofreadModel.count + " 条可疑译文。仅在检测到日文残留、术语不一致等问题时生成报告。"
                                             : "译后校对已启用。检测到可疑译文后，这里会生成逐条质检报告。")
                                          : "译后校对未启用。请到“设置”页勾选“启用译后校对”。"
                                }
                            }

                            Rectangle {
                                Layout.preferredWidth: 92
                                Layout.preferredHeight: AppStyle.buttonHeightSmall
                                Layout.alignment: Qt.AlignVCenter
                                radius: 17
                                color: AppPalette.accentSoft
                                border.color: AppPalette.borderColor
                                Label {
                                    anchors.centerIn: parent
                                    text: proofreadModel.count + " 条"
                                    color: AppPalette.accentColor
                                    font.pixelSize: AppStyle.fontSmall
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
                            spacing: AppStyle.spacingMedium
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
                                        spacing: AppStyle.spacingMedium

                                        RowLayout {
                                            Layout.fillWidth: true
                                            spacing: AppStyle.spacingMedium

                                            ColumnLayout {
                                                Layout.fillWidth: true
                                                spacing: AppStyle.spacingTight
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: indexText + "  译后质检"
                                                    color: AppPalette.textColor
                                                    font.pixelSize: AppStyle.fontBodyLarge
                                                    font.weight: Font.DemiBold
                                                }
                                                Label {
                                                    Layout.fillWidth: true
                                                    text: timeText + "  ·  " + reason
                                                    color: AppPalette.mutedText
                                                    font.pixelSize: AppStyle.fontCaption
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
                                            spacing: AppStyle.spacingSmall
                                            IssueChip { title: "日文残留: " + japaneseResidue; tone: japaneseResidue === "是" ? "error" : "neutral" }
                                            IssueChip { title: "术语不一致: " + glossaryMismatch; tone: glossaryMismatch === "是" ? "amber" : "neutral" }
                                        }

                                        Label {
                                            Layout.fillWidth: true
                                            text: changedHint
                                            wrapMode: Text.WordWrap
                                            color: changed === "有变化" ? AppPalette.amberColor : AppPalette.mutedText
                                            font.pixelSize: AppStyle.fontSmall
                                        }

                                        ReportField {
                                            title: "\u539f\u6587"
                                            body: original
                                            tone: "normal"
                                            maxLines: 2
                                        }
                                        ReportField {
                                            title: "\u521d\u8bd1"
                                            body: draft
                                            tone: "normal"
                                            maxLines: 2
                                        }
                                        ReportField {
                                            title: "\u6821\u5bf9\u540e\u8bd1\u6587"
                                            body: revised
                                            tone: "accent"
                                            maxLines: 2
                                        }

                                        RowLayout {
                                            Layout.alignment: Qt.AlignRight
                                            spacing: AppStyle.spacingSmall
                                            Button {
                                                text: "\u67e5\u770b\u5b8c\u6574\u8be6\u60c5"
                                                onClicked: page.openProofreadDetail(indexText, timeText, reason, japaneseResidue, glossaryMismatch, changed, changedHint, original, draft, revised)
                                            }
                                            Button {
                                                text: "\u4eba\u5de5\u4fee\u6539\u6b64\u6761"
                                                enabled: original && original !== ""
                                                onClicked: page.requestManualEdit(original, (revised && revised !== "") ? revised : draft)
                                            }
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
                    spacing: AppStyle.spacingMedium

                    Label {
                        text: "错误诊断"
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontSection
                        font.weight: Font.DemiBold
                    }

                    Label {
                        Layout.fillWidth: true
                        text: page.diagnosticsText ? ("已记录 " + page.diagnosticsText.split(/\n+/).filter(function(line) { return line && line.trim(); }).length + " 条错误诊断。") : "暂无错误"
                        color: AppPalette.mutedText
                        font.pixelSize: AppStyle.fontSmall
                        wrapMode: Text.WordWrap
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: AppStyle.spacingMedium

                        Button {
                            text: "查看完整错误"
                            highlighted: true
                            enabled: page.diagnosticsText !== ""
                            onClicked: diagnosticsDialog.open()
                        }

                        Button { text: "导出诊断包"; onClicked: diagExportDialog.open() }
                    }
                }
            }
        }
    }

    ProofreadDetailDialog {
        id: proofreadDetailDialog
        host: page
        anchors.centerIn: parent
    }

    Dialog {
        id: qualityReportDialog
        modal: true
        anchors.centerIn: parent
        width: Math.max(420, Math.min(page.width - 48, 980))
        height: Math.max(460, Math.min(page.height - 72, 760))
        title: "质量自检详情"
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: ScrollView {
            width: qualityReportDialog.width
            height: qualityReportDialog.height
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: Math.max(0, qualityReportDialog.width - 32)
                spacing: AppStyle.spacingLarge

                Label {
                    Layout.fillWidth: true
                    text: page.qualityReportSummary
                    color: AppPalette.textColor
                    font.pixelSize: AppStyle.fontBodyLarge
                    font.weight: Font.DemiBold
                    wrapMode: Text.WordWrap
                }

                Label {
                    Layout.fillWidth: true
                    text: page.qualityReportGeneratedAt ? ("生成时间：" + page.qualityReportGeneratedAt) : "等待翻译完成后生成"
                    color: AppPalette.mutedText
                    font.pixelSize: AppStyle.fontSmall
                    wrapMode: Text.WordWrap
                }

                ReportField {
                    title: "关键指标"
                    body: page.qualityReportMetrics
                    tone: "normal"
                }
                ReportField {
                    title: "提醒"
                    body: page.qualityReportWarnings
                    tone: page.qualityReportStatus === "通过" ? "normal" : "accent"
                }
                ReportField {
                    title: "建议"
                    body: page.qualityReportSuggestions
                    tone: "accent"
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    Button { text: "关闭"; onClicked: qualityReportDialog.close() }
                }
            }
        }
    }

    Dialog {
        id: diagnosticsDialog
        modal: true
        anchors.centerIn: parent
        width: Math.max(420, Math.min(page.width - 48, 980))
        height: Math.max(460, Math.min(page.height - 72, 760))
        title: "错误诊断详情"
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        contentItem: ColumnLayout {
            width: diagnosticsDialog.width - 48
            height: diagnosticsDialog.height - 96
            spacing: AppStyle.spacingMedium

            Label {
                Layout.fillWidth: true
                text: "仅显示运行中的错误详情，不影响导出诊断包。"
                color: AppPalette.mutedText
                font.pixelSize: AppStyle.fontSmall
                wrapMode: Text.WordWrap
            }

            TextArea {
                Layout.fillWidth: true
                Layout.fillHeight: true
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                text: page.diagnosticsText || "暂无错误"
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

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                Button { text: "关闭"; onClicked: diagnosticsDialog.close() }
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
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                if (!p.toLowerCase().endsWith(".zip")) p += ".zip"
                page.tbridge.exportDiagnostic(p)
            }
        }
    }
}

