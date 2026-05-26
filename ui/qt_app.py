import os
import threading
import time
import traceback
import json
import shutil
import zipfile
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

import requests
from bs4 import NavigableString
from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt5.QtGui import QFont, QGuiApplication, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMessageBox,
    QRadioButton,
    QPlainTextEdit,
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


class TranslateWorker(QObject):
    progress = Signal(int, int, int)
    item = Signal(str, str)
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

            results = translator.translate_batch(all_texts, progress_callback=on_progress, item_callback=on_item)

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

            self.finished.emit(cfg.out)
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
        self.setWindowTitle("EPUB 日译中 V3.2beta版")
        self._setup_window_icon()
        self.resize(1140, 780)
        self.setMinimumSize(960, 680)

        self.default_dir = os.getcwd()
        self._base_font_pt = 9
        self._ui_font_pt = 9
        self.translation_start_time = 0.0
        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[TranslateWorker] = None
        self.is_paused = False
        self.last_task_cfg: Optional[TranslateConfig] = None
        self._glm_perf_limited = False
        self._perf_values_before_glm: Optional[dict] = None
        self._api_test_signal = _ApiTestSignal()
        self._api_test_signal.result.connect(self._show_api_test_result)

        self._build_ui()
        self._apply_adaptive_font()
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

        title = StrongBodyLabel("EPUB 日译中 V3.2beta版")
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
            QRadioButton {{ color: {radio_color}; }}
            DropLineEdit[dragging="true"] {{ border: 2px solid {drag_border}; background: {drag_bg}; }}
            """
        )
        self.rt_dst.setStyleSheet(f"color:{rt_color};")
        self._apply_native_titlebar_theme(theme == Theme.DARK)

    def _apply_native_titlebar_theme(self, dark: bool):
        """Best-effort dark title bar on Windows 10/11."""
        if os.name != "nt" or ctypes is None:
            return
        try:
            hwnd = int(self.winId())
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
        font = QFont(combo.font())
        font.setPointSize(self._ui_font_pt)
        combo.setFont(font)
        view_getter = getattr(combo, "view", None)
        view = view_getter() if callable(view_getter) else None
        if view is not None:
            view.setFont(font)

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

        self.provider_combo = ComboBox()
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
        layout.addWidget(card)
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

        # 使用 balanced 预设作为默认值
        default_cfg = PERFORMANCE_PRESETS["balanced"]
        self.slider_max_workers.setValue(default_cfg["max_workers"])
        self.slider_batch_size.setValue(default_cfg["batch_size"])
        self.slider_max_batch_length.setValue(default_cfg["max_batch_length"])
        self.slider_max_text_size_for_batch.setValue(default_cfg["max_text_size_for_batch"])
        self.slider_api_timeout.setValue(120)

        self.lbl_max_workers = BodyLabel("")
        self.lbl_batch_size = BodyLabel("")
        self.lbl_max_batch_length = BodyLabel("")
        self.lbl_max_text_size_for_batch = BodyLabel("")
        self.lbl_api_timeout = BodyLabel("")

        for slider in [
            self.slider_max_workers,
            self.slider_batch_size,
            self.slider_max_batch_length,
            self.slider_max_text_size_for_batch,
            self.slider_api_timeout,
        ]:
            slider.valueChanged.connect(self._update_perf_slider_labels)

        for title, slider, label in [
            ("并发数", self.slider_max_workers, self.lbl_max_workers),
            ("批量大小", self.slider_batch_size, self.lbl_batch_size),
            ("批量字符上限", self.slider_max_batch_length, self.lbl_max_batch_length),
            ("单条字符上限", self.slider_max_text_size_for_batch, self.lbl_max_text_size_for_batch),
            ("超时(秒)", self.slider_api_timeout, self.lbl_api_timeout),
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

        glossary_card = self._make_card("术语设置")
        row3_l = QHBoxLayout()
        self.extract_glossary_cb = CheckBox("自动提取术语（实验）")
        self.enable_glossary_cb = CheckBox("启用术语表")
        self.import_glossary_btn = PushButton("导入术语表 JSON")
        self.import_glossary_btn.clicked.connect(self.import_glossary_json)
        self.enable_glossary_cb.setChecked(True)
        row3_l.addWidget(self.import_glossary_btn)
        row3_l.addWidget(self.extract_glossary_cb)
        row3_l.addWidget(self.enable_glossary_cb)
        row3_l.addStretch(1)
        glossary_card.layout().addLayout(row3_l)
        glossary_card.layout().addWidget(CaptionLabel(f"默认术语表路径: {get_data_dir() / 'glossary.json'}"))
        layout.addWidget(glossary_card)

        ui_card = self._make_card("界面与推理设置")
        row4_l = QHBoxLayout()
        self.theme_combo = ComboBox()
        self._sync_combo_font(self.theme_combo)
        self.theme_combo.addItems(["浅色主题", "深色主题"])
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        self.enable_thinking_cb = CheckBox("开启深度思考")
        self.enable_thinking_cb.setChecked(False)
        self.enable_thinking_cb.stateChanged.connect(self._on_thinking_toggle_changed)
        row4_l.addWidget(BodyLabel("主题"))
        row4_l.addWidget(self.theme_combo)
        row4_l.addSpacing(16)
        row4_l.addWidget(self.enable_thinking_cb)
        row4_l.addStretch(1)
        ui_card.layout().addLayout(row4_l)
        ui_card.layout().addWidget(CaptionLabel("默认关闭深度思考；开启后可能更慢、成本更高。"))
        layout.addWidget(ui_card)

        layout.addStretch(1)
        self._update_perf_slider_labels()
        return page

    def _build_status_page(self) -> QWidget:
        page = self._make_page_container()
        layout = page.layout()

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

        layout.addWidget(cards_wrap)

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
        layout.addWidget(progress_card)

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
        layout.addWidget(realtime_card)

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
        layout.addWidget(err_card)

        layout.addStretch(1)
        self._reset_stat_cards()
        return page

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
        self.nav_status_btn.setChecked(key == "status")
        self.nav_settings_btn.setChecked(key == "option")

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
        self._apply_provider_perf_limits(provider)

    def _apply_provider_perf_limits(self, provider: str):
        if not hasattr(self, "slider_batch_size"):
            return

        if provider == "glm":
            if not self._glm_perf_limited:
                self._perf_values_before_glm = {
                    "max_workers": self.slider_max_workers.value(),
                    "batch_size": self.slider_batch_size.value(),
                    "max_batch_length": self.slider_max_batch_length.value(),
                    "max_text_size_for_batch": self.slider_max_text_size_for_batch.value(),
                }

            self.slider_max_workers.setRange(1, 2)
            self.slider_batch_size.setRange(1, 2)
            self.slider_max_batch_length.setRange(1, 500)
            self.slider_max_text_size_for_batch.setRange(1, 150)

            self.slider_max_workers.setValue(min(self.slider_max_workers.value(), 2))
            self.slider_batch_size.setValue(min(self.slider_batch_size.value(), 2))
            self.slider_max_batch_length.setValue(min(self.slider_max_batch_length.value(), 500))
            self.slider_max_text_size_for_batch.setValue(min(self.slider_max_text_size_for_batch.value(), 150))
            self.perf_limit_hint.setText("GLM 已启用限流保护：并发≤2、批量≤2、批量字符≤500、单条字符≤150。")
            self._glm_perf_limited = True
        else:
            self.slider_max_workers.setRange(1, 25)
            self.slider_batch_size.setRange(1, 15)
            self.slider_max_batch_length.setRange(1, 8000)
            self.slider_max_text_size_for_batch.setRange(1, 1000)

            if self._glm_perf_limited and self._perf_values_before_glm:
                self.slider_max_workers.setValue(self._perf_values_before_glm["max_workers"])
                self.slider_batch_size.setValue(self._perf_values_before_glm["batch_size"])
                self.slider_max_batch_length.setValue(self._perf_values_before_glm["max_batch_length"])
                self.slider_max_text_size_for_batch.setValue(self._perf_values_before_glm["max_text_size_for_batch"])
            self._glm_perf_limited = False
            self.perf_limit_hint.setText("")

        self._update_perf_slider_labels()

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
            self.estimate_label.setText("预估字符: -")
            return
        self.estimate_label.setText("预估字符: 计算中...")
        try:
            book = load_book(path)
            total = self._estimate_book_chars(book)
            self.estimate_label.setText(f"预估字符: {total:,}")
        except Exception:
            self.estimate_label.setText("预估字符: 无法读取")

    def _estimate_book_chars(self, book) -> int:
        all_texts = []
        for _, _, tags in iter_text_nodes(book):
            for tag in tags:
                text = tag.get_text(" ", strip=True)
                if text:
                    all_texts.append(text)
        all_texts.extend(extract_toc_titles(book))
        return sum(len(t) for t in all_texts)

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

        self.worker_thread = QThread(self)
        self.worker = TranslateWorker(cfg)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.item.connect(self._on_item)
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

    def _on_status(self, text: str):
        self.stats_label.setText(text)


    def _on_finished(self, out_path: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if out_path == CANCELLED_RESULT:
            self.is_paused = True
            self.resume_btn.setEnabled(True)
            self._on_status("已暂停，可切换模型后点击恢复继续；已翻译内容将命中缓存")
            QMessageBox.information(self, "已暂停", "翻译已暂停。可切换模型后点击恢复继续，已翻译内容会保留。")
            return

        self.is_paused = False
        self.resume_btn.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_pct.setText("100%")
        QMessageBox.information(self, "完成", f"翻译完成\n输出文件: {out_path}")

    def _on_failed(self, detail: str):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        self.is_paused = False
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

    def _clear_runtime_stats(self):
        self._reset_stat_cards()
        self.progress_bar.setValue(0)
        self.progress_pct.setText("0%")
        self.stats_label.setText("状态: 已清空")
        self.rt_src.setText("")
        self.rt_dst.setText("")
        self.last_error_text.setPlainText("")

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

    def import_glossary_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "导入术语表 JSON", self.default_dir, "JSON files (*.json);;All files (*.*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"读取 JSON 失败:\n{e}")
            return
        if not isinstance(payload, dict):
            QMessageBox.critical(self, "错误", "术语表 JSON 顶层必须是对象")
            return

        normalized_glossary, import_stats = JaZhTranslator.normalize_glossary_payload(payload)
        data_dir = get_data_dir()
        glossary_path = data_dir / "glossary.json"
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = data_dir / f"glossary.backup.before_import.{timestamp}.json"

        try:
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

            added = merge_stats.get("added", 0)
            skipped = merge_stats.get("skipped", 0)
            conflicts = merge_stats.get("conflicts", 0)
            QMessageBox.information(
                self,
                "完成",
                f"术语表增量导入完成\n新增: {added}\n跳过(已存在): {skipped}\n冲突: {conflicts}\n目标: {glossary_path}\n备份: {backup_path if has_existing else 'N/A'}",
            )
        except Exception as e:
            QMessageBox.critical(self, "错误", f"术语表导入失败:\n{e}")

    def _show_api_test_result(self, level: str, title: str, message: str):
        if level == "reset":
            self.test_btn.setEnabled(True)
            self.test_btn.setText("测试连接")
            return
        if level == "info":
            QMessageBox.information(self, title, message)
        elif level == "warn":
            QMessageBox.warning(self, title, message)
        else:
            QMessageBox.critical(self, title, message)


class _ApiTestSignal(QObject):
    result = Signal(str, str, str)
