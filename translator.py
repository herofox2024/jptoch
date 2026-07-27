import asyncio
import json
import logging
import os
import random
import re
import hashlib
import sys
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests
try:
    import httpx
except Exception:  # pragma: no cover - optional speed-up dependency
    httpx = None
try:
    import json_repair
except Exception:  # pragma: no cover - optional dependency
    json_repair = None
import translation_quality as tq
from glossary_store import normalize_glossary_payload as gs_normalize_glossary_payload
from glossary_store import merge_glossaries as gs_merge_glossaries
from glossary_store import clean_new_terms as gs_clean_new_terms
from glossary_store import glossary_prompt_payload as gs_glossary_prompt_payload
from glossary_store import select_glossary_entries as gs_select_glossary_entries
from glossary_store import build_glossary_text as gs_build_glossary_text
from glossary_store import rebuild_glossary_index as gs_rebuild_glossary_index
from glossary_store import has_valid_glossary_match as gs_has_valid_glossary_match
from glossary_store import normalize_policy as gs_normalize_policy
from provider_registry import (
    API_KEY_REQUIRED_PROVIDERS,
    PROVIDER_DEFAULTS,
    SUPPORTED_PROVIDERS,
    normalize_api_url,
    provider_default_model,
    provider_default_url,
    provider_env_api_key,
)
from provider_client import (
    CONTENT_MODERATION_SNIPPETS,
    apply_payload_options,
    create_session,
    is_auth_http_error,
    is_content_moderation_http_error,
    response_snippet,
)
from quality_rules import is_suspicious_translation_pair
from style_detector import GENRE_LABELS, TONE_LABELS
from translation_cache import (
    atomic_write_json as tc_atomic_write_json,
    cache_digest as tc_cache_digest,
    context_cache_key as tc_context_cache_key,
    load_json_file as tc_load_json_file,
    model_cache_key as tc_model_cache_key,
    parse_model_cache_key as tc_parse_model_cache_key,
    text_cache_key as tc_text_cache_key,
)

try:
    from backend import request_log as qml_request_log
except Exception:  # pragma: no cover - non-QML entry points can run without it
    try:
        from experimental.qml_v4.backend import request_log as qml_request_log
    except Exception:  # pragma: no cover
        qml_request_log = None


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


GLOSSARY_EXTRACTION_MODES = {"novel", "lite"}


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

DEEPSEEK_API_URL = provider_default_url("deepseek")
DEEPSEEK_MODEL = provider_default_model("deepseek")
DOUBAO_API_URL = provider_default_url("doubao")
DOUBAO_MODEL = provider_default_model("doubao")
SAKURA_API_URL = provider_default_url("sakura")
SAKURA_MODEL = provider_default_model("sakura")
GEMINI_API_URL = provider_default_url("gemini")
GEMINI_MODEL = provider_default_model("gemini")
GLM_API_URL = provider_default_url("glm")
GLM_MODEL = provider_default_model("glm")
WENXIN_API_URL = provider_default_url("wenxin")
WENXIN_MODEL = provider_default_model("wenxin")
LONGCAT_API_URL = provider_default_url("longcat")
LONGCAT_MODEL = provider_default_model("longcat")
DEFAULT_TEXT_SEPARATOR = "\n---SPLIT---\n"


class _HttpxResponseAdapter:
    """Small adapter exposing the requests.Response subset used by this module."""

    def __init__(self, status_code: int, text: str, url: str, json_data: Optional[Dict[str, Any]] = None):
        self.status_code = int(status_code)
        self.text = text or ""
        self.url = url or ""
        self._json_data = json_data

    def json(self) -> Dict[str, Any]:
        if self._json_data is not None:
            return self._json_data
        return json.loads(self.text or "{}")

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        raise requests.exceptions.HTTPError(
            f"{self.status_code} Error for url: {self.url}",
            response=self,
        )


class _AsyncHttpJsonExecutor:
    """Run OpenAI-compatible JSON POST calls through one httpx.AsyncClient pool."""

    def __init__(self, max_connections: int):
        if httpx is None:
            raise RuntimeError("httpx is not available")
        self._max_connections = max(1, int(max_connections or 1))
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._client = None
        self._thread = threading.Thread(target=self._run_loop, name="translator-httpx", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        limits = httpx.Limits(
            max_connections=self._max_connections * 2,
            max_keepalive_connections=self._max_connections,
        )
        self._client = httpx.AsyncClient(limits=limits, trust_env=True)
        self._ready.set()
        self._loop.run_forever()

    async def _post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> _HttpxResponseAdapter:
        assert self._client is not None
        try:
            resp = await self._client.post(url, headers=headers, json=payload, timeout=float(timeout))
            text = resp.text or ""
            try:
                json_data = resp.json()
            except Exception:
                json_data = None
            return _HttpxResponseAdapter(resp.status_code, text, str(resp.url), json_data)
        except httpx.TimeoutException as exc:
            raise requests.exceptions.Timeout(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise requests.exceptions.ConnectionError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise requests.exceptions.RequestException(str(exc)) from exc

    def post(self, url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int) -> _HttpxResponseAdapter:
        if self._closed.is_set():
            raise requests.exceptions.ConnectionError("async http executor is closed")
        future = asyncio.run_coroutine_threadsafe(
            self._post(url, headers, payload, timeout),
            self._loop,
        )
        return future.result(timeout=max(float(timeout) + 10.0, 15.0))

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()

        async def _close_client():
            if self._client is not None:
                await self._client.aclose()

        try:
            future = asyncio.run_coroutine_threadsafe(_close_client(), self._loop)
            future.result(timeout=5)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


class FastFailError(RuntimeError):
    """用于标识应立即中断流程的不可恢复错误（如明确配置的 HTTP 502）。"""


class ContentModerationError(RuntimeError):
    """Raised when an upstream provider rejects the batch because its content
    moderation filter flags one or more source texts. Unlike FastFailError this
    does NOT abort the whole pipeline — callers should split the batch and retry
    each item on its own so only the offending text is lost."""

    def __init__(self, message: str, offending_indices: Optional[List[int]] = None):
        super().__init__(message)
        self.offending_indices = list(offending_indices or [])


class TranslationIncompleteError(RuntimeError):
    """Raised when some texts could not be safely translated."""

    def __init__(
        self,
        failed_texts: Optional[List[str]] = None,
        residue_texts: Optional[List[str]] = None,
        partial_results: Optional[Dict[str, str]] = None,
        failed_details: Optional[List[Dict[str, Any]]] = None,
        residue_details: Optional[List[Dict[str, Any]]] = None,
    ):
        self.failed_texts = list(dict.fromkeys(failed_texts or []))
        self.residue_texts = list(dict.fromkeys(residue_texts or []))
        self.partial_results = dict(partial_results or {})
        self.failed_details = self._normalize_failed_details(failed_details, self.failed_texts)
        self.residue_details = self._normalize_residue_details(residue_details, self.residue_texts)
        message = (
            f"翻译未完成：{len(self.failed_texts)} 条未成功翻译，"
            f"{len(self.residue_texts)} 条疑似仍有日文残留。"
            "已保留成功译文缓存，请降低并发/批量或切换模型后恢复续译。"
        )
        super().__init__(message)

    @staticmethod
    def _snippet(text: Any, limit: int = 220) -> str:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    @classmethod
    def _normalize_failed_details(
        cls,
        details: Optional[List[Dict[str, Any]]],
        fallback_texts: List[str],
    ) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        seen = set()
        for item in details or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or item.get("original") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(
                {
                    "text": text,
                    "reason": str(item.get("reason") or "未返回安全译文"),
                }
            )
        for text in fallback_texts:
            if text not in seen:
                seen.add(text)
                normalized.append({"text": text, "reason": "未返回安全译文"})
        return normalized

    @classmethod
    def _normalize_residue_details(
        cls,
        details: Optional[List[Dict[str, Any]]],
        fallback_texts: List[str],
    ) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for item in details or []:
            if not isinstance(item, dict):
                continue
            original = str(item.get("original") or item.get("text") or "").strip()
            if not original or original in seen:
                continue
            fragments = item.get("fragments") or []
            if isinstance(fragments, str):
                fragments = [fragments]
            fragments = [str(fragment).strip() for fragment in fragments if str(fragment).strip()]
            seen.add(original)
            normalized.append(
                {
                    "original": original,
                    "translated": str(item.get("translated") or ""),
                    "fragments": list(dict.fromkeys(fragments)),
                    "reason": str(item.get("reason") or "译文疑似仍有日文残留"),
                }
            )
        for text in fallback_texts:
            if text not in seen:
                seen.add(text)
                normalized.append(
                    {
                        "original": text,
                        "translated": "",
                        "fragments": [],
                        "reason": "译文疑似仍有日文残留",
                    }
                )
        return normalized

    def format_diagnostics(self, max_items: int = 5) -> str:
        """Format actionable diagnostics for logs and UI error panels."""
        lines = [
            (
                f"翻译未完成诊断：未成功翻译 {len(self.failed_texts)} 条，"
                f"疑似日文残留 {len(self.residue_texts)} 条。"
            )
        ]
        if self.failed_details:
            lines.append("[失败样例]")
            for index, detail in enumerate(self.failed_details[:max_items], 1):
                lines.append(f"{index}. 原文: {self._snippet(detail.get('text'))}")
                lines.append(f"   原因: {self._snippet(detail.get('reason'), 120)}")
        if self.residue_details:
            lines.append("[日文残留样例]")
            for index, detail in enumerate(self.residue_details[:max_items], 1):
                fragments = detail.get("fragments") or []
                fragment_text = "、".join(fragments[:8]) if fragments else "未知片段"
                lines.append(f"{index}. 残留片段: {self._snippet(fragment_text, 160)}")
                lines.append(f"   原文: {self._snippet(detail.get('original'))}")
                translated = self._snippet(detail.get("translated"))
                if translated:
                    lines.append(f"   译文: {translated}")
                reason = self._snippet(detail.get("reason"), 120)
                if reason:
                    lines.append(f"   原因: {reason}")
        return "\n".join(lines)


def get_data_dir() -> Path:
    """获取用户数据目录，用于存储缓存和配置"""
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(exist_ok=True)
    return data_dir


tq.configure_data_dir(get_data_dir)


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
    JAPANESE_KANA_RE = tq.JAPANESE_KANA_RE
    JAPANESE_KANA_FRAGMENT_RE = tq.JAPANESE_KANA_FRAGMENT_RE
    JAPANESE_QUOTED_TEXT_RE = tq.JAPANESE_QUOTED_TEXT_RE
    JAPANESE_SHORT_QUOTED_TEXT_RE = tq.JAPANESE_SHORT_QUOTED_TEXT_RE
    JAPANESE_SINGLE_KATAKANA_RE = tq.JAPANESE_SINGLE_KATAKANA_RE
    SHA256_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
    JAPANESE_O_NAME_PREFIX_RE = tq.JAPANESE_O_NAME_PREFIX_RE
    JAPANESE_O_PREFIX_NON_PERSON_STEMS = tq.JAPANESE_O_PREFIX_NON_PERSON_STEMS
    JAPANESE_RESIDUE_ALLOWLIST_FILE = tq.JAPANESE_RESIDUE_ALLOWLIST_FILE
    _japanese_residue_allowlist_cache: Optional[Dict[str, Any]] = None
    _japanese_residue_allowlist_mtime: Optional[float] = None
    _japanese_residue_allowlist_checked_at = 0.0
    _japanese_residue_allowlist_check_interval = 5.0
    # 允许中文译文中的字形描述，例如“コ”字形、コ字型、ロの字形。
    # 这些是形状标记，不是未翻译日文残留；更长的假名片段仍会被检测。
    ALLOWED_JAPANESE_SHAPE_NOTATION_RE = tq.ALLOWED_JAPANESE_SHAPE_NOTATION_RE
    ALLOWED_LATIN_MIDDLE_DOT_RE = tq.ALLOWED_LATIN_MIDDLE_DOT_RE
    JAPANESE_EXPLANATORY_QUOTE_CUE_RE = tq.JAPANESE_EXPLANATORY_QUOTE_CUE_RE
    JAPANESE_READING_PUZZLE_RUN_RE = tq.JAPANESE_READING_PUZZLE_RUN_RE
    JAPANESE_READING_PUZZLE_CONTEXT_RE = tq.JAPANESE_READING_PUZZLE_CONTEXT_RE

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
        # 短标题/诗句。模型偶尔会把这类孤立短句返回为空或跳过，导致整本书保存前失败。
        "旅ゆけば": "旅行之中",
        "「性が合わぬとは……？」": "“性情不合是指……？”",
        "伊織は、『昔、飛衛といふ者あり』という兵法書の書き出しを、思い出していた。": "伊织想起了那本兵法书开头写着的《昔日有飞卫其人》。",
        "「腹を切るほうが、よほど楽であり容易でもあろう。しかし、武士の切腹というものは、何ゆえに自害いたさねばならなかったのかと、世の中のさまざまな思惑を招くことになる。勇之介は事を荒立てまいと、手合わせに敗れたふうを装ったのだ」": "“切腹或许要轻松容易得多。可是，武士一旦切腹，世人就会揣测他为何非得自害不可，引来种种议论。勇之介是不想把事情闹大，才装作是在交手中败下阵来的样子。”",
    }

    # ---- Phase 1-①: 智能分批阈值 ----
    SMART_BATCH_SHORT = 30    # 短文本上限（称呼、语气词、短对话）
    SMART_BATCH_LONG = 200    # 长文本下限（整段叙述，单独处理）

    STYLE_FEW_SHOT_EXAMPLES: Dict[str, Tuple[str, str]] = {
        "general": (
            "彼女は小さく息をつき、窓の外へ目を向けた。",
            "她轻轻叹了口气，将目光投向窗外。",
        ),
        "mystery": (
            "鍵は内側から掛かっていた。だが、床には濡れた足跡が一つだけ残っていた。",
            "门是从里面锁上的。然而，地板上只留下了一枚湿漉漉的脚印。",
        ),
        "historical_mystery": (
            "与力の前で、辰造はあえて口を噤んだ。",
            "在与力面前，辰造有意闭口不言。",
        ),
        "scifi": (
            "端末の警告灯が点滅し、隔壁の向こうで冷却炉が唸り始めた。",
            "终端的警示灯开始闪烁，隔壁另一侧的冷却炉低声轰鸣起来。",
        ),
        "fantasy": (
            "古い紋章が光を帯びると、封じられていた門が静かに開いた。",
            "古老纹章泛起光芒，被封印的大门静静开启。",
        ),
    }
    TONE_FEW_SHOT_EXAMPLES: Dict[str, Tuple[str, str]] = {
        "neutral": (
            "それでも、彼は最後まで理由を語らなかった。",
            "即便如此，他直到最后也没有说出理由。",
        ),
        "light": (
            "「ちょっと待ってよ。なんで私まで行くことになってるの？」",
            "“等一下啦。为什么连我也得一起去啊？”",
        ),
        "literary": (
            "雨音だけが、長い沈黙の隙間を静かに満たしていた。",
            "唯有雨声，静静填满漫长沉默之间的空隙。",
        ),
    }

    # ---- Phase 2-④: 上下文窗口翻译 ----
    ENABLE_CONTEXT_WINDOW = True   # 是否启用上下文窗口
    ENABLE_BATCH_ITEM_CONTEXT = False  # 批量 JSON 不默认给每条塞 prev/next，避免大幅增加 token
    CONTEXT_PREVIEW_LEN = 80       # 前后文预览最大字符数
    DEEPSEEK_CONTEXT_WINDOW_MAX_TEXTS = 2000
    LONGCAT_CONTEXT_WINDOW_MAX_TEXTS = 2000
    FAST_BATCH_PROVIDERS = {"deepseek", "longcat"}
    FAST_BATCH_MIN_TEXTS = 2000
    FAST_BATCH_MAX_ITEMS = 16
    FAST_BATCH_PROVIDER_MAX_ITEMS = {
        "longcat": 6,
    }
    FAST_BATCH_MAX_CHARS = 2600
    FAST_BATCH_LONG_THRESHOLD = 700
    RATE_WINDOW_SECONDS = 60.0
    PROVIDER_RATE_PRESETS: Dict[str, Dict[str, int]] = {
        "deepseek": {"rpm": 36, "tpm": 120000, "max_workers": 6, "batch_size": 6},
        "longcat": {"rpm": 24, "tpm": 90000, "max_workers": 4, "batch_size": 4},
    }

    def _provider_uses_context_window(self) -> bool:
        """Hy-MT2 is prone to leaking reference context into the translation."""
        return self.ENABLE_CONTEXT_WINDOW and self.provider != "hymt2"

    def _provider_uses_context_window_for_task(self, total_texts: int) -> bool:
        """Disable per-batch context on large books where context increases latency more than quality."""
        if not self._provider_uses_context_window():
            return False
        if self.provider == "deepseek" and int(total_texts or 0) > self.DEEPSEEK_CONTEXT_WINDOW_MAX_TEXTS:
            return False
        if self.provider == "longcat" and int(total_texts or 0) > self.LONGCAT_CONTEXT_WINDOW_MAX_TEXTS:
            return False
        return True

    def _fast_batch_max_items_for_provider(self) -> int:
        provider = (self.provider or "").strip().lower()
        return max(1, int(self.FAST_BATCH_PROVIDER_MAX_ITEMS.get(provider, self.FAST_BATCH_MAX_ITEMS)))

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
    _PROVIDER_URLS: Dict[str, str] = {key: value.api_url for key, value in PROVIDER_DEFAULTS.items()}
    _PROVIDER_MODELS: Dict[str, str] = {key: value.model for key, value in PROVIDER_DEFAULTS.items()}

    @classmethod
    def _get_provider_default_url(cls, provider: str) -> str:
        return provider_default_url(provider)

    @classmethod
    def _get_provider_default_model(cls, provider: str) -> str:
        return provider_default_model(provider)

    @classmethod
    def _get_provider_rate_profile(cls, provider: str) -> Dict[str, int]:
        return dict(cls.PROVIDER_RATE_PRESETS.get((provider or "").strip().lower(), {}))

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
        top_k: Optional[int] = None,
        repetition_penalty: Optional[float] = None,
        max_tokens: Optional[int] = None,
        frequency_penalty: Optional[float] = None,
        glossary_path: Optional[str] = None,
        glossary_override: Optional[Dict[str, Any]] = None,
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
        prompt_extra_instruction: str = "",
        enable_prompt_examples: bool = True,
        hymt2_generation_mode: str = "stable",
        hymt2_prompt_mode: str = "official",
        hymt2_runtime_mode: str = "cpu",
        glossary_extraction_mode: str = "novel",
        glossary_fingerprint: str = "",
    ):
        self.provider = (provider or "deepseek").strip().lower()
        # preset 参数已弃用，不再应用预设，由调用方直接传递参数值
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"不支持的提供方: {provider}")

        self.api_key = api_key or provider_env_api_key(self.provider)
        if self.provider in {"sakura", "hymt2"} and not self.api_key:
            # 本地 OpenAI 兼容服务通常可无鉴权，默认给一个占位 key，兼容部分网关。
            self.api_key = "sk-local"
        if not self.api_key:
            if self.provider in API_KEY_REQUIRED_PROVIDERS:
                raise ValueError(f"未找到 {self.provider} API Key，请在界面输入或设置对应环境变量")

        default_url = provider_default_url(self.provider)
        default_model = provider_default_model(self.provider)

        raw_api_url = (api_url or default_url).strip()
        self.api_url = self._normalize_api_url(raw_api_url)
        self.model = (model or default_model).strip()
        self.hymt2_generation_mode = str(hymt2_generation_mode or "stable").strip().lower()
        if self.hymt2_generation_mode not in {"stable", "official"}:
            self.hymt2_generation_mode = "stable"
        self.hymt2_prompt_mode = str(hymt2_prompt_mode or "official").strip().lower()
        if self.hymt2_prompt_mode not in {"official", "project"}:
            self.hymt2_prompt_mode = "official"
        self.hymt2_runtime_mode = str(hymt2_runtime_mode or "cpu").strip().lower()
        if self.hymt2_runtime_mode not in {"cpu", "gpu"}:
            self.hymt2_runtime_mode = "cpu"
        self.glossary_extraction_mode = self._normalize_glossary_extraction_mode(glossary_extraction_mode)
        hymt2_official_mode = self.provider == "hymt2" and self.hymt2_generation_mode == "official"
        default_temperature = 0.7 if hymt2_official_mode else (0.1 if self.provider in {"sakura", "hymt2"} else 0.3)
        default_top_p = 0.6 if hymt2_official_mode else (0.3 if self.provider in {"sakura", "hymt2"} else None)
        self.temperature = temperature if temperature is not None else default_temperature
        self.top_p = top_p if top_p is not None else default_top_p
        self.top_k = int(top_k) if top_k is not None else (20 if hymt2_official_mode else None)
        self.repetition_penalty = (
            float(repetition_penalty)
            if repetition_penalty is not None
            else (1.05 if hymt2_official_mode else None)
        )
        self.max_tokens = int(max_tokens) if max_tokens is not None else (4096 if hymt2_official_mode else None)
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
        if self.provider == "hymt2":
            old_workers, old_batch = max_workers, batch_size
            if self.hymt2_runtime_mode == "gpu":
                max_workers = min(max_workers, 6)
                batch_size = min(batch_size, 8)
                max_batch_length = min(max_batch_length, 1000)
                max_text_size_for_batch = min(max_text_size_for_batch, 250)
            else:
                max_workers = min(max_workers, 1)
                batch_size = min(batch_size, 1)
                max_batch_length = min(max_batch_length, 300)
                max_text_size_for_batch = min(max_text_size_for_batch, 120)
            api_timeout = max(api_timeout, 300)
            if (old_workers, old_batch) != (max_workers, batch_size):
                logger.info(
                    "Hy-MT2 本地%s模式: 并发 %s→%s，批量 %s→%s",
                    "GPU" if self.hymt2_runtime_mode == "gpu" else "CPU",
                    old_workers,
                    max_workers,
                    old_batch,
                    batch_size,
                )
        endpoint_hint = f"{self.api_url} {self.model}".lower()
        if "longcat" in endpoint_hint:
            old_workers, old_batch = max_workers, batch_size
            max_workers = min(max_workers, 4)
            batch_size = min(batch_size, 4)
            if (old_workers, old_batch) != (max_workers, batch_size):
                logger.info(
                    "LongCat 稳定性保护: 并发 %s→%s，批量 %s→%s",
                    old_workers,
                    max_workers,
                    old_batch,
                    batch_size,
                )

        rate_profile = self._get_provider_rate_profile(self.provider)
        if rate_profile:
            old_workers, old_batch = max_workers, batch_size
            profile_workers = int(rate_profile.get("max_workers") or 0)
            profile_batch = int(rate_profile.get("batch_size") or 0)
            if profile_workers > 0:
                max_workers = min(max_workers, profile_workers)
            if profile_batch > 0:
                batch_size = min(batch_size, profile_batch)
            if (old_workers, old_batch) != (max_workers, batch_size):
                logger.info(
                    "%s 预设限制: 并发 %s→%s，批量 %s→%s",
                    self.provider,
                    old_workers,
                    max_workers,
                    old_batch,
                    batch_size,
                )
        self._provider_rpm_limit = int(rate_profile.get("rpm") or 0)
        self._provider_tpm_limit = int(rate_profile.get("tpm") or 0)

        data_dir = get_data_dir()
        self.glossary_path = glossary_path or str(data_dir / "glossary.json")
        self.glossary_fingerprint = re.sub(r"[^0-9a-f]", "", str(glossary_fingerprint or "").lower())[:16]
        self.cache_path = cache_path or str(data_dir / "cache.json")
        self.enable_glossary = bool(enable_glossary)

        override_glossary = None
        if glossary_override is not None:
            override_glossary, _ = gs_normalize_glossary_payload(glossary_override or {})
            has_terms = any(bool(override_glossary.get(category)) for category in DEFAULT_GLOSSARY_CATEGORIES)
            if has_terms and not self.glossary_fingerprint:
                prompt_glossary = gs_glossary_prompt_payload(override_glossary)
                compact = json.dumps(prompt_glossary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                self.glossary_fingerprint = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:16]

        if self.enable_glossary:
            self.glossary = override_glossary if override_glossary is not None else self._load_json(self.glossary_path, {})
        else:
            self.glossary = {}
        self.cache = self._load_json(self.cache_path, {})
        self._cross_model_text_cache_index: Dict[str, str] = {}
        self._cross_model_context_cache_index: Dict[Tuple[str, str], str] = {}
        self._cross_model_cache_index_built = False

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
        self._dynamic_limit_lock = threading.RLock()
        self._dynamic_max_workers = max(1, int(max_workers or 1))
        self._dynamic_batch_size = max(1, int(batch_size or 1))
        self._dynamic_backoff_until = 0.0
        self._dynamic_limit_events = 0
        self._dynamic_success_count = 0
        self._proofread_auth_failed = False
        self.cancel_event = cancel_event or threading.Event()
        # 连接池大小与并发数匹配，避免 "Connection pool is full" 警告
        self.session = create_session(self.max_workers)
        self._provider_rate_lock = threading.RLock()
        self._provider_rate_requests: deque[float] = deque()
        self._provider_rate_tokens: deque[Tuple[float, int]] = deque()
        self._async_http_executor = None
        if httpx is not None and self.provider in self.FAST_BATCH_PROVIDERS:
            try:
                self._async_http_executor = _AsyncHttpJsonExecutor(self.max_workers)
                logger.info("批量 JSON 已启用 httpx 异步连接池: provider=%s, max_connections=%s", self.provider, self.max_workers)
            except Exception as exc:
                logger.warning("httpx 异步连接池初始化失败，回退 requests: %s", exc)
        self.extract_glossary = bool(extract_glossary)
        self.enable_thinking = bool(enable_thinking)
        self.enable_proofread = bool(enable_proofread)
        self.proofread_genre = proofread_genre if proofread_genre in GENRE_LABELS else "general"
        self.proofread_tone = proofread_tone if proofread_tone in TONE_LABELS else "neutral"
        self.prompt_extra_instruction = str(prompt_extra_instruction or "").strip()
        self.enable_prompt_examples = bool(enable_prompt_examples)
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
            "batch_json_lenient_success": 0,
            "truncation_continuation": 0,
            "glossary_new_terms_added": 0,
            "proofread_suspicious": 0,
            "proofread_fixed": 0,
            "proofread_rejected": 0,
            "quality_retranslate": 0,
            "translation_incomplete": 0,
            "japanese_residue_remaining": 0,
            "dynamic_limit_events": 0,
            "rate_limit_events": 0,
            "dynamic_limit_workers": self._dynamic_max_workers,
            "dynamic_limit_batch_size": self._dynamic_batch_size,
            "proofread_batch_requests": 0,
            "proofread_batch_success": 0,
            "proofread_batch_lenient_success": 0,
            "translate_total_texts": 0,
            "translate_cache_hits": 0,
            "translate_pending_unique": 0,
            "translate_planned_batches": 0,
            "translate_context_cache_tasks": 0,
            "translate_elapsed_ms": 0,
            "translate_fast_batch_mode": 0,
            "async_httpx_available": 1 if httpx is not None else 0,
            "async_httpx_requests": 0,
        }
        logger.info(
            f"翻译器初始化完成: provider={self.provider}, model={self.model}, "
            f"并发数={self.max_workers}, 批量大小={self.batch_size}"
        )
        if self.provider == "hymt2":
            logger.info(
                "Hy-MT2 生成模式: %s, Prompt模式: %s, 运行模式: %s, temperature=%s, top_p=%s, top_k=%s, repetition_penalty=%s, max_tokens=%s",
                self.hymt2_generation_mode,
                self.hymt2_prompt_mode,
                self.hymt2_runtime_mode,
                self.temperature,
                self.top_p,
                self.top_k,
                self.repetition_penalty,
                self.max_tokens,
            )

    def _apply_provider_payload_options(self, payload: Dict[str, Any], provider: Optional[str] = None) -> None:
        """为特定提供方追加请求参数。"""
        active_provider = (provider or self.provider or "").strip().lower()
        apply_payload_options(payload, active_provider, self.enable_thinking)
        if active_provider == "hymt2":
            if self.top_k is not None:
                payload["top_k"] = self.top_k
            if self.repetition_penalty is not None:
                payload["repetition_penalty"] = self.repetition_penalty
                payload["repeat_penalty"] = self.repetition_penalty
            if self.max_tokens is not None:
                payload["max_tokens"] = self.max_tokens

    def _post_batch_json_payload(
        self,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        *,
        messages: Optional[List[Dict[str, Any]]] = None,
        source_text: Optional[Any] = None,
        batch_size: int = 1,
        context: str = "批量JSON翻译",
    ):
        """POST batch JSON requests through httpx pool when available, otherwise requests."""
        self._wait_provider_rate_budget(
            estimated_tokens=self._estimate_request_tokens(messages=messages, source_text=source_text, batch_size=batch_size),
            estimated_requests=1,
            context=context,
        )
        executor = getattr(self, "_async_http_executor", None)
        if executor is not None:
            self._inc_stat("async_httpx_requests")
            return executor.post(self.api_url, headers, payload, self.API_TIMEOUT)
        return self.session.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=self.API_TIMEOUT,
        )

    def _estimate_request_tokens(
        self,
        messages: Optional[List[Dict[str, Any]]] = None,
        source_text: Optional[Any] = None,
        batch_size: int = 1,
    ) -> int:
        parts: List[str] = []
        for message in messages or []:
            if isinstance(message, dict):
                content = str(message.get("content") or "").strip()
                if content:
                    parts.append(content)
            elif message is not None:
                content = str(message).strip()
                if content:
                    parts.append(content)
        if source_text is not None:
            if isinstance(source_text, str):
                text = source_text.strip()
            else:
                try:
                    text = json.dumps(source_text, ensure_ascii=False)
                except Exception:
                    text = str(source_text)
            text = str(text or "").strip()
            if text:
                parts.append(text)
        total_chars = sum(len(part) for part in parts)
        estimated = max(1, int(total_chars / 4) + max(1, int(batch_size or 1)) * 12)
        return estimated

    def _wait_provider_rate_budget(
        self,
        *,
        estimated_tokens: int = 0,
        estimated_requests: int = 1,
        context: str = "",
    ) -> None:
        rpm = max(0, int(getattr(self, "_provider_rpm_limit", 0) or 0))
        tpm = max(0, int(getattr(self, "_provider_tpm_limit", 0) or 0))
        if rpm <= 0 and tpm <= 0:
            return

        estimated_tokens = max(1, int(estimated_tokens or 1))
        estimated_requests = max(1, int(estimated_requests or 1))
        now = time.time()
        with self._provider_rate_lock:
            while True:
                cutoff = now - self.RATE_WINDOW_SECONDS
                while self._provider_rate_requests and self._provider_rate_requests[0] <= cutoff:
                    self._provider_rate_requests.popleft()
                while self._provider_rate_tokens and self._provider_rate_tokens[0][0] <= cutoff:
                    self._provider_rate_tokens.popleft()

                request_count = len(self._provider_rate_requests)
                token_count = sum(tokens for _, tokens in self._provider_rate_tokens)
                wait_seconds = 0.0

                if rpm > 0 and request_count + estimated_requests > rpm and self._provider_rate_requests:
                    oldest_request = self._provider_rate_requests[0]
                    wait_seconds = max(wait_seconds, self.RATE_WINDOW_SECONDS - (now - oldest_request))

                if tpm > 0 and token_count + estimated_tokens > tpm and self._provider_rate_tokens:
                    running_tokens = token_count
                    for ts, tokens in self._provider_rate_tokens:
                        running_tokens -= tokens
                        if running_tokens + estimated_tokens <= tpm:
                            wait_seconds = max(wait_seconds, self.RATE_WINDOW_SECONDS - (now - ts))
                            break

                if wait_seconds <= 0:
                    self._provider_rate_requests.append(now)
                    self._provider_rate_tokens.append((now, estimated_tokens))
                    return

                logger.info(
                    "%s 触发 provider 预限流: provider=%s, rpm=%s, tpm=%s, 预计等待 %.1fs",
                    context or "API请求",
                    self.provider,
                    rpm,
                    tpm,
                    wait_seconds,
                )
                if self.cancel_event.wait(wait_seconds):
                    raise RuntimeError("翻译已取消")
                now = time.time()

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
        return normalize_api_url(url)

    @staticmethod
    def _extract_json_object(raw: str, prefer_new_terms: bool = False) -> Optional[dict]:
        """从模型返回中提取 JSON，兼容对象、数组、代码块与前后说明文字。"""
        if not raw:
            return None
        text = raw.strip()

        def looks_like_translation_list(value: Any) -> bool:
            if not isinstance(value, list) or not value:
                return False
            for item in value[:3]:
                if isinstance(item, str):
                    return True
                if isinstance(item, dict) and (
                    any(key in item for key in ("zh", "translation", "translated", "text", "cn", "中文", "dst", "revised"))
                    or any(key in item for key in ("idx", "index", "id"))
                ):
                    return True
            return False

        def looks_like_glossary_terms_list(value: Any) -> bool:
            if not isinstance(value, list) or not value:
                return False
            for item in value[:3]:
                if isinstance(item, dict) and any(
                    key in item for key in ("src", "original", "dst", "translation", "category", "policy", "info")
                ):
                    return True
            return False

        def coerce(value: Any, allow_list: bool = True) -> Optional[dict]:
            if isinstance(value, dict):
                return value
            if allow_list and prefer_new_terms and looks_like_glossary_terms_list(value):
                return {"new_terms": value}
            if allow_list and looks_like_translation_list(value):
                return {"translations": value, "new_terms": []}
            return None

        def is_batch_container(value: Optional[dict]) -> bool:
            return isinstance(value, dict) and any(key in value for key in ("translations", "items", "new_terms"))

        def parse_candidate(candidate: str) -> Optional[dict]:
            candidate = (candidate or "").strip()
            if not candidate:
                return None
            try:
                parsed = json.loads(candidate)
                coerced = coerce(parsed, allow_list=True)
                if coerced is not None:
                    return coerced
            except (json.JSONDecodeError, ValueError):
                if json_repair is not None:
                    try:
                        parsed = json_repair.loads(candidate)
                        coerced = coerce(parsed, allow_list=True)
                        if coerced is not None:
                            return coerced
                    except Exception:
                        pass
            decoder = json.JSONDecoder()
            fallback = None
            for match in re.finditer(r"[\{\[]", candidate):
                try:
                    parsed, _ = decoder.raw_decode(candidate[match.start():])
                except (json.JSONDecodeError, ValueError):
                    if json_repair is not None:
                        try:
                            parsed = json_repair.loads(candidate[match.start():])
                        except Exception:
                            continue
                    else:
                        continue
                allow_list = True
                if isinstance(parsed, list):
                    prefix = candidate[max(0, match.start() - 40):match.start()]
                    allow_list = match.start() == 0 or bool(
                        re.search(r'"(?:translations|items)"\s*:\s*$', prefix)
                    )
                coerced = coerce(parsed, allow_list=allow_list)
                if is_batch_container(coerced):
                    return coerced
                if fallback is None:
                    fallback = coerced
            return fallback if is_batch_container(fallback) else None

        parsed = parse_candidate(text)
        if parsed is not None:
            return parsed

        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE):
            parsed = parse_candidate(match.group(1))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _extract_lenient_indexed_items(raw: str, value_keys: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Best-effort parser for model outputs that look like JSON but contain unescaped quotes."""
        if not raw:
            return []
        text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        value_keys = value_keys or ["zh", "translation", "translated", "text", "cn", "中文", "dst", "revised"]
        idx_matches = list(re.finditer(r'"(?:idx|index|id)"\s*:\s*"?(\d+)"?', text))
        if not idx_matches:
            return []

        def extract_value(chunk: str) -> Optional[str]:
            key_pattern = "|".join(re.escape(key) for key in value_keys)
            key_match = re.search(rf'"(?:{key_pattern})"\s*:', chunk)
            if not key_match:
                return None
            pos = key_match.end()
            while pos < len(chunk) and chunk[pos].isspace():
                pos += 1
            if pos >= len(chunk):
                return None
            if chunk[pos] == '"':
                start = pos + 1
                tail = chunk[start:]
                end_match = re.search(
                    r'"\s*(?:,\s*"(?:idx|index|id|new_terms|src|dst|category)"\s*:|\}\s*,?\s*(?:\{|\]|,?\s*"new_terms"|$))',
                    tail,
                    flags=re.DOTALL,
                )
                if end_match:
                    value = tail[:end_match.start()]
                else:
                    last_quote = tail.rfind('"')
                    value = tail[:last_quote] if last_quote >= 0 else tail
            else:
                end_match = re.search(r"\s*(?:,\s*\"|\}\s*,?\s*(?:\{|\]|$))", chunk[pos:], flags=re.DOTALL)
                value = chunk[pos:pos + end_match.start()] if end_match else chunk[pos:]
            value = value.strip()
            if not value:
                return None
            return value.replace('\\"', '"').replace("\\n", "\n")

        items: List[Dict[str, Any]] = []
        for pos, match in enumerate(idx_matches):
            idx = int(match.group(1))
            chunk_start = text.rfind("{", 0, match.start())
            if chunk_start < 0:
                chunk_start = match.start()
            next_start = idx_matches[pos + 1].start() if pos + 1 < len(idx_matches) else len(text)
            chunk = text[chunk_start:next_start]
            value = extract_value(chunk)
            if value is not None:
                items.append({"idx": idx, "zh": value})
        return items

    @staticmethod
    def _response_snippet(raw: str, limit: int = 240) -> str:
        """Compact API response content for local diagnostics."""
        return response_snippet(raw, limit)

    # LongCat / LongCat-like providers return a 400 with a JSON body whose
    # ``error.code`` is ``security_audit_fail`` when their content moderation
    # filter blocks a request. Detect it here so callers can split the batch and
    # retry items one-by-one instead of losing the whole batch.
    _CONTENT_MODERATION_SNIPPETS = CONTENT_MODERATION_SNIPPETS

    @classmethod
    def _is_content_moderation_http_error(cls, error: requests.exceptions.HTTPError) -> bool:
        return is_content_moderation_http_error(error)

    @staticmethod
    def _is_auth_http_error(error: requests.exceptions.HTTPError) -> bool:
        return is_auth_http_error(error)

    def _mark_proofread_auth_failed(self) -> None:
        if not getattr(self, "_proofread_auth_failed", False):
            logger.warning("校对 API 认证失败，本次任务后续校对将直接跳过")
        self._proofread_auth_failed = True

    def _log_http_error_response(
        self,
        error: requests.exceptions.HTTPError,
        context: str,
        attempt: Optional[int] = None,
        max_retries: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """Log HTTP error response body without leaking request headers/API keys."""
        resp = getattr(error, "response", None)
        if resp is None:
            logger.warning("%s HTTP 错误%s: %s", context, self._format_attempt(attempt, max_retries), error)
            return ""

        active_provider = (provider or self.provider or "").lower()
        active_model = model or self.model
        url = getattr(resp, "url", "")
        status_code = getattr(resp, "status_code", "unknown")
        body = ""
        try:
            body = resp.text or ""
        except Exception:
            body = ""
        snippet = self._response_snippet(body, limit=900) if body else "<empty>"
        prefix = "GLM 400" if active_provider == "glm" and status_code == 400 else f"HTTP {status_code}"
        logger.warning(
            "%s %s 响应体%s: provider=%s, model=%s, url=%s, body=%s",
            context,
            prefix,
            self._format_attempt(attempt, max_retries),
            active_provider or "-",
            active_model or "-",
            url,
            snippet,
        )
        return snippet

    @staticmethod
    def _format_attempt(attempt: Optional[int], max_retries: Optional[int]) -> str:
        if attempt is None or max_retries is None:
            return ""
        return f" (尝试 {attempt + 1}/{max_retries})"

    @staticmethod
    def _summarize_prompt(messages: Optional[List[Dict[str, Any]]], limit: int = 700) -> str:
        if not messages:
            return ""
        parts = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "-")
            content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
            if content:
                parts.append(f"{role}: {content}")
        text = " | ".join(parts)
        if qml_request_log is not None:
            return qml_request_log.compact_text(text, limit)
        return response_snippet(text, limit)

    def _log_api_request_event(
        self,
        context: str,
        started_at: float,
        outcome: str,
        *,
        status_code: Optional[int] = None,
        attempt: Optional[int] = None,
        max_retries: Optional[int] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        url: Optional[str] = None,
        batch_size: Optional[int] = None,
        error: Optional[str] = None,
        messages: Optional[List[Dict[str, Any]]] = None,
        source_text: Optional[Any] = None,
        response_text: Optional[Any] = None,
        token_total: Optional[int] = None,
        category: Optional[str] = None,
    ) -> None:
        """Log slow/failed API requests without leaking headers or API keys."""

        elapsed_ms = int(max(0.0, time.time() - started_at) * 1000)
        is_ok = str(outcome or "").lower() == "ok" and (
            status_code is None or 200 <= int(status_code) < 300
        )
        if qml_request_log is not None:
            try:
                qml_request_log.record_event(
                    context=context,
                    provider=provider or self.provider or "-",
                    model=model or self.model or "-",
                    url=url or self.api_url or "-",
                    status_code=status_code,
                    outcome=outcome or "-",
                    elapsed_ms=elapsed_ms,
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=batch_size,
                    prompt_summary=self._summarize_prompt(messages),
                    source_text=source_text,
                    response_text=response_text,
                    error=str(error or ""),
                    token_total=token_total,
                    category=category or "",
                )
            except Exception:
                pass
        if is_ok and elapsed_ms < 15000:
            return
        log_label = "慢请求" if is_ok else "API请求"
        logger.warning(
            "%s%s: context=%s, outcome=%s, status=%s, provider=%s, model=%s, url=%s, batch_size=%s, elapsed_ms=%s%s",
            log_label,
            self._format_attempt(attempt, max_retries),
            context,
            outcome or "-",
            status_code if status_code is not None else "-",
            provider or self.provider or "-",
            model or self.model or "-",
            url or self.api_url or "-",
            batch_size if batch_size is not None else "-",
            elapsed_ms,
            f", error={self._response_snippet(str(error), limit=240)}" if error else "",
        )

    def _inc_stat(self, key: str, delta: int = 1):
        with self._stats_lock:
            self.stats[key] = self.stats.get(key, 0) + delta

    def _set_stat(self, key: str, value: int):
        with self._stats_lock:
            self.stats[key] = int(value)

    def _ensure_dynamic_limiter(self) -> None:
        """Lazily initialize runtime throttling state for tests/old subclasses."""
        if not hasattr(self, "_dynamic_limit_lock"):
            self._dynamic_limit_lock = threading.RLock()
        if not hasattr(self, "_dynamic_max_workers"):
            self._dynamic_max_workers = max(1, int(getattr(self, "max_workers", 1) or 1))
        if not hasattr(self, "_dynamic_batch_size"):
            self._dynamic_batch_size = max(1, int(getattr(self, "batch_size", 1) or 1))
        if not hasattr(self, "_dynamic_backoff_until"):
            self._dynamic_backoff_until = 0.0
        if not hasattr(self, "_dynamic_limit_events"):
            self._dynamic_limit_events = 0
        if not hasattr(self, "_dynamic_success_count"):
            self._dynamic_success_count = 0
        if not hasattr(self, "_dynamic_format_failures"):
            self._dynamic_format_failures = 0

    @staticmethod
    def _scale_limit(value: int, factor: float) -> int:
        return max(1, int(value * factor + 0.999))

    def _current_dynamic_workers(self) -> int:
        self._ensure_dynamic_limiter()
        with self._dynamic_limit_lock:
            return max(1, int(self._dynamic_max_workers))

    def _current_dynamic_batch_size(self) -> int:
        self._ensure_dynamic_limiter()
        with self._dynamic_limit_lock:
            return max(1, int(self._dynamic_batch_size))

    def _record_dynamic_limit_event(self, reason: str, kind: str = "rate") -> None:
        """Reduce runtime pressure after 429/timeout/format instability."""
        self._ensure_dynamic_limiter()
        kind = (kind or "rate").lower()
        with self._dynamic_limit_lock:
            old_workers = max(1, int(self._dynamic_max_workers))
            old_batch = max(1, int(self._dynamic_batch_size))
            self._dynamic_limit_events += 1
            if kind == "format":
                self._dynamic_format_failures += 1
                worker_factor = 0.85
                batch_factor = 0.5
                backoff_seconds = min(20.0, 1.5 * self._dynamic_format_failures)
            elif kind == "timeout":
                worker_factor = 0.75
                batch_factor = 0.75
                backoff_seconds = min(45.0, 2 ** min(self._dynamic_limit_events, 5))
            else:
                worker_factor = 0.6
                batch_factor = 0.7
                backoff_seconds = min(60.0, 2 ** min(self._dynamic_limit_events, 5))

            new_workers = old_workers if worker_factor >= 1.0 else self._scale_limit(old_workers, worker_factor)
            new_batch = self._scale_limit(old_batch, batch_factor)
            if kind == "format" and (self._dynamic_format_failures >= 3 or old_batch <= 3):
                # Repeated malformed JSON means batch JSON is not reliable for the current model/run.
                # Drop to single-item batches; translate_one_batch then uses the normal single-text path.
                new_batch = 1
            self._dynamic_max_workers = max(1, new_workers)
            self._dynamic_batch_size = max(1, new_batch)
            self._dynamic_backoff_until = max(
                float(self._dynamic_backoff_until),
                time.time() + backoff_seconds + random.uniform(0, 0.5),
            )
            self._dynamic_success_count = 0

        self._inc_stat("dynamic_limit_events")
        if kind in {"rate", "timeout"}:
            self._inc_stat("rate_limit_events")
        self._set_stat("dynamic_limit_workers", self._current_dynamic_workers())
        self._set_stat("dynamic_limit_batch_size", self._current_dynamic_batch_size())
        event_label = "API 动态格式降级触发" if kind == "format" else "API 动态限流触发"
        logger.warning(
            "%s: %s；运行时并发 %s→%s，批量 %s→%s",
            event_label,
            reason,
            old_workers,
            self._current_dynamic_workers(),
            old_batch,
            self._current_dynamic_batch_size(),
        )

    def _record_api_success_event(self) -> None:
        """Slowly recover dynamic limits after a stable success streak."""
        self._ensure_dynamic_limiter()
        with self._dynamic_limit_lock:
            if time.time() < float(self._dynamic_backoff_until):
                return
            base_workers = max(1, int(getattr(self, "max_workers", 1) or 1))
            base_batch = max(1, int(getattr(self, "batch_size", 1) or 1))
            if self._dynamic_max_workers >= base_workers and self._dynamic_batch_size >= base_batch:
                return
            self._dynamic_success_count += 1
            if self._dynamic_success_count < 20:
                return
            self._dynamic_success_count = 0
            self._dynamic_max_workers = min(base_workers, int(self._dynamic_max_workers) + 1)
            self._dynamic_batch_size = min(base_batch, int(self._dynamic_batch_size) + 1)
            self._dynamic_format_failures = max(0, int(getattr(self, "_dynamic_format_failures", 0)) - 1)

        self._set_stat("dynamic_limit_workers", self._current_dynamic_workers())
        self._set_stat("dynamic_limit_batch_size", self._current_dynamic_batch_size())
        logger.info(
            "API 动态限流恢复: 运行时并发=%s，批量=%s",
            self._current_dynamic_workers(),
            self._current_dynamic_batch_size(),
        )

    def _wait_dynamic_backoff(self) -> None:
        self._ensure_dynamic_limiter()
        with self._dynamic_limit_lock:
            wait_seconds = max(0.0, float(self._dynamic_backoff_until) - time.time())
        if wait_seconds > 0 and self.cancel_event.wait(wait_seconds):
            raise RuntimeError("翻译已取消")

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
        return tq.has_japanese_residue(text)

    @staticmethod
    def _extract_japanese_residue_fragments(text: str) -> List[str]:
        """Extract repeated kana fragments so proofread can avoid fixing the same residue repeatedly."""
        return tq.extract_japanese_residue_fragments(text)

    @classmethod
    def _has_likely_o_name_prefix_residue(cls, text: str) -> bool:
        """Detect お + CJK name prefixes even when followed by Chinese text, e.g. お仲写."""
        return tq.has_likely_o_name_prefix_residue(text)

    @classmethod
    def _has_weak_japanese_residue(cls, text: str) -> bool:
        """Return True for low-risk single-kana leftovers, e.g. historical terms like 藪入り."""
        return tq.has_weak_japanese_residue(text)

    @classmethod
    def _has_blocking_japanese_residue(cls, text: str) -> bool:
        """Return True only for residue that should block cache/save completion."""
        return tq.has_blocking_japanese_residue(text)

    @classmethod
    def _is_short_quoted_japanese_literal(cls, text: str) -> bool:
        """Short quoted literals can be dialogue particles, clues, or terms."""
        return tq.is_short_quoted_japanese_literal(text)

    @classmethod
    def _postprocess_translation(cls, src: str, dst: Optional[str]) -> str:
        """Apply conservative local cleanups before residue checks and cache writes."""
        return tq.postprocess_translation(src, dst)

    @classmethod
    def _repair_japanese_o_name_prefix_residue(cls, src: str, dst: str) -> str:
        """Convert likely Japanese female-name prefixes left by the model, e.g. お仲 -> 阿仲."""
        return tq.repair_japanese_o_name_prefix_residue(src, dst)

    @staticmethod
    def _strip_allowed_japanese_notation(text: str) -> str:
        """Ignore approved literal Japanese snippets that are not untranslated residue."""
        return tq.strip_allowed_japanese_notation(text)

    @classmethod
    def _strip_builtin_allowed_quoted_literals(cls, text: str) -> str:
        """Allow very short quoted katakana markers, e.g. “コ”, without allowing real Japanese phrases."""
        return tq.strip_builtin_allowed_quoted_literals(text)

    @classmethod
    def _strip_builtin_allowed_reading_puzzle_runs(cls, text: str) -> str:
        """Allow kana spelling runs when Chinese context explains a reading puzzle."""
        return tq.strip_builtin_allowed_reading_puzzle_runs(text)

    @classmethod
    def japanese_residue_allowlist_path(cls) -> str:
        """Return the user-editable allowlist path for literal Japanese snippets."""
        return tq.japanese_residue_allowlist_path()

    @classmethod
    def _load_japanese_residue_allowlist(cls) -> Dict[str, Any]:
        """Load user-configurable residue allowlist with lightweight mtime caching."""
        return tq.load_japanese_residue_allowlist()

    @classmethod
    def _strip_user_allowed_japanese_literals(cls, text: str) -> str:
        """Strip user-approved literals from residue detection only; translation text is unchanged."""
        return tq.strip_user_allowed_japanese_literals(text)

    @staticmethod
    def _build_residue_repair_guidance(examples: List[Dict[str, str]]) -> str:
        """Build a compact in-run hint from successful residue fixes."""
        if not examples:
            return ""
        lines = [
            "【本书内日文残留修复参考】",
            "以下是本次翻译中已成功修复过的日文残留示例。遇到类似残留时，请结合当前原文完整翻译成自然中文，不要机械替换，也不要保留假名。",
        ]
        for example in examples[:5]:
            fragment = example.get("fragment", "")
            draft = example.get("draft", "")
            revised = example.get("revised", "")
            lines.append(f"- 残留片段「{fragment}」：错误初译「{draft}」 -> 修正「{revised}」")
        return "\n".join(lines)

    @staticmethod
    def has_japanese_residue(text: str) -> bool:
        """Public helper for UI/bridge code that must reject untranslated kana residue."""
        return JaZhTranslator._has_japanese_residue(text)

    @staticmethod
    def has_blocking_japanese_residue(text: str) -> bool:
        """Public helper for final save checks; weak single-kana leftovers are warnings only."""
        return JaZhTranslator._has_blocking_japanese_residue(text)

    @staticmethod
    def has_weak_japanese_residue(text: str) -> bool:
        """Public helper for diagnostics; weak residue should not block saving."""
        return JaZhTranslator._has_weak_japanese_residue(text)

    @classmethod
    def _has_only_trivial_japanese_noise(cls, text: str) -> bool:
        """Return True when the bulk of *text* is Chinese and any leftover kana
        is just a couple of isolated name / term fragments. Today's logs show
        a pattern where LongCat leaves one stray kana (e.g. ``ひょう`` or
        ``キヨ``) inside an otherwise complete Chinese sentence — that is a
        real defect, but not severe enough to discard the whole translation.
        Treat those as 'trivial noise' so callers can decide locally how to
        count them."""
        return tq.has_only_trivial_japanese_noise(text)

    @staticmethod
    def japanese_residue_fragments(text: str) -> List[str]:
        """Public helper for diagnostics and UI messages."""
        return tq.extract_japanese_residue_fragments(text)

    @classmethod
    def _is_incomplete_translation(cls, src: str, dst: Optional[str]) -> bool:
        return tq.is_incomplete_translation(src, dst)

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
                        "policy": str(entry.get("policy", entry.get("enforcement", ""))).strip(),
                    }
            return {}

        value = glossary_snapshot.get(original)
        if isinstance(value, dict):
            return {
                "category": "Item",
                "source": str(value.get("source", "")).strip(),
                "info": str(value.get("info", "")).strip(),
                "policy": str(value.get("policy", value.get("enforcement", ""))).strip(),
            }
        return {"category": "Item", "source": "", "info": "", "policy": ""} if value else {}

    def _glossary_enforcement_level(self, entry: Dict[str, str]) -> str:
        """Return force/reference/contextual/preserve/ignore for glossary enforcement."""
        original = str(entry.get("original", "")).strip()
        translation = str(entry.get("translation", "")).strip()
        if not self._is_meaningful_glossary_term(original, translation):
            return "ignore"

        metadata = self._lookup_glossary_metadata(original)
        category = str(entry.get("category") or metadata.get("category") or "Item").strip()
        source = str(entry.get("source") or metadata.get("source") or "").strip()
        info = str(entry.get("info") or metadata.get("info") or "").strip()
        policy = gs_normalize_policy(entry.get("policy") or metadata.get("policy") or "")

        if policy == "force":
            return "force"
        if policy == "reference":
            return "reference"
        if policy == "contextual":
            return "contextual"
        if policy == "preserve":
            return "preserve"
        if policy == "ignore":
            return "ignore"

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

    def _expected_glossary_translation(self, entry: Dict[str, str]) -> str:
        level = self._glossary_enforcement_level(entry)
        if level == "preserve":
            return str(entry.get("original", "")).strip()
        return str(entry.get("translation", "")).strip()

    def _iter_all_glossary_entries(self) -> List[Dict[str, str]]:
        entries: List[Dict[str, str]] = []
        seen_original = set()

        glossary_index = getattr(self, "_glossary_index", None) or {}
        if glossary_index:
            for indexed_entries in glossary_index.values():
                for indexed_entry in indexed_entries:
                    original = indexed_entry[0] if len(indexed_entry) > 0 else ""
                    translation = indexed_entry[1] if len(indexed_entry) > 1 else ""
                    source = indexed_entry[2] if len(indexed_entry) > 2 else ""
                    policy = indexed_entry[3] if len(indexed_entry) > 3 else ""
                    info = indexed_entry[4] if len(indexed_entry) > 4 else ""
                    original = str(original).strip()
                    translation = str(translation).strip()
                    source = str(source or "").strip()
                    policy = str(policy or "").strip()
                    info = str(info or "").strip()
                    if not original or not translation or original in seen_original:
                        continue
                    item = {"original": original, "translation": translation}
                    if source:
                        item["source"] = source
                    if policy:
                        item["policy"] = policy
                    if info:
                        item["info"] = info
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
                    policy = str(entry.get("policy", entry.get("enforcement", ""))).strip()
                    info = str(entry.get("info", "")).strip()
                    if not original or not translation or original in seen_original:
                        continue
                    item = {"original": original, "translation": translation}
                    if source:
                        item["source"] = source
                    if policy:
                        item["policy"] = policy
                    if info:
                        item["info"] = info
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
                policy = str(value.get("policy", value.get("enforcement", ""))).strip()
                info = str(value.get("info", "")).strip()
            else:
                translation = str(value).strip()
                source = ""
                policy = ""
                info = ""
            if not translation:
                continue
            item = {"original": original, "translation": translation}
            if source:
                item["source"] = source
            if policy:
                item["policy"] = policy
            if info:
                item["info"] = info
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
            if self._glossary_enforcement_level(entry) == "ignore":
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
            metadata = self._lookup_glossary_metadata(original)
            if metadata:
                entry = {**entry, **{k: v for k, v in metadata.items() if v}}
            if self._glossary_enforcement_level(entry) in {"force", "preserve"}:
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
                expected = self._expected_glossary_translation(entry)
                if original and expected and gs_has_valid_glossary_match(src, original) and expected not in dst:
                    if self._glossary_enforcement_level(entry) == "preserve":
                        issues.append(f"术语应保留原文: {original}")
                    else:
                        issues.append(f"术语未按术语表翻译: {original} -> {expected}")
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
        if getattr(self, "_proofread_auth_failed", False):
            return None

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
            + "短片假名普通物品、仅供参考术语和上下文命中术语不得强行替换；"
            + "标注保留原文的术语必须保留源词；如果术语译法会破坏语义，保留初译。\n"
            + "\n【输出格式】\n只输出修正后的简体中文译文。禁止输出说明、修改说明、理由、注释、括号说明或项目符号。\n"
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
                self._wait_dynamic_backoff()
                self._wait_provider_rate_budget(
                    estimated_tokens=self._estimate_request_tokens(messages=messages, source_text=src, batch_size=1),
                    estimated_requests=1,
                    context="译后校对",
                )
                self._inc_stat("api_requests_total")
                request_started = time.time()
                resp = self.session.post(
                    proofread_url,
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                self._log_api_request_event(
                    "译后校对",
                    request_started,
                    "ok" if 200 <= resp.status_code < 300 else "http_error",
                    status_code=resp.status_code,
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                    url=proofread_url,
                    batch_size=1,
                    messages=messages,
                    source_text=src,
                    response_text=getattr(resp, "text", ""),
                )
                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    self._record_dynamic_limit_event("校对 HTTP 429", kind="rate")
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
                self._record_api_success_event()
                return cleaned
            except requests.exceptions.Timeout as e:
                self._inc_stat("api_requests_failed")
                self._record_dynamic_limit_event("校对请求超时", kind="timeout")
                self._log_api_request_event(
                    "译后校对",
                    locals().get("request_started", time.time()),
                    "timeout",
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                    url=proofread_url,
                    batch_size=1,
                    messages=messages,
                    source_text=src,
                    error=e,
                )
                logger.warning(f"译后校对超时: {e}")
                if attempt == 1:
                    return draft
            except requests.exceptions.HTTPError as e:
                self._inc_stat("api_requests_failed")
                self._log_api_request_event(
                    "译后校对",
                    locals().get("request_started", time.time()),
                    "http_error",
                    status_code=getattr(getattr(e, "response", None), "status_code", None),
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                    url=proofread_url,
                    batch_size=1,
                    messages=messages,
                    source_text=src,
                    response_text=getattr(getattr(e, "response", None), "text", ""),
                    error=e,
                )
                self._log_http_error_response(
                    e,
                    "译后校对",
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                )
                if self._is_auth_http_error(e):
                    self._mark_proofread_auth_failed()
                    return None
                if attempt == 1:
                    return draft
            except Exception as e:
                logger.warning(f"译后校对失败: {e}")
                if attempt == 1:
                    return draft
        return draft

    def _proofread_translations_batch(self, items: List[Dict[str, Any]]) -> Optional[Dict[int, str]]:
        """Proofread multiple suspicious translations with one JSON API request."""
        if not bool(getattr(self, "enable_proofread", False)) or not items:
            return {}
        if getattr(self, "_proofread_auth_failed", False):
            return None

        prepared: List[Dict[str, Any]] = []
        allowed_entries_by_idx: Dict[int, List[Dict[str, str]]] = {}
        draft_by_idx: Dict[int, str] = {}
        src_by_idx: Dict[int, str] = {}

        for item in items:
            try:
                idx = int(item.get("idx"))
            except (TypeError, ValueError):
                continue
            src = str(item.get("src", "") or "").strip()
            draft = str(item.get("draft", "") or "").strip()
            issues = [str(issue) for issue in item.get("issues", []) if str(issue).strip()]
            if not src or not draft or not issues:
                continue

            selected_entries = self._select_proofread_glossary_entries(src, max_terms=30)
            allowed_entries_by_idx[idx] = selected_entries
            src_by_idx[idx] = src
            draft_by_idx[idx] = draft

            payload_item: Dict[str, Any] = {
                "idx": idx,
                "issues": issues,
                "src": src,
                "draft": draft,
            }
            prev_text = item.get("prev")
            next_text = item.get("next")
            if prev_text:
                payload_item["prev"] = str(prev_text)[:self.CONTEXT_PREVIEW_LEN]
            if next_text:
                payload_item["next"] = str(next_text)[:self.CONTEXT_PREVIEW_LEN]
            if selected_entries:
                payload_item["glossary"] = [
                    {
                        "original": str(entry.get("original", "")),
                        "translation": str(entry.get("translation", "")),
                        **({"info": str(entry.get("info", ""))} if entry.get("info") else {}),
                    }
                    for entry in selected_entries
                ]
            prepared.append(payload_item)

        if not prepared:
            return {}

        system_prompt = self._build_proofread_system_prompt()
        user_prompt = (
            "请逐项校对 JSON 数组中的中文初译，只修复 issues 指出的明确问题。\n"
            "prev/next 只是上下文参考，不要翻译 prev/next。\n"
            "术语只在日文原文中独立命中且符合上下文时才修正；仅供参考/上下文命中术语不得机械强改；保留原文术语必须保留源词；如果术语译法会破坏语义，保留初译。\n"
            "禁止输出说明、修改说明、理由、注释、括号说明或项目符号。\n"
            "必须只返回 JSON 对象，格式为：{\"items\":[{\"idx\":0,\"revised\":\"修正后的简体中文译文\"}]}。\n\n"
            f"【待校对项目】\n{json.dumps(prepared, ensure_ascii=False)}"
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
        proofread_model = self.proofread_model or self.model
        proofread_url = self._get_proofread_url() if self.proofread_provider else self.api_url
        active_provider = (self.proofread_provider or self.provider or "").lower()
        payload = {
            "model": proofread_model,
            "messages": messages,
            "temperature": 0.1,
        }
        self._apply_provider_payload_options(payload, self.proofread_provider or self.provider)
        if active_provider == "deepseek":
            payload["response_format"] = {"type": "json_object"}

        for attempt in range(2):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._wait_dynamic_backoff()
                self._wait_provider_rate_budget(
                    estimated_tokens=self._estimate_request_tokens(messages=messages, source_text=prepared, batch_size=len(prepared)),
                    estimated_requests=1,
                    context="批量校对",
                )
                self._inc_stat("proofread_batch_requests")
                self._inc_stat("api_requests_total")
                request_started = time.time()
                resp = self.session.post(
                    proofread_url,
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                self._log_api_request_event(
                    "批量校对",
                    request_started,
                    "ok" if 200 <= resp.status_code < 300 else "http_error",
                    status_code=resp.status_code,
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                    url=proofread_url,
                    batch_size=len(prepared),
                    messages=messages,
                    source_text=prepared,
                    response_text=getattr(resp, "text", ""),
                )
                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    self._record_dynamic_limit_event("批量校对 HTTP 429", kind="rate")
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    logger.warning("批量校对请求遇到 502，回退单条校对")
                    return {}
                if resp.status_code in (401, 403):
                    self._inc_stat("api_requests_failed")
                    try:
                        resp.raise_for_status()
                    except requests.exceptions.HTTPError as e:
                        self._log_http_error_response(
                            e,
                            "批量校对",
                            attempt=attempt,
                            max_retries=2,
                            provider=self.proofread_provider or self.provider,
                            model=proofread_model,
                        )
                    self._mark_proofread_auth_failed()
                    return None
                resp.raise_for_status()
                data = resp.json()
                self._accumulate_usage_tokens(data)

                choices = data.get("choices", [])
                if not choices:
                    self._record_dynamic_limit_event("批量校对缺少 choices", kind="format")
                    return {}
                message = choices[0].get("message", {})
                raw = (message.get("content", "") or "").strip()
                obj = self._extract_json_object(raw)
                if not isinstance(obj, dict):
                    lenient_items = self._extract_lenient_indexed_items(
                        raw,
                        value_keys=["revised", "zh", "translation", "translated", "text", "cn", "中文"],
                    )
                    if lenient_items:
                        obj = {"items": lenient_items}
                        self._inc_stat("proofread_batch_lenient_success")
                        logger.info("批量校对 JSON 宽松解析成功: %s/%s 条", len(lenient_items), len(prepared))
                    else:
                        logger.warning("批量校对 JSON 解析失败，响应摘要: %s", self._response_snippet(raw))
                        self._record_dynamic_limit_event("批量校对 JSON 解析失败", kind="format")
                        return {}
                arr = obj.get("items") or obj.get("translations")
                if not isinstance(arr, list):
                    lenient_items = self._extract_lenient_indexed_items(
                        raw,
                        value_keys=["revised", "zh", "translation", "translated", "text", "cn", "中文"],
                    )
                    if lenient_items:
                        arr = lenient_items
                        self._inc_stat("proofread_batch_lenient_success")
                        logger.info("批量校对 JSON 宽松解析补全 items: %s/%s 条", len(lenient_items), len(prepared))
                    else:
                        logger.warning("批量校对缺少 items，响应摘要: %s", self._response_snippet(raw))
                        self._record_dynamic_limit_event("批量校对缺少 items", kind="format")
                        return {}

                revised_by_idx: Dict[int, str] = {}
                for position, result_item in enumerate(arr):
                    if isinstance(result_item, str):
                        idx = position
                        revised_raw = result_item
                    elif isinstance(result_item, dict):
                        try:
                            idx = int(result_item.get("idx", result_item.get("index", position)))
                        except (TypeError, ValueError):
                            continue
                        revised_raw = (
                            result_item.get("revised")
                            or result_item.get("zh")
                            or result_item.get("translation")
                            or result_item.get("translated")
                            or result_item.get("text")
                            or result_item.get("cn")
                            or result_item.get("中文")
                            or ""
                        )
                    else:
                        continue
                    if idx not in draft_by_idx:
                        continue
                    if not isinstance(revised_raw, str) or not revised_raw.strip():
                        continue
                    cleaned = self._strip_proofread_explanations(revised_raw, fallback=draft_by_idx[idx])
                    invalid_injections = self._find_invalid_glossary_injections(
                        src_by_idx[idx],
                        draft_by_idx[idx],
                        cleaned,
                        allowed_entries=allowed_entries_by_idx.get(idx, []),
                    )
                    if invalid_injections:
                        self._inc_stat("proofread_rejected")
                        logger.warning(
                            "批量校对结果引入未命中术语，已保留初译: "
                            + ", ".join(invalid_injections)
                        )
                        cleaned = draft_by_idx[idx]
                    revised_by_idx[idx] = cleaned

                if revised_by_idx:
                    self._inc_stat("proofread_batch_success")
                    self._record_api_success_event()
                return revised_by_idx
            except requests.exceptions.Timeout as e:
                self._inc_stat("api_requests_failed")
                self._record_dynamic_limit_event("批量校对请求超时", kind="timeout")
                self._log_api_request_event(
                    "批量校对",
                    locals().get("request_started", time.time()),
                    "timeout",
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                    url=proofread_url,
                    batch_size=len(prepared),
                    messages=messages,
                    source_text=prepared,
                    error=e,
                )
                logger.warning(f"批量校对超时: {e}")
                if attempt == 1:
                    return {}
            except requests.exceptions.HTTPError as e:
                self._inc_stat("api_requests_failed")
                self._log_api_request_event(
                    "批量校对",
                    locals().get("request_started", time.time()),
                    "http_error",
                    status_code=getattr(getattr(e, "response", None), "status_code", None),
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                    url=proofread_url,
                    batch_size=len(prepared),
                    messages=messages,
                    source_text=prepared,
                    response_text=getattr(getattr(e, "response", None), "text", ""),
                    error=e,
                )
                self._log_http_error_response(
                    e,
                    "批量校对",
                    attempt=attempt,
                    max_retries=2,
                    provider=self.proofread_provider or self.provider,
                    model=proofread_model,
                )
                if self._is_auth_http_error(e):
                    self._mark_proofread_auth_failed()
                    return None
                if attempt == 1:
                    return {}
            except Exception as e:
                logger.warning(f"批量校对失败: {e}")
                if attempt == 1:
                    return {}
        return {}

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
            self._wait_dynamic_backoff()
            self._wait_provider_rate_budget(
                estimated_tokens=self._estimate_request_tokens(messages=continuation_messages, source_text=continuation_prompt, batch_size=1),
                estimated_requests=1,
                context="截断续取",
            )
            self._inc_stat("api_requests_total")
            request_started = time.time()
            resp = self.session.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=self.API_TIMEOUT,
            )
            self._log_api_request_event(
                "截断续取",
                request_started,
                "ok" if 200 <= resp.status_code < 300 else "http_error",
                status_code=resp.status_code,
                batch_size=1,
                messages=continuation_messages,
                source_text=continuation_prompt,
                response_text=getattr(resp, "text", ""),
            )
            if resp.status_code in (429, 502):
                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    self._record_dynamic_limit_event("截断续取 HTTP 429", kind="rate")
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
            if additional:
                self._record_api_success_event()
            return (additional or "").strip(), finish_reason
        except requests.exceptions.HTTPError as e:
            self._inc_stat("api_requests_failed")
            self._log_api_request_event(
                "截断续取",
                locals().get("request_started", time.time()),
                "http_error",
                status_code=getattr(getattr(e, "response", None), "status_code", None),
                batch_size=1,
                messages=continuation_messages,
                source_text=continuation_prompt,
                response_text=getattr(getattr(e, "response", None), "text", ""),
                error=e,
            )
            self._log_http_error_response(e, "截断续取")
            return "", None
        except Exception as e:
            self._log_api_request_event(
                "截断续取",
                locals().get("request_started", time.time()),
                "request_error",
                batch_size=1,
                messages=continuation_messages,
                source_text=continuation_prompt,
                error=e,
            )
            logger.warning(f"截断续取请求失败: {e}")
            return "", None

    def _call_glossary_extraction_json(
        self,
        texts: List[str],
        *,
        max_retries: int = 2,
        extraction_mode: Optional[str] = None,
    ) -> BatchJsonResult:
        """Dedicated glossary extraction request with JSON repair/continuation."""
        if not texts:
            return BatchJsonResult(translations=[], new_terms=[], missing_indices=[], finish_reason="stop")

        numbered = [{"idx": i, "text": t} for i, t in enumerate(texts)]
        system_prompt = self._build_glossary_extraction_system_prompt(extraction_mode=extraction_mode)
        user_prompt = (
            "请从以下 JSON 数组中抽取术语，仅返回 JSON 对象，不要翻译正文：\n"
            f"{json.dumps(numbered, ensure_ascii=False)}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "top_p": 0.3,
        }
        apply_payload_options(payload, self.provider, self.enable_thinking)
        if self.provider == "deepseek":
            payload["response_format"] = {"type": "json_object"}

        mode = self._normalize_glossary_extraction_mode(extraction_mode or self.glossary_extraction_mode)

        def _parse_terms(raw_text: str) -> Tuple[Optional[dict], List[Dict[str, Any]]]:
            obj = self._extract_json_object(raw_text, prefer_new_terms=True)
            raw_terms: List[Dict[str, Any]] = []
            if isinstance(obj, dict):
                candidates = obj.get("new_terms", [])
                if isinstance(candidates, list):
                    raw_terms = candidates
                elif isinstance(obj.get("translations"), list):
                    raw_terms = obj.get("translations") or []
            elif isinstance(obj, list):
                raw_terms = obj
            return obj if isinstance(obj, dict) else None, raw_terms

        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._wait_dynamic_backoff()
                self._wait_provider_rate_budget(
                    estimated_tokens=self._estimate_request_tokens(messages=messages, source_text=numbered, batch_size=len(texts)),
                    estimated_requests=1,
                    context=f"术语抽取:{mode}",
                )
                self._inc_stat("api_requests_total")
                request_started = time.time()
                logger.info(
                    "术语抽取请求开始: provider=%s, model=%s, mode=%s, attempt=%s/%s, texts=%s, timeout=%ss",
                    self.provider,
                    self.model,
                    mode,
                    attempt + 1,
                    max_retries,
                    len(texts),
                    self.API_TIMEOUT,
                )
                if qml_request_log is not None:
                    try:
                        qml_request_log.record_event(
                            context="术语抽取",
                            provider=self.provider or "-",
                            model=self.model or "-",
                            url=self.api_url or "-",
                            status_code=None,
                            outcome="started",
                            elapsed_ms=0,
                            attempt=attempt,
                            max_retries=max_retries,
                            batch_size=len(texts),
                            prompt_summary=self._summarize_prompt(messages),
                            source_text=numbered,
                            response_text="",
                            error="",
                            token_total=None,
                            category=f"glossary_extract:{mode}",
                        )
                    except Exception:
                        pass
                resp = self.session.post(
                    self.api_url,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                self._log_api_request_event(
                    "术语抽取",
                    request_started,
                    "ok" if 200 <= resp.status_code < 300 else "http_error",
                    status_code=resp.status_code,
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=len(texts),
                    messages=messages,
                    source_text=numbered,
                    response_text=getattr(resp, "text", ""),
                    category=f"glossary_extract:{mode}",
                )
                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    self._record_dynamic_limit_event("术语抽取 HTTP 429", kind="rate")
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    self._inc_stat("api_requests_failed")
                    raise FastFailError("术语抽取失败: HTTP 502 Bad Gateway（已按配置直接中断）")
                resp.raise_for_status()
                data = resp.json()
                self._accumulate_usage_tokens(data)
                choices = data.get("choices", [])
                if not choices:
                    self._inc_stat("batch_json_parse_fail")
                    logger.warning("术语抽取缺少 choices，响应摘要: %s", self._response_snippet(getattr(resp, "text", "")))
                    continue
                message = choices[0].get("message", {})
                raw = str(message.get("content", "") or "").strip()
                if not raw:
                    self._inc_stat("batch_json_parse_fail")
                    logger.warning("术语抽取缺少 content，响应摘要: %s", self._response_snippet(getattr(resp, "text", "")))
                    continue

                finish_reason = self._get_finish_reason(data)
                is_truncated = finish_reason == "length"
                if is_truncated:
                    accumulated_raw = raw
                    continuations_used = 0
                    continuation_prompt = "请继续输出未完成的 JSON，不要从头开始。"
                    while continuations_used < self.MAX_CONTINUATIONS and finish_reason == "length":
                        if self.cancel_event.is_set():
                            break
                        additional, new_finish = self._send_continuation_request(
                            messages=messages,
                            accumulated_content=accumulated_raw,
                            continuation_prompt=continuation_prompt,
                            headers={
                                "Authorization": f"Bearer {self.api_key}",
                                "Content-Type": "application/json",
                            },
                            base_payload={
                                "model": self.model,
                                "temperature": payload.get("temperature", 0.1),
                                "top_p": payload.get("top_p", 0.3),
                            },
                        )
                        if not additional:
                            break
                        accumulated_raw += additional
                        finish_reason = new_finish
                        continuations_used += 1
                        self._inc_stat("truncation_continuation")
                        logger.info("术语抽取截断续取 %s/%s", continuations_used, self.MAX_CONTINUATIONS)
                    raw = accumulated_raw

                obj, raw_terms = _parse_terms(raw)
                if obj is not None and isinstance(obj.get("new_terms", []), list) and not raw_terms:
                    logger.info("术语抽取批次完成: mode=%s, input=%s, terms=0, truncated=%s", mode, len(texts), is_truncated)
                    self._record_api_success_event()
                    return BatchJsonResult(
                        translations=[],
                        new_terms=[],
                        missing_indices=[],
                        finish_reason=finish_reason,
                        is_truncated=is_truncated,
                        raw_content=raw,
                    )
                if not raw_terms:
                    self._inc_stat("batch_json_parse_fail")
                    logger.warning("术语抽取解析失败，响应摘要: %s", self._response_snippet(raw))
                    continue
                if self._normalize_glossary_extraction_mode(mode) == "lite":
                    filtered_terms = []
                    for item in raw_terms:
                        if not isinstance(item, dict):
                            continue
                        category = str(item.get("category", "")).strip()
                        if category and category not in {"Person", "Location"}:
                            continue
                        if not category:
                            item = {**item, "category": "Person"}
                        filtered_terms.append(item)
                    raw_terms = filtered_terms
                if not raw_terms:
                    logger.info("术语抽取完成但没有通过模式过滤的术语: mode=%s", mode)
                    return BatchJsonResult(translations=[], new_terms=[], missing_indices=[], finish_reason=finish_reason, is_truncated=is_truncated, raw_content=raw)
                self._record_api_success_event()
                logger.info(
                    "术语抽取批次完成: mode=%s, input=%s, terms=%s, truncated=%s",
                    mode,
                    len(texts),
                    len(raw_terms),
                    is_truncated,
                )
                return BatchJsonResult(
                    translations=[],
                    new_terms=raw_terms,
                    missing_indices=[],
                    finish_reason=finish_reason,
                    is_truncated=is_truncated,
                    raw_content=raw,
                )
            except FastFailError:
                raise
            except requests.exceptions.Timeout as e:
                self._inc_stat("api_requests_failed")
                logger.warning("术语抽取超时 (尝试 %s/%s): %s", attempt + 1, max_retries, e)
                if attempt + 1 >= max_retries:
                    return BatchJsonResult(translations=None, new_terms=[], missing_indices=list(range(len(texts))), finish_reason=None, raw_content="")
            except requests.exceptions.HTTPError as e:
                self._inc_stat("api_requests_failed")
                self._log_http_error_response(e, "术语抽取")
                if self._is_content_moderation_http_error(e):
                    raise ContentModerationError(str(e))
                if attempt + 1 >= max_retries:
                    return BatchJsonResult(translations=None, new_terms=[], missing_indices=list(range(len(texts))), finish_reason=None, raw_content=getattr(getattr(e, "response", None), "text", ""))
            except Exception as e:
                self._inc_stat("api_requests_failed")
                logger.warning("术语抽取请求失败 (尝试 %s/%s): %s", attempt + 1, max_retries, e)
                if attempt + 1 >= max_retries:
                    return BatchJsonResult(translations=None, new_terms=[], missing_indices=list(range(len(texts))), finish_reason=None, raw_content="")
        return BatchJsonResult(translations=None, new_terms=[], missing_indices=list(range(len(texts))), finish_reason=None, raw_content="")

    def get_stats(self) -> Dict[str, int]:
        with self._stats_lock:
            return dict(self.stats)

    @staticmethod
    def _load_json(path: str, default) -> dict:
        """加载 JSON 文件，不存在则返回默认值"""
        loaded = tc_load_json_file(path, default)
        if loaded is default and os.path.exists(path):
            logging.warning("JSON 文件解析失败 %s", path)
        return loaded

    @staticmethod
    def _atomic_write_json(path: Union[str, Path], payload: Dict[str, Any]) -> None:
        """原子写入 JSON，避免异常中断导致文件损坏。"""
        tc_atomic_write_json(path, payload)

    @classmethod
    def normalize_glossary_payload(cls, payload: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, int]]:
        return gs_normalize_glossary_payload(payload)

    def _cache_key(self, text: str) -> str:
        """Include provider/model in primary cache keys; cross-model resume uses a digest index."""
        return tc_model_cache_key(self.provider, self.model, text, self.glossary_fingerprint)

    def _is_context_cache_text(self, text: str) -> bool:
        """Short dialogue fragments are context-sensitive and should not share one global cache entry."""
        text = (text or "").strip()
        if not self._provider_uses_context_window() or not text:
            return False
        if len(text) > self.SMART_BATCH_SHORT:
            return False
        # Pure local-rule phrases are intentionally stable and can keep the normal text cache.
        if text in self.PRE_TRANSLATE_RULES:
            return False
        if not re.search(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]", text):
            return False
        return True

    def _cache_key_for_context(
        self,
        text: str,
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
    ) -> str:
        """Use a context-aware model cache key for short fragments, preserving normal keys for longer text."""
        text = (text or "").strip()
        if not self._is_context_cache_text(text) or not (prev_text or next_text):
            return self._cache_key(text)
        return tc_context_cache_key(
            self.provider,
            self.model,
            text,
            prev_text,
            next_text,
            self.CONTEXT_PREVIEW_LEN,
            self.glossary_fingerprint,
        )

    @property
    def last_ordered_results(self) -> List[Optional[str]]:
        """Most recent translate_batch result aligned to the input text order."""
        return list(getattr(self, "_last_ordered_results", []))

    # ---- Phase 1-②: 文本级缓存（跨模型共享可复用译文）----
    _text_cache: Dict[str, Dict[str, Any]] = {}
    _text_cache_loaded = False
    TEXT_CACHE_FILE_NAME = "text_cache.json"
    TEXT_CACHE_SAVE_THRESHOLD = 250
    _text_cache_dirty_count = 0
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
        self._text_cache_dirty_count = 0
        self._text_cache_loaded = True
        logger.info(f"文本缓存已加载: {len(self._text_cache)} 条记录")

    def _text_cache_key(self, text: str) -> str:
        """纯文本缓存键（不绑定 provider/model）。"""
        return tc_text_cache_key(text)

    @classmethod
    def _cache_digest(cls, text: str) -> str:
        return tc_cache_digest(text)

    @classmethod
    def _parse_model_cache_key(cls, key: str) -> Tuple[str, Optional[str], Optional[str]]:
        """Return (kind, text_digest, context_digest) for v2/v3 cache keys."""
        return tc_parse_model_cache_key(key)

    def _ensure_cross_model_cache_index(self) -> None:
        """Build digest indexes so a new provider/model can reuse previous model-cache entries."""
        with self._cache_lock:
            if self._cross_model_cache_index_built:
                return
            text_index: Dict[str, str] = {}
            context_index: Dict[Tuple[str, str], str] = {}
            for key, value in self.cache.items():
                if not isinstance(value, str) or not value.strip():
                    continue
                kind, text_digest, context_digest = self._parse_model_cache_key(str(key))
                if kind == "context" and text_digest and context_digest:
                    context_index.setdefault((context_digest, text_digest), value)
                elif kind == "text" and text_digest:
                    text_index.setdefault(text_digest, value)
            self._cross_model_text_cache_index = text_index
            self._cross_model_context_cache_index = context_index
            self._cross_model_cache_index_built = True

    def _invalidate_cross_model_cache_index(self) -> None:
        with self._cache_lock:
            self._cross_model_cache_index_built = False
            self._cross_model_text_cache_index = {}
            self._cross_model_context_cache_index = {}

    def _lookup_cross_model_cache(self, text: str, current_cache_key: str) -> Optional[str]:
        """Find a safe candidate from cache.json entries created by another provider/model."""
        if getattr(self, "glossary_fingerprint", ""):
            return None
        if not text or not current_cache_key:
            return None
        self._ensure_cross_model_cache_index()
        kind, text_digest, context_digest = self._parse_model_cache_key(current_cache_key)
        with self._cache_lock:
            if kind == "context" and text_digest and context_digest:
                return self._cross_model_context_cache_index.get((context_digest, text_digest))
            if text_digest:
                return self._cross_model_text_cache_index.get(text_digest)
        return None

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

    def _is_trusted_manual_cache(self, text: str) -> bool:
        self._load_manual_cache()
        entry = self._manual_cache.get(self._manual_cache_key(text))
        if isinstance(entry, str):
            return True
        if isinstance(entry, dict):
            return bool(entry.get("trusted", True))
        return False

    def _flush_manual_cache(self):
        manual_cache_path = str(get_data_dir() / self.MANUAL_CACHE_FILE_NAME)
        self._atomic_write_json(manual_cache_path, self._manual_cache)

    def save_manual_translation(self, src: str, dst: str, trusted: bool = True) -> None:
        """保存人工译文并立即更新内存缓存。"""
        src = (src or "").strip()
        dst = (dst or "").strip()
        if not src or not dst:
            raise ValueError("原文和译文不能为空")
        self._load_manual_cache(force=True)
        self._manual_cache[self._manual_cache_key(src)] = {
            "source": src,
            "translation": dst,
            "trusted": bool(trusted),
            "updated_at": int(time.time()),
        }
        self._flush_manual_cache()

    def lookup_cached_translation(self, src: str) -> Tuple[Optional[str], str]:
        """Return cached translation and source label for UI-side manual editing."""
        src = (src or "").strip()
        if not src:
            return None, ""

        manual = self._lookup_manual_cache(src)
        if manual:
            return manual, "manual"

        self._load_text_cache()
        text_entry = self._text_cache.get(self._text_cache_key(src))
        if isinstance(text_entry, dict) and text_entry.get("translation"):
            return str(text_entry.get("translation")), "text_cache"

        cache_key = self._cache_key(src)
        with self._cache_lock:
            model_cached = self.cache.get(cache_key)
            if not model_cached:
                digest = self._cache_digest(src)
                for key, value in self.cache.items():
                    if digest in str(key):
                        model_cached = value
                        break
        if model_cached:
            return str(model_cached), "model_cache"

        return None, ""

    def _lookup_text_cache(self, text: str, allow_unverified: bool = False) -> Optional[str]:
        """查找文本级缓存；恢复续译时可复用已通过安全校验的普通译文。"""
        if getattr(self, "glossary_fingerprint", ""):
            return None
        self._load_text_cache()
        key = self._text_cache_key(text)
        entry = self._text_cache.get(key)
        if entry and isinstance(entry, dict) and (entry.get("verified", False) or allow_unverified):
            return entry.get("translation")
        return None

    def _save_text_cache_entry(self, text: str, translation: str, verified: bool = False):
        """保存文本级缓存条目。"""
        if getattr(self, "glossary_fingerprint", ""):
            return
        self._load_text_cache()
        key = self._text_cache_key(text)
        entry = {
            "translation": translation,
            "verified": verified,
            "updated_at": int(time.time()),
        }
        with self._cache_lock:
            # 不覆盖已 verified 的条目
            existing = self._text_cache.get(key, {})
            if isinstance(existing, dict) and existing.get("verified", False):
                return
            if isinstance(existing, dict) and existing.get("translation") == translation and bool(existing.get("verified", False)) == bool(verified):
                return
            self._text_cache[key] = entry
            self._text_cache_dirty_count = int(getattr(self, "_text_cache_dirty_count", 0)) + 1
            should_flush = self._text_cache_dirty_count >= self.TEXT_CACHE_SAVE_THRESHOLD
        if should_flush:
            self._flush_text_cache()

    def _flush_text_cache(self):
        """持久化文本缓存。"""
        with self._cache_lock:
            if not self._text_cache:
                return
            snapshot = dict(self._text_cache)
            dirty_count = int(getattr(self, "_text_cache_dirty_count", 0))
        text_cache_path = str(get_data_dir() / self.TEXT_CACHE_FILE_NAME)
        self._atomic_write_json(text_cache_path, snapshot)
        if dirty_count > 0:
            with self._cache_lock:
                self._text_cache_dirty_count = max(
                    0,
                    int(getattr(self, "_text_cache_dirty_count", 0)) - dirty_count,
                )

    def _save_cache(self, force: bool = False):
        """保存缓存到文件，使用延迟写入策略。"""
        snapshot = None
        with self._cache_lock:
            self._cache_dirty = True
            self._save_counter += 1

            if force or self._save_counter >= self.CACHE_SAVE_THRESHOLD:
                snapshot = dict(self.cache)
                self._cache_dirty = False
                self._save_counter = 0

        if snapshot is None:
            return

        try:
            self._atomic_write_json(self.cache_path, snapshot)
        except IOError as e:
            with self._cache_lock:
                self._cache_dirty = True
            logger.error(f"缓存保存失败: {e}")

    def flush_cache(self):
        """强制保存缓存（程序退出或翻译完成时调用）"""
        with self._cache_lock:
            cache_dirty = self._cache_dirty
        if cache_dirty:
            self._save_cache(force=True)
        self._flush_text_cache()

    def disable_cache_writes(self) -> None:
        """停止本实例继续写入翻译缓存，用于“停止并清空本次译文”。"""
        flag = getattr(self, "_discard_cache_writes", None)
        if flag is None:
            self._discard_cache_writes = threading.Event()
            flag = self._discard_cache_writes
        flag.set()

    def discard_cache_writes(self) -> None:
        """Backward-compatible alias for older bridge/test code."""
        self.disable_cache_writes()

    def request_cancel(self, close_session: bool = True) -> None:
        """Request cooperative cancellation and close HTTP connections best-effort.

        ``requests`` calls cannot be interrupted by ``threading.Event`` while a
        socket read is in progress. Closing the session gives in-flight provider
        calls a chance to fail fast during app shutdown instead of keeping
        ThreadPoolExecutor workers alive until the read timeout expires.
        """
        self.cancel_event.set()
        if close_session:
            try:
                self.session.close()
            except Exception:
                pass

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

        # Build lookup sets: plain原文, sha256, md5 — legacy cache.json stores
        # entries under the plain source text, while newer builds use
        # "v2:provider:model:<sha256>" / "v3ctx:..." keys. Match every form.
        plain_texts = set(unique_texts)
        digests = set()
        for text in unique_texts:
            raw = text.encode("utf-8")
            digests.add(hashlib.sha256(raw).hexdigest())
            digests.add(hashlib.md5(raw).hexdigest())

        removed = 0
        with self._cache_lock:
            # If this translator instance was just constructed (e.g. from the
            # QML "clear cache" button) its in-memory cache is empty even
            # though cache.json on disk is populated. Load it first so we
            # actually have something to clear.
            if not self.cache:
                try:
                    loaded = self._load_json(self.cache_path, {})
                    if isinstance(loaded, dict) and loaded:
                        self.cache = loaded
                        self._cache_dirty = False
                except Exception as e:
                    logger.warning(f"加载缓存以进行清理失败: {e}")

            if all_models:
                def _matches(key: str) -> bool:
                    s = str(key)
                    if s in plain_texts:
                        return True
                    return any(s.endswith(f":{d}") or s == d for d in digests)

                keys_to_remove = [key for key in list(self.cache) if _matches(key)]
                for key in keys_to_remove:
                    self.cache.pop(key, None)
                    removed += 1
            else:
                for text in unique_texts:
                    cache_key = self._cache_key(text)
                    if cache_key in self.cache:
                        self.cache.pop(cache_key, None)
                        removed += 1
                    # Legacy fallback: also drop a plain-text key if present.
                    if text in self.cache and text != cache_key:
                        self.cache.pop(text, None)
                        removed += 1
            if removed:
                self._cache_dirty = True
                self._invalidate_cross_model_cache_index()

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
                self._invalidate_cross_model_cache_index()

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
        entries = gs_select_glossary_entries(
            context_text,
            glossary_snapshot,
            self.glossary_categories,
            limit,
            glossary_index=glossary_index,
        )
        filtered = []
        for entry in entries:
            original = str(entry.get("original", "")).strip()
            metadata = self._lookup_glossary_metadata(original)
            if metadata:
                entry = {**entry, **{k: v for k, v in metadata.items() if v}}
            if self._glossary_enforcement_level(entry) == "ignore":
                continue
            filtered.append(entry)
        return filtered


    def _build_glossary_text(self, selected_entries: Optional[List[Dict[str, str]]] = None) -> str:
        """?????????? selected_entries ?????????"""
        with self._cache_lock:
            glossary_snapshot = dict(self.glossary)
        return gs_build_glossary_text(glossary_snapshot, self.glossary_categories, selected_entries)

    def _hymt2_uses_official_prompt(self) -> bool:
        return self.provider == "hymt2" and self.hymt2_prompt_mode == "official"

    def _build_hymt2_official_glossary_text(self, selected_entries: Optional[List[Dict[str, str]]]) -> str:
        lines: List[str] = []
        for entry in selected_entries or []:
            original = str(entry.get("original", "")).strip()
            target = self._expected_glossary_translation(entry).strip()
            if original and target:
                lines.append(f"{original} 翻译成 {target}")
        return "\n".join(lines)

    def _build_hymt2_official_style_hint(self) -> str:
        _, _, genre_label, tone_label = self._get_style_profile()
        hints = []
        if genre_label:
            hints.append(genre_label)
        if tone_label:
            hints.append(tone_label)
        if not hints:
            return ""
        return f"注意翻译风格要符合【{' + '.join(hints)}】，但不要添加解释。"

    def _build_hymt2_official_user_prompt(
        self,
        text: str,
        selected_entries: Optional[List[Dict[str, str]]] = None,
        residue_guidance: str = "",
    ) -> str:
        parts: List[str] = []
        glossary_text = self._build_hymt2_official_glossary_text(selected_entries)
        if glossary_text:
            parts.append(f"参考下面的翻译：\n{glossary_text}")
        style_hint = self._build_hymt2_official_style_hint()
        if style_hint:
            parts.append(style_hint)
        custom_guidance = self._build_custom_prompt_guidance()
        if custom_guidance:
            parts.append(custom_guidance)
        if residue_guidance:
            parts.append(residue_guidance)
        parts.append(
            "将以下日语文本翻译为简体中文，注意只需要输出翻译后的结果，不要额外解释：\n\n"
            f"{text}"
        )
        return "\n\n".join(part for part in parts if part.strip())

    def _get_style_profile(self) -> Tuple[str, str, str, str]:
        genre = self.proofread_genre if self.proofread_genre in GENRE_LABELS else "general"
        tone = self.proofread_tone if self.proofread_tone in TONE_LABELS else "neutral"
        return genre, tone, GENRE_LABELS.get(genre, "通用小说"), TONE_LABELS.get(tone, "中性口吻")

    def _build_style_examples(self) -> str:
        if not bool(getattr(self, "enable_prompt_examples", True)):
            return ""
        genre, tone, genre_label, tone_label = self._get_style_profile()
        sections = []
        genre_example = self.STYLE_FEW_SHOT_EXAMPLES.get(genre)
        if genre_example:
            src, dst = genre_example
            sections.append(
                f"{genre_label}示例（只学习处理方式，不复用内容）：\n"
                f"日文：{src}\n中文：{dst}"
            )
        tone_example = self.TONE_FEW_SHOT_EXAMPLES.get(tone)
        if tone_example:
            src, dst = tone_example
            sections.append(
                f"{tone_label}示例（只学习语气，不添加示例内容）：\n"
                f"日文：{src}\n中文：{dst}"
            )
        if not sections:
            return ""
        return "【示例引导】\n" + "\n\n".join(sections)

    @staticmethod
    def _simplified_chinese_output_rule() -> str:
        return (
            "【简体中文输出要求】\n"
            "必须输出简体中文。不要输出繁体字、异体字或台湾/香港用字；"
            "如模型内部生成繁体表达，必须转换为大陆简体中文后再输出。"
        )

    def _build_custom_prompt_guidance(self) -> str:
        text = str(getattr(self, "prompt_extra_instruction", "") or "").strip()
        if not text:
            return ""
        if len(text) > 1600:
            text = text[:1600].rstrip() + "..."
        return (
            "【用户补充要求】\n"
            "在不违反“准确、不新增剧情、不输出说明、保持段落结构”的前提下，遵守以下补充要求：\n"
            f"{text}"
        )

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
            "historical_mystery": [
                "按历史捕物/时代推理处理，优先保证案情线索、称谓、官职、地名和时代语境准确。",
                "不要把江户时代对白改成现代轻小说吐槽腔，不要自由润色或补解释。",
                "对奉行、与力、同心、冈引、町火消、旗本、长屋等时代词保持稳定译法。",
                "保留推理信息的不确定性，不替读者解释暗号、物证或人物动机。",
                "对白可以自然中文化，但不能牺牲时代感、阶层关系和原文粗粝口吻。",
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
                "3. 专有名词按术语表策略处理：强制使用必须遵守；仅供参考/上下文命中不得机械强改；保留原文必须保留源词。\n"
                "4. 保持原段落结构，不合并、不拆分段落。\n"
                "5. 不解释原文，不输出注释，不输出修改说明。\n"
                "6. 只输出修正后的简体中文译文。\n\n"
            )
        else:
            header = (
                "当前翻译风格设置：\n"
                f"- 作品类型：{genre_label}\n"
                f"- 叙事口吻：{tone_label}\n\n"
                "请按上述类型与口吻进行初译，同时必须遵守：\n"
                "1. 不新增剧情、不删除信息、不改变原意。\n"
                "2. 专有名词按术语表策略处理：强制使用必须遵守；仅供参考/上下文命中需结合语境；保留原文不翻译。\n"
                "3. 保持原段落结构，不合并、不拆分段落。\n"
                "4. 保持人物语气、叙事节奏和情绪层次。\n"
                "5. 只输出简体中文译文，不输出解释或注释。\n\n"
            )

        parts = [
            self._simplified_chinese_output_rule(),
            header + f"{genre_label}要求：\n{numbered(genre_rules[genre])}\n\n{tone_label}要求：\n{numbered(tone_rules[tone])}"
        ]
        examples = self._build_style_examples()
        if examples:
            parts.append(examples)
        custom_guidance = self._build_custom_prompt_guidance()
        if custom_guidance:
            parts.append(custom_guidance)
        return "\n\n".join(parts)

    def build_prompt_preview(self) -> str:
        """Build a local preview of active prompt fragments without calling any API."""
        sample_glossary_entries = [
            {"original": "術語A", "translation": "译名A"},
            {"original": "術語B", "translation": "译名B"},
        ]
        if self._hymt2_uses_official_prompt():
            single_user = self._build_hymt2_official_user_prompt(
                "ここに翻訳対象の日本語が入ります。",
                selected_entries=sample_glossary_entries,
            )
            return (
                "【Hy-MT2 官方简洁 Prompt 模板】\n"
                "System Prompt：不使用\n\n"
                "【User Prompt 模板】\n"
                f"{single_user}"
            )

        translation_system = self._build_style_guidance("translation")
        proofread_system = self._build_proofread_system_prompt()
        sample_glossary = (
            "术语A->译名A #强制使用\n"
            "术语B->译名B #仅在上下文符合时使用；备注示例\n"
            "术语C->术语C #保留原文不翻译"
        )
        single_user = (
            f"【术语表】\n{sample_glossary}\n\n"
            f"{self._translation_task_instruction()}\n"
            "ここに翻訳対象の日本語が入ります。\n\n"
            "【前文上下文（仅供参考，帮助理解当前文本的语境，无需翻译）】\n前一段文本预览\n\n"
            "【后文上下文（仅供参考，帮助理解当前文本的语境，无需翻译）】\n后一段文本预览"
        )
        proofread_user = (
            "【发现的问题】\n"
            "- 译文中疑似残留日文假名\n"
            "- 术语未按术语表翻译\n\n"
            f"【术语表】\n{sample_glossary}\n\n"
            "【日文原文】\nここに校对対象の日本語が入ります。\n\n"
            "【中文初译】\n这里是中文初译。\n\n"
            "【输出格式】\n只输出修正后的简体中文译文。禁止输出说明、修改说明、理由、注释、括号说明或项目符号。"
        )
        return (
            "【初译 System Prompt 片段】\n"
            f"{translation_system}\n\n"
            "【初译 User Prompt 模板】\n"
            f"{single_user}\n\n"
            "【译后校对 System Prompt 片段】\n"
            f"{proofread_system}\n\n"
            "【译后校对 User Prompt 模板】\n"
            f"{proofread_user}"
        )


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

    @staticmethod
    def _normalize_glossary_extraction_mode(value: Any) -> str:
        mode = str(value or "").strip().lower()
        if mode not in GLOSSARY_EXTRACTION_MODES:
            return "novel"
        return mode

    def _build_glossary_extraction_system_prompt(self, extraction_mode: Optional[str] = None) -> str:
        mode = self._normalize_glossary_extraction_mode(extraction_mode or self.glossary_extraction_mode)
        if self._extraction_prompt_data:
            template = self._extraction_prompt_data.get("glossary_extraction_prompt", "")
            if template:
                prompt = resolve_template_vars(
                    template,
                    target_lang="简体中文",
                    extraction_mode=mode,
                    glossary_extraction_mode=mode,
                )
            else:
                prompt = ""
        else:
            prompt = ""

        if not prompt:
            prompt = "你是专业的日文术语提取助手。"

        if mode == "lite":
            prompt += (
                "\n\n提取模式：精简模式。只提取人物名和地名；"
                "不要提取普通名词、道具、组织、技能、注音、片假名噪声或说明性文字。"
            )
        else:
            prompt += (
                "\n\n提取模式：小说模式。优先提取人物名、地名、组织名、道具名、技能名和虚构生物名，"
                "但仍然宁缺毋滥，不要提取普通名词或解释性文字。"
            )

        prompt += (
            "\n\n输出要求：只输出 JSON 对象，顶层字段仅允许 new_terms。"
            "new_terms 的每个元素格式为 {\"src\":\"原词\",\"dst\":\"译词\",\"category\":\"分类\"}。"
            "不要输出解释、前后缀说明或代码块外文字。"
        )
        return prompt.rstrip()

    def _translation_task_instruction(self) -> str:
        """Return the user-facing translation instruction for the active style."""
        genre, _, _, _ = self._get_style_profile()
        if genre == "historical_mystery":
            return "请将以下日文准确、克制、自然地翻译为简体中文，不要自由润色、不要补充解释："
        return "请将以下日文翻译为优美流畅的简体中文："

    def _get_moderation_fallback_config(self) -> Optional[Dict[str, str]]:
        """Use the configured proofread model as a translation fallback after moderation blocks."""
        configured = bool(
            self.proofread_provider
            or self._proofread_api_url
            or self.proofread_model
            or self.proofread_api_key
        )
        if not configured:
            return None

        provider = (self.proofread_provider or self.provider or "").strip().lower()
        api_url = self._get_proofread_url() if (self.proofread_provider or self._proofread_api_url) else self.api_url
        model = self.proofread_model or self._get_provider_default_model(provider) or self.model
        api_key = self.proofread_api_key or (self.api_key if provider == self.provider else "")
        local_no_key_providers = {"sakura", "hymt2"}
        if provider != self.provider and not self.proofread_api_key and provider not in local_no_key_providers:
            logger.warning("内容审核备用模型未配置校对 API Key，跳过备用翻译: provider=%s", provider)
            return None
        if not api_url or not model or (not api_key and provider not in local_no_key_providers):
            return None
        if (
            provider == self.provider
            and self._normalize_api_url(api_url) == self.api_url
            and model == self.model
            and (api_key or "") == (self.api_key or "")
        ):
            return None
        return {"provider": provider, "api_url": self._normalize_api_url(api_url), "model": model, "api_key": api_key}

    def _call_moderation_fallback_translation(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
    ) -> Optional[SingleChunkResult]:
        fallback = self._get_moderation_fallback_config()
        if not fallback:
            return None

        provider = fallback["provider"]
        payload = {
            "model": fallback["model"],
            "messages": messages,
            "temperature": temperature,
        }
        self._apply_provider_payload_options(payload, provider)
        headers = {
            "Authorization": f"Bearer {fallback['api_key'] or 'sk-local'}",
            "Content-Type": "application/json",
        }
        logger.info(
            "主模型内容审核拦截，改用校对模型作为备用翻译: provider=%s, model=%s",
            provider,
            fallback["model"],
        )

        last_error = None
        for attempt in range(2):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._inc_stat("moderation_fallback_requests")
                self._wait_provider_rate_budget(
                    estimated_tokens=self._estimate_request_tokens(messages=messages, source_text=messages, batch_size=1),
                    estimated_requests=1,
                    context="内容审核备用翻译",
                )
                self._inc_stat("api_requests_total")
                request_started = time.time()
                resp = self.session.post(
                    fallback["api_url"],
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                self._log_api_request_event(
                    "内容审核备用翻译",
                    request_started,
                    "ok" if 200 <= resp.status_code < 300 else "http_error",
                    status_code=resp.status_code,
                    attempt=attempt,
                    max_retries=2,
                    provider=provider,
                    model=fallback["model"],
                    url=fallback["api_url"],
                    batch_size=1,
                    messages=messages,
                    source_text=messages,
                    response_text=getattr(resp, "text", ""),
                )
                resp.raise_for_status()
                data = resp.json()
                self._accumulate_usage_tokens(data)
                choices = data.get("choices", [])
                if not choices:
                    last_error = "备用模型响应缺少 choices"
                    continue
                content = ((choices[0].get("message", {}) or {}).get("content", "") or "").strip()
                if not content:
                    last_error = "备用模型响应缺少 content"
                    continue
                self._inc_stat("moderation_fallback_success")
                return SingleChunkResult(
                    content=content,
                    finish_reason=self._get_finish_reason(data),
                    is_truncated=self._get_finish_reason(data) == "length",
                )
            except requests.exceptions.HTTPError as e:
                self._inc_stat("api_requests_failed")
                self._log_api_request_event(
                    "内容审核备用翻译",
                    locals().get("request_started", time.time()),
                    "http_error",
                    status_code=getattr(getattr(e, "response", None), "status_code", None),
                    attempt=attempt,
                    max_retries=2,
                    provider=provider,
                    model=fallback["model"],
                    url=fallback["api_url"],
                    batch_size=1,
                    messages=messages,
                    source_text=messages,
                    response_text=getattr(getattr(e, "response", None), "text", ""),
                    error=e,
                )
                self._log_http_error_response(
                    e,
                    "内容审核备用翻译",
                    attempt=attempt,
                    max_retries=2,
                    provider=provider,
                    model=fallback["model"],
                )
                if self._is_content_moderation_http_error(e):
                    last_error = "备用模型也被内容审核拦截"
                    break
                last_error = f"备用模型 HTTP 错误: {e}"
            except Exception as e:
                self._inc_stat("api_requests_failed")
                self._log_api_request_event(
                    "内容审核备用翻译",
                    locals().get("request_started", time.time()),
                    "request_error",
                    attempt=attempt,
                    max_retries=2,
                    provider=provider,
                    model=fallback["model"],
                    url=fallback["api_url"],
                    batch_size=1,
                    messages=messages,
                    source_text=messages,
                    error=e,
                )
                last_error = str(e)
                logger.warning("内容审核备用翻译失败 (尝试 %s/2): %s", attempt + 1, e)
        logger.warning("内容审核备用翻译未成功: %s", last_error or "未知错误")
        return None

    def _call_deepseek_single(
        self,
        text: str,
        max_retries: int = 3,
        text_separator: Optional[str] = None,
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
        residue_guidance: str = "",
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
1. 输出仅为简体中文译文，不要解释或添加原文
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
        if self._hymt2_uses_official_prompt():
            user_prompt = self._build_hymt2_official_user_prompt(
                text,
                selected_entries=selected_entries,
                residue_guidance=residue_guidance,
            )
            messages = [{"role": "user", "content": user_prompt}]
        else:
            context_guidance = ""
            if self._provider_uses_context_window() and (prev_text or next_text):
                context_guidance = "\n\n" + self._build_context_guidance(prev_text, next_text)
            residue_guidance_text = f"\n\n{residue_guidance}" if residue_guidance else ""
            user_prompt = (
                f"【术语表】\n{self._build_glossary_text(selected_entries)}\n\n"
                f"{self._translation_task_instruction()}\n{text}"
                f"{context_guidance}"
                f"{residue_guidance_text}"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
                self._wait_dynamic_backoff()
                self._wait_provider_rate_budget(
                    estimated_tokens=self._estimate_request_tokens(messages=messages, source_text=text, batch_size=1),
                    estimated_requests=1,
                    context="单条翻译",
                )
                self._inc_stat("api_requests_total")
                request_started = time.time()
                resp = self.session.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=self.API_TIMEOUT,
                )
                self._log_api_request_event(
                    "单条翻译",
                    request_started,
                    "ok" if 200 <= resp.status_code < 300 else "http_error",
                    status_code=resp.status_code,
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=1,
                    messages=messages,
                    source_text=text,
                    response_text=getattr(resp, "text", ""),
                )

                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    self._record_dynamic_limit_event("HTTP 429", kind="rate")
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
                    self._record_dynamic_limit_event("API 响应缺少 choices 字段", kind="format")
                    raise KeyError("API 响应缺少 choices 字段")
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if not content:
                    self._record_dynamic_limit_event("API 响应缺少 content 字段", kind="format")
                    raise KeyError("API 响应缺少 content 字段")

                content = content.strip()
                self._record_api_success_event()
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
                self._record_dynamic_limit_event("请求超时", kind="timeout")
                last_error = "请求超时"
                self._log_api_request_event(
                    "单条翻译",
                    locals().get("request_started", time.time()),
                    "timeout",
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=1,
                    messages=messages,
                    source_text=text,
                    error=last_error,
                )
                logger.warning(f"API 请求超时 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                self._inc_stat("api_requests_failed")
                last_error = "网络连接失败"
                self._log_api_request_event(
                    "单条翻译",
                    locals().get("request_started", time.time()),
                    "connection_error",
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=1,
                    messages=messages,
                    source_text=text,
                    error=last_error,
                )
                logger.warning(f"网络连接失败 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.HTTPError as e:
                self._inc_stat("api_requests_failed")
                self._log_api_request_event(
                    "单条翻译",
                    locals().get("request_started", time.time()),
                    "http_error",
                    status_code=getattr(getattr(e, "response", None), "status_code", None),
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=1,
                    messages=messages,
                    source_text=text,
                    response_text=getattr(getattr(e, "response", None), "text", ""),
                    error=e,
                )
                body_snippet = self._log_http_error_response(
                    e,
                    "单条翻译",
                    attempt=attempt,
                    max_retries=max_retries,
                )
                last_error = f"HTTP 错误: {e}"
                if body_snippet:
                    last_error += f"; 响应体: {self._response_snippet(body_snippet, limit=240)}"
                if self._is_content_moderation_http_error(e):
                    self._inc_stat("content_moderation_reject")
                    fallback_result = self._call_moderation_fallback_translation(
                        messages,
                        float(payload.get("temperature", self.temperature) or 0.3),
                    )
                    if fallback_result is not None:
                        return fallback_result
                    break
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
        residue_guidance: str = "",
    ) -> str:
        """向后兼容的包装器，仅返回 content 字符串"""
        result = self._call_deepseek_single(text, max_retries, text_separator,
                                              prev_text=prev_text, next_text=next_text,
                                              residue_guidance=residue_guidance)
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
        elif self._provider_uses_context_window() and (prev_text or next_text):
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

        def retry_or_fail(reason: str, finish_reason: Optional[str] = None, raw_content: str = "") -> Optional[BatchJsonResult]:
            """Retry malformed batch JSON once more; after max retries, let caller fall back to single translation."""
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt + random.uniform(0, 1)
                logger.info(
                    "%s，准备重试批量 JSON (%s/%s)",
                    reason,
                    attempt + 1,
                    max_retries,
                )
                if self.cancel_event.wait(wait_time):
                    raise RuntimeError("翻译已取消")
                return None
            return BatchJsonResult(
                translations=None,
                missing_indices=list(range(len(texts))),
                finish_reason=finish_reason,
                raw_content=raw_content,
            )

        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")
            try:
                self._wait_dynamic_backoff()
                self._inc_stat("api_requests_total")
                request_started = time.time()
                resp = self._post_batch_json_payload(
                    headers,
                    payload,
                    messages=messages,
                    source_text=numbered,
                    batch_size=len(texts),
                    context="批量JSON翻译",
                )
                self._log_api_request_event(
                    "批量JSON翻译",
                    request_started,
                    "ok" if 200 <= resp.status_code < 300 else "http_error",
                    status_code=resp.status_code,
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=len(texts),
                    messages=messages,
                    source_text=numbered,
                    response_text=getattr(resp, "text", ""),
                )
                if resp.status_code == 429:
                    self._inc_stat("api_requests_failed")
                    self._record_dynamic_limit_event("批量 JSON HTTP 429", kind="rate")
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
                    self._record_dynamic_limit_event("批量 JSON 缺少 choices", kind="format")
                    failed = retry_or_fail("批量 JSON 缺少 choices", finish_reason=self._get_finish_reason(data))
                    if failed is None:
                        continue
                    return failed
                message = choices[0].get("message", {})
                raw = message.get("content", "")
                if not raw:
                    self._inc_stat("batch_json_parse_fail")
                    self._record_dynamic_limit_event("批量 JSON 缺少 content", kind="format")
                    failed = retry_or_fail("批量 JSON 缺少 content", finish_reason=self._get_finish_reason(data))
                    if failed is None:
                        continue
                    return failed

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
                    lenient_items = self._extract_lenient_indexed_items(raw)
                    if lenient_items:
                        obj = {"translations": lenient_items, "new_terms": []}
                        self._inc_stat("batch_json_lenient_success")
                        logger.info("批量 JSON 宽松解析成功: %s/%s 条", len(lenient_items), len(texts))
                    else:
                        self._inc_stat("batch_json_parse_fail")
                        logger.warning("批量 JSON 解析失败，响应摘要: %s", self._response_snippet(raw))
                        self._record_dynamic_limit_event("批量 JSON 解析失败", kind="format")
                        failed = retry_or_fail("批量 JSON 解析失败", finish_reason=finish_reason, raw_content=raw)
                        if failed is None:
                            continue
                        failed.is_truncated = is_truncated
                        return failed

                arr = obj.get("translations") or obj.get("items")
                if not isinstance(arr, list):
                    lenient_items = self._extract_lenient_indexed_items(raw)
                    if lenient_items:
                        arr = lenient_items
                        obj = {"translations": arr, "new_terms": []}
                        self._inc_stat("batch_json_lenient_success")
                        logger.info("批量 JSON 宽松解析补全 translations: %s/%s 条", len(lenient_items), len(texts))
                    else:
                        self._inc_stat("batch_json_parse_fail")
                        logger.warning("批量 JSON 缺少 translations/items，响应摘要: %s", self._response_snippet(raw))
                        self._record_dynamic_limit_event("批量 JSON 缺少 translations/items", kind="format")
                        failed = retry_or_fail("批量 JSON 缺少 translations/items", finish_reason=finish_reason, raw_content=raw)
                        if failed is None:
                            continue
                        failed.is_truncated = is_truncated
                        return failed

                # 逐条校验 idx，跳过无效项（防幻觉），保留有效项
                out = [None] * len(texts)
                valid_indices = set()

                for position, item in enumerate(arr):
                    if isinstance(item, str):
                        idx = position
                        zh = item
                    elif isinstance(item, dict):
                        idx = item.get("idx", item.get("index", item.get("id", position)))
                        if isinstance(idx, str) and idx.strip().isdigit():
                            idx = int(idx.strip())
                        zh = (
                            item.get("zh")
                            or item.get("translation")
                            or item.get("translated")
                            or item.get("text")
                            or item.get("cn")
                            or item.get("中文")
                            or item.get("dst")
                        )
                    else:
                        continue
                    if not isinstance(idx, int) or idx < 0 or idx >= len(texts):
                        continue
                    if not isinstance(zh, str) or not zh.strip():
                        continue
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

                if valid_indices:
                    self._record_api_success_event()
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
            except requests.exceptions.Timeout as e:
                self._inc_stat("api_requests_failed")
                self._record_dynamic_limit_event("批量 JSON 请求超时", kind="timeout")
                self._log_api_request_event(
                    "批量JSON翻译",
                    locals().get("request_started", time.time()),
                    "timeout",
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=len(texts),
                    messages=messages,
                    source_text=numbered,
                    error=e,
                )
                logger.warning(f"批量翻译请求超时 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                return BatchJsonResult(
                    translations=None, missing_indices=list(range(len(texts))),
                )
            except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
                self._inc_stat("api_requests_failed")
                self._log_api_request_event(
                    "批量JSON翻译",
                    locals().get("request_started", time.time()),
                    "http_error" if isinstance(e, requests.exceptions.HTTPError) else "request_error",
                    status_code=getattr(getattr(e, "response", None), "status_code", None),
                    attempt=attempt,
                    max_retries=max_retries,
                    batch_size=len(texts),
                    messages=messages,
                    source_text=numbered,
                    response_text=getattr(getattr(e, "response", None), "text", ""),
                    error=e,
                )
                if isinstance(e, requests.exceptions.HTTPError):
                    if self._is_content_moderation_http_error(e):
                        self._inc_stat("batch_moderation_reject")
                        logger.warning(
                            "批量 JSON 翻译被内容审核拦截 (尝试 %s/%s): %s",
                            attempt + 1,
                            max_retries,
                            e,
                        )
                        raise ContentModerationError(
                            f"内容审核拦截: {e}",
                            offending_indices=list(range(len(texts))),
                        )
                    self._log_http_error_response(
                        e,
                        "批量 JSON 翻译",
                        attempt=attempt,
                        max_retries=max_retries,
                    )
                else:
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

    def extract_glossary_candidates(
        self,
        texts: List[str],
        *,
        batch_size: Optional[int] = None,
        max_chars: int = 30000,
        max_texts: int = 120,
        extraction_mode: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """Pre-extract glossary candidates before a full translation run."""
        try:
            from text_utils import is_translatable
        except Exception:
            def is_translatable(value: str) -> bool:
                return bool(str(value or "").strip())

        selected: List[str] = []
        char_total = 0
        for text in texts or []:
            value = str(text or "").strip()
            if not value or not is_translatable(value):
                continue
            if value in selected:
                continue
            if len(selected) >= max_texts:
                break
            if char_total + len(value) > max_chars and selected:
                break
            selected.append(value)
            char_total += len(value)

        if not selected:
            return {"terms": [], "glossary": {cat: [] for cat in self.glossary_categories}, "text_count": 0, "char_count": 0}

        effective_batch_size = max(1, min(int(batch_size or self.batch_size or 1), 12))
        mode = self._normalize_glossary_extraction_mode(extraction_mode or self.glossary_extraction_mode)
        raw_terms: List[Dict[str, Any]] = []
        total_batches = (len(selected) + effective_batch_size - 1) // effective_batch_size
        for batch_index in range(total_batches):
            if self.cancel_event.is_set():
                raise RuntimeError("术语预提取已取消")
            start = batch_index * effective_batch_size
            chunk = selected[start:start + effective_batch_size]
            result = self._call_glossary_extraction_json(
                chunk,
                max_retries=2,
                extraction_mode=mode,
            )
            batch_terms = list(result.new_terms or []) if result else []
            raw_terms.extend(batch_terms)
            logger.info(
                "术语预提取批次: %s/%s, mode=%s, texts=%s, raw_terms=%s",
                batch_index + 1,
                total_batches,
                mode,
                len(chunk),
                len(batch_terms),
            )
            if progress_callback:
                progress_callback(batch_index + 1, total_batches)

        cleaned = self._clean_new_terms(raw_terms)
        if mode == "lite":
            cleaned = [
                term
                for term in cleaned
                if str(term.get("category", "")).strip() in {"Person", "Location"}
            ]
        logger.info(
            "术语预提取完成: mode=%s, text_count=%s, char_count=%s, raw_terms=%s, cleaned_terms=%s",
            mode,
            len(selected),
            char_total,
            len(raw_terms),
            len(cleaned),
        )
        normalized_by_category = {cat: [] for cat in self.glossary_categories}
        seen = set()
        for term in cleaned:
            src = str(term.get("src", "")).strip()
            dst = str(term.get("dst", "")).strip()
            category = str(term.get("category", "Item")).strip() or "Item"
            if category not in self.glossary_categories:
                category = "Item"
            if not src or not dst:
                continue
            key = src
            if key in seen:
                continue
            seen.add(key)
            entry = {"original": src, "translation": dst, "source": "preextract"}
            info = str(term.get("info", "")).strip()
            if info:
                entry["info"] = info
            policy = gs_normalize_policy(term.get("policy", ""))
            if policy:
                entry["policy"] = policy
            normalized_by_category[category].append(entry)

        return {
            "terms": cleaned,
            "glossary": normalized_by_category,
            "text_count": len(selected),
            "char_count": char_total,
        }


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
                policy = str(term.get("policy", "")).strip()
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
                if policy:
                    entry["policy"] = policy
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

    def _translate_chunk(
        self,
        text: str,
        prev_text: Optional[str] = None,
        next_text: Optional[str] = None,
        residue_guidance: str = "",
    ) -> str:
        """翻译单个文本块（带缓存），可选上下文窗口。"""
        text = text.strip()
        if not text:
            return text

        if self.cancel_event.is_set():
            raise RuntimeError("翻译已取消")

        cache_key = self._cache_key_for_context(text, prev_text, next_text)
        with self._cache_lock:
            if cache_key in self.cache:
                return self.cache[cache_key]

        try:
            zh = self._call_deepseek(
                text,
                prev_text=prev_text,
                next_text=next_text,
                residue_guidance=residue_guidance,
            )
        except TypeError as exc:
            message = str(exc)
            if "residue_guidance" not in message and "unexpected keyword" not in message:
                raise
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
        raw = text.strip()
        if raw in self.PRE_TRANSLATE_RULES:
            return self.PRE_TRANSLATE_RULES[raw]
        stripped = raw.strip('「」『』')
        if stripped in self.PRE_TRANSLATE_RULES:
            return self.PRE_TRANSLATE_RULES[stripped]
        furigana_repaired = tq.repair_furigana_reading_residue(raw)
        if furigana_repaired != raw and not self._has_blocking_japanese_residue(furigana_repaired):
            return furigana_repaired
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

    def _smart_batch_task_keys(
        self,
        task_keys: List[str],
        task_texts: Dict[str, str],
        effective_batch_size: int,
        fast_mode: bool = False,
    ) -> List[List[str]]:
        """Smart-batch internal task keys while measuring the real source text length."""
        short: List[str] = []
        medium: List[str] = []
        long: List[str] = []
        long_threshold = max(
            self.SMART_BATCH_LONG,
            int(getattr(self, "max_text_size_for_batch", self.SMART_BATCH_LONG) or self.SMART_BATCH_LONG),
        )
        if fast_mode:
            long_threshold = max(long_threshold, self.FAST_BATCH_LONG_THRESHOLD)

        for key in task_keys:
            text_len = len(task_texts.get(key, ""))
            if text_len <= self.SMART_BATCH_SHORT:
                short.append(key)
            elif text_len <= long_threshold:
                medium.append(key)
            else:
                long.append(key)

        batches: List[List[str]] = []

        def flush_group(keys: List[str], max_items: int, max_chars: int) -> None:
            current: List[str] = []
            current_len = 0
            for key in keys:
                text_len = len(task_texts.get(key, ""))
                if current and (len(current) >= max_items or current_len + text_len >= max_chars):
                    batches.append(current)
                    current = []
                    current_len = 0
                current.append(key)
                current_len += text_len
            if current:
                batches.append(current)

        if fast_mode:
            max_items = min(max(effective_batch_size, 1), self._fast_batch_max_items_for_provider())
            max_chars = max(int(getattr(self, "max_batch_length", 0) or 0), self.FAST_BATCH_MAX_CHARS)
            short_max_items = max_items if self.provider == "longcat" else min(max_items * 2, 32)
            flush_group(short, short_max_items, max_chars * 2)
            flush_group(medium, max_items, max_chars)
        else:
            flush_group(short, min(effective_batch_size * 2, 20), self.max_batch_length * 2)
            flush_group(medium, effective_batch_size, self.max_batch_length)
        for key in long:
            batches.append([key])

        short_count = len([b for b in batches if b and len(task_texts.get(b[0], "")) <= self.SMART_BATCH_SHORT])
        medium_count = len([
            b for b in batches
            if b and self.SMART_BATCH_SHORT < len(task_texts.get(b[0], "")) <= long_threshold
        ])
        long_count = len([b for b in batches if b and len(task_texts.get(b[0], "")) > long_threshold])
        logger.info(
            f"智能分批: 短文本 {len(short)}→{short_count}批, "
            f"中文本 {len(medium)}→{medium_count}批, "
            f"长文本 {len(long)}→{long_count}批"
            + ("，大书快速模式已启用" if fast_mode else "")
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
        batch_started_at = time.time()
        start_stats = self.get_stats()
        start_api_requests = int(start_stats.get("api_requests_total", 0))
        start_tokens = int(start_stats.get("tokens_total", 0))
        start_batch_total = int(start_stats.get("batch_total", 0))
        start_quality_retranslate = int(start_stats.get("quality_retranslate", 0))
        total_chars = sum(len(str(text or "")) for text in texts)
        planned_batches = 0
        completed = 0
        failed_texts: Dict[str, str] = {}
        residue_texts: Dict[str, str] = {}

        # 使用实例配置，允许传入覆盖
        effective_batch_size = batch_size if batch_size is not None else self.batch_size
        effective_batch_size = max(1, min(int(effective_batch_size or 1), self._current_dynamic_batch_size()))
        fast_batch_mode = (
            self.provider in self.FAST_BATCH_PROVIDERS
            and total >= self.FAST_BATCH_MIN_TEXTS
            and effective_batch_size > 1
        )
        if fast_batch_mode:
            old_effective_batch_size = effective_batch_size
            fast_batch_max_items = self._fast_batch_max_items_for_provider()
            effective_batch_size = min(
                fast_batch_max_items,
                max(effective_batch_size, min(fast_batch_max_items, max(8, old_effective_batch_size * 2))),
            )
            with self._dynamic_limit_lock:
                self._dynamic_batch_size = max(int(self._dynamic_batch_size), effective_batch_size)
            self._set_stat("dynamic_limit_batch_size", self._current_dynamic_batch_size())
            self._set_stat("translate_fast_batch_mode", 1)
            logger.info(
                "%s 大书快速批量: texts=%s, batch_size=%s→%s, max_chars=%s, long_threshold=%s",
                self.provider,
                total,
                old_effective_batch_size,
                effective_batch_size,
                self.FAST_BATCH_MAX_CHARS,
                self.FAST_BATCH_LONG_THRESHOLD,
            )
        else:
            self._set_stat("translate_fast_batch_mode", 0)

        ordered_results: List[Optional[str]] = [None] * total
        self._last_ordered_results = ordered_results
        context_sequence = list(context_texts or texts)
        if len(context_sequence) < total:
            context_sequence = list(texts)
        use_context_window = self._provider_uses_context_window_for_task(total)
        if self._provider_uses_context_window() and not use_context_window:
            logger.info(
                "%s 大书快速策略: texts=%s，已关闭批量上下文窗口以减少 token 与缓存碎片",
                self.provider,
                total,
            )

        def log_translate_summary(status: str, planned: int = 0) -> None:
            elapsed = max(0.001, time.time() - batch_started_at)
            stats = self.get_stats()
            api_delta = max(0, int(stats.get("api_requests_total", 0)) - start_api_requests)
            token_delta = max(0, int(stats.get("tokens_total", 0)) - start_tokens)
            batch_delta = max(0, int(stats.get("batch_total", 0)) - start_batch_total)
            quality_delta = max(0, int(stats.get("quality_retranslate", 0)) - start_quality_retranslate)
            chars_per_second = int(total_chars / elapsed) if total_chars else 0
            texts_per_second = round(float(completed) / elapsed, 2) if completed else 0.0
            self._set_stat("translate_elapsed_ms", int(elapsed * 1000))
            cache_hits = int(stats.get("translate_cache_hits", 0))
            if planned or batch_delta or api_delta:
                logger.info(
                    "批量JSON翻译完成: status=%s, planned_batches=%s, actual_batch_tasks=%s, "
                    "api_requests=%s, tokens=%s, elapsed=%.1fs, fast_batch=%s",
                    status,
                    planned,
                    batch_delta,
                    api_delta,
                    token_delta,
                    elapsed,
                    "on" if fast_batch_mode else "off",
                )
            logger.info(
                "翻译阶段性能汇总: status=%s, texts=%s, completed=%s, chars=%s, elapsed=%.1fs, "
                "chars/s=%s, texts/s=%s, cache_hits=%s, pending_unique=%s, planned_batches=%s, "
                "actual_batch_tasks=%s, api_requests=%s, tokens=%s, quality_retranslate=%s, "
                "context_window=%s, fast_batch=%s",
                status,
                total,
                completed,
                total_chars,
                elapsed,
                chars_per_second,
                texts_per_second,
                cache_hits,
                len(uncached_unique),
                planned,
                batch_delta,
                api_delta,
                token_delta,
                quality_delta,
                "on" if use_context_window else "off",
                "on" if fast_batch_mode else "off",
            )

        def get_context_for_index(idx: int) -> Tuple[Optional[str], Optional[str]]:
            if not use_context_window or idx < 0 or idx >= len(context_sequence):
                return None, None
            prev_text = context_sequence[idx - 1] if idx > 0 else None
            next_text = context_sequence[idx + 1] if idx + 1 < len(context_sequence) else None
            return prev_text, next_text

        uncached_unique: List[str] = []
        pending_tasks: Dict[str, Dict[str, Any]] = {}
        pending_counts: Dict[str, int] = {}
        seen_uncached = set()

        def task_key_for(text: str, idx: int) -> str:
            prev_text, next_text = get_context_for_index(idx)
            return self._cache_key_for_context(text, prev_text, next_text)

        def add_pending_task(text: str, idx: int) -> None:
            key = task_key_for(text, idx)
            prev_text, next_text = get_context_for_index(idx)
            if key not in pending_tasks:
                pending_tasks[key] = {
                    "text": text,
                    "prev": prev_text,
                    "next": next_text,
                    "indices": [],
                }
            pending_tasks[key]["indices"].append(idx)
            pending_counts[key] = pending_counts.get(key, 0) + 1
            if key not in seen_uncached:
                uncached_unique.append(key)
                seen_uncached.add(key)

        def remember_completed(idx: int, text: str, translated: str) -> None:
            translated = self._postprocess_translation(text, translated)
            ordered_results[idx] = translated
            results.setdefault(text, translated)
            mark_complete(text)

        def mark_incomplete(text: str, reason: str, translated: Optional[str] = None) -> None:
            key = str(text or "")
            if not key:
                return
            # merge consecutive identical reasons for content-moderation failures
            prev_reason = failed_texts.get(key)
            if prev_reason and prev_reason != reason and "内容审核拦截" in prev_reason and "内容审核拦截" in reason:
                return
            if translated is not None:
                translated = self._postprocess_translation(key, translated)
            if translated is not None and self._has_blocking_japanese_residue(translated):
                residue_texts[key] = translated
                failed_texts[key] = "译文疑似仍有日文残留"
                return
            if translated is None and key in residue_texts:
                failed_texts.setdefault(key, "译文疑似仍有日文残留")
                return
            failed_texts[key] = reason

        def mark_complete(text: str) -> None:
            key = str(text or "")
            if not key:
                return
            failed_texts.pop(key, None)
            residue_texts.pop(key, None)

        def accept_translation(original: str, translated: Optional[str], reason: str = "") -> Optional[str]:
            cleaned = self._postprocess_translation(original, translated)
            if not cleaned:
                mark_incomplete(original, reason or "译文为空（可能是模型内容审核拦截）", cleaned)
                return None
            if self._is_incomplete_translation(original, cleaned):
                mark_incomplete(original, reason or "译文为空或仍有日文残留", cleaned)
                return None
            mark_complete(original)
            return cleaned

        # Phase 1-③: 预翻译计数
        pre_translated = 0
        manual_cache_hits = 0
        cross_model_cache_hits = 0
        # Phase 1-②: 文本缓存命中计数
        text_cache_hits = 0

        with self._cache_lock:
            for idx, text in enumerate(texts):
                # ① 人工修改缓存优先级最高，不受模型和跨模型缓存开关影响。
                cache_key = task_key_for(text, idx)
                manual_cached = self._lookup_manual_cache(text)
                if manual_cached is not None:
                    manual_cached = self._postprocess_translation(text, manual_cached)
                if manual_cached is not None and (
                    self._is_trusted_manual_cache(text)
                    or not self._is_incomplete_translation(text, manual_cached)
                ):
                    remember_completed(idx, text, manual_cached)
                    self.cache[cache_key] = manual_cached
                    completed += 1
                    manual_cache_hits += 1
                    if item_callback:
                        item_callback(text, manual_cached)
                    continue

                # ② 模型缓存查找
                if cache_key in self.cache:
                    cached_translation = self._postprocess_translation(text, self.cache[cache_key])
                    if not self._is_incomplete_translation(text, cached_translation):
                        if self.cache.get(cache_key) != cached_translation:
                            self.cache[cache_key] = cached_translation
                            self._cache_dirty = True
                        remember_completed(idx, text, cached_translation)
                        completed += 1
                        continue
                    self.cache.pop(cache_key, None)
                    self._cache_dirty = True

                # ③ 跨模型 cache.json 复用：切换模型后恢复续译时复用旧模型已完成译文。
                if getattr(self, "allow_text_cache_reuse", False):
                    cross_cached = self._lookup_cross_model_cache(text, cache_key)
                    if cross_cached is not None:
                        cross_cached = self._postprocess_translation(text, cross_cached)
                        if not self._is_incomplete_translation(text, cross_cached):
                            remember_completed(idx, text, cross_cached)
                            self.cache[cache_key] = cross_cached
                            self._cache_dirty = True
                            completed += 1
                            cross_model_cache_hits += 1
                            if item_callback:
                                item_callback(text, cross_cached)
                            continue

                # ③ Phase 1-③: 本地预翻译规则
                pre_result = self._pre_translate(text)
                if pre_result is not None:
                    pre_result = self._postprocess_translation(text, pre_result)
                    if self._is_incomplete_translation(text, pre_result):
                        add_pending_task(text, idx)
                        continue
                    remember_completed(idx, text, pre_result)
                    # 同步写入模型缓存
                    self.cache[cache_key] = pre_result
                    completed += 1
                    pre_translated += 1
                    if item_callback:
                        item_callback(text, pre_result)
                    continue

                # ④ Phase 1-②: 文本级缓存（跨模型复用已通过安全校验的译文）
                if getattr(self, "allow_text_cache_reuse", False) and not self._is_context_cache_text(text):
                    text_cached = self._lookup_text_cache(text, allow_unverified=True)
                    if text_cached is not None:
                        text_cached = self._postprocess_translation(text, text_cached)
                        if not self._is_incomplete_translation(text, text_cached):
                            remember_completed(idx, text, text_cached)
                            self.cache[cache_key] = text_cached
                            completed += 1
                            text_cache_hits += 1
                            if item_callback:
                                item_callback(text, text_cached)
                            continue

                # ⑤ 未命中，加入待翻译队列
                add_pending_task(text, idx)

        if manual_cache_hits:
            logger.info(f"人工译文缓存命中: {manual_cache_hits} 条")
        if cross_model_cache_hits:
            logger.info(f"跨模型模型缓存命中: {cross_model_cache_hits} 条")
        if pre_translated:
            logger.info(f"预翻译命中: {pre_translated} 条")
        if text_cache_hits:
            logger.info(f"文本缓存命中: {text_cache_hits} 条（跨模型）")
        logger.info(f"批量翻译: {total} 条，缓存命中 {completed} 条，待翻译去重后 {len(uncached_unique)} 条")

        if self.proofread_genre == "historical_mystery" and 0 < len(uncached_unique) <= 20 and effective_batch_size > 1:
            effective_batch_size = 1
            logger.info(
                "历史推理少量剩余文本启用保守重试: batch_size=1，不走批量 JSON，禁用自由润色"
            )
        if self.provider == "hymt2" and self.hymt2_runtime_mode != "gpu" and effective_batch_size > 1:
            old_effective_batch_size = effective_batch_size
            effective_batch_size = 1
            if old_effective_batch_size != effective_batch_size:
                logger.info("Hy-MT2 本地稳定模式: batch_size=1，不走批量 JSON")

        if progress_callback:
            progress_callback(completed, total)

        if not uncached_unique:
            self._save_cache(force=True)
            if pre_translated or text_cache_hits:
                self._flush_text_cache()
            self._set_stat("translate_total_texts", total)
            self._set_stat("translate_cache_hits", completed)
            self._set_stat("translate_pending_unique", 0)
            self._set_stat("translate_planned_batches", 0)
            self._set_stat("translate_context_cache_tasks", 0)
            log_translate_summary("cache_only", planned=0)
            self._last_ordered_results = ordered_results
            return results

        # ---- Phase 1-①: 智能分批 ----
        task_texts = {key: str(task.get("text", "")) for key, task in pending_tasks.items()}
        batches = self._smart_batch_task_keys(
            uncached_unique,
            task_texts,
            effective_batch_size,
            fast_mode=fast_batch_mode,
        )
        planned_batches = len(batches)
        logger.info(f"智能分批为 {planned_batches} 个批次进行并发翻译")
        self._set_stat("translate_total_texts", total)
        self._set_stat("translate_cache_hits", completed)
        self._set_stat("translate_pending_unique", len(uncached_unique))
        self._set_stat("translate_planned_batches", planned_batches)

        if use_context_window:
            context_cache_count = sum(1 for key, task in pending_tasks.items() if key.startswith("v3ctx:"))
            logger.info(f"上下文窗口已启用: {len(context_sequence)} 条文本；上下文缓存任务 {context_cache_count} 个")
            self._set_stat("translate_context_cache_tasks", context_cache_count)
        else:
            self._set_stat("translate_context_cache_tasks", 0)

        def get_context_for_task(task_key: str) -> Tuple[Optional[str], Optional[str]]:
            task = pending_tasks.get(task_key) or {}
            return task.get("prev"), task.get("next")

        residue_repair_examples: Dict[str, Dict[str, str]] = {}
        residue_repair_examples_lock = threading.Lock()

        def get_residue_guidance(fragments: Optional[List[str]]) -> str:
            if not fragments:
                return ""
            with residue_repair_examples_lock:
                examples = [
                    residue_repair_examples[fragment]
                    for fragment in fragments
                    if fragment in residue_repair_examples
                ]
            return self._build_residue_repair_guidance(examples)

        def remember_residue_repair(draft: str, revised: str) -> None:
            fragments = self._extract_japanese_residue_fragments(draft)
            if not fragments:
                return
            if self._has_japanese_residue(revised):
                return
            example_revised = (revised or "").strip()[:160]
            example_draft = (draft or "").strip()[:160]
            if not example_revised or not example_draft:
                return
            with residue_repair_examples_lock:
                for fragment in fragments:
                    residue_repair_examples.setdefault(
                        fragment,
                        {
                            "fragment": fragment,
                            "draft": example_draft,
                            "revised": example_revised,
                        },
                    )

        def call_translate_chunk(
            text: str,
            prev_text: Optional[str] = None,
            next_text: Optional[str] = None,
            residue_fragments: Optional[List[str]] = None,
        ) -> str:
            residue_guidance = get_residue_guidance(residue_fragments)
            try:
                return self._translate_chunk(
                    text,
                    prev_text=prev_text,
                    next_text=next_text,
                    residue_guidance=residue_guidance,
                )
            except TypeError as exc:
                # 兼容测试或旧子类 monkeypatch 的 _translate_chunk(text) 签名。
                message = str(exc)
                if "residue_guidance" in message or "unexpected keyword" in message:
                    try:
                        return self._translate_chunk(text, prev_text=prev_text, next_text=next_text)
                    except TypeError:
                        return self._translate_chunk(text)
                if "prev_text" in message or "next_text" in message or "positional" in message:
                    return self._translate_chunk(text)
                raise

        proofread_residue_fragments_seen: Dict[str, int] = {}
        proofread_residue_fragments_lock = threading.Lock()

        def repair_batch_quality(batch_keys: List[str], pairs: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
            enable_proofread = bool(getattr(self, "enable_proofread", False))
            pairs = [
                (task_key, src, self._postprocess_translation(src, dst))
                for task_key, src, dst in pairs
            ]
            if len(pairs) <= 1 and not enable_proofread:
                return pairs

            suspicious_idx = set()
            proofread_issues: Dict[int, List[str]] = {}
            retranslate_residue_fragments: Dict[int, List[str]] = {}
            batch_text_values = [src for _, src, _ in pairs]
            outputs = [((dst or "").strip()) for _, _, dst in pairs]
            dup_counter: Dict[str, int] = {}
            for out in outputs:
                dup_counter[out] = dup_counter.get(out, 0) + 1

            for i, (_, src, dst) in enumerate(pairs):
                clean_dst = (dst or "").strip()
                if is_suspicious_translation_pair(src, clean_dst):
                    suspicious_idx.add(i)
                    continue
                if clean_dst and dup_counter.get(clean_dst, 0) >= 3 and len(set(batch_text_values)) >= 3:
                    suspicious_idx.add(i)
                    continue
                if enable_proofread:
                    issues = self._find_proofread_issues(src, clean_dst)
                    if issues:
                        # Phase 2-⑤: 校对分级 — 本地检查通过则跳过 LLM 校对
                        if self._should_skip_proofread(src, clean_dst):
                            logger.debug(f"校对分级跳过 [{i}]: 文本过短或匹配跳过模式")
                            continue
                        weak_residue_only = (
                            self._has_weak_japanese_residue(clean_dst)
                            and not self._has_blocking_japanese_residue(clean_dst)
                        )
                        residue_fragments = self._extract_japanese_residue_fragments(clean_dst)
                        with proofread_residue_fragments_lock:
                            repeated_fragments = [
                                fragment for fragment in residue_fragments
                                if proofread_residue_fragments_seen.get(fragment, 0) > 0
                            ]
                            if not repeated_fragments:
                                for fragment in residue_fragments:
                                    proofread_residue_fragments_seen[fragment] = (
                                        proofread_residue_fragments_seen.get(fragment, 0) + 1
                                    )
                        if repeated_fragments:
                            if weak_residue_only:
                                logger.debug(
                                    "弱日文残留仅提示不阻塞，跳过重复校对: "
                                    + " / ".join(repeated_fragments[:5])
                                )
                                continue
                            suspicious_idx.add(i)
                            retranslate_residue_fragments[i] = repeated_fragments
                            logger.info(
                                "重复日文残留转为重译，跳过重复校对: "
                                + " / ".join(repeated_fragments[:5])
                            )
                            continue
                        proofread_issues[i] = issues

            if proofread_issues:
                self._inc_stat("proofread_suspicious", len(proofread_issues))
            if suspicious_idx:
                self._inc_stat("quality_retranslate", len(suspicious_idx))

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
            proofread_skipped = 0
            batch_proofread_revisions: Dict[int, str] = {}
            proofread_only_idx = sorted(set(proofread_issues) - suspicious_idx)
            if enable_proofread and len(proofread_only_idx) >= 2:
                batch_items = []
                for batch_i in proofread_only_idx:
                    task_key, src, draft = repaired[batch_i]
                    proofread_prev, proofread_next = get_context_for_task(task_key)
                    batch_items.append(
                        {
                            "idx": batch_i,
                            "src": src,
                            "draft": draft,
                            "issues": list(proofread_issues[batch_i]),
                            "prev": proofread_prev,
                            "next": proofread_next,
                        }
                    )
                try:
                    batch_proofread_revisions = self._proofread_translations_batch(batch_items)
                    if batch_proofread_revisions is None:
                        # 401 / 403 from proofread API — skip proofread for these
                        # items rather than silently treating draft as revised.
                        proofread_skipped += len(batch_items)
                        batch_proofread_revisions = {}
                        logger.warning(
                            f"批量校对认证失败，跳过 {len(batch_items)} 条校对"
                        )
                    elif batch_proofread_revisions:
                        logger.info(
                            f"批量校对完成: {len(batch_proofread_revisions)}/{len(batch_items)} 条"
                        )
                except Exception as batch_proofread_error:
                    logger.warning(f"批量校对失败，回退单条校对: {batch_proofread_error}")

            for i in sorted(all_repair_idx):
                task_key, src, _ = repaired[i]
                try:
                    if enable_proofread and i in proofread_issues and i not in suspicious_idx:
                        draft = repaired[i][2]
                        issues = list(proofread_issues[i])
                        if getattr(self, "_proofread_auth_failed", False):
                            proofread_skipped += 1
                            continue
                        if i in batch_proofread_revisions:
                            revised = batch_proofread_revisions[i]
                        else:
                            proofread_prev, proofread_next = get_context_for_task(task_key)
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
                        if revised is None:
                            proofread_skipped += 1
                            continue
                        revised = self._postprocess_translation(src, revised)
                        if (
                            any("日文" in issue or "假名" in issue for issue in issues)
                            and self._has_blocking_japanese_residue(revised)
                        ):
                            try:
                                fallback_prev, fallback_next = get_context_for_task(task_key)
                                fallback_revised = call_translate_chunk(
                                    src,
                                    fallback_prev,
                                    fallback_next,
                                    self._extract_japanese_residue_fragments(revised),
                                )
                                if fallback_revised:
                                    revised = self._postprocess_translation(src, fallback_revised)
                                issues.append("校对后仍残留日文，已回退单条重译")
                            except Exception as fallback_error:
                                logger.warning(f"校对后单条重译失败 [{i}]: {fallback_error}")
                        repaired[i] = (task_key, src, revised)
                        remember_residue_repair(draft, revised)
                        if not self._is_context_cache_text(src):
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
                        repair_prev, repair_next = get_context_for_task(task_key)
                        repaired_text = call_translate_chunk(
                            src,
                            repair_prev,
                            repair_next,
                            retranslate_residue_fragments.get(i),
                        )
                        repaired[i] = (
                            task_key,
                            src,
                            self._postprocess_translation(src, repaired_text),
                        )
                    fixed_count += 1
                except Exception as e:
                    logger.warning(f"质检重译失败 [{i}]: {e}")
            if proofread_fixed:
                self._inc_stat("proofread_fixed", proofread_fixed)
            if proofread_skipped:
                logger.info(
                    f"质检修复完成，成功修复 {fixed_count}/{len(all_repair_idx)} 条，"
                    f"因认证失败跳过校对 {proofread_skipped} 条"
                )
            else:
                logger.info(f"质检修复完成，成功修复 {fixed_count}/{len(all_repair_idx)} 条")
            return repaired

        def translate_one_batch(batch: List[str]) -> List[Tuple[str, str, str]]:
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")

            batch_texts = [task_texts[key] for key in batch]

            if len(batch) == 1:
                task_key = batch[0]
                text = batch_texts[0]
                prev_ctx, next_ctx = get_context_for_task(task_key)
                zh = call_translate_chunk(text, prev_ctx, next_ctx)
                return repair_batch_quality(batch, [(task_key, text, zh)])

            self._inc_stat("batch_total")
            # 优先使用结构化 JSON 返回，减少分割符丢失导致的拆分失败。
            item_contexts = (
                [get_context_for_task(task_key) for task_key in batch]
                if use_context_window and self.ENABLE_BATCH_ITEM_CONTEXT
                else None
            )
            batch_prev_ctx, batch_next_ctx = get_context_for_task(batch[0])
            try:
                result = self._call_deepseek_batch_json(
                    batch_texts,
                    prev_text=batch_prev_ctx,
                    next_text=batch_next_ctx,
                    item_contexts=item_contexts,
                )
            except TypeError as exc:
                if "item_contexts" not in str(exc):
                    raise
                result = self._call_deepseek_batch_json(
                    batch_texts,
                    prev_text=batch_prev_ctx,
                    next_text=batch_next_ctx,
                )
            except ContentModerationError as moderation_exc:
                logger.warning(
                    "批量 JSON 被内容审核拦截，拆单条重试: %s",
                    moderation_exc,
                )
                self._inc_stat("batch_moderation_fallback")
                single_parts: List[Optional[str]] = []
                for task_key, text in zip(batch, batch_texts):
                    try:
                        retry_prev, retry_next = get_context_for_task(task_key)
                        single_parts.append(call_translate_chunk(text, retry_prev, retry_next))
                    except Exception as single_exc:
                        logger.warning(
                            "内容审核拦截后的单条重试失败: %s",
                            single_exc,
                        )
                        single_parts.append(None)
                return repair_batch_quality(batch, list(zip(batch, batch_texts, single_parts)))

            # Case 1: 全部成功（所有 idx 都有有效译文）
            if result.translations is not None and not result.missing_indices:
                json_parts = result.translations
                if isinstance(json_parts, list) and len(json_parts) == len(batch):
                    if self.extract_glossary and result.new_terms:
                        cleaned_terms = self._clean_new_terms(result.new_terms)
                        self._merge_new_terms_into_glossary(cleaned_terms)
                    self._inc_stat("batch_json_success")
                    return repair_batch_quality(batch, list(zip(batch, batch_texts, json_parts)))

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
                        retry_prev, retry_next = get_context_for_task(batch[idx])
                        final_parts[idx] = call_translate_chunk(batch_texts[idx], retry_prev, retry_next)
                    except Exception as e:
                        logger.warning(f"单条重试失败 [idx={idx}]: {e}")
                        final_parts[idx] = None  # 保留为未完成，禁止回写原文

                return repair_batch_quality(batch, list(zip(batch, batch_texts, final_parts)))

            # Case 3: 批量 JSON 两次仍全部失败 — 直接逐条单条翻译。
            # 不再走分隔符批量，避免格式/分隔符再次失败导致最后少量文本反复卡住。
            self._inc_stat("batch_fallback")
            logger.info("批量 JSON 多次失败，回退逐条单条翻译: %s 条", len(batch))
            single_parts: List[Optional[str]] = []
            for task_key, text in zip(batch, batch_texts):
                try:
                    retry_prev, retry_next = get_context_for_task(task_key)
                    single_parts.append(call_translate_chunk(text, retry_prev, retry_next))
                except Exception as e:
                    logger.warning(f"批量失败后的单条翻译失败: {e}")
                    single_parts.append(None)
            return repair_batch_quality(batch, list(zip(batch, batch_texts, single_parts)))

        executor = ThreadPoolExecutor(max_workers=max(1, self.max_workers))
        futures: Dict[Any, List[str]] = {}
        future_order = deque()
        batch_queue = deque(batches)

        def pop_next_dynamic_batch() -> List[str]:
            batch = list(batch_queue.popleft())
            dynamic_batch_size = self._current_dynamic_batch_size()
            if len(batch) > dynamic_batch_size:
                head = batch[:dynamic_batch_size]
                tail = batch[dynamic_batch_size:]
                if tail:
                    batch_queue.appendleft(tail)
                return head
            return batch

        def submit_available_batches() -> None:
            current_limit = self._current_dynamic_workers()
            while batch_queue and len(futures) < current_limit:
                if self.cancel_event.is_set():
                    raise RuntimeError("翻译已取消")
                batch = pop_next_dynamic_batch()
                if not batch:
                    continue
                future = executor.submit(translate_one_batch, batch)
                futures[future] = batch
                future_order.append(future)
                current_limit = self._current_dynamic_workers()

        def trim_excess_futures() -> None:
            """Cancel queued futures when dynamic concurrency shrinks."""
            limit = self._current_dynamic_workers()
            if len(futures) <= limit:
                return
            kept = deque()
            cancelled = 0
            while future_order and len(futures) > limit:
                future = future_order.pop()
                if future.done():
                    continue
                if future.cancel():
                    futures.pop(future, None)
                    cancelled += 1
                    continue
                kept.appendleft(future)
            while kept:
                future_order.appendleft(kept.popleft())
            if cancelled:
                logger.info(f"动态并发收缩: 已取消 {cancelled} 个排队任务，当前上限={limit}")

        try:
            submit_available_batches()
            trim_excess_futures()

            # Runtime throttling requires incremental submission instead of queuing all batches at once.
            while futures:
                if self.cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    self._save_cache(force=True)
                    raise RuntimeError("翻译已取消")

                done, _ = wait(set(futures), timeout=0.2, return_when=FIRST_COMPLETED)
                if not done:
                    trim_excess_futures()
                    submit_available_batches()
                    continue

                # Remove completed futures from future_order first so the deque
                # is not resized mid-iteration by worker callbacks. See #71.
                done_set = set(done)
                new_future_order = deque(f for f in future_order if f not in done_set)
                future_order.clear()
                future_order.extend(new_future_order)
                for future in done:
                    batch = futures.pop(future, None)
                    if batch is None:
                        continue
                    try:
                        batch_results = future.result()
                        for task_key, original, translated in batch_results:
                            accepted = accept_translation(original, translated, "批次译文疑似未完成")
                            if accepted is None:
                                continue
                            translated = accepted
                            if self._should_write_cache():
                                with self._cache_lock:
                                    self.cache[task_key] = translated
                            # Phase 1-②: 写入文本级缓存（非短文本才写入）
                            if not self._is_context_cache_text(original):
                                self._save_text_cache_entry(original, translated, verified=False)
                            task = pending_tasks.get(task_key, {})
                            for occurrence_idx in task.get("indices", []):
                                ordered_results[occurrence_idx] = translated
                            results.setdefault(original, translated)
                            completed += pending_counts.get(task_key, 1)
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
                        for task_key in batch:
                            if self.cancel_event.is_set():
                                self._save_cache(force=True)
                                raise RuntimeError("翻译已取消")
                            text = task_texts[task_key]
                            try:
                                fallback_prev, fallback_next = get_context_for_task(task_key)
                                zh = call_translate_chunk(text, fallback_prev, fallback_next)
                                accepted = accept_translation(text, zh, "批次失败后的单条重试仍未完成")
                                if accepted is None:
                                    continue
                                zh = accepted
                                if self._should_write_cache():
                                    with self._cache_lock:
                                        self.cache[task_key] = zh
                                task = pending_tasks.get(task_key, {})
                                for occurrence_idx in task.get("indices", []):
                                    ordered_results[occurrence_idx] = zh
                                results.setdefault(text, zh)
                            except Exception as e2:
                                logger.error(f"翻译失败: {e2}")
                                mark_incomplete(text, f"单条重试失败: {e2}")
                                continue
                            completed += pending_counts.get(task_key, 1)
                            if item_callback:
                                item_callback(text, zh)
                            if progress_callback:
                                progress_callback(completed, total)

                submit_available_batches()
                trim_excess_futures()
        finally:
            executor.shutdown(wait=not self.cancel_event.is_set(), cancel_futures=True)

        self._save_cache(force=True)
        self._flush_text_cache()

        for idx, text in enumerate(texts):
            translated = ordered_results[idx] if idx < len(ordered_results) else None
            cache_key = task_key_for(text, idx)
            if translated is None:
                with self._cache_lock:
                    cached = self.cache.get(cache_key)
                if cached is not None:
                    accepted = accept_translation(text, cached, "最终缓存补全疑似未完成")
                else:
                    accepted = None
                if accepted is not None:
                    ordered_results[idx] = accepted
                    results.setdefault(text, accepted)
                elif cached is not None:
                    with self._cache_lock:
                        self.cache.pop(cache_key, None)
                        self._cache_dirty = True
                continue
            accepted = accept_translation(text, translated, "最终校验发现译文仍未完成")
            if accepted is None:
                ordered_results[idx] = None
            else:
                ordered_results[idx] = accepted
                results.setdefault(text, accepted)

        missing_texts = [text for idx, text in enumerate(texts) if idx >= len(ordered_results) or not ordered_results[idx]]
        for text in missing_texts:
            mark_incomplete(text, "未返回安全译文")

        if failed_texts or residue_texts:
            unique_failed = list(dict.fromkeys(failed_texts.keys()))
            unique_residue = list(dict.fromkeys(residue_texts.keys()))
            if unique_failed:
                self._inc_stat("translation_incomplete", len(unique_failed))
            if unique_residue:
                self._inc_stat("japanese_residue_remaining", len(unique_residue))
            failed_details = [
                {
                    "text": text,
                    "reason": failed_texts.get(text) or "未返回安全译文",
                }
                for text in unique_failed
            ]
            residue_details = []
            for text in unique_residue:
                translated = residue_texts.get(text, "")
                residue_details.append(
                    {
                        "original": text,
                        "translated": translated,
                        "fragments": self._extract_japanese_residue_fragments(translated),
                        "reason": failed_texts.get(text) or "译文疑似仍有日文残留",
                    }
                )
            incomplete_error = TranslationIncompleteError(
                failed_texts=unique_failed,
                residue_texts=unique_residue,
                partial_results=results,
                failed_details=failed_details,
                residue_details=residue_details,
            )
            logger.error(
                "%s\n日文残留白名单路径: %s",
                incomplete_error.format_diagnostics(max_items=5),
                self.japanese_residue_allowlist_path(),
            )
            log_translate_summary("incomplete", planned=planned_batches)
            raise incomplete_error

        if progress_callback and completed < total:
            progress_callback(total, total)

        log_translate_summary("success", planned=planned_batches)
        self._last_ordered_results = ordered_results
        return results

    def __del__(self):
        """析构时保存缓存"""
        try:
            executor = getattr(self, "_async_http_executor", None)
            if executor is not None:
                executor.close()
            self.request_cancel(close_session=True)
            self.flush_cache()
        except Exception:
            pass
