# 更新日志

本文件用于 GitHub 自动发布说明。

发布新版本前，在这里新增对应版本小节，例如 `## v4.1.2`。GitHub Actions 会自动读取该小节，并追加提交摘要后写入 Release 页面。

## v4.2.2
- 移除无引用的 cache_store.py，原子写入能力统一由 translation_cache.py 提供
- request_log.py 从 backend 包提升到项目根目录，核心引擎不再依赖 QML 后端
- 补充 .gitignore 规则，覆盖率与测试缓存产物不再入库
- 发布工作流增加 pytest 全量回归和 QML 冒烟测试，测试失败阻断打包
- 同步 app_info.py、README、README_EN 版本号至 V4.2.2
- 引入 ruff 静态检查，配置见 pyproject.toml（仅启用 Pyflakes F 与语法级 E9）
- 修复 style_detector.py 历史推理关键词表中重复字典键导致的词条丢失
- 清理 10 处未使用导入与 7 处未使用变量
- 发布工作流增加 ruff 检查步骤，失败阻断打包
- 统一 Python 版本到 3.12：CI 打包环境、.python-version、ruff 目标版本三者一致
- 新增 tests/test_python_version_alignment.py 守护版本一致性并拒绝预发布解释器
- 补充 .gitignore 虚拟环境规则与 pyproject.toml 的 pytest 配置段
- 批量翻译提示词新增中文表达质量约束（避免日式直译、保留转折语气、动作描写准确），模板见 dict/system_prompt_hq_format.yaml，并对旧版自定义模板做兜底追加
- 新增译后润色档 enable_polish（默认关闭）：检测翻译腔、语气缺失、感官动词不足，复用校对 provider 二次润色
- 新增 tests/test_translation_polish.py 覆盖润色检测逻辑与开关行为
- 修复窗口标题与版权提示页的版本号硬编码：统一由 backend/app_info.py 注入 AppDisplayName，避免发版后仍显示旧版本
- 新增窗口级快捷键：Ctrl+Enter 开始翻译、Ctrl+P 暂停、Ctrl+R 恢复、Ctrl+Shift+X 停止、Ctrl+1/2/3 切换页面
- AppStyle 新增圆角与边框 token（radiusTiny/Chip/Button/Field/Card/Dialog/Pill、borderWidthHairline/Emphasis、borderSubtle）
- 拆分 ApiConfigPage：模型/Prompt 预设弹窗与 Hy-MT2 本地模型弹窗抽成 ApiModelPresetDialog / ApiLocalModelDialog 组件，页面从 1252 行降到 588 行
- 新组件通过属性与信号与宿主页面通信，不直接依赖全局桥接对象，便于单独预览和复用
- 拆分 OptionsPage：性能参数与性能预设抽成 OptionsPerformancePane 组件，页面从 1191 行降到 983 行
- 补充无障碍支持：TaskActionButton 增加 Accessible 角色/名称/描述与键盘激活（Enter/空格），支持 Tab 聚焦并显示聚焦描边；MonitorPage 进度条与 ApiConfigPage 表单控件补充可读名称
- 修复 TaskActionButton 之前无法用键盘操作的问题
- 界面改为 macOS 视觉风格：系统蓝 #007AFF 强调色、分组灰 #F2F2F7 背景、系统级成功/警告/危险色，深浅两套对齐 Apple 系统色板
- 圆角体系放大为 Apple 风格：面板 16、卡片 12、数组件 8；AppStyle 圆角 token 同步上调
- 字体改为无衬线优先（SF Pro / PingFang SC → 微软雅黑），标题不再使用宋体，靠字重区分层级
- 窗口标题栏配色同步新调色板；Material 主题明暗判定改由 AppPalette.dark 驱动，修复半透明主题下控件色偏
- 主题名称更新为「浅色 / 深色 / 毛玻璃」
- 修复启动画面未适配主题：改为在创建前直接读取 config.json 的 theme，按浅色/深色/毛玻璃分别渲染卡片、文字与渐变进度条，移除原有绿色硬编码
- 启动画面细节对齐 Apple 风格：卡片圆角 18px、进度条改为蓝色横向渐变、阴影更柔和
- 新增「关于」入口：窗口顶部工具条右侧显示「关于 v4.2」，点击打开弹窗查看显示版本、内部版本、Python 与 Qt 运行环境、项目链接与版权说明
- 关于弹窗支持键盘操作（Tab 聚焦、Enter/空格打开）与无障碍标签
- 新增顶部工具条 AppTopBar：在系统原生标题栏之下留出 44px 轻量工具条承载全局入口，不影响窗口拖拽与最小化/最大化行为
- 导航栏「项目与联系」卡片恢复原有高度，仅保留 GitHub 与 Email


## v4.2.1
- 移除冗余进度值属性并调整布局
- 重构Windows标题栏主题适配逻辑
- 新增 navigateToGlossary 信号用于跳转到术语表页面
- 新增 isTranslationBusy 函数用于判断是否处于翻译操作中
- 补充术语任务的功能说明、使用流程以及进度分离的相关细节，更新了术语表的使用步骤，新增术语任务独立进度的相关文档说明和冒烟测试的补充解释


## v4.2.0
- 统一内容审核错误判定逻辑
- 重构限流与默认参数管理
- 新增通用组件与工具类，重构术语表与导航逻辑
- 新建NoticePageDialog.qml弹窗组件用于版权提示页管理
- 在qmldir中注册新增的弹窗组件
- 重构OptionsPage中的弹窗代码，替换为封装好的NoticePageDialog
- 抽离弹窗组件到独立文件并重构选项页逻辑
- 增两个QML组件：GlossaryProfileSection和TableHeader，同时更新qmldir注册这两个新组件
- 完成UI优化与组件复用重构
- 移除顶部header栏布局


## v4.1.9

- 新增内容审核拦截处理与统计逻辑
- 新增ContentModerationError异常处理，实现多批次内容审核失败时自动拆分为单条重试
- 新增术语提取过程中的审核跳过计数逻辑
- 在qml后端和主翻译器中添加审核跳过状态的传递与UI提示
- 新增对应测试用例验证审核拦截处理流程
- 新增日语助词边界处理规则，添加单元测试覆盖粒子剥离场景
- 重构术语去重逻辑，按原词合并重复译法并处理别名与分类
- 更新提示词与过滤逻辑，新增Creature分类支持与精简模式说明

- 补充aliases字段格式规范与实际使用逻辑
## v4.1.8
- 新增多项功能并优化日文翻译处理流程
- 重构翻译流水线，使用清洗后的标题更新EPUB元数据并智能重命名输出文件
- 修复 EPUB 内部书名元数据没有同步翻译的问题。
- 优化 GitHub 自动发布说明生成流程。
- 新增发布说明自动读取 CHANGELOG 的功能。

## v4.1.1

- 补强 QML/V4 翻译任务持久化、请求日志、失败块恢复、日文残留策略、模型与 Prompt 预设、后端 pipeline、EPUB fixture 测试和 UI 信息架构。
- 增强 Hy-MT2 本地模型接入，支持 llama-server 外部模式和本地模型参数预设。
- 优化保存前日文残留诊断，降低谜题假名、专名、振假名等场景的误阻塞。
- 修复 EPUB 保存、版权提示页、目录标题污染、运行日志清空、书名元数据等问题。

