import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, Union


logger = logging.getLogger(__name__)


def load_json(path: str, default: Any) -> Any:
    """Load JSON from file; return default on missing or decode error."""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 文件解析失败 {path}: {e}")
            return default
    return default


def atomic_write_json(path: Union[str, Path], payload: Dict[str, Any]) -> None:
    """Atomically write JSON to avoid file corruption on interruption."""
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
