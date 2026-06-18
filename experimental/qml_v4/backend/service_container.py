# -*- coding: utf-8 -*-
"""
服务容器模块 — 参考 manga-translator-ui 的 ServiceContainer 模式

提供统一的依赖注入容器，管理应用级服务实例的生命周期。
支持分阶段初始化（light → heavy），避免启动时一次性加载所有模块。

用法：
    from backend.service_container import ServiceContainer, get_container

    container = get_container()

    # 轻量初始化（UI 启动前）
    container.init_light(config_path=...)

    # 重量初始化（翻译开始前，懒加载）
    translator = container.get_translator()

    # 便捷访问
    from backend.service_container import get_config
    cfg = get_config()
"""

import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 全局容器单例
_container: Optional["ServiceContainer"] = None
_container_lock = threading.Lock()


def get_container() -> "ServiceContainer":
    """获取全局服务容器单例。"""
    global _container
    with _container_lock:
        if _container is None:
            _container = ServiceContainer()
        return _container


# ---------------------------------------------------------------------------
# 便捷函数 — 从容器中获取服务实例
# ---------------------------------------------------------------------------
def get_config() -> Optional[Dict[str, Any]]:
    return get_container().config

def get_translator() -> Optional[Any]:
    return get_container().translator

def get_cache() -> Optional[Dict[str, str]]:
    return get_container().cache

def get_glossary() -> Optional[Dict[str, Any]]:
    return get_container().glossary


# ---------------------------------------------------------------------------
# 服务容器
# ---------------------------------------------------------------------------
class ServiceContainer:
    """
    服务容器：统一管理应用级服务实例。

    初始化分两阶段：
        init_light()  — 加载配置、日志、缓存（启动时）
        init_heavy()  — 加载翻译器实例、术语表等（翻译开始前，懒加载）
    """

    def __init__(self):
        self._config: Dict[str, Any] = {}
        self._translator = None
        self._cache: Dict[str, str] = {}
        self._glossary: Dict[str, Any] = {}
        self._data_dir: Optional[Path] = None
        self._light_initialized = False
        self._heavy_initialized = False
        self._lock = threading.Lock()

    # ---- 属性 ----
    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    @config.setter
    def config(self, value: Dict[str, Any]):
        self._config = value

    @property
    def translator(self) -> Optional[Any]:
        return self._translator

    @property
    def cache(self) -> Dict[str, str]:
        return self._cache

    @property
    def glossary(self) -> Dict[str, Any]:
        return self._glossary

    @property
    def data_dir(self) -> Optional[Path]:
        return self._data_dir

    @property
    def light_initialized(self) -> bool:
        return self._light_initialized

    @property
    def heavy_initialized(self) -> bool:
        return self._heavy_initialized

    # ---- 初始化 ----
    def init_light(self, config_path: Optional[str] = None) -> "ServiceContainer":
        """
        轻量初始化：加载配置、缓存、数据目录。
        在 UI 启动前调用，不加载翻译器等重量模块。
        """
        if self._light_initialized:
            return self

        with self._lock:
            if self._light_initialized:
                return self

            # 确定数据目录
            from translator import get_data_dir
            self._data_dir = get_data_dir()
            logger.info(f"数据目录: {self._data_dir}")

            # 加载配置
            if config_path is None:
                config_path = str(self._data_dir / "config.json")
            self._config = self._load_json(config_path) or {}
            logger.info(f"配置已加载: {config_path}")

            # 加载缓存
            cache_path = self._data_dir / "cache.json"
            self._cache = self._load_json(str(cache_path)) or {}
            logger.info(f"缓存已加载: {len(self._cache)} 条记录")

            self._light_initialized = True
            logger.info("轻量初始化完成")

        return self

    def init_heavy(self, translator_config: Optional[Dict[str, Any]] = None) -> "ServiceContainer":
        """
        重量初始化：加载翻译器实例、术语表等。
        在翻译开始前懒加载，避免启动时开销。
        """
        if self._heavy_initialized:
            return self

        if not self._light_initialized:
            self.init_light()

        with self._lock:
            if self._heavy_initialized:
                return self

            # 加载术语表
            glossary_path = self._data_dir / "glossary.json"
            self._glossary = self._load_json(str(glossary_path)) or {}
            logger.info(f"术语表已加载: {len(self._glossary)} 条记录")

            self._heavy_initialized = True
            logger.info("重量初始化完成")

        return self

    def get_translator(self, **kwargs) -> Any:
        """
        获取或创建翻译器实例。
        翻译器按需创建，避免提前加载。
        """
        from translator import JaZhTranslator

        cfg = {**self._config, **kwargs}
        translator = JaZhTranslator(
            api_key=cfg.get("api_key"),
            provider=cfg.get("provider", "deepseek"),
            api_url=cfg.get("api_url"),
            model=cfg.get("model"),
            max_workers=int(cfg.get("max_workers", 5)),
            batch_size=int(cfg.get("batch_size", 4)),
            max_batch_length=int(cfg.get("max_batch_length", 800)),
            max_text_size_for_batch=int(cfg.get("max_text_size_for_batch", 200)),
            api_timeout=int(cfg.get("api_timeout", 120)),
            cancel_event=cfg.get("cancel_event"),
            extract_glossary=cfg.get("extract_glossary", False),
            enable_glossary=cfg.get("enable_glossary", True),
            enable_thinking=cfg.get("enable_thinking", False),
            enable_proofread=cfg.get("enable_proofread", False),
            proofread_genre=cfg.get("proofread_genre", "general"),
            proofread_tone=cfg.get("proofread_tone", "neutral"),
        )
        self._translator = translator
        return translator

    def save_config(self, path: Optional[str] = None) -> bool:
        """保存配置到磁盘。"""
        if path is None:
            path = str(self._data_dir / "config.json")
        return self._save_json(path, self._config)

    def save_cache(self, path: Optional[str] = None) -> bool:
        """保存缓存到磁盘。"""
        if path is None:
            path = str(self._data_dir / "cache.json")
        return self._save_json(path, self._cache)

    def clear(self):
        """清理容器状态。"""
        self._config = {}
        self._translator = None
        self._cache = {}
        self._glossary = {}
        self._light_initialized = False
        self._heavy_initialized = False

    # ---- 内部工具 ----
    @staticmethod
    def _load_json(path: str) -> Optional[Dict[str, Any]]:
        import json
        try:
            p = Path(path)
            if not p.exists():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载 JSON 失败 ({path}): {e}")
            return None

    @staticmethod
    def _save_json(path: str, data: Dict[str, Any]) -> bool:
        import json
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            # 原子写入
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
            return True
        except Exception as e:
            logger.error(f"保存 JSON 失败 ({path}): {e}")
            return False
