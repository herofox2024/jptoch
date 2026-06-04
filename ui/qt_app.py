import os
import re
import subprocess
import threading
import time
import traceback
import json
import shutil
import zipfile
from dataclasses import dataclass
from typing import Optional, Tuple
from pathlib import Path

import requests
from bs4 import NavigableString
from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt5.QtGui import QFont, QGuiApplication, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QRadioButton,
    QAbstractItemView,
    QHeaderView,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SegmentedWidget,
    Slider,
    StrongBodyLabel,
    Theme,
    setTheme,
)
from qfluentwidgets.components.widgets.combo_box import ComboBoxMenu

from epub_io import (
    apply_toc_translations,
    extract_toc_titles,
    iter_text_nodes,
    load_book,
    save_book,
)
from translator import JaZhTranslator, PERFORMANCE_PRESETS, get_data_dir
from text_utils import is_translatable

CANCELLED_RESULT = "__CANCELLED__"

try:
    import ctypes
except Exception:
    ctypes = None


GLOSSARY_CATEGORIES = ["Person", "Location", "Org", "Item", "Skill", "Creature"]

PERF_UI_PRESETS = {
    "glm_free": {
        "label": "智谱免费版",
        "values": {
            "max_workers": 1,
            "batch_size": 2,
            "max_batch_length": 200,
            "max_text_size_for_batch": 200,
            "api_timeout": 300,
        },
        "hint": "智谱免费版建议低并发、低批量，降低 429/限流概率。",
    },
    "gemini_free": {
        "label": "Gemini 免费版",
        "values": {
            "max_workers": 1,
            "batch_size": 2,
            "max_batch_length": 200,
            "max_text_size_for_batch": 200,
            "api_timeout": 300,
        },
        "hint": "Gemini 免费版也容易限流，建议使用和智谱免费版接近的保守参数。",
    },
    "deepseek_paid": {
        "label": "DeepSeek 付费版",
        "values": {
            "max_workers": 12,
            "batch_size": 10,
            "max_batch_length": 4000,
            "max_text_size_for_batch": 1000,
            "api_timeout": 120,
        },
        "hint": "DeepSeek 付费版可使用较高并发和批量，速度和质量都更稳定。",
    },
}


def format_glossary_source_label(source: str) -> str:
    source = str(source or "").strip()
    if not source:
        return "未知来源"
    if source == "auto":
        return "自动提取"
    if source == "manual":
        return "手动添加"
    return f"来源：{source}"


def load_glossary_rows(glossary_path: Path):
    if not glossary_path.exists():
        return []

    payload = JaZhTranslator._load_json(str(glossary_path), {})
    normalized, _ = JaZhTranslator.normalize_glossary_payload(payload if isinstance(payload, dict) else {})
    rows = []
    for category in GLOSSARY_CATEGORIES:
        for entry in normalized.get(category, []):
            original = str(entry.get("original", "")).strip()
            translation = str(entry.get("translation", "")).strip()
            info_parts = []
            if entry.get("info"):
                info_parts.append(str(entry.get("info")).strip())
            info_parts.append(format_glossary_source_label(str(entry.get("source", "")).strip()))
            if original and translation:
                rows.append((category, original, translation, "；".join(info_parts)))
    return rows


class ScaledComboBoxMenu(ComboBoxMenu):
    def __init__(self, parent=None, font_pt: int = 9):
        super().__init__(parent=parent)
        self._font_pt = max(9, int(font_pt))
        self._font = QFont(parent.font() if parent is not None else self.font())
        self._font.setPointSize(self._font_pt)
        self._apply_font()

    def _apply_font(self):
        font = self._font
        self.setFont(font)
        self.view.setFont(font)
        self.view.viewport().setFont(font)
        self.view.setStyleSheet(f"MenuActionListWidget{{ font-size: {self._font_pt}pt; }}")
        self.setItemHeight(max(33, int(round(self._font_pt * 3.4))))

    def _createActionItem(self, action, before=None):
        item = super()._createActionItem(action, before)
        item.setFont(self._font)
        self._adjustItemText(item, action)
        return item


class ScaledComboBox(ComboBox):
    """ComboBox popup font needs explicit scaling in qfluentwidgets."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._popup_font_pt = 9

    def set_scaled_font(self, point_size: int):
        font_pt = max(9, int(point_size))
        font = QFont(self.font())
        font.setPointSize(font_pt)
        self._popup_font_pt = font_pt
        self.setFont(font)

    def _createComboMenu(self):
        return ScaledComboBoxMenu(self, self._popup_font_pt)


@dataclass
class TranslateConfig:
    inp: str
    out: str
    api_key: str
    provider: str
    api_url: str
    model: str
    extract_glossary: bool
    enable_glossary: bool
    max_workers: int
    batch_size: int
    max_batch_length: int
    max_text_size_for_batch: int
    api_timeout: int
    direction: str
    enable_thinking: bool
    enable_proofread: bool


class GlossaryImportWorker(QObject):
    finished = Signal(int, int, int, str, str)
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    @Slot()
    def run(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("术语表 JSON 顶层必须是对象")

            normalized_glossary, import_stats = JaZhTranslator.normalize_glossary_payload(payload)
            data_dir = get_data_dir()
            glossary_path = data_dir / "glossary.json"
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            backup_path = data_dir / f"glossary.backup.before_import.{timestamp}.json"

            existing = JaZhTranslator._load_json(str(glossary_path), {}) if glossary_path.exists() else {}
            if existing:
                existing_normalized, _ = JaZhTranslator.normalize_glossary_payload(existing)
                merged, merge_stats = JaZhTranslator.merge_glossaries(existing_normalized, normalized_glossary)
            else:
                merged = normalized_glossary
                merge_stats = {
                    "added": import_stats.get("accepted", 0),
                    "skipped": import_stats.get("skipped", 0),
                    "conflicts": import_stats.get("conflicts", 0),
                }

            has_existing = glossary_path.exists()
            if has_existing:
                shutil.copy2(glossary_path, backup_path)
            JaZhTranslator._atomic_write_json(glossary_path, merged)

            self.finished.emit(
                int(merge_stats.get("added", 0)),
                int(merge_stats.get("skipped", 0)),
                int(merge_stats.get("conflicts", 0)),
                str(glossary_path),
                str(backup_path if has_existing else "N/A"),
            )
        except Exception as e:
            self.failed.emit(str(e))


class GlossaryLoadWorker(QObject):
    finished = Signal(object, str)
    failed = Signal(str)

    @Slot()
    def run(self):
        try:
            glossary_path = get_data_dir() / "glossary.json"
            rows = load_glossary_rows(glossary_path)
            self.finished.emit(rows, str(glossary_path))
        except Exception as e:
            self.failed.emit(str(e))


class EstimateCharsWorker(QObject):
    finished = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    @Slot()
    def run(self):
        try:
            book = load_book(self.path)
            all_texts = []
            for _, _, tags in iter_text_nodes(book):
                for tag in tags:
                    text = tag.get_text(" ", strip=True)
                    if text:
                        all_texts.append(text)
            all_texts.extend(extract_toc_titles(book))
            self.finished.emit(self.path, sum(len(t) for t in all_texts))
        except Exception as e:
            self.failed.emit(self.path, str(e))


class TranslateWorker(QObject):
    progress = Signal(int, int, int)
    item = Signal(str, str)
    proofread_detail = Signal(dict)
    status = Signal(str)
    stat_update = Signal(int, int, int, int, int, float, int, int, int, int)
    finished = Signal(str)
    failed = Signal(str)
    error_detail = Signal(str)

    def __init__(self, config: TranslateConfig):
        super().__init__()
        self.config = config
        self.cancel_event = threading.Event()
        self.start_ts = 0.0
        self.translator: Optional[JaZhTranslator] = None

    def cancel(self):
        self.cancel_event.set()
        translator = self.translator
        if translator is not None:
            try:
                translator.flush_cache()
                translator.session.close()
            except Exception:
                pass

    @staticmethod
    def _extract_text(tag) -> str:
        return tag.get_text(" ", strip=True)

    @staticmethod
    def _is_translatable(text: str) -> bool:
        return is_translatable(text)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        invalid = '<>:"/\\|?*'
        cleaned = "".join("_" if c in invalid or ord(c) < 32 else c for c in name)
        cleaned = " ".join(cleaned.split()).strip(" ._")
        if cleaned.lower().endswith(".epub"):
            cleaned = cleaned[:-5].strip(" ._")
        cleaned = cleaned[:120].strip(" ._")
        if not cleaned:
            return ""

        reserved_names = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "CONIN$",
            "CONOUT$",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
        if cleaned.split(".", 1)[0].upper() in reserved_names:
            cleaned = f"{cleaned}_"
        return cleaned

    @staticmethod
    def _unique_epub_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 1000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")

    def _translated_output_path(
        self,
        cfg: TranslateConfig,
        translator: JaZhTranslator,
        toc_titles: list,
        results: dict,
    ) -> str:
        source_path = Path(cfg.out)
        source_base = Path(cfg.inp).stem
        candidates = []

        if source_base in results and results[source_base]:
            candidates.append(str(results[source_base]))

        if self._is_translatable(source_base):
            try:
                name_results = translator.translate_batch([source_base])
                translated_name = name_results.get(source_base)
                if translated_name:
                    candidates.append(str(translated_name))
            except Exception:
                pass

        for title in toc_titles:
            translated_title = results.get(title)
            if translated_title:
                candidates.append(str(translated_title))
                break

        for candidate in candidates:
            safe_name = self._sanitize_filename(candidate)
            if not safe_name:
                continue
            target = source_path.with_name(f"{safe_name}.epub")
            if os.path.normcase(os.path.abspath(str(target))) == os.path.normcase(os.path.abspath(str(source_path))):
                return str(source_path)
            return str(self._unique_epub_path(target))

        return str(source_path)

    @Slot()
    def run(self):
        cfg = self.config
        self.start_ts = time.time()
        try:
            translator = JaZhTranslator(
                api_key=cfg.api_key,
                provider=cfg.provider,
                api_url=cfg.api_url,
                model=cfg.model,
                max_workers=cfg.max_workers,
                batch_size=cfg.batch_size,
                max_batch_length=cfg.max_batch_length,
                max_text_size_for_batch=cfg.max_text_size_for_batch,
                api_timeout=cfg.api_timeout,
                cancel_event=self.cancel_event,
                extract_glossary=cfg.extract_glossary,
                enable_glossary=cfg.enable_glossary,
                enable_thinking=cfg.enable_thinking,
                enable_proofread=cfg.enable_proofread,
            )
            self.translator = translator

            book = load_book(cfg.inp)
            docs = list(iter_text_nodes(book))
            toc_titles = extract_toc_titles(book)

            all_texts = []
            text_tag_map = []

            for doc_idx, (_, _, tags) in enumerate(docs):
                for tag in tags:
                    anchors = tag.find_all("a")
                    if len(anchors) > 1:
                        node_records = []
                        for node in tag.find_all(string=True):
                            raw = str(node).strip()
                            if self._is_translatable(raw):
                                all_texts.append(raw)
                                node_records.append((node, raw))
                        if node_records:
                            text_tag_map.append(("multi_anchor", doc_idx, tag, node_records))
                        continue

                    text = self._extract_text(tag)
                    if self._is_translatable(text):
                        all_texts.append(text)
                        mode = "single_anchor" if len(anchors) == 1 else "plain"
                        text_tag_map.append((mode, doc_idx, tag, text))

            toc_indices_start = len(all_texts)
            all_texts.extend(toc_titles)
            toc_indices_end = len(all_texts)

            total_chars = sum(len(t) for t in all_texts) or 1
            total_texts = len(all_texts)
            self.status.emit(f"开始翻译 文本块:{total_texts} 字符:{total_chars}")

            def emit_stat(completed: int, total: int):
                stats = translator.get_stats() if translator else {}
                elapsed = max(0.0, time.time() - self.start_ts)
                api_total = int(stats.get("api_requests_total", 0))
                batch_total = int(stats.get("batch_total", 0))
                batch_ok = int(stats.get("batch_json_success", 0)) + int(stats.get("batch_delimiter_success", 0))
                fail_count = int(stats.get("api_requests_failed", 0))
                terms = int(stats.get("glossary_new_terms_added", 0))
                success_rate = (batch_ok * 100.0 / batch_total) if batch_total else 100.0
                speed = int(completed / elapsed) if elapsed > 0 else 0
                # 平均速度：已完成文本块占比 * 总字数 / 已耗时
                translated_chars = int((completed / total) * total_chars) if total > 0 else 0
                char_speed = int(translated_chars / elapsed) if elapsed > 0 else 0
                token_total = int(stats.get("tokens_total", 0))
                self.stat_update.emit(
                    completed,
                    total,
                    terms,
                    api_total,
                    fail_count,
                    success_rate,
                    speed,
                    char_speed,
                    translated_chars,
                    token_total,
                )

            def on_progress(completed, total):
                self.progress.emit(completed, total, total_chars)
                emit_stat(completed, total)

            def on_item(src, dst):
                self.item.emit(src, dst)

            def on_proofread_detail(detail):
                self.proofread_detail.emit(detail)

            results = translator.translate_batch(
                all_texts,
                progress_callback=on_progress,
                item_callback=on_item,
                proofread_callback=on_proofread_detail,
            )

            if self.cancel_event.is_set():
                self.finished.emit(CANCELLED_RESULT)
                return

            for record in text_tag_map:
                mode, _, tag = record[0], record[1], record[2]

                if mode == "multi_anchor":
                    node_records = record[3]
                    for node, original in node_records:
                        translated = results.get(original)
                        if translated:
                            node.replace_with(NavigableString(translated))
                    continue

                original = record[3]
                translated = results.get(original)
                if not translated:
                    continue

                if mode == "single_anchor":
                    anchor = tag.find("a")
                    if anchor:
                        for child in list(tag.contents):
                            if child is not anchor:
                                child.extract()
                        anchor.clear()
                        anchor.append(NavigableString(translated))
                        continue

                tag.clear()
                tag.append(NavigableString(translated))

            for item, soup, _ in docs:
                item.set_content(str(soup).encode("utf-8"))

            toc_translations = {}
            for i in range(toc_indices_start, toc_indices_end):
                original = all_texts[i]
                if original in results:
                    toc_translations[original] = results[original]

            if toc_translations:
                apply_toc_translations(book, toc_translations)

            save_book(cfg.out, book, chinese_mode=(cfg.direction == "zh"))
            final_out = cfg.out
            try:
                translated_out = self._translated_output_path(cfg, translator, toc_titles, results)
                if translated_out != cfg.out:
                    Path(cfg.out).rename(translated_out)
                    final_out = translated_out
            except Exception as rename_error:
                self.status.emit(f"文件名翻译失败，已保留原输出文件: {rename_error}")
            translator.flush_cache()

            self.progress.emit(total_texts, total_texts, total_chars)
            emit_stat(total_texts, total_texts)

            # 翻译完成时，将调试统计写入错误详情面板
            if translator:
                stats = translator.get_stats()
                partial = int(stats.get("batch_json_partial_success", 0))
                retry = int(stats.get("batch_partial_retry", 0))
                trunc = int(stats.get("truncation_continuation", 0))
                if partial or retry or trunc:
                    lines = ["[P0 调试统计]"]
                    if partial:
                        lines.append(f"  批量部分成功: {partial} 次")
                    if retry:
                        lines.append(f"  缺失索引重试: {retry} 次")
                    if trunc:
                        lines.append(f"  截断续取: {trunc} 次")
                    self.error_detail.emit("\n".join(lines))

            self.finished.emit(final_out)
        except Exception as e:
            # User-triggered cancel should end as a normal stop instead of an error.
            if self.cancel_event.is_set() and "翻译已取消" in str(e):
                self.finished.emit(CANCELLED_RESULT)
                return
            self.error_detail.emit(traceback.format_exc())
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


class DropLineEdit(LineEdit):
    fileDropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and urls[0].toLocalFile().lower().endswith(".epub"):
                event.acceptProposedAction()
                self.setProperty("dragging", True)
                self.style().unpolish(self)
                self.style().polish(self)
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setProperty("dragging", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.setProperty("dragging", False)
        self.style().unpolish(self)
        self.style().polish(self)
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if path.lower().endswith(".epub"):
            self.fileDropped.emit(path)
            event.acceptProposedAction()


class QtAppWindow(QWidget):
    PROVIDERS = [
        ("DeepSeek", "deepseek"),
        ("Doubao", "doubao"),
        ("Sakura", "sakura"),
        ("Gemini", "gemini"),
        ("GLM(Zhipu)", "glm"),
        ("Custom", "custom"),
    ]

    def __init__(self):
        super().__init__()
        setTheme(Theme.LIGHT)
        self.setWindowTitle("EPUB 日译中 V3.2betaV1版")
        self._setup_window_icon()
        self.resize(1140, 780)
        self.setMinimumSize(960, 680)

        self.default_dir = os.getcwd()
        self._base_font_pt = 9
        self._ui_font_pt = 9
        self.translation_start_time = 0.0
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[TranslateWorker] = None
        self.glossary_import_thread: Optional[QThread] = None
        self.glossary_import_worker: Optional[GlossaryImportWorker] = None
        self.glossary_load_thread: Optional[QThread] = None
        self.glossary_load_worker: Optional[GlossaryLoadWorker] = None
        self.estimate_thread: Optional[QThread] = None
        self.estimate_worker: Optional[EstimateCharsWorker] = None
        self._estimate_pending_path = ""
        self._estimate_running_path = ""
        self.estimate_timer = QTimer(self)
        self.estimate_timer.setSingleShot(True)
        self.estimate_timer.timeout.connect(self._start_estimate_chars)
        self._glossary_all_rows = []
        self._glossary_pending_rows = []
        self._glossary_populate_index = 0
        self._glossary_table_dirty = False
        self._glossary_table_loading = False
        self._glossary_dirty_after_populate = False
        self._proofread_detail_count = 0
        self.is_paused = False
        self.last_task_cfg: Optional[TranslateConfig] = None
        self._glm_perf_limited = False
        self._perf_values_before_glm: Optional[dict] = None
        self._api_test_signal = _ApiTestSignal()
        self._api_test_signal.result.connect(self._show_api_test_result)
        self._active_perf_preset = "custom"
        self._applying_perf_preset = False

        self._build_ui()
        self._apply_adaptive_font()
        self._sync_all_combo_fonts()
        self._on_provider_change()
        self._update_perf_slider_labels()
        self._setup_styles(Theme.LIGHT)

    def _setup_window_icon(self):
        """Set title bar icon from assets folder if present."""
        root_dir = Path(__file__).resolve().parent.parent
        candidates = [
            root_dir / "assets" / "logo.ico",
            root_dir / "assets" / "logo.png",
            root_dir / "logo.ico",
            root_dir / "logo.png",
        ]
        for path in candidates:
            if path.exists():
                self.setWindowIcon(QIcon(str(path)))
                return

    def _apply_adaptive_font(self):
        """Apply DPI-aware font sizing for better readability."""
        screen = QGuiApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen is not None else 96.0

        # Baseline tuned for common Windows DPI scales.
        if dpi >= 168:       # ~175%+
            base_pt = 12
        elif dpi >= 144:     # ~150%
            base_pt = 11
        elif dpi >= 120:     # ~125%
            base_pt = 10
        else:                # 100%
            base_pt = 9

        # Keep text readable on 100% desktop scaling while staying compact on high-DPI screens.
        self._base_font_pt = base_pt
        self._ui_font_pt = max(9, int(round(base_pt * 0.9)))
        font = QFont(self.font())
        font.setPointSize(self._ui_font_pt)
        self.setFont(font)
        app = QApplication.instance()
        if app is not None:
            app.setFont(font)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        nav = QFrame(self)
        nav.setObjectName("navPane")
        nav.setFixedWidth(230)
        nav_layout = QVBoxLayout(nav)
        nav_layout.setContentsMargins(14, 18, 14, 14)
        nav_layout.setSpacing(10)

        title = StrongBodyLabel("EPUB 日译中 V3.2betaV1版")
        nav_layout.addWidget(title)
        nav_layout.addWidget(CaptionLabel("Qt Fluent UI"))

        self.nav_task_btn = PushButton("任务")
        self.nav_task_btn.setIcon(FluentIcon.DOCUMENT.icon())
        self.nav_task_btn.setCheckable(True)
        self.nav_task_btn.clicked.connect(lambda: self._switch_page("task"))
        nav_layout.addWidget(self.nav_task_btn)

        self.nav_api_btn = PushButton("接口配置")
        self.nav_api_btn.setIcon(FluentIcon.CLOUD.icon())
        self.nav_api_btn.setCheckable(True)
        self.nav_api_btn.clicked.connect(lambda: self._switch_page("api"))
        nav_layout.addWidget(self.nav_api_btn)

        self.nav_glossary_btn = PushButton("术语表")
        self.nav_glossary_btn.setIcon(FluentIcon.LIBRARY.icon())
        self.nav_glossary_btn.setCheckable(True)
        self.nav_glossary_btn.clicked.connect(lambda: self._switch_page("glossary"))
        nav_layout.addWidget(self.nav_glossary_btn)

        self.nav_status_btn = PushButton("状态监控")
        self.nav_status_btn.setIcon(FluentIcon.HISTORY.icon())
        self.nav_status_btn.setCheckable(True)
        self.nav_status_btn.clicked.connect(lambda: self._switch_page("status"))
        nav_layout.addWidget(self.nav_status_btn)

        nav_layout.addStretch(1)

        self.nav_settings_btn = PushButton("设置")
        self.nav_settings_btn.setIcon(FluentIcon.SETTING.icon())
        self.nav_settings_btn.setCheckable(True)
        self.nav_settings_btn.clicked.connect(lambda: self._switch_page("option"))
        nav_layout.addWidget(self.nav_settings_btn, 0, Qt.AlignLeft | Qt.AlignBottom)

        root.addWidget(nav)

        self.page_area = ScrollArea(self)
        self.page_area.setWidgetResizable(True)
        root.addWidget(self.page_area, 1)

        self.pages = {
            "task": self._build_task_page(),
            "api": self._build_api_page(),
            "glossary": self._build_glossary_page(),
            "option": self._build_option_page(),
            "status": self._build_status_page(),
        }
        self._switch_page("task")

    def _setup_styles(self, theme: Theme):
        if theme == Theme.DARK:
            win_bg = "#15181d"
            page_bg = "#15181d"
            nav_bg = "#1f2329"
            nav_border = "#3a4049"
            card_bg = "#2b3038"
            card_border = "#404854"
            drag_bg = "#1f2f45"
            drag_border = "#5b8bd9"
            rt_color = "#8cb4ff"
            radio_color = "#e6eaf2"
            table_bg = "#222831"
            table_alt_bg = "#2a303a"
            table_text = "#edf2f7"
            table_grid = "#3a4049"
            table_header_bg = "#303743"
            table_selected_bg = "#315f9c"
            table_selected_text = "#ffffff"
            dialog_bg = "#242a33"
            dialog_text = "#edf2f7"
            dialog_button_bg = "#303743"
            dialog_button_hover = "#3a4656"
            dialog_button_pressed = "#26303c"
            perf_checked_bg = "#315f9c"
            perf_checked_border = "#8cb4ff"
            perf_checked_text = "#ffffff"
        else:
            win_bg = "#f5f7fb"
            page_bg = "#f5f7fb"
            nav_bg = "#f9fbff"
            nav_border = "#e6e8eb"
            card_bg = "#ffffff"
            card_border = "#e8eaee"
            drag_bg = "#ebf4ff"
            drag_border = "#2b6cb0"
            rt_color = "#005fb8"
            radio_color = "#1f2937"
            table_bg = "#ffffff"
            table_alt_bg = "#f5f7fb"
            table_text = "#1f2937"
            table_grid = "#e5e7eb"
            table_header_bg = "#f1f5f9"
            table_selected_bg = "#dbeafe"
            table_selected_text = "#0f172a"
            dialog_bg = "#ffffff"
            dialog_text = "#1f2937"
            dialog_button_bg = "#f8fafc"
            dialog_button_hover = "#eef2f7"
            dialog_button_pressed = "#e2e8f0"
            perf_checked_bg = "#dbeafe"
            perf_checked_border = "#2563eb"
            perf_checked_text = "#0f172a"

        self._current_theme = theme
        self.setStyleSheet(
            f"""
            QWidget {{ background: {win_bg}; }}
            QScrollArea {{ background: {page_bg}; border: none; }}
            QScrollArea > QWidget > QWidget {{ background: {page_bg}; }}
            QFrame#navPane {{ border: 1px solid {nav_border}; border-radius: 12px; background: {nav_bg}; }}
            QFrame#card {{ border: 1px solid {card_border}; border-radius: 10px; background: {card_bg}; }}
            QLabel, QLineEdit, QPlainTextEdit, QComboBox, QPushButton, QCheckBox, QRadioButton {{
                font-size: {self._ui_font_pt}pt;
            }}
            QComboBox QAbstractItemView {{
                font-size: {self._ui_font_pt}pt;
            }}
            QTableWidget {{
                background: {table_bg};
                alternate-background-color: {table_alt_bg};
                color: {table_text};
                gridline-color: {table_grid};
                selection-background-color: {table_selected_bg};
                selection-color: {table_selected_text};
            }}
            QTableWidget::item {{
                color: {table_text};
            }}
            QTableWidget::item:selected {{
                background: {table_selected_bg};
                color: {table_selected_text};
            }}
            QHeaderView::section {{
                background: {table_header_bg};
                color: {table_text};
                border: 1px solid {table_grid};
                padding: 5px;
            }}
            QTableCornerButton::section {{
                background: {table_header_bg};
                border: 1px solid {table_grid};
            }}
            QMessageBox {{
                background: {dialog_bg};
                color: {dialog_text};
            }}
            QMessageBox QLabel {{
                background: transparent;
                color: {dialog_text};
                font-size: {self._ui_font_pt}pt;
            }}
            QMessageBox QPushButton {{
                background: {dialog_button_bg};
                color: {dialog_text};
                border: 1px solid {table_grid};
                border-radius: 6px;
                min-width: 76px;
                padding: 6px 14px;
                font-size: {self._ui_font_pt}pt;
            }}
            QMessageBox QPushButton:hover {{
                background: {dialog_button_hover};
            }}
            QMessageBox QPushButton:pressed {{
                background: {dialog_button_pressed};
            }}
            QPushButton#perfPresetButton:checked {{
                background: {perf_checked_bg};
                color: {perf_checked_text};
                border: 1px solid {perf_checked_border};
                font-weight: 600;
            }}
            QRadioButton {{ color: {radio_color}; }}
            DropLineEdit[dragging="true"] {{ border: 2px solid {drag_border}; background: {drag_bg}; }}
            """
        )
        self.rt_dst.setStyleSheet(f"color:{rt_color};")
        self._apply_native_titlebar_theme(theme == Theme.DARK)

    def _apply_native_titlebar_theme(self, dark: bool, widget=None):
        """Best-effort dark title bar on Windows 10/11."""
        if os.name != "nt" or ctypes is None:
            return
        try:
            target = widget if widget is not None else self
            hwnd = int(target.winId())
            value = ctypes.c_int(1 if dark else 0)
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
            dwmapi = ctypes.windll.dwmapi
            # Try current attribute first, then fallback for older builds.
            res = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
            if res != 0:
                dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1),
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
        except Exception:
            pass

    def _make_page_container(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        return w

    def _make_card(self, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        lay.addWidget(StrongBodyLabel(title))
        return card

    def _sync_combo_font(self, combo: ComboBox):
        if hasattr(combo, "set_scaled_font"):
            combo.set_scaled_font(self._ui_font_pt)
        else:
            font = QFont(combo.font())
            font.setPointSize(self._ui_font_pt)
            combo.setFont(font)
        view_getter = getattr(combo, "view", None)
        view = view_getter() if callable(view_getter) else None
        if view is not None:
            view.setFont(combo.font())

    def _sync_all_combo_fonts(self):
        for name in ("provider_combo", "theme_combo", "glossary_category_combo", "glossary_source_combo"):
            combo = getattr(self, name, None)
            if combo is not None:
                self._sync_combo_font(combo)

    def _on_glossary_enabled_changed(self):
        enabled = self.enable_glossary_cb.isChecked()
        self.extract_glossary_cb.setEnabled(enabled)
        if not enabled:
            self.extract_glossary_cb.setChecked(False)
        self._set_glossary_table_editable(enabled)

    def _set_glossary_table_editable(self, enabled: bool):
        table = getattr(self, "glossary_table", None)
        if table is not None:
            if enabled:
                table.setEditTriggers(
                    QAbstractItemView.DoubleClicked
                    | QAbstractItemView.SelectedClicked
                    | QAbstractItemView.EditKeyPressed
                )
            else:
                table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        save_btn = getattr(self, "glossary_save_btn", None)
        if save_btn is not None:
            save_btn.setEnabled(enabled and self._glossary_table_dirty)
        for name in ("glossary_add_btn", "glossary_delete_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(enabled)

    def _build_task_page(self) -> QWidget:
        page = self._make_page_container()
        layout = page.layout()

        card = self._make_card("文件设置")
        form_layout = QGridLayout()
        form_layout.setHorizontalSpacing(10)
        form_layout.setVerticalSpacing(10)

        self.input_edit = DropLineEdit()
        self.output_edit = LineEdit()
        self.estimate_label = CaptionLabel("预估字符: -")

        in_btn = PushButton("选择输入")
        in_btn.clicked.connect(self.pick_input)
        out_btn = PushButton("选择输出")
        out_btn.clicked.connect(self.pick_output)

        form_layout.addWidget(BodyLabel("输入 EPUB"), 0, 0)
        form_layout.addWidget(self.input_edit, 0, 1)
        form_layout.addWidget(in_btn, 0, 2)
        form_layout.addWidget(self.estimate_label, 0, 3)

        form_layout.addWidget(BodyLabel("输出 EPUB"), 1, 0)
        form_layout.addWidget(self.output_edit, 1, 1)
        form_layout.addWidget(out_btn, 1, 2)

        form_layout.setColumnStretch(1, 1)
        card.layout().addLayout(form_layout)
        card.layout().addWidget(CaptionLabel("支持将 .epub 文件直接拖拽到输入框"))

        self.input_edit.textChanged.connect(self._on_input_changed)
        self.input_edit.fileDropped.connect(self._on_input_file_dropped)

        layout.addWidget(card)

        action_card = self._make_card("操作")
        act_l = QHBoxLayout()
        self.start_btn = PrimaryPushButton("开始翻译")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = PushButton("暂停")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        self.resume_btn = PushButton("恢复")
        self.resume_btn.setEnabled(False)
        self.resume_btn.clicked.connect(self.resume)
        act_l.addWidget(self.start_btn)
        act_l.addWidget(self.cancel_btn)
        act_l.addWidget(self.resume_btn)
        act_l.addStretch(1)
        action_card.layout().addLayout(act_l)
        self.pause_hint_label = CaptionLabel("暂停会等待当前 API 请求结束；已完成内容会写入缓存，可切换模型后恢复。")
        action_card.layout().addWidget(self.pause_hint_label)
        layout.addWidget(action_card)

        layout.addWidget(CaptionLabel(f"缓存目录: {get_data_dir()}"))
        layout.addStretch(1)
        return page

    def _build_api_page(self) -> QWidget:
        page = self._make_page_container()
        layout = page.layout()

        card = self._make_card("API 配置")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.provider_combo = ScaledComboBox()
        self._sync_combo_font(self.provider_combo)
        for label, _ in self.PROVIDERS:
            self.provider_combo.addItem(label)
        self.provider_combo.currentTextChanged.connect(self._on_provider_change)

        self.api_key_edit = PasswordLineEdit()
        self.api_url_edit = LineEdit()
        self.model_edit = LineEdit()
        self.api_timeout_edit = LineEdit()
        self.api_timeout_edit.setText("15")
        self.test_btn = PushButton("测试连接")
        self.test_btn.clicked.connect(self._test_api_connection)

        grid.addWidget(BodyLabel("服务提供方"), 0, 0)
        grid.addWidget(self.provider_combo, 0, 1)

        grid.addWidget(BodyLabel("API Key"), 1, 0)
        grid.addWidget(self.api_key_edit, 1, 1)
        grid.addWidget(self.test_btn, 1, 2)

        grid.addWidget(BodyLabel("Base URL"), 2, 0)
        grid.addWidget(self.api_url_edit, 2, 1, 1, 2)

        grid.addWidget(BodyLabel("模型"), 3, 0)
        grid.addWidget(self.model_edit, 3, 1, 1, 2)

        grid.addWidget(BodyLabel("测试超时(秒)"), 4, 0)
        grid.addWidget(self.api_timeout_edit, 4, 1)

        grid.setColumnStretch(1, 1)
        card.layout().addLayout(grid)
        self.provider_capability_label = CaptionLabel("")
        self.provider_capability_label.setWordWrap(True)
        card.layout().addWidget(self.provider_capability_label)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    def _build_glossary_page(self) -> QWidget:
        page = self._make_page_container()
        layout = page.layout()

        card = self._make_card("术语表")
        toolbar = QHBoxLayout()
        self.glossary_summary_label = BodyLabel("")
        self.glossary_refresh_btn = PushButton("刷新")
        self.glossary_refresh_btn.clicked.connect(self._refresh_glossary_table)
        self.glossary_add_btn = PushButton("新增术语")
        self.glossary_add_btn.setEnabled(False)
        self.glossary_add_btn.clicked.connect(self._add_glossary_row)
        self.glossary_delete_btn = PushButton("删除选中")
        self.glossary_delete_btn.setEnabled(False)
        self.glossary_delete_btn.clicked.connect(self._delete_selected_glossary_rows)
        self.glossary_save_btn = PushButton("保存修改")
        self.glossary_save_btn.setEnabled(False)
        self.glossary_save_btn.clicked.connect(self._save_glossary_table_edits)
        self.glossary_import_page_btn = PushButton("增量导入 JSON")
        self.glossary_import_page_btn.clicked.connect(self.import_glossary_json)
        self.glossary_export_btn = PushButton("导出/备份 JSON")
        self.glossary_export_btn.clicked.connect(self.export_glossary_json)
        self.glossary_restore_btn = PushButton("恢复备份")
        self.glossary_restore_btn.clicked.connect(self.restore_glossary_backup)

        settings_row = QHBoxLayout()
        self.enable_glossary_cb = CheckBox("启用术语表")
        self.enable_glossary_cb.setChecked(False)
        self.enable_glossary_cb.stateChanged.connect(self._on_glossary_enabled_changed)
        self.extract_glossary_cb = CheckBox("自动提取术语（实验）")
        self.extract_glossary_cb.setChecked(False)
        self.extract_glossary_cb.setEnabled(False)
        settings_row.addWidget(self.enable_glossary_cb)
        settings_row.addWidget(self.extract_glossary_cb)
        settings_row.addStretch(1)

        card.layout().addLayout(settings_row)
        card.layout().addWidget(CaptionLabel("术语表默认不启用；勾选“启用术语表”后，本次翻译才会使用术语表。"))

        filter_row = QHBoxLayout()
        self.glossary_search_edit = LineEdit()
        self.glossary_search_edit.setPlaceholderText("搜索原文 / 译文 / 备注")
        self.glossary_search_edit.textChanged.connect(self._apply_glossary_filters)
        self.glossary_category_combo = ScaledComboBox()
        self._sync_combo_font(self.glossary_category_combo)
        self.glossary_category_combo.addItems(["全部分类"] + GLOSSARY_CATEGORIES)
        self.glossary_category_combo.currentTextChanged.connect(self._apply_glossary_filters)
        self.glossary_source_combo = ScaledComboBox()
        self._sync_combo_font(self.glossary_source_combo)
        self.glossary_source_combo.addItems(["全部来源", "自动提取", "手动添加", "未知来源"])
        self.glossary_source_combo.currentTextChanged.connect(self._apply_glossary_filters)
        filter_row.addWidget(BodyLabel("筛选"))
        filter_row.addWidget(self.glossary_search_edit, 1)
        filter_row.addWidget(self.glossary_category_combo)
        filter_row.addWidget(self.glossary_source_combo)
        card.layout().addLayout(filter_row)

        toolbar.addWidget(self.glossary_summary_label)
        toolbar.addStretch(1)
        toolbar.addWidget(self.glossary_add_btn)
        toolbar.addWidget(self.glossary_delete_btn)
        toolbar.addWidget(self.glossary_refresh_btn)
        toolbar.addWidget(self.glossary_save_btn)
        toolbar.addWidget(self.glossary_import_page_btn)
        toolbar.addWidget(self.glossary_export_btn)
        toolbar.addWidget(self.glossary_restore_btn)

        self.glossary_table = QTableWidget(0, 4)
        self.glossary_table.setHorizontalHeaderLabels(["分类", "原文", "译文", "备注/来源"])
        self.glossary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.glossary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.glossary_table.setAlternatingRowColors(True)
        self.glossary_table.setMinimumHeight(420)
        self.glossary_table.verticalHeader().setVisible(False)
        self.glossary_table.verticalHeader().setDefaultSectionSize(30)
        self.glossary_table.itemChanged.connect(self._on_glossary_table_item_changed)
        header = self.glossary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        card.layout().addLayout(toolbar)
        card.layout().addWidget(self.glossary_table)
        layout.addWidget(card)
        layout.addWidget(CaptionLabel(f"术语表路径: {self._glossary_path()}"))
        layout.addStretch(1)
        return page

    def _build_option_page(self) -> QWidget:
        page = self._make_page_container()
        layout = page.layout()

        perf_card = self._make_card("性能参数")
        self.slider_max_workers = Slider(Qt.Horizontal)
        self.slider_max_workers.setRange(1, 25)
        self.slider_batch_size = Slider(Qt.Horizontal)
        self.slider_batch_size.setRange(1, 15)
        self.slider_max_batch_length = Slider(Qt.Horizontal)
        self.slider_max_batch_length.setRange(1, 8000)
        self.slider_max_text_size_for_batch = Slider(Qt.Horizontal)
        self.slider_max_text_size_for_batch.setRange(1, 1000)
        self.slider_api_timeout = Slider(Qt.Horizontal)
        self.slider_api_timeout.setRange(1, 300)

        def make_spinbox(minimum: int, maximum: int) -> QSpinBox:
            box = QSpinBox()
            box.setRange(minimum, maximum)
            box.setFixedWidth(92)
            return box

        self.spin_max_workers = make_spinbox(1, 25)
        self.spin_batch_size = make_spinbox(1, 15)
        self.spin_max_batch_length = make_spinbox(1, 8000)
        self.spin_max_text_size_for_batch = make_spinbox(1, 1000)
        self.spin_api_timeout = make_spinbox(1, 300)

        # 使用 balanced 预设作为默认值
        default_cfg = PERFORMANCE_PRESETS["balanced"]
        self.slider_max_workers.setValue(default_cfg["max_workers"])
        self.slider_batch_size.setValue(default_cfg["batch_size"])
        self.slider_max_batch_length.setValue(default_cfg["max_batch_length"])
        self.slider_max_text_size_for_batch.setValue(default_cfg["max_text_size_for_batch"])
        self.slider_api_timeout.setValue(120)

        for slider, spinbox in [
            (self.slider_max_workers, self.spin_max_workers),
            (self.slider_batch_size, self.spin_batch_size),
            (self.slider_max_batch_length, self.spin_max_batch_length),
            (self.slider_max_text_size_for_batch, self.spin_max_text_size_for_batch),
            (self.slider_api_timeout, self.spin_api_timeout),
        ]:
            spinbox.setValue(slider.value())
            slider.valueChanged.connect(spinbox.setValue)
            spinbox.valueChanged.connect(slider.setValue)

        self.lbl_max_workers = BodyLabel("")
        self.lbl_batch_size = BodyLabel("")
        self.lbl_max_batch_length = BodyLabel("")
        self.lbl_max_text_size_for_batch = BodyLabel("")
        self.lbl_api_timeout = BodyLabel("")

        preset_row = QHBoxLayout()
        preset_row.addWidget(BodyLabel("推荐预设"))
        self._perf_preset_buttons = {}
        for preset_key in ("glm_free", "gemini_free", "deepseek_paid"):
            btn = PushButton(PERF_UI_PRESETS[preset_key]["label"])
            btn.setObjectName("perfPresetButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, key=preset_key: self._apply_perf_preset(key))
            self._perf_preset_buttons[preset_key] = btn
            preset_row.addWidget(btn)
        self.custom_perf_btn = PushButton("自定义")
        self.custom_perf_btn.setObjectName("perfPresetButton")
        self.custom_perf_btn.setCheckable(True)
        self.custom_perf_btn.clicked.connect(self._mark_custom_perf)
        self._perf_preset_buttons["custom"] = self.custom_perf_btn
        preset_row.addWidget(self.custom_perf_btn)
        preset_row.addStretch(1)
        perf_card.layout().addLayout(preset_row)

        for slider in [
            self.slider_max_workers,
            self.slider_batch_size,
            self.slider_max_batch_length,
            self.slider_max_text_size_for_batch,
            self.slider_api_timeout,
        ]:
            slider.valueChanged.connect(self._on_perf_value_changed)

        for title, slider, label in [
            ("并发数", self.slider_max_workers, self.spin_max_workers),
            ("批量大小", self.slider_batch_size, self.spin_batch_size),
            ("批量字符上限", self.slider_max_batch_length, self.spin_max_batch_length),
            ("单条字符上限", self.slider_max_text_size_for_batch, self.spin_max_text_size_for_batch),
            ("超时(秒)", self.slider_api_timeout, self.spin_api_timeout),
        ]:
            row = QHBoxLayout()
            row.addWidget(BodyLabel(title))
            row.addWidget(slider, 1)
            row.addWidget(label)
            perf_card.layout().addLayout(row)

        self.perf_limit_hint = CaptionLabel("")
        perf_card.layout().addWidget(self.perf_limit_hint)
        layout.addWidget(perf_card)

        direction_card = self._make_card("翻页方向")
        row2_l = QHBoxLayout()
        self.dir_zh = QRadioButton("中文习惯")
        self.dir_ja = QRadioButton("保持原版")
        self.dir_zh.setChecked(True)
        row2_l.addWidget(self.dir_zh)
        row2_l.addWidget(self.dir_ja)
        row2_l.addStretch(1)
        direction_card.layout().addLayout(row2_l)
        layout.addWidget(direction_card)

        ui_card = self._make_card("界面与推理设置")
        row4_l = QHBoxLayout()
        self.theme_combo = ScaledComboBox()
        self._sync_combo_font(self.theme_combo)
        self.theme_combo.addItems(["浅色主题", "深色主题"])
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.enable_thinking_cb = CheckBox("开启深度思考")
        self.enable_thinking_cb.setChecked(False)
        self.enable_thinking_cb.stateChanged.connect(self._on_thinking_toggle_changed)
        self.enable_proofread_cb = CheckBox("启用译后校对")
        self.enable_proofread_cb.setChecked(False)
        row4_l.addWidget(BodyLabel("主题"))
        row4_l.addWidget(self.theme_combo)
        row4_l.addSpacing(16)
        row4_l.addWidget(self.enable_thinking_cb)
        row4_l.addWidget(self.enable_proofread_cb)
        row4_l.addStretch(1)
        ui_card.layout().addLayout(row4_l)
        ui_card.layout().addWidget(CaptionLabel("默认关闭深度思考和译后校对；译后校对只修正疑似日文残留、术语不一致等问题，会额外消耗 token。"))
        layout.addWidget(ui_card)

        layout.addStretch(1)
        self._update_perf_slider_labels()
        self._set_active_perf_preset("custom")
        return page

    def _build_status_page(self) -> QWidget:
        page = self._make_page_container()
        layout = page.layout()

        self.status_tabs = SegmentedWidget()
        self.status_stack = QStackedWidget()
        self._status_section_indexes = {}
        layout.addWidget(self.status_tabs)
        layout.addWidget(self.status_stack)

        overview_page = QWidget()
        overview_layout = QVBoxLayout(overview_page)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        overview_layout.setSpacing(12)

        cards_wrap = QFrame()
        cards_layout = QGridLayout(cards_wrap)
        cards_layout.setHorizontalSpacing(8)
        cards_layout.setVerticalSpacing(8)

        self.stat_value_labels = {}
        stat_defs = [
            ("completed", "已完成"),
            ("total", "总文本块"),
            ("terms", "新增术语"),
            ("elapsed", "预计剩余"),
            ("speed", "速度(块/秒)"),
            ("char_speed", "速度(字/秒)"),
            ("api", "API 请求"),
            ("token", "Token 消耗"),
            ("success", "成功率"),
            ("fail", "失败数"),
        ]

        for idx, (key, text) in enumerate(stat_defs):
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(2)
            cl.addWidget(CaptionLabel(text))
            val = StrongBodyLabel("-")
            cl.addWidget(val)
            self.stat_value_labels[key] = val
            cards_layout.addWidget(card, idx // 5, idx % 5)

        overview_layout.addWidget(cards_wrap)

        progress_card = self._make_card("翻译进度")
        bar_row = QHBoxLayout()
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_pct = BodyLabel("0%")
        self.progress_pct.setFixedWidth(40)
        bar_row.addWidget(self.progress_bar)
        bar_row.addWidget(self.progress_pct)
        progress_card.layout().addLayout(bar_row)
        self.stats_label = CaptionLabel("状态: 待开始")
        progress_card.layout().addWidget(self.stats_label)
        stat_actions = QHBoxLayout()
        self.clear_stats_btn = PushButton("清空统计")
        self.clear_stats_btn.clicked.connect(self._clear_runtime_stats)
        stat_actions.addWidget(self.clear_stats_btn)
        stat_actions.addStretch(1)
        progress_card.layout().addLayout(stat_actions)
        overview_layout.addWidget(progress_card)
        overview_layout.addStretch(1)

        realtime_page = QWidget()
        realtime_layout = QVBoxLayout(realtime_page)
        realtime_layout.setContentsMargins(0, 0, 0, 0)
        realtime_layout.setSpacing(12)
        realtime_card = self._make_card("实时翻译")
        self.rt_src = BodyLabel("")
        self.rt_src.setWordWrap(True)
        self.rt_dst = BodyLabel("")
        self.rt_dst.setWordWrap(True)
        self.rt_dst.setStyleSheet("color:#005fb8;")
        realtime_card.layout().addWidget(CaptionLabel("原文"))
        realtime_card.layout().addWidget(self.rt_src)
        realtime_card.layout().addWidget(CaptionLabel("译文"))
        realtime_card.layout().addWidget(self.rt_dst)
        realtime_layout.addWidget(realtime_card)
        realtime_layout.addStretch(1)

        proofread_page = QWidget()
        proofread_layout = QVBoxLayout(proofread_page)
        proofread_layout.setContentsMargins(0, 0, 0, 0)
        proofread_layout.setSpacing(12)
        proofread_card = self._make_card("译后校对详情")
        self.proofread_detail_text = QPlainTextEdit()
        self.proofread_detail_text.setReadOnly(True)
        self.proofread_detail_text.setPlaceholderText("启用译后校对后，可疑译文的原因、原文、初译和校对后译文会显示在这里")
        self.proofread_detail_text.setMinimumHeight(180)
        proofread_card.layout().addWidget(self.proofread_detail_text)
        proofread_actions = QHBoxLayout()
        self.clear_proofread_btn = PushButton("清空校对详情")
        self.clear_proofread_btn.clicked.connect(self._clear_proofread_details)
        proofread_actions.addWidget(self.clear_proofread_btn)
        proofread_actions.addStretch(1)
        proofread_card.layout().addLayout(proofread_actions)
        proofread_layout.addWidget(proofread_card)
        proofread_layout.addStretch(1)

        diagnostic_page = QWidget()
        diagnostic_layout = QVBoxLayout(diagnostic_page)
        diagnostic_layout.setContentsMargins(0, 0, 0, 0)
        diagnostic_layout.setSpacing(12)
        err_card = self._make_card("最近一次错误详情")
        self.last_error_text = QPlainTextEdit()
        self.last_error_text.setReadOnly(True)
        self.last_error_text.setPlaceholderText("暂无错误")
        self.last_error_text.setMinimumHeight(140)
        err_card.layout().addWidget(self.last_error_text)
        err_actions = QHBoxLayout()
        self.export_diag_btn = PushButton("导出诊断包")
        self.export_diag_btn.clicked.connect(self._export_diagnostic_bundle)
        err_actions.addWidget(self.export_diag_btn)
        err_actions.addStretch(1)
        err_card.layout().addLayout(err_actions)
        diagnostic_layout.addWidget(err_card)
        diagnostic_layout.addStretch(1)

        for key, text, widget in [
            ("overview", "运行概览", overview_page),
            ("realtime", "实时翻译", realtime_page),
            ("proofread", "校对详情", proofread_page),
            ("diagnostic", "错误诊断", diagnostic_page),
        ]:
            index = self.status_stack.addWidget(widget)
            self._status_section_indexes[key] = index
            self.status_tabs.addItem(key, text, onClick=lambda checked=False, k=key: self._switch_status_section(k))

        layout.addStretch(1)
        self.status_tabs.setCurrentItem("overview")
        self._switch_status_section("overview")
        self._reset_stat_cards()
        return page

    def _switch_status_section(self, key: str):
        stack = getattr(self, "status_stack", None)
        indexes = getattr(self, "_status_section_indexes", {})
        if stack is not None and key in indexes:
            stack.setCurrentIndex(indexes[key])
        tabs = getattr(self, "status_tabs", None)
        if tabs is not None and tabs.currentRouteKey() != key:
            tabs.setCurrentItem(key)

    def _reset_stat_cards(self):
        self.stat_value_labels["completed"].setText("0")
        self.stat_value_labels["total"].setText("0")
        self.stat_value_labels["terms"].setText("0")
        self.stat_value_labels["elapsed"].setText("-")
        self.stat_value_labels["speed"].setText("-")
        self.stat_value_labels["char_speed"].setText("-")
        self.stat_value_labels["api"].setText("0")
        self.stat_value_labels["token"].setText("0")
        self.stat_value_labels["success"].setText("-")
        self.stat_value_labels["fail"].setText("0")

    def _switch_page(self, key: str):
        self.page_area.takeWidget()
        self.page_area.setWidget(self.pages[key])
        self.nav_task_btn.setChecked(key == "task")
        self.nav_api_btn.setChecked(key == "api")
        self.nav_glossary_btn.setChecked(key == "glossary")
        self.nav_status_btn.setChecked(key == "status")
        self.nav_settings_btn.setChecked(key == "option")
        if key == "glossary":
            self._refresh_glossary_table()

    def _current_provider_key(self) -> str:
        selected = self.provider_combo.currentText()
        for label, key in self.PROVIDERS:
            if label == selected:
                return key
        return "deepseek"

    def _on_provider_change(self):
        provider = self._current_provider_key()
        if provider == "sakura":
            self.api_url_edit.setText("http://127.0.0.1:8080/v1/chat/completions")
            self.model_edit.setText("sakura-v1.0")
        elif provider == "doubao":
            self.api_url_edit.setText("https://ark.cn-beijing.volces.com/api/v3/chat/completions")
            self.model_edit.setText("Doubao-Seed-1.6-flash")
        elif provider == "gemini":
            self.api_url_edit.setText("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            self.model_edit.setText("gemini-2.5-flash")
        elif provider == "glm":
            self.api_url_edit.setText("https://open.bigmodel.cn/api/paas/v4/chat/completions")
            self.model_edit.setText("glm-4-flash")
        elif provider == "custom":
            self.api_url_edit.setText("")
            self.model_edit.setText("")
        else:
            self.api_url_edit.setText("https://api.deepseek.com/chat/completions")
            self.model_edit.setText("deepseek-v4-flash")

        is_custom = provider == "custom"
        self.api_url_edit.setEnabled(is_custom)
        self.api_key_edit.setEnabled(provider != "sakura")
        self._update_provider_capability_hint(provider)
        self._apply_provider_perf_limits(provider)

    def _update_provider_capability_hint(self, provider: str):
        hints = {
            "deepseek": "DeepSeek：推荐用于主力翻译；付费版可使用较高并发和批量。批量 JSON 稳定，译后校对会额外消耗 token。",
            "doubao": "Doubao：火山方舟 OpenAI 兼容接口；请按账号限流能力设置并发和批量。",
            "sakura": "Sakura：本地模型接口，不需要 API Key；速度取决于本机/本地服务性能。",
            "gemini": "Gemini：不支持 DeepSeek 的 thinking 参数；免费版容易触发限流，建议点击“Gemini 免费版”性能预设。",
            "glm": "GLM/智谱：免费版限流明显，建议点击“智谱免费版”性能预设；译后校对建议低并发运行。",
            "custom": "Custom：自定义 OpenAI 兼容接口；请确认模型是否支持批量 JSON、thinking 参数和当前超时设置。",
        }
        label = getattr(self, "provider_capability_label", None)
        if label is not None:
            label.setText(hints.get(provider, ""))

    def _apply_provider_perf_limits(self, provider: str):
        if not hasattr(self, "slider_batch_size"):
            return

        if provider == "glm":
            preset = PERF_UI_PRESETS["glm_free"]
            self.perf_limit_hint.setText(
                f"当前服务商推荐使用“{preset['label']}”预设：{self._format_perf_values(preset['values'])}。"
                "切换服务商不会自动覆盖当前参数，请手动点击预设按钮应用。"
            )
        elif provider == "gemini":
            preset = PERF_UI_PRESETS["gemini_free"]
            self.perf_limit_hint.setText(
                f"当前服务商推荐使用“{preset['label']}”预设：{self._format_perf_values(preset['values'])}。"
                "切换服务商不会自动覆盖当前参数，请手动点击预设按钮应用。"
            )
        elif provider == "deepseek":
            preset = PERF_UI_PRESETS["deepseek_paid"]
            self.perf_limit_hint.setText(
                f"当前服务商推荐使用“{preset['label']}”预设：{self._format_perf_values(preset['values'])}。"
                "切换服务商不会自动覆盖当前参数，请手动点击预设按钮应用。"
            )
        else:
            self.perf_limit_hint.setText("当前为自定义/本地服务商，请按模型限流能力手动调整性能参数。")

        self._update_perf_slider_labels()

    @staticmethod
    def _format_perf_values(values: dict) -> str:
        return (
            f"并发 {values['max_workers']}，批量 {values['batch_size']}，"
            f"批量字符 {values['max_batch_length']}，单条字符 {values['max_text_size_for_batch']}，"
            f"超时 {values['api_timeout']} 秒"
        )

    def _apply_perf_preset(self, preset_key: str):
        preset = PERF_UI_PRESETS.get(preset_key)
        if not preset:
            return
        values = preset["values"]
        self._applying_perf_preset = True
        try:
            self.slider_max_workers.setValue(values["max_workers"])
            self.slider_batch_size.setValue(values["batch_size"])
            self.slider_max_batch_length.setValue(values["max_batch_length"])
            self.slider_max_text_size_for_batch.setValue(values["max_text_size_for_batch"])
            self.slider_api_timeout.setValue(values["api_timeout"])
        finally:
            self._applying_perf_preset = False
        self._set_active_perf_preset(preset_key)
        self.perf_limit_hint.setText(f"已应用“{preset['label']}”预设：{preset['hint']}")
        self._update_perf_slider_labels()

    def _mark_custom_perf(self):
        self._set_active_perf_preset("custom")
        self.perf_limit_hint.setText("已切换为自定义性能参数；当前数值会直接用于下一次翻译。")
        self._update_perf_slider_labels()

    def _on_perf_value_changed(self):
        self._update_perf_slider_labels()
        if not getattr(self, "_applying_perf_preset", False):
            if getattr(self, "_active_perf_preset", "custom") != "custom":
                self._set_active_perf_preset("custom")
                self.perf_limit_hint.setText("参数已手动修改，当前为自定义性能参数。")

    def _set_active_perf_preset(self, preset_key: str):
        self._active_perf_preset = preset_key
        for key, btn in getattr(self, "_perf_preset_buttons", {}).items():
            previous = btn.blockSignals(True)
            btn.setChecked(key == preset_key)
            btn.blockSignals(previous)

    def _update_perf_slider_labels(self):
        self.lbl_max_workers.setText(str(self.slider_max_workers.value()))
        self.lbl_batch_size.setText(str(self.slider_batch_size.value()))
        self.lbl_max_batch_length.setText(str(self.slider_max_batch_length.value()))
        self.lbl_max_text_size_for_batch.setText(str(self.slider_max_text_size_for_batch.value()))
        self.lbl_api_timeout.setText(str(self.slider_api_timeout.value()))

    def _on_theme_changed(self):
        if self.theme_combo.currentIndex() == 1:
            setTheme(Theme.DARK)
            self._setup_styles(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
            self._setup_styles(Theme.LIGHT)

    def _on_thinking_toggle_changed(self):
        if self.enable_thinking_cb.isChecked():
            QMessageBox.information(self, "深度思考设置", "已开启深度思考。注意：响应可能更慢、成本更高。")
        else:
            QMessageBox.information(self, "深度思考设置", "已关闭深度思考（默认推荐）。")

    def _on_input_file_dropped(self, path: str):
        if not os.path.isfile(path):
            QMessageBox.warning(self, "提示", f"文件不存在: {path}")
            return
        self.input_edit.setText(path)
        base = os.path.splitext(os.path.basename(path))[0]
        self.output_edit.setText(os.path.join(os.path.dirname(path), f"{base}_zh.epub"))

    def _on_input_changed(self):
        path = self.input_edit.text().strip()
        if not path or not os.path.exists(path) or not path.lower().endswith(".epub"):
            self._estimate_pending_path = ""
            self.estimate_timer.stop()
            self.estimate_label.setText("预估字符: -")
            return
        self.estimate_label.setText("预估字符: 计算中...")
        self._estimate_pending_path = path
        self.estimate_timer.start(300)

    def _estimate_book_chars(self, book) -> int:
        all_texts = []
        for _, _, tags in iter_text_nodes(book):
            for tag in tags:
                text = tag.get_text(" ", strip=True)
                if text:
                    all_texts.append(text)
        all_texts.extend(extract_toc_titles(book))
        return sum(len(t) for t in all_texts)

    def _start_estimate_chars(self):
        path = self._estimate_pending_path
        if not path or not os.path.exists(path) or not path.lower().endswith(".epub"):
            return
        if self.estimate_thread is not None:
            return

        self._estimate_running_path = path
        thread = QThread(self)
        worker = EstimateCharsWorker(path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_estimate_finished)
        worker.failed.connect(self._on_estimate_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_estimate_worker)
        self.estimate_thread = thread
        self.estimate_worker = worker
        thread.start()

    def _clear_estimate_worker(self):
        finished_path = self._estimate_running_path
        self.estimate_thread = None
        self.estimate_worker = None
        self._estimate_running_path = ""
        current = self.input_edit.text().strip()
        if current and current != finished_path:
            self._estimate_pending_path = current
            QTimer.singleShot(0, self._start_estimate_chars)

    def _on_estimate_finished(self, path: str, total: int):
        if path == self.input_edit.text().strip():
            self.estimate_label.setText(f"预估字符: {total:,}")

    def _on_estimate_failed(self, path: str, detail: str):
        if path == self.input_edit.text().strip():
            self.estimate_label.setText("预估字符: 无法读取")

    def _test_api_connection(self):
        api_key = self.api_key_edit.text().strip()
        api_url = self.api_url_edit.text().strip()
        model = self.model_edit.text().strip()
        provider = self._current_provider_key()

        if not api_key and provider != "sakura":
            QMessageBox.warning(self, "提示", "请先填写 API Key")
            return
        if not api_url:
            QMessageBox.warning(self, "提示", "请先填写 Base URL")
            return
        if not model:
            QMessageBox.warning(self, "提示", "请先填写模型")
            return

        timeout_text = self.api_timeout_edit.text().strip()
        try:
            timeout_seconds = float(timeout_text)
            if timeout_seconds <= 0:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "提示", "测试超时必须是大于0的数字")
            return

        api_url = JaZhTranslator._normalize_api_url(api_url)
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中...")

        def worker():
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            }
            if (not self.enable_thinking_cb.isChecked()) and provider in {"deepseek", "doubao", "glm", "custom"}:
                payload["thinking"] = {"type": "disabled"}

            try:
                resp = requests.post(api_url, headers=headers, json=payload, timeout=timeout_seconds)
                if resp.status_code == 401:
                    self._api_test_signal.result.emit("error", "认证失败", "API Key 无效或已过期")
                elif resp.status_code == 402:
                    self._api_test_signal.result.emit("error", "余额不足", "API 账户余额不足或已欠费")
                elif resp.status_code == 429:
                    self._api_test_signal.result.emit("warn", "限流提示", "API Key 有效，但当前触发限流")
                elif 200 <= resp.status_code < 300:
                    self._api_test_signal.result.emit("info", "连接成功", "API Key 有效，连接测试通过")
                else:
                    self._api_test_signal.result.emit("error", "连接失败", f"HTTP {resp.status_code}\n{resp.text[:200]}")
            except requests.exceptions.Timeout:
                self._api_test_signal.result.emit("error", "连接超时", f"请求超时（{timeout_seconds}秒），请检查网络或 Base URL")
            except requests.exceptions.ConnectionError:
                self._api_test_signal.result.emit("error", "连接失败", "无法连接服务，请检查 Base URL 和网络")
            except Exception as e:
                self._api_test_signal.result.emit("error", "测试异常", str(e))
            finally:
                self._api_test_signal.result.emit("reset", "", "")

        threading.Thread(target=worker, daemon=True).start()

    def pick_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择输入 EPUB", self.default_dir, "EPUB files (*.epub);;All files (*.*)")
        if not path:
            return
        self._on_input_file_dropped(path)

    def pick_output(self):
        current = self.output_edit.text().strip() or "output_zh.epub"
        path, _ = QFileDialog.getSaveFileName(self, "选择输出 EPUB", current, "EPUB files (*.epub);;All files (*.*)")
        if path:
            self.output_edit.setText(path)

    def _build_config(self) -> Optional[TranslateConfig]:
        cfg = TranslateConfig(
            inp=self.input_edit.text().strip(),
            out=self.output_edit.text().strip(),
            api_key=self.api_key_edit.text().strip(),
            provider=self._current_provider_key(),
            api_url=self.api_url_edit.text().strip(),
            model=self.model_edit.text().strip(),
            extract_glossary=self.extract_glossary_cb.isChecked(),
            enable_glossary=self.enable_glossary_cb.isChecked(),
            max_workers=self.slider_max_workers.value(),
            batch_size=self.slider_batch_size.value(),
            max_batch_length=self.slider_max_batch_length.value(),
            max_text_size_for_batch=self.slider_max_text_size_for_batch.value(),
            api_timeout=self.slider_api_timeout.value(),
            direction="zh" if self.dir_zh.isChecked() else "ja",
            enable_thinking=self.enable_thinking_cb.isChecked(),
            enable_proofread=self.enable_proofread_cb.isChecked(),
        )
        if not cfg.inp or not os.path.exists(cfg.inp):
            QMessageBox.critical(self, "错误", "请选择有效的输入 EPUB")
            return None
        if not cfg.out:
            QMessageBox.critical(self, "错误", "请填写输出文件")
            return None
        if cfg.provider in {"deepseek", "doubao", "gemini", "glm", "custom"} and not cfg.api_key:
            QMessageBox.critical(self, "错误", "该提供方需要 API Key")
            return None
        if not cfg.api_url or not cfg.model:
            QMessageBox.critical(self, "错误", "请填写 Base URL 和模型")
            return None
        return cfg


    def _launch_worker(self, cfg: TranslateConfig, resumed: bool = False):
        self._switch_page("status")
        if not resumed:
            self._reset_stat_cards()
            self.rt_src.setText("")
            self.rt_dst.setText("")
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        self.is_paused = False
        self.translation_start_time = time.time()
        self._set_pause_hint("翻译运行中；点击暂停后，会等待当前 API 请求结束并保留已完成缓存。")
        if not resumed:
            self._clear_proofread_details()

        self.worker_thread = QThread(self)
        self.worker = TranslateWorker(cfg)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.item.connect(self._on_item)
        self.worker.proofread_detail.connect(self._on_proofread_detail)
        self.worker.status.connect(self._on_status)
        self.worker.stat_update.connect(self._on_stat_update)
        self.worker.error_detail.connect(self._on_error_detail)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)

        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self.worker_thread.start()

    def start(self):
        cfg = self._build_config()
        if not cfg:
            return
        self.last_task_cfg = cfg
        self._launch_worker(cfg, resumed=False)

    def resume(self):
        if not self.is_paused:
            QMessageBox.information(self, "提示", "当前没有可恢复的暂停任务")
            return
        cfg = self._build_config()
        if not cfg:
            return
        if self.last_task_cfg and (cfg.inp != self.last_task_cfg.inp or cfg.out != self.last_task_cfg.out):
            QMessageBox.warning(self, "提示", "恢复时请保持输入/输出文件不变")
            return
        self.last_task_cfg = cfg
        self._on_status("正在恢复翻译（断点续译）...")
        self._launch_worker(cfg, resumed=True)

    def cancel(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)
        self._set_pause_hint("正在暂停：等待当前 API 请求结束；缓存已尽量写入，可切换模型后恢复。")
        self._on_status("正在暂停，当前请求结束后停止；可切换模型后点击恢复继续")

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_stat_update(self, completed: int, total: int, terms: int, api_total: int, fail_count: int, success_rate: float, speed: int, char_speed: int, _chars: int, token_total: int):
        self.stat_value_labels["completed"].setText(str(completed))
        self.stat_value_labels["total"].setText(str(total))
        self.stat_value_labels["terms"].setText(str(terms))
        elapsed_seconds = max(0.0, time.time() - self.translation_start_time)
        if completed >= total and total > 0:
            remaining = 0
        elif completed > 0 and total > 0:
            remaining = max(0, int((elapsed_seconds / completed) * (total - completed)))
        else:
            remaining = -1
        self.stat_value_labels["elapsed"].setText(self._format_elapsed(remaining) if remaining >= 0 else "-")
        self.stat_value_labels["speed"].setText(str(speed))
        self.stat_value_labels["char_speed"].setText(str(char_speed))
        self.stat_value_labels["api"].setText(str(api_total))
        self.stat_value_labels["token"].setText(str(token_total))
        self.stat_value_labels["success"].setText(f"{success_rate:.1f}%")
        self.stat_value_labels["fail"].setText(str(fail_count))

    def _on_progress(self, completed: int, total: int, total_chars: int):
        ratio = int((completed * 100 / total) if total else 0)
        self.progress_bar.setValue(ratio)
        self.progress_pct.setText(f"{ratio}%")
        elapsed = self._format_elapsed(time.time() - self.translation_start_time)
        translated_chars = int((completed / total) * total_chars) if total > 0 else 0
        self.stats_label.setText(f"实时翻译字数 {translated_chars}/{total_chars} | 耗时 {elapsed}")

    def _on_item(self, src: str, dst: str):
        self.rt_src.setText(src)
        self.rt_dst.setText(dst)
        if not self.last_error_text.toPlainText().strip():
            self.last_error_text.setPlainText("")

    def _on_proofread_detail(self, detail: dict):
        self._proofread_detail_count += 1
        issues = detail.get("issues") or []
        if isinstance(issues, str):
            issues = [issues]
        reason = "；".join(str(issue) for issue in issues if str(issue).strip()) or "-"
        japanese_residue = "是" if detail.get("japanese_residue") else "否"
        glossary_mismatch = "是" if detail.get("glossary_mismatch") else "否"
        block = "\n".join(
            [
                f"#{self._proofread_detail_count} 译后校对",
                f"可疑原因: {reason}",
                f"日文残留触发: {japanese_residue}",
                f"术语不一致触发: {glossary_mismatch}",
                "原文:",
                str(detail.get("original", "")),
                "初译:",
                str(detail.get("draft", "")),
                "校对后译文:",
                str(detail.get("revised", "")),
                "-" * 48,
            ]
        )
        self.proofread_detail_text.appendPlainText(block)
        text = self.proofread_detail_text.toPlainText()
        if len(text) > 30000:
            self.proofread_detail_text.setPlainText(text[-30000:])

    def _on_status(self, text: str):
        self.stats_label.setText(text)

    def _set_pause_hint(self, text: str):
        label = getattr(self, "pause_hint_label", None)
        if label is not None:
            label.setText(text)

    def _play_completion_voice(self):
        message = "\u4f60\u597d\uff0c\u5df2\u5b8c\u6210"
        if os.name != "nt":
            QApplication.beep()
            return

        try:
            escaped_message = message.replace("'", "''")
            ps_command = (
                "Add-Type -AssemblyName System.Speech;"
                "$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "$speaker.Rate = 0;"
                f"$speaker.Speak('{escaped_message}');"
            )
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-Command",
                    ps_command,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            QApplication.beep()


    def _on_finished(self, out_path: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if out_path == CANCELLED_RESULT:
            self.is_paused = True
            self.resume_btn.setEnabled(True)
            self._set_pause_hint("已暂停：可以切换模型或调整参数，然后点击“恢复”继续；已完成内容会命中缓存。")
            self._on_status("已暂停，可切换模型后点击恢复继续；已翻译内容将命中缓存")
            QMessageBox.information(self, "已暂停", "翻译已暂停。可切换模型后点击恢复继续，已翻译内容会保留。")
            return

        self.is_paused = False
        self.resume_btn.setEnabled(False)
        self._set_pause_hint("翻译已完成。再次翻译同一内容会优先命中缓存。")
        self.progress_bar.setValue(100)
        self.progress_pct.setText("100%")
        self.output_edit.setText(out_path)
        self._play_completion_voice()
        QMessageBox.information(self, "完成", f"翻译完成\n输出文件: {out_path}")

    def _on_failed(self, detail: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.is_paused = False
        self._set_pause_hint("任务已停止。可检查错误详情，调整模型或参数后重新开始。")
        if "HTTP 421" in detail or "HTTP 429" in detail:
            QMessageBox.warning(
                self,
                "警告",
                "遇到 421/429 限流或配额问题。\n可直接再次开始或点恢复继续，已翻译内容会命中缓存。",
            )
            self._on_status("接口限流或配额不足，任务已停止；可调整模型/参数后继续")
            return
        QMessageBox.critical(self, "错误", f"翻译失败\n{detail}")

    def _on_error_detail(self, detail: str):
        self.last_error_text.setPlainText(detail[:20000] if detail else "")

    def _clear_proofread_details(self):
        self._proofread_detail_count = 0
        proofread_text = getattr(self, "proofread_detail_text", None)
        if proofread_text is not None:
            proofread_text.setPlainText("")

    def _clear_runtime_stats(self):
        self._reset_stat_cards()
        self.progress_bar.setValue(0)
        self.progress_pct.setText("0%")
        self.stats_label.setText("状态: 已清空")
        self.rt_src.setText("")
        self.rt_dst.setText("")
        self.last_error_text.setPlainText("")
        self._clear_proofread_details()

    def _build_masked_config_snapshot(self) -> dict:
        api_key = self.api_key_edit.text().strip()
        masked_key = ""
        if api_key:
            if len(api_key) <= 8:
                masked_key = "*" * len(api_key)
            else:
                masked_key = f"{api_key[:4]}***{api_key[-4:]}"
        return {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "provider": self._current_provider_key(),
            "api_url": self.api_url_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "api_key_masked": masked_key,
            "max_workers": self.slider_max_workers.value(),
            "batch_size": self.slider_batch_size.value(),
            "max_batch_length": self.slider_max_batch_length.value(),
            "max_text_size_for_batch": self.slider_max_text_size_for_batch.value(),
            "api_timeout": self.slider_api_timeout.value(),
            "direction": "zh" if self.dir_zh.isChecked() else "ja",
            "enable_glossary": self.enable_glossary_cb.isChecked(),
            "extract_glossary": self.extract_glossary_cb.isChecked(),
            "enable_proofread": self.enable_proofread_cb.isChecked(),
            "api_test_timeout_seconds": self.api_timeout_edit.text().strip(),
            "input_file": self.input_edit.text().strip(),
            "output_file": self.output_edit.text().strip(),
            "last_error_preview": self.last_error_text.toPlainText()[:4000],
        }

    def _export_diagnostic_bundle(self):
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出诊断包",
            str(Path(self.default_dir) / f"diagnostic_{time.strftime('%Y%m%d_%H%M%S')}.zip"),
            "ZIP files (*.zip);;All files (*.*)",
        )
        if not save_path:
            return

        try:
            data_dir = get_data_dir()
            logs_dir = data_dir / "logs"
            cfg = self._build_masked_config_snapshot()

            with zipfile.ZipFile(save_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("config_snapshot.json", json.dumps(cfg, ensure_ascii=False, indent=2))
                if logs_dir.exists():
                    for p in sorted(logs_dir.glob("app-*.log"))[-10:]:
                        zf.write(p, arcname=f"logs/{p.name}")
                glossary_path = data_dir / "glossary.json"
                if glossary_path.exists():
                    zf.write(glossary_path, arcname="glossary.json")
            QMessageBox.information(self, "完成", f"诊断包导出成功:\n{save_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出诊断包失败:\n{e}")

    def _glossary_path(self) -> Path:
        return get_data_dir() / "glossary.json"

    def _load_glossary_rows(self):
        glossary_path = self._glossary_path()
        return load_glossary_rows(glossary_path), glossary_path

    def _refresh_glossary_table(self):
        table = getattr(self, "glossary_table", None)
        label = getattr(self, "glossary_summary_label", None)
        if table is None or label is None:
            return

        if self.glossary_load_thread is not None:
            return

        self._glossary_all_rows = []
        self._glossary_pending_rows = []
        self._glossary_populate_index = 0
        self._glossary_table_dirty = False
        table.clearContents()
        table.setRowCount(0)
        label.setText("正在加载术语表...")

        thread = QThread(self)
        worker = GlossaryLoadWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_glossary_load_finished)
        worker.failed.connect(self._on_glossary_load_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_glossary_load_worker)

        self.glossary_load_thread = thread
        self.glossary_load_worker = worker
        thread.start()

    def _clear_glossary_load_worker(self):
        self.glossary_load_thread = None
        self.glossary_load_worker = None

    def _on_glossary_load_failed(self, detail: str):
        table = getattr(self, "glossary_table", None)
        label = getattr(self, "glossary_summary_label", None)
        if table is not None:
            table.setRowCount(0)
        if label is not None:
            label.setText(f"术语表读取失败: {detail}")

    def _on_glossary_load_finished(self, rows, glossary_path: str):
        table = getattr(self, "glossary_table", None)
        label = getattr(self, "glossary_summary_label", None)
        if table is None or label is None:
            return

        self._glossary_all_rows = list(rows)
        self._glossary_table_dirty = False
        self._apply_glossary_filters()

    def _apply_glossary_filters(self):
        table = getattr(self, "glossary_table", None)
        label = getattr(self, "glossary_summary_label", None)
        if table is None or label is None:
            return

        if self._glossary_table_dirty:
            self._merge_visible_glossary_edits()

        query = ""
        search_edit = getattr(self, "glossary_search_edit", None)
        if search_edit is not None:
            query = search_edit.text().strip().lower()

        category_filter = "全部分类"
        category_combo = getattr(self, "glossary_category_combo", None)
        if category_combo is not None:
            category_filter = category_combo.currentText()

        source_filter = "全部来源"
        source_combo = getattr(self, "glossary_source_combo", None)
        if source_combo is not None:
            source_filter = source_combo.currentText()

        filtered = []
        for row_idx, row in enumerate(self._glossary_all_rows):
            category, original, translation, note = row
            if category_filter != "全部分类" and category != category_filter:
                continue
            if source_filter != "全部来源" and source_filter not in note:
                continue
            if query and query not in " ".join(row).lower():
                continue
            filtered.append((row_idx, row))

        self._set_glossary_display_rows(filtered, total_rows=len(self._glossary_all_rows))

    def _set_glossary_display_rows(self, rows, total_rows: int):
        table = getattr(self, "glossary_table", None)
        label = getattr(self, "glossary_summary_label", None)
        if table is None or label is None:
            return

        self._glossary_pending_rows = list(rows)
        self._glossary_populate_index = 0
        self._glossary_dirty_after_populate = self._glossary_table_dirty
        self._glossary_table_loading = True
        table.clearContents()
        table.setRowCount(0)
        shown = len(self._glossary_pending_rows)
        if shown == total_rows:
            label.setText(f"共 {total_rows} 条术语，正在显示...")
        else:
            label.setText(f"共 {total_rows} 条术语，筛选显示 {shown} 条，正在显示...")
        self._set_glossary_table_editable(self.enable_glossary_cb.isChecked())
        QTimer.singleShot(0, self._populate_glossary_table_chunk)

    def _populate_glossary_table_chunk(self):
        table = getattr(self, "glossary_table", None)
        label = getattr(self, "glossary_summary_label", None)
        if table is None or label is None:
            return

        rows = self._glossary_pending_rows
        start = self._glossary_populate_index
        if start >= len(rows):
            total_rows = len(self._glossary_all_rows)
            if len(rows) == total_rows:
                label.setText(f"共 {total_rows} 条术语")
            else:
                label.setText(f"共 {total_rows} 条术语，筛选显示 {len(rows)} 条")
            self._glossary_table_loading = False
            self._glossary_table_dirty = bool(getattr(self, "_glossary_dirty_after_populate", False))
            self._set_glossary_table_editable(self.enable_glossary_cb.isChecked())
            return

        end = min(start + 300, len(rows))
        table.setUpdatesEnabled(False)
        try:
            table.setRowCount(end)
            for row_idx in range(start, end):
                source_index, row_values = rows[row_idx]
                for col_idx, value in enumerate(row_values):
                    item = QTableWidgetItem(value)
                    item.setData(Qt.UserRole, source_index)
                    item.setToolTip(value)
                    table.setItem(row_idx, col_idx, item)
        finally:
            table.setUpdatesEnabled(True)

        self._glossary_populate_index = end
        total_rows = len(self._glossary_all_rows)
        label.setText(f"正在显示术语 {end}/{len(rows)}")
        if end < len(rows):
            QTimer.singleShot(0, self._populate_glossary_table_chunk)
        else:
            self._glossary_table_loading = False
            self._glossary_table_dirty = bool(getattr(self, "_glossary_dirty_after_populate", False))
            self._set_glossary_table_editable(self.enable_glossary_cb.isChecked())
            if len(rows) == total_rows:
                label.setText(f"共 {total_rows} 条术语")
            else:
                label.setText(f"共 {total_rows} 条术语，筛选显示 {len(rows)} 条")

    def _on_glossary_table_item_changed(self, item):
        if self._glossary_table_loading:
            return
        if not self.enable_glossary_cb.isChecked():
            return
        self._glossary_table_dirty = True
        save_btn = getattr(self, "glossary_save_btn", None)
        if save_btn is not None:
            save_btn.setEnabled(True)

    def _merge_visible_glossary_edits(self):
        table = getattr(self, "glossary_table", None)
        if table is None:
            return
        for row in range(table.rowCount()):
            first_item = table.item(row, 0)
            if first_item is None:
                continue
            source_index = first_item.data(Qt.UserRole)
            if not isinstance(source_index, int) or source_index < 0 or source_index >= len(self._glossary_all_rows):
                continue
            self._glossary_all_rows[source_index] = (
                self._table_text(table, row, 0),
                self._table_text(table, row, 1),
                self._table_text(table, row, 2),
                self._table_text(table, row, 3),
            )

    def _set_glossary_dirty(self, dirty: bool = True):
        self._glossary_table_dirty = dirty
        save_btn = getattr(self, "glossary_save_btn", None)
        if save_btn is not None:
            save_btn.setEnabled(dirty and self.enable_glossary_cb.isChecked())

    def _add_glossary_row(self):
        if not self.enable_glossary_cb.isChecked():
            QMessageBox.information(self, "提示", "请先勾选“启用术语表”，再新增术语。")
            return
        if self._glossary_table_dirty:
            self._merge_visible_glossary_edits()

        category = "Item"
        combo = getattr(self, "glossary_category_combo", None)
        if combo is not None and combo.currentText() in GLOSSARY_CATEGORIES:
            category = combo.currentText()

        self._glossary_all_rows.append((category, "", "", "手动添加"))
        self._set_glossary_dirty(True)

        search = getattr(self, "glossary_search_edit", None)
        if search is not None:
            search.setText("")
        if combo is not None:
            combo.setCurrentText(category)
        source_combo = getattr(self, "glossary_source_combo", None)
        if source_combo is not None:
            source_combo.setCurrentText("全部来源")
        self._apply_glossary_filters()

    def _delete_selected_glossary_rows(self):
        if not self.enable_glossary_cb.isChecked():
            QMessageBox.information(self, "提示", "请先勾选“启用术语表”，再删除术语。")
            return
        table = getattr(self, "glossary_table", None)
        if table is None:
            return

        selected_rows = sorted({idx.row() for idx in table.selectedIndexes()})
        if not selected_rows:
            QMessageBox.information(self, "提示", "请先选择要删除的术语行。")
            return

        confirm = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除选中的 {len(selected_rows)} 条术语吗？删除后需要点击“保存修改”才会写入文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._merge_visible_glossary_edits()
        source_indices = []
        for row in selected_rows:
            item = table.item(row, 0)
            if item is None:
                continue
            source_index = item.data(Qt.UserRole)
            if isinstance(source_index, int) and 0 <= source_index < len(self._glossary_all_rows):
                source_indices.append(source_index)

        for source_index in sorted(set(source_indices), reverse=True):
            del self._glossary_all_rows[source_index]

        self._set_glossary_dirty(True)
        self._apply_glossary_filters()

    def _build_glossary_payload_from_rows(self, rows):
        payload = {category: [] for category in GLOSSARY_CATEGORIES}
        for category, original, translation, info in rows:
            category = str(category).strip()
            original = str(original).strip()
            translation = str(translation).strip()
            info = str(info).strip()
            if not original or not translation:
                continue
            if category not in GLOSSARY_CATEGORIES:
                category = "Item"
            info, source = self._parse_glossary_note_source(info)
            entry = {"original": original, "translation": translation}
            if info:
                entry["info"] = info
            if source:
                entry["source"] = source
            payload[category].append(entry)
        return payload

    def _save_glossary_table_edits(self):
        if not self.enable_glossary_cb.isChecked():
            QMessageBox.information(self, "提示", "请先勾选“启用术语表”，再编辑和保存术语。")
            return

        table = getattr(self, "glossary_table", None)
        if table is None:
            return

        self._merge_visible_glossary_edits()
        rows_to_save = self._glossary_all_rows or [
            (
                self._table_text(table, row, 0),
                self._table_text(table, row, 1),
                self._table_text(table, row, 2),
                self._table_text(table, row, 3),
            )
            for row in range(table.rowCount())
        ]

        payload = self._build_glossary_payload_from_rows(rows_to_save)
        normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
        JaZhTranslator._atomic_write_json(self._glossary_path(), normalized)
        self._set_glossary_dirty(False)
        self._set_glossary_table_editable(True)
        self._refresh_glossary_table()
        QMessageBox.information(
            self,
            "完成",
            f"术语表已保存\n有效术语: {stats.get('accepted', 0)}\n跳过重复/无效: {stats.get('skipped', 0)}\n冲突: {stats.get('conflicts', 0)}",
        )

    def export_glossary_json(self):
        table = getattr(self, "glossary_table", None)
        if table is None:
            return
        if self._glossary_table_dirty:
            self._merge_visible_glossary_edits()

        rows_to_export = self._glossary_all_rows or [
            (
                self._table_text(table, row, 0),
                self._table_text(table, row, 1),
                self._table_text(table, row, 2),
                self._table_text(table, row, 3),
            )
            for row in range(table.rowCount())
        ]
        if not rows_to_export:
            QMessageBox.information(self, "提示", "当前没有可导出的术语。")
            return

        default_path = get_data_dir() / f"glossary.backup.{time.strftime('%Y%m%d-%H%M%S')}.json"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出/备份术语表 JSON",
            str(default_path),
            "JSON files (*.json);;All files (*.*)",
        )
        if not save_path:
            return
        if not save_path.lower().endswith(".json"):
            save_path += ".json"

        payload = self._build_glossary_payload_from_rows(rows_to_export)
        normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
        JaZhTranslator._atomic_write_json(save_path, normalized)
        QMessageBox.information(
            self,
            "完成",
            f"术语表已导出\n路径: {save_path}\n有效术语: {stats.get('accepted', 0)}",
        )

    def restore_glossary_backup(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "恢复术语表备份 JSON",
            str(get_data_dir()),
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return

        confirm = QMessageBox.question(
            self,
            "确认恢复",
            "恢复备份会替换当前术语表。当前术语表会先自动备份一份，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                raise ValueError("术语表 JSON 顶层必须是对象")
            normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
            glossary_path = self._glossary_path()
            backup_path = ""
            if glossary_path.exists():
                backup_path = str(get_data_dir() / f"glossary.backup.before_restore.{time.strftime('%Y%m%d-%H%M%S')}.json")
                shutil.copy2(glossary_path, backup_path)
            JaZhTranslator._atomic_write_json(glossary_path, normalized)
            self._set_glossary_dirty(False)
            self._refresh_glossary_table()
            QMessageBox.information(
                self,
                "完成",
                f"术语表已恢复\n有效术语: {stats.get('accepted', 0)}\n跳过重复/无效: {stats.get('skipped', 0)}\n当前文件: {glossary_path}\n替换前备份: {backup_path or 'N/A'}",
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"恢复术语表备份失败:\n{e}")

    @staticmethod
    def _table_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item is not None else ""

    @staticmethod
    def _parse_glossary_note_source(value: str) -> Tuple[str, str]:
        parts = [part.strip() for part in re.split(r"[；;]", value or "") if part.strip()]
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

    def _set_glossary_importing(self, importing: bool):
        default_texts = {
            "glossary_import_page_btn": "增量导入 JSON",
        }
        for name, default_text in default_texts.items():
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(not importing)
                btn.setText("正在导入..." if importing else default_text)

    def _clear_glossary_import_worker(self):
        self.glossary_import_thread = None
        self.glossary_import_worker = None
        self._set_glossary_importing(False)

    def _on_glossary_import_finished(self, added: int, skipped: int, conflicts: int, glossary_path: str, backup_path: str):
        self._refresh_glossary_table()
        QMessageBox.information(
            self,
            "完成",
            f"术语表增量导入完成\n新增: {added}\n跳过(已存在): {skipped}\n冲突: {conflicts}\n目标: {glossary_path}\n备份: {backup_path}",
        )

    def _on_glossary_import_failed(self, detail: str):
        QMessageBox.critical(self, "错误", f"术语表导入失败:\n{detail}")

    def import_glossary_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入术语表 JSON", self.default_dir, "JSON files (*.json);;All files (*.*)")
        if not path:
            return

        if self.glossary_import_thread is not None:
            QMessageBox.information(self, "正在导入", "术语表正在导入中，请等待当前任务完成。")
            return

        self._set_glossary_importing(True)
        self._on_status("正在后台导入术语表...")
        thread = QThread(self)
        worker = GlossaryImportWorker(path)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_glossary_import_finished)
        worker.failed.connect(self._on_glossary_import_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_glossary_import_worker)

        self.glossary_import_thread = thread
        self.glossary_import_worker = worker
        thread.start()

    def _show_api_test_result(self, level: str, title: str, message: str):
        if level == "reset":
            self.test_btn.setEnabled(True)
            self.test_btn.setText("测试连接")
            return
        self._show_themed_message(level, title, message)

    def _show_themed_message(self, level: str, title: str, message: str):
        icon_map = {
            "info": QMessageBox.Information,
            "warn": QMessageBox.Warning,
            "error": QMessageBox.Critical,
        }
        box = QMessageBox(self)
        box.setIcon(icon_map.get(level, QMessageBox.Critical))
        box.setWindowTitle(title)
        box.setText(message)
        box.setStandardButtons(QMessageBox.Ok)
        box.setDefaultButton(QMessageBox.Ok)
        box.setStyleSheet(self.styleSheet())
        self._apply_native_titlebar_theme(getattr(self, "_current_theme", Theme.LIGHT) == Theme.DARK, box)
        box.exec_()


class _ApiTestSignal(QObject):
    result = Signal(str, str, str)
