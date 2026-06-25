# -*- coding: utf-8 -*-
"""
术语表桥接器：QAbstractListModel 暴露给 QML TableView，支持增删改查、筛选、导入导出。
"""

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Tuple

from PySide6.QtCore import (
    QAbstractListModel, QModelIndex, Qt, QObject, Signal, Slot, Property, QThread,
)

logger = logging.getLogger(__name__)

from backend.toast_bridge import ToastBridge

GLOSSARY_CATEGORIES = ["Person", "Location", "Org", "Item", "Skill", "Creature"]


def _translator_cls():
    from translator import JaZhTranslator

    return JaZhTranslator


def _data_dir() -> Path:
    from translator import get_data_dir

    return get_data_dir()

# Model roles
ROLE_CATEGORY = Qt.UserRole + 1
ROLE_ORIGINAL = Qt.UserRole + 2
ROLE_TRANSLATION = Qt.UserRole + 3
ROLE_NOTE = Qt.UserRole + 4
ROLE_SOURCE_INDEX = Qt.UserRole + 5
ROLE_POLICY = Qt.UserRole + 6


class GlossaryModel(QAbstractListModel):
    """术语表数据模型，暴露 4 列给 QML TableView。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_rows: List[Dict[str, str]] = []
        self._filtered: List[Tuple[int, Dict[str, str]]] = []
        self._dirty = False
        self._query = ""
        self._category_filter = "全部分类"
        self._source_filter = "全部来源"

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._filtered)

    def roleNames(self):
        return {
            ROLE_CATEGORY: b"category",
            ROLE_ORIGINAL: b"original",
            ROLE_TRANSLATION: b"translation",
            ROLE_NOTE: b"note",
            ROLE_SOURCE_INDEX: b"sourceIndex",
            ROLE_POLICY: b"policy",
        }

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._filtered):
            return None
        _, row = self._filtered[index.row()]
        if role == ROLE_CATEGORY:
            return row.get("category", "")
        if role == ROLE_ORIGINAL:
            return row.get("original", "")
        if role == ROLE_TRANSLATION:
            return row.get("translation", "")
        if role == ROLE_NOTE:
            return row.get("note", "")
        if role == ROLE_SOURCE_INDEX:
            return self._filtered[index.row()][0]
        if role == ROLE_POLICY:
            return self._policy_label(row.get("policy", ""))
        if role == Qt.DisplayRole:
            return row.get("original", "")
        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or index.row() >= len(self._filtered):
            return False
        src_idx = self._filtered[index.row()][0]
        if src_idx < 0 or src_idx >= len(self._all_rows):
            return False
        row = dict(self._all_rows[src_idx])
        if role == ROLE_CATEGORY:
            row["category"] = str(value).strip() or "Item"
        elif role == ROLE_ORIGINAL:
            row["original"] = str(value)
        elif role == ROLE_TRANSLATION:
            row["translation"] = str(value)
        elif role == ROLE_NOTE:
            info, source = self._parse_note_source(str(value))
            row["info"] = info
            row["source"] = source
            row["note"] = self._make_note(info, source)
        elif role == ROLE_POLICY:
            row["policy"] = self._policy_value(str(value))
        else:
            return False
        self._all_rows[src_idx] = row
        self._filtered[index.row()] = (src_idx, self._all_rows[src_idx])
        self._dirty = True
        self.dataChanged.emit(index, index, [role])
        return True

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    # --- data management ---
    @staticmethod
    def _source_label(source: str) -> str:
        source = str(source or "").strip()
        if source == "auto":
            return "自动提取"
        if source == "manual":
            return "手动添加"
        if source:
            return f"来源：{source}"
        return "未知来源"

    @staticmethod
    def _policy_value(value: str) -> str:
        value = str(value or "").strip().lower()
        if value in {"force", "forced", "强制", "强制使用"}:
            return "force"
        if value in {"reference", "ref", "weak", "参考", "仅供参考"}:
            return "reference"
        if value in {"ignore", "ignored", "忽略", "忽略校对"}:
            return "ignore"
        return ""

    @classmethod
    def _policy_label(cls, policy: str) -> str:
        policy = cls._policy_value(policy)
        if policy == "force":
            return "强制使用"
        if policy == "reference":
            return "仅供参考"
        if policy == "ignore":
            return "忽略校对"
        return "默认策略"

    @classmethod
    def _make_note(cls, info: str = "", source: str = "") -> str:
        parts = []
        info = str(info or "").strip()
        if info:
            parts.append(info)
        parts.append(cls._source_label(source))
        return "；".join(parts)

    @classmethod
    def _make_row(
        cls,
        category: str,
        original: str,
        translation: str,
        info: str = "",
        source: str = "",
        policy: str = "",
    ) -> Dict[str, str]:
        return {
            "category": str(category or "Item").strip() or "Item",
            "original": str(original or ""),
            "translation": str(translation or ""),
            "info": str(info or "").strip(),
            "source": str(source or "").strip(),
            "policy": cls._policy_value(policy),
            "note": cls._make_note(info, source),
        }

    @staticmethod
    def _parse_note_source(value: str) -> Tuple[str, str]:
        parts = [part.strip() for part in re.split(r"[;；]", value or "") if part.strip()]
        info_parts = []
        source = ""
        for part in parts:
            lower_part = part.lower()
            if part == "自动提取":
                source = "auto"
            elif part == "手动添加":
                source = "manual"
            elif part == "未知来源":
                source = ""
            elif lower_part.startswith("source="):
                source = part.split("=", 1)[1].strip()
            elif part.startswith("来源：") or part.startswith("来源:"):
                source = re.split(r"[:：]", part, maxsplit=1)[1].strip()
            else:
                info_parts.append(part)
        return "；".join(info_parts), source

    @classmethod
    def _row_to_payload_entry(cls, row: Dict[str, str]):
        category = str(row.get("category", "Item")).strip() or "Item"
        original = str(row.get("original", "")).strip()
        translation = str(row.get("translation", "")).strip()
        if not original or not translation:
            return category, None
        if category not in GLOSSARY_CATEGORIES:
            category = "Item"

        info = str(row.get("info", "")).strip()
        source = str(row.get("source", "")).strip()
        if (not info and not source) and row.get("note"):
            info, source = cls._parse_note_source(row.get("note", ""))

        entry = {"original": original, "translation": translation}
        if info:
            entry["info"] = info
        if source:
            entry["source"] = source
        policy = cls._policy_value(row.get("policy", ""))
        if policy:
            entry["policy"] = policy
        return category, entry

    def load_from_disk(self):
        translator_cls = _translator_cls()
        path = _data_dir() / "glossary.json"
        if not path.exists():
            self._all_rows = []
            self._apply_filter()
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载术语表失败: {e}")
            self._all_rows = []
            self._apply_filter()
            return 0
        normalized, _ = translator_cls.normalize_glossary_payload(data if isinstance(data, dict) else {})
        rows = []
        for category in GLOSSARY_CATEGORIES:
            for entry in normalized.get(category, []):
                original = str(entry.get("original", "")).strip()
                translation = str(entry.get("translation", "")).strip()
                info = str(entry.get("info", "")).strip()
                source = str(entry.get("source", "")).strip()
                policy = str(entry.get("policy", entry.get("enforcement", ""))).strip()
                if original and translation:
                    rows.append(self._make_row(category, original, translation, info, source, policy))
        self._all_rows = rows
        self._dirty = False
        self._apply_filter()
        return len(rows)

    def save_to_disk(self):
        translator_cls = _translator_cls()
        payload = {}
        for row in self._all_rows:
            cat, entry = self._row_to_payload_entry(row)
            if entry is None:
                continue
            if cat not in payload:
                payload[cat] = []
            payload[cat].append(entry)
        path = _data_dir() / "glossary.json"
        normalized, _ = translator_cls.normalize_glossary_payload(payload)
        translator_cls._atomic_write_json(path, normalized)
        self._dirty = False
        return len(self._all_rows)

    @property
    def dirty(self):
        return self._dirty

    @property
    def total_count(self):
        return len(self._all_rows)

    @property
    def filtered_count(self):
        return len(self._filtered)

    def source_stats(self):
        auto_count = 0
        manual_count = 0
        unknown_count = 0
        for row in self._all_rows:
            source = str(row.get("source", "") or "").strip().lower()
            note = str(row.get("note", "") or "")
            if source == "auto" or "自动提取" in note:
                auto_count += 1
            elif source == "manual" or "手动添加" in note:
                manual_count += 1
            else:
                unknown_count += 1
        return {
            "total": len(self._all_rows),
            "filtered": len(self._filtered),
            "auto": auto_count,
            "manual": manual_count,
            "unknown": unknown_count,
        }

    def add_row(self, category="Item"):
        self._all_rows.append(self._make_row(category, "", "", "", "manual", "force"))
        self._dirty = True
        self._apply_filter()

    def delete_rows(self, rows_to_delete: List[int]):
        """删除指定 filtered 索引对应的行。"""
        src_indices = set()
        for idx in sorted(rows_to_delete, reverse=True):
            if 0 <= idx < len(self._filtered):
                src_idx = self._filtered[idx][0]
                src_indices.add(src_idx)
        if not src_indices:
            return 0
        # Keep rows whose index is not in src_indices
        self._all_rows = [r for i, r in enumerate(self._all_rows) if i not in src_indices]
        self._dirty = True
        self._apply_filter()
        return len(src_indices)

    def import_json(self, path_str: str):
        try:
            translator_cls = _translator_cls()
            with open(path_str, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("术语表 JSON 顶层必须是对象")
            normalized, import_stats = translator_cls.normalize_glossary_payload(payload)
            glossary_path = _data_dir() / "glossary.json"
            existing = {}
            if glossary_path.exists():
                existing = json.loads(glossary_path.read_text(encoding="utf-8"))
            existing_normalized, _ = translator_cls.normalize_glossary_payload(existing if isinstance(existing, dict) else {})
            if existing_normalized:
                merged, merge_stats = translator_cls.merge_glossaries(existing_normalized, normalized)
            else:
                merged = normalized
                merge_stats = {"added": import_stats.get("accepted", 0), "skipped": import_stats.get("skipped", 0), "conflicts": import_stats.get("conflicts", 0)}
            # Backup before overwriting
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = _data_dir() / f"glossary.backup.before_import.{timestamp}.json"
            if glossary_path.exists():
                shutil.copy2(glossary_path, backup_path)
            translator_cls._atomic_write_json(glossary_path, merged)
            self.load_from_disk()
            return {
                "added": int(merge_stats.get("added", 0)),
                "skipped": int(merge_stats.get("skipped", 0)),
                "conflicts": int(merge_stats.get("conflicts", 0)),
                "total": len(self._all_rows),
            }
        except Exception as e:
            raise ValueError(str(e))

    def export_json(self, path_str: str):
        translator_cls = _translator_cls()
        payload = {}
        for row in self._all_rows:
            cat, entry = self._row_to_payload_entry(row)
            if entry is None:
                continue
            if cat not in payload:
                payload[cat] = []
            payload[cat].append(entry)
        normalized, _ = translator_cls.normalize_glossary_payload(payload)
        Path(path_str).write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
        return len(self._all_rows)

    def restore_backup(self, path_str: str):
        try:
            translator_cls = _translator_cls()
            with open(path_str, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("备份 JSON 顶层必须是对象")
            glossary_path = _data_dir() / "glossary.json"
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = _data_dir() / f"glossary.backup.before_restore.{timestamp}.json"
            if glossary_path.exists():
                shutil.copy2(glossary_path, backup_path)
            translator_cls._atomic_write_json(glossary_path, payload)
            self.load_from_disk()
            return len(self._all_rows)
        except Exception as e:
            raise ValueError(str(e))

    def search(self, query: str, category_filter: str, source_filter: str):
        self._query = query.strip().lower()
        self._category_filter = category_filter
        self._source_filter = source_filter
        self._apply_filter()

    def _apply_filter(self):
        old_count = len(self._filtered)
        filtered = []
        for row_idx, row in enumerate(self._all_rows):
            cat = row.get("category", "")
            note = row.get("note", "")
            if self._category_filter != "全部分类" and cat != self._category_filter:
                continue
            if self._source_filter != "全部来源" and self._source_filter not in note:
                continue
            searchable = " ".join(
                str(row.get(key, ""))
                for key in ("category", "original", "translation", "note", "info", "source", "policy")
            )
            searchable = f"{searchable} {self._policy_label(row.get('policy', ''))}".lower()
            if self._query and self._query not in searchable:
                continue
            filtered.append((row_idx, row))
        self.beginResetModel()
        self._filtered = filtered
        self.endResetModel()


class GlossaryBridge(QObject):
    """QML 术语表桥接器。"""

    loaded = Signal(int)   # total count
    saved = Signal(int)
    importDone = Signal(int, int, int, int)  # added, skipped, conflicts, total
    exportDone = Signal(str, int)
    restoreDone = Signal(int)
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = GlossaryModel(self)

    @Property(QObject, constant=True)
    def model(self):
        return self._model

    @Slot()
    def load(self):
        try:
            count = self._model.load_from_disk()
            self.loaded.emit(count)
        except Exception as e:
            self.errorOccurred.emit(f"加载术语表失败: {e}")

    @Slot()
    def save(self):
        try:
            count = self._model.save_to_disk()
            self.saved.emit(count)
            ToastBridge.success(f"术语表已保存 ({count} 条)")
        except Exception as e:
            self.errorOccurred.emit(f"保存术语表失败: {e}")
            ToastBridge.error("保存术语表失败")

    @Slot(str)
    def addRow(self, category: str = "Item"):
        self._model.add_row(category)

    @Slot("QVariantList")
    def deleteRows(self, rows):
        """rows: list of filtered row indices."""
        count = self._model.delete_rows([int(r) for r in rows])
        if count == 0:
            self.errorOccurred.emit("未选中任何术语")

    @Slot(str)
    def importJson(self, path_str: str):
        try:
            result = self._model.import_json(path_str)
            self.importDone.emit(result["added"], result["skipped"], result["conflicts"], result["total"])
            ToastBridge.success(f"导入完成: 新增 {result['added']} 条, 跳过 {result['skipped']} 条")
        except Exception as e:
            self.errorOccurred.emit(f"导入失败: {e}")
            ToastBridge.error("术语表导入失败")

    @Slot(str)
    def exportJson(self, path_str: str):
        try:
            count = self._model.export_json(path_str)
            self.exportDone.emit(path_str, count)
            ToastBridge.success(f"术语表已导出 ({count} 条)")
        except Exception as e:
            self.errorOccurred.emit(f"导出失败: {e}")
            ToastBridge.error("术语表导出失败")

    @Slot(str)
    def restoreBackup(self, path_str: str):
        try:
            count = self._model.restore_backup(path_str)
            self.restoreDone.emit(count)
            ToastBridge.success(f"备份已恢复 ({count} 条)")
        except Exception as e:
            self.errorOccurred.emit(f"恢复备份失败: {e}")
            ToastBridge.error("恢复备份失败")

    @Slot(str, str, str)
    def search(self, query: str, category_filter: str, source_filter: str):
        self._model.search(query, category_filter, source_filter)

    @Slot(result="QVariantMap")
    def getStats(self):
        return self._model.source_stats()
