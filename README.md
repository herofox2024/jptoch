﻿﻿﻿﻿﻿<div align="center">

<img src="assets/logo.png" width="180" alt="AI日译中 EPUB 翻译器">

# AI日译中（EPUB）

基于大模型 API 的日文 EPUB 自动翻译工具，面向轻小说、推理小说、科幻小说等日文电子书场景，支持翻译、术语表、缓存续译、译后校对和 Windows 桌面安装包。

![Version](https://img.shields.io/badge/version-V4.0%20RC1-2f6f5f)
![UI](https://img.shields.io/badge/UI-PySide6%20%2B%20QML-203a43)
![Platform](https://img.shields.io/badge/platform-Windows-c47f2c)
![Status](https://img.shields.io/badge/status-release%20candidate-blue)

**当前候选主线：QML/V4.0 RC1**  
**稳定回退版：Qt V3.2.1**

</div>

---

## 文档导航

| 内容 | 说明 |
|------|------|
| [版本定位](#版本定位) | 当前主线、回退版、历史入口的维护策略 |
| [核心功能](#核心功能) | EPUB 翻译、术语表、缓存续译、译后校对 |
| [快速开始](#快速开始) | 安装包运行和源码运行方式 |
| [使用流程](#使用流程) | 从选择 EPUB 到生成中文 EPUB 的步骤 |
| [API 配置](#api-配置) | 支持的大模型供应商和免费版参数建议 |
| [翻译设置](#翻译设置) | 性能参数、小说风格、译后校对、术语表 |
| [缓存与续译](#缓存与续译) | 暂停、恢复、停止、换模型重译的行为说明 |
| [项目结构](#项目结构) | 当前代码目录和入口文件 |
| [打包说明](#打包说明) | PyInstaller 和 Inno Setup 打包命令 |
| [常见问题](#常见问题) | 限流、缓存、目录未翻译、启动慢等问题 |
| [版本记录](#版本记录) | V4.0 RC1 与历史版本摘要 |

---

## 版本定位

| 版本 | 入口 | 状态 | 说明 |
|------|------|------|------|
| QML/V4.0 RC1 | `experimental/qml_v4/main.py` | 当前候选主线 | 新功能优先进入该版本，已完成真实 EPUB 流程验证 |
| Qt V3.2.1 | `main_qt.py` | 稳定回退版 | 进入维护模式，只修 P0/P1 严重问题 |
| Tk 旧版 | `app.py` | 冻结兼容 | 仅保留兼容测试或阻断性修复 |

说明：`experimental/qml_v4/` 是历史目录名。V4.0 RC1 阶段暂不改目录，避免影响已有打包脚本、安装脚本和用户路径。

---

## 核心功能

- **EPUB 日译中**：翻译正文、标题、列表、引用等常见 HTML 内容，尽量保留原书结构。
- **目录与链接处理**：支持 NCX/nav 目录翻译、短文本书内目录链接翻译，并保留 `href` 跳转关系。
- **多大模型供应商**：支持 DeepSeek、豆包、Sakura、Gemini、智谱 GLM、文心一言和自定义 OpenAI 兼容接口。
- **缓存续译**：相同文本命中缓存后不重复请求 API，支持暂停后恢复翻译。
- **模型隔离缓存**：切换大模型后可避免直接复用旧模型译文，便于重新翻译。
- **术语表管理**：支持启用/禁用术语表、导入、增量导入、重复过滤、编辑、来源显示和自动提取。
- **译后校对**：检查日文残留、可疑译文和术语不一致，可展示原文、初译、校对后译文和触发原因。
- **小说风格 Prompt**：支持作品类型和叙事口吻设置，可用于初译和译后校对提示词。
- **状态监控**：展示实时进度、已翻译字数、总字数、预计剩余时间、速度、API 次数、Token 和失败数。
- **EPUB 兼容增强**：对 `body/br` 排版 EPUB、短目录页、Ruby 注音和图片占位文本做了兼容处理。
- **Windows 安装包**：支持 onedir 瘦身打包，并可通过 Inno Setup 制作安装程序。
- **Toast 通知 (P0)**：非阻塞浮层消息，操作完成/失败/警告即时反馈。
- **翻译管线 (P1)**：Pipeline 阶段抽象，风格检测等步骤可独立开关配置。
- **服务容器 (P1)**：ServiceContainer 依赖注入，分阶段初始化，统一管理后端实例。
- **运行时主题切换 (P2)**：ThemeRegistry 主题注册表，切换时平滑过渡 + Toast 通知。

---

## 快速开始

### 方式一：使用安装包

已打包的 RC1 安装程序位于：

```text
dist/installer/AI日译中(EPUB)V4.0 RC1 安装程序.exe
```

安装后从开始菜单或桌面快捷方式启动即可。

### 方式二：从源码运行 QML/V4.0 RC1

```powershell
pip install -r experimental/qml_v4/requirements.txt
python experimental/qml_v4/main.py
```

### 方式三：运行稳定回退版 Qt V3.2.1

```powershell
pip install -r requirements.txt
python main_qt.py
```

### 方式四：历史 Tk 入口

```powershell
python app.py
```

Tk 入口已冻结，不建议日常使用。

---

## 使用流程

1. 打开软件，进入「任务」页。
2. 拖入或选择需要翻译的日文 EPUB。
3. 确认输出 EPUB 路径。
4. 进入「API」页，选择服务提供方，填写 API Key、Base URL 和模型名。
5. 进入「设置」页，选择性能参数、小说风格、是否启用译后校对。
6. 如需固定专有名词，进入「术语表」页启用术语表并导入或编辑术语。
7. 回到「任务」页点击开始翻译。
8. 在「状态」页查看实时进度、预计剩余时间、速度、API 次数和校对详情。
9. 翻译完成后，用 EPUB 阅读器检查目录、章节跳转和排版。

---

## API 配置

| 供应商 | 默认用途 | 说明 |
|--------|----------|------|
| DeepSeek | 推荐主力翻译 | 速度和质量较稳定，适合长篇 EPUB |
| 豆包 Doubao | 通用翻译 | 需要火山引擎 API Key |
| Sakura | 本地/自建服务 | 兼容 OpenAI `chat/completions` 的本地服务 |
| Gemini | 免费/付费 API | 免费版容易限流，部分参数不支持 `thinking` 字段 |
| 智谱 GLM | 免费/付费 API | 免费版限流明显，建议低并发小批量 |
| 文心一言 | 兼容供应商 | 需填写可用 API Key、Base URL 和模型名 |
| Custom | 自定义接口 | 适合代理网关或其他 OpenAI 兼容服务 |

### 免费版参数建议

免费模型通常不是不能用，而是并发和批量必须保守：

| 场景 | 并发数 | 批量大小 | 单条字符上限 | 批量总字符 | 超时 |
|------|--------|----------|--------------|------------|------|
| 智谱 GLM 免费版 | `1` | `2-3` | `200` 左右 | `200` 左右 | `300` 秒 |
| Gemini 免费版 | `1` | `2-3` | `200` 左右 | `200` 左右 | `300` 秒 |
| DeepSeek 付费版 | 可提高 | 可提高 | 可提高 | 可提高 | 按网络情况调整 |

注意：Gemini 免费版即使使用与智谱 GLM 相同的保守参数，也可能触发 API 限流。长篇 EPUB 建议优先使用付费大模型。

---

## 翻译设置

### 性能参数

V4.0 RC1 支持 Slider + SpinBox 精确调节，并提供模型参数预设。

| 参数 | 作用 | 建议 |
|------|------|------|
| 并发数 | 同时请求 API 的任务数量 | 免费模型填 `1`，付费模型按限额提高 |
| 批量大小 | 每次请求合并的文本条数 | 免费模型 `2-3`，付费模型可更高 |
| 单条字符上限 | 单个文本块过长时的切分阈值 | 长句多的小说可适当提高 |
| 批量总字符 | 单次批量请求最大字符数 | 免费模型保守，付费模型按稳定性调整 |
| API 超时 | 单次请求等待时间 | 网络慢或免费模型建议 `300` 秒 |

### 小说风格 Prompt

当前支持两类设置：

- **作品类型**：自动识别、通用小说、推理小说、科幻小说、幻想/异世界。
- **叙事口吻**：自动识别、中性叙事、轻小说风格、文学叙事。

风格设置会影响初译和译后校对的提示词。自动识别基于书名、目录和样本文本做本地判断，不额外消耗 API Token。

### 译后校对

译后校对用于质量修复，不是无限制自由润色。当前重点检查：

- 是否存在日文残留。
- 专有名词是否与术语表不一致。
- 初译是否明显漏译或格式异常。
- 校对后译文是否保留原意。

如果使用免费模型做校对，翻译时间和 Token 消耗都会增加，并且更容易遇到限流。

### 术语表

默认术语表路径：

```text
~/.epub_translator/glossary.json
```

术语表示例：

```json
{
  "能面島": "能面岛",
  "女学生探偵シリーズ": "女学生侦探系列",
  "魔王": "魔王"
}
```

术语表页面支持：

- 启用/禁用术语表。
- 导入术语表 JSON。
- 增量导入并过滤重复项。
- 直接编辑术语内容。
- 显示来源：自动提取、手动导入、未知来源。

---

## 缓存与续译

默认缓存路径：

```text
~/.epub_translator/cache.json
```

行为说明：

- 点击「暂停」后，当前已经完成的译文会保留，后续可点击「恢复」继续。
- 点击「停止」用于结束当前任务，并清空本次 UI 中的实时翻译状态。
- 已写入缓存的文本下次会直接命中，不重复请求 API。
- 如果想换大模型重新翻译，需要使用模型隔离缓存或清理对应缓存，否则相同文本可能继续复用旧译文。
- 遇到 429 限流时，可以降低并发/批量后重新开始，已翻译内容会优先命中缓存。

日志路径：

```text
~/.epub_translator/logs/app-YYYYMMDD.log
```

---

## 项目结构

```text
.
├─ experimental/qml_v4/        # QML/V4.0 RC1 当前候选主线
│  ├─ main.py                  # V4 启动入口（PySide6 + QML）
│  ├─ qml/                     # QML 页面与主题
│  │  ├─ main.qml              # 主窗口（导航栏、页面切换、主题绑定）
│  │  ├─ AppPalette.qml        # 全局调色板（Light/Dark/Glass 三态响应式）
│  │  ├─ pages/                # 5 个功能页面
│  │  │  ├─ TaskPage.qml       # 任务页（EPUB 拖入、开始/暂停/停止）
│  │  │  ├─ MonitorPage.qml    # 状态页（进度、统计、校对详情）
│  │  │  ├─ ApiConfigPage.qml  # API 配置页（供应商、Key、连接测试）
│  │  │  ├─ GlossaryPage.qml   # 术语表页（CRUD、导入导出、搜索筛选）
│  │  │  └─ OptionsPage.qml    # 设置页（性能、风格、校对、主题）
│  │  └─ components/           # 可复用组件
│  │     ├─ Toast.qml          # Toast 通知浮层（P0 新增）
│  │     └─ ThemeRegistry.qml  # 主题注册表工具（P2 新增）
│  ├─ backend/                 # Python-QML 桥接层
│  │  ├─ config_bridge.py      # 配置桥接（Qt Property → QML 绑定）
│  │  ├─ translate_bridge.py   # 翻译桥接（QThread Worker + Pipeline）
│  │  ├─ glossary_bridge.py    # 术语表桥接（QAbstractListModel）
│  │  ├─ toast_bridge.py       # Toast 信号桥接（P0 新增）
│  │  ├─ pipeline.py           # 翻译管线阶段抽象（P1 新增）
│  │  └─ service_container.py  # 服务容器依赖注入（P1 新增）
│  ├─ assets/                  # V4 图标资源
│  └─ EPUBTranslator*.spec     # PyInstaller 打包配置
├─ ui/qt_app.py                # Qt V3.2.1 回退版 UI
├─ main_qt.py                  # Qt V3.2.1 启动入口
├─ app.py                      # Tk 历史兼容入口，冻结维护
├─ translator.py               # 翻译核心：API、批处理、缓存、术语、校对
├─ epub_io.py                  # EPUB 读取、写入、目录和排版兼容
├─ style_detector.py           # 小说类型和叙事风格本地识别
├─ glossary_store.py           # 术语表加载、保存、合并、去重
├─ cache_store.py              # 缓存和 JSON 原子写入
├─ text_utils.py               # 文本可翻译性判断
├─ installer/                  # Inno Setup 脚本
└─ tests/                      # 回归测试
```

### 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                      QML UI 层 (PySide6)                      │
│  TaskPage  MonitorPage  ApiConfigPage  GlossaryPage  Options  │
│    │  │        │              │              │           │    │
├────┼──┼────────┼──────────────┼──────────────┼───────────┼────┤
│    │  │        │              │              │           │    │
│    ▼  ▼        ▼              ▼              ▼           ▼    │
│  TranslateBridge  GlossaryBridge  ConfigBridge  ToastBridge  │
│  ┌─────────────┐ ┌────────────┐ ┌──────────┐ ┌───────────┐  │
│  │QThread      │ │QListModel  │ │Qt Props  │ │Signal     │  │
│  │Worker.run() │ │CRUD        │ │Save/Load │ │info/succ/ │  │
│  │             │ │            │ │          │ │warn/err   │  │
│  └──────┬──────┘ └─────┬──────┘ └────┬─────┘ └─────┬─────┘  │
├─────────┼──────────────┼─────────────┼─────────────┼────────┤
│         ▼              ▼             ▼             ▼        │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Python 业务逻辑层                        │    │
│  │                                                      │    │
│  │  ┌─────────────────┐  ┌──────────────────────────┐  │    │
│  │  │ ServiceContainer│  │  TranslationPipeline     │  │    │
│  │  │ (P1 新增)       │  │  (P1 新增)               │  │    │
│  │  │ init_light()    │  │  StyleDetectStage        │  │    │
│  │  │ init_heavy()    │  │  CacheLookupStage (可选)  │  │    │
│  │  │ get_translator()│  │  TranslateStage  (可选)  │  │    │
│  │  └─────────────────┘  │  ProofreadStage  (可选)  │  │    │
│  │                       └──────────────────────────┘  │    │
│  │                                                      │    │
│  │  ┌──────────────────────────────────────────────┐    │    │
│  │  │           JaZhTranslator (核心引擎)            │    │    │
│  │  │  translate_batch()                            │    │    │
│  │  │  ┌─────────────────────────────────────────┐ │    │    │
│  │  │  │ 缓存查找 → 分批 → API调用(7家LLM)        │ │    │    │
│  │  │  │ 术语替换 → 质检 → 校对修复 → 术语提取    │ │    │    │
│  │  │  │ → 进度/统计/校对详情 实时信号发射         │ │    │    │
│  │  │  └─────────────────────────────────────────┘ │    │    │
│  │  └──────────────────────────────────────────────┘    │    │
│  │                                                      │    │
│  │  ┌──────────────────┐  ┌─────────────────────────┐  │    │
│  │  │   epub_io.py     │  │   Supporting Modules    │  │    │
│  │  │  load / save     │  │  style_detector.py      │  │    │
│  │  │  iter_text_nodes │  │  glossary_store.py      │  │    │
│  │  │  extract_toc     │  │  cache_store.py         │  │    │
│  │  └──────────────────┘  └─────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              外部 API 层                              │    │
│  │  DeepSeek | Doubao | Sakura | Gemini | GLM | Wenxin │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 翻译流程（从点击到完成）

```
用户点击"开始翻译"
    │
    ▼
TaskPage.tbridge.startTranslation(cfg)
    │ Slot("QVariant")
    ▼
TranslateBridge._make_config() → 参数校验 → ToastBridge.info("正在加载...")
    │ 创建 _TranslateWorker + QThread
    ▼
_TranslateWorker.run() [QThread 中执行]
    │
    ├─ ① EPUB 解析: load_book() → iter_text_nodes() → extract_toc_titles()
    ├─ ② 文本提取: 遍历 HTML → is_translatable() 筛选 → all_texts[]
    ├─ ③ 风格检测: StyleDetectStage → detect_novel_style() (P1 管线阶段)
    ├─ ④ 创建翻译器: JaZhTranslator(provider, model, glossary, proofread...)
    ├─ ⑤ 预估时间: _estimate_translation_duration()
    ├─ ⑥ 批量翻译: translator.translate_batch(all_texts)
    │     └─ 缓存命中 → 分批 → ThreadPoolExecutor → LLM API
    │         └─ 术语替换 → 质检 → 校对 → 术语提取 → 缓存保存
    │         └─ 实时信号: progressChanged / statUpdate / itemTranslated / proofreadDetail
    ├─ ⑦ 结果回写: 译文 → HTML 标签替换
    ├─ ⑧ 目录翻译: apply_toc_translations()
    ├─ ⑨ 保存 EPUB: save_book() + 智能文件名
    └─ ⑩ 完成: finished.emit() → ToastBridge.success("翻译完成!") + TTS 语音

暂停: cancel_event.set() → 当前批次完成后等待 → resumeTranslation() 新线程继续
停止: cancel_event.set() + discard_cache_writes() → 清理本次缓存
```

### 信号流向（Python ↔ QML）

```
Python 端信号                    QML 端接收
═══════════════                 ═══════════
progressChanged(completed,total,chars) → MonitorPage 进度条
statUpdate(10个统计参数)        → MonitorPage 统计面板
itemTranslated(src,dst)         → MonitorPage 实时译文滚动
proofreadDetail(7个校对参数)    → MonitorPage 校对详情列表
proofreadStyleDetected(4个参数) → MonitorPage 风格标识
statusChanged(msg)              → MonitorPage 状态文字
finished(out_path)              → TaskPage 按钮恢复
failed(err)                     → TaskPage 错误提示

ToastBridge.showInfo(msg)       → Toast 蓝色浮层 (P0)
ToastBridge.showSuccess(msg)    → Toast 绿色浮层 (P0)
ToastBridge.showWarning(msg)    → Toast 橙色浮层 (P0)
ToastBridge.showError(msg)      → Toast 红色浮层 (P0)

ConfigBridge.theme              → AppPalette 颜色响应式更新 (P2)
  └─ onThemeChanged             → Toast 通知 + 保存磁盘
```

---

## 打包说明

### PyInstaller onedir 瘦身打包

```powershell
python -m PyInstaller experimental\qml_v4\EPUBTranslator_onedir_slim.spec --noconfirm
```

输出目录：

```text
dist/AI日译中(EPUB)V4.0 RC1_slim/
```

### Inno Setup 安装包

使用 Inno Setup 6 编译 `installer/EPUB日译中V4.0_slim.iss`。

常见路径：

```powershell
& "C:\Users\HUAWEI\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "installer\EPUB日译中V4.0_slim.iss"
```

输出安装包：

```text
dist/installer/AI日译中(EPUB)V4.0 RC1 安装程序.exe
```

---

## 常见问题

### 为什么启动比较慢？

QML/PySide6、EPUB 解析、配置加载和 Python 运行时初始化都会增加启动时间。V4 已做过优化：启动动画、页面懒加载、术语表延迟加载、重模块延迟导入。首次启动仍可能比普通原生软件慢。

### 为什么免费模型经常 429 或超时？

免费 API 通常有请求频率、并发、Token 和每日额度限制。把并发降到 `1`，批量降到 `2-3`，单条字符和批量总字符控制在 `200` 左右，再重试。

### 为什么换了大模型，输出还是旧译文？

通常是缓存命中导致。相同原文如果已经缓存，下次会直接复用译文。需要使用模型隔离缓存或清理旧缓存后再翻译。

### 为什么目录页还有日文？

部分 EPUB 的目录不是标准 NCX/nav，而是正文里的短链接列表。V4 已增加短书内目录链接翻译逻辑，但极端排版仍建议翻译后人工检查目录页。

### 为什么预估字符数很少？

有些 EPUB 使用 `body/br` 或非标准 HTML 排版，正文不在常见段落标签里。V4 已增加 fallback 提取逻辑，用于改善这类 EPUB 的字符统计和翻译覆盖。

### 为什么校对后和初译差不多？

校对目标是修复漏译、日文残留、术语错误和明显异常，不是默认大幅改写。如果初译已经可用，校对结果可能变化很小。

### API 报“响应缺少 choices 字段”是什么意思？

通常表示供应商返回的不是 OpenAI 兼容 `chat/completions` 格式，可能是 Base URL 填错、模型名不可用、鉴权失败、余额不足或供应商错误页。先检查日志中的完整响应。

---

## 回归建议

发布前建议至少跑三类 EPUB：

- 普通章节型 EPUB。
- `body/br` 或非标准排版 EPUB。
- 大术语表 EPUB，验证术语召回、缓存和速度。

每次回归重点检查：

- 输出 EPUB 能否打开。
- 目录和章节跳转是否正常。
- 第 1-10 页是否存在明显日文残留。
- 术语是否一致。
- 暂停、恢复、停止是否符合预期。
- 日志是否存在连续 API 错误。

---

## 版本记录

### V4.0 RC1

- QML/V4 从实验版调整为当前候选主线。
- README、启动标题、安装包命名统一为 `AI日译中(EPUB)V4.0 RC1`。
- **架构改造 (P0/P1/P2)**：引入 Toast 通知系统、翻译管线阶段抽象、服务容器依赖注入、运行时主题切换增强。
- 增加 iOS26 玻璃主题、深色主题修正、导航和状态页视觉优化。
- 增加启动动画、页面懒加载、术语表延迟加载和重模块延迟导入。
- 增加停止按钮、暂停恢复续译、状态页预计翻译时长/预计剩余时间。
- 增加文心一言供应商。
- 增加小说风格设置和本地风格识别，风格可影响初译和译后校对 Prompt。
- 增强 `body/br` 排版 EPUB 的字符统计和正文提取。
- 增强短目录页和书内 HTML 链接文本翻译。
- 提供 onedir 瘦身打包和 Inno Setup 安装包。

### Qt V3.2.1

- 作为稳定回退版保留。
- 已进入维护模式，仅修 P0/P1 严重问题。
- 保留 API 配置、术语表、缓存、暂停恢复、状态监控等成熟功能。

### 历史版本摘要

- V3.2 系列：Qt UI 主线阶段，完善术语表、缓存续译、校对详情、性能参数和安装包。
- V3.1 系列：引入 Qt 版本并逐步替代 Tk UI。
- V2.x 系列：完成多页面桌面 UI、状态监控和基础打包。
- V1.x 系列：完成 EPUB 翻译、API 调用、缓存、术语表和基础 GUI。

---

## License

本项目用于个人学习和本地 EPUB 翻译工作流。请遵守原书版权、API 服务商条款和所在地区法律法规。不要传播未授权的翻译成品。
