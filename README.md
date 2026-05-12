# EPUB 日译中翻译工具

基于 DeepSeek API 的日文 EPUB 电子书自动翻译工具，将日文 EPUB 翻译为简体中文。

## 安装

```bash
pip install -r requirements.txt
```

依赖：
- Python 3.8+
- tkinter（GUI，通常 Python 自带）
- requests、beautifulsoup4、ebooklib

## 使用方法

### 图形界面

```bash
python app.py
```

1. 选择输入的日文 EPUB 文件
2. 设置输出文件路径（自动生成）
3. 输入 DeepSeek API Key
4. 选择翻页方向：
   - **中文习惯（从左到右）** - 点击右侧翻下一页
   - **保持原版（从右到左）** - 点击左侧翻下一页
5. 点击"开始翻译"

### 环境变量

设置 `DEEPSEEK_API_KEY` 环境变量可免去手动输入 API Key：

```bash
# Windows
set DEEPSEEK_API_KEY=your-api-key

# Linux/macOS
export DEEPSEEK_API_KEY=your-api-key
```

## 功能特性

### 核心功能

- **智能文本提取** - 自动提取正文 `<p>`、`<h1>`-`<h3>`、`<li>`、`<blockquote>` 等标签内容
- **目录翻译** - 自动翻译 NCX 目录标题，保持章节导航功能
- **超链接保留** - 翻译时保留正文中的 `<a>` 超链接，目录页跳转功能正常
- **Ruby 注音处理** - 自动合并 Ruby 标签内容，翻译后去除日文注音
- **图片过滤** - 过滤图片占位符，避免误翻译

### 翻译质量

- **缓存机制** - 已翻译内容自动缓存，支持断点续传
- **术语表** - 通过 `glossary.json` 维护专有名词翻译一致性
- **长文本分块** - 自动按段落分割长文本，避免切断句子
- **批量并发** - 多线程并发翻译，提高效率

### 容错处理

- **API 重试** - 网络故障自动重试，支持速率限制处理
- **取消功能** - 翻译过程中可随时取消
- **损坏修复** - 自动修复 manifest 引用缺失文件等问题
- **目录修复** - 自动修复 uid 缺失的目录条目

### 阅读体验

- **翻页方向** - 可选择中文习惯（从左到右）或保持原版（从右到左）
- **语言标记** - 自动将 `dc:language` 更新为 `zh`

## 术语表

编辑 `~/.epub_translator/glossary.json` 添加术语条目：

```json
{
  "勇者": "勇者",
  "魔王": "魔王",
  "魔法少女": "魔法少女"
}
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `app.py` | 图形界面主程序 |
| `translator.py` | 翻译核心逻辑（DeepSeek API 调用、缓存、术语表） |
| `epub_io.py` | EPUB 文件读写、目录处理、翻页方向设置 |
| `glossary.json` | 术语表（项目目录） |
| `requirements.txt` | Python 依赖 |

缓存文件存储在 `~/.epub_translator/cache.json`。

## 翻译流程

```
输入 EPUB
    ↓
加载并解析
    ↓
提取文本内容 ──→ 过滤图片占位符
    ↓
提取目录标题
    ↓
批量并发翻译 ←── 术语表
    ↓
应用翻译结果
    ├── 正文：保留超链接结构
    ├── 目录：翻译 NCX 标题
    └── 设置：翻页方向、语言
    ↓
保存 EPUB
```

## 技术细节

### 超链接保留

原版目录页结构：
```html
<p><a href="chapter-1.html"><span>第一章</span></a></p>
```

翻译后：
```html
<p><a href="chapter-1.html">第一章 开篇</a></p>
```

超链接 `<a>` 标签的 `href` 属性被保留，仅替换文本内容。

### Ruby 注音

原版：
```html
<p>わたしの<ruby>浅羽<rt>あさば</rt></ruby>くん</p>
```

提取文本：`わたしの浅羽くん`（合并 Ruby 内容）

翻译后：
```html
<p>我的浅羽君</p>
```

Ruby 标签被移除，只保留翻译文本。

### 图片占位符

`\uFFFC` (￼) 是图片占位符，`get_text()` 会返回它。翻译前会过滤掉只包含占位符的文本，避免误翻译。

## 注意事项

- 需要 DeepSeek API Key（按使用量付费）
- 翻译大文件可能耗时较长，请耐心等待
- 首次翻译无缓存，后续相同内容会从缓存读取
- 建议翻译后用阅读器检查效果

## 更新日志

### v1.4
- **实时统计面板**：翻译过程中显示完整统计信息 - 进度、字符数、耗时、批量成功率、回退率、API 请求数
- **统计追踪系统**：新增 `get_stats()` 和 `_inc_stat()` 方法，追踪 API 请求、批量翻译成功率、回退次数等关键指标
- **UI 优化**：窗口尺寸调整为 780x340，状态标签支持自动换行（wraplength=700）
- **耗时显示**：新增 `_format_elapsed()` 方法，格式化显示翻译用时（MM:SS 或 HH:MM:SS）

### v1.3
- **GUI 线程安全修复**：将翻译线程中的界面更新（进度、状态、弹窗、按钮状态）统一切换到 Tk 主线程调度，降低运行中偶发卡死或崩溃风险。
- **EPUB 打包兼容性修复**：修复 `repair_epub()` 重打包细节，确保 `mimetype` 以未压缩方式写入并优先入包，提升不同阅读器兼容性。
- **加载异常处理增强**：`load_book()` 扩展损坏文件相关异常捕获（`KeyError`、`zipfile.BadZipFile`、`ValueError`、`OSError`），失败提示更稳定。
- **回归测试**：执行 `python -m unittest discover -s tests -v`，6 个测试全部通过。

### v1.2
- **智能语言检测** - 新增 `_is_translatable()` 方法，自动识别日文/中文内容，忽略纯数字和纯英文文本
- **智能文本分块** - 新增 `_smart_split_text()` 方法，按日文句号（。）分割长文本，避免生硬截断句子
- **结构化 JSON 响应** - 新增 `_call_deepseek_batch_json()` 方法，支持 API 返回结构化 JSON，减少分隔符解析失败
- **多超链接处理** - 支持一个标签内包含多个 `<a>` 链接的复杂结构，正确保留目录跳转功能
- **优雅取消机制** - 使用 `threading.Event` 实现更流畅的取消操作，API 请求期间也能响应取消
- **连接复用** - 使用 `requests.Session()` 复用 HTTP 连接，提升批量翻译效率
- **翻译去重优化** - 批量翻译前去重，避免重复翻译相同内容

### v1.1
- 新增目录（NCX）标题翻译
- 新增超链接保留功能
- 新增 Ruby 注音处理
- 新增图片占位符过滤
- 新增翻页方向设置
- 修复 uid 缺失导致目录被清空的问题

### v1.0
- 基础翻译功能
- 缓存机制
- 术语表支持
- GUI 界面

## 许可证

MIT License

## DeepSeek + Sakura 双后端说明

项目已支持两种翻译后端，可在 GUI 中切换：

- `DeepSeek`：云端 API，默认 `Base URL = https://api.deepseek.com/chat/completions`，默认模型 `deepseek-chat`
- `Sakura`：本地/自建 OpenAI 兼容服务，默认 `Base URL = http://127.0.0.1:8080/v1/chat/completions`，默认模型 `sakura-v1.0`

### GUI 使用

1. 在“服务提供方”选择 `DeepSeek` 或 `Sakura`
2. 程序会自动填充对应默认 `Base URL` 与“模型名”
3. 如你的网关地址或模型名不同，可手动覆盖
4. 点击“开始翻译”

### API Key 规则

- 选择 `DeepSeek` 时：必须填写 API Key（或设置环境变量 `DEEPSEEK_API_KEY`）
- 选择 `Sakura` 时：可留空。程序内部会自动使用占位 Key `sk-local` 以兼容部分网关

### 环境变量（可选）

若你想免手动输入，可提前设置：

```bash
# Windows
set DEEPSEEK_API_KEY=your-api-key

# Linux/macOS
export DEEPSEEK_API_KEY=your-api-key
```

### 注意事项

- `Sakura` 模式依赖本地/自建服务先启动，并且接口需兼容 `chat/completions`
- 若使用反向代理或第三方网关，请确认 `Base URL` 与模型名与服务端配置一致
- 当前界面标题仍显示 `EPUB 日译中 (DeepSeek)`，但功能上已经支持双后端切换


## �����޸ģ�v1.5��

### 1) �����������ģ��
- ���������ṩ��ѡ��`DeepSeek` / `Sakura` / `Gemini` / `�Զ���`
- �����ɱ༭������`Base URL`��`ģ����`
- ������֧�� provider + api_url + model ���Σ�֧���Զ���ȫ `/chat/completions` �˵�
- `Sakura` ģʽ�� Key ʱ�Զ�ʹ��ռλ `sk-local`��`DeepSeek/Gemini/Custom` ����Ҫ�� API Key

### 2) GUI ������ǿ
- ���ڳߴ����Ϊ `920x460`����С `760x420`��
- ���� EPUB ���Զ�Ԥ���ɷ����ַ������첽���㣬���������棩
- ���������������JSON����ť��֧��һ��������������Զ����ݾ��ļ�
- �������Զ���ȡ���ʵ�飩������

### 3) ������·���ȶ����Ż�
- �����ṹ����������Ϊ JSON ����`translations + new_terms`
- �����Զ���ȡ����ʱ��֧������������������ϴ��ȥ�ز�����д�� `glossary.json`
- ��ǿ JSON �����ݴ������ݴ���������ǰ�������ı�
- ���� 502 ��������ж��߼���������Ч����
- ��������С�� `4` ����Ϊ `5`

### 4) ͳ������־
- ͳ����������`batch_delimiter_success`��`batch_json_parse_fail`��`glossary_new_terms_added`
- ״̬��չʾ��ǿ���ܳɹ��ʡ�JSON �ɹ��ʡ������ʡ�JSON ʧ�ܴ�����API ������������������
- �����ļ���־�����`~/.epub_translator/logs/app-YYYYMMDD.log`

### 5) ������˵��
- ���θĶ���Ҫ�漰 `app.py` �� `translator.py`
- ����������������Ŀ¼ `_tmp_manga_translator_ui/` �� JSON �ļ� `wenku_6590ff1cf1b791665f9886c4.json`����ǰδ���������̣�
