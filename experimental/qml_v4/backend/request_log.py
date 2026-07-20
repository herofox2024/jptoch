# -*- coding: utf-8 -*-
"""Persistent structured request logs for QML/V4 diagnostics."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOCK = threading.RLock()
_MAX_LINES_PER_FILE = 2000
_MAX_FILES = 14
_SNIPPET_LIMIT = 900

_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;\"'}]+"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;\"'}]+"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{12,})\b"),
]


def data_dir() -> Path:
    path = Path.home() / ".epub_translator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def request_log_dir() -> Path:
    path = data_dir() / "request_logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def current_log_path() -> Path:
    return request_log_dir() / f"request-log-{time.strftime('%Y%m%d')}.jsonl"


def redact(value: Any) -> str:
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + "***" if match.groups() else "***", text)
    return text


def compact_text(value: Any, limit: int = _SNIPPET_LIMIT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            value = str(value)
    text = redact(re.sub(r"\s+", " ", value).strip())
    limit = max(80, int(limit or _SNIPPET_LIMIT))
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def estimate_tokens(*values: Any) -> int:
    chars = 0
    for value in values:
        if value is None:
            continue
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        chars += len(value)
    return max(1, chars // 2) if chars else 0


def classify(outcome: str = "", status_code: Optional[int] = None, error: str = "", category: str = "") -> str:
    if category:
        return str(category).strip().lower()
    raw = f"{outcome or ''} {status_code or ''} {error or ''}".lower()
    if "residue" in raw or "日文残留" in raw:
        return "residue"
    if "security_audit_fail" in raw or "content_moderation" in raw or "moderation" in raw or "内容审核" in raw or "违规" in raw:
        return "security"
    if "timeout" in raw or "超时" in raw:
        return "timeout"
    if "json" in raw or "format" in raw or "格式" in raw or "parse" in raw:
        return "format"
    if status_code == 429 or "rate" in raw or "限流" in raw:
        return "rate_limit"
    if str(outcome or "").lower() == "ok" and (status_code is None or 200 <= int(status_code) < 300):
        return "ok"
    return "failed"


def _iter_log_files() -> Iterable[Path]:
    return sorted(request_log_dir().glob("request-log-*.jsonl"), reverse=True)


def _prune_files() -> None:
    files = list(_iter_log_files())
    for path in files[_MAX_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass


def _prune_current_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) <= _MAX_LINES_PER_FILE:
        return
    keep = lines[-_MAX_LINES_PER_FILE:]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_event(**fields: Any) -> Dict[str, Any]:
    """Append one structured diagnostic event. Never raises to callers."""
    now = time.time()
    entry: Dict[str, Any] = {
        "id": f"{int(now * 1000)}-{threading.get_ident()}",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "epoch_ms": int(now * 1000),
        "context": compact_text(fields.get("context"), 120),
        "provider": compact_text(fields.get("provider"), 80),
        "model": compact_text(fields.get("model"), 120),
        "url": compact_text(fields.get("url"), 240),
        "status_code": fields.get("status_code"),
        "outcome": compact_text(fields.get("outcome"), 80),
        "elapsed_ms": int(fields.get("elapsed_ms") or 0),
        "attempt": fields.get("attempt"),
        "max_retries": fields.get("max_retries"),
        "batch_size": fields.get("batch_size"),
        "token_total": int(fields.get("token_total") or 0),
        "prompt_summary": compact_text(fields.get("prompt_summary"), 700),
        "source_summary": compact_text(fields.get("source_text"), 900),
        "response_summary": compact_text(fields.get("response_text"), 900),
        "error": compact_text(fields.get("error"), 700),
    }
    entry["category"] = classify(
        outcome=entry.get("outcome", ""),
        status_code=entry.get("status_code"),
        error=entry.get("error", ""),
        category=fields.get("category") or "",
    )
    if not entry["token_total"]:
        entry["token_total"] = estimate_tokens(
            entry.get("prompt_summary"),
            entry.get("source_summary"),
            entry.get("response_summary"),
        )

    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("EPUB_TRANSLATOR_TEST_REQUEST_LOG"):
        return entry

    try:
        with _LOCK:
            path = current_log_path()
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
            _prune_current_file(path)
            _prune_files()
    except Exception:
        pass
    return entry


def read_recent(limit: int = 300, category: str = "", query: str = "") -> List[Dict[str, Any]]:
    limit = max(20, min(int(limit or 300), 2000))
    category = str(category or "").strip().lower()
    query = str(query or "").strip().lower()
    out: List[Dict[str, Any]] = []
    with _LOCK:
        for path in _iter_log_files():
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if category and category != "all" and str(entry.get("category", "")).lower() != category:
                    continue
                if query:
                    haystack = " ".join(
                        str(entry.get(key, ""))
                        for key in (
                            "context",
                            "provider",
                            "model",
                            "url",
                            "outcome",
                            "prompt_summary",
                            "source_summary",
                            "response_summary",
                            "error",
                            "category",
                        )
                    ).lower()
                    if query not in haystack:
                        continue
                out.append(entry)
                if len(out) >= limit:
                    return out
    return out


def clear_logs() -> int:
    removed = 0
    with _LOCK:
        for path in list(_iter_log_files()):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed
