﻿# EPUB 日译中翻译工具

一个基于大模型 API 的日文 EPUB 自动翻译工具，提供桌面 GUI，支持将日文 EPUB 翻译为简体中文，并尽量保留原书结构（目录、链接、章节）。

## 功能概览

- EPUB 正文翻译（段落、标题、列表、引用等常见标签）
- 目录（NCX）标题翻译
- 超链接结构保留（保留 `href`，替换文本）
- Ruby 注音处理（提取正文语义，去除注音标签干扰）
- 图片占位文本过滤（避免误翻）
- 翻页方向设置（中文习惯 / 保持原版）
- 缓存机制（减少重复翻译）
- 术语表支持（`glossary.json`）
- 多线程批量翻译

## 新增能力（v1.5）

- 新增服务提供方选择：`DeepSeek` / `Sakura` / `Gemini` / `Custom`
- 新增可编辑配置：`Base URL`、`Model`
- 输入 EPUB 后自动预估可翻译字符数（异步，不阻塞 UI）
- 新增“导入术语表 JSON”按钮（覆盖写入前自动备份）
- 新增“自动提取术语（实验）”开关
- 注意：开启自动术语提取会显著增加 token 消耗，请谨慎使用
- 批量结构化返回升级为 JSON 对象：`translations + new_terms`
- 启用术语提取时：自动清洗、去重并增量写入 `glossary.json`
- 增强 JSON 解析容错（兼容代码块包裹和前后噪声）
- 增强错误处理：对 HTTP 502 快速中断
- 状态统计增强：成功率、JSON 成功率、回退率、JSON 失败计数、API 请求数、新增术语数
- 新增文件日志：`~/.epub_translator/logs/app-YYYYMMDD.log`

## 环境要求

- Python 3.8+
- tkinter（通常随 Python 安装）
- 依赖见 `requirements.txt`

## 安装

```bash
pip install -r requirements.txt
```

## 使用方法

### 启动 GUI

```bash
python app.py
```

### 基本步骤

1. 选择输入 EPUB
2. 确认输出路径
3. 选择服务提供方（DeepSeek / Sakura / Gemini / Custom）
4. 设置 API Key（Sakura 默认可留空，会使用 `sk-local`）
5. 检查 `Base URL` 与 `Model`
6. 选择翻页方向
7. 点击“开始翻译”

## API Key 与后端说明

- `DeepSeek`：
  - 默认 URL：`https://api.deepseek.com/chat/completions`
  - 默认模型：`deepseek-chat`
  - 需要 API Key
- `Sakura`（本地/自建 OpenAI 兼容服务）：
  - 默认 URL：`http://127.0.0.1:8080/v1/chat/completions`
  - 默认模型：`sakura-v1.0`
  - API Key 可留空（程序会使用 `sk-local`）
- `Gemini`（OpenAI 兼容入口）：
  - 默认 URL：`https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
  - 默认模型：`gemini-2.5-pro`
  - 需要 API Key
- `Custom`：
  - 需自行填写可用的 `Base URL`、`Model`、API Key

## 环境变量

可选：预先设置 DeepSeek Key，减少手动输入。

```bash
# Windows
set DEEPSEEK_API_KEY=your-api-key

# Linux/macOS
export DEEPSEEK_API_KEY=your-api-key
```

## 术语表

默认路径：`~/.epub_translator/glossary.json`

示例：

```json
{
  "勇者": "勇者",
  "魔王": "魔王",
  "魔法少女": "魔法少女"
}
```

## 缓存与日志

- 缓存：`~/.epub_translator/cache.json`
- 日志：`~/.epub_translator/logs/app-YYYYMMDD.log`

## 项目结构

- `app.py`：GUI 主程序
- `translator.py`：翻译核心逻辑（API 调用、批处理、缓存、术语处理）
- `epub_io.py`：EPUB 读写、目录与翻页设置
- `requirements.txt`：依赖清单

## 注意事项

- 大文件翻译耗时较长，请耐心等待
- 建议翻译后在阅读器中检查排版与章节跳转
- 若使用自建/代理网关，请确认接口兼容 `chat/completions`

## 版本记录

### v1.5

- 多后端支持与模型/URL 可配置
- 字符预估、术语导入、实验性术语提取
- 批量 JSON 结构化翻译与容错增强
- 统计与日志增强
- 502 失败快速中断

### v1.4

- 实时统计面板
- 翻译耗时格式化显示

### v1.3

- GUI 线程安全修复
- EPUB 打包兼容性修复
- 加载异常处理增强

### v1.2

- 智能语言检测与文本分块
- 结构化批量翻译（早期版本）
- 连接复用与批量去重优化

### v1.1

- 目录翻译、超链接保留、Ruby 处理、图片占位过滤、翻页方向设置

### v1.0

- 基础翻译功能、缓存机制、术语表支持、GUI

## License

MIT License
