# -*- coding: utf-8 -*-
"""Persistent translation task history for QML/V4.

This is intentionally small: it records enough state for restart diagnostics
and later UI resume/history features without taking over the translation
pipeline.
"""

from __future__ import annotations

import json
import hashlib
import copy
import logging
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


HISTORY_FILE_NAME = "translation_task_history.json"
DEFAULT_HISTORY_LIMIT = 80
DEFAULT_FAILURE_BLOCK_LIMIT = 200
MAX_PERSISTED_TEXT_CHARS = 4000
DETAILED_TASK_STATUSES = {
    "running",
    "pausing",
    "paused",
    "cancelling",
    "stopping",
    "failed",
    "partial",
}
SENSITIVE_CONFIG_KEYS = {
    "api_key",
    "proofread_api_key",
    "recovery_fallback_api_key",
}


logger = logging.getLogger(__name__)


def data_dir() -> Path:
    path = Path.home() / ".epub_translator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_path() -> Path:
    return data_dir() / HISTORY_FILE_NAME


def now_ts() -> int:
    return int(time.time())


def make_task_id() -> str:
    return time.strftime("translation-%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


def text_hash(text: Any) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8", errors="ignore")).hexdigest()


def sanitize_config(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep useful task settings while never persisting API keys."""

    result: Dict[str, Any] = {}
    for key, value in dict(config or {}).items():
        if key in SENSITIVE_CONFIG_KEYS:
            result[key] = ""
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, (list, tuple)):
            cleaned = [
                str(item)
                for item in value
                if isinstance(item, (str, int, float)) and str(item).strip()
            ]
            if cleaned:
                result[key] = cleaned
    return result


def _compact_text(value: Any, limit: int = 2000) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


@dataclass
class SubtaskRecord:
    index: int
    source: str
    source_hash: str
    status: str = "pending"
    translation: str = ""
    reason: str = ""
    chars: int = 0
    updated_at: int = 0


@dataclass
class TaskRecord:
    task_id: str
    kind: str = "translation"
    status: str = "running"
    created_at: int = 0
    updated_at: int = 0
    started_at: int = 0
    finished_at: int = 0
    input_path: str = ""
    output_path: str = ""
    provider: str = ""
    model: str = ""
    max_workers: int = 0
    batch_size: int = 0
    total_texts: int = 0
    completed_texts: int = 0
    failed_texts: int = 0
    total_chars: int = 0
    progress: float = 0.0
    config: Dict[str, Any] = None
    subtasks: List[Dict[str, Any]] = None
    failure_summary: Dict[str, Any] = None
    failed_blocks: List[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value not in (None, [], {})}


def build_subtask_records(texts: List[Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for index, text in enumerate(list(texts or [])):
        source = _compact_text(text, MAX_PERSISTED_TEXT_CHARS)
        records.append(
            asdict(
                SubtaskRecord(
                    index=index,
                    source=source,
                    source_hash=text_hash(text),
                    chars=len(str(text or "")),
                )
            )
        )
    return records


def _normalize_fragments(value: Any) -> List[str]:
    if isinstance(value, str):
        fragments = [value]
    elif isinstance(value, list):
        fragments = value
    else:
        fragments = []
    cleaned = [_compact_text(fragment, 120) for fragment in fragments]
    return list(dict.fromkeys(fragment for fragment in cleaned if fragment))


def _parse_residue_sample(sample: Any) -> Dict[str, Any]:
    text = str(sample or "").strip()
    fragments: List[str] = []
    body = text
    if text.startswith("fragment: ") and " | text: " in text:
        fragment_part, body = text.split(" | text: ", 1)
        fragment_part = fragment_part.replace("fragment: ", "", 1).strip()
        fragments = [part.strip() for part in fragment_part.split("/") if part.strip()]
    return {
        "text": _compact_text(body),
        "translation": _compact_text(body),
        "fragments": _normalize_fragments(fragments),
    }


def normalize_failed_blocks(
    failed_details: Optional[List[Mapping[str, Any]]] = None,
    residue_details: Optional[List[Mapping[str, Any]]] = None,
    residue_samples: Optional[List[Any]] = None,
    max_items: int = DEFAULT_FAILURE_BLOCK_LIMIT,
) -> List[Dict[str, Any]]:
    """Normalize failed/residue diagnostics for persistent UI display."""

    max_items = max(1, int(max_items or DEFAULT_FAILURE_BLOCK_LIMIT))
    blocks: List[Dict[str, Any]] = []
    seen = set()

    def add_block(kind: str, text: Any, reason: Any, translation: Any = "", fragments: Any = None) -> None:
        if len(blocks) >= max_items:
            return
        normalized_text = _compact_text(text)
        normalized_translation = _compact_text(translation)
        if not normalized_text and not normalized_translation:
            return
        key = (kind, normalized_text, normalized_translation)
        if key in seen:
            return
        seen.add(key)
        blocks.append(
            {
                "kind": kind,
                "text": normalized_text,
                "reason": _compact_text(reason, 300),
                "translation": normalized_translation,
                "fragments": _normalize_fragments(fragments),
            }
        )

    for item in failed_details or []:
        if not isinstance(item, Mapping):
            continue
        add_block(
            "failed",
            item.get("text") or item.get("original") or "",
            item.get("reason") or "未返回安全译文",
            item.get("translation") or item.get("translated") or "",
            item.get("fragments") or [],
        )

    for item in residue_details or []:
        if not isinstance(item, Mapping):
            continue
        add_block(
            "residue",
            item.get("original") or item.get("text") or "",
            item.get("reason") or "译文疑似仍有日文残留",
            item.get("translated") or item.get("translation") or "",
            item.get("fragments") or [],
        )

    for sample in residue_samples or []:
        parsed = _parse_residue_sample(sample)
        add_block(
            "save_residue",
            parsed["text"],
            "保存前检查发现高风险日文残留",
            parsed["translation"],
            parsed["fragments"],
        )

    return blocks


class TranslationTaskHistoryStore:
    """Append/update a bounded JSON task history."""

    def __init__(self, path: Optional[Path] = None, limit: int = DEFAULT_HISTORY_LIMIT):
        self.path = path or history_path()
        self.limit = max(1, int(limit or DEFAULT_HISTORY_LIMIT))
        self._lock = threading.RLock()
        self._records_cache: Optional[List[Dict[str, Any]]] = None
        self._cache_mtime_ns: Optional[int] = None

    @staticmethod
    def _compact_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        compacted = copy.deepcopy(list(records or []))
        for record in compacted:
            if not isinstance(record, dict):
                continue
            if str(record.get("status") or "").strip().lower() in DETAILED_TASK_STATUSES:
                continue
            subtasks = record.pop("subtasks", None)
            if isinstance(subtasks, list):
                record["subtask_count"] = len(subtasks)
            record.pop("failed_blocks", None)
        return compacted

    def load(self) -> List[Dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                self._records_cache = []
                self._cache_mtime_ns = None
                return []
            try:
                mtime_ns = self.path.stat().st_mtime_ns
            except OSError:
                mtime_ns = None
            if self._records_cache is not None and self._cache_mtime_ns == mtime_ns:
                return copy.deepcopy(self._records_cache)
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
            except Exception:
                return []
            if isinstance(payload, dict):
                records = payload.get("tasks", [])
            else:
                records = payload
            if not isinstance(records, list):
                return []
            normalized: List[Dict[str, Any]] = []
            for record in records:
                if isinstance(record, dict) and record.get("task_id"):
                    normalized.append(dict(record))
            normalized = normalized[-self.limit :]
            self._records_cache = copy.deepcopy(normalized)
            self._cache_mtime_ns = mtime_ns
            return copy.deepcopy(normalized)

    def save(self, records: List[Dict[str, Any]]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            trimmed = self._compact_records(list(records or [])[-self.limit :])
            payload = {
                "version": 2,
                "updated_at": now_ts(),
                "tasks": trimmed,
            }
            try:
                previous_size = self.path.stat().st_size
            except OSError:
                previous_size = 0
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp.replace(self.path)
            try:
                current_stat = self.path.stat()
                current_size = current_stat.st_size
                self._cache_mtime_ns = current_stat.st_mtime_ns
            except OSError:
                current_size = 0
                self._cache_mtime_ns = None
            self._records_cache = copy.deepcopy(trimmed)
            if previous_size >= 5 * 1024 * 1024 and current_size < previous_size * 0.8:
                logger.info(
                    "翻译任务历史已压缩: %.1f MB -> %.1f MB",
                    previous_size / (1024 * 1024),
                    current_size / (1024 * 1024),
                )

    def _find_or_create(self, records: List[Dict[str, Any]], task_id: str) -> Dict[str, Any]:
        for record in records:
            if record.get("task_id") == task_id:
                return record
        record = TaskRecord(task_id=task_id, created_at=now_ts(), updated_at=now_ts()).to_dict()
        records.append(record)
        return record

    @staticmethod
    def _recompute_summary(record: Dict[str, Any]) -> None:
        subtasks = record.get("subtasks", [])
        if not isinstance(subtasks, list):
            subtasks = []
            record["subtasks"] = subtasks
        total = len(subtasks)
        completed = sum(1 for item in subtasks if isinstance(item, dict) and item.get("status") == "success")
        failed = sum(1 for item in subtasks if isinstance(item, dict) and item.get("status") in {"failed", "residue", "save_residue"})
        total_chars = sum(int(item.get("chars") or 0) for item in subtasks if isinstance(item, dict))
        record["total_texts"] = total or int(record.get("total_texts") or 0)
        record["completed_texts"] = completed
        record["failed_texts"] = failed
        record["total_chars"] = total_chars or int(record.get("total_chars") or 0)
        record["progress"] = round(float(completed) / float(total), 4) if total > 0 else float(record.get("progress") or 0.0)

    def upsert(self, task_id: str, changes: Mapping[str, Any]) -> Dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        with self._lock:
            records = self.load()
            existing = self._find_or_create(records, task_id)
            for key, value in dict(changes or {}).items():
                if key in SENSITIVE_CONFIG_KEYS:
                    continue
                existing[key] = value
            existing["updated_at"] = now_ts()
            self.save(records)
            return dict(existing)

    def initialize_subtasks(self, task_id: str, texts: List[Any], preserve_existing: bool = True) -> Dict[str, Any]:
        task_id = str(task_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        subtasks = build_subtask_records(list(texts or []))
        with self._lock:
            records = self.load()
            record = self._find_or_create(records, task_id)
            if preserve_existing:
                existing_by_key = {}
                for item in record.get("subtasks", []) or []:
                    if not isinstance(item, dict):
                        continue
                    key = (int(item.get("index") or -1), item.get("source_hash"))
                    existing_by_key[key] = item
                merged = []
                for item in subtasks:
                    key = (int(item.get("index") or -1), item.get("source_hash"))
                    old = existing_by_key.get(key)
                    if old and old.get("status") in {"success", "failed", "residue", "save_residue"}:
                        merged.append({**item, **old})
                    else:
                        merged.append(item)
                subtasks = merged
            record["subtasks"] = subtasks
            record["subtask_schema"] = 1
            self._recompute_summary(record)
            record["updated_at"] = now_ts()
            self.save(records)
            return dict(record)

    def mark_subtask_success(self, task_id: str, source: Any, translation: Any) -> Dict[str, Any]:
        return self.mark_subtasks_success(task_id, {source: translation})

    def mark_subtasks_success(self, task_id: str, translations: Mapping[Any, Any]) -> Dict[str, Any]:
        cleaned = {
            text_hash(source): _compact_text(dst, MAX_PERSISTED_TEXT_CHARS)
            for source, dst in dict(translations or {}).items()
            if str(source or "").strip() and str(dst or "").strip()
        }
        if not cleaned:
            return {"changed": 0, "record": {}}

        now = now_ts()
        with self._lock:
            records = self.load()
            record = self._find_or_create(records, task_id)
            changed = 0
            for item in record.get("subtasks", []) or []:
                if not isinstance(item, dict):
                    continue
                translated = cleaned.get(item.get("source_hash"))
                if translated is None:
                    continue
                if item.get("status") == "success" and item.get("translation"):
                    continue
                item["status"] = "success"
                item["translation"] = translated
                item["reason"] = ""
                item["updated_at"] = now
                changed += 1
            if changed:
                self._recompute_summary(record)
                record["updated_at"] = now
                self.save(records)
            return {"changed": changed, "record": dict(record)}

    def mark_blocks_success(self, task_id: str, translations: Mapping[str, Any]) -> Dict[str, Any]:
        """Mark failed/residue subtasks as fixed and remove matching failure blocks."""

        cleaned = {
            text_hash(source): _compact_text(dst, MAX_PERSISTED_TEXT_CHARS)
            for source, dst in dict(translations or {}).items()
            if str(source or "").strip() and str(dst or "").strip()
        }
        if not cleaned:
            return {"changed": 0, "remaining_blocks": 0, "record": {}}

        now = now_ts()
        with self._lock:
            records = self.load()
            record = self._find_or_create(records, task_id)
            changed = 0

            for item in record.get("subtasks", []) or []:
                if not isinstance(item, dict):
                    continue
                translated = cleaned.get(item.get("source_hash"))
                if translated is None:
                    continue
                item["status"] = "success"
                item["translation"] = translated
                item["reason"] = ""
                item["updated_at"] = now
                changed += 1

            remaining_blocks = []
            for block in record.get("failed_blocks", []) or []:
                if not isinstance(block, Mapping):
                    continue
                source = block.get("text") or ""
                if text_hash(source) in cleaned:
                    continue
                remaining_blocks.append(dict(block))
            record["failed_blocks"] = remaining_blocks

            summary = dict(record.get("failure_summary") or {})
            summary["block_count"] = len(remaining_blocks)
            summary["retranslated_count"] = int(summary.get("retranslated_count") or 0) + len(cleaned)
            if not remaining_blocks:
                summary["failed_count"] = 0
                summary["residue_count"] = 0
            record["failure_summary"] = summary

            self._recompute_summary(record)
            record["updated_at"] = now
            self.save(records)
            return {
                "changed": changed,
                "remaining_blocks": len(remaining_blocks),
                "record": dict(record),
            }

    def record_recovery_results(self, task_id: str, results: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        """Persist bounded recovery metadata for failed blocks and subtasks."""

        normalized = {
            text_hash(source): {
                "recovery_attempts": max(0, int((result or {}).get("attempts") or 0)),
                "recovery_action": _compact_text((result or {}).get("action") or "", 80),
                "recovery_status": _compact_text((result or {}).get("status") or "", 80),
                "recovery_reason": _compact_text((result or {}).get("reason") or "", 300),
            }
            for source, result in dict(results or {}).items()
            if str(source or "").strip() and isinstance(result, Mapping)
        }
        if not normalized:
            return {"changed": 0, "record": {}}

        with self._lock:
            records = self.load()
            record = self._find_or_create(records, task_id)
            changed = 0
            for collection_name in ("failed_blocks", "subtasks"):
                for item in record.get(collection_name, []) or []:
                    if not isinstance(item, dict):
                        continue
                    source = item.get("text") if collection_name == "failed_blocks" else item.get("source")
                    metadata = normalized.get(text_hash(source))
                    if not metadata:
                        continue
                    item.update(metadata)
                    changed += 1
            if changed:
                record["updated_at"] = now_ts()
                self.save(records)
            return {"changed": changed, "record": dict(record)}

    def mark_subtasks_problem(self, task_id: str, blocks: List[Mapping[str, Any]]) -> Dict[str, Any]:
        now = now_ts()
        with self._lock:
            records = self.load()
            record = self._find_or_create(records, task_id)
            changed = 0
            by_hash = {}
            for block in blocks or []:
                if not isinstance(block, Mapping):
                    continue
                source = block.get("text") or ""
                if source:
                    by_hash[text_hash(source)] = block
            if by_hash:
                for item in record.get("subtasks", []) or []:
                    if not isinstance(item, dict):
                        continue
                    block = by_hash.get(item.get("source_hash"))
                    if not block:
                        continue
                    item["status"] = str(block.get("kind") or "failed")
                    item["reason"] = _compact_text(block.get("reason") or "", 300)
                    if block.get("translation"):
                        item["translation"] = _compact_text(block.get("translation"), MAX_PERSISTED_TEXT_CHARS)
                    item["updated_at"] = now
                    changed += 1
            if changed:
                self._recompute_summary(record)
                record["updated_at"] = now
                self.save(records)
            return {"changed": changed, "record": dict(record)}

    def latest_unfinished(self) -> Dict[str, Any]:
        unfinished = {
            "running",
            "pausing",
            "paused",
            "failed",
            "partial",
        }
        records = self.load()
        for record in reversed(records):
            if str(record.get("status") or "") in unfinished:
                return self._summary_record(record)
        return {}

    def latest(self) -> Dict[str, Any]:
        records = self.load()
        return dict(records[-1]) if records else {}

    @staticmethod
    def _summary_record(record: Mapping[str, Any]) -> Dict[str, Any]:
        result = dict(record or {})
        had_subtasks = "subtasks" in result
        subtasks = result.pop("subtasks", None)
        if had_subtasks and isinstance(subtasks, list):
            result["subtask_count"] = len(subtasks)
        else:
            result.setdefault("subtask_count", int(result.get("total_texts") or 0))
        return result

    def list_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, int(limit or 20))
        return [self._summary_record(record) for record in self.load()[-limit:]][::-1]

    def clear(self) -> int:
        records = self.load()
        count = len(records)
        self.save([])
        return count
