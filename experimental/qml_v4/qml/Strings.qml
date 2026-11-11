pragma Singleton

import QtQuick

/* ============================================================
   Strings — 界面文案集中处

   背景：全项目 `qsTr(` 出现 0 次，文案散落在 48 个 QML 文件里，
   后续要出英文界面得改动几百处。这里先把**结构性命名牌**收敛到一处：
   页面标题、导航项、主要动作按钮、状态词。

   约定：
     - 只放会被多处引用、或需要整体更换语言的文案；
     - 长段落说明文字仍留在原地（贴上下文更易维护），
       但页面标题、导航、主按钮、状态词必须先从这里取；
     - 后续接 qsTr 时，只需把这里的字面量换成 qsTr("...") 即可，
       调用点无需改动。
   ============================================================ */

QtObject {
    // ---- 应用 ----
    readonly property string appName: "AI日译中（EPUB）"
    readonly property string appTagline: "日系小说翻译工作台"
    readonly property string about: "关于"

    // ---- 导航 ----
    readonly property string navWorkspace: "工作台"
    readonly property string navWorkspaceDesc: "翻译与任务"
    readonly property string navStatus: "状态"
    readonly property string navStatusDesc: "实时进度"
    readonly property string navLog: "日志"
    readonly property string navLogDesc: "实时诊断"
    readonly property string navApi: "API"
    readonly property string navApiDesc: "模型接口"
    readonly property string navGlossary: "术语表"
    readonly property string navGlossaryDesc: "名词统一"
    readonly property string navSettings: "设置"
    readonly property string navSettingsDesc: "性能校对"

    // ---- 页面标题 ----
    readonly property string pageTask: "任务"
    readonly property string pageMonitor: "状态监控"
    readonly property string pageLog: "日志"
    readonly property string pageApi: "API 接口配置"
    readonly property string pageGlossary: "术语表"
    readonly property string pageOptions: "翻译设置"

    // ---- 工作台主按钮 ----
    readonly property string actionStart: "开始翻译"
    readonly property string actionStarting: "翻译中..."
    readonly property string actionPause: "暂停"
    readonly property string actionResume: "恢复"
    readonly property string actionStop: "停止"
    readonly property string actionClearCache: "清缓存"
    readonly property string actionManualEdit: "人工修改"
    readonly property string actionStopConfirmTitle: "确认停止翻译？"
    readonly property string actionStopConfirmOk: "停止并清空缓存"
    readonly property string actionStopConfirmCancel: "继续翻译"

    // ---- 工作台状态词（与 TaskControlPanel.workbenchState 对应）----
    readonly property string stateRunning: "翻译运行中"
    readonly property string stateReady: "可以开始"
    readonly property string stateEmpty: "等待文件"
    readonly property string stateRunningDetail: "正在处理文本块"
    readonly property string stateIdleDetail: "等待开始"

    // ---- 文件选择 ----
    readonly property string dialogPickSource: "选择 EPUB 文件"
    readonly property string dialogSaveOutput: "保存翻译后的 EPUB"
    readonly property string filterEpub: "EPUB 文件 (*.epub)"
}
