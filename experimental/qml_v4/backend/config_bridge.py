# -*- coding: utf-8 -*-
"""
配置桥接器：管理应用配置，提供 QML 可绑定的属性，支持持久化到 JSON 文件。
"""

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Property, Slot

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

PROVIDER_DEFAULTS = {
    "deepseek": {"url": DEEPSEEK_API_URL, "model": DEEPSEEK_MODEL},
    "doubao":   {"url": DOUBAO_API_URL,   "model": DOUBAO_MODEL},
    "sakura":   {"url": SAKURA_API_URL,   "model": SAKURA_MODEL},
    "gemini":   {"url": GEMINI_API_URL,   "model": GEMINI_MODEL},
    "glm":      {"url": GLM_API_URL,      "model": GLM_MODEL},
    "wenxin":   {"url": WENXIN_API_URL,   "model": WENXIN_MODEL},
    "custom":   {"url": "", "model": ""},
}

PROVIDER_HINTS = {
    "deepseek": "DeepSeek 官方 API，速度快质量好",
    "doubao":   "火山引擎豆包模型，需自行申请 API Key",
    "sakura":   "本地 Sakura 模型，需自行部署（默认 127.0.0.1:8080）",
    "gemini":   "Google Gemini API，免费额度有限",
    "glm":      "智谱开放平台，免费版限制并发",
    "wenxin":   "百度千帆/文心一言 OpenAI 兼容接口，需使用千帆 API Key",
    "custom":   "任意 OpenAI 兼容端点，请手动填写 URL 和模型名",
}

PROVIDER_CAPABILITY = {
    "glm": "智谱免费版限制并发 ≤2，batch ≤2",
    "gemini": "Gemini 免费版有限流",
    "wenxin": "文心一言/千帆：建议先低并发低批量测试，旧版 access_token RPC 接口不兼容",
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
}

# Keys that are persisted
_CONFIG_KEYS = [
    "inp", "out", "api_key", "provider", "api_url", "model",
    "extract_glossary", "enable_glossary",
    "max_workers", "batch_size", "max_batch_length", "max_text_size_for_batch", "api_timeout",
    "direction", "enable_thinking", "enable_proofread", "theme",
]

CONFIG_FILE_NAME = "config.json"


def _data_dir() -> Path:
    data_dir = Path.home() / ".epub_translator"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def _config_path() -> Path:
    return _data_dir() / CONFIG_FILE_NAME


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
    _themeChanged = Signal()

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
        self._theme = "light"
        self._load_from_disk()

    def _load_from_disk(self):
        path = _config_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in _CONFIG_KEYS:
                if key in data:
                    setattr(self, f"_{key}", data[key])
            logger.info(f"配置已加载: {path}")
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")

    @Slot()
    def saveToDisk(self):
        """持久化当前配置到 JSON 文件。"""
        path = _config_path()
        data = {}
        for key in _CONFIG_KEYS:
            val = getattr(self, f"_{key}", None)
            if val is not None and val != "":
                data[key] = val
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"配置已保存: {path}")
        except Exception as e:
            logger.warning(f"保存配置失败: {e}")

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
        self.configChanged.emit()

    # --- Properties ---
    @Property(str, notify=_inpChanged)
    def inp(self) -> str: return self._inp
    @inp.setter
    def inp(self, val: str):
        if val != self._inp:
            self._inp = val; self._inpChanged.emit()

    @Property(str, notify=_outChanged)
    def out(self) -> str: return self._out
    @out.setter
    def out(self, val: str):
        if val != self._out:
            self._out = val; self._outChanged.emit()

    @Property(str, notify=_apiKeyChanged)
    def apiKey(self) -> str: return self._api_key
    @apiKey.setter
    def apiKey(self, val: str):
        if val != self._api_key:
            self._api_key = val; self._apiKeyChanged.emit()

    @Property(str, notify=_providerChanged)
    def provider(self) -> str: return self._provider

    @Property(str, notify=_apiUrlChanged)
    def apiUrl(self) -> str: return self._api_url
    @apiUrl.setter
    def apiUrl(self, val: str):
        if val != self._api_url:
            self._api_url = val; self._apiUrlChanged.emit()

    @Property(str, notify=_modelChanged)
    def model(self) -> str: return self._model
    @model.setter
    def model(self, val: str):
        if val != self._model:
            self._model = val; self._modelChanged.emit()

    @Property(bool, notify=_extractGlossaryChanged)
    def extractGlossary(self) -> bool: return self._extract_glossary
    @extractGlossary.setter
    def extractGlossary(self, val: bool):
        if val != self._extract_glossary:
            self._extract_glossary = val; self._extractGlossaryChanged.emit()

    @Property(bool, notify=_enableGlossaryChanged)
    def enableGlossary(self) -> bool: return self._enable_glossary
    @enableGlossary.setter
    def enableGlossary(self, val: bool):
        if val != self._enable_glossary:
            self._enable_glossary = val; self._enableGlossaryChanged.emit()

    @Property(int, notify=_maxWorkersChanged)
    def maxWorkers(self) -> int: return self._max_workers
    @maxWorkers.setter
    def maxWorkers(self, val: int):
        if val != self._max_workers:
            self._max_workers = val; self._maxWorkersChanged.emit()

    @Property(int, notify=_batchSizeChanged)
    def batchSize(self) -> int: return self._batch_size
    @batchSize.setter
    def batchSize(self, val: int):
        if val != self._batch_size:
            self._batch_size = val; self._batchSizeChanged.emit()

    @Property(int, notify=_maxBatchLengthChanged)
    def maxBatchLength(self) -> int: return self._max_batch_length
    @maxBatchLength.setter
    def maxBatchLength(self, val: int):
        if val != self._max_batch_length:
            self._max_batch_length = val; self._maxBatchLengthChanged.emit()

    @Property(int, notify=_maxTextSizeForBatchChanged)
    def maxTextSizeForBatch(self) -> int: return self._max_text_size_for_batch
    @maxTextSizeForBatch.setter
    def maxTextSizeForBatch(self, val: int):
        if val != self._max_text_size_for_batch:
            self._max_text_size_for_batch = val; self._maxTextSizeForBatchChanged.emit()

    @Property(int, notify=_apiTimeoutChanged)
    def apiTimeout(self) -> int: return self._api_timeout
    @apiTimeout.setter
    def apiTimeout(self, val: int):
        if val != self._api_timeout:
            self._api_timeout = val; self._apiTimeoutChanged.emit()

    @Property(str, notify=_directionChanged)
    def direction(self) -> str: return self._direction
    @direction.setter
    def direction(self, val: str):
        if val != self._direction:
            self._direction = val; self._directionChanged.emit()

    @Property(bool, notify=_enableThinkingChanged)
    def enableThinking(self) -> bool: return self._enable_thinking
    @enableThinking.setter
    def enableThinking(self, val: bool):
        if val != self._enable_thinking:
            self._enable_thinking = val; self._enableThinkingChanged.emit()

    @Property(bool, notify=_enableProofreadChanged)
    def enableProofread(self) -> bool: return self._enable_proofread
    @enableProofread.setter
    def enableProofread(self, val: bool):
        if val != self._enable_proofread:
            self._enable_proofread = val; self._enableProofreadChanged.emit()

    @Property(str, notify=_themeChanged)
    def theme(self) -> str: return self._theme
    @theme.setter
    def theme(self, val: str):
        if val != self._theme:
            self._theme = val; self._themeChanged.emit()
