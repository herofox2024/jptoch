import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Dialogs
import ".."

/* ============================================================
   GlossaryProfileSection — 术语 Profile 模块（自包含）

   原 GlossaryPage 中与「术语 profile / 术语提取 / 译后统一」
   相关的状态、逻辑、两个 Dialog 和两个 FileDialog 全部下沉到这里，
   页面只保留「术语表」职责和两个入口按钮。

   依赖注入：cfg / tbridge（由页面传入）。
   ============================================================ */

Item {
    id: section

    property var cfg: null
    property var tbridge: null

    // 状态
    property string glossaryProfileStatus: ""
    property string glossaryBatchStatus: ""
    property string glossaryPostApplyStatus: ""
    property bool glossaryTaskActive: false

    // 书籍列表
    property var glossaryExtractionBooks: []
    property var glossaryPostApplyBooks: []

    // 提取模式
    property var glossaryExtractionModeValues: ["novel", "lite"]
    property var glossaryExtractionModeLabels: ["小说向（novel）", "精简（lite）"]

    // profile scope
    property var glossaryProfileScopeValues: ["all", "genre", "series", "book"]
    property var glossaryProfileScopeLabels: ["全部", "题材", "系列", "本书"]
    property var glossaryProfileTargetScopeValues: ["genre", "series", "book"]
    property var glossaryProfileTargetScopeLabels: ["题材", "系列", "本书"]

    ListModel { id: glossaryProfileModel }

    // 公开接口（供页面入口按钮调用）
    function openWorkflowDialog() { glossaryWorkflowDialog.open() }
    function openProfileDialog() { glossaryProfileDialog.open() }

    function _normalizeEpubPaths(values) {
        var items = []
        if (!values) return items
        if (typeof values === "string") values = [values]
        for (var i = 0; i < values.length; i++) {
            var path = FilePathUtils.normalizeFileUrl(values[i])
            if (path && path.toLowerCase().endsWith(".epub") && items.indexOf(path) < 0) {
                items.push(path)
            }
        }
        return items
    }

    function glossaryExtractionModeIndex(value) {
        var idx = section.glossaryExtractionModeValues.indexOf(String(value || "novel").toLowerCase())
        return idx >= 0 ? idx : 0
    }

    function glossaryExtractionModeValue(index) {
        return section.glossaryExtractionModeValues[index] || "novel"
    }

    function syncGlossaryExtractionModeCombo() {
        if (typeof glossaryExtractionModeCombo === "undefined") return
        glossaryExtractionModeCombo.currentIndex = section.glossaryExtractionModeIndex(
            section.cfg ? section.cfg.glossaryExtractionMode : "novel"
        )
    }

    function glossaryProviderLabel(provider) {
        var value = String(provider || "deepseek").toLowerCase()
        if (value === "deepseek") return "DeepSeek"
        if (value === "doubao") return "豆包"
        if (value === "sakura") return "Sakura 本地"
        if (value === "hymt2") return "Hy-MT2 本地"
        if (value === "gemini") return "Gemini"
        if (value === "glm") return "GLM"
        if (value === "wenxin") return "文心/千帆"
        if (value === "longcat") return "LongCat"
        if (value === "custom") return "Custom"
        return value
    }

    function glossaryProviderCapability(provider) {
        var value = String(provider || "deepseek").toLowerCase()
        if (value === "deepseek") return "推荐用于术语抽取：支持 JSON 输出约束，稳定性最好。"
        if (value === "longcat") return "可用于术语抽取：注意 API Key、审核拦截和长尾等待。"
        if (value === "sakura" || value === "hymt2") return "本地模型可用，但 JSON 稳定性较弱，不建议作为高质量术语抽取首选。"
        if (value === "custom") return "自定义接口可用，前提是兼容 OpenAI chat/completions 并能稳定返回 JSON。"
        return "已接入术语抽取，稳定性取决于模型对 JSON 输出的遵循程度。"
    }

    function glossaryExtractionProviderText() {
        var provider = section.cfg ? section.cfg.provider : "deepseek"
        var model = section.cfg ? String(section.cfg.model || "") : ""
        var mode = section.cfg ? String(section.cfg.glossaryExtractionMode || "lite") : "lite"
        return "当前术语抽取模型：" + section.glossaryProviderLabel(provider)
                + (model !== "" ? " / " + model : "")
                + "；模式：" + mode + "。"
                + section.glossaryProviderCapability(provider)
    }

    function glossaryProfileLabel(profile) {
        var item = profile || {}
        var profileName = String(item.name || "未命名")
        var count = Number(item.termCount || 0)
        return section.glossaryProfileScopeLabel(item.scope) + " / " + profileName + " / " + count + " 条"
    }

    function addGlossaryExtractionBooks(paths) {
        var values = section._normalizeEpubPaths(paths)
        if (values.length === 0) return
        var merged = section.glossaryExtractionBooks.slice()
        for (var i = 0; i < values.length; i++) {
            if (merged.indexOf(values[i]) < 0) merged.push(values[i])
        }
        section.glossaryExtractionBooks = merged
        section.glossaryBatchStatus = "已选择 " + merged.length + " 本 EPUB，点击“批量提取术语”生成 profile。"
    }

    function removeGlossaryExtractionBook(index) {
        var values = section.glossaryExtractionBooks.slice()
        if (index >= 0 && index < values.length) values.splice(index, 1)
        section.glossaryExtractionBooks = values
        section.glossaryBatchStatus = values.length > 0 ? "已选择 " + values.length + " 本 EPUB" : ""
    }

    function clearGlossaryExtractionBooks() {
        section.glossaryExtractionBooks = []
        section.glossaryBatchStatus = ""
    }

    function addGlossaryPostApplyBooks(paths) {
        var values = section._normalizeEpubPaths(paths)
        if (values.length === 0) return
        var merged = section.glossaryPostApplyBooks.slice()
        for (var i = 0; i < values.length; i++) {
            if (merged.indexOf(values[i]) < 0) merged.push(values[i])
        }
        section.glossaryPostApplyBooks = merged
        section.glossaryPostApplyStatus = "已选择 " + merged.length + " 本已翻译 EPUB，点击“统一术语并输出 EPUB”生成副本。"
    }

    function removeGlossaryPostApplyBook(index) {
        var values = section.glossaryPostApplyBooks.slice()
        if (index >= 0 && index < values.length) values.splice(index, 1)
        section.glossaryPostApplyBooks = values
    }

    function clearGlossaryPostApplyBooks() {
        section.glossaryPostApplyBooks = []
        section.glossaryPostApplyStatus = ""
    }

    function extractSelectedBooksGlossary() {
        if (!section.tbridge || !section.tbridge.extractGlossaryFromBooks || !section.cfg) return
        if (section.glossaryExtractionBooks.length === 0) return
        section.glossaryTaskActive = true
        section.glossaryBatchStatus = "正在批量提取术语..."
        section.glossaryPostApplyStatus = ""
        section.tbridge.extractGlossaryFromBooks(section.cfg, section.glossaryExtractionBooks)
    }

    function applyGlossaryToTranslatedBook() {
        if (!section.tbridge || !section.cfg) return
        section.glossaryTaskActive = true
        section.glossaryBatchStatus = ""
        section.glossaryPostApplyStatus = "正在统一已翻译 EPUB 的术语..."
        if (section.glossaryPostApplyBooks.length > 0 && section.tbridge.applyGlossaryToTranslatedBooks) {
            section.tbridge.applyGlossaryToTranslatedBooks(section.cfg, section.glossaryPostApplyBooks)
        } else if (section.tbridge.applyGlossaryToTranslatedBook) {
            section.tbridge.applyGlossaryToTranslatedBook(section.cfg)
        }
    }

    function glossaryProfileScopeValue(index) {
        return section.glossaryProfileScopeValues[index] || ""
    }

    function glossaryProfileTargetScopeValue(index) {
        return section.glossaryProfileTargetScopeValues[index] || "book"
    }

    function glossaryProfileScopeIndex(value) {
        var idx = section.glossaryProfileScopeValues.indexOf(value || "all")
        return idx >= 0 ? idx : 0
    }

    function glossaryProfileTargetScopeIndex(value) {
        var idx = section.glossaryProfileTargetScopeValues.indexOf(value || "book")
        return idx >= 0 ? idx : 2
    }

    function glossaryProfileScopeLabel(value) {
        var idx = section.glossaryProfileScopeValues.indexOf(value || "all")
        return idx >= 0 ? section.glossaryProfileScopeLabels[idx] : "全部"
    }

    function formatTimestamp(ts) {
        if (!ts) return "-"
        var value = new Date(ts * 1000)
        if (isNaN(value.getTime())) return "-"
        return Qt.formatDateTime(value, "yyyy-MM-dd hh:mm")
    }

    function refreshGlossaryProfiles() {
        if (!section.cfg || !section.cfg.listGlossaryProfiles) return
        var scope = section.glossaryProfileScopeValue(profileFilterCombo.currentIndex)
        var items = section.cfg.listGlossaryProfiles(scope === "all" ? "" : scope)
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
        section.glossaryProfileStatus = glossaryProfileModel.count > 0
                ? "共 " + glossaryProfileModel.count + " 个 profile"
                : "暂无 profile"
    }

    function saveCurrentGlossaryProfile() {
        if (!section.cfg || !section.cfg.saveCurrentGlossaryAsProfile) return
        var name = glossaryProfileNameField.text.trim()
        if (!name) {
            section.glossaryProfileStatus = "请输入 profile 名称"
            return
        }
        var scope = section.glossaryProfileTargetScopeValue(profileTargetCombo.currentIndex)
        var sourceBook = glossaryProfileSourceField.text.trim()
        var result = section.cfg.saveCurrentGlossaryAsProfile(scope, name, sourceBook)
        section.glossaryProfileStatus = result.message || ""
        if (result.ok) {
            section.refreshGlossaryProfiles()
        }
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(section.glossaryProfileStatus) : ToastBridge.showError(section.glossaryProfileStatus)
        }
    }

    function deleteGlossaryProfile(profileId) {
        if (!section.cfg || !section.cfg.deleteGlossaryProfile || !profileId) return
        var result = section.cfg.deleteGlossaryProfile(profileId)
        section.glossaryProfileStatus = result.message || ""
        section.refreshGlossaryProfiles()
        if (typeof ToastBridge !== "undefined" && ToastBridge) {
            result.ok ? ToastBridge.showSuccess(section.glossaryProfileStatus) : ToastBridge.showError(section.glossaryProfileStatus)
        }
    }

    Connections {
        target: section.cfg
        ignoreUnknownSignals: true

        function onGlossaryProfilesChanged() {
            section.refreshGlossaryProfiles()
        }
        function onGlossaryExtractionModeChanged() {
            section.syncGlossaryExtractionModeCombo()
        }
    }

    Connections {
        target: section.tbridge
        ignoreUnknownSignals: true

        function onGlossaryBookExtractionProgressChanged(completed, total) {
            section.glossaryTaskActive = true
            section.glossaryBatchStatus = "正在批量提取术语: " + completed + "/" + total
        }
        function onGlossaryBookExtractionFailed(err) {
            section.glossaryTaskActive = false
            section.glossaryBatchStatus = "批量术语提取失败: " + err
        }
        function onGlossaryBookExtractionFinished(result) {
            var message = result && result.message ? result.message : "本书术语提取完成"
            section.glossaryTaskActive = false
            section.glossaryBatchStatus = message
            if (!result || Number(result.failed_count || 0) === 0) {
                section.clearGlossaryExtractionBooks()
            }
            GlossaryProfileUtils.addSelectedGlossaryProfileIds(section.cfg, result && result.profile_ids ? result.profile_ids : [])
            section.refreshGlossaryProfiles()
            if (section.cfg && section.cfg.notifyGlossaryProfilesChanged) {
                section.cfg.notifyGlossaryProfilesChanged()
            }
        }
        function onGlossaryPostApplyFinished(result) {
            var message = result && result.message ? result.message : "术语后处理完成"
            if (result && result.output_path) {
                message += "；输出: " + FilePathUtils.fileName(result.output_path)
            } else if (result && result.output_paths && result.output_paths.length > 0) {
                message += "；输出 " + result.output_paths.length + " 本"
            }
            section.glossaryTaskActive = false
            section.glossaryPostApplyStatus = message
        }
        function onGlossaryPostApplyFailed(err) {
            section.glossaryTaskActive = false
            section.glossaryPostApplyStatus = "术语后处理失败: " + err
        }
    }

    FileDialog {
        id: glossaryExtractionDialog
        title: "选择待抽取 EPUB"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            if (selectedFiles && selectedFiles.length > 0) {
                section.addGlossaryExtractionBooks(selectedFiles)
            } else if (selectedFile) {
                section.addGlossaryExtractionBooks([selectedFile])
            }
        }
    }

    FileDialog {
        id: glossaryPostApplyDialog
        title: "选择已翻译 EPUB"
        nameFilters: ["EPUB 文件 (*.epub)"]
        fileMode: FileDialog.OpenFiles
        onAccepted: {
            if (selectedFiles && selectedFiles.length > 0) {
                section.addGlossaryPostApplyBooks(selectedFiles)
            } else if (selectedFile) {
                section.addGlossaryPostApplyBooks([selectedFile])
            }
        }
    }

    Dialog {
        id: glossaryWorkflowDialog
        modal: true
        anchors.centerIn: parent
        width: Math.max(780, Math.min(section.width - 48, 1080))
        height: Math.max(560, Math.min(section.height - 72, 840))
        title: "术语任务"
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: {
            section.refreshGlossaryProfiles()
            section.syncGlossaryExtractionModeCombo()
        }

        contentItem: ScrollView {
            width: glossaryWorkflowDialog.width
            height: glossaryWorkflowDialog.height
            clip: true
            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
            ScrollBar.vertical.policy: ScrollBar.AsNeeded

            ColumnLayout {
                width: Math.max(0, glossaryWorkflowDialog.width - 32)
                spacing: AppStyle.spacingLarge

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: workflowProfileContent.implicitHeight + 24
                    radius: AppPalette.radiusLarge
                    color: AppPalette.cardBg
                    border.color: AppPalette.borderColor
                    clip: true

                    ColumnLayout {
                        id: workflowProfileContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingSmall

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingMedium

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingTight
                                Label {
                                    text: "翻译时使用的术语 Profile"
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontSubHeader
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: GlossaryProfileUtils.selectedGlossaryProfileCount(section.cfg) > 0
                                          ? "已选 " + GlossaryProfileUtils.selectedGlossaryProfileCount(section.cfg) + " 个 profile；开始翻译或译后统一时生效。"
                                          : "未选择 profile；可先提取术语，或刷新后勾选已有 profile。"
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontCaption
                                    elide: Text.ElideRight
                                }
                            }

                            CheckBox {
                                text: "启用术语表"
                                checked: section.cfg ? section.cfg.enableGlossary : true
                                onCheckedChanged: { if (section.cfg) section.cfg.enableGlossary = checked }
                            }
                            CheckBox {
                                text: "启用分层"
                                checked: section.cfg ? section.cfg.enableLayeredGlossary : false
                                enabled: section.cfg ? section.cfg.enableGlossary : true
                                onCheckedChanged: { if (section.cfg) section.cfg.enableLayeredGlossary = checked }
                            }
                            CheckBox {
                                text: "合并全局"
                                checked: section.cfg ? section.cfg.useGlobalGlossary : true
                                enabled: section.cfg ? (section.cfg.enableGlossary && section.cfg.enableLayeredGlossary) : true
                                onCheckedChanged: { if (section.cfg) section.cfg.useGlobalGlossary = checked }
                            }
                            Button {
                                text: "刷新"
                                onClicked: section.refreshGlossaryProfiles()
                            }
                            Button {
                                text: "清空选择"
                                enabled: GlossaryProfileUtils.selectedGlossaryProfileCount(section.cfg) > 0
                                onClicked: GlossaryProfileUtils.clearSelectedGlossaryProfiles(section.cfg)
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            visible: glossaryProfileModel.count === 0
                            text: "暂无可选 profile。可以在下方选择 EPUB 并提取术语。"
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontCaption
                            wrapMode: Text.WordWrap
                        }

                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(48, Math.min(132, workflowProfileFlow.implicitHeight + 8))
                            visible: glossaryProfileModel.count > 0
                            clip: true
                            ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
                            ScrollBar.vertical.policy: ScrollBar.AsNeeded

                            Flow {
                                id: workflowProfileFlow
                                width: Math.max(0, parent.width)
                                spacing: AppStyle.spacingSmall

                                Repeater {
                                    model: glossaryProfileModel
                                    delegate: CheckBox {
                                        text: section.glossaryProfileScopeLabel(scope) + " / " + (name || "未命名") + " / " + Number(termCount || 0) + " 条"
                                        checked: GlossaryProfileUtils.isGlossaryProfileSelected(section.cfg, profileId || "")
                                        enabled: !!section.cfg && !!section.cfg.enableGlossary
                                        onToggled: GlossaryProfileUtils.toggleGlossaryProfile(section.cfg, profileId || "", checked)
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: workflowExtractContent.implicitHeight + 24
                    radius: AppPalette.radiusLarge
                    color: AppPalette.cardBg
                    border.color: AppPalette.borderColor
                    clip: true

                    ColumnLayout {
                        id: workflowExtractContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingSmall

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingTight
                                Label {
                                    text: "提取术语"
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontSubHeader
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: section.glossaryExtractionProviderText()
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontCaption
                                    wrapMode: Text.WordWrap
                                }
                            }

                            ComboBox {
                                id: glossaryExtractionModeCombo
                                Layout.preferredWidth: 172
                                model: section.glossaryExtractionModeLabels
                                enabled: !!section.cfg
                                onActivated: {
                                    if (section.cfg) {
                                        section.cfg.glossaryExtractionMode = section.glossaryExtractionModeValue(currentIndex)
                                    }
                                }
                                Component.onCompleted: section.syncGlossaryExtractionModeCombo()
                            }
                            Button {
                                text: "选择 EPUB"
                                onClicked: glossaryExtractionDialog.open()
                            }
                            Button {
                                text: "批量提取术语"
                                highlighted: true
                                enabled: !!section.tbridge && !(section.tbridge && section.tbridge.busy) && !!section.cfg && section.glossaryExtractionBooks.length > 0
                                onClicked: section.extractSelectedBooksGlossary()
                            }
                            Button {
                                text: "清空"
                                enabled: section.glossaryExtractionBooks.length > 0
                                onClicked: section.clearGlossaryExtractionBooks()
                            }
                        }

                        Label {
                            Layout.fillWidth: true
                            text: section.glossaryBatchStatus || "选择原始或待翻译 EPUB，提取后会自动生成 book profile 并勾选。"
                            color: AppPalette.mutedText
                            font.pixelSize: AppStyle.fontCaption
                            wrapMode: Text.WordWrap
                        }

                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(36, Math.min(92, glossaryExtractionBooksList.contentHeight + 4))
                            visible: section.glossaryExtractionBooks.length > 0
                            clip: true

                            ListView {
                                id: glossaryExtractionBooksList
                                width: Math.max(0, parent.width)
                                height: contentHeight
                                spacing: AppStyle.spacingTight
                                model: section.glossaryExtractionBooks
                                delegate: RowLayout {
                                    width: ListView.view.width
                                    spacing: AppStyle.spacingSmall
                                    Label {
                                        Layout.fillWidth: true
                                        text: FilePathUtils.pathDisplay(modelData)
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontTiny
                                        elide: Text.ElideMiddle
                                    }
                                    Button {
                                        text: "移除"
                                        onClicked: section.removeGlossaryExtractionBook(index)
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: workflowPostApplyContent.implicitHeight + 24
                    radius: AppPalette.radiusLarge
                    color: AppPalette.cardBg
                    border.color: AppPalette.borderColor
                    clip: true

                    ColumnLayout {
                        id: workflowPostApplyContent
                        anchors.fill: parent
                        anchors.margins: 12
                        spacing: AppStyle.spacingSmall

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: AppStyle.spacingSmall

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: AppStyle.spacingTight
                                Label {
                                    text: "译后术语统一"
                                    color: AppPalette.textColor
                                    font.pixelSize: AppStyle.fontSubHeader
                                    font.weight: Font.DemiBold
                                }
                                Label {
                                    Layout.fillWidth: true
                                    text: section.glossaryPostApplyStatus || "选择已翻译 EPUB，使用已选 profile 的中文别名统一，并生成 _glossary_fixed.epub 副本。"
                                    color: AppPalette.mutedText
                                    font.pixelSize: AppStyle.fontCaption
                                    wrapMode: Text.WordWrap
                                }
                            }

                            Button {
                                text: "选择已译 EPUB"
                                enabled: !!section.tbridge && !(section.tbridge && section.tbridge.busy)
                                onClicked: glossaryPostApplyDialog.open()
                            }
                            Button {
                                text: "统一术语并输出 EPUB"
                                highlighted: true
                                enabled: !!section.tbridge && !(section.tbridge && section.tbridge.busy) && !!section.cfg
                                         && (section.glossaryPostApplyBooks.length > 0 || section.cfg.out !== "")
                                onClicked: section.applyGlossaryToTranslatedBook()
                            }
                            Button {
                                text: "清空"
                                enabled: section.glossaryPostApplyBooks.length > 0
                                onClicked: section.clearGlossaryPostApplyBooks()
                            }
                        }

                        ScrollView {
                            Layout.fillWidth: true
                            Layout.preferredHeight: Math.max(36, Math.min(92, glossaryPostApplyList.contentHeight + 4))
                            visible: section.glossaryPostApplyBooks.length > 0
                            clip: true

                            ListView {
                                id: glossaryPostApplyList
                                width: Math.max(0, parent.width)
                                height: contentHeight
                                spacing: AppStyle.spacingTight
                                model: section.glossaryPostApplyBooks
                                delegate: RowLayout {
                                    width: ListView.view.width
                                    spacing: AppStyle.spacingSmall
                                    Label {
                                        Layout.fillWidth: true
                                        text: FilePathUtils.pathDisplay(modelData)
                                        color: AppPalette.textColor
                                        font.pixelSize: AppStyle.fontTiny
                                        elide: Text.ElideMiddle
                                    }
                                    Button {
                                        text: "移除"
                                        onClicked: section.removeGlossaryPostApplyBook(index)
                                    }
                                }
                            }
                        }
                    }
                }

                ProgressBar {
                    Layout.fillWidth: true
                    visible: section.glossaryTaskActive
                    value: section.tbridge ? section.tbridge.glossaryProgressValue : 0
                    indeterminate: section.glossaryTaskActive && value < 0.001
                    Behavior on value {
                        NumberAnimation { duration: 240; easing.type: Easing.OutCubic }
                    }
                }
            }
        }
    }

    Dialog {
        id: glossaryProfileDialog
        modal: true
        anchors.centerIn: parent
        width: Math.max(760, Math.min(section.width - 48, 1040))
        height: Math.max(520, Math.min(section.height - 72, 820))
        title: "术语 Profile 管理"
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        onOpened: section.refreshGlossaryProfiles()

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
                        text: section.cfg ? section.cfg.glossaryProfilesPath : ""
                        readOnly: true
                        selectByMouse: true
                        color: AppPalette.textColor
                        font.pixelSize: AppStyle.fontCaption
                    }
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: section.width > 920 ? 4 : 2
                    rowSpacing: 8
                    columnSpacing: 12

                    Label { text: "过滤范围" }
                    ComboBox {
                        id: profileFilterCombo
                        Layout.fillWidth: true
                        model: section.glossaryProfileScopeLabels
                        currentIndex: section.glossaryProfileScopeIndex("all")
                        onActivated: section.refreshGlossaryProfiles()
                    }

                    Label { text: "保存范围" }
                    ComboBox {
                        id: profileTargetCombo
                        Layout.fillWidth: true
                        model: section.glossaryProfileTargetScopeLabels
                        currentIndex: section.glossaryProfileTargetScopeIndex("book")
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
                        onClicked: section.saveCurrentGlossaryProfile()
                    }

                    Button {
                        text: "刷新"
                        onClicked: section.refreshGlossaryProfiles()
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: section.glossaryProfileStatus
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
                                        text: section.glossaryProfileScopeLabel(scope)
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
                                        text: section.formatTimestamp(updatedAt || createdAt)
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
                                        onClicked: section.deleteGlossaryProfile(profileId)
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
}
