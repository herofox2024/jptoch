# -*- coding: utf-8 -*-
"""
配置桥接器：管理应用配置，提供 QML 可绑定的属性，支持持久化到 JSON 文件。
"""

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import translation_quality as tq
from PySide6.QtCore import QObject, Signal, Property, Slot, QTimer

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
LONGCAT_API_URL = "https://api.longcat.chat/openai/v1/chat/completions"
LONGCAT_MODEL = "LongCat-2.0"
HYMT2_API_URL = "http://127.0.0.1:8080/v1/chat/completions"
HYMT2_MODEL = "Hy-MT2-1.8B-Q4_K_M"

PROVIDER_DEFAULTS = {
    "deepseek": {"url": DEEPSEEK_API_URL, "model": DEEPSEEK_MODEL},
    "doubao":   {"url": DOUBAO_API_URL,   "model": DOUBAO_MODEL},
    "sakura":   {"url": SAKURA_API_URL,   "model": SAKURA_MODEL},
    "gemini":   {"url": GEMINI_API_URL,   "model": GEMINI_MODEL},
    "glm":      {"url": GLM_API_URL,      "model": GLM_MODEL},
    "wenxin":   {"url": WENXIN_API_URL,   "model": WENXIN_MODEL},
    "longcat":  {"url": LONGCAT_API_URL,  "model": LONGCAT_MODEL},
    "hymt2":    {"url": HYMT2_API_URL,    "model": HYMT2_MODEL},
    "custom":   {"url": "", "model": ""},
}

PROVIDER_HINTS = {
    "deepseek": "DeepSeek 官方 API，速度快质量好",
    "doubao":   "火山引擎豆包模型，需自行申请 API Key",
    "sakura":   "本地 Sakura 模型，需自行部署（默认 127.0.0.1:8080）",
    "gemini":   "Google Gemini API，免费额度有限",
    "glm":      "智谱开放平台，免费版限制并发",
    "wenxin":   "百度千帆/文心一言 OpenAI 兼容接口，需使用千帆 API Key",
    "longcat":  "美团 LongCat OpenAI 兼容接口，默认模型 LongCat-2.0",
    "hymt2":    "腾讯 Hy-MT2 本地翻译模型，无需 API Key；可用 Python 本地模式或 llama-server.exe 模式",
    "custom":   "任意 OpenAI 兼容端点，请手动填写 URL 和模型名",
}

PROVIDER_CAPABILITY = {
    "glm": "智谱免费版限制并发 ≤2，batch ≤2",
    "gemini": "Gemini 免费版有限流",
    "wenxin": "文心一言/千帆：建议先低并发低批量测试，旧版 access_token RPC 接口不兼容",
    "longcat": "LongCat：已自动限制并发≤8、batch≤9；遇到内容审核会拆分/降级处理",
    "hymt2": "Hy-MT2 本地：CPU 限制并发=1、batch=1；GPU 默认 4/4，最大并发≤6、batch≤8；适合离线初译或审核备用",
}

PERF_UI_PRESETS = {
    "default": {
        "label": "默认", "hint": "稳定安全，适合所有账户",
        "values": { "max_workers": 5, "batch_size": 4, "max_batch_length": 800, "max_text_size_for_batch": 200, "api_timeout": 120 },
    },
    "balanced": {
        "label": "适中", "hint": "推荐配置，效率与稳定性兼顾",
        "values": { "max_workers": 12, "batch_size": 10, "max_batch_length": 4000, "max_text_size_for_batch": 600, "api_timeout": 120 },
    },
    "extreme": {
        "label": "极端", "hint": "极限速度，高风险",
        "values": { "max_workers": 25, "batch_size": 15, "max_batch_length": 8000, "max_text_size_for_batch": 1000, "api_timeout": 120 },
    },
    "glm_free": {
        "label": "智谱免费版", "hint": "智谱免费版建议低并发、低批量",
        "values": { "max_workers": 1, "batch_size": 2, "max_batch_length": 200, "max_text_size_for_batch": 200, "api_timeout": 300 },
    },
    "gemini_free": {
        "label": "Gemini 免费版", "hint": "Gemini 免费版保守参数",
        "values": { "max_workers": 1, "batch_size": 2, "max_batch_length": 200, "max_text_size_for_batch": 200, "api_timeout": 300 },
    },
    "deepseek_paid": {
        "label": "DeepSeek 付费版", "hint": "较高并发和批量",
        "values": { "max_workers": 12, "batch_size": 10, "max_batch_length": 4000, "max_text_size_for_batch": 1000, "api_timeout": 120 },
    },
    "hymt2_local": {
        "label": "Hy-MT2 CPU", "hint": "CPU 稳定保存优先",
        "values": { "max_workers": 1, "batch_size": 1, "max_batch_length": 300, "max_text_size_for_batch": 120, "api_timeout": 300 },
    },
    "hymt2_gpu": {
        "label": "Hy-MT2 GPU", "hint": "RTX 2070 8GB 等 GPU 推荐起点",
        "values": { "max_workers": 4, "batch_size": 4, "max_batch_length": 1000, "max_text_size_for_batch": 250, "api_timeout": 300 },
    },
}

PROMPT_TEXT_DEFAULT_LITERARY = """请以简体中文输出。保持原作叙事节奏、人物称谓和文学语气；不要添加解释、译者注或括号说明；无法确定的专名先直译并保持前后一致。"""
PROMPT_TEXT_HYMT2_OFFICIAL = """Translate Japanese to Simplified Chinese. Output only the translation. Do not explain. Keep names and dialogue natural."""
PROMPT_TEXT_SAFE_CONSERVATIVE = """请以简体中文输出。遇到敏感、暴力、恐怖或成人语境时，按文学叙事进行克制翻译，不要拒译、不要输出安全说明、不要省略原意。"""
PROMPT_TEXT_FAILED_BLOCK_REPAIR = """请只修复当前失败文本块并输出简体中文译文。不要返回 JSON、编号、解释、原文或额外说明；保留必要专名，翻译所有可翻译的日文假名。"""
PROMPT_TEXT_PROOFREAD_RETRANSLATE = """请以校对模型身份重译失败段落：输出流畅简体中文，修复漏译、日文残留、繁体字、JSON 破损和空返回问题；不要添加译者注。"""

MODEL_PROMPT_PRESETS = [
    {
        "key": "deepseek_fast",
        "label": "DeepSeek 快速",
        "category": "model",
        "source": "builtin",
        "hint": "云端快速预设：适合先跑初译，保留基础残留检查。",
        "values": {
            "provider": "deepseek",
            "api_url": DEEPSEEK_API_URL,
            "model": DEEPSEEK_MODEL,
            "max_workers": 10,
            "batch_size": 8,
            "max_batch_length": 3000,
            "max_text_size_for_batch": 600,
            "api_timeout": 120,
            "enable_proofread": False,
            "enable_prompt_examples": True,
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "deepseek_stable",
        "label": "DeepSeek 稳定文学",
        "category": "workflow",
        "source": "builtin",
        "hint": "主力云端翻译预设：自动风格、启用校对、保守并发，适合正式译书。",
        "values": {
            "provider": "deepseek",
            "api_url": DEEPSEEK_API_URL,
            "model": DEEPSEEK_MODEL,
            "max_workers": 5,
            "batch_size": 4,
            "max_batch_length": 800,
            "max_text_size_for_batch": 200,
            "api_timeout": 120,
            "enable_proofread": True,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
            "prompt_extra_instruction": PROMPT_TEXT_DEFAULT_LITERARY,
            "enable_prompt_examples": True,
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "longcat_stable",
        "label": "LongCat 稳定",
        "category": "model",
        "source": "builtin",
        "hint": "LongCat 安全稳定预设：降低并发批量，减少超时和安全拒绝后的整批损失。",
        "values": {
            "provider": "longcat",
            "api_url": LONGCAT_API_URL,
            "model": LONGCAT_MODEL,
            "max_workers": 4,
            "batch_size": 4,
            "max_batch_length": 1200,
            "max_text_size_for_batch": 260,
            "api_timeout": 300,
            "enable_proofread": True,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
            "enable_prompt_examples": True,
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "longcat_balanced",
        "label": "LongCat 平衡",
        "category": "workflow",
        "source": "builtin",
        "hint": "LongCat 2.0 预设：限制到当前稳定上限，适合速度优先但保留残留检查。",
        "values": {
            "provider": "longcat",
            "api_url": LONGCAT_API_URL,
            "model": LONGCAT_MODEL,
            "max_workers": 8,
            "batch_size": 9,
            "max_batch_length": 4000,
            "max_text_size_for_batch": 600,
            "api_timeout": 300,
            "enable_proofread": True,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
            "prompt_extra_instruction": PROMPT_TEXT_SAFE_CONSERVATIVE,
            "enable_prompt_examples": True,
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "hymt2_cpu_stable",
        "label": "Hy-MT2 CPU 稳定",
        "category": "model",
        "source": "builtin",
        "hint": "本地 CPU 预设：1/1、官方短 Prompt、稳定生成参数，优先保证可保存。",
        "values": {
            "provider": "hymt2",
            "api_key": "sk-local",
            "api_url": HYMT2_API_URL,
            "model": HYMT2_MODEL,
            "max_workers": 1,
            "batch_size": 1,
            "max_batch_length": 300,
            "max_text_size_for_batch": 120,
            "api_timeout": 300,
            "enable_proofread": False,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
            "enable_prompt_examples": False,
            "hymt2_generation_mode": "stable",
            "hymt2_prompt_mode": "official",
            "hymt2_runtime_mode": "cpu",
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "hymt2_gpu_stable",
        "label": "Hy-MT2 GPU 稳定",
        "category": "model",
        "source": "builtin",
        "hint": "本地 CUDA llama-server 预设：4/4、官方短 Prompt；如卡顿或 OOM 再降到 CPU 稳定。",
        "values": {
            "provider": "hymt2",
            "api_key": "sk-local",
            "api_url": HYMT2_API_URL,
            "model": HYMT2_MODEL,
            "max_workers": 4,
            "batch_size": 4,
            "max_batch_length": 1000,
            "max_text_size_for_batch": 250,
            "api_timeout": 300,
            "enable_proofread": False,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
            "enable_prompt_examples": False,
            "hymt2_generation_mode": "stable",
            "hymt2_prompt_mode": "official",
            "hymt2_runtime_mode": "gpu",
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "custom_openai",
        "label": "Custom OpenAI 兼容",
        "category": "model",
        "source": "builtin",
        "hint": "自定义兼容端点模板：只切换到 custom，不写入 URL、模型名或密钥。",
        "values": {
            "provider": "custom",
            "max_workers": 3,
            "batch_size": 3,
            "max_batch_length": 800,
            "max_text_size_for_batch": 200,
            "api_timeout": 300,
            "enable_prompt_examples": True,
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "prompt_literary_default",
        "label": "默认文学 Prompt",
        "category": "prompt",
        "source": "builtin",
        "hint": "强调简体中文、文学语气、不要解释或译者注。",
        "values": {
            "prompt_extra_instruction": PROMPT_TEXT_DEFAULT_LITERARY,
            "enable_prompt_examples": True,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
        },
    },
    {
        "key": "prompt_hymt2_official_short",
        "label": "Hy-MT2 官方短 Prompt",
        "category": "prompt",
        "source": "builtin",
        "hint": "适合 Hy-MT2 本地模型：短指令、少解释、降低跑偏概率。",
        "values": {
            "prompt_extra_instruction": PROMPT_TEXT_HYMT2_OFFICIAL,
            "enable_prompt_examples": False,
            "hymt2_generation_mode": "stable",
            "hymt2_prompt_mode": "official",
        },
    },
    {
        "key": "prompt_safe_conservative",
        "label": "安全保守翻译",
        "category": "prompt",
        "source": "builtin",
        "hint": "用于容易被拒译的恐怖、暴力或成人语境，要求按文学叙事克制翻译。",
        "values": {
            "prompt_extra_instruction": PROMPT_TEXT_SAFE_CONSERVATIVE,
            "enable_prompt_examples": False,
            "japanese_residue_policy": "balanced",
        },
    },
    {
        "key": "prompt_failed_block_repair",
        "label": "失败块修复 Prompt",
        "category": "prompt",
        "source": "builtin",
        "hint": "用于单独重译失败块：禁止解释、编号和 JSON，直接给安全译文。",
        "values": {
            "prompt_extra_instruction": PROMPT_TEXT_FAILED_BLOCK_REPAIR,
            "enable_prompt_examples": False,
            "japanese_residue_policy": "lenient",
        },
    },
    {
        "key": "prompt_proofread_retranslate",
        "label": "校对重译 Prompt",
        "category": "prompt",
        "source": "builtin",
        "hint": "用于备用校对模型重译失败段落，重点修复漏译、残留和空返回。",
        "values": {
            "prompt_extra_instruction": PROMPT_TEXT_PROOFREAD_RETRANSLATE,
            "enable_proofread": True,
            "enable_prompt_examples": False,
            "proofread_genre": "auto",
            "proofread_tone": "auto",
            "japanese_residue_policy": "balanced",
        },
    },
]

MODEL_PROMPT_PRESET_BY_KEY = {item["key"]: item for item in MODEL_PROMPT_PRESETS}

PRESET_CONFIG_KEYS = {
    "provider", "api_url", "model",
    "max_workers", "batch_size", "max_batch_length", "max_text_size_for_batch", "api_timeout",
    "direction", "enable_thinking", "enable_proofread", "proofread_genre", "proofread_tone",
    "proofread_provider", "proofread_api_url", "proofread_model",
    "prompt_extra_instruction", "enable_prompt_examples",
    "enable_layered_glossary", "use_global_glossary", "use_genre_glossary", "use_series_glossary", "use_book_glossary",
    "series_glossary_name", "book_glossary_name", "selected_glossary_profile_ids",
    "hymt2_generation_mode", "hymt2_prompt_mode", "hymt2_runtime_mode",
    "japanese_residue_policy",
}
PRESET_SECRET_KEYS = {"api_key", "proofread_api_key"}
PRESET_CATEGORY_LABELS = {
    "model": "模型",
    "prompt": "Prompt",
    "workflow": "组合",
}

# Keys that are persisted
_CONFIG_KEYS = [
    "inp", "out", "api_key", "provider", "api_url", "model",
    "extract_glossary", "enable_glossary",
    "enable_layered_glossary", "use_global_glossary", "use_genre_glossary", "use_series_glossary", "use_book_glossary",
    "pre_extract_glossary", "series_glossary_name", "book_glossary_name", "selected_glossary_profile_ids",
    "max_workers", "batch_size", "max_batch_length", "max_text_size_for_batch", "api_timeout",
    "direction", "enable_thinking", "enable_proofread", "proofread_genre", "proofread_tone",
    "proofread_provider", "proofread_api_key", "proofread_api_url", "proofread_model",
    "allow_text_cache_reuse", "prompt_extra_instruction", "enable_prompt_examples", "theme",
    "enable_notice_page", "notice_page_text", "hymt2_generation_mode", "hymt2_prompt_mode", "hymt2_runtime_mode",
    "japanese_residue_policy",
]

CONFIG_FILE_NAME = "config.json"
JAPANESE_RESIDUE_ALLOWLIST_FILE_NAME = "japanese_residue_allowlist.json"
MODEL_PROMPT_PRESETS_FILE_NAME = "model_prompt_presets.json"
DEFAULT_NOTICE_PAGE_TEXT = (
    "本书由 AI日译中(EPUB) V4.1 辅助翻译。\n"
    "译文仅供个人学习、研究与阅读辅助使用，请勿传播或用于商业用途。\n"
    "请支持并购买正版书籍。"
)
_RESIDUE_QUOTE_CHARS = "「」『』“”\"'（）()【】[]〈〉《》"


def _data_dir() -> Path:
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _config_path() -> Path:
    return _data_dir() / CONFIG_FILE_NAME


def _japanese_residue_allowlist_path() -> Path:
    return _data_dir() / JAPANESE_RESIDUE_ALLOWLIST_FILE_NAME


def _model_prompt_presets_path() -> Path:
    return _data_dir() / MODEL_PROMPT_PRESETS_FILE_NAME


def _slugify_preset_key(text: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", str(text or "").strip()).strip("_").lower()
    if not slug:
        slug = "preset"
    return slug[:48]


def _clean_preset_values(values: Any) -> Dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    cleaned: Dict[str, Any] = {}
    for key, value in values.items():
        if key in PRESET_SECRET_KEYS or key not in PRESET_CONFIG_KEYS:
            continue
        cleaned[key] = value
    return cleaned


def _normalize_model_prompt_preset(item: Any, fallback_prefix: str = "user") -> Dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    values = _clean_preset_values(item.get("values"))
    if not values:
        return {}
    raw_key = str(item.get("key") or item.get("label") or "").strip()
    key = raw_key if raw_key.startswith("user_") else f"user_{_slugify_preset_key(raw_key)}"
    if key == "user_":
        key = f"user_{fallback_prefix}"
    category = str(item.get("category") or "workflow").strip().lower()
    if category not in PRESET_CATEGORY_LABELS:
        category = "workflow"
    label = str(item.get("label") or key.replace("user_", "")).strip()[:80]
    hint = str(item.get("hint") or "").strip()[:240]
    return {
        "key": key,
        "label": label or key,
        "hint": hint,
        "category": category,
        "source": "user",
        "values": values,
    }


def _load_user_model_prompt_presets() -> List[Dict[str, Any]]:
    path = _model_prompt_presets_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        raw_items = data.get("presets") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            return []
        result: List[Dict[str, Any]] = []
        seen = set()
        for idx, item in enumerate(raw_items):
            preset = _normalize_model_prompt_preset(item, fallback_prefix=f"preset_{idx + 1}")
            key = preset.get("key")
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(preset)
        return result
    except Exception as exc:
        logger.warning("加载模型/Prompt 用户预设失败: %s", exc)
        return []


def _save_user_model_prompt_presets(items: List[Dict[str, Any]]) -> None:
    path = _model_prompt_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = []
    seen = set()
    for idx, item in enumerate(items or []):
        preset = _normalize_model_prompt_preset(item, fallback_prefix=f"preset_{idx + 1}")
        key = preset.get("key")
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(preset)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"version": 1, "presets": cleaned}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _normalize_residue_fragment(fragment: str) -> str:
    text = str(fragment or "").strip()
    return text.strip(_RESIDUE_QUOTE_CHARS).strip()


def _default_residue_allowlist() -> Dict[str, List[str]]:
    return {"quoted": [], "exact": [], "quoted_regex": [], "regex": []}


def _clean_string_list(value: Any) -> List[str]:
    if hasattr(value, "toVariant"):
        try:
            value = value.toVariant()
        except Exception:
            value = []
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _load_residue_allowlist() -> Dict[str, List[str]]:
    path = _japanese_residue_allowlist_path()
    payload = _default_residue_allowlist()
    if not path.exists():
        return payload
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return payload
        for key in payload:
            payload[key] = _clean_string_list(data.get(key))
    except Exception as exc:
        logger.warning("加载日文残留允许列表失败: %s", exc)
    return payload


def _save_residue_allowlist(payload: Dict[str, List[str]]) -> None:
    path = _japanese_residue_allowlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = _default_residue_allowlist()
    for key in cleaned:
        cleaned[key] = _clean_string_list(payload.get(key))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _invalidate_translator_residue_allowlist_cache() -> None:
    try:
        from translator import JaZhTranslator

        JaZhTranslator._japanese_residue_allowlist_cache = None
        JaZhTranslator._japanese_residue_allowlist_mtime = None
        JaZhTranslator._japanese_residue_allowlist_checked_at = 0.0
    except Exception:
        pass
    try:
        import translation_quality as tq

        tq.invalidate_japanese_residue_allowlist_cache()
    except Exception:
        pass


class ConfigBridge(QObject):
    # --- Signals ---
    configChanged = Signal()
    _inpChanged = Signal()
    _outChanged = Signal()
    _apiKeyChanged = Signal()
    _providerChanged = Signal()
    _apiUrlChanged = Signal()
    _modelChanged = Signal()
    _extractGlossaryChanged = Signal()
    _enableGlossaryChanged = Signal()
    _enableLayeredGlossaryChanged = Signal()
    _useGlobalGlossaryChanged = Signal()
    _useGenreGlossaryChanged = Signal()
    _useSeriesGlossaryChanged = Signal()
    _useBookGlossaryChanged = Signal()
    _preExtractGlossaryChanged = Signal()
    _seriesGlossaryNameChanged = Signal()
    _bookGlossaryNameChanged = Signal()
    _selectedGlossaryProfileIdsChanged = Signal()
    _maxWorkersChanged = Signal()
    _batchSizeChanged = Signal()
    _maxBatchLengthChanged = Signal()
    _maxTextSizeForBatchChanged = Signal()
    _apiTimeoutChanged = Signal()
    _directionChanged = Signal()
    _enableThinkingChanged = Signal()
    _enableProofreadChanged = Signal()
    _proofreadGenreChanged = Signal()
    _proofreadToneChanged = Signal()
    _proofreadProviderChanged = Signal()
    _proofreadApiKeyChanged = Signal()
    _proofreadApiUrlChanged = Signal()
    _promptExtraInstructionChanged = Signal()
    _enablePromptExamplesChanged = Signal()
    _enableNoticePageChanged = Signal()
    _noticePageTextChanged = Signal()
    glossaryProfilesChanged = Signal()
    _hymt2GenerationModeChanged = Signal()
    _hymt2PromptModeChanged = Signal()
    _hymt2RuntimeModeChanged = Signal()
    _japaneseResiduePolicyChanged = Signal()
    _themeChanged = Signal()
    japaneseResidueAllowlistChanged = Signal()
    knownKatakanaTermsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inp = ""
        self._out = ""
        self._api_key = ""
        self._provider = "deepseek"
        self._api_url = DEEPSEEK_API_URL
        self._model = DEEPSEEK_MODEL
        self._extract_glossary = False
        self._enable_glossary = True
        self._enable_layered_glossary = False
        self._use_global_glossary = True
        self._use_genre_glossary = False
        self._use_series_glossary = False
        self._use_book_glossary = False
        self._pre_extract_glossary = False
        self._series_glossary_name = ""
        self._book_glossary_name = ""
        self._selected_glossary_profile_ids = []
        self._max_workers = 5
        self._batch_size = 4
        self._max_batch_length = 800
        self._max_text_size_for_batch = 200
        self._api_timeout = 120
        self._direction = "zh"
        self._enable_thinking = False
        self._enable_proofread = True
        self._proofread_genre = "auto"
        self._proofread_tone = "auto"
        self._proofread_provider = ""
        self._proofread_api_key = ""
        self._proofread_api_url = ""
        self._proofread_model = ""   # P3-⑥: 校对专用模型（空=使用主模型）
        self._allow_text_cache_reuse = True
        self._prompt_extra_instruction = ""
        self._enable_prompt_examples = True
        self._enable_notice_page = False
        self._notice_page_text = DEFAULT_NOTICE_PAGE_TEXT
        self._hymt2_generation_mode = "stable"
        self._hymt2_prompt_mode = "official"
        self._hymt2_runtime_mode = "cpu"
        self._japanese_residue_policy = "balanced"
        self._theme = "light"
        self._autosave_enabled = False
        self._load_from_disk()
        self._last_saved_config_text = self._current_config_json()
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self.saveToDisk)
        self._autosave_enabled = True

    def _schedule_save(self):
        """Debounce config writes so QML pages do not need per-control saves."""
        if not getattr(self, "_autosave_enabled", False):
            return
        self.configChanged.emit()
        self._save_timer.start()

    def _emit_changed(self, signal):
        signal.emit()
        self._schedule_save()

    def _load_from_disk(self):
        path = _config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in _CONFIG_KEYS:
                if key in data:
                    setattr(self, f"_{key}", data[key])
            if "allow_text_cache_reuse" not in data:
                self._allow_text_cache_reuse = True
            if "enable_prompt_examples" not in data:
                self._enable_prompt_examples = True
            if "enable_layered_glossary" not in data:
                self._enable_layered_glossary = False
            self._extract_glossary = False
            self._pre_extract_glossary = False
            if "use_global_glossary" not in data:
                self._use_global_glossary = True
            if "use_genre_glossary" not in data:
                self._use_genre_glossary = False
            if "use_series_glossary" not in data:
                self._use_series_glossary = False
            if "use_book_glossary" not in data:
                self._use_book_glossary = False
            if "series_glossary_name" not in data:
                self._series_glossary_name = ""
            if "book_glossary_name" not in data:
                self._book_glossary_name = ""
            self._selected_glossary_profile_ids = _clean_string_list(getattr(self, "_selected_glossary_profile_ids", []))
            if "enable_notice_page" not in data:
                self._enable_notice_page = False
            if not str(getattr(self, "_notice_page_text", "") or "").strip():
                self._notice_page_text = DEFAULT_NOTICE_PAGE_TEXT
            if getattr(self, "_hymt2_generation_mode", "") not in {"stable", "official"}:
                self._hymt2_generation_mode = "stable"
            if getattr(self, "_hymt2_prompt_mode", "") not in {"official", "project"}:
                self._hymt2_prompt_mode = "official"
            if getattr(self, "_hymt2_runtime_mode", "") not in {"cpu", "gpu"}:
                self._hymt2_runtime_mode = "cpu"
            if getattr(self, "_japanese_residue_policy", "") not in {"strict", "balanced", "lenient"}:
                self._japanese_residue_policy = "balanced"
            logger.info(f"配置已加载: {path}")
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")

    @Slot()
    def saveToDisk(self):
        """持久化当前配置到 JSON 文件。"""
        path = _config_path()
        config_text = self._current_config_json()
        if path.exists() and config_text == getattr(self, "_last_saved_config_text", ""):
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(config_text, encoding="utf-8")
            self._last_saved_config_text = config_text
            logger.info(f"配置已保存: {path}")
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")

    def _current_config_json(self) -> str:
        data = {}
        for key in _CONFIG_KEYS:
            val = getattr(self, f"_{key}", None)
            if val is not None:
                data[key] = val
        return json.dumps(data, indent=2, ensure_ascii=False)

    @Slot(str, result="QVariantMap")
    def getProviderDefaults(self, provider: str):
        info = PROVIDER_DEFAULTS.get(provider, {})
        return {"url": info.get("url", ""), "model": info.get("model", "")}

    @Slot(str, result=str)
    def getProviderHint(self, provider: str) -> str:
        return PROVIDER_HINTS.get(provider, "")

    @Slot(str, result=str)
    def getProviderCapability(self, provider: str) -> str:
        return PROVIDER_CAPABILITY.get(provider, "")

    @Slot(str, result="QVariantMap")
    def getPerfPreset(self, key: str):
        preset = PERF_UI_PRESETS.get(key, {})
        return preset.get("values", {})

    def _apply_config_values(self, values: Dict[str, Any]) -> bool:
        signal_by_key = {
            "api_key": self._apiKeyChanged,
            "provider": self._providerChanged,
            "api_url": self._apiUrlChanged,
            "model": self._modelChanged,
            "max_workers": self._maxWorkersChanged,
            "batch_size": self._batchSizeChanged,
            "max_batch_length": self._maxBatchLengthChanged,
            "max_text_size_for_batch": self._maxTextSizeForBatchChanged,
            "api_timeout": self._apiTimeoutChanged,
            "enable_proofread": self._enableProofreadChanged,
            "proofread_genre": self._proofreadGenreChanged,
            "proofread_tone": self._proofreadToneChanged,
            "proofread_provider": self._proofreadProviderChanged,
            "proofread_api_url": self._proofreadApiUrlChanged,
            "proofread_model": self._proofreadModelChanged,
            "prompt_extra_instruction": self._promptExtraInstructionChanged,
            "enable_prompt_examples": self._enablePromptExamplesChanged,
            "enable_layered_glossary": self._enableLayeredGlossaryChanged,
            "use_global_glossary": self._useGlobalGlossaryChanged,
            "use_genre_glossary": self._useGenreGlossaryChanged,
            "use_series_glossary": self._useSeriesGlossaryChanged,
            "use_book_glossary": self._useBookGlossaryChanged,
            "pre_extract_glossary": self._preExtractGlossaryChanged,
            "series_glossary_name": self._seriesGlossaryNameChanged,
            "book_glossary_name": self._bookGlossaryNameChanged,
            "selected_glossary_profile_ids": self._selectedGlossaryProfileIdsChanged,
            "hymt2_generation_mode": self._hymt2GenerationModeChanged,
            "hymt2_prompt_mode": self._hymt2PromptModeChanged,
            "hymt2_runtime_mode": self._hymt2RuntimeModeChanged,
            "japanese_residue_policy": self._japaneseResiduePolicyChanged,
        }
        changed = False
        for key, value in dict(values or {}).items():
            if key == "selected_glossary_profile_ids":
                value = _clean_string_list(value)
            attr = f"_{key}"
            if not hasattr(self, attr):
                continue
            if getattr(self, attr) == value:
                continue
            setattr(self, attr, value)
            signal = signal_by_key.get(key)
            if signal:
                signal.emit()
            changed = True
        if changed:
            self._schedule_save()
        return changed

    @Slot(result="QVariantList")
    def getModelPromptPresets(self):
        items = list(MODEL_PROMPT_PRESETS) + _load_user_model_prompt_presets()
        return [
            {
                "key": item.get("key", ""),
                "label": item.get("label", ""),
                "hint": item.get("hint", ""),
                "category": item.get("category", "workflow"),
                "categoryLabel": PRESET_CATEGORY_LABELS.get(item.get("category", "workflow"), "组合"),
                "source": item.get("source", "builtin"),
                "user": item.get("source") == "user",
            }
            for item in items
        ]

    def _find_model_prompt_preset(self, key: str) -> Dict[str, Any]:
        key = str(key or "").strip()
        if key in MODEL_PROMPT_PRESET_BY_KEY:
            return MODEL_PROMPT_PRESET_BY_KEY[key]
        for item in _load_user_model_prompt_presets():
            if item.get("key") == key:
                return item
        return {}

    def _current_model_prompt_preset_values(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        for key in PRESET_CONFIG_KEYS:
            attr = f"_{key}"
            if hasattr(self, attr):
                values[key] = getattr(self, attr)
        return _clean_preset_values(values)

    @Slot(str, result="QVariantMap")
    def applyModelPromptPreset(self, key: str):
        preset = self._find_model_prompt_preset(key)
        if not preset:
            return {"ok": False, "message": "未知模型/Prompt 预设"}
        values = dict(preset.get("values") or {})
        provider = str(values.get("provider") or "").strip().lower()
        if provider in {"hymt2", "sakura"}:
            values["api_key"] = "sk-local"
        self._apply_config_values(values)
        return {
            "ok": True,
            "message": f"已应用预设: {preset.get('label', key)}",
            "provider": values.get("provider", self._provider),
            "model": values.get("model", self._model),
        }

    @Property(str, constant=True)
    def modelPromptPresetsPath(self) -> str:
        return str(_model_prompt_presets_path())

    @Slot(result="QVariantMap")
    def getCurrentModelPromptPresetSnapshot(self):
        values = self._current_model_prompt_preset_values()
        return {
            "provider": values.get("provider", self._provider),
            "model": values.get("model", self._model),
            "category": "workflow",
            "values": values,
            "secretsExcluded": True,
        }

    @Slot(str, str, result="QVariantMap")
    def saveCurrentModelPromptPreset(self, label: str, hint: str = ""):
        label = str(label or "").strip()
        if not label:
            label = f"{self._provider or 'custom'} 当前配置"
        base_key = f"user_{_slugify_preset_key(label)}"
        items = _load_user_model_prompt_presets()
        existing = {item.get("key") for item in items}
        key = base_key
        suffix = 2
        while key in existing or key in MODEL_PROMPT_PRESET_BY_KEY:
            key = f"{base_key}_{suffix}"
            suffix += 1
        preset = {
            "key": key,
            "label": label[:80],
            "hint": str(hint or "由当前 API、模型、性能、Prompt、校对和残留策略生成。").strip()[:240],
            "category": "workflow",
            "source": "user",
            "values": self._current_model_prompt_preset_values(),
        }
        items.append(preset)
        _save_user_model_prompt_presets(items)
        logger.info("已保存模型/Prompt 用户预设: %s", key)
        return {"ok": True, "message": f"已保存预设: {preset['label']}", "key": key}

    @Slot(str, result="QVariantMap")
    def deleteUserModelPromptPreset(self, key: str):
        key = str(key or "").strip()
        if not key.startswith("user_"):
            return {"ok": False, "message": "只能删除自定义预设，内置预设不能删除"}
        items = _load_user_model_prompt_presets()
        kept = [item for item in items if item.get("key") != key]
        if len(kept) == len(items):
            return {"ok": False, "message": "未找到要删除的自定义预设"}
        _save_user_model_prompt_presets(kept)
        logger.info("已删除模型/Prompt 用户预设: %s", key)
        return {"ok": True, "message": "已删除自定义预设", "key": key}

    def _write_preset_export(self, path: str, presets: List[Dict[str, Any]]) -> Dict[str, Any]:
        raw_path = str(path or "").strip()
        if not raw_path:
            return {"ok": False, "message": "请选择导出路径"}
        target = Path(raw_path)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        safe_presets = []
        for idx, item in enumerate(presets or []):
            preset = _normalize_model_prompt_preset(item, fallback_prefix=f"export_{idx + 1}")
            if preset:
                safe_presets.append(preset)
        payload = {
            "version": 1,
            "type": "qml_v4_model_prompt_presets",
            "secrets_excluded": True,
            "presets": safe_presets,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "message": f"已导出 {len(safe_presets)} 个预设: {target}", "path": str(target)}

    @Slot(str, result="QVariantMap")
    def exportModelPromptPresets(self, path: str):
        return self._write_preset_export(path, _load_user_model_prompt_presets())

    @Slot(str, str, result="QVariantMap")
    def exportCurrentModelPromptPreset(self, path: str, label: str = ""):
        label = str(label or "").strip() or f"{self._provider or 'custom'} 当前配置"
        preset = {
            "key": f"user_{_slugify_preset_key(label)}",
            "label": label[:80],
            "hint": "由当前配置导出。API Key 已排除。",
            "category": "workflow",
            "source": "user",
            "values": self._current_model_prompt_preset_values(),
        }
        return self._write_preset_export(path, [preset])

    @Slot(str, result="QVariantMap")
    def importModelPromptPresets(self, path: str):
        source = Path(str(path or "").strip())
        if not source.exists():
            return {"ok": False, "message": "预设文件不存在"}
        try:
            data = json.loads(source.read_text(encoding="utf-8-sig"))
            raw_items = data.get("presets") if isinstance(data, dict) else data
            if isinstance(raw_items, dict):
                raw_items = [raw_items]
            if not isinstance(raw_items, list):
                return {"ok": False, "message": "预设文件格式不正确"}
            current = _load_user_model_prompt_presets()
            by_key = {item.get("key"): item for item in current if item.get("key")}
            imported = 0
            for idx, item in enumerate(raw_items):
                preset = _normalize_model_prompt_preset(item, fallback_prefix=f"import_{idx + 1}")
                key = preset.get("key")
                if not key:
                    continue
                if key in MODEL_PROMPT_PRESET_BY_KEY:
                    key = f"user_{key}"
                    preset["key"] = key
                base_key = key
                suffix = 2
                while key in MODEL_PROMPT_PRESET_BY_KEY:
                    key = f"{base_key}_{suffix}"
                    suffix += 1
                preset["key"] = key
                by_key[key] = preset
                imported += 1
            _save_user_model_prompt_presets(list(by_key.values()))
            logger.info("已导入模型/Prompt 用户预设: %s 个, 来源: %s", imported, source)
            return {"ok": True, "message": f"已导入 {imported} 个预设，API Key 已自动排除", "count": imported}
        except Exception as exc:
            logger.warning("导入模型/Prompt 预设失败: %s", exc)
            return {"ok": False, "message": f"导入预设失败: {exc}"}

    @Property(str, constant=True)
    def glossaryProfilesPath(self) -> str:
        from glossary_profiles import glossary_profiles_dir

        return str(glossary_profiles_dir(_data_dir()))

    @Slot(result="QVariantList")
    @Slot(str, result="QVariantList")
    def listGlossaryProfiles(self, scope: str = ""):
        try:
            from glossary_profiles import list_profiles

            scope_filter = str(scope or "").strip().lower()
            profiles = list_profiles(_data_dir())
            if scope_filter:
                profiles = [item for item in profiles if item.get("scope") == scope_filter]
            return [
                {
                    "id": item.get("id", ""),
                    "profileId": item.get("id", ""),
                    "name": item.get("name", ""),
                    "scope": item.get("scope", ""),
                    "description": item.get("description", ""),
                    "sourceBook": item.get("source_book", ""),
                    "termCount": int(item.get("term_count") or 0),
                    "createdAt": int(item.get("created_at") or 0),
                    "updatedAt": int(item.get("updated_at") or 0),
                }
                for item in profiles
            ]
        except Exception as exc:
            logger.warning("读取术语 profile 失败: %s", exc)
            return []

    @Slot()
    def notifyGlossaryProfilesChanged(self):
        self.glossaryProfilesChanged.emit()

    @Slot(str, result="QVariantMap")
    def deleteGlossaryProfile(self, profile_id: str):
        try:
            from glossary_profiles import delete_profile

            ok = delete_profile(_data_dir(), profile_id)
            if ok:
                self.glossaryProfilesChanged.emit()
            return {"ok": bool(ok), "message": "已删除术语 profile" if ok else "未找到术语 profile"}
        except Exception as exc:
            logger.warning("删除术语 profile 失败: %s", exc)
            return {"ok": False, "message": f"删除失败: {exc}"}

    @Slot(str, str, str, result="QVariantMap")
    def saveCurrentGlossaryAsProfile(self, scope: str, name: str, source_book: str = ""):
        try:
            from glossary_profiles import upsert_profile
            from glossary_store import normalize_glossary_payload
            from translation_cache import load_json_file

            glossary, _ = normalize_glossary_payload(load_json_file(_data_dir() / "glossary.json", {}))
            has_terms = any(
                isinstance(entries, list) and bool(entries)
                for entries in (glossary or {}).values()
            )
            if not has_terms:
                return {"ok": False, "message": "当前全局术语表为空，无法保存 profile"}
            profile = upsert_profile(
                _data_dir(),
                name=str(name or "").strip(),
                scope=str(scope or "book").strip().lower(),
                terms=glossary,
                description="由当前全局术语表生成",
                source_book=str(source_book or "").strip(),
            )
            self.glossaryProfilesChanged.emit()
            return {
                "ok": True,
                "message": f"已保存术语 profile: {profile.get('name', '')}",
                "id": profile.get("id", ""),
                "termCount": int(profile.get("term_count") or 0),
            }
        except Exception as exc:
            logger.warning("保存术语 profile 失败: %s", exc)
            return {"ok": False, "message": f"保存失败: {exc}"}

    @Slot(result=str)
    def buildPromptPreview(self) -> str:
        try:
            project_root = Path(__file__).resolve().parents[3]
            if str(project_root) not in sys.path:
                sys.path.insert(0, str(project_root))
            from translator import JaZhTranslator

            genre = self._proofread_genre if self._proofread_genre != "auto" else "general"
            tone = self._proofread_tone if self._proofread_tone != "auto" else "neutral"
            translator = JaZhTranslator(
                api_key="preview",
                provider=self._provider if self._provider != "custom" else "deepseek",
                api_url=self._api_url or None,
                model=self._model or None,
                enable_glossary=False,
                cache_path=str(_data_dir() / ".prompt_preview_cache.json"),
                enable_proofread=self._enable_proofread,
                proofread_genre=genre,
                proofread_tone=tone,
                prompt_extra_instruction=self._prompt_extra_instruction,
                enable_prompt_examples=self._enable_prompt_examples,
                hymt2_generation_mode=self._hymt2_generation_mode,
                hymt2_prompt_mode=self._hymt2_prompt_mode,
            )
            return translator.build_prompt_preview()
        except Exception as exc:
            logger.warning("生成 Prompt 预览失败: %s", exc)
            return f"生成 Prompt 预览失败: {exc}"

    @Property(str, constant=True)
    def japaneseResidueAllowlistPath(self) -> str:
        return str(_japanese_residue_allowlist_path())

    @Property(str, constant=True)
    def knownKatakanaTermsPath(self) -> str:
        return tq.known_katakana_terms_path()

    @Slot(result="QVariantMap")
    def getJapaneseResidueAllowlist(self):
        payload = _load_residue_allowlist()
        return {
            "path": str(_japanese_residue_allowlist_path()),
            "quoted": payload.get("quoted", []),
            "exact": payload.get("exact", []),
            "quotedRegex": payload.get("quoted_regex", []),
            "regex": payload.get("regex", []),
        }

    @Slot(str, result="QVariantMap")
    def addJapaneseResidueAllowQuoted(self, fragment: str):
        value = _normalize_residue_fragment(fragment)
        if not value:
            return {"ok": False, "message": "请输入需要放行的片段"}
        payload = _load_residue_allowlist()
        quoted = payload.setdefault("quoted", [])
        if value not in quoted:
            quoted.append(value)
            _save_residue_allowlist(payload)
            _invalidate_translator_residue_allowlist_cache()
            self.japaneseResidueAllowlistChanged.emit()
            logger.info("已加入日文残留允许列表: %s", value)
            return {"ok": True, "message": f"已加入白名单: {value}"}
        return {"ok": True, "message": f"白名单已存在: {value}"}

    @Slot(str, result="QVariantMap")
    def removeJapaneseResidueAllowQuoted(self, fragment: str):
        value = _normalize_residue_fragment(fragment)
        if not value:
            return {"ok": False, "message": "请选择要删除的片段"}
        payload = _load_residue_allowlist()
        quoted = payload.setdefault("quoted", [])
        if value in quoted:
            payload["quoted"] = [item for item in quoted if item != value]
            _save_residue_allowlist(payload)
            _invalidate_translator_residue_allowlist_cache()
            self.japaneseResidueAllowlistChanged.emit()
            logger.info("已移除日文残留允许列表: %s", value)
            return {"ok": True, "message": f"已删除: {value}"}
        return {"ok": False, "message": f"白名单不存在: {value}"}

    @Slot(result="QVariantMap")
    def getKnownKatakanaTerms(self):
        user_terms = tq.load_user_known_katakana_terms()
        merged = tq.load_known_katakana_terms()
        items = []
        for source in sorted(merged):
            items.append({
                "source": source,
                "target": merged[source],
                "builtin": source in tq.DEFAULT_KNOWN_KATAKANA_TERMS and source not in user_terms,
            })
        return {
            "path": tq.known_katakana_terms_path(),
            "items": items,
        }

    @Slot(str, str, result="QVariantMap")
    def addKnownKatakanaTerm(self, source: str, target: str):
        source_text = str(source or "").strip()
        target_text = str(target or "").strip()
        if not source_text:
            return {"ok": False, "message": "请输入需要修复的片假名原词"}
        if not target_text:
            return {"ok": False, "message": "请输入对应中文译名"}
        if not tq.JAPANESE_KANA_RE.search(source_text):
            return {"ok": False, "message": "原词需要包含日文假名"}
        user_terms = tq.load_user_known_katakana_terms()
        user_terms[source_text] = target_text
        tq.save_known_katakana_terms(user_terms)
        self.knownKatakanaTermsChanged.emit()
        logger.info("已保存片假名术语修复词: %s -> %s", source_text, target_text)
        return {"ok": True, "message": f"已保存修复词: {source_text} -> {target_text}"}

    @Slot(str, result="QVariantMap")
    def removeKnownKatakanaTerm(self, source: str):
        source_text = str(source or "").strip()
        if not source_text:
            return {"ok": False, "message": "请选择要删除的修复词"}
        user_terms = tq.load_user_known_katakana_terms()
        if source_text not in user_terms:
            if source_text in tq.DEFAULT_KNOWN_KATAKANA_TERMS:
                return {"ok": False, "message": "内置修复词不能删除，只能添加同名词条覆盖"}
            return {"ok": False, "message": f"修复词不存在: {source_text}"}
        user_terms.pop(source_text, None)
        tq.save_known_katakana_terms(user_terms)
        self.knownKatakanaTermsChanged.emit()
        logger.info("已删除片假名术语修复词: %s", source_text)
        return {"ok": True, "message": f"已删除修复词: {source_text}"}

    @Slot(str)
    def setProvider(self, provider: str):
        if provider == self._provider:
            return
        self._provider = provider
        defaults = PROVIDER_DEFAULTS.get(provider, {})
        self._api_url = defaults.get("url", "")
        self._model = defaults.get("model", "")
        self._providerChanged.emit()
        self._apiUrlChanged.emit()
        self._modelChanged.emit()
        self._schedule_save()

    # --- Properties ---
    @Property(str, notify=_inpChanged)
    def inp(self) -> str: return self._inp
    @inp.setter
    def inp(self, val: str):
        if val != self._inp:
            self._inp = val; self._emit_changed(self._inpChanged)

    @Property(str, notify=_outChanged)
    def out(self) -> str: return self._out
    @out.setter
    def out(self, val: str):
        if val != self._out:
            self._out = val; self._emit_changed(self._outChanged)

    @Property(str, notify=_apiKeyChanged)
    def apiKey(self) -> str: return self._api_key
    @apiKey.setter
    def apiKey(self, val: str):
        if val != self._api_key:
            self._api_key = val; self._emit_changed(self._apiKeyChanged)

    @Property(str, notify=_providerChanged)
    def provider(self) -> str: return self._provider

    @Property(str, notify=_apiUrlChanged)
    def apiUrl(self) -> str: return self._api_url
    @apiUrl.setter
    def apiUrl(self, val: str):
        if val != self._api_url:
            self._api_url = val; self._emit_changed(self._apiUrlChanged)

    @Property(str, notify=_modelChanged)
    def model(self) -> str: return self._model
    @model.setter
    def model(self, val: str):
        if val != self._model:
            self._model = val; self._emit_changed(self._modelChanged)

    @Property(bool, notify=_extractGlossaryChanged)
    def extractGlossary(self) -> bool: return self._extract_glossary
    @extractGlossary.setter
    def extractGlossary(self, val: bool):
        if val != self._extract_glossary:
            self._extract_glossary = val; self._emit_changed(self._extractGlossaryChanged)

    @Property(bool, notify=_enableGlossaryChanged)
    def enableGlossary(self) -> bool: return self._enable_glossary
    @enableGlossary.setter
    def enableGlossary(self, val: bool):
        if val != self._enable_glossary:
            self._enable_glossary = val; self._emit_changed(self._enableGlossaryChanged)

    @Property(bool, notify=_enableLayeredGlossaryChanged)
    def enableLayeredGlossary(self) -> bool: return self._enable_layered_glossary
    @enableLayeredGlossary.setter
    def enableLayeredGlossary(self, val: bool):
        val = bool(val)
        if val != self._enable_layered_glossary:
            self._enable_layered_glossary = val; self._emit_changed(self._enableLayeredGlossaryChanged)

    @Property(bool, notify=_useGlobalGlossaryChanged)
    def useGlobalGlossary(self) -> bool: return self._use_global_glossary
    @useGlobalGlossary.setter
    def useGlobalGlossary(self, val: bool):
        val = bool(val)
        if val != self._use_global_glossary:
            self._use_global_glossary = val; self._emit_changed(self._useGlobalGlossaryChanged)

    @Property(bool, notify=_useGenreGlossaryChanged)
    def useGenreGlossary(self) -> bool: return self._use_genre_glossary
    @useGenreGlossary.setter
    def useGenreGlossary(self, val: bool):
        val = bool(val)
        if val != self._use_genre_glossary:
            self._use_genre_glossary = val; self._emit_changed(self._useGenreGlossaryChanged)

    @Property(bool, notify=_useSeriesGlossaryChanged)
    def useSeriesGlossary(self) -> bool: return self._use_series_glossary
    @useSeriesGlossary.setter
    def useSeriesGlossary(self, val: bool):
        val = bool(val)
        if val != self._use_series_glossary:
            self._use_series_glossary = val; self._emit_changed(self._useSeriesGlossaryChanged)

    @Property(bool, notify=_useBookGlossaryChanged)
    def useBookGlossary(self) -> bool: return self._use_book_glossary
    @useBookGlossary.setter
    def useBookGlossary(self, val: bool):
        val = bool(val)
        if val != self._use_book_glossary:
            self._use_book_glossary = val; self._emit_changed(self._useBookGlossaryChanged)

    @Property(bool, notify=_preExtractGlossaryChanged)
    def preExtractGlossary(self) -> bool: return self._pre_extract_glossary
    @preExtractGlossary.setter
    def preExtractGlossary(self, val: bool):
        val = bool(val)
        if val != self._pre_extract_glossary:
            self._pre_extract_glossary = val; self._emit_changed(self._preExtractGlossaryChanged)

    @Property(str, notify=_seriesGlossaryNameChanged)
    def seriesGlossaryName(self) -> str: return self._series_glossary_name
    @seriesGlossaryName.setter
    def seriesGlossaryName(self, val: str):
        val = str(val or "")
        if val != self._series_glossary_name:
            self._series_glossary_name = val; self._emit_changed(self._seriesGlossaryNameChanged)

    @Property(str, notify=_bookGlossaryNameChanged)
    def bookGlossaryName(self) -> str: return self._book_glossary_name
    @bookGlossaryName.setter
    def bookGlossaryName(self, val: str):
        val = str(val or "")
        if val != self._book_glossary_name:
            self._book_glossary_name = val; self._emit_changed(self._bookGlossaryNameChanged)

    @Property("QVariantList", notify=_selectedGlossaryProfileIdsChanged)
    def selectedGlossaryProfileIds(self):
        return list(self._selected_glossary_profile_ids or [])
    @selectedGlossaryProfileIds.setter
    def selectedGlossaryProfileIds(self, val):
        cleaned = _clean_string_list(val)
        if cleaned != self._selected_glossary_profile_ids:
            self._selected_glossary_profile_ids = cleaned
            self._emit_changed(self._selectedGlossaryProfileIdsChanged)

    @Property(int, notify=_maxWorkersChanged)
    def maxWorkers(self) -> int: return self._max_workers
    @maxWorkers.setter
    def maxWorkers(self, val: int):
        if val != self._max_workers:
            self._max_workers = val; self._emit_changed(self._maxWorkersChanged)

    @Property(int, notify=_batchSizeChanged)
    def batchSize(self) -> int: return self._batch_size
    @batchSize.setter
    def batchSize(self, val: int):
        if val != self._batch_size:
            self._batch_size = val; self._emit_changed(self._batchSizeChanged)

    @Property(int, notify=_maxBatchLengthChanged)
    def maxBatchLength(self) -> int: return self._max_batch_length
    @maxBatchLength.setter
    def maxBatchLength(self, val: int):
        if val != self._max_batch_length:
            self._max_batch_length = val; self._emit_changed(self._maxBatchLengthChanged)

    @Property(int, notify=_maxTextSizeForBatchChanged)
    def maxTextSizeForBatch(self) -> int: return self._max_text_size_for_batch
    @maxTextSizeForBatch.setter
    def maxTextSizeForBatch(self, val: int):
        if val != self._max_text_size_for_batch:
            self._max_text_size_for_batch = val; self._emit_changed(self._maxTextSizeForBatchChanged)

    @Property(int, notify=_apiTimeoutChanged)
    def apiTimeout(self) -> int: return self._api_timeout
    @apiTimeout.setter
    def apiTimeout(self, val: int):
        if val != self._api_timeout:
            self._api_timeout = val; self._emit_changed(self._apiTimeoutChanged)

    @Property(str, notify=_directionChanged)
    def direction(self) -> str: return self._direction
    @direction.setter
    def direction(self, val: str):
        if val != self._direction:
            self._direction = val; self._emit_changed(self._directionChanged)

    @Property(bool, notify=_enableThinkingChanged)
    def enableThinking(self) -> bool: return self._enable_thinking
    @enableThinking.setter
    def enableThinking(self, val: bool):
        if val != self._enable_thinking:
            self._enable_thinking = val; self._emit_changed(self._enableThinkingChanged)

    @Property(bool, notify=_enableProofreadChanged)
    def enableProofread(self) -> bool: return self._enable_proofread
    @enableProofread.setter
    def enableProofread(self, val: bool):
        if val != self._enable_proofread:
            self._enable_proofread = val; self._emit_changed(self._enableProofreadChanged)

    @Property(str, notify=_proofreadGenreChanged)
    def proofreadGenre(self) -> str: return self._proofread_genre
    @proofreadGenre.setter
    def proofreadGenre(self, val: str):
        if val != self._proofread_genre:
            self._proofread_genre = val; self._emit_changed(self._proofreadGenreChanged)

    @Property(str, notify=_proofreadToneChanged)
    def proofreadTone(self) -> str: return self._proofread_tone
    @proofreadTone.setter
    def proofreadTone(self, val: str):
        if val != self._proofread_tone:
            self._proofread_tone = val; self._emit_changed(self._proofreadToneChanged)

    @Property(str, notify=_proofreadProviderChanged)
    def proofreadProvider(self) -> str: return self._proofread_provider
    @proofreadProvider.setter
    def proofreadProvider(self, val: str):
        if val != self._proofread_provider:
            self._proofread_provider = val; self._emit_changed(self._proofreadProviderChanged)

    @Property(str, notify=_proofreadApiKeyChanged)
    def proofreadApiKey(self) -> str: return self._proofread_api_key
    @proofreadApiKey.setter
    def proofreadApiKey(self, val: str):
        if val != self._proofread_api_key:
            self._proofread_api_key = val; self._emit_changed(self._proofreadApiKeyChanged)

    @Property(str, notify=_proofreadApiUrlChanged)
    def proofreadApiUrl(self) -> str: return self._proofread_api_url
    @proofreadApiUrl.setter
    def proofreadApiUrl(self, val: str):
        if val != self._proofread_api_url:
            self._proofread_api_url = val; self._emit_changed(self._proofreadApiUrlChanged)

    _proofreadModelChanged = Signal()
    @Property(str, notify=_proofreadModelChanged)
    def proofreadModel(self) -> str: return self._proofread_model
    @proofreadModel.setter
    def proofreadModel(self, val: str):
        if val != self._proofread_model:
            self._proofread_model = val; self._emit_changed(self._proofreadModelChanged)

    _allowTextCacheReuseChanged = Signal()
    @Property(bool, notify=_allowTextCacheReuseChanged)
    def allowTextCacheReuse(self) -> bool: return self._allow_text_cache_reuse
    @allowTextCacheReuse.setter
    def allowTextCacheReuse(self, val: bool):
        if val != self._allow_text_cache_reuse:
            self._allow_text_cache_reuse = val; self._emit_changed(self._allowTextCacheReuseChanged)

    @Property(str, notify=_promptExtraInstructionChanged)
    def promptExtraInstruction(self) -> str: return self._prompt_extra_instruction
    @promptExtraInstruction.setter
    def promptExtraInstruction(self, val: str):
        val = str(val or "")
        if val != self._prompt_extra_instruction:
            self._prompt_extra_instruction = val; self._emit_changed(self._promptExtraInstructionChanged)

    @Property(bool, notify=_enablePromptExamplesChanged)
    def enablePromptExamples(self) -> bool: return self._enable_prompt_examples
    @enablePromptExamples.setter
    def enablePromptExamples(self, val: bool):
        val = bool(val)
        if val != self._enable_prompt_examples:
            self._enable_prompt_examples = val; self._emit_changed(self._enablePromptExamplesChanged)

    @Property(bool, notify=_enableNoticePageChanged)
    def enableNoticePage(self) -> bool: return self._enable_notice_page
    @enableNoticePage.setter
    def enableNoticePage(self, val: bool):
        val = bool(val)
        if val != self._enable_notice_page:
            self._enable_notice_page = val; self._emit_changed(self._enableNoticePageChanged)

    @Property(str, notify=_noticePageTextChanged)
    def noticePageText(self) -> str: return self._notice_page_text
    @noticePageText.setter
    def noticePageText(self, val: str):
        val = str(val or "")
        if val != self._notice_page_text:
            self._notice_page_text = val; self._emit_changed(self._noticePageTextChanged)

    @Property(str, notify=_hymt2GenerationModeChanged)
    def hymt2GenerationMode(self) -> str: return self._hymt2_generation_mode
    @hymt2GenerationMode.setter
    def hymt2GenerationMode(self, val: str):
        val = str(val or "stable").strip().lower()
        if val not in {"stable", "official"}:
            val = "stable"
        if val != self._hymt2_generation_mode:
            self._hymt2_generation_mode = val; self._emit_changed(self._hymt2GenerationModeChanged)

    @Property(str, notify=_hymt2PromptModeChanged)
    def hymt2PromptMode(self) -> str: return self._hymt2_prompt_mode
    @hymt2PromptMode.setter
    def hymt2PromptMode(self, val: str):
        val = str(val or "official").strip().lower()
        if val not in {"official", "project"}:
            val = "official"
        if val != self._hymt2_prompt_mode:
            self._hymt2_prompt_mode = val; self._emit_changed(self._hymt2PromptModeChanged)

    @Property(str, notify=_hymt2RuntimeModeChanged)
    def hymt2RuntimeMode(self) -> str: return self._hymt2_runtime_mode
    @hymt2RuntimeMode.setter
    def hymt2RuntimeMode(self, val: str):
        val = str(val or "cpu").strip().lower()
        if val not in {"cpu", "gpu"}:
            val = "cpu"
        if val != self._hymt2_runtime_mode:
            self._hymt2_runtime_mode = val; self._emit_changed(self._hymt2RuntimeModeChanged)

    @Property(str, notify=_japaneseResiduePolicyChanged)
    def japaneseResiduePolicy(self) -> str: return self._japanese_residue_policy
    @japaneseResiduePolicy.setter
    def japaneseResiduePolicy(self, val: str):
        val = str(val or "balanced").strip().lower()
        if val not in {"strict", "balanced", "lenient"}:
            val = "balanced"
        if val != self._japanese_residue_policy:
            self._japanese_residue_policy = val; self._emit_changed(self._japaneseResiduePolicyChanged)

    @Property(str, notify=_themeChanged)
    def theme(self) -> str: return self._theme
    @theme.setter
    def theme(self, val: str):
        if val != self._theme:
            self._theme = val; self._emit_changed(self._themeChanged)
