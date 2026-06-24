import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

Page {
    id: taskPage
    padding: 24
    background: Item {
        Rectangle {
            anchors.fill: parent
            color: "transparent"
        }
        Rectangle {
            width: 360
            height: 360
            radius: 180
            x: parent.width - width * 0.65
            y: -height * 0.45
            color: AppPalette.glass ? AppPalette.glassGlowCyan : AppPalette.accentSoft
            opacity: AppPalette.dark ? 0.16 : 0.24
        }
        Rectangle {
            width: 280
            height: 280
            radius: 140
            x: -width * 0.42
            y: parent.height - height * 0.58
            color: AppPalette.glass ? AppPalette.glassGlowAmber : AppPalette.backgroundAlt
            opacity: AppPalette.dark ? 0.16 : 0.32
        }
    }

    property var cfg: null
    property var tbridge: null
    readonly property bool busy: tbridge ? tbridge.busy : false
    readonly property bool readyToStart: cfg && cfg.inp !== "" && cfg.out !== ""
    readonly property string titleFont: typeof AppFontTitle !== "undefined" ? AppFontTitle : "Microsoft YaHei UI"

    signal navigateToStatus()

    function openManualEdit(src, dst) {
        manualEditDialog.srcText = (src || "").trim()
        manualEditDialog.dstText = (dst || "").trim()
        srcSearchField.text = manualEditDialog.srcText
        dstEditField.text = manualEditDialog.dstText
        manualEditStatus.text = ""
        manualEditDialog.keepPreset = true
        manualEditDialog.open()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 18

        RowLayout {
            Layout.fillWidth: true
            spacing: 14

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label {
                    text: "任务"
                    color: AppPalette.textColor
                    font.family: taskPage.titleFont
                    font.pixelSize: 28
                    font.weight: Font.DemiBold
                }
                Label {
                    text: "把 EPUB 放到工作台上，确认源文件和输出文件，然后开始翻译或断点续译。"
                    color: AppPalette.mutedText
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Rectangle {
                Layout.preferredWidth: 128
                Layout.preferredHeight: 34
                radius: 17
                color: AppPalette.accentSoft
                border.color: AppPalette.borderColor
                Label {
                    anchors.centerIn: parent
                    text: taskPage.busy ? "翻译运行中" : "等待任务"
                    color: taskPage.busy ? AppPalette.accentColor : AppPalette.mutedText
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: taskPage.width > 980 ? 2 : 1
            columnSpacing: 18
            rowSpacing: 18

            Rectangle {
                id: dropCard
                Layout.fillWidth: true
                Layout.preferredHeight: 320
                radius: AppPalette.radiusLarge
                color: AppPalette.cardBg
                border.color: dropCard.hovering ? AppPalette.amberColor : AppPalette.borderColor
                border.width: dropCard.hovering ? 2 : 1
                scale: dropCard.hovering ? 1.012 : 1.0

                property bool hovering: false

                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 22
                    spacing: 16

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        Rectangle {
                            Layout.preferredWidth: 48
                            Layout.preferredHeight: 48
                            radius: 16
                            color: AppPalette.accentSoft
                            border.color: AppPalette.lineColor
                            Label {
                                anchors.centerIn: parent
                                text: "EPUB"
                                color: AppPalette.accentColor
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2
                            Label {
                                text: "把书放到工作台上"
                                color: AppPalette.textColor
                                font.pixelSize: 19
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: "拖入新文件会自动生成当前书名对应的 _zh.epub 输出路径。"
                                color: AppPalette.mutedText
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }

                    Rectangle {
                        id: dropArea
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        radius: 22
                        color: dropCard.hovering ? AppPalette.accentSoft : AppPalette.fieldBg
                        border.color: dropCard.hovering ? AppPalette.amberColor : AppPalette.lineColor
                        border.width: dropCard.hovering ? 2 : 1

                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: -5
                            radius: 27
                            color: "transparent"
                            border.color: AppPalette.amberColor
                            border.width: dropCard.hovering ? 1 : 0
                            opacity: dropCard.hovering ? 0.45 : 0
                        }

                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: 7
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: dropCard.hovering ? "释放 EPUB 文件" : "拖放 EPUB 文件到这里"
                                color: AppPalette.textColor
                                font.pixelSize: 19
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: "或使用右侧“选择源文件”按钮"
                                color: AppPalette.mutedText
                                font.pixelSize: 12
                            }
                        }

                        DropArea {
                            anchors.fill: parent
                            onEntered: dropCard.hovering = true
                            onExited: dropCard.hovering = false
                            onDropped: function(drop) {
                                dropCard.hovering = false
                                if (drop.urls.length > 0) {
                                    var path = FilePathUtils.normalizeFileUrl(drop.urls[0])
                                    taskPage.setInputPath(path)
                                }
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 320
                spacing: 14

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusLarge
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.borderColor

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "源文件"
                                color: AppPalette.textColor
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Label {
                                Layout.preferredWidth: 150
                                text: taskPage.compactEstimateText(estimateLabel.text)
                                color: AppPalette.accentColor
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                                horizontalAlignment: Text.AlignRight
                                elide: Text.ElideRight
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: taskPage.pathDisplay(cfg ? cfg.inp : "")
                            color: (cfg && cfg.inp !== "") ? AppPalette.textColor : AppPalette.mutedText
                            font.pixelSize: 13
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            TextField {
                                id: inpField
                                Layout.fillWidth: true
                                placeholderText: "输入 EPUB 路径"
                                text: cfg ? cfg.inp : ""
                                selectByMouse: true
                                onTextChanged: {
                                    if (cfg) cfg.inp = text
                                    if (!activeFocus) cursorPosition = 0
                                    if (activeFocus) estimateTimer.restart()
                                }
                                onEditingFinished: {
                                    if (text !== "") taskPage.setInputPath(text)
                                }
                                Component.onCompleted: cursorPosition = 0
                            }
                            Button {
                                text: "选择源文件"
                                onClicked: inputDialog.open()
                            }
                        }

                        Label {
                            id: estimateLabel
                            visible: false
                            text: "预估字符: -"
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: AppPalette.radiusLarge
                    color: AppPalette.surfaceRaised
                    border.color: AppPalette.borderColor

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 18
                        spacing: 10

                        RowLayout {
                            Layout.fillWidth: true
                            Label {
                                Layout.fillWidth: true
                                text: "输出文件"
                                color: AppPalette.textColor
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Label {
                                text: "EPUB"
                                color: AppPalette.amberColor
                                font.pixelSize: 11
                                font.weight: Font.DemiBold
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: taskPage.pathDisplay(cfg ? cfg.out : "")
                            color: (cfg && cfg.out !== "") ? AppPalette.textColor : AppPalette.mutedText
                            font.pixelSize: 13
                            elide: Text.ElideMiddle
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            TextField {
                                id: outField
                                Layout.fillWidth: true
                                placeholderText: "输出文件路径 (.epub)"
                                text: cfg ? cfg.out : ""
                                selectByMouse: true
                                onTextChanged: {
                                    if (cfg) cfg.out = text
                                    if (!activeFocus) cursorPosition = 0
                                }
                                Component.onCompleted: cursorPosition = 0
                            }
                            Button {
                                text: "选择输出"
                                onClicked: outputDialog.open()
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: taskPage.width > 900 ? 298 : 372
            radius: AppPalette.radiusLarge
            color: AppPalette.glass ? Qt.rgba(1, 1, 1, 0.48) : AppPalette.surfaceRaised
            border.color: AppPalette.borderColor
            clip: true

            Rectangle {
                width: 260
                height: 260
                radius: 130
                anchors.right: parent.right
                anchors.rightMargin: -96
                anchors.top: parent.top
                anchors.topMargin: -112
                color: AppPalette.accentSoft
                opacity: 0.45
            }

            Rectangle {
                width: 170
                height: 170
                radius: 85
                anchors.left: parent.left
                anchors.leftMargin: -70
                anchors.bottom: parent.bottom
                anchors.bottomMargin: -88
                color: AppPalette.glass ? AppPalette.glassGlowAmber : AppPalette.backgroundAlt
                opacity: 0.36
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Label {
                        Layout.fillWidth: true
                        text: "准备翻译"
                        color: AppPalette.textColor
                        font.pixelSize: 18
                        font.weight: Font.DemiBold
                    }
                    Rectangle {
                        Layout.preferredWidth: 86
                        Layout.preferredHeight: 24
                        radius: 12
                        color: taskPage.readyToStart ? AppPalette.cardBg : AppPalette.cardAlt
                        border.color: AppPalette.lineColor
                        Label {
                            anchors.centerIn: parent
                            text: taskPage.readyToStart ? "可开始" : "待选择"
                            color: taskPage.readyToStart ? AppPalette.successColor : AppPalette.mutedText
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: taskPage.width > 900 ? 150 : 224
                    spacing: 8

                    TaskActionButton {
                        id: startBtn
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        primary: true
                        label: taskPage.busy ? "翻译中..." : "开始翻译"
                        hint: taskPage.readyToStart ? "使用当前模型与参数启动任务" : "请先选择源文件和输出文件"
                        enabled: taskPage.readyToStart && !taskPage.busy
                        onClicked: {
                            if (taskPage.tbridge) {
                                taskPage.tbridge.startTranslation(cfg)
                                taskPage.navigateToStatus()
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12

                        GridLayout {
                            Layout.fillWidth: true
                            columns: taskPage.width > 900 ? 5 : (taskPage.width > 600 ? 3 : 2)
                            columnSpacing: 10
                            rowSpacing: 10

                            TaskActionButton {
                                id: pauseBtn
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                label: "暂停"
                                hint: "保留已写入缓存"
                                enabled: taskPage.busy
                                onClicked: { if (taskPage.tbridge) taskPage.tbridge.pauseTranslation() }
                            }

                            TaskActionButton {
                                id: resumeBtn
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                label: "恢复"
                                hint: "继续断点任务"
                                enabled: taskPage.readyToStart && !taskPage.busy
                                onClicked: {
                                    if (taskPage.tbridge) {
                                        taskPage.tbridge.resumeTranslation(cfg)
                                        taskPage.navigateToStatus()
                                    }
                                }
                            }

                            TaskActionButton {
                                id: stopBtn
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                label: "停止"
                                hint: "取消并清空本次缓存"
                                danger: true
                                enabled: taskPage.busy
                                onClicked: {
                                    if (taskPage.tbridge) {
                                        taskPage.tbridge.stopTranslation()
                                    }
                                }
                            }

                            TaskActionButton {
                                id: clearCacheBtn
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                label: "清缓存"
                                hint: "重新翻译当前书"
                                enabled: taskPage.readyToStart && !taskPage.busy
                                onClicked: clearCacheDialog.open()
                            }

                            TaskActionButton {
                                id: manualEditBtn
                                Layout.fillWidth: true
                                Layout.preferredHeight: 40
                                label: "人工修改"
                                hint: "编辑单条译文"
                                enabled: !taskPage.busy
                                onClicked: manualEditDialog.open()
                            }
                        }
                    }

                    Flow {
                        Layout.fillWidth: true
                        spacing: 7
                        SummaryChip { title: "模型"; value: taskPage.modelSummary() }
                        SummaryChip { title: "并发"; value: taskPage.valueOrDash(cfg ? cfg.maxWorkers : "") }
                        SummaryChip { title: "批量"; value: taskPage.valueOrDash(cfg ? cfg.batchSize : "") }
                        SummaryChip { title: "单条上限"; value: taskPage.valueOrDash(cfg ? cfg.maxTextSizeForBatch : "") }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    Layout.bottomMargin: 2
                    radius: 22
                    color: AppPalette.fieldBg
                    border.color: AppPalette.lineColor

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 16
                        anchors.rightMargin: 10
                        anchors.topMargin: 6
                        anchors.bottomMargin: 6
                        spacing: 10
                        Rectangle {
                            Layout.preferredWidth: 8
                            Layout.preferredHeight: 8
                            radius: 4
                            color: taskPage.readyToStart ? AppPalette.successColor : AppPalette.amberColor
                        }
                        Label {
                            Layout.fillWidth: true
                            text: "暂停会保留已写入缓存的内容，切换模型后点“恢复”可续译；停止会取消任务并清空本次已翻译缓存。"
                            color: AppPalette.mutedText
                            wrapMode: Text.NoWrap
                            font.pixelSize: 12
                            maximumLineCount: 1
                            elide: Text.ElideRight
                        }
                        Rectangle {
                            visible: taskPage.width > 880
                            Layout.preferredWidth: 104
                            Layout.preferredHeight: 28
                            radius: 14
                            color: taskPage.readyToStart ? AppPalette.accentSoft : AppPalette.cardAlt
                            border.color: AppPalette.lineColor
                            Label {
                                anchors.centerIn: parent
                                text: taskPage.readyToStart ? "工作台已就绪" : "等待文件"
                                color: taskPage.readyToStart ? AppPalette.successColor : AppPalette.mutedText
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: "数据目录: " + (AppDir || "")
            color: AppPalette.mutedText
            font.pixelSize: 11
            elide: Text.ElideMiddle
        }

        Item { Layout.fillHeight: true }
    }

    component TaskActionButton: Rectangle {
        id: actionRoot
        property string label: ""
        property string hint: ""
        property bool primary: false
        property bool danger: false
        signal clicked()

        implicitWidth: primary ? 320 : 132
        implicitHeight: primary ? 64 : 40
        radius: primary ? 24 : 18
        color: !enabled
               ? AppPalette.cardAlt
               : (primary ? AppPalette.accentColor : (danger ? Qt.rgba(0.80, 0.24, 0.20, AppPalette.glass ? 0.18 : 0.10) : AppPalette.cardBg))
        border.color: !enabled
                      ? AppPalette.lineColor
                      : (primary ? AppPalette.accentColor : (danger ? AppPalette.errorColor : AppPalette.borderColor))
        border.width: primary ? 0 : 1
        opacity: enabled ? 1.0 : 0.52
        scale: actionMouse.containsMouse && enabled ? 1.012 : 1.0

        Behavior on scale {
            NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "transparent"
            border.color: actionMouse.containsMouse && actionRoot.enabled ? AppPalette.amberColor : "transparent"
            border.width: 1
            opacity: actionMouse.containsMouse ? 0.7 : 0
        }

        ColumnLayout {
            anchors.centerIn: parent
            width: parent.width - 20
            spacing: primary ? 5 : 1
            Label {
                Layout.alignment: Qt.AlignHCenter
                text: actionRoot.label
                color: !actionRoot.enabled
                       ? AppPalette.mutedText
                       : (actionRoot.primary ? "#ffffff" : (actionRoot.danger ? AppPalette.errorColor : AppPalette.textColor))
                font.pixelSize: actionRoot.primary ? 18 : 13
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                maximumLineCount: 1
            }
            Label {
                Layout.alignment: Qt.AlignHCenter
                visible: actionRoot.hint !== ""
                text: actionRoot.hint
                color: actionRoot.primary ? Qt.rgba(1, 1, 1, 0.82) : AppPalette.mutedText
                font.pixelSize: actionRoot.primary ? 11 : 9
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }

        MouseArea {
            id: actionMouse
            anchors.fill: parent
            hoverEnabled: true
            enabled: actionRoot.enabled
            cursorShape: Qt.PointingHandCursor
            onClicked: actionRoot.clicked()
        }
    }

    FileDialog {
        id: inputDialog
        title: "选择 EPUB 文件"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            if (selectedFile) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                taskPage.setInputPath(p)
            }
        }
    }

    FileDialog {
        id: outputDialog
        title: "保存翻译后的 EPUB"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.SaveFile
        onAccepted: {
            if (selectedFile) {
                var p = FilePathUtils.normalizeFileUrl(selectedFile)
                if (!p.toLowerCase().endsWith(".epub")) p += ".epub"
                if (cfg) cfg.out = p
            }
        }
    }

    Dialog {
        id: clearCacheDialog
        title: "清理当前 EPUB 缓存"
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: parent

        ColumnLayout {
            width: 420
            spacing: 10
            Label {
                Layout.fillWidth: true
                text: "将清理���前源文件对应的翻译缓存，包括所有模型下的 cache.json 条目和跨模型 text_cache.json 条目。"
                color: AppPalette.textColor
                wrapMode: Text.WordWrap
            }
            Label {
                Layout.fillWidth: true
                text: "不会删除 EPUB 文件，也不会清空术语表。清理后再次翻译会重新请求 API。"
                color: AppPalette.mutedText
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
        }

        onAccepted: {
            if (taskPage.tbridge) {
                taskPage.tbridge.clearCurrentBookCache(cfg)
            }
        }
    }

    Dialog {
        id: manualEditDialog
        title: "人工修改译文"
        modal: true
        standardButtons: Dialog.Ok | Dialog.Cancel
        anchors.centerIn: parent
        width: 640

        property string srcText: ""
        property string dstText: ""
        property bool keepPreset: false

        ColumnLayout {
            width: parent.width - 40
            spacing: 14

            Label {
                Layout.fillWidth: true
                text: "输入日文原文查找已缓存译文，也可以直接填写中文译文。保存后写入人工译文缓存，恢复续译或下次翻译时优先使用，不会直接修改已经生成的 EPUB。"
                color: AppPalette.mutedText
                wrapMode: Text.WordWrap
                font.pixelSize: 12
            }

            Label {
                text: "日文原文（必须与 EPUB 中的原文一致）:"
                color: AppPalette.textColor
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            TextField {
                id: srcSearchField
                Layout.fillWidth: true
                placeholderText: "输入日文原文来查找或保存人工译文..."
                selectByMouse: true
            }

            Button {
                text: "查找译文"
                Layout.alignment: Qt.AlignLeft
                onClicked: {
                    manualEditDialog.srcText = srcSearchField.text.trim()
                    if (taskPage.tbridge && manualEditDialog.srcText) {
                        taskPage.tbridge.lookupTranslation(manualEditDialog.srcText)
                    }
                }
            }

            Label {
                text: "中文译文（可直接编辑）:"
                color: AppPalette.textColor
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            TextArea {
                id: dstEditField
                Layout.fillWidth: true
                Layout.preferredHeight: 120
                placeholderText: '点击"查找译文"后，译文会显示在这里；也可以直接输入人工译文。'
                wrapMode: TextArea.Wrap
                selectByMouse: true
            }

            Label {
                id: manualEditStatus
                Layout.fillWidth: true
                text: ""
                color: AppPalette.mutedText
                font.pixelSize: 12
                visible: text !== ""
            }
        }

        onOpened: {
            if (!keepPreset) {
                srcSearchField.text = ""
                dstEditField.text = ""
                manualEditDialog.srcText = ""
                manualEditDialog.dstText = ""
            }
            keepPreset = false
            manualEditStatus.text = ""
        }

        onAccepted: {
            var src = manualEditDialog.srcText
            var dst = dstEditField.text.trim()
            if (!src || !dst) {
                manualEditStatus.text = "原文和译文不能为空"
                manualEditStatus.color = AppPalette.errorColor
                return
            }
            if (taskPage.tbridge) {
                taskPage.tbridge.saveManualTranslation(src, dst)
                manualEditStatus.text = "已保存，恢复续译或下次翻译时会优先使用"
                manualEditStatus.color = AppPalette.successColor
            }
        }
    }

    Timer {
        id: estimateTimer
        interval: 300
        onTriggered: {
            if (cfg && cfg.inp) {
                estimateLabel.text = "预估字符: 计算中..."
                if (taskPage.tbridge) taskPage.tbridge.startEstimateChars(cfg.inp)
            }
        }
    }

    Connections {
        target: taskPage.tbridge
        enabled: true
        function onEstimateFinished(path, chars) {
            if (cfg && path === cfg.inp && chars >= 0) {
                estimateLabel.text = "预估字符: " + chars.toLocaleString()
            }
        }
        function onEstimateFailed(path, err) {
            if (cfg && path === cfg.inp) {
                estimateLabel.text = "预估字符: 读取失败"
            }
        }
        function onManualTranslationLookup(result) {
            if (typeof manualEditDialog !== "undefined" && manualEditDialog.visible && result) {
                dstEditField.text = result
                manualEditStatus.text = ""
            }
        }
        function onManualTranslationSaved(result) {
            if (typeof manualEditDialog !== "undefined" && manualEditDialog.visible) {
                manualEditStatus.text = "已保存，恢复续译或下次翻译时会优先使用"
                manualEditStatus.color = AppPalette.successColor
            }
        }
        function onFailed(err) {
            if (typeof manualEditDialog !== "undefined" && manualEditDialog.visible) {
                manualEditStatus.text = err
                manualEditStatus.color = AppPalette.errorColor
            }
        }
    }

    function defaultOutputPath(path) {
        var normalized = (path || "").replace(/\\/g, "/")
        var slash = normalized.lastIndexOf("/")
        var dir = slash >= 0 ? normalized.substring(0, slash + 1) : ""
        var base = slash >= 0 ? normalized.substring(slash + 1) : normalized
        base = base.replace(/\.epub$/i, "")
        return dir + base + "_zh.epub"
    }

    function fileName(path) {
        if (!path || path === "") return "未选择"
        var normalized = path.replace(/\\/g, "/")
        var slash = normalized.lastIndexOf("/")
        return slash >= 0 ? normalized.substring(slash + 1) : normalized
    }

    function pathDisplay(path) {
        if (!path || path === "") return "未选择"
        return path.replace(/\\/g, "/")
    }

    function compactEstimateText(text) {
        if (!text || text === "预估字符: -") return "预估: -"
        return text.replace("预估字符:", "预估:")
    }

    function valueOrDash(value) {
        if (value === undefined || value === null || value === "") return "-"
        return value.toString()
    }

    function modelSummary() {
        if (!cfg) return "-"
        var provider = cfg.provider || "-"
        var model = cfg.model || "-"
        if (model === "-") return provider
        return provider + " / " + model
    }

    function setInputPath(path) {
        if (cfg) {
            cfg.inp = path
            cfg.out = taskPage.defaultOutputPath(path)
        }
        estimateLabel.text = "预估字符: 计算中..."
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
        if (taskPage.tbridge) taskPage.tbridge.startEstimateChars(path)
    }

    Component.onCompleted: {
        Qt.callLater(function() {
            inpField.cursorPosition = 0
            outField.cursorPosition = 0
        })
    }

    component SummaryChip: Rectangle {
        property string title: ""
        property string value: ""

        width: Math.min(240, Math.max(88, chipRow.implicitWidth + 22))
        height: 28
        radius: 15
        color: AppPalette.cardBg
        border.color: AppPalette.lineColor

        RowLayout {
            id: chipRow
            anchors.centerIn: parent
            spacing: 5
            Label {
                text: title + ":"
                color: AppPalette.mutedText
                font.pixelSize: 11
            }
            Label {
                text: value
                color: AppPalette.textColor
                font.pixelSize: 11
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                maximumLineCount: 1
            }
        }
    }
}

