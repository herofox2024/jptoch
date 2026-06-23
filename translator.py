import json
import logging
import os
import random
import re
import hashlib
import sys
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests
from glossary_store import normalize_glossary_payload as gs_normalize_glossary_payload
from glossary_store import merge_glossaries as gs_merge_glossaries
from glossary_store import clean_new_terms as gs_clean_new_terms
from glossary_store import select_glossary_entries as gs_select_glossary_entries
from glossary_store import build_glossary_text as gs_build_glossary_text
from glossary_store import rebuild_glossary_index as gs_rebuild_glossary_index
from glossary_store import has_valid_glossary_match as gs_has_valid_glossary_match
from style_detector import GENRE_LABELS, TONE_LABELS


# ---------------------------------------------------------------------------
# 结果数据类：用于 _call_deepseek_single / _call_deepseek_batch_json 返回
# ---------------------------------------------------------------------------
@dataclass
class SingleChunkResult:
    """单条翻译 API 调用结果"""
    content: str
    finish_reason: Optional[str] = None   # "stop", "length", or None
    is_truncated: bool = False


@dataclass
class BatchJsonResult:
    """批量 JSON 翻译 API 调用结果（支持部分成功）"""
    translations: Optional[List[Optional[str]]] = None  # None=全部失败; 有 None 槽=部分成功
    new_terms: Optional[List[Dict[str, Any]]] = None
    missing_indices: List[int] = field(default_factory=list)
    finish_reason: Optional[str] = None
    is_truncated: bool = False
    raw_content: str = ""


# YAML 模块延迟加载（可选依赖）
_yaml_module = None
_yaml_available = None


def _get_yaml():
    """延迟加载 yaml 模块，避免启动时报错"""
    global _yaml_module, _yaml_available
    if _yaml_available is None:
        try:
            import yaml
            _yaml_module = yaml
            _yaml_available = True
        except ImportError:
            _yaml_available = False
            logging.warning("PyYAML not installed. YAML prompt templates will not be supported. Install with: pip install pyyaml")
    return _yaml_module if _yaml_available else None

logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL = "Doubao-Seed-1.6-flash"
SAKURA_API_URL = "http://127.0.0.1:8080/v1/chat/completions"
SAKURA_MODEL = "sakura-v1.0"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = "gemini-2.5-flash"
GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODEL = "glm-4-flash"
WENXIN_API_URL = "https://qianfan.baidubce.com/v2/chat/completions"
WENXIN_MODEL = "ernie-4.5-turbo-128k"
DEFAULT_TEXT_SEPARATOR = "\n---SPLIT---\n"


class FastFailError(RuntimeError):
    """用于标识应立即中断流程的不可恢复错误（如明确配置的 HTTP 502）。"""


class TranslationIncompleteError(RuntimeError):
    """Raised when some texts could not be safely translated."""

    def __init__(
        self,
        failed_texts: Optional[List[str]] = None,
        residue_texts: Optional[List[str]] = None,
        partial_results: Optional[Dict[str, str]] = None,
    ):
        self.failed_texts = list(dict.fromkeys(failed_texts or []))
        self.residue_texts = list(dict.fromkeys(residue_texts or []))
        self.partial_results = dict(partial_results or {})
        message = (
            f"翻译未完成：{len(self.failed_texts)} 条未成功翻译，"
            f"{len(self.residue_texts)} 条疑似仍有日文残留。"
            "已保留成功译文缓存，请降低并发/批量或切换模型后恢复续译。"
        )
        super().__init__(message)


def get_data_dir() -> Path:
    """获取用户数据目录，用于存储缓存和配置"""
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(exist_ok=True)
    return data_dir


# 内置提示词模板（打包 exe 时项目 dict/ 不可用，自动释放到用户目录）
_BUILTIN_TEMPLATES = {
    "glossary_extraction_prompt.yaml": """\
# 术语提取规则模板 / Glossary Extraction Rules Template
# 使用方法：此文件定义术语提取的质量控制规则，拼接到系统提示词后

glossary_extraction_prompt: |
  **术语提取规则 (GLOSSARY EXTRACTION RULES):**

  **目标语言: {{{target_lang}}}**

  # 提取任务
  仅提取高度专有的专有名词（人名、地名、特殊技能等），需要跨章节保持一致翻译。

  # 规则与约束

  ## 1. 宁缺毋滥原则
  *   **不强制提取**：如果没有术语符合条件，返回 `"new_terms": []`。返回空数组完全正常。
  *   **不提取通用词**：不要提取普通名词、动词、形容词。
      *   例：❌ "学校"、"老师"、"美味"、"魔法"、"剑"、"魔王"
      *   例：✅ "UA高中"、"艾克斯卡利巴"、"龟派气功"
  *   **不提取模糊术语**：如果词可以直译（如"红龙"），除非是特定角色名，否则不提取。
  *   **有疑问则跳过**：如果不确定是否为专有名词，不提取。

  ## 2. 噪音清洗
  *   忽略 OCR 噪音或乱码
  *   跳过语法破碎的文本片段

  ## 3. 边界规范化
  *   移除敬称后缀：-san/-kun/-chan/-sama/-sensei 等
  *   提取核心词：如"The Holy Sword Excalibur"只提取"Excalibur"

  # 分类类别
  *   **Person**: 人物名（唯一角色名）
  *   **Location**: 地名（城市、商店、场所）
  *   **Org**: 组织/团体名
  *   **Item**: 传说/命名物品
  *   **Skill**: 特殊招式/魔法名
  *   **Creature**: 虚构生物/命名宠物

  # 数量控制
  *   每批最多返回 5 条术语
  *   宁缺毋滥，质量优先
""",
    "system_prompt_hq_format.yaml": """\
# 批量翻译输出格式模板 / Batch Translation Output Format Template
# 用于 _call_deepseek_batch_json 方法的系统提示词

system_prompt_base: |
  你是日文到中文翻译助手。
  请严格输出 JSON 对象，不要输出任何额外文字。

system_prompt_output_format: |
  JSON 顶层字段：
  1) "translations": 数组，长度必须与输入一致，索引顺序一致，元素格式 {"idx": 整数, "zh": "译文"}。
  2) "new_terms": 数组，元素格式 {"src": "原词", "dst": "译词", "category": "分类"}，没有则返回空数组。
     - category 可选值：Person, Location, Org, Item, Skill, Creature
     - 若无法确定分类，可省略 category 字段

system_prompt_no_extract: |
  当未启用术语抽取时，必须返回 "new_terms": []。

# 开启术语提取时的追加规则（会替换 {{{optional_extraction_rules}}} 占位符）
optional_extraction_rules: |
  术语抽取规则：
  - 仅提取专有名词或固定术语（人名/地名/组织/招式/装备等）
  - 不提取通用词、语气词、普通动词形容词
  - 每批最多返回 5 条，宁缺毋滥
  - 每条术语需指定 category 字段

# 完整模板（运行时组装）
system_prompt_template: |
  {{{system_prompt_base}}}
  {{{system_prompt_output_format}}}
  {{{optional_extraction_rules}}}
""",
}


def get_dict_dir() -> Path:
    """获取 dict/ 目录路径（存放提示词模板）

    开发模式（源码运行）：优先使用项目目录下的 dict/
    打包模式（PyInstaller exe）：使用用户数据目录，首次运行自动释放内置模板
    """
    is_frozen = getattr(sys, "frozen", False)

    if not is_frozen:
        # 开发模式：优先项目目录
        project_dict = Path(__file__).parent / "dict"
        if project_dict.exists():
            return project_dict

    # 打包模式或项目目录无 dict/：使用用户数据目录，自动释放内置模板
    data_dict = get_data_dir() / "dict"
    data_dict.mkdir(exist_ok=True)
    for filename, content in _BUILTIN_TEMPLATES.items():
        target = data_dict / filename
        if not target.exists():
            try:
                target.write_text(content, encoding="utf-8")
                logging.info(f"已释放内置模板: {target}")
            except Exception as e:
                logging.warning(f"释放内置模板失败 {target}: {e}")
    return data_dict


def load_prompt_template(dict_dir: Path, stem: str) -> Optional[Dict[str, Any]]:
    """
    加载提示词模板文件，优先级：.yaml > .yml > .json

    Args:
        dict_dir: dict/ 目录路径
        stem: 文件名（不含扩展名）

    Returns:
        解析后的字典，加载失败返回 None
    """
    for ext in ('.yaml', '.yml', '.json'):
        path = dict_dir / (stem + ext)
        if not path.exists():
            continue

        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()

            if ext in ('.yaml', '.yml'):
                yaml = _get_yaml()
                if yaml is None:
                    logging.warning(f"Cannot load YAML template {path}: PyYAML not installed")
                    continue
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)

            if isinstance(data, dict):
                logging.debug(f"Loaded prompt template from: {path}")
                return data
        except Exception as e:
            logging.warning(f"Failed to load prompt template {path}: {e}")

    return None


def resolve_template_vars(template: str, **kwargs) -> str:
    """
    替换模板中的 {{{var}}} 占位符

    Args:
        template: 模板字符串
        **kwargs: 变量键值对

    Returns:
        替换后的字符串
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{{{" + key + "}}}", str(value) if value is not None else "")
    return result


# 默认术语分类
DEFAULT_GLOSSARY_CATEGORIES = ["Person", "Location", "Org", "Item", "Skill", "Creature"]


PERFORMANCE_PRESETS = {
    "default": {
        "label": "默认",
        "description": "稳定安全，适合所有账户",
        "max_workers": 5,
        "batch_size": 4,
        "max_batch_length": 800,
        "max_text_size_for_batch": 200,
        "chunk_size": 1200,
    },
    "balanced": {
        "label": "适中",
        "description": "推荐配置，效率与稳定性兼顾",
        "max_workers": 12,
        "batch_size": 10,
        "max_batch_length": 4000,
        "max_text_size_for_batch": 600,
        "chunk_size": 2500,
    },
    "extreme": {
        "label": "极端",
        "description": "极限速度，高风险",
        "max_workers": 25,
        "batch_size": 15,
        "max_batch_length": 8000,
        "max_text_size_for_batch": 1000,
        "chunk_size": 4000,
    },
}


class JaZhTranslator:
    # 类常量：配置参数
    CACHE_SAVE_THRESHOLD = 20  # 缓存保存阈值，每 N 次更新后保存
    API_TIMEOUT = 120  # API 请求超时时间（秒）
    MAX_RETRIES = 3  # API 请求最大重试次数
    MAX_CONTINUATIONS = 2  # finish_reason=length 时最大续取次数

    # ---- Phase 1-③: 本地预翻译规则表（高频短句直接替换，跳过 API）----
    PRE_TRANSLATE_RULES: Dict[str, str] = {
        # 基本应答
        "はい": "是的",
        "いいえ": "不",
        "うん": "嗯",
        "ううん": "不是",
        "そう": "是的",
        "そうか": "是吗",
        "そうですね": "是啊",
        "なるほど": "原来如此",
        "もちろん": "当然",
        "もちろんです": "当然",
        "大丈夫": "没问题",
        "大丈夫です": "没关系",
        "大丈夫ですか": "没事吧",
        "よかった": "太好了",
        "よかったです": "太好了",
        "残念": "可惜",
        "残念です": "真遗憾",
        "仕方ない": "没办法",
        "仕方がない": "没办法",
        "気にしないで": "别在意",
        "気をつけて": "小心",
        # 问候
        "おはよう": "早上好",
        "おはようございます": "早上好",
        "こんにちは": "你好",
        "こんばんは": "晚上好",
        "おやすみ": "晚安",
        "おやすみなさい": "晚安",
        "さようなら": "再见",
        "じゃあね": "再见",
        "またね": "回头见",
        "また後で": "待会见",
        "いってきます": "我出门了",
        "いってらっしゃい": "路上小心",
        "ただいま": "我回来了",
        "おかえり": "欢迎回来",
        "おかえりなさい": "欢迎回来",
        # 感谢/道歉
        "ありがとう": "谢谢",
        "ありがとうございます": "谢谢",
        "ありがとうございました": "非常感谢",
        "どうも": "多谢",
        "すみません": "不好意思",
        "すいません": "不好意思",
        "ごめん": "抱歉",
        "ごめんなさい": "对不起",
        "ごめんね": "抱歉啊",
        "申し訳ありません": "非常抱歉",
        "申し訳ございません": "非常抱歉",
        # 用餐
        "いただきます": "我开动了",
        "ごちそうさま": "我吃好了",
        "ごちそうさまでした": "多谢款待",
        "おいしい": "好吃",
        "おいしいです": "很好吃",
        "うまい": "好吃",
        "まずい": "难吃",
        # 日常
        "お願いします": "拜托了",
        "お願い": "拜托",
        "お疲れ様": "辛苦了",
        "お疲れ様です": "辛苦了",
        "お疲れ様でした": "辛苦了",
        "頑張って": "加油",
        "頑張ります": "我会努力的",
        "頑張った": "努力了",
        "すごい": "好厉害",
        "すごいですね": "好厉害啊",
        "やった": "太好了",
        "やったー": "太好了",
        "やばい": "糟了",
        "まさか": "不会吧",
        "本当": "真的",
        "本当ですか": "真的吗",
        "嘘": "骗人",
        "嘘つき": "骗子",
        "さすが": "不愧是",
        "さすがです": "真不愧是",
        "わかった": "知道了",
        "わかりました": "明白了",
        "わからない": "不知道",
        "わかりません": "我不明白",
        "知らない": "不知道",
        "知りません": "不知道",
        "待って": "等等",
        "ちょっと待って": "稍等一下",
        "ちょっと": "稍等",
        "どうぞ": "请",
        "どうした": "怎么了",
        "どうしたの": "怎么了",
        "どうしましたか": "怎么了",
        "どうしよう": "怎么办",
        "大変": "糟糕",
        "大変です": "不得了",
        "やめろ": "住手",
        "やめて": "不要",
        "やめてください": "请住手",
        "助けて": "救命",
        "助けてください": "请救救我",
        "おめでとう": "恭喜",
        "おめでとうございます": "恭喜",
        "さあ": "来吧",
        "ええ": "嗯",
        "えっと": "那个",
        "あの": "那个",
        "あのさ": "那个啊",
        "ねえ": "喂",
        "おい": "喂",
        "ほら": "你看",
        "はいはい": "好好",
        "まあまあ": "还行",
        "さて": "那么",
        "さてと": "那么",
        "よし": "好",
        "よし！": "好！",
        "えっ": "诶",
        "ええっ": "诶诶",
        "ふん": "哼",
        "ふうん": "哼",
        "へえ": "哦",
        "へー": "哦—",
        "はあ": "哈",
        "はぁ": "唉",
    }

    # ---- Phase 1-①: 智能分批阈值 ----
    SMART_BATCH_SHORT = 30    # 短文本上限（称呼、语气词、短对话）
    SMART_BATCH_LONG = 200    # 长文本下限（整段叙述，单独处理）

    # ---- Phase 2-④: 上下文窗口翻译 ----
    ENABLE_CONTEXT_WINDOW = True   # 是否启用上下文窗口
    ENABLE_BATCH_ITEM_CONTEXT = False  # 批量 JSON 不默认给每条塞 prev/next，避免大幅增加 token
    CONTEXT_PREVIEW_LEN = 80       # 前后文预览最大字符数

    def _build_context_guidance(self, prev_text: Optional[str], next_text: Optional[str]) -> str:
        """构建上下文提示（仅附加到 user_prompt，不影响 system_prompt）。"""
        parts = []
        if prev_text:
            preview = prev_text[:self.CONTEXT_PREVIEW_LEN]
            parts.append(f"【前文上下文（仅供参考，帮助理解当前文本的语境，无需翻译）】\n{preview}")
        if next_text:
            preview = next_text[:self.CONTEXT_PREVIEW_LEN]
            parts.append(f"【后文上下文（仅供参考，帮助理解当前文本的语境，无需翻译）】\n{preview}")
        result = "\n\n".join(parts) if parts else ""
        if result:
            logger.debug(f"上下文窗口: 前文={bool(prev_text)}, 后文={bool(next_text)}, 长度={len(result)}")
        return result

    # ---- Phase 2-⑤: 校对分级 ----
    PROOFREAD_SKIP_PATTERNS: List[str] = [
        # 这些模式的译文通常不需要校对（标点、空行、纯数字等）
        r"^[、。！？…\s]*$",       # 纯标点/空白
        r"^\d+[%％]?$",            # 纯数字/百分比
        r"^[A-Za-z0-9\s]+$",      # 纯英文数字
        r"^[「」『』\s]*$",        # 纯引号
    ]

    # P3-⑥: 提供方默认 URL 映射
    _PROVIDER_URLS: Dict[str, str] = {
        "deepseek": "https://api.deepseek.com/chat/completions",
        "doubao": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "sakura": "http://127.0.0.1:8080/v1/chat/completions",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "glm": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "wenxin": "https://qianfan.baidubce.com/v2/chat/completions",
        "custom": "",
    }

    @classmethod
    def _get_provider_default_url(cls, provider: str) -> str:
        return cls._PROVIDER_URLS.get(provider, "")

    def _get_proofread_url(self) -> str:
        """获取校对专用 API URL。"""
        if self._proofread_api_url:
            return self._proofread_api_url
        return self.api_url

    def _should_skip_proofread(self, src: str, dst: str) -> bool:
        """快速判断译文是否应该跳过 LLM 校对。"""
        dst = (dst or "").strip()
        if not dst:
            return True
        # 超短文本跳过校对（标点、语气词等）
        if len(src) <= 5 and len(dst) <= 5:
            return True
        # 匹配跳过模式
        import re as _re
        for pattern in self.PROOFREAD_SKIP_PATTERNS:
            if _re.match(pattern, dst):
                return True
        return False

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider: str = "deepseek",
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        glossary_path: Optional[str] = None,
        cache_path: Optional[str] = None,
        max_workers: int = 5,
        batch_size: int = 4,
        max_batch_length: int = 800,
        max_text_size_for_batch: int = 200,
        api_timeout: int = 120,
        chunk_size: int = 1200,
        cancel_event: Optional[threading.Event] = None,
        extract_glossary: bool = False,
        enable_glossary: bool = True,
        preset: Optional[str] = None,  # 已弃用，保留签名以兼容 Tk UI
        enable_thinking: bool = False,
        enable_proofread: bool = False,
        proofread_genre: str = "general",
        proofread_tone: str = "neutral",
        proofread_model: Optional[str] = None,  # P3-⑥: 校对专用模型
        proofread_provider: Optional[str] = None,  # P3-⑥: 校对专用 provider
        proofread_api_key: Optional[str] = None,
        proofread_api_url: Optional[str] = None,
        allow_text_cache_reuse: bool = False,
    ):
        self.provider = (provider or "deepseek").strip().lower()
        # preset 参数已弃用，不再应用预设，由调用方直接传递参数值
        if self.provider not in {"deepseek", "doubao", "sakura", "gemini", "glm", "wenxin", "custom"}:
            raise ValueError(f"不支持的提供方: {provider}")

        self.api_key = api_key or ""
        if not self.api_key:
            if self.provider == "deepseek":
                self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
            elif self.provider == "doubao":
                self.api_key = os.getenv("DOUBAO_API_KEY", "") or os.getenv("ARK_API_KEY", "")
            elif self.provider == "glm":
                self.api_key = os.getenv("GLM_API_KEY", "") or os.getenv("ZHIPU_API_KEY", "")
            elif self.provider == "wenxin":
                self.api_key = os.getenv("WENXIN_API_KEY", "") or os.getenv("QIANFAN_API_KEY", "")
        if self.provider == "deepseek" and not self.api_key:
            raise ValueError("未找到 DeepSeek API Key，请在界面输入或设置环境变量 DEEPSEEK_API_KEY")
        if self.provider == "doubao" and not self.api_key:
            raise ValueError("未找到豆包 API Key，请在界面输入或设置环境变量 DOUBAO_API_KEY / ARK_API_KEY")
        if self.provider == "gemini" and not self.api_key:
            raise ValueError("未找到 Gemini API Key，请在界面输入")
        if self.provider == "wenxin" and not self.api_key:
            raise ValueError("未找到文心一言/千帆 API Key，请在界面输入或设置环境变量 WENXIN_API_KEY / QIANFAN_API_KEY")
        if self.provider == "sakura" and not self.api_key:
            # Sakura 本地服务通常可无鉴权，默认给一个占位 key，兼容部分网关。
            self.api_key = "sk-local"
        if self.provider == "custom" and not self.api_key:
            raise ValueError("未找到自定义 API Key，请在界面输入")

        default_url = DEEPSEEK_API_URL
        default_model = DEEPSEEK_MODEL
        if self.provider == "sakura":
            default_url = SAKURA_API_URL
            default_model = SAKURA_MODEL
        elif self.provider == "doubao":
            default_url = DOUBAO_API_URL
            default_model = DOUBAO_MODEL
        elif self.provider == "gemini":
            default_url = GEMINI_API_URL
            default_model = GEMINI_MODEL
        elif self.provider == "glm":
            default_url = GLM_API_URL
            default_model = GLM_MODEL
        elif self.provider == "wenxin":
            default_url = WENXIN_API_URL
            default_model = WENXIN_MODEL

        raw_api_url = (api_url or default_url).strip()
        self.api_url = self._normalize_api_url(raw_api_url)
        self.model = (model or default_model).strip()
        self.temperature = temperature if temperature is not None else (0.1 if self.provider == "sakura" else 0.3)
        self.top_p = top_p if top_p is not None else (0.3 if self.provider == "sakura" else None)
        self.frequency_penalty = (
            frequency_penalty if frequency_penalty is not None else (0.1 if self.provider == "sakura" else None)
        )
        glm_model_name = self.model.lower()
        is_glm_free_or_flash = self.provider == "glm" and ("flash" in glm_model_name or "free" in glm_model_name)
        if is_glm_free_or_flash:
            max_workers = min(max_workers, 2)
            batch_size = min(batch_size, 2)
            max_batch_length = min(max_batch_length, 500)
            max_text_size_for_batch = min(max_text_size_for_batch, 150)

        data_dir = get_data_dir()
        self.glossary_path = glossary_path or str(data_dir / "glossary.json")
        self.cache_path = cache_path or str(data_dir / "cache.json")
        self.enable_glossary = bool(enable_glossary)

        self.glossary = self._load_json(self.glossary_path, {}) if self.enable_glossary else {}
        self.cache = self._load_json(self.cache_path, {})

        # 术语表分类（需要在 _count_glossary_terms 之前初始化）
        self.glossary_categories = DEFAULT_GLOSSARY_CATEGORIES

        # 记录术语表加载情况
        glossary_count = self._count_glossary_terms()
        if not self.enable_glossary:
            logger.info(f"术语表已禁用（默认路径: {self.glossary_path}）")
        elif glossary_count > 0:
            logger.info(f"加载术语表: {glossary_count} 条术语（来源: {self.glossary_path}）")
        else:
            logger.info(f"术语表为空或不存在: {self.glossary_path}")
        self._glossary_index = gs_rebuild_glossary_index(self.glossary or {}, self.glossary_categories) if self.enable_glossary else {}

        self._cache_dirty = False
        self._save_counter = 0
        self._cache_lock = threading.RLock()
        self._discard_cache_writes = threading.Event()
        self._stats_lock = threading.Lock()
        self._glossary_prompt_max_terms = 120
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.max_batch_length = max_batch_length
        self.max_text_size_for_batch = max_text_size_for_batch
        self.API_TIMEOUT = int(api_timeout)
        self.chunk_size = chunk_size
        self.cancel_event = cancel_event or threading.Event()
        self.session = requests.Session()
        # 连接池大小与并发数匹配，避免 "Connection pool is full" 警告
        adapter = requests.adapters.HTTPAdapter(pool_connections=self.max_workers, pool_maxsize=self.max_workers)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.extract_glossary = bool(extract_glossary)
        self.enable_thinking = bool(enable_thinking)
        self.enable_proofread = bool(enable_proofread)
        self.proofread_genre = proofread_genre if proofread_genre in GENRE_LABELS else "general"
        self.proofread_tone = proofread_tone if proofread_tone in TONE_LABELS else "neutral"
        # P3-⑥: 双模型流水线 — 校对用独立模型
        self.proofread_model = proofread_model or None
        self.proofread_provider = proofread_provider or None
        self.proofread_api_key = proofread_api_key or None
        self.allow_text_cache_reuse = bool(allow_text_cache_reuse)
        # P3-⑥: 校对专用 API URL（当 proofread_provider 与主 provider 不同时使用）
        self._proofread_api_url: Optional[str] = None
        if proofread_api_url:
            self._proofread_api_url = self._normalize_api_url(proofread_api_url)
        elif self.proofread_provider and self.proofread_provider != self.provider:
            self._proofread_api_url = self._get_provider_default_url(self.proofread_provider)

        # 加载提示词模板
        dict_dir = get_dict_dir()
        self._extraction_prompt_data = load_prompt_template(dict_dir, "glossary_extraction_prompt")
        self._output_format_data = load_prompt_template(dict_dir, "system_prompt_hq_format")

        self.stats = {
            "api_requests_total": 0,
            "api_requests_failed": 0,
            "tokens_total": 0,
            "batch_total": 0,
            "batch_json_success": 0,
            "batch_json_partial_success": 0,
            "batch_partial_retry": 0,
            "batch_delimiter_success": 0,
            "batch_fallback": 0,
            "batch_split_mismatch": 0,
            "batch_json_parse_fail": 0,
            "truncation_continuation": 0,
            "glossary_new_terms_added": 0,
            "proofread_suspicious": 0,
            "proofread_fixed": 0,
            "proofread_rejected": 0,
            "translation_incomplete": 0,
            "japanese_residue_remaining": 0,
        }
        logger.info(
            f"翻译器初始化完成: provider={self.provider}, model={self.model}, "
            f"并发数={self.max_workers}, 批量大小={self.batch_size}"
        )

    def _apply_provider_payload_options(self, payload: Dict[str, Any], provider: Optional[str] = None) -> None:
        """为特定提供方追加请求参数。"""
        active_provider = (provider or self.provider or "").lower()
        if (not self.enable_thinking) and active_provider in {"deepseek", "doubao", "glm", "custom"}:
            # 用户要求关闭深度思考。
            payload["thinking"] = {"type": "disabled"}

    @classmethod
    def _wait_global_rate_limit(cls, cancel_event: threading.Event) -> None:
        with cls._global_rate_limit_lock:
            wait_seconds = max(0.0, cls._global_rate_limit_until - time.time())
        if wait_seconds > 0 and cancel_event.wait(wait_seconds):
            raise RuntimeError("?????")

    @classmethod
    def _mark_global_rate_limit(cls, seconds: float) -> None:
        until = time.time() + max(0.0, seconds)
        with cls._global_rate_limit_lock:
            cls._global_rate_limit_until = max(cls._global_rate_limit_until, until)

    @staticmethod
    def _normalize_api_url(url: str) -> str:
        """兼容填写根地址或 /v1 的场景，自动补全到 chat completions 端点。"""
        u = (url or "").strip()
        if not u:
            return u
        u = u.rstrip("/")
        lower = u.lower()
        if lower.endswith("/chat/completions"):
            return u
        if lower.endswith("/v1"):
            return u + "/chat/completions"
        if lower.endswith("/v1/chat"):
            return u + "/completions"
        return u + "/chat/completions"

    @staticmethod
    def _extract_json_object(raw: str) -> Optional[dict]:
        """从模型返回中提取 JSON 对象，兼容 ```json 代码块与前后文本。"""
        if not raw:
            return None
        text = raw.strip()
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if m:
            try:
                obj = json.loads(m.group(1).strip())
                return obj if isinstance(obj, dict) else None
            except (json.JSONDecodeError, ValueError):
                pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1].strip())
                return obj if isinstance(obj, dict) else None
            except (json.JSONDecodeError, ValueError):
                return None
        return None

    def _inc_stat(self, key: str, delta: int = 1):
        with self._stats_lock:
            self.stats[key] = self.stats.get(key, 0) + delta

    def _accumulate_usage_tokens(self, data: Dict[str, Any]) -> None:
        """Accumulate usage.total_tokens from OpenAI-compatible responses when present."""
        if not isinstance(data, dict):
            return
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return
        total = usage.get("total_tokens")
        try:
            tokens = int(total)
        except (TypeError, ValueError):
            return
        if tokens > 0:
            self._inc_stat("tokens_total", tokens)

    def _get_finish_reason(self, data: Dict[str, Any]) -> Optional[str]:
        """从 OpenAI-compatible API 响应中提取 finish_reason"""
        choices = data.get("choices", [])
        if not choices or not isinstance(choices, list):
            return None
        choice = choices[0]
        if not isinstance(choice, dict):
            return None
        return choice.get("finish_reason")

    @staticmethod
    def _has_japanese_residue(text: str) -> bool:
        """Detect kana residue in Chinese drafts. Han characters alone are not reliable."""
        return bool(re.search(r"[\u3040-\u30ff\u31f0-\u31ff]", text or ""))

    @classmethod
    def _is_incomplete_translation(cls, src: str, dst: Optional[str]) -> bool:
        """Return True when a translation is unsafe to cache or write to EPUB."""
        source = (src or "").strip()
        translated = (dst or "").strip()
        if not translated:
            return True
        if cls._has_japanese_residue(translated):
            return True
        if source and translated == source and cls._has_japanese_residue(source):
            return True
        return False

    @staticmethod
    def _is_meaningful_glossary_term(original: str, translation: str) -> bool:
        """Ignore punctuation-only glossary entries in proofreading checks."""
        semantic_pattern = r"[A-Za-z0-9\u3040-\u30ff\u31f0-\u31ff\u3400-\u9fff]"
        return bool(re.search(semantic_pattern, original or "")) and bool(re.search(semantic_pattern, translation or ""))

    @staticmethod
    def _contains_katakana(text: str) -> bool:
        return bool(re.search(r"[\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9f]", text or ""))

    @staticmethod
    def _is_explicit_force_glossary_marker(source: str, info: str) -> bool:
        marker = f"{source} {info}".lower()
        return any(token in marker for token in ("force", "forced", "confirmed", "强制", "固定", "已确认"))

    @staticmethod
    def _is_reference_only_glossary_marker(source: str, info: str) -> bool:
        source_l = (source or "").strip().lower()
        marker = f"{source} {info}".lower()
        if source_l in {"auto", "自动提取", "reference", "ref", "weak", "suggestion"}:
            return True
        return any(token in marker for token in ("参考", "弱", "多义", "普通名词", "不强制", "reference-only"))

    def _lookup_glossary_metadata(self, original: str) -> Dict[str, str]:
        original = str(original or "").strip()
        if not original:
            return {}

        glossary_snapshot = getattr(self, "glossary", {}) or {}
        categories = getattr(self, "glossary_categories", DEFAULT_GLOSSARY_CATEGORIES)
        is_categorized = any(key in glossary_snapshot and isinstance(glossary_snapshot.get(key), list) for key in categories)
        if is_categorized:
            for category in categories:
                entries = glossary_snapshot.get(category, [])
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    entry_original = str(entry.get("original", entry.get("src", ""))).strip()
                    if entry_original != original:
                        continue
                    return {
                        "category": category,
                        "source": str(entry.get("source", "")).strip(),
                        "info": str(entry.get("info", "")).strip(),
                    }
            return {}

        value = glossary_snapshot.get(original)
        if isinstance(value, dict):
            return {
                "category": "Item",
                "source": str(value.get("source", "")).strip(),
                "info": str(value.get("info", "")).strip(),
            }
        return {"category": "Item", "source": "", "info": ""} if value else {}

    def _glossary_enforcement_level(self, entry: Dict[str, str]) -> str:
        """Return force/reference/ignore for proofread glossary enforcement."""
        original = str(entry.get("original", "")).strip()
        translation = str(entry.get("translation", "")).strip()
        if not self._is_meaningful_glossary_term(original, translation):
            return "ignore"

        metadata = self._lookup_glossary_metadata(original)
        category = str(entry.get("category") or metadata.get("category") or "Item").strip()
        source = str(entry.get("source") or metadata.get("source") or "").strip()
        info = str(entry.get("info") or metadata.get("info") or "").strip()

        if self._is_explicit_force_glossary_marker(source, info):
            return "force"
        if self._is_reference_only_glossary_marker(source, info):
            return "reference"

        if category in {"Person", "Location", "Org", "Skill", "Creature"}:
            return "force"

        # Short katakana item names are often common nouns embedded in longer words,
        # so keep them as prompt references unless explicitly marked as forced.
        if self._contains_katakana(original) and len(original) <= 4:
            return "reference"

        return "force"

    def _iter_all_glossary_entries(self) -> List[Dict[str, str]]:
        entries: List[Dict[str, str]] = []
        seen_original = set()

        glossary_index = getattr(self, "_glossary_index", None) or {}
        if glossary_index:
            for indexed_entries in glossary_index.values():
                for original, translation, source in indexed_entries:
                    original = str(original).strip()
                    translation = str(translation).strip()
                    source = str(source or "").strip()
                    if not original or not translation or original in seen_original:
                        continue
                    item = {"original": original, "translation": translation}
                    if source:
                        item["source"] = source
                    entries.append(item)
                    seen_original.add(original)
            return entries

        glossary_snapshot = getattr(self, "glossary", {}) or {}
        categories = getattr(self, "glossary_categories", DEFAULT_GLOSSARY_CATEGORIES)
        is_categorized = any(key in glossary_snapshot and isinstance(glossary_snapshot.get(key), list) for key in categories)
        if is_categorized:
            for category in categories:
                category_entries = glossary_snapshot.get(category, [])
                if not isinstance(category_entries, list):
                    continue
                for entry in category_entries:
                    if not isinstance(entry, dict):
                        continue
                    original = str(entry.get("original", entry.get("src", ""))).strip()
                    translation = str(entry.get("translation", entry.get("dst", ""))).strip()
                    source = str(entry.get("source", "")).strip()
                    if not original or not translation or original in seen_original:
                        continue
                    item = {"original": original, "translation": translation}
                    if source:
                        item["source"] = source
                    entries.append(item)
                    seen_original.add(original)
            return entries

        for original, value in glossary_snapshot.items():
            original = str(original).strip()
            if not original or original in seen_original:
                continue
            if isinstance(value, dict):
                translation = str(value.get("dst", value.get("translation", ""))).strip()
                source = str(value.get("source", "")).strip()
            else:
                translation = str(value).strip()
                source = ""
            if not translation:
                continue
            item = {"original": original, "translation": translation}
            if source:
                item["source"] = source
            entries.append(item)
            seen_original.add(original)
        return entries

    def _find_invalid_glossary_injections(
        self,
        src: str,
        draft: str,
        revised: str,
        allowed_entries: Optional[List[Dict[str, str]]] = None,
    ) -> List[str]:
        """Find glossary translations newly introduced without a valid source-side term match."""
        if not self.enable_glossary:
            return []

        src = src or ""
        draft = draft or ""
        revised = revised or ""
        if not src or not revised or revised == draft:
            return []

        allowed_originals = {
            str(entry.get("original", "")).strip()
            for entry in (allowed_entries or [])
            if str(entry.get("original", "")).strip()
        }
        invalid: List[str] = []
        for entry in self._iter_all_glossary_entries():
            original = str(entry.get("original", "")).strip()
            translation = str(entry.get("translation", "")).strip()
            if not original or not translation:
                continue
            if original in allowed_originals:
                continue
            if len(translation) < 2 or not self._is_meaningful_glossary_term(original, translation):
                continue
            if translation in draft or translation not in revised:
                continue
            # Only reject when the source contains the glossary term text but it was
            # not a valid standalone match, e.g. グラス inside サングラス.
            if original in src and not gs_has_valid_glossary_match(src, original):
                invalid.append(f"{original}->{translation}")
                if len(invalid) >= 5:
                    break
        return invalid

    def _select_proofread_glossary_entries(self, src: str, max_terms: int = 30) -> List[Dict[str, str]]:
        entries = self._select_glossary_entries(src, max_terms=max_terms)
        filtered = []
        for entry in entries:
            original = str(entry.get("original", "")).strip()
            translation = str(entry.get("translation", "")).strip()
            source = str(entry.get("source", "")).strip().lower()
            # 自动提取术语容易跨书污染。初译可参考，但校对阶段不强制执行。
            if source in {"auto", "自动提取"}:
                continue
            metadata = self._lookup_glossary_metadata(original)
            if metadata:
                entry = {**entry, **{k: v for k, v in metadata.items() if v}}
            if self._glossary_enforcement_level(entry) == "force":
                filtered.append(entry)
        return filtered

    def _find_proofread_issues(self, src: str, dst: str) -> List[str]:
        issues: List[str] = []
        src = (src or "").strip()
        dst = (dst or "").strip()
        if not src or not dst:
            return issues

        if self._has_japanese_residue(dst):
            issues.append("译文中疑似残留日文假名")

        if self.enable_glossary:
            for entry in self._select_proofread_glossary_entries(src, max_terms=30):
                original = str(entry.get("original", "")).strip()
                translation = str(entry.get("translation", "")).strip()
                if original and translation and gs_has_valid_glossary_match(src, original) and translation not in dst:
                    issues.append(f"术语未按术语表翻译: {original} -> {translation}")
        return issues

    def _build_proofread_system_prompt(self) -> str:
        return self._build_style_guidance("proofread")

    @staticmethod
    def _strip_proofread_explanations(text: str, fallback: str = "") -> str:
        """Remove model-added proofreading notes while preserving the revised translation."""
        cleaned = (text or "").strip()
        if not cleaned:
            return fallback

        cleaned = re.sub(r"^```(?:text|markdown|zh|中文)?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        cleaned = re.sub(r"^(?:修正后的中文译文|修正后译文|校对后译文|译文)[:：]\s*", "", cleaned).strip()

        note_prefix = r"(?:说明|修改说明|校对说明|修正说明|理由|解释|注)"
        # Remove a trailing parenthesized note such as "（说明：...）".
        while True:
            stripped = re.sub(rf"\s*[\(（]\s*{note_prefix}\s*[:：][\s\S]*?[\)）]\s*$", "", cleaned).strip()
            if stripped == cleaned:
                break
            cleaned = stripped

        # Remove a trailing free-form note line such as "说明：..." or "修改说明：...".
        cleaned = re.sub(rf"(?:^|\n)\s*{note_prefix}\s*[:：][\s\S]*$", "", cleaned).strip()
        return cleaned or fallback

    def _proofread_translation(
        self,
        src: str,
        draft: str,
        issues: List[str],
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
    ) -> str:
        """Ask the model to fix only detected translation/proper-noun issues."""
        if not bool(getattr(self, "enable_proofread", False)) or not issues:
            return draft

        selected_entries = self._select_proofread_glossary_entries(src, max_terms=30)
        glossary_text = self._build_glossary_text(selected_entries)
        system_prompt = self._build_proofread_system_prompt()
        context_guidance = self._build_context_guidance(prev_text, next_text)
        user_prompt = (
            "【发现的问题】\n"
            + "\n".join(f"- {issue}" for issue in issues)
            + f"\n\n【术语表】\n{glossary_text}\n\n"
            + (f"{context_guidance}\n\n" if context_guidance else "")
            + f"【日文原文】\n{src}\n\n"
            + f"【中文初译】\n{draft}\n"
            + "\n【术语规则】\n术语只在日文原文中独立命中且符合上下文时才修正；"
            + "短片假名普通物品和参考术语不得强行替换；如果术语译法会破坏语义，保留初译。\n"
            + "\n【输出格式】\n只输出修正后的中文译文。禁止输出说明、修改说明、理由、注释、括号说明或项目符号。\n"
        )
        proofread_api_key = self.proofread_api_key or self.api_key
        headers = {
            "Authorization": f"Bearer {proofread_api_key}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # P3-⑥: 双模型流水线 — 校对用独立模型/URL
        proofread_model = self.proofread_model or self.model
        proofread_url = self._get_proofread_url() if self.proofread_provider else self.api_url
        payload = {
            "model": proofread_model,
            "messages": messages,
            "temperature": 0.1,
        }
        self._apply_provider_payload_options(payload, self.proofread_provider or self.provider)

        for attempt in range(2):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._inc_stat("api_requests_total")
                resp = self.session.post(
                    proofread_url,
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                if resp.status_code == 429:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    logger.warning("校对请求遇到 502，保留初译")
                    return draft
                resp.raise_for_status()
                data = resp.json()
                self._accumulate_usage_tokens(data)
                choices = data.get("choices", [])
                if not choices:
                    return draft
                message = choices[0].get("message", {})
                revised = (message.get("content", "") or "").strip()
                cleaned = self._strip_proofread_explanations(revised, fallback=draft)
                invalid_injections = self._find_invalid_glossary_injections(
                    src,
                    draft,
                    cleaned,
                    allowed_entries=selected_entries,
                )
                if invalid_injections:
                    self._inc_stat("proofread_rejected")
                    logger.warning(
                        "校对结果引入未命中术语，已保留初译: "
                        + ", ".join(invalid_injections)
                    )
                    return draft
                return cleaned
            except Exception as e:
                logger.warning(f"译后校对失败: {e}")
                if attempt == 1:
                    return draft
        return draft

    def _send_continuation_request(
        self,
        messages: List[Dict[str, str]],
        accumulated_content: str,
        continuation_prompt: str,
        headers: Dict[str, str],
        base_payload: Dict[str, Any],
    ) -> Tuple[str, Optional[str]]:
        """
        发送截断续取请求（finish_reason=length 时继续）

        Args:
            messages: 原始消息历史
            accumulated_content: 已累积的内容
            continuation_prompt: 续取提示词
            headers: API headers
            base_payload: 基础 payload（不含 messages）

        Returns:
            (additional_content, finish_reason) 或 ("", None) 失败时
        """
        continuation_messages = list(messages)
        continuation_messages.append({"role": "assistant", "content": accumulated_content})
        continuation_messages.append({"role": "user", "content": continuation_prompt})

        payload = dict(base_payload)
        payload["messages"] = continuation_messages

        try:
            self._inc_stat("api_requests_total")
            resp = self.session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.API_TIMEOUT,
            )
            if resp.status_code in (429, 502):
                return "", None  # 优雅降级
            resp.raise_for_status()
            data = resp.json()
            self._accumulate_usage_tokens(data)
            choices = data.get("choices", [])
            if not choices:
                return "", None
            message = choices[0].get("message", {})
            additional = message.get("content", "")
            finish_reason = self._get_finish_reason(data)
            return (additional or "").strip(), finish_reason
        except Exception as e:
            logger.warning(f"截断续取请求失败: {e}")
            return "", None

    def get_stats(self) -> Dict[str, int]:
        with self._stats_lock:
            return dict(self.stats)

    @staticmethod
    def _load_json(path: str, default) -> dict:
        """加载 JSON 文件，不存在则返回默认值"""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logging.warning(f"JSON 文件解析失败 {path}: {e}")
                return default
        return default

    @staticmethod
    def _atomic_write_json(path: Union[str, Path], payload: Dict[str, Any]) -> None:
        """原子写入 JSON，避免异常中断导致文件损坏。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp_name, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, str(target))
        except Exception:
            try:
                if os.path.exists(tmp_name):
                    os.remove(tmp_name)
            except OSError:
                pass
            raise

    @classmethod
    def normalize_glossary_payload(cls, payload: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, int]]:
        return gs_normalize_glossary_payload(payload)

    def _cache_key(self, text: str) -> str:
        """Include provider/model in cache keys so switching models re-translates."""
        provider_model = f"{self.provider}:{self.model}".lower()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"v2:{provider_model}:{digest}"

    # ---- Phase 1-②: 文本级缓存（跨模型共享已验证译文）----
    _text_cache: Dict[str, Dict[str, Any]] = {}
    _text_cache_loaded = False
    TEXT_CACHE_FILE_NAME = "text_cache.json"
    _manual_cache: Dict[str, Dict[str, Any]] = {}
    _manual_cache_loaded = False
    MANUAL_CACHE_FILE_NAME = "manual_cache.json"

    def _load_text_cache(self):
        """加载文本级缓存（跨模型共享）。"""
        if self._text_cache_loaded:
            return
        text_cache_path = str(get_data_dir() / self.TEXT_CACHE_FILE_NAME)
        loaded = self._load_json(text_cache_path, {})
        if isinstance(loaded, dict):
            self._text_cache = loaded
        self._text_cache_loaded = True
        logger.info(f"文本缓存已加载: {len(self._text_cache)} 条记录")

    def _text_cache_key(self, text: str) -> str:
        """纯文本缓存键（不绑定 provider/model）。"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @classmethod
    def _cache_digest(cls, text: str) -> str:
        return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()

    def _load_manual_cache(self, force: bool = False):
        """加载人工修改缓存。人工译文优先级最高，不受跨模型缓存开关影响。"""
        if self._manual_cache_loaded and not force:
            return
        manual_cache_path = str(get_data_dir() / self.MANUAL_CACHE_FILE_NAME)
        loaded = self._load_json(manual_cache_path, {})
        self._manual_cache = loaded if isinstance(loaded, dict) else {}
        self._manual_cache_loaded = True
        logger.info(f"人工译文缓存已加载: {len(self._manual_cache)} 条记录")

    def _manual_cache_key(self, text: str) -> str:
        return self._cache_digest(text)

    def _lookup_manual_cache(self, text: str) -> Optional[str]:
        self._load_manual_cache()
        entry = self._manual_cache.get(self._manual_cache_key(text))
        if isinstance(entry, dict):
            return entry.get("translation")
        if isinstance(entry, str):
            return entry
        return None

    def _flush_manual_cache(self):
        manual_cache_path = str(get_data_dir() / self.MANUAL_CACHE_FILE_NAME)
        self._atomic_write_json(manual_cache_path, self._manual_cache)

    def save_manual_translation(self, src: str, dst: str) -> None:
        """保存人工译文并立即更新内存缓存。"""
        src = (src or "").strip()
        dst = (dst or "").strip()
        if not src or not dst:
            raise ValueError("原文和译文不能为空")
        self._load_manual_cache(force=True)
        self._manual_cache[self._manual_cache_key(src)] = {
            "source": src,
            "translation": dst,
            "updated_at": int(time.time()),
        }
        self._flush_manual_cache()

    def _lookup_text_cache(self, text: str) -> Optional[str]:
        """查找文本级缓存，返回已验证的译文或 None。"""
        self._load_text_cache()
        key = self._text_cache_key(text)
        entry = self._text_cache.get(key)
        if entry and isinstance(entry, dict) and entry.get("verified", False):
            return entry.get("translation")
        return None

    def _save_text_cache_entry(self, text: str, translation: str, verified: bool = False):
        """保存文本级缓存条目。"""
        self._load_text_cache()
        key = self._text_cache_key(text)
        # 不覆盖已 verified 的条目
        existing = self._text_cache.get(key, {})
        if isinstance(existing, dict) and existing.get("verified", False):
            return
        self._text_cache[key] = {
            "translation": translation,
            "verified": verified,
            "updated_at": int(time.time()),
        }
        # 每 50 条保存一次
        if len(self._text_cache) % 50 == 0:
            self._flush_text_cache()

    def _flush_text_cache(self):
        """持久化文本缓存。"""
        if not self._text_cache:
            return
        text_cache_path = str(get_data_dir() / self.TEXT_CACHE_FILE_NAME)
        self._atomic_write_json(text_cache_path, self._text_cache)

    def _save_cache(self, force: bool = False):
        """保存缓存到文件，使用延迟写入策略"""
        with self._cache_lock:
            self._cache_dirty = True
            self._save_counter += 1

            if force or self._save_counter >= self.CACHE_SAVE_THRESHOLD:
                try:
                    self._atomic_write_json(self.cache_path, self.cache)
                    self._cache_dirty = False
                    self._save_counter = 0
                except IOError as e:
                    logger.error(f"缓存保存失败: {e}")

    def flush_cache(self):
        """强制保存缓存（程序退出或翻译完成时调用）"""
        if self._cache_dirty:
            self._save_cache(force=True)
        self._flush_text_cache()

    def discard_cache_writes(self) -> None:
        """停止本实例继续写入翻译缓存，用于“停止并清空本次译文”。"""
        flag = getattr(self, "_discard_cache_writes", None)
        if flag is None:
            self._discard_cache_writes = threading.Event()
            flag = self._discard_cache_writes
        flag.set()

    def _should_write_cache(self) -> bool:
        flag = getattr(self, "_discard_cache_writes", None)
        return not (flag is not None and flag.is_set())

    def clear_cache_for_texts(
        self,
        texts: List[str],
        include_text_cache: bool = False,
        all_models: bool = False,
    ) -> int:
        """清理指定原文对应的缓存。

        Args:
            texts: 要清理的原文文本。
            include_text_cache: 是否同时清理跨模型 text_cache.json。
            all_models: 是否清理所有 provider/model 下的同原文缓存。
        """
        unique_texts = {str(text or "").strip() for text in texts}
        unique_texts.discard("")
        if not unique_texts:
            return 0

        removed = 0
        with self._cache_lock:
            if all_models:
                digests = set()
                for text in unique_texts:
                    raw = text.encode("utf-8")
                    digests.add(hashlib.sha256(raw).hexdigest())
                    digests.add(hashlib.md5(raw).hexdigest())
                keys_to_remove = [
                    key for key in list(self.cache)
                    if any(str(key).endswith(f":{digest}") or str(key) == digest for digest in digests)
                ]
                for key in keys_to_remove:
                    self.cache.pop(key, None)
                    removed += 1
            else:
                for text in unique_texts:
                    cache_key = self._cache_key(text)
                    if cache_key in self.cache:
                        self.cache.pop(cache_key, None)
                        removed += 1
            if removed:
                self._cache_dirty = True

        if removed:
            self._save_cache(force=True)

        if include_text_cache:
            self._load_text_cache()
            text_removed = 0
            for text in unique_texts:
                key = self._text_cache_key(text)
                if key in self._text_cache:
                    self._text_cache.pop(key, None)
                    text_removed += 1
            if text_removed:
                text_cache_path = str(get_data_dir() / self.TEXT_CACHE_FILE_NAME)
                self._atomic_write_json(text_cache_path, self._text_cache)
                removed += text_removed

            self._load_manual_cache(force=True)
            manual_removed = 0
            for text in unique_texts:
                key = self._manual_cache_key(text)
                if key in self._manual_cache:
                    self._manual_cache.pop(key, None)
                    manual_removed += 1
            if manual_removed:
                self._flush_manual_cache()
                removed += manual_removed
        return removed

    def _count_glossary_terms(self) -> int:
        """统计术语表中的术语数量"""
        if not self.glossary:
            return 0

        # 检测是否为新格式（分类结构）
        is_categorized = any(
            key in self.glossary and isinstance(self.glossary.get(key), list)
            for key in self.glossary_categories
        )

        if is_categorized:
            total = 0
            for category in self.glossary_categories:
                entries = self.glossary.get(category, [])
                if isinstance(entries, list):
                    total += len(entries)
            return total
        else:
            return len(self.glossary)

    def _select_glossary_entries(self, context_text: str, max_terms: Optional[int] = None) -> List[Dict[str, str]]:
        """??????????????????"""
        if not self.enable_glossary:
            return []
        with self._cache_lock:
            glossary_snapshot = dict(self.glossary)
        if not glossary_snapshot:
            return []

        limit = max_terms or self._glossary_prompt_max_terms
        glossary_index = getattr(self, "_glossary_index", None)
        return gs_select_glossary_entries(
            context_text,
            glossary_snapshot,
            self.glossary_categories,
            limit,
            glossary_index=glossary_index,
        )


    def _build_glossary_text(self, selected_entries: Optional[List[Dict[str, str]]] = None) -> str:
        """?????????? selected_entries ?????????"""
        with self._cache_lock:
            glossary_snapshot = dict(self.glossary)
        return gs_build_glossary_text(glossary_snapshot, self.glossary_categories, selected_entries)

    def _get_style_profile(self) -> Tuple[str, str, str, str]:
        genre = self.proofread_genre if self.proofread_genre in GENRE_LABELS else "general"
        tone = self.proofread_tone if self.proofread_tone in TONE_LABELS else "neutral"
        return genre, tone, GENRE_LABELS.get(genre, "通用小说"), TONE_LABELS.get(tone, "中性口吻")

    def _build_style_guidance(self, stage: str) -> str:
        genre, tone, genre_label, tone_label = self._get_style_profile()
        genre_rules = {
            "general": [
                "保持中性、自然、准确的中文表达。",
                "不主动强化文风，不把译文改成轻小说、古风或网络文风。",
                "只在表达明显生硬时做小幅调整。",
            ],
            "mystery": [
                "保留线索、时间顺序、人物关系、证词和模糊表达。",
                "不要替读者解释谜题，不要补充原文没有明说的因果。",
                "对数字、地点、称谓、物证、动作细节保持准确。",
                "语气可以更清晰，但不能牺牲原文悬念。",
            ],
            "scifi": [
                "保持技术术语、设定名、组织名、设备名一致。",
                "技术表达要准确清楚，不要为了口语化而削弱专业感。",
                "不擅自解释设定，不补充原文没有的信息。",
                "对单位、数字、时间、空间、实验条件保持准确。",
            ],
            "fantasy": [
                "保持人名、地名、种族、魔法、技能、道具、组织名一致。",
                "文风可以略有叙事感，但不要改成古风腔或网文腔。",
                "不擅自强化设定，不补充原文没有的世界观说明。",
                "战斗、技能、称号和等级表达要清楚稳定。",
            ],
        }
        tone_rules = {
            "neutral": [
                "使用中性、克制、自然的中文口吻。",
                "不额外强化角色卖萌、吐槽或文学腔。",
            ],
            "light": [
                "对白要自然，符合中文轻小说阅读习惯。",
                "保留角色语气、吐槽感、情绪强弱和称呼关系。",
                "不要过度书面化，不要把口语对白改得太正式。",
                "不要擅自加入网络流行语。",
            ],
            "literary": [
                "叙述语言可以更顺畅、凝练，但不能改写原意。",
                "保留原文的节奏、留白和情绪，不要过度口语化。",
                "避免华丽堆砌，不要把普通叙述改成生硬文学腔。",
            ],
        }

        def numbered(items: List[str]) -> str:
            return "\n".join(f"{idx}. {item}" for idx, item in enumerate(items, 1))

        if stage == "proofread":
            header = (
                "你是日译中小说校对编辑。\n"
                f"当前作品类型是：{genre_label}。\n"
                f"当前叙事口吻是：{tone_label}。\n\n"
                "你的任务是修正中文初译中的明显问题，不做自由润色。\n\n"
                "必须遵守：\n"
                "1. 不新增剧情、不删除信息、不改变原意。\n"
                "2. 修正日文残留、漏译、明显错译、语病和不自然表达。\n"
                "3. 专有名词必须按术语表翻译。\n"
                "4. 保持原段落结构，不合并、不拆分段落。\n"
                "5. 不解释原文，不输出注释，不输出修改说明。\n"
                "6. 只输出修正后的中文译文。\n\n"
            )
        else:
            header = (
                "当前翻译风格设置：\n"
                f"- 作品类型：{genre_label}\n"
                f"- 叙事口吻：{tone_label}\n\n"
                "请按上述类型与口吻进行初译，同时必须遵守：\n"
                "1. 不新增剧情、不删除信息、不改变原意。\n"
                "2. 专有名词必须按术语表翻译。\n"
                "3. 保持原段落结构，不合并、不拆分段落。\n"
                "4. 保持人物语气、叙事节奏和情绪层次。\n"
                "5. 只输出译文，不输出解释或注释。\n\n"
            )

        return header + f"{genre_label}要求：\n{numbered(genre_rules[genre])}\n\n{tone_label}要求：\n{numbered(tone_rules[tone])}"


    def _build_batch_system_prompt(self) -> str:
        """
        构建批量翻译的系统提示词（使用模板）

        Returns:
            完整的系统提示词
        """
        # 基础提示词
        base_prompt = """你是日文到中文翻译助手。
请严格输出 JSON 对象，不要输出任何额外文字。
JSON 顶层字段：
1) "translations": 数组，长度必须与输入一致，索引顺序一致，元素格式 {"idx": 整数, "zh": "译文"}。
2) "new_terms": 数组，元素格式 {"src": "原词", "dst": "译词", "category": "分类"}，没有则返回空数组。
   - category 可选值：Person, Location, Org, Item, Skill, Creature
   - 若无法确定分类，可省略 category 字段"""

        # 尝试从模板加载
        if self._output_format_data:
            template = self._output_format_data.get("system_prompt_template", "")
            if template:
                # 组装模板
                base_part = self._output_format_data.get("system_prompt_base", "")
                format_part = self._output_format_data.get("system_prompt_output_format", "")
                extraction_rules = self._output_format_data.get("optional_extraction_rules", "")

                if self.extract_glossary:
                    optional_rules = extraction_rules
                else:
                    no_extract = self._output_format_data.get("system_prompt_no_extract", "")
                    optional_rules = no_extract if no_extract else '\n当未启用术语抽取时，必须返回 "new_terms": []。'

                system_prompt = resolve_template_vars(
                    template,
                    system_prompt_base=base_part or base_prompt,
                    system_prompt_output_format=format_part,
                    optional_extraction_rules=optional_rules,
                    target_lang="简体中文"
                )
                # 追加术语提取规则
                if self.extract_glossary and self._extraction_prompt_data:
                    extraction_prompt = self._extraction_prompt_data.get("glossary_extraction_prompt", "")
                    if extraction_prompt:
                        extraction_prompt = resolve_template_vars(extraction_prompt, target_lang="简体中文")
                        system_prompt += "\n\n" + extraction_prompt

                return system_prompt.rstrip() + "\n\n" + self._build_style_guidance("translation")

        # 回退到硬编码
        if not self.extract_glossary:
            system_prompt = base_prompt + '\n\n当未启用术语抽取时，必须返回 "new_terms": []。'
            return system_prompt.rstrip() + "\n\n" + self._build_style_guidance("translation")

        # 添加术语提取规则
        extraction_rules = """
术语抽取规则：
- 仅提取专有名词或固定术语（人名/地名/组织/招式/装备等）
- 不提取通用词、语气词、普通动词形容词
- 每批最多返回 5 条，宁缺毋滥
- 每条术语建议指定 category 字段"""

        # 追加模板中的抽取规则
        if self._extraction_prompt_data:
            template_extraction = self._extraction_prompt_data.get("glossary_extraction_prompt", "")
            if template_extraction:
                extraction_rules = "\n" + resolve_template_vars(template_extraction, target_lang="简体中文")

        system_prompt = base_prompt + "\n" + extraction_rules
        return system_prompt.rstrip() + "\n\n" + self._build_style_guidance("translation")

    def _call_deepseek_single(
        self,
        text: str,
        max_retries: int = 3,
        text_separator: Optional[str] = None,
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
    ) -> SingleChunkResult:
        """
        调用模型 API（单条），支持截断续取。

        Returns:
            SingleChunkResult: 包含 content、finish_reason、is_truncated
        """
        sep = text_separator or DEFAULT_TEXT_SEPARATOR
        is_batch = sep in text

        deepseek_prompt = """你是资深日文文学翻译专家，精通日中双语，擅长文学翻译。
【翻译原则】信、雅、达：
- 信：准确传达原文含义，不随意增删改，保持原作风格和情感基调
- 雅：译文文笔优美，符合中文表达习惯，避免生硬直译或翻译腔
- 达：语言流畅自然，通顺易懂，让读者沉浸在故事中
【日文特有表达处理】：
1. 敬语体系：将敬语转换为符合中文语境的表达，不必过度保留敬称
2. 姐さん/兄さん等称谓：根据角色关系，译为"姐姐/哥哥"或保留昵称风格
3. 委婉表达：日文的含蓄委婉可适当转化为更直接的中文表达，但要保留情感色彩
4. 语气词：よ、ね、さ等语气词不必逐字翻译，用自然的中文语气表达即可
5. 内心独白：保持第一人称叙述的连贯性，内心想法用括号或直接叙述

【文体风格】：
1. 小说对话：保持角色性格和语气，对话生动自然
2. 叙述描写：文笔优美，有文学质感，避免大白话
3. 专业术语：按术语表翻译，保持一致
4. 成语典故：可用恰当中文成语替代，但要自然不生硬
【输出要求】：
1. 输出仅为译文，不要解释或添加原文
2. 保持原文段落结构，不合并或拆分段落
3. 保留专有名词一致性（人名、地名、作品名等）
4. 标点符号使用中文规范
5. 禁止输出任何翻译说明、注释、括号备注或编号列表
6. 禁止在译文末尾附加翻译说明内容"""

        sakura_prompt = """你是一个轻小说翻译模型，可以流畅通顺地使用给定术语表以指定格式从日文翻译到简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的人名。
你必须按照以下规则执行：
1. 理解并严格遵循术语表格式与备注。
2. 仅输出译文，不输出说明。
3. 不改变段落数量与顺序。"""

        system_prompt = (sakura_prompt if self.provider == "sakura" else deepseek_prompt).rstrip()
        system_prompt += "\n\n" + self._build_style_guidance("translation")
        if is_batch:
            system_prompt += f"""

【重要！多段落分隔规则】原文由多个独立段落组成，段落之间用'{sep.strip()}'分隔。
你必须在译文中保留相同数量的段落，且每个段落之间也必须用'{sep.strip()}'分隔。
绝对不能将多个段落合并为一个段落！
输出格式：译文1{sep.strip()}译文2{sep.strip()}译文3..."""

        selected_entries = self._select_glossary_entries(text)
        context_guidance = ""
        if self.ENABLE_CONTEXT_WINDOW and (prev_text or next_text):
            context_guidance = "\n\n" + self._build_context_guidance(prev_text, next_text)
        user_prompt = (
            f"【术语表】\n{self._build_glossary_text(selected_entries)}\n\n"
            f"请将以下日文翻译为优美流畅的中文：\n{text}"
            f"{context_guidance}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        self._apply_provider_payload_options(payload)
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty

        last_error = None
        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")

            try:
                self._inc_stat("api_requests_total")
                resp = self.session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )

                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    logger.warning(f"API 限流，等待 {wait_time:.1f} 秒后重试...")
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    self._inc_stat("api_requests_failed")
                    raise FastFailError("翻译失败: HTTP 502 Bad Gateway（已按配置直接中断）")

                resp.raise_for_status()
                data = resp.json()
                self._accumulate_usage_tokens(data)

                choices = data.get("choices", [])
                if not choices:
                    raise KeyError("API 响应缺少 choices 字段")
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if not content:
                    raise KeyError("API 响应缺少 content 字段")

                content = content.strip()
                finish_reason = self._get_finish_reason(data)
                is_truncated = finish_reason == "length"

                # P0-B: 截断续取逻辑
                if is_truncated:
                    accumulated = content
                    continuations_used = 0
                    continuation_prompt = "请继续完成翻译，从断点处继续输出。"

                    while continuations_used < self.MAX_CONTINUATIONS and finish_reason == "length":
                        if self.cancel_event.is_set():
                            break

                        additional, new_finish = self._send_continuation_request(
                            messages=messages,
                            accumulated_content=accumulated,
                            continuation_prompt=continuation_prompt,
                            headers=headers,
                            base_payload={
                                "model": self.model,
                                "temperature": self.temperature,
                                "top_p": self.top_p,
                                "frequency_penalty": self.frequency_penalty,
                            },
                        )
                        if not additional:
                            break  # 优雅降级

                        accumulated += additional
                        finish_reason = new_finish
                        continuations_used += 1
                        self._inc_stat("truncation_continuation")
                        logger.info(f"截断续取 {continuations_used}/{self.MAX_CONTINUATIONS}")

                    content = accumulated
                    is_truncated = finish_reason == "length"  # 可能仍然截断

                return SingleChunkResult(
                    content=content,
                    finish_reason=finish_reason,
                    is_truncated=is_truncated,
                )

            except requests.exceptions.Timeout:
                self._inc_stat("api_requests_failed")
                last_error = "请求超时"
                logger.warning(f"API 请求超时 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                self._inc_stat("api_requests_failed")
                last_error = "网络连接失败"
                logger.warning(f"网络连接失败 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.HTTPError as e:
                self._inc_stat("api_requests_failed")
                last_error = f"HTTP 错误: {e}"
                logger.warning(f"HTTP 错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                self._inc_stat("api_requests_failed")
                last_error = f"API 响应格式错误: {e}"
                logger.error(f"API 响应格式错误: {e}")
                break
            except FastFailError:
                raise
            except Exception as e:
                self._inc_stat("api_requests_failed")
                last_error = f"未知错误: {e}"
                logger.error(f"未知错误: {e}")

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt + random.uniform(0, 1)
                if self.cancel_event.wait(wait_time):
                    raise RuntimeError("翻译已取消")

        raise RuntimeError(f"翻译失败: {last_error}")

    def _call_deepseek(
        self,
        text: str,
        max_retries: int = 3,
        text_separator: Optional[str] = None,
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
    ) -> str:
        """向后兼容的包装器，仅返回 content 字符串"""
        result = self._call_deepseek_single(text, max_retries, text_separator,
                                              prev_text=prev_text, next_text=next_text)
        return result.content

    def _call_deepseek_batch_json(
        self,
        texts: List[str],
        max_retries: int = 2,
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
        item_contexts: Optional[List[Tuple[Optional[str], Optional[str]]]] = None,
    ) -> BatchJsonResult:
        """批量翻译：结构化返回 translations + new_terms。支持截断续取和部分成功。"""
        if not texts:
            return BatchJsonResult(translations=[], new_terms=[], missing_indices=[], finish_reason="stop")

        numbered = []
        for i, t in enumerate(texts):
            item = {"idx": i, "text": t}
            if item_contexts and i < len(item_contexts):
                item_prev, item_next = item_contexts[i]
                if item_prev:
                    item["prev"] = item_prev[:self.CONTEXT_PREVIEW_LEN]
                if item_next:
                    item["next"] = item_next[:self.CONTEXT_PREVIEW_LEN]
            numbered.append(item)

        # 从模板构建系统提示词
        system_prompt = self._build_batch_system_prompt()
        context_text = "\n".join(texts)
        selected_entries = self._select_glossary_entries(context_text)

        context_guidance = ""
        if item_contexts:
            context_guidance = "\n\nJSON 中的 prev/next 字段是上下文参考，只用于理解语境；只翻译 text 字段。"
        elif self.ENABLE_CONTEXT_WINDOW and (prev_text or next_text):
            context_guidance = "\n\n" + self._build_context_guidance(prev_text, next_text)

        user_prompt = (
            f"【术语表】\n{self._build_glossary_text(selected_entries)}\n\n"
            f"请翻译以下 JSON 数组中的 text 字段并返回 JSON：\n{json.dumps(numbered, ensure_ascii=False)}"
            f"{context_guidance}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
        }
        self._apply_provider_payload_options(payload)
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty
        if self.provider == "deepseek":
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._inc_stat("api_requests_total")
                resp = self.session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    self._inc_stat("api_requests_failed")
                    raise FastFailError("翻译失败: HTTP 502 Bad Gateway（已按配置直接中断）")
                resp.raise_for_status()
                data = resp.json()
                self._accumulate_usage_tokens(data)

                choices = data.get("choices", [])
                if not choices:
                    self._inc_stat("batch_json_parse_fail")
                    return BatchJsonResult(
                        translations=None, missing_indices=list(range(len(texts))),
                        finish_reason=self._get_finish_reason(data),
                    )
                message = choices[0].get("message", {})
                raw = message.get("content", "")
                if not raw:
                    self._inc_stat("batch_json_parse_fail")
                    return BatchJsonResult(
                        translations=None, missing_indices=list(range(len(texts))),
                        finish_reason=self._get_finish_reason(data),
                    )

                raw = raw.strip()
                finish_reason = self._get_finish_reason(data)
                is_truncated = finish_reason == "length"

                # P0-B: 截断续取 — 拼接 JSON 字符串直到完整或达到上限
                if is_truncated:
                    accumulated_raw = raw
                    continuations_used = 0
                    continuation_prompt = "请从断点处继续输出 JSON，不要从头开始。"

                    while continuations_used < self.MAX_CONTINUATIONS and finish_reason == "length":
                        if self.cancel_event.is_set():
                            break
                        additional, new_finish = self._send_continuation_request(
                            messages=messages,
                            accumulated_content=accumulated_raw,
                            continuation_prompt=continuation_prompt,
                            headers=headers,
                            base_payload={
                                "model": self.model,
                                "temperature": payload.get("temperature", self.temperature),
                                "top_p": self.top_p,
                                "frequency_penalty": self.frequency_penalty,
                            },
                        )
                        if not additional:
                            break
                        accumulated_raw += additional
                        finish_reason = new_finish
                        continuations_used += 1
                        self._inc_stat("truncation_continuation")
                        logger.info(f"批量 JSON 截断续取 {continuations_used}/{self.MAX_CONTINUATIONS}")

                    raw = accumulated_raw
                    is_truncated = finish_reason == "length"

                # P0-A: 部分成功校验（替代全有全无）
                obj = self._extract_json_object(raw)
                if not isinstance(obj, dict):
                    self._inc_stat("batch_json_parse_fail")
                    return BatchJsonResult(
                        translations=None, missing_indices=list(range(len(texts))),
                        finish_reason=finish_reason, is_truncated=is_truncated, raw_content=raw,
                    )

                arr = obj.get("translations") or obj.get("items")
                if not isinstance(arr, list):
                    self._inc_stat("batch_json_parse_fail")
                    return BatchJsonResult(
                        translations=None, missing_indices=list(range(len(texts))),
                        finish_reason=finish_reason, is_truncated=is_truncated, raw_content=raw,
                    )

                # 逐条校验 idx，跳过无效项（防幻觉），保留有效项
                out = [None] * len(texts)
                valid_indices = set()

                for item in arr:
                    if not isinstance(item, dict):
                        continue  # 跳过非 dict 项
                    idx = item.get("idx")
                    zh = item.get("zh")
                    if not isinstance(idx, int) or idx < 0 or idx >= len(texts):
                        continue  # 跳过越界 idx（幻觉）
                    if not isinstance(zh, str) or not zh.strip():
                        continue  # 跳过空译文
                    out[idx] = zh.strip()
                    valid_indices.add(idx)

                missing_indices = [i for i in range(len(texts)) if i not in valid_indices]

                if valid_indices and missing_indices:
                    self._inc_stat("batch_json_partial_success")
                    logger.warning(
                        f"批量 JSON 部分成功: {len(valid_indices)}/{len(texts)} 有效, "
                        f"缺失索引: {missing_indices}"
                    )

                raw_terms = obj.get("new_terms", [])
                if not isinstance(raw_terms, list):
                    raw_terms = []

                return BatchJsonResult(
                    translations=out,
                    new_terms=raw_terms,
                    missing_indices=missing_indices,
                    finish_reason=finish_reason,
                    is_truncated=is_truncated,
                    raw_content=raw,
                )
            except FastFailError:
                raise
            except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
                self._inc_stat("api_requests_failed")
                logger.warning(f"批量翻译请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                return BatchJsonResult(
                    translations=None, missing_indices=list(range(len(texts))),
                )

        return BatchJsonResult(
            translations=None, missing_indices=list(range(len(texts))),
        )

    def replace_glossary(self, glossary: Dict[str, Any]) -> None:
        """线程安全替换术语表，并持久化到 glossary_path。"""
        with self._cache_lock:
            normalized, _ = self.normalize_glossary_payload(glossary or {})
            self.glossary = normalized
            self._glossary_index = gs_rebuild_glossary_index(self.glossary or {}, self.glossary_categories)
            self._atomic_write_json(self.glossary_path, self.glossary)

    @classmethod
    def merge_glossaries(
        cls,
        existing: Dict[str, List[Dict[str, str]]],
        incoming: Dict[str, List[Dict[str, str]]],
    ) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, int]]:
        return gs_merge_glossaries(existing, incoming)


    @staticmethod
    def _clean_new_terms(raw_terms: List[dict]) -> List[Dict[str, Any]]:
        return gs_clean_new_terms(raw_terms)


    def _merge_new_terms_into_glossary(self, terms: List[Dict[str, Any]]) -> int:
        """
        增量写入 glossary.json（仅新增，不覆盖）。
        使用与导入一致的分类 schema 与 keep_old 冲突策略。

        Args:
            terms: 清洗后的术语列表，每个元素包含
                   {"src", "dst", "category", "info"?, "source"?}

        Returns:
            新增的术语数量
        """
        if not terms:
            return 0

        added = 0
        conflicts = 0
        skipped = 0
        with self._cache_lock:
            # 先将当前术语统一归一化到分类 schema
            normalized_existing, _ = self.normalize_glossary_payload(self.glossary or {})
            self.glossary = normalized_existing

            incoming_by_category = {cat: [] for cat in self.glossary_categories}
            for term in terms:
                src = str(term.get("src", "")).strip()
                dst = str(term.get("dst", "")).strip()
                category = str(term.get("category", "Item")).strip() or "Item"
                info = str(term.get("info", "")).strip()
                source = str(term.get("source", "auto")).strip() or "auto"
                if not src or not dst:
                    skipped += 1
                    continue
                if category not in self.glossary_categories:
                    category = "Item"
                entry: Dict[str, str] = {"original": src, "translation": dst}
                if info:
                    entry["info"] = info
                if source:
                    entry["source"] = source
                incoming_by_category[category].append(entry)

            merged, merge_stats = gs_merge_glossaries(self.glossary, incoming_by_category)
            self.glossary = merged
            self._glossary_index = gs_rebuild_glossary_index(self.glossary or {}, self.glossary_categories)
            added += int(merge_stats.get("added", 0))
            skipped += int(merge_stats.get("skipped", 0))
            conflicts += int(merge_stats.get("conflicts", 0))

            if added > 0:
                try:
                    self._atomic_write_json(self.glossary_path, self.glossary)
                except Exception as e:
                    logger.warning(f"术语表写入失败: {e}")
                    added = 0

        if added > 0:
            self._inc_stat("glossary_new_terms_added", added)
            logger.info(f"新增 {added} 条术语到术语表")
        if conflicts > 0 or skipped > 0:
            logger.info(f"自动术语合并统计: added={added} skipped={skipped} conflicts={conflicts}")

        return added

    def _translate_chunk(self, text: str, prev_text: Optional[str] = None, next_text: Optional[str] = None) -> str:
        """翻译单个文本块（带缓存），可选上下文窗口。"""
        text = text.strip()
        if not text:
            return text

        if self.cancel_event.is_set():
            raise RuntimeError("翻译已取消")

        cache_key = self._cache_key(text)
        with self._cache_lock:
            if cache_key in self.cache:
                return self.cache[cache_key]

        zh = self._call_deepseek(text, prev_text=prev_text, next_text=next_text)

        if self._should_write_cache():
            with self._cache_lock:
                self.cache[cache_key] = zh
            self._save_cache()
        return zh

    @staticmethod
    def _smart_split_text(text: str, chunk_size: int) -> List[str]:
        """按段落+句子优先切分，尽量避免生硬按字符截断。"""
        text = text.strip()
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        paragraphs = [p for p in text.split("\n") if p]
        chunks: List[str] = []
        current = ""

        def flush_current():
            nonlocal current
            if current:
                chunks.append(current)
                current = ""

        for para in paragraphs:
            if len(para) > chunk_size:
                sentences = re.split(r"(?<=[。！？!?…])", para)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue

                    if len(sentence) > chunk_size:
                        flush_current()
                        for i in range(0, len(sentence), chunk_size):
                            chunks.append(sentence[i:i + chunk_size])
                        continue

                    if not current:
                        current = sentence
                    elif len(current) + 1 + len(sentence) <= chunk_size:
                        current += "\n" + sentence
                    else:
                        flush_current()
                        current = sentence
                continue

            if not current:
                current = para
            elif len(current) + 1 + len(para) <= chunk_size:
                current += "\n" + para
            else:
                flush_current()
                current = para

        flush_current()
        return chunks

    def translate(self, text: str, chunk_size: Optional[int] = None) -> str:
        """翻译文本，支持缓存和长文本分块"""
        text = text.strip()
        if not text:
            return text

        # 使用实例配置，允许传入覆盖
        effective_chunk_size = chunk_size if chunk_size is not None else self.chunk_size

        cache_key = self._cache_key(text)
        with self._cache_lock:
            if cache_key in self.cache:
                return self.cache[cache_key]

        if len(text) <= effective_chunk_size:
            zh = self._call_deepseek(text)
        else:
            chunks = self._smart_split_text(text, effective_chunk_size)
            with ThreadPoolExecutor(max_workers=min(self.max_workers, len(chunks))) as executor:
                futures = {executor.submit(self._translate_chunk, c): i for i, c in enumerate(chunks)}
                results = [None] * len(chunks)
                for future in as_completed(futures):
                    idx = futures[future]
                    results[idx] = future.result()

            zh = "\n".join(results).strip()

        if self._should_write_cache():
            with self._cache_lock:
                self.cache[cache_key] = zh
            self._save_cache()
        return zh

    # ---- Phase 1-③: 本地预翻译 ----
    def _pre_translate(self, text: str) -> Optional[str]:
        """本地规则预翻译，命中则返回译文，否则返回 None。"""
        stripped = text.strip()
        if stripped in self.PRE_TRANSLATE_RULES:
            return self.PRE_TRANSLATE_RULES[stripped]
        return None

    # ---- Phase 1-①: 智能分批 ----
    def _smart_batch(self, texts: List[str], effective_batch_size: int) -> List[List[str]]:
        """
        按文本长度分三档智能分批：
        - 短文本（≤30字）：大 batch 合并（2x batch_size），减少 API 调用
        - 中文本（30~200字）：正常 batch_size 合并
        - 长文本（>200字）：单条处理，避免 JSON 格式解析失败
        """
        short = []
        medium = []
        long = []

        long_threshold = max(self.SMART_BATCH_LONG, int(getattr(self, "max_text_size_for_batch", self.SMART_BATCH_LONG) or self.SMART_BATCH_LONG))

        for text in texts:
            text_len = len(text)
            if text_len <= self.SMART_BATCH_SHORT:
                short.append(text)
            elif text_len <= long_threshold:
                medium.append(text)
            else:
                long.append(text)

        batches = []

        # 短文本：大 batch（2x），按字符总量限制
        short_batch_size = min(effective_batch_size * 2, 20)
        current = []
        current_len = 0
        for text in short:
            if len(current) < short_batch_size and current_len + len(text) < self.max_batch_length * 2:
                current.append(text)
                current_len += len(text)
            else:
                if current:
                    batches.append(current)
                current = [text]
                current_len = len(text)
        if current:
            batches.append(current)

        # 中文本：正常 batch_size
        current = []
        current_len = 0
        for text in medium:
            if len(current) < effective_batch_size and current_len + len(text) < self.max_batch_length:
                current.append(text)
                current_len += len(text)
            else:
                if current:
                    batches.append(current)
                current = [text]
                current_len = len(text)
        if current:
            batches.append(current)

        # 长文本：每条单独处理
        for text in long:
            batches.append([text])

        # 统计
        short_count = len([b for b in batches if b and len(b[0]) <= self.SMART_BATCH_SHORT])
        medium_count = len([b for b in batches if b and self.SMART_BATCH_SHORT < len(b[0]) <= long_threshold])
        long_count = len([b for b in batches if b and len(b[0]) > long_threshold])
        logger.info(
            f"智能分批: 短文本 {len(short)}→{short_count}批, "
            f"中文本 {len(medium)}→{medium_count}批, "
            f"长文本 {len(long)}→{long_count}批"
        )

        return batches

    def translate_batch(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        item_callback: Optional[Callable[[str, str], None]] = None,
        proofread_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        batch_size: Optional[int] = None,
        context_texts: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """并发批量翻译多个文本（Phase 1 优化版）"""
        results: Dict[str, str] = {}
        total = len(texts)
        completed = 0
        failed_texts: Dict[str, str] = {}
        residue_texts: Dict[str, str] = {}

        # 使用实例配置，允许传入覆盖
        effective_batch_size = batch_size if batch_size is not None else self.batch_size

        uncached_unique: List[str] = []
        pending_counts: Dict[str, int] = {}
        seen_uncached = set()

        def mark_incomplete(text: str, reason: str, translated: Optional[str] = None) -> None:
            key = str(text or "")
            if not key:
                return
            failed_texts.setdefault(key, reason)
            if translated is not None and self._has_japanese_residue(translated):
                residue_texts.setdefault(key, translated)

        def should_accept_translation(original: str, translated: Optional[str], reason: str = "") -> bool:
            if self._is_incomplete_translation(original, translated):
                mark_incomplete(original, reason or "译文为空或仍有日文残留", translated)
                return False
            return True

        # Phase 1-③: 预翻译计数
        pre_translated = 0
        manual_cache_hits = 0
        # Phase 1-②: 文本缓存命中计数
        text_cache_hits = 0

        with self._cache_lock:
            for text in texts:
                # ① 人工修改缓存优先级最高，不受模型和跨模型缓存开关影响。
                cache_key = self._cache_key(text)
                manual_cached = self._lookup_manual_cache(text)
                if manual_cached is not None and not self._is_incomplete_translation(text, manual_cached):
                    results[text] = manual_cached
                    self.cache[cache_key] = manual_cached
                    completed += 1
                    manual_cache_hits += 1
                    if item_callback:
                        item_callback(text, manual_cached)
                    continue

                # ② 模型缓存查找
                if cache_key in self.cache:
                    cached_translation = self.cache[cache_key]
                    if not self._is_incomplete_translation(text, cached_translation):
                        results[text] = cached_translation
                        completed += 1
                        continue
                    self.cache.pop(cache_key, None)
                    self._cache_dirty = True

                # ③ Phase 1-③: 本地预翻译规则
                pre_result = self._pre_translate(text)
                if pre_result is not None:
                    if self._is_incomplete_translation(text, pre_result):
                        pending_counts[text] = pending_counts.get(text, 0) + 1
                        if text not in seen_uncached:
                            uncached_unique.append(text)
                            seen_uncached.add(text)
                        continue
                    results[text] = pre_result
                    # 同步写入模型缓存
                    self.cache[cache_key] = pre_result
                    completed += 1
                    pre_translated += 1
                    if item_callback:
                        item_callback(text, pre_result)
                    continue

                # ④ Phase 1-②: 文本级缓存（跨模型，仅复用已校对译文）
                if getattr(self, "allow_text_cache_reuse", False):
                    text_cached = self._lookup_text_cache(text)
                    if text_cached is not None:
                        if not self._is_incomplete_translation(text, text_cached):
                            results[text] = text_cached
                            self.cache[cache_key] = text_cached
                            completed += 1
                            text_cache_hits += 1
                            if item_callback:
                                item_callback(text, text_cached)
                            continue

                # ⑤ 未命中，加入待翻译队列
                pending_counts[text] = pending_counts.get(text, 0) + 1
                if text not in seen_uncached:
                    uncached_unique.append(text)
                    seen_uncached.add(text)

        if manual_cache_hits:
            logger.info(f"人工译文缓存命中: {manual_cache_hits} 条")
        if pre_translated:
            logger.info(f"预翻译命中: {pre_translated} 条")
        if text_cache_hits:
            logger.info(f"文本缓存命中: {text_cache_hits} 条（跨模型）")
        logger.info(f"批量翻译: {total} 条，缓存命中 {completed} 条，待翻译去重后 {len(uncached_unique)} 条")

        if progress_callback:
            progress_callback(completed, total)

        if not uncached_unique:
            self._save_cache(force=True)
            if pre_translated or text_cache_hits:
                self._flush_text_cache()
            return results

        # ---- Phase 1-①: 智能分批 ----
        batches = self._smart_batch(uncached_unique, effective_batch_size)
        logger.info(f"智能分批为 {len(batches)} 个批次进行并发翻译")

        # Phase 2-④: 构建文本→索引映射，用原始文本顺序提供上下文。
        text_index_map: Dict[str, int] = {}
        context_sequence = list(context_texts or texts)
        if self.ENABLE_CONTEXT_WINDOW:
            for idx, text in enumerate(context_sequence):
                text_index_map.setdefault(text, idx)
            logger.info(f"上下文窗口已启用: {len(text_index_map)} 条文本已索引")

        def get_context_for_text(text: str) -> Tuple[Optional[str], Optional[str]]:
            if not self.ENABLE_CONTEXT_WINDOW or not text_index_map:
                return None, None
            idx = text_index_map.get(text, -1)
            if idx < 0:
                return None, None
            prev_text = context_sequence[idx - 1] if idx > 0 else None
            next_text = context_sequence[idx + 1] if idx + 1 < len(context_sequence) else None
            return prev_text, next_text

        def call_translate_chunk(text: str, prev_text: Optional[str] = None, next_text: Optional[str] = None) -> str:
            try:
                return self._translate_chunk(text, prev_text=prev_text, next_text=next_text)
            except TypeError as exc:
                # 兼容测试或旧子类 monkeypatch 的 _translate_chunk(text) 签名。
                message = str(exc)
                if "prev_text" in message or "next_text" in message or "positional" in message:
                    return self._translate_chunk(text)
                raise

        mismatch_count = 0

        def is_suspicious_pair(src: str, dst: str) -> bool:
            src = (src or "").strip()
            dst = (dst or "").strip()
            if not dst:
                return True
            if len(src) >= 20 and len(dst) <= 1:
                return True
            if len(dst) >= 8:
                most_common = max(dst.count(ch) for ch in set(dst))
                if most_common / max(1, len(dst)) >= 0.65:
                    return True
            if re.search(r"(.{2,10})\1{3,}", dst):
                return True
            return False

        def repair_batch_quality(batch: List[str], pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
            enable_proofread = bool(getattr(self, "enable_proofread", False))
            if len(pairs) <= 1 and not enable_proofread:
                return pairs

            suspicious_idx = set()
            proofread_issues: Dict[int, List[str]] = {}
            outputs = [((dst or "").strip()) for _, dst in pairs]
            dup_counter: Dict[str, int] = {}
            for out in outputs:
                dup_counter[out] = dup_counter.get(out, 0) + 1

            for i, (src, dst) in enumerate(pairs):
                clean_dst = (dst or "").strip()
                if is_suspicious_pair(src, clean_dst):
                    suspicious_idx.add(i)
                    continue
                if clean_dst and dup_counter.get(clean_dst, 0) >= 3 and len(set(batch)) >= 3:
                    suspicious_idx.add(i)
                    continue
                if enable_proofread:
                    issues = self._find_proofread_issues(src, clean_dst)
                    if issues:
                        # Phase 2-⑤: 校对分级 — 本地检查通过则跳过 LLM 校对
                        if self._should_skip_proofread(src, clean_dst):
                            logger.debug(f"校对分级跳过 [{i}]: 文本过短或匹配跳过模式")
                            continue
                        proofread_issues[i] = issues

            if proofread_issues:
                self._inc_stat("proofread_suspicious", len(proofread_issues))

            all_repair_idx = suspicious_idx | set(proofread_issues)
            if not all_repair_idx:
                return pairs

            logger.info(
                f"质检发现 {len(all_repair_idx)} 条可疑译文，"
                f"重译={sorted(suspicious_idx)}，校对={sorted(proofread_issues)}"
            )
            repaired = list(pairs)
            fixed_count = 0
            proofread_fixed = 0
            for i in sorted(all_repair_idx):
                src = batch[i]
                try:
                    if enable_proofread and i in proofread_issues and i not in suspicious_idx:
                        draft = repaired[i][1]
                        issues = list(proofread_issues[i])
                        proofread_prev, proofread_next = get_context_for_text(src)
                        try:
                            revised = self._proofread_translation(
                                src,
                                draft,
                                issues,
                                prev_text=proofread_prev,
                                next_text=proofread_next,
                            )
                        except TypeError as exc:
                            message = str(exc)
                            if "prev_text" in message or "next_text" in message or "unexpected keyword" in message:
                                revised = self._proofread_translation(src, draft, issues)
                            else:
                                raise
                        if any("日文" in issue or "假名" in issue for issue in issues) and self._has_japanese_residue(revised):
                            try:
                                fallback_prev, fallback_next = get_context_for_text(src)
                                fallback_revised = call_translate_chunk(src, fallback_prev, fallback_next)
                                if fallback_revised:
                                    revised = fallback_revised
                                issues.append("校对后仍残留日文，已回退单条重译")
                            except Exception as fallback_error:
                                logger.warning(f"校对后单条重译失败 [{i}]: {fallback_error}")
                        repaired[i] = (src, revised)
                        self._save_text_cache_entry(src, revised, verified=True)
                        proofread_fixed += 1
                        if proofread_callback:
                            detail = {
                                "original": src,
                                "draft": draft,
                                "revised": revised,
                                "issues": issues,
                                "japanese_residue": any("日文" in issue or "假名" in issue for issue in issues),
                                "glossary_mismatch": any("术语" in issue for issue in issues),
                            }
                            try:
                                proofread_callback(detail)
                            except Exception as callback_error:
                                logger.warning(f"译后校对详情回调失败: {callback_error}")
                    else:
                        repair_prev, repair_next = get_context_for_text(src)
                        repaired[i] = (src, call_translate_chunk(src, repair_prev, repair_next))
                    fixed_count += 1
                except Exception as e:
                    logger.warning(f"质检重译失败 [{i}]: {e}")
            if proofread_fixed:
                self._inc_stat("proofread_fixed", proofread_fixed)
            logger.info(f"质检修复完成，成功修复 {fixed_count}/{len(all_repair_idx)} 条")
            return repaired

        def translate_one_batch(batch: List[str]) -> List[Tuple[str, str]]:
            nonlocal mismatch_count
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")

            if len(batch) == 1:
                text = batch[0]
                prev_ctx, next_ctx = get_context_for_text(text)
                zh = call_translate_chunk(text, prev_ctx, next_ctx)
                return repair_batch_quality(batch, [(text, zh)])

            self._inc_stat("batch_total")
            # 优先使用结构化 JSON 返回，减少分割符丢失导致的拆分失败。
            item_contexts = (
                [get_context_for_text(text) for text in batch]
                if self.ENABLE_CONTEXT_WINDOW and self.ENABLE_BATCH_ITEM_CONTEXT
                else None
            )
            batch_prev_ctx, batch_next_ctx = get_context_for_text(batch[0])
            try:
                result = self._call_deepseek_batch_json(
                    batch,
                    prev_text=batch_prev_ctx,
                    next_text=batch_next_ctx,
                    item_contexts=item_contexts,
                )
            except TypeError as exc:
                if "item_contexts" not in str(exc):
                    raise
                result = self._call_deepseek_batch_json(
                    batch,
                    prev_text=batch_prev_ctx,
                    next_text=batch_next_ctx,
                )

            # Case 1: 全部成功（所有 idx 都有有效译文）
            if result.translations is not None and not result.missing_indices:
                json_parts = result.translations
                if isinstance(json_parts, list) and len(json_parts) == len(batch):
                    if self.extract_glossary and result.new_terms:
                        cleaned_terms = self._clean_new_terms(result.new_terms)
                        self._merge_new_terms_into_glossary(cleaned_terms)
                    self._inc_stat("batch_json_success")
                    return repair_batch_quality(batch, list(zip(batch, json_parts)))

            # Case 2: 部分成功 — 有效条目直接用，缺失条目单条重试
            if result.translations is not None and result.missing_indices:
                if self.extract_glossary and result.new_terms:
                    cleaned_terms = self._clean_new_terms(result.new_terms)
                    self._merge_new_terms_into_glossary(cleaned_terms)
                self._inc_stat("batch_json_success")
                self._inc_stat("batch_partial_retry")

                final_parts = list(result.translations)  # 复制
                for idx in result.missing_indices:
                    logger.info(f"部分成功重试: 缺失索引 {idx} 走单条翻译")
                    try:
                        retry_prev, retry_next = get_context_for_text(batch[idx])
                        final_parts[idx] = call_translate_chunk(batch[idx], retry_prev, retry_next)
                    except Exception as e:
                        logger.warning(f"单条重试失败 [idx={idx}]: {e}")
                        final_parts[idx] = None  # 保留为未完成，禁止回写原文

                return repair_batch_quality(batch, list(zip(batch, final_parts)))

            # Case 3: 全部失败 — 回退到分隔符批量
            separator = f"\n---SPLIT-{uuid.uuid4().hex}---\n"
            combined = separator.join(batch)
            combined_zh = self._call_deepseek(
                combined,
                text_separator=separator,
                prev_text=batch_prev_ctx,
                next_text=batch_next_ctx,
            )
            parts = combined_zh.split(separator)

            if len(parts) != len(batch):
                with self._cache_lock:
                    mismatch_count += 1
                self._inc_stat("batch_fallback")
                self._inc_stat("batch_split_mismatch")
                return [(t, call_translate_chunk(t, *get_context_for_text(t))) for t in batch]

            self._inc_stat("batch_delimiter_success")
            return repair_batch_quality(batch, list(zip(batch, parts)))

        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        futures = {}
        try:
            for batch in batches:
                if self.cancel_event.is_set():
                    raise RuntimeError("翻译已取消")
                futures[executor.submit(translate_one_batch, batch)] = batch

            # P3-⑦: 流式处理 — 使用 as_completed 让先完成的批次先回写
            # 相比 wait(pending, timeout=0.2) 轮询，as_completed 响应更及时
            pending_futures = set(futures)
            for future in as_completed(pending_futures):
                if self.cancel_event.is_set():
                    for f in pending_futures:
                        f.cancel()
                    self._save_cache(force=True)
                    raise RuntimeError("翻译已取消")

                try:
                    batch_results = future.result()
                    for original, translated in batch_results:
                        if not should_accept_translation(original, translated, "批次译文疑似未完成"):
                            continue
                        if self._should_write_cache():
                            with self._cache_lock:
                                self.cache[self._cache_key(original)] = translated
                        # Phase 1-②: 写入文本级缓存（非短文本才写入）
                        if len(original) > self.SMART_BATCH_SHORT:
                            self._save_text_cache_entry(original, translated, verified=False)
                        results[original] = translated
                        completed += pending_counts.get(original, 1)
                        if item_callback:
                            item_callback(original, translated)
                        if progress_callback:
                            progress_callback(completed, total)
                    if self._should_write_cache():
                        self._save_cache()
                except Exception as e:
                    logger.error(f"批次翻译失败: {e}")
                    if "502" in str(e):
                        raise
                    batch = futures[future]
                    for text in batch:
                        if self.cancel_event.is_set():
                            self._save_cache(force=True)
                            raise RuntimeError("翻译已取消")
                        try:
                            fallback_prev, fallback_next = get_context_for_text(text)
                            zh = call_translate_chunk(text, fallback_prev, fallback_next)
                            if not should_accept_translation(text, zh, "批次失败后的单条重试仍未完成"):
                                continue
                            results[text] = zh
                        except Exception as e2:
                            logger.error(f"翻译失败: {e2}")
                            mark_incomplete(text, f"单条重试失败: {e2}")
                            continue
                        completed += pending_counts.get(text, 1)
                        if item_callback:
                            item_callback(text, results[text])
                        if progress_callback:
                            progress_callback(completed, total)
        finally:
            executor.shutdown(wait=not self.cancel_event.is_set(), cancel_futures=True)

        self._save_cache(force=True)
        self._flush_text_cache()
        if mismatch_count:
            logger.warning(f"批量拆分回退 {mismatch_count} 次（模型输出与批次数不一致，已自动逐条翻译）")

        for text in texts:
            if text not in results:
                with self._cache_lock:
                    cached = self.cache.get(self._cache_key(text))
                if cached is not None:
                    if should_accept_translation(text, cached, "最终缓存补全疑似未完成"):
                        results[text] = cached
                    else:
                        with self._cache_lock:
                            self.cache.pop(self._cache_key(text), None)
                            self._cache_dirty = True
            elif not should_accept_translation(text, results.get(text), "最终校验发现译文仍未完成"):
                results.pop(text, None)

        missing_texts = [text for text in texts if text not in results]
        for text in missing_texts:
            mark_incomplete(text, "未返回安全译文")

        if failed_texts or residue_texts:
            unique_failed = list(dict.fromkeys(failed_texts.keys()))
            unique_residue = list(dict.fromkeys(residue_texts.keys()))
            if unique_failed:
                self._inc_stat("translation_incomplete", len(unique_failed))
            if unique_residue:
                self._inc_stat("japanese_residue_remaining", len(unique_residue))
            sample = " | ".join(unique_failed[:3])
            logger.error(
                "翻译未完成：%s 条未成功翻译，%s 条疑似日文残留。样例: %s",
                len(unique_failed),
                len(unique_residue),
                sample or "-",
            )
            raise TranslationIncompleteError(
                failed_texts=unique_failed,
                residue_texts=unique_residue,
                partial_results=results,
            )

        if progress_callback and completed < total:
            progress_callback(total, total)

        return results

    def __del__(self):
        """析构时保存缓存"""
        try:
            self.flush_cache()
            self.session.close()
        except Exception:
            pass
