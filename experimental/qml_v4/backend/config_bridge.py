# -*- coding: utf-8 -*-
"""
配置桥接器：管理应用配置，提供 QML 可绑定的属性，支持持久化到 JSON 文件。
"""

import json
import logging
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
    "hymt2": "Hy-MT2 本地：稳定模式自动限制并发=1、batch=1、超时≥300；适合离线初译或审核备用，不建议默认承担最终校对",
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
        "label": "Hy-MT2 本地", "hint": "本地小模型稳定保存优先，禁用批量 JSON",
        "values": { "max_workers": 1, "batch_size": 1, "max_batch_length": 300, "max_text_size_for_batch": 120, "api_timeout": 300 },
    },
}

# Keys that are persisted
_CONFIG_KEYS = [
    "inp", "out", "api_key", "provider", "api_url", "model",
    "extract_glossary", "enable_glossary",
    "max_workers", "batch_size", "max_batch_length", "max_text_size_for_batch", "api_timeout",
    "direction", "enable_thinking", "enable_proofread", "proofread_genre", "proofread_tone",
    "proofread_provider", "proofread_api_key", "proofread_api_url", "proofread_model",
    "allow_text_cache_reuse", "prompt_extra_instruction", "enable_prompt_examples", "theme",
    "enable_notice_page", "notice_page_text",
]

CONFIG_FILE_NAME = "config.json"
JAPANESE_RESIDUE_ALLOWLIST_FILE_NAME = "japanese_residue_allowlist.json"
DEFAULT_NOTICE_PAGE_TEXT = (
    "本书由 AI日译中(EPUB) V4.1 辅助翻译。\n"
    "译文仅供个人学习、研究与阅读辅助使用，请勿传播或用于商业用途。\n"
    "请支持并购买正版书籍。"
)
_RESIDUE_QUOTE_CHARS = "「」『』“”\"'（）()【】[]"


def _data_dir() -> Path:
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _config_path() -> Path:
    return _data_dir() / CONFIG_FILE_NAME


def _japanese_residue_allowlist_path() -> Path:
    return _data_dir() / JAPANESE_RESIDUE_ALLOWLIST_FILE_NAME


def _normalize_residue_fragment(fragment: str) -> str:
    text = str(fragment or "").strip()
    return text.strip(_RESIDUE_QUOTE_CHARS).strip()


def _default_residue_allowlist() -> Dict[str, List[str]]:
    return {"quoted": [], "exact": [], "quoted_regex": [], "regex": []}


def _clean_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
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
            if "enable_notice_page" not in data:
                self._enable_notice_page = False
            if not str(getattr(self, "_notice_page_text", "") or "").strip():
                self._notice_page_text = DEFAULT_NOTICE_PAGE_TEXT
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

    @Property(str, notify=_themeChanged)
    def theme(self) -> str: return self._theme
    @theme.setter
    def theme(self, val: str):
        if val != self._theme:
            self._theme = val; self._emit_changed(self._themeChanged)
