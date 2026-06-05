import QtQuick
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs

Page {
    id: page
    padding: 24
    property var cfg: null
    property var tbridge: null  // kept for progressValue binding

    // Internal stats
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
    property string proofreadText: ""

    // Timer for elapsed time
    property real startTs: 0
    Timer {
        id: elapsedTimer
        interval: 1000; running: tbridge ? (TranslateBridge ? TranslateBridge.busy : false) : false; repeat: true
        onTriggered: {
            var elapsed = Date.now() / 1000 - page.startTs
            var mins = Math.floor(elapsed / 60)
            var secs = Math.floor(elapsed % 60)
            page.statElapsed = (mins < 10 ? "0" : "") + mins + ":" + (secs < 10 ? "0" : "") + secs
        }
    }

    Connections {
        target: TranslateBridge
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
            if (!elapsedTimer.running) {
                page.startTs = Date.now() / 1000
                page.statElapsed = "00:00"
                elapsedTimer.start()
            }
        }
        function onItemTranslated(src, dst) {
            rtSrc.text = src
            rtDst.text = dst
        }
        function onProofreadDetail(original, before, after) {
            page.proofreadText += "[" + new Date().toLocaleTimeString() + "]\n原文: " + original + "\n初译: " + before + "\n校对: " + after + "\n\n"
        }
        function onErrorDetail(msg) {
            diagText.text += msg + "\n"
        }
        function onFailed(msg) {
            page.statStatus = "失敗: " + msg.substring(0, 100)
            elapsedTimer.stop()
        }
        function onFinished(path) {
            if (path === "__CANCELLED__") { page.statStatus = "已取消" } else { page.statStatus = "完成: " + path; if (TranslateBridge) TranslateBridge.playCompletionVoice() }
            elapsedTimer.stop()
        }
        function onBusyChanged() {
            if (!(TranslateBridge ? TranslateBridge.busy : false)) {
                elapsedTimer.stop()
                page.statElapsed = "--:--"
                page.statSpeed = 0
                page.statCharSpeed = 0
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 16

        Label { text: "状态监控"; font.pixelSize: 24; font.weight: Font.DemiBold }

        TabBar {
            id: statusTabs; Layout.fillWidth: true
            TabButton { text: "运行概览" }
            TabButton { text: "实时翻译" }
            TabButton { text: "校对详情" }
            TabButton { text: "错误诊断" }
        }

        SwipeView {
            id: statusSwipe
            Layout.fillWidth: true; Layout.fillHeight: true
            currentIndex: statusTabs.currentIndex; clip: true

            // Overview
            Pane {
                ColumnLayout {
                    anchors.fill: parent; spacing: 12
                    ProgressBar {
                        Layout.fillWidth: true
                        value: tbridge ? TranslateBridge.progressValue : 0
                        indeterminate: tbridge ? (TranslateBridge ? TranslateBridge.busy : false) && TranslateBridge.progressValue < 0.001 : false
                    }
                    Label {
                        text: Math.round((tbridge ? TranslateBridge.progressValue : 0) * 100) + "%"
                        font.pixelSize: 18; font.weight: Font.DemiBold
                    }
                    Label { text: "状态: " + page.statStatus; color: (Material.theme === Material.Dark ? "#999999" : "#666666") }

                    GridLayout {
                        columns: 5; rowSpacing: 8; columnSpacing: 8; Layout.fillWidth: true
                        StatCard { title: "已完成字符"; value: page.statTranslatedChars.toLocaleString() }
                        StatCard { title: "总字符数"; value: page.statTotalChars > 0 ? page.statTotalChars.toLocaleString() : "--" }
                        StatCard { title: "新术语"; value: page.statTerms }
                        StatCard { title: "耗时"; value: page.statElapsed }
                        StatCard { title: "速度"; value: page.statSpeed > 0 ? page.statSpeed + "条/分" : ((TranslateBridge ? TranslateBridge.busy : false) ? "0条/分" : "--") }
                        StatCard { title: "字符速度"; value: page.statCharSpeed > 0 ? page.statCharSpeed + "字/秒" : ((TranslateBridge ? TranslateBridge.busy : false) ? "0字/秒" : "--") }
                        StatCard { title: "API 次数"; value: page.statApiTotal > 0 ? page.statApiTotal : "--" }
                        StatCard { title: "Token"; value: page.statTokenTotal > 0 ? page.statTokenTotal : "--" }
                        StatCard { title: "成功率"; value: (TranslateBridge ? TranslateBridge.busy : false) && page.statApiTotal === 0 ? "--" : (page.statApiTotal === 0 && page.statCompleted === 0 ? "--" : page.statSuccessRate.toFixed(1) + "%") }
                        StatCard { title: "失败数"; value: page.statFailCount > 0 ? page.statFailCount : "0" }
                    }
                }
            }

            // Realtime
            Pane {
                RowLayout {
                    anchors.fill: parent; spacing: 8
                    TextArea {
                        id: rtSrc
                        Layout.fillWidth: true; Layout.fillHeight: true; readOnly: true
                        placeholderText: "原文..."; font.pixelSize: 12
                        wrapMode: Text.WordWrap
                    }
                    TextArea {
                        id: rtDst
                        Layout.fillWidth: true; Layout.fillHeight: true; readOnly: true
                        placeholderText: "译文..."; font.pixelSize: 12
                        wrapMode: Text.WordWrap; color: Material.accent
                    }
                }
            }

            // Proofread
            Pane {
                ColumnLayout {
                    anchors.fill: parent
                    TextArea {
                        Layout.fillWidth: true; Layout.fillHeight: true; readOnly: true
                        placeholderText: "校对详情将在此显示..."
                        text: page.proofreadText; font.pixelSize: 12
                    }
                    Button {
                        text: "清空校对详情"
                        onClicked: page.proofreadText = ""
                    }
                }
            }

            // Diagnostic
            Pane {
                ColumnLayout {
                    anchors.fill: parent
                    TextArea {
                        id: diagText
                        Layout.fillWidth: true; Layout.fillHeight: true; readOnly: true
                        placeholderText: "暂无错误"; font.pixelSize: 12
                    }
                    Button { text: "导出诊断包"; onClicked: diagExportDialog.open() }
                }
            }
        }
    }

    component StatCard: Pane {
        property string title: ""
        property var value: ""
        Layout.preferredWidth: 140; Material.elevation: 1; padding: 12
        contentItem: ColumnLayout {
            spacing: 4
            Label { text: title; font.pixelSize: 11; color: (Material.theme === Material.Dark ? "#999999" : "#666666") }
            Label { text: value !== undefined ? value.toString() : "0"; font.pixelSize: 16; font.weight: Font.DemiBold }
        }
    }

    FileDialog {
        id: diagExportDialog
        title: "导出诊断包"
        nameFilters: ["ZIP 文件 (*.zip)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile && TranslateBridge) {
                var p = selectedFile.toString()
                if (p.startsWith("file:///")) p = p.substring(8)
                else if (p.startsWith("file://")) p = p.substring(7)
                p = decodeURIComponent(p)
                if (!p.toLowerCase().endsWith(".zip")) p += ".zip"
                TranslateBridge.exportDiagnostic(p)
            }
        }
    }}