import json
import logging
import os
import random
import re
import sys
import threading
import time
import uuid
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import requests

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

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL = "Doubao-Seed-1.6-flash"
SAKURA_API_URL = "http://127.0.0.1:8080/v1/chat/completions"
SAKURA_MODEL = "sakura-v1.0"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_TEXT_SEPARATOR = "\n---SPLIT---\n"


class FastFailError(RuntimeError):
    """用于标识应立即中断流程的不可恢复错误（如明确配置的 HTTP 502）。"""


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
        chunk_size: int = 1200,
        cancel_event: Optional[threading.Event] = None,
        extract_glossary: bool = False,
        enable_glossary: bool = True,
        preset: Optional[str] = None,
    ):
        self.provider = (provider or "deepseek").strip().lower()
        if self.provider not in {"deepseek", "doubao", "sakura", "gemini", "custom"}:
            raise ValueError(f"不支持的提供方: {provider}")

        self.api_key = api_key or ""
        if not self.api_key:
            if self.provider == "deepseek":
                self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
            elif self.provider == "doubao":
                self.api_key = os.getenv("DOUBAO_API_KEY", "") or os.getenv("ARK_API_KEY", "")
        if self.provider == "deepseek" and not self.api_key:
            raise ValueError("未找到 DeepSeek API Key，请在界面输入或设置环境变量 DEEPSEEK_API_KEY")
        if self.provider == "doubao" and not self.api_key:
            raise ValueError("未找到豆包 API Key，请在界面输入或设置环境变量 DOUBAO_API_KEY / ARK_API_KEY")
        if self.provider == "gemini" and not self.api_key:
            raise ValueError("未找到 Gemini API Key，请在界面输入")
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

        raw_api_url = (api_url or default_url).strip()
        self.api_url = self._normalize_api_url(raw_api_url)
        self.model = (model or default_model).strip()
        self.temperature = temperature if temperature is not None else (0.1 if self.provider == "sakura" else 0.3)
        self.top_p = top_p if top_p is not None else (0.3 if self.provider == "sakura" else None)
        self.frequency_penalty = (
            frequency_penalty if frequency_penalty is not None else (0.1 if self.provider == "sakura" else None)
        )

        data_dir = get_data_dir()
        self.glossary_path = glossary_path or str(data_dir / "glossary.json")
        self.cache_path = cache_path or str(data_dir / "cache.json")
        self.enable_glossary = bool(enable_glossary)

        # 应用性能预设（如果指定）
        if preset and preset in PERFORMANCE_PRESETS:
            preset_config = PERFORMANCE_PRESETS[preset]
            max_workers = preset_config["max_workers"]
            batch_size = preset_config["batch_size"]
            max_batch_length = preset_config["max_batch_length"]
            max_text_size_for_batch = preset_config["max_text_size_for_batch"]
            chunk_size = preset_config["chunk_size"]
            logger.info(f"应用性能预设: {preset}")

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

        self._cache_dirty = False
        self._save_counter = 0
        self._cache_lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self._glossary_prompt_max_terms = 120
        self.max_workers = max_workers
        self.batch_size = batch_size
        self.max_batch_length = max_batch_length
        self.max_text_size_for_batch = max_text_size_for_batch
        self.chunk_size = chunk_size
        self.cancel_event = cancel_event or threading.Event()
        self.session = requests.Session()
        # 连接池大小与并发数匹配，避免 "Connection pool is full" 警告
        adapter = requests.adapters.HTTPAdapter(pool_connections=self.max_workers, pool_maxsize=self.max_workers)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.extract_glossary = bool(extract_glossary)

        # 加载提示词模板
        dict_dir = get_dict_dir()
        self._extraction_prompt_data = load_prompt_template(dict_dir, "glossary_extraction_prompt")
        self._output_format_data = load_prompt_template(dict_dir, "system_prompt_hq_format")

        self.stats = {
            "api_requests_total": 0,
            "batch_total": 0,
            "batch_json_success": 0,
            "batch_delimiter_success": 0,
            "batch_fallback": 0,
            "batch_split_mismatch": 0,
            "batch_json_parse_fail": 0,
            "glossary_new_terms_added": 0,
        }
        logger.info(
            f"翻译器初始化完成: provider={self.provider}, model={self.model}, "
            f"并发数={self.max_workers}, 批量大小={self.batch_size}"
        )

    def _apply_provider_payload_options(self, payload: Dict[str, Any]) -> None:
        """为特定提供方追加请求参数。"""
        if self.provider in {"deepseek", "doubao"}:
            # 用户要求关闭深度思考。
            payload["thinking"] = {"type": "disabled"}

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
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
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
        """
        归一化术语表为分类结构。
        支持：
        1) {src: dst}
        2) {src: {"dst"/"translation", "info"}}
        3) {Person:[{original,translation}], ...}
        冲突策略：keep_old（同 original 出现多次时保留首次）。
        """
        normalized: Dict[str, List[Dict[str, str]]] = {c: [] for c in DEFAULT_GLOSSARY_CATEGORIES}
        stats = {"accepted": 0, "skipped": 0, "conflicts": 0}
        seen_by_original: Dict[str, str] = {}

        def _add_entry(src_raw: Any, dst_raw: Any, category: str = "Item", info_raw: Any = ""):
            src = str(src_raw).strip()
            dst = str(dst_raw).strip()
            info = str(info_raw).strip()
            if not src or not dst:
                stats["skipped"] += 1
                return
            if category not in DEFAULT_GLOSSARY_CATEGORIES:
                category = "Item"
            prev = seen_by_original.get(src)
            if prev is not None:
                if prev != dst:
                    stats["conflicts"] += 1
                stats["skipped"] += 1
                return
            seen_by_original[src] = dst
            entry = {"original": src, "translation": dst}
            if info:
                entry["info"] = info
            normalized[category].append(entry)
            stats["accepted"] += 1

        if not isinstance(payload, dict):
            return normalized, stats

        has_category_key = any(k in payload and isinstance(payload.get(k), list) for k in DEFAULT_GLOSSARY_CATEGORIES)
        if has_category_key:
            for category in DEFAULT_GLOSSARY_CATEGORIES:
                entries = payload.get(category, [])
                if not isinstance(entries, list):
                    continue
                for item in entries:
                    if not isinstance(item, dict):
                        stats["skipped"] += 1
                        continue
                    src = item.get("original", item.get("src", ""))
                    dst = item.get("translation", item.get("dst", ""))
                    info = item.get("info", "")
                    _add_entry(src, dst, category=category, info_raw=info)
            return normalized, stats

        for src, value in payload.items():
            if isinstance(value, dict):
                dst = value.get("dst", value.get("translation", ""))
                info = value.get("info", "")
            else:
                dst = value
                info = ""
            _add_entry(src, dst, category="Item", info_raw=info)

        return normalized, stats

    def _save_cache(self, force: bool = False):
        """保存缓存到文件，使用延迟写入策略"""
        with self._cache_lock:
            self._cache_dirty = True
            self._save_counter += 1

            if force or self._save_counter >= self.CACHE_SAVE_THRESHOLD:
                try:
                    with open(self.cache_path, "w", encoding="utf-8") as f:
                        json.dump(self.cache, f, ensure_ascii=False, indent=2)
                    self._cache_dirty = False
                    self._save_counter = 0
                except IOError as e:
                    logger.error(f"缓存保存失败: {e}")

    def flush_cache(self):
        """强制保存缓存（程序退出或翻译完成时调用）"""
        if self._cache_dirty:
            self._save_cache(force=True)

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
        """按上下文召回相关术语，仅返回命中项。"""
        if not self.enable_glossary:
            return []
        with self._cache_lock:
            glossary_snapshot = dict(self.glossary)
        if not glossary_snapshot:
            return []

        selected: List[Dict[str, str]] = []
        seen_original = set()
        limit = max_terms or self._glossary_prompt_max_terms

        # 新格式优先
        is_categorized = any(
            key in glossary_snapshot and isinstance(glossary_snapshot.get(key), list)
            for key in self.glossary_categories
        )
        if is_categorized:
            for category in self.glossary_categories:
                entries = glossary_snapshot.get(category, [])
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    original = str(entry.get("original", entry.get("src", ""))).strip()
                    translation = str(entry.get("translation", entry.get("dst", ""))).strip()
                    if not original or not translation:
                        continue
                    if original in seen_original:
                        continue
                    if original in context_text:
                        selected.append({"original": original, "translation": translation})
                        seen_original.add(original)
                        if len(selected) >= limit:
                            return selected
            return selected

        # 旧格式兜底
        for k, v in glossary_snapshot.items():
            original = str(k).strip()
            if not original or original in seen_original:
                continue
            if isinstance(v, dict):
                translation = str(v.get("dst", v.get("translation", ""))).strip()
            else:
                translation = str(v).strip()
            if not translation:
                continue
            if original in context_text:
                selected.append({"original": original, "translation": translation})
                seen_original.add(original)
                if len(selected) >= limit:
                    return selected
        return selected

    def _build_glossary_text(self, selected_entries: Optional[List[Dict[str, str]]] = None) -> str:
        """构建术语表文本；传入 selected_entries 时仅输出命中术语。"""
        if selected_entries is not None:
            if not selected_entries:
                return "无术语表。"
            lines = []
            for item in selected_entries:
                original = str(item.get("original", "")).strip()
                translation = str(item.get("translation", "")).strip()
                if original and translation:
                    lines.append(f"{original}->{translation}")
            return "\n".join(lines) if lines else "无术语表。"

        """构建术语表文本，兼容新旧两种格式"""
        with self._cache_lock:
            glossary_snapshot = dict(self.glossary)

        if not glossary_snapshot:
            return "无术语表。"

        lines = []

        # 检测是否为新格式（分类结构）
        is_categorized = any(
            key in glossary_snapshot and isinstance(glossary_snapshot.get(key), list)
            for key in self.glossary_categories
        )

        if is_categorized:
            # 新格式：按分类输出
            for category in self.glossary_categories:
                entries = glossary_snapshot.get(category, [])
                if not isinstance(entries, list) or not entries:
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    original = entry.get("original", entry.get("src", ""))
                    translation = entry.get("translation", entry.get("dst", ""))
                    if original and translation:
                        lines.append(f"{original}->{translation}")
        else:
            # 旧格式：扁平结构
            for k, v in glossary_snapshot.items():
                if isinstance(v, dict):
                    dst = str(v.get("dst", "")).strip()
                    info = str(v.get("info", "")).strip()
                    if dst and info:
                        lines.append(f"{k}->{dst} #{info}")
                    elif dst:
                        lines.append(f"{k}->{dst}")
                    else:
                        lines.append(f"{k} => {json.dumps(v, ensure_ascii=False)}")
                else:
                    lines.append(f"{k} => {v}")

        return "\n".join(lines) if lines else "无术语表。"

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

                return system_prompt

        # 回退到硬编码
        if not self.extract_glossary:
            return base_prompt + '\n\n当未启用术语抽取时，必须返回 "new_terms": []。'

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

        return base_prompt + "\n" + extraction_rules

    def _call_deepseek(
        self,
        text: str,
        max_retries: int = 3,  # 可通过 JaZhTranslator.MAX_RETRIES 调整默认值
        text_separator: Optional[str] = None,
    ) -> str:
        """调用模型 API，支持重试机制"""
        sep = text_separator or DEFAULT_TEXT_SEPARATOR
        is_batch = sep in text

        deepseek_prompt = """你是资深日文文学翻译专家，精通日中双语，擅长文学翻译。
【翻译原则】信、雅、达：
- 信：准确传达原文含义，不随意增删改，保持原作风格和情感基调
- 雅：译文文笔优美，符合中文表达习惯，避免生硬直译或翻译腔
- 达：语言流畅自然，通顺易懂，让读者沉浸在故事中
【日文特有表达处理】：
1. 敬语体系：将敬语转换为符合中文语境的表达，不必过度保留敬称
2. 姐さん/兄さん等称谓：根据角色关系，译为“姐姐/哥哥”或保留昵称风格
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
4. 标点符号使用中文规范"""

        sakura_prompt = """你是一个轻小说翻译模型，可以流畅通顺地使用给定术语表以指定格式从日文翻译到简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的人名。
你必须按照以下规则执行：
1. 理解并严格遵循术语表格式与备注。
2. 仅输出译文，不输出说明。
3. 不改变段落数量与顺序。"""

        system_prompt = sakura_prompt if self.provider == "sakura" else deepseek_prompt
        if is_batch:
            system_prompt += f"""

【重要！多段落分隔规则】原文由多个独立段落组成，段落之间用'{sep.strip()}'分隔。
你必须在译文中保留相同数量的段落，且每个段落之间也必须用'{sep.strip()}'分隔。
绝对不能将多个段落合并为一个段落！
输出格式：译文1{sep.strip()}译文2{sep.strip()}译文3..."""

        selected_entries = self._select_glossary_entries(text)
        user_prompt = (
            f"【术语表】\n{self._build_glossary_text(selected_entries)}\n\n"
            f"请将以下日文翻译为优美流畅的中文：\n{text}"
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    logger.warning(f"API 限流，等待 {wait_time:.1f} 秒后重试...")
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    raise FastFailError("翻译失败: HTTP 502 Bad Gateway（已按配置直接中断）")

                resp.raise_for_status()
                data = resp.json()
                # 验证响应格式
                choices = data.get("choices", [])
                if not choices:
                    raise KeyError("API 响应缺少 choices 字段")
                message = choices[0].get("message", {})
                content = message.get("content", "")
                if not content:
                    raise KeyError("API 响应缺少 content 字段")
                return content.strip()

            except requests.exceptions.Timeout:
                last_error = "请求超时"
                logger.warning(f"API 请求超时 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.ConnectionError:
                last_error = "网络连接失败"
                logger.warning(f"网络连接失败 (尝试 {attempt + 1}/{max_retries})")
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP 错误: {e}"
                logger.warning(f"HTTP 错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                last_error = f"API 响应格式错误: {e}"
                logger.error(f"API 响应格式错误: {e}")
                break
            except FastFailError:
                raise
            except Exception as e:
                last_error = f"未知错误: {e}"
                logger.error(f"未知错误: {e}")

            if attempt < max_retries - 1:
                wait_time = 2 ** attempt + random.uniform(0, 1)
                if self.cancel_event.wait(wait_time):
                    raise RuntimeError("翻译已取消")

        raise RuntimeError(f"翻译失败: {last_error}")

    def _call_deepseek_batch_json(self, texts: List[str], max_retries: int = 2) -> Optional[Dict[str, object]]:
        """批量翻译：结构化返回 translations + new_terms。失败时返回 None。"""
        if not texts:
            return {"translations": [], "new_terms": []}

        numbered = [{"idx": i, "text": t} for i, t in enumerate(texts)]

        # 从模板构建系统提示词
        system_prompt = self._build_batch_system_prompt()
        context_text = "\n".join(texts)
        selected_entries = self._select_glossary_entries(context_text)

        user_prompt = (
            f"【术语表】\n{self._build_glossary_text(selected_entries)}\n\n"
            f"请翻译以下 JSON 数组中的 text 字段并返回 JSON：\n{json.dumps(numbered, ensure_ascii=False)}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1 if self.provider == "deepseek" else self.temperature,
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
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                if resp.status_code == 502:
                    raise FastFailError("翻译失败: HTTP 502 Bad Gateway（已按配置直接中断）")
                resp.raise_for_status()
                data = resp.json()
                # 验证响应格式
                choices = data.get("choices", [])
                if not choices:
                    self._inc_stat("batch_json_parse_fail")
                    return None
                message = choices[0].get("message", {})
                raw = message.get("content", "")
                if not raw:
                    self._inc_stat("batch_json_parse_fail")
                    return None
                raw = raw.strip()
                obj = self._extract_json_object(raw)
                if not isinstance(obj, dict):
                    self._inc_stat("batch_json_parse_fail")
                    return None
                arr = obj.get("translations") or obj.get("items")
                if not isinstance(arr, list) or len(arr) != len(texts):
                    self._inc_stat("batch_json_parse_fail")
                    return None

                out = [None] * len(texts)
                for item in arr:
                    if not isinstance(item, dict):
                        self._inc_stat("batch_json_parse_fail")
                        return None
                    idx = item.get("idx")
                    zh = item.get("zh")
                    if not isinstance(idx, int) or idx < 0 or idx >= len(texts) or not isinstance(zh, str):
                        self._inc_stat("batch_json_parse_fail")
                        return None
                    out[idx] = zh.strip()
                if any(v is None for v in out):
                    self._inc_stat("batch_json_parse_fail")
                    return None
                raw_terms = obj.get("new_terms", [])
                if not isinstance(raw_terms, list):
                    raw_terms = []
                return {"translations": out, "new_terms": raw_terms}
            except FastFailError:
                raise
            except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
                logger.warning(f"批量翻译请求失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    if self.cancel_event.wait(wait_time):
                        raise RuntimeError("翻译已取消")
                    continue
                return None

        return None

    def replace_glossary(self, glossary: Dict[str, Any]) -> None:
        """线程安全替换术语表，并持久化到 glossary_path。"""
        with self._cache_lock:
            normalized, _ = self.normalize_glossary_payload(glossary or {})
            self.glossary = normalized
            self._atomic_write_json(self.glossary_path, self.glossary)

    @classmethod
    def merge_glossaries(
        cls,
        existing: Dict[str, List[Dict[str, str]]],
        incoming: Dict[str, List[Dict[str, str]]],
    ) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, int]]:
        """
        将 incoming 术语增量合并到 existing 中（keep_old 冲突策略）。

        Args:
            existing: 已有术语表（分类结构）
            incoming: 新导入的术语表（分类结构，已归一化）

        Returns:
            (merged, stats)  merged 为合并后的术语表，stats 含 added/skipped/conflicts
        """
        merged = {c: list(existing.get(c, [])) for c in DEFAULT_GLOSSARY_CATEGORIES}
        stats = {"added": 0, "skipped": 0, "conflicts": 0}
        seen: Dict[str, str] = {}
        for cat in DEFAULT_GLOSSARY_CATEGORIES:
            for entry in merged[cat]:
                original = str(entry.get("original", "")).strip()
                translation = str(entry.get("translation", "")).strip()
                if original and original not in seen:
                    seen[original] = translation

        for cat in DEFAULT_GLOSSARY_CATEGORIES:
            for entry in incoming.get(cat, []):
                src = str(entry.get("original", entry.get("src", ""))).strip()
                dst = str(entry.get("translation", entry.get("dst", ""))).strip()
                if not src or not dst:
                    stats["skipped"] += 1
                    continue
                prev = seen.get(src)
                if prev is not None:
                    if prev != dst:
                        stats["conflicts"] += 1
                    stats["skipped"] += 1
                    continue
                new_entry = {"original": src, "translation": dst}
                for k in ("info", "source"):
                    if k in entry and entry[k]:
                        new_entry[k] = entry[k]
                merged[cat].append(new_entry)
                seen[src] = dst
                stats["added"] += 1

        return merged, stats

    @staticmethod
    def _clean_new_terms(raw_terms: List[dict]) -> List[Dict[str, Any]]:
        """
        清洗术语：最短长度、排除通用词、去重，保留分类信息。

        Returns:
            清洗后的术语列表，每个元素包含
            {"src": ..., "dst": ..., "category": ..., "info"?: ..., "source": ...}
        """
        if not raw_terms:
            return []

        # 通用词停用表（不提取）
        stop_words = {
            "我们", "你们", "他们", "这个", "那个", "这里", "那里", "然后", "但是", "因为", "所以",
            "可以", "不会", "已经", "正在", "没有", "非常", "真的", "老师", "学校", "城市", "国家",
            "魔法", "剑", "勇者", "魔王", "世界", "时间", "地方", "事情", "东西", "样子",
            "之后", "之前", "起来", "下去", "出来", "进去", "回来", "过来",
        }

        # 分类映射（处理各种变体）
        category_map = {
            "person": "Person",
            "角色": "Person",
            "人物": "Person",
            "location": "Location",
            "地点": "Location",
            "场所": "Location",
            "org": "Org",
            "organization": "Org",
            "组织": "Org",
            "团体": "Org",
            "item": "Item",
            "物品": "Item",
            "装备": "Item",
            "道具": "Item",
            "skill": "Skill",
            "技能": "Skill",
            "招式": "Skill",
            "魔法": "Skill",
            "creature": "Creature",
            "生物": "Creature",
            "怪物": "Creature",
            "宠物": "Creature",
        }

        cleaned: List[Dict[str, Any]] = []
        seen = set()

        for item in raw_terms:
            if not isinstance(item, dict):
                continue

            # 兼容多种字段名
            src = str(item.get("src", item.get("original", ""))).strip()
            dst = str(item.get("dst", item.get("translation", ""))).strip()
            raw_category = item.get("category", item.get("cat", ""))
            info = str(item.get("info", "")).strip()
            source = str(item.get("source", "auto")).strip() or "auto"

            if not src or not dst:
                continue
            if len(src) < 2 or len(dst) < 2:
                continue
            if src in stop_words or dst in stop_words:
                continue

            # 标准化分类
            category = "Item"  # 默认分类
            if raw_category:
                normalized = str(raw_category).lower().strip()
                category = category_map.get(normalized, raw_category if raw_category in DEFAULT_GLOSSARY_CATEGORIES else "Item")

            key = (src, dst)
            if key in seen:
                continue
            seen.add(key)

            cleaned.append({
                "src": src,
                "dst": dst,
                "category": category,
                "info": info,
                "source": source,
            })

        return cleaned

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

            existing_by_original: Dict[str, str] = {}
            for cat in self.glossary_categories:
                for entry in self.glossary.get(cat, []):
                    if not isinstance(entry, dict):
                        continue
                    original = str(entry.get("original", entry.get("src", ""))).strip()
                    translation = str(entry.get("translation", entry.get("dst", ""))).strip()
                    if original and translation and original not in existing_by_original:
                        existing_by_original[original] = translation

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

                prev = existing_by_original.get(src)
                if prev is not None:
                    if prev != dst:
                        conflicts += 1
                    skipped += 1
                    continue

                new_entry: Dict[str, str] = {
                    "original": src,
                    "translation": dst,
                }
                if info:
                    new_entry["info"] = info
                if source:
                    new_entry["source"] = source
                self.glossary[category].append(new_entry)
                existing_by_original[src] = dst
                added += 1

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

    def _translate_chunk(self, text: str) -> str:
        """翻译单个文本块（带缓存）"""
        text = text.strip()
        if not text:
            return text

        if self.cancel_event.is_set():
            raise RuntimeError("翻译已取消")

        with self._cache_lock:
            if text in self.cache:
                return self.cache[text]

        zh = self._call_deepseek(text)

        with self._cache_lock:
            self.cache[text] = zh

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

        with self._cache_lock:
            if text in self.cache:
                return self.cache[text]

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

        with self._cache_lock:
            self.cache[text] = zh
        self._save_cache()
        return zh

    def translate_batch(
        self,
        texts: List[str],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        item_callback: Optional[Callable[[str, str], None]] = None,
        batch_size: Optional[int] = None,
    ) -> Dict[str, str]:
        """并发批量翻译多个文本"""
        results: Dict[str, str] = {}
        total = len(texts)
        completed = 0

        # 使用实例配置，允许传入覆盖
        effective_batch_size = batch_size if batch_size is not None else self.batch_size

        uncached_unique: List[str] = []
        seen_uncached = set()

        with self._cache_lock:
            for text in texts:
                if text in self.cache:
                    results[text] = self.cache[text]
                    completed += 1
                elif text not in seen_uncached:
                    uncached_unique.append(text)
                    seen_uncached.add(text)

        logger.info(f"批量翻译: {total} 条，缓存命中 {completed} 条，待翻译去重后 {len(uncached_unique)} 条")

        if progress_callback:
            progress_callback(completed, total)

        if not uncached_unique:
            return results

        batches = []
        current_batch = []
        current_length = 0
        max_batch_length = self.max_batch_length

        for text in uncached_unique:
            if len(text) <= self.max_text_size_for_batch and current_length + len(text) < max_batch_length and len(current_batch) < effective_batch_size:
                current_batch.append(text)
                current_length += len(text)
            else:
                if current_batch:
                    batches.append(current_batch)
                if len(text) <= self.max_text_size_for_batch:
                    current_batch = [text]
                    current_length = len(text)
                else:
                    batches.append([text])
                    current_batch = []
                    current_length = 0

        if current_batch:
            batches.append(current_batch)

        logger.info(f"合并为 {len(batches)} 个批次进行并发翻译")
        mismatch_count = 0

        def translate_one_batch(batch: List[str]) -> List[Tuple[str, str]]:
            nonlocal mismatch_count
            if self.cancel_event.is_set():
                raise RuntimeError("翻译已取消")

            if len(batch) == 1:
                text = batch[0]
                zh = self._translate_chunk(text)
                return [(text, zh)]

            self._inc_stat("batch_total")
            # 优先使用结构化 JSON 返回，减少分割符丢失导致的拆分失败。
            payload = self._call_deepseek_batch_json(batch)
            if payload and isinstance(payload, dict):
                json_parts = payload.get("translations", [])
                if isinstance(json_parts, list) and len(json_parts) == len(batch):
                    if self.extract_glossary:
                        raw_terms = payload.get("new_terms", [])
                        cleaned_terms = self._clean_new_terms(raw_terms if isinstance(raw_terms, list) else [])
                        self._merge_new_terms_into_glossary(cleaned_terms)
                    self._inc_stat("batch_json_success")
                    return list(zip(batch, json_parts))

            if payload and not isinstance(payload, dict):
                json_parts = payload
            else:
                json_parts = None
            if json_parts and len(json_parts) == len(batch):
                self._inc_stat("batch_json_success")
                return list(zip(batch, json_parts))

            separator = f"\n---SPLIT-{uuid.uuid4().hex}---\n"
            combined = separator.join(batch)
            combined_zh = self._call_deepseek(combined, text_separator=separator)
            parts = combined_zh.split(separator)

            if len(parts) != len(batch):
                with self._cache_lock:
                    mismatch_count += 1
                self._inc_stat("batch_fallback")
                self._inc_stat("batch_split_mismatch")
                return [(t, self._translate_chunk(t)) for t in batch]

            self._inc_stat("batch_delimiter_success")
            return list(zip(batch, parts))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(translate_one_batch, batch): batch for batch in batches}

            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    raise RuntimeError("翻译已取消")

                try:
                    batch_results = future.result()
                    for original, translated in batch_results:
                        results[original] = translated
                        completed += 1
                        if item_callback:
                            item_callback(original, translated)
                        if progress_callback:
                            progress_callback(completed, total)
                except Exception as e:
                    logger.error(f"批次翻译失败: {e}")
                    if "502" in str(e):
                        raise
                    batch = futures[future]
                    for text in batch:
                        if self.cancel_event.is_set():
                            raise RuntimeError("翻译已取消")
                        try:
                            zh = self._translate_chunk(text)
                            results[text] = zh
                        except Exception as e2:
                            logger.error(f"翻译失败: {e2}")
                            results[text] = text
                        completed += 1
                        if item_callback:
                            item_callback(text, results[text])
                        if progress_callback:
                            progress_callback(completed, total)

        self._save_cache(force=True)
        if mismatch_count:
            logger.warning(f"批量拆分回退 {mismatch_count} 次（模型输出与批次数不一致，已自动逐条翻译）")

        for text in texts:
            if text not in results:
                with self._cache_lock:
                    cached = self.cache.get(text)
                if cached is not None:
                    results[text] = cached

        return results

    def __del__(self):
        """析构时保存缓存"""
        try:
            self.flush_cache()
            self.session.close()
        except Exception:
            pass
