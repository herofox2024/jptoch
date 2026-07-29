"""
Tkinter UI（已归档）

此文件为旧版 Tk 界面，自 2026-05 起：
- 不再新增功能，仅接受阻断性 bug 修复
- 主入口为 QML/V4：experimental/qml_v4/main.py
- 新功能开发请修改 experimental/qml_v4/

启动方式（仅用于兼容测试）：
    python archived/tk_v1/app.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import logging
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback
import json
import shutil

try:
    from tkinterdnd2 import TkinterDnD  # optional
except Exception:
    TkinterDnD = None

from bs4 import NavigableString

from epub_io import (
    apply_toc_translations,
    extract_toc_titles,
    iter_text_nodes,
    load_book,
    save_book,
)
from translator import JaZhTranslator, get_data_dir, PERFORMANCE_PRESETS
from text_utils import is_translatable

logger = logging.getLogger(__name__)

# ── 主题配色 ──────────────────────────────────────────────
THEME = {
    "bg":          "#f5f6fa",
    "sidebar":     "#2c3e50",
    "sidebar_text":"#ecf0f1",
    "sidebar_active": "#3498db",
    "card_bg":     "#ffffff",
    "card_border": "#dcdde1",
    "text":        "#2f3542",
    "text_light":  "#636e72",
    "accent":      "#3498db",
    "success":     "#2ecc71",
    "warning":     "#f39c12",
    "danger":      "#e74c3c",
    "progress_bg": "#dfe6e9",
}


def setup_logging():
    """配置日志输出到控制台和文件。"""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)

    data_dir = get_data_dir()
    logs_dir = data_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"app-{time.strftime('%Y%m%d')}.log"

    if not any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(log_path)
        for h in root.handlers
    ):
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)

    logger.info(f"日志文件: {log_path}")


class App((TkinterDnD.Tk if TkinterDnD is not None else tk.Tk)):
    def __init__(self):
        super().__init__()
        self.title("EPUB 日译中翻译器")
        self.geometry("1020x640")
        self.minsize(860, 560)
        self.configure(bg=THEME["bg"])
        self.default_dir = os.getcwd()

        self._running_event = threading.Event()
        self.completed = False
        self.translator = None
        self.cancel_event = threading.Event()
        self.translation_start_time = 0.0

        # ── 变量 ──
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output_zh.epub")
        self.api_key_var = tk.StringVar(value="")
        self.provider_var = tk.StringVar(value="deepseek")
        self.provider_display_var = tk.StringVar(value="DeepSeek")
        self.api_url_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="")
        self.estimate_var = tk.StringVar(value="预估字符: -")
        self.realtime_src_var = tk.StringVar(value="")
        self.realtime_dst_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)
        self.direction_var = tk.StringVar(value="zh")
        self.extract_glossary_var = tk.BooleanVar(value=False)
        self.enable_glossary_var = tk.BooleanVar(value=False)
        self.preset_var = tk.StringVar(value="default")
        self._estimate_after_id = None
        self._estimate_seq = 0

        # 统计卡片变量
        self.stat_completed_var = tk.StringVar(value="0")
        self.stat_total_var = tk.StringVar(value="0")
        self.stat_elapsed_var = tk.StringVar(value="00:00")
        self.stat_speed_var = tk.StringVar(value="-")
        self.stat_api_var = tk.StringVar(value="0")
        self.stat_success_var = tk.StringVar(value="-")
        self.stat_fail_var = tk.StringVar(value="0")
        self.stat_terms_var = tk.StringVar(value="0")

        self.input_var.trace_add("write", self._on_input_var_change)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 属性 ──
    @property
    def running(self) -> bool:
        return self._running_event.is_set()

    @running.setter
    def running(self, value: bool):
        if value:
            self._running_event.set()
        else:
            self._running_event.clear()

    # ── 线程辅助 ──
    def _run_on_ui_thread(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def _set_status(self, text: str):
        logger.info(f"[状态] {text}")

    def _set_progress(self, value: float):
        self._run_on_ui_thread(self.progress_var.set, value)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        seconds = max(0, int(seconds))
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _build_stats_text(self, completed: int, total: int, total_chars: int) -> str:
        elapsed = self._format_elapsed(time.time() - self.translation_start_time)
        stats = self.translator.get_stats() if self.translator else {}
        api_total = stats.get("api_requests_total", 0)
        batch_total = stats.get("batch_total", 0)
        batch_json_ok = stats.get("batch_json_success", 0)
        batch_delim_ok = stats.get("batch_delimiter_success", 0)
        batch_fb = stats.get("batch_fallback", 0)
        batch_json_fail = stats.get("batch_json_parse_fail", 0)
        terms_added = stats.get("glossary_new_terms_added", 0)
        batch_ok = batch_json_ok + batch_delim_ok
        batch_ok_rate = (batch_ok * 100.0 / batch_total) if batch_total else 100.0
        batch_json_ok_rate = (batch_json_ok * 100.0 / batch_total) if batch_total else 100.0
        batch_fb_rate = (batch_fb * 100.0 / batch_total) if batch_total else 0.0
        status_prefix = "翻译完成" if completed >= total else "翻译中..."
        return (
            f"{status_prefix} {completed}/{total} | 字符:{total_chars} | 耗时:{elapsed} | "
            f"批量成功率:{batch_ok_rate:.1f}% | JSON成功率:{batch_json_ok_rate:.1f}% | 回退率:{batch_fb_rate:.1f}% | "
            f"JSON失败:{batch_json_fail} | API请求:{api_total} | 新增术语:{terms_added}"
        )

    def _show_info(self, title: str, message: str):
        self._run_on_ui_thread(messagebox.showinfo, title, message)

    def _show_error(self, title: str, message: str):
        self._run_on_ui_thread(messagebox.showerror, title, message)

    def _reset_buttons_async(self):
        self._run_on_ui_thread(self._reset_buttons)

    # ════════════════════════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════════════════════════
    def _build_ui(self):
        # ── 左侧导航栏 ──
        self.sidebar = tk.Frame(self, bg=THEME["sidebar"], width=160)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        tk.Label(
            self.sidebar, text="EPUB 翻译器 V2.0.1", bg=THEME["sidebar"],
            fg="white", font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(pady=(18, 24))

        self._nav_buttons = []
        nav_items = [
            ("task",   "任务"),
            ("api",    "接口配置"),
            ("option", "翻译选项"),
            ("status", "状态监控"),
        ]
        for key, label in nav_items:
            btn = tk.Button(
                self.sidebar, text=label, anchor="w", padx=18,
                font=("Microsoft YaHei UI", 10),
                bg=THEME["sidebar"], fg=THEME["sidebar_text"],
                activebackground=THEME["sidebar_active"], activeforeground="white",
                bd=0, cursor="hand2",
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons.append((key, btn))

        # ── 右侧内容区 ──
        self.content = tk.Frame(self, bg=THEME["bg"])
        self.content.pack(side="left", fill="both", expand=True)

        self.pages = {}
        for key in ("task", "api", "option", "status"):
            page = tk.Frame(self.content, bg=THEME["bg"])
            self.pages[key] = page

        self._build_task_page(self.pages["task"])
        self._build_api_page(self.pages["api"])
        self._build_option_page(self.pages["option"])
        self._build_status_page(self.pages["status"])

        self._show_page("task")

    # ── 页面切换 ──
    def _show_page(self, key: str):
        for k, page in self.pages.items():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=20, pady=14)
        for k, btn in self._nav_buttons:
            if k == key:
                btn.configure(bg=THEME["sidebar_active"], fg="white")
            else:
                btn.configure(bg=THEME["sidebar"], fg=THEME["sidebar_text"])

    # ── 卡片容器辅助 ──
    @staticmethod
    def _make_card(parent, title: str) -> tk.LabelFrame:
        card = tk.LabelFrame(
            parent, text=f"  {title}  ", bg=THEME["card_bg"],
            fg=THEME["text"], font=("Microsoft YaHei UI", 10, "bold"),
            padx=12, pady=10, bd=1, relief="groove",
        )
        return card

    # ── 任务页面 ──
    def _build_task_page(self, parent):
        card = self._make_card(parent, "文件设置")
        card.pack(fill="x", pady=(0, 10))

        pad = {"padx": 8, "pady": 6}

        tk.Label(card, text="输入 EPUB:", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", **pad)
        self.input_entry = tk.Entry(card, textvariable=self.input_var, font=("Microsoft YaHei UI", 9))
        self.input_entry.grid(row=0, column=1, sticky="ew", **pad)
        if TkinterDnD is not None:
            self.input_entry.drop_target_register("DND_Files")
            self.input_entry.dnd_bind("<<Drop>>", self._on_input_drop)
            self.input_entry.dnd_bind("<<DnDEnter>>", self._on_input_drag_enter)
            self.input_entry.dnd_bind("<<DnDLeave>>", self._on_input_drag_leave)
        tk.Button(card, text="选择...", command=self.pick_input, width=8, cursor="hand2").grid(row=0, column=2, **pad)
        tk.Label(card, textvariable=self.estimate_var, fg=THEME["text_light"], bg=THEME["card_bg"], anchor="w", font=("Microsoft YaHei UI", 8)).grid(row=0, column=3, sticky="w", **pad)

        tk.Label(card, text="输出 EPUB:", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", **pad)
        self.output_entry = tk.Entry(card, textvariable=self.output_var, font=("Microsoft YaHei UI", 9))
        self.output_entry.grid(row=1, column=1, sticky="ew", **pad)
        tk.Button(card, text="选择...", command=self.pick_output, width=8, cursor="hand2").grid(row=1, column=2, **pad)

        card.columnconfigure(1, weight=1)

        # 操作按钮
        btn_card = self._make_card(parent, "操作")
        btn_card.pack(fill="x", pady=(0, 10))

        btn_frame = tk.Frame(btn_card, bg=THEME["card_bg"])
        btn_frame.pack(fill="x")

        self.start_btn = tk.Button(
            btn_frame, text="▶ 开始翻译", command=self.start, width=14,
            bg=THEME["accent"], fg="white", font=("Microsoft YaHei UI", 10, "bold"),
            activebackground="#2980b9", activeforeground="white", cursor="hand2", bd=0,
        )
        self.start_btn.pack(side="left", padx=(0, 10))

        self.cancel_btn = tk.Button(
            btn_frame, text="取消", command=self.cancel, width=8,
            state="disabled", cursor="hand2",
        )
        self.cancel_btn.pack(side="left")

        # 缓存路径
        data_dir = get_data_dir()
        tk.Label(
            parent, text=f"缓存目录: {data_dir}", fg=THEME["text_light"],
            bg=THEME["bg"], font=("Microsoft YaHei UI", 8), anchor="w",
        ).pack(fill="x", pady=(6, 0))

    # ── 接口配置页面 ──
    def _build_api_page(self, parent):
        card = self._make_card(parent, "API 配置")
        card.pack(fill="x", pady=(0, 10))

        pad = {"padx": 8, "pady": 6}

        tk.Label(card, text="服务提供方:", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9)).grid(row=0, column=0, sticky="w", **pad)
        self.provider_combo = ttk.Combobox(
            card, textvariable=self.provider_display_var,
            values=["DeepSeek", "Doubao", "Sakura", "Gemini", "GLM(Zhipu)", "LongCat 2.0", "自定义"],
            state="readonly", width=14,
        )
        self.provider_combo.grid(row=0, column=1, sticky="w", **pad)
        self.provider_combo.bind("<<ComboboxSelected>>", self._on_provider_combo_change)

        tk.Label(card, text="API Key:", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9)).grid(row=1, column=0, sticky="w", **pad)
        tk.Entry(card, textvariable=self.api_key_var, show="*", font=("Microsoft YaHei UI", 9)).grid(row=1, column=1, sticky="ew", **pad)
        self.test_btn = tk.Button(
            card, text="测试连接", command=self._test_api_connection,
            width=8, cursor="hand2",
        )
        self.test_btn.grid(row=1, column=2, **pad)

        tk.Label(card, text="Base URL:", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9)).grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(card, textvariable=self.api_url_var, font=("Microsoft YaHei UI", 9)).grid(row=2, column=1, sticky="ew", **pad)

        tk.Label(card, text="模型名:", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9)).grid(row=3, column=0, sticky="w", **pad)
        tk.Entry(card, textvariable=self.model_var, font=("Microsoft YaHei UI", 9)).grid(row=3, column=1, sticky="ew", **pad)

        card.columnconfigure(1, weight=1)

        self._on_provider_change()

    # ── 翻译选项页面 ──
    def _build_option_page(self, parent):
        # 性能预设
        preset_card = self._make_card(parent, "性能预设")
        preset_card.pack(fill="x", pady=(0, 10))

        pad = {"padx": 8, "pady": 6}
        preset_frame = tk.Frame(preset_card, bg=THEME["card_bg"])
        preset_frame.pack(fill="x", **pad)

        self.preset_combo = ttk.Combobox(
            preset_frame, textvariable=self.preset_var,
            values=["default", "balanced", "extreme"],
            state="readonly", width=14,
        )
        self.preset_combo.pack(side="left")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)

        self.preset_desc_label = tk.Label(
            preset_frame, text=PERFORMANCE_PRESETS["default"]["description"],
            fg=THEME["text_light"], bg=THEME["card_bg"], anchor="w",
            font=("Microsoft YaHei UI", 9),
        )
        self.preset_desc_label.pack(side="left", padx=(12, 0))

        # 翻页方向
        dir_card = self._make_card(parent, "翻页方向")
        dir_card.pack(fill="x", pady=(0, 10))

        dir_frame = tk.Frame(dir_card, bg=THEME["card_bg"])
        dir_frame.pack(fill="x", padx=8, pady=6)
        tk.Radiobutton(
            dir_frame, text="中文习惯（从左到右）", variable=self.direction_var,
            value="zh", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Radiobutton(
            dir_frame, text="保持原版（从右到左）", variable=self.direction_var,
            value="ja", bg=THEME["card_bg"], font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(20, 0))

        # 术语表
        glossary_card = self._make_card(parent, "术语表")
        glossary_card.pack(fill="x", pady=(0, 10))

        glos_frame = tk.Frame(glossary_card, bg=THEME["card_bg"])
        glos_frame.pack(fill="x", padx=8, pady=6)

        self.import_glossary_btn = tk.Button(
            glos_frame, text="导入术语表 JSON", command=self.import_glossary_json,
            width=16, cursor="hand2",
        )
        self.import_glossary_btn.pack(side="left", padx=(0, 12))

        self.extract_glossary_cb = tk.Checkbutton(
            glos_frame, text="自动提取术语（实验）", variable=self.extract_glossary_var,
            onvalue=True, offvalue=False, bg=THEME["card_bg"],
            font=("Microsoft YaHei UI", 9),
        )
        self.extract_glossary_cb.pack(side="left", padx=(0, 12))

        self.enable_glossary_cb = tk.Checkbutton(
            glos_frame, text="启用术语表", variable=self.enable_glossary_var,
            onvalue=True, offvalue=False, bg=THEME["card_bg"],
            font=("Microsoft YaHei UI", 9),
        )
        self.enable_glossary_cb.pack(side="left")

        self.glossary_notice_label = tk.Label(
            glossary_card,
            text=f"提示：开启术语表后默认读取 {get_data_dir() / 'glossary.json'}，token 消耗会翻倍，请谨慎使用。",
            fg=THEME["warning"], bg=THEME["card_bg"], anchor="w",
            justify="left", wraplength=640, font=("Microsoft YaHei UI", 8),
        )
        self.glossary_notice_label.pack(fill="x", padx=8, pady=(0, 4))

    # ── 状态监控页面 ──
    def _build_status_page(self, parent):
        # 统计卡片行
        cards_row = tk.Frame(parent, bg=THEME["bg"])
        cards_row.pack(fill="x", pady=(0, 10))

        stat_items = [
            ("已完成", self.stat_completed_var, THEME["accent"]),
            ("总文本块", self.stat_total_var, THEME["text"]),
            ("新增术语", self.stat_terms_var, THEME["accent"]),
            ("耗时", self.stat_elapsed_var, THEME["text"]),
            ("速度", self.stat_speed_var, THEME["success"]),
            ("API 请求", self.stat_api_var, THEME["text"]),
            ("成功率", self.stat_success_var, THEME["success"]),
            ("失败数", self.stat_fail_var, THEME["danger"]),
        ]
        for i, (label, var, color) in enumerate(stat_items):
            card = tk.Frame(cards_row, bg=THEME["card_bg"], bd=1, relief="groove")
            card.pack(side="left", fill="both", expand=True, padx=3)
            tk.Label(card, text=label, bg=THEME["card_bg"], fg=THEME["text_light"],
                     font=("Microsoft YaHei UI", 8)).pack(pady=(8, 0))
            tk.Label(card, textvariable=var, bg=THEME["card_bg"], fg=color,
                     font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(2, 8))

        # 进度条
        progress_card = self._make_card(parent, "翻译进度")
        progress_card.pack(fill="x", pady=(0, 10))

        self.bar = ttk.Progressbar(progress_card, maximum=100, variable=self.progress_var, length=400)
        self.bar.pack(fill="x", padx=8, pady=8)

        # 实时翻译展示
        rt_card = self._make_card(parent, "实时翻译")
        rt_card.pack(fill="both", expand=True, pady=(0, 10))

        tk.Label(
            rt_card, textvariable=self.realtime_src_var, bg=THEME["card_bg"],
            fg=THEME["text"], anchor="w", justify="left", wraplength=680,
            font=("Microsoft YaHei UI", 9),
        ).pack(fill="x", padx=12, pady=(6, 2))

        tk.Frame(rt_card, bg=THEME["card_border"], height=1).pack(fill="x", padx=12, pady=2)

        tk.Label(
            rt_card, textvariable=self.realtime_dst_var, bg=THEME["card_bg"],
            fg=THEME["accent"], anchor="w", justify="left", wraplength=680,
            font=("Microsoft YaHei UI", 9),
        ).pack(fill="x", padx=12, pady=(2, 6))

    # ════════════════════════════════════════════════════════
    #  事件处理
    # ════════════════════════════════════════════════════════
    # 下拉框显示文本 -> 内部值映射
    _PROVIDER_MAP = {"DeepSeek": "deepseek", "Doubao": "doubao", "Sakura": "sakura", "Gemini": "gemini", "GLM(Zhipu)": "glm", "LongCat 2.0": "longcat", "自定义": "custom"}

    def _on_provider_combo_change(self, event=None):
        display = self.provider_combo.get()
        self.provider_var.set(self._PROVIDER_MAP.get(display, "deepseek"))
        self._on_provider_change()

    def _on_provider_change(self):
        provider = self.provider_var.get().strip().lower()
        if provider == "sakura":
            self.api_url_var.set("http://127.0.0.1:8080/v1/chat/completions")
            self.model_var.set("sakura-v1.0")
        elif provider == "doubao":
            self.api_url_var.set("https://ark.cn-beijing.volces.com/api/v3/chat/completions")
            self.model_var.set("Doubao-Seed-1.6-flash")
        elif provider == "gemini":
            self.api_url_var.set("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            self.model_var.set("gemini-2.5-flash")
        elif provider == "glm":
            self.api_url_var.set("https://open.bigmodel.cn/api/paas/v4/chat/completions")
            self.model_var.set("glm-4-flash")
        elif provider == "longcat":
            self.api_url_var.set("https://api.longcat.chat/openai/v1/chat/completions")
            self.model_var.set("LongCat-2.0")
        elif provider == "custom":
            self.api_url_var.set("")
            self.model_var.set("")
        else:
            self.api_url_var.set("https://api.deepseek.com/chat/completions")
            self.model_var.set("deepseek-v4-flash")

    def _on_preset_change(self, event=None):
        preset = self.preset_var.get()
        preset_config = PERFORMANCE_PRESETS.get(preset, PERFORMANCE_PRESETS["default"])
        self.preset_desc_label.config(text=preset_config["description"])
        if preset == "extreme":
            messagebox.showwarning(
                "高风险警告",
                "【极端模式风险提示】\n\n"
                "1. 高并发可能频繁触发 API 限流（429错误），导致大量重试\n"
                "2. 大批量请求失败时回退代价高，可能反而拖慢整体速度\n"
                "3. 内存占用显著增加，低配电脑可能卡顿\n"
                "4. 单次请求超时风险上升\n\n"
                "建议：仅在付费账户、高配电脑、稳定网络环境下使用。\n"
                "如遇频繁限流，请切回【适中】或【默认】模式。",
            )

    def _test_api_connection(self):
        api_key = self.api_key_var.get().strip()
        api_url = self.api_url_var.get().strip()
        model = self.model_var.get().strip()
        provider = self.provider_var.get().strip().lower()

        if not api_key and provider != "sakura":
            messagebox.showwarning("提示", "请先填写 API Key")
            return
        if not api_url:
            messagebox.showwarning("提示", "请先填写 Base URL")
            return
        if not model:
            messagebox.showwarning("提示", "请先填写模型名")
            return

        api_url = JaZhTranslator._normalize_api_url(api_url)
        self.test_btn.config(state="disabled", text="测试中...")

        def do_test():
            import requests
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 1,
            }
            if provider in {"deepseek", "doubao", "glm"}:
                payload["thinking"] = {"type": "disabled"}

            try:
                resp = requests.post(api_url, headers=headers, json=payload, timeout=15)
                if resp.status_code == 401:
                    self._run_on_ui_thread(
                        messagebox.showerror, "认证失败", "API Key 无效或已过期，请检查后重试。"
                    )
                elif resp.status_code == 402:
                    self._run_on_ui_thread(
                        messagebox.showerror, "余额不足", "API 账户余额不足或已欠费，请充值后重试。"
                    )
                elif resp.status_code == 429:
                    self._run_on_ui_thread(
                        messagebox.showwarning, "限流提示", "API Key 有效，但当前触发限流，请稍后再试。"
                    )
                elif 200 <= resp.status_code < 300:
                    self._run_on_ui_thread(
                        messagebox.showinfo, "连接成功", "API Key 有效，连接测试通过！"
                    )
                else:
                    detail = resp.text[:200]
                    self._run_on_ui_thread(
                        messagebox.showerror, "连接失败", f"HTTP {resp.status_code}\n{detail}"
                    )
            except requests.exceptions.Timeout:
                self._run_on_ui_thread(
                    messagebox.showerror, "连接超时", "请求超时（15秒），请检查网络或 Base URL 是否正确。"
                )
            except requests.exceptions.ConnectionError:
                self._run_on_ui_thread(
                    messagebox.showerror, "连接失败", "无法连接服务器，请检查 Base URL 和网络。"
                )
            except Exception as e:
                self._run_on_ui_thread(
                    messagebox.showerror, "测试异常", str(e)
                )
            finally:
                self._run_on_ui_thread(self.test_btn.config, state="normal", text="测试连接")

        threading.Thread(target=do_test, daemon=True).start()

    @staticmethod
    def _extract_text(tag) -> str:
        return tag.get_text(" ", strip=True)

    @staticmethod
    def _is_translatable(text: str) -> bool:
        return is_translatable(text)

    def pick_input(self):
        path = filedialog.askopenfilename(
            title="选择输入 EPUB",
            initialdir=self.default_dir,
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
        )
        if path:
            self._set_input_path(path)

    def _set_input_path(self, path):
        self.input_var.set(path)
        base = os.path.splitext(os.path.basename(path))[0]
        out_path = os.path.join(os.path.dirname(path), f"{base}_zh.epub")
        self.output_var.set(out_path)
        logger.info(f"选择输入文件: {path}")
        self._schedule_estimate(path)

    def _on_input_drop(self, event):
        raw = event.data
        # tkinterdnd2 返回格式：
        #   单文件（无空格）: {C:/path/to/file.epub}
        #   单文件（有空格）: {C:/path with spaces/file.epub}
        #   多文件: {C:/a.epub} {C:/b.epub}
        # 使用正则提取所有花括号内的路径，取第一个
        import re
        paths = re.findall(r'\{([^}]+)\}', raw)
        if not paths:
            # 无花括号包裹的情况（某些平台）
            paths = raw.strip().split()
        path = paths[0].strip() if paths else ""
        if not path.lower().endswith(".epub"):
            messagebox.showwarning("提示", "请拖入 .epub 文件")
            return
        if not os.path.isfile(path):
            messagebox.showwarning("提示", f"文件不存在: {path}")
            return
        self._set_input_path(path)

    def _on_input_drag_enter(self, event):
        self.input_entry.configure(bg="#d5f5e3")

    def _on_input_drag_leave(self, event):
        self.input_entry.configure(bg="white")

    def pick_output(self):
        current = self.output_var.get().strip()
        initial_dir = os.path.dirname(current) if current and os.path.dirname(current) else self.default_dir
        initial_file = os.path.basename(current) if current else "output_zh.epub"
        path = filedialog.asksaveasfilename(
            title="选择输出 EPUB",
            initialdir=initial_dir,
            initialfile=initial_file,
            defaultextension=".epub",
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
        )
        if path:
            self.output_var.set(path)
            logger.info(f"选择输出文件: {path}")

    def import_glossary_json(self):
        path = filedialog.askopenfilename(
            title="Import Glossary JSON",
            initialdir=self.default_dir,
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read JSON:\n{e}")
            return

        if not isinstance(payload, dict):
            messagebox.showerror("Error", "Glossary JSON 顶层必须是对象")
            return

        normalized_glossary, import_stats = JaZhTranslator.normalize_glossary_payload(payload)
        data_dir = get_data_dir()
        glossary_path = data_dir / "glossary.json"
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = data_dir / f"glossary.backup.before_import.{timestamp}.json"

        try:
            # 读取现有术语表，增量合并
            existing = JaZhTranslator._load_json(str(glossary_path), {}) if glossary_path.exists() else {}
            if existing:
                # 先归一化现有术语表
                existing_normalized, _ = JaZhTranslator.normalize_glossary_payload(existing)
                # 增量合并：新术语追加到已有术语表
                merged, merge_stats = JaZhTranslator.merge_glossaries(existing_normalized, normalized_glossary)
            else:
                merged = normalized_glossary
                merge_stats = {"added": import_stats.get("accepted", 0), "skipped": import_stats.get("skipped", 0), "conflicts": import_stats.get("conflicts", 0)}

            # 备份
            has_existing = glossary_path.exists()
            if has_existing:
                shutil.copy2(glossary_path, backup_path)

            JaZhTranslator._atomic_write_json(glossary_path, merged)

            if self.translator is not None:
                self.translator.replace_glossary(merged)

            added = merge_stats.get("added", 0)
            skipped = merge_stats.get("skipped", 0)
            conflicts = merge_stats.get("conflicts", 0)
            logger.info(
                "Glossary imported: %s -> %s (added=%s skipped=%s conflicts=%s)",
                path, glossary_path, added, skipped, conflicts,
            )
            logger.info(f"术语表增量导入: 新增{added} 跳过{skipped} 冲突{conflicts}")
            messagebox.showinfo(
                "Done",
                f"术语表增量导入完成\n"
                f"新增: {added}\n跳过(已存在): {skipped}\n冲突: {conflicts}\n"
                f"目标: {glossary_path}\n"
                f"备份: {backup_path if has_existing else 'N/A'}",
            )
        except Exception as e:
            logger.error(f"Glossary import failed: {e}")
            messagebox.showerror("Error", f"术语表导入失败:\n{e}")

    def _on_input_var_change(self, *_):
        if self.running:
            return
        path = self.input_var.get().strip()
        self._schedule_estimate(path)

    def _schedule_estimate(self, path: str):
        if self._estimate_after_id is not None:
            try:
                self.after_cancel(self._estimate_after_id)
            except Exception:
                pass
            self._estimate_after_id = None

        if not path or not os.path.exists(path) or not path.lower().endswith(".epub"):
            self.estimate_var.set("预估字符: -")
            return

        self.estimate_var.set("预估字符: 计算中...")
        self._estimate_seq += 1
        seq = self._estimate_seq
        self._estimate_after_id = self.after(500, lambda: self._start_estimate_worker(path, seq))

    def _start_estimate_worker(self, path: str, seq: int):
        self._estimate_after_id = None

        def worker():
            try:
                book = load_book(path)
                total_chars = self._estimate_book_chars(book)
                text = f"预估字符: {total_chars:,}"
            except Exception as e:
                logger.warning(f"EPUB 字符预估失败: {e}")
                text = "预估字符: 无法读取"

            def apply_result():
                if seq == self._estimate_seq and not self.running:
                    self.estimate_var.set(text)

            self._run_on_ui_thread(apply_result)

        threading.Thread(target=worker, daemon=True).start()

    def _estimate_book_chars(self, book) -> int:
        all_texts = []
        for item, soup, tags in iter_text_nodes(book):
            for tag in tags:
                anchors = tag.find_all("a")
                if len(anchors) > 1:
                    for node in tag.find_all(string=True):
                        raw = str(node).strip()
                        if self._is_translatable(raw):
                            all_texts.append(raw)
                    continue

                text = self._extract_text(tag)
                if self._is_translatable(text):
                    all_texts.append(text)

        all_texts.extend(extract_toc_titles(book))
        return sum(len(t) for t in all_texts)

    # ════════════════════════════════════════════════════════
    #  翻译核心逻辑
    # ════════════════════════════════════════════════════════
    def start(self):
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        api_key = self.api_key_var.get().strip()
        provider = self.provider_var.get().strip().lower()
        api_url = self.api_url_var.get().strip()
        model = self.model_var.get().strip()
        extract_glossary = bool(self.extract_glossary_var.get())
        enable_glossary = bool(self.enable_glossary_var.get())

        if not inp or not os.path.exists(inp):
            messagebox.showerror("错误", "请选择有效的输入 EPUB")
            return
        if not out:
            messagebox.showerror("错误", "请填写输出文件名")
            return
        if provider in {"deepseek", "doubao", "gemini", "glm", "longcat", "custom"} and not api_key:
            if provider == "deepseek":
                provider_name = "DeepSeek"
            elif provider == "doubao":
                provider_name = "Doubao"
            elif provider == "gemini":
                provider_name = "Gemini"
            elif provider == "glm":
                provider_name = "GLM"
            elif provider == "longcat":
                provider_name = "LongCat 2.0"
            else:
                provider_name = "自定义"
            messagebox.showerror("错误", f"请填写 {provider_name} API Key")
            return
        if not api_url:
            messagebox.showerror("错误", "请填写 Base URL")
            return
        if not model:
            messagebox.showerror("错误", "请填写模型名")
            return

        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.running = True
        self.completed = False
        self.cancel_event.clear()
        self.translation_start_time = time.time()

        # 切换到状态监控页
        self._show_page("status")

        thread = threading.Thread(
            target=self.run_translate,
            args=(inp, out, api_key, provider, api_url, model, extract_glossary, enable_glossary),
            daemon=True,
        )
        thread.start()
        logger.info(f"开始翻译: {inp} -> {out}")

    def cancel(self):
        self.running = False
        self.cancel_event.set()
        logger.info("正在取消...")
        logger.info("用户请求取消翻译")

    def _on_close(self):
        if self.running:
            if messagebox.askyesno("确认", "翻译正在进行中，确定要退出吗？"):
                self.running = False
                self.cancel_event.set()
                if self.translator:
                    self.translator.flush_cache()
            else:
                return
        elif self.completed:
            if not messagebox.askyesno("确认", "翻译已完成，是否退出？"):
                return

        if self.translator:
            try:
                self.translator.flush_cache()
            except Exception as e:
                logger.error(f"保存缓存失败: {e}")

        self.destroy()

    def _update_stat_cards(self, completed: int, total: int, total_chars: int):
        """更新状态监控页的统计卡片。"""
        elapsed_sec = time.time() - self.translation_start_time
        self.stat_completed_var.set(str(completed))
        self.stat_total_var.set(str(total))
        self.stat_elapsed_var.set(self._format_elapsed(elapsed_sec))
        if elapsed_sec > 0 and total_chars > 0:
            chars_per_sec = total_chars / elapsed_sec * (completed / total) if total > 0 else 0
            self.stat_speed_var.set(f"{chars_per_sec:.0f} 字/秒")
        stats = self.translator.get_stats() if self.translator else {}
        self.stat_api_var.set(str(stats.get("api_requests_total", 0)))
        self.stat_terms_var.set(str(stats.get("glossary_new_terms_added", 0)))
        batch_total = stats.get("batch_total", 0)
        batch_ok = stats.get("batch_json_success", 0) + stats.get("batch_delimiter_success", 0)
        if batch_total > 0:
            self.stat_success_var.set(f"{batch_ok * 100.0 / batch_total:.1f}%")
        else:
            self.stat_success_var.set("-")
        self.stat_fail_var.set(str(stats.get("batch_json_parse_fail", 0)))

    def _update_realtime(self, src: str, dst: str):
        """更新实时翻译显示。"""
        # 截断超长文本，只显示前 200 字符
        src_display = src[:200] + "..." if len(src) > 200 else src
        dst_display = dst[:200] + "..." if len(dst) > 200 else dst
        self.realtime_src_var.set(f"日文: {src_display}")
        self.realtime_dst_var.set(f"中文: {dst_display}")

    def run_translate(self, inp, out, api_key, provider, api_url, model, extract_glossary, enable_glossary):
        try:
            self._set_status("初始化翻译器...")
            self.translator = JaZhTranslator(
                api_key=api_key,
                provider=provider,
                api_url=api_url,
                model=model,
                extract_glossary=extract_glossary,
                enable_glossary=enable_glossary,
                cancel_event=self.cancel_event,
                preset=self.preset_var.get(),
            )

            self._set_status("读取 EPUB 中...")
            book = load_book(inp)

            toc_titles = extract_toc_titles(book)
            logger.info(f"发现 {len(toc_titles)} 个目录标题")

            docs = []
            all_texts = []
            text_tag_map = []

            for item, soup, tags in iter_text_nodes(book):
                if self.cancel_event.is_set():
                    raise RuntimeError("翻译已取消")

                doc_idx = len(docs)
                docs.append((item, soup, tags))
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
            for title in toc_titles:
                all_texts.append(title)
            toc_indices_end = len(all_texts)

            total_chars = sum(len(t) for t in all_texts) or 1
            total_texts = len(all_texts)
            logger.info(f"共 {len(docs)} 个文档，{total_texts} 个文本块，{total_chars} 字符")

            def on_progress(completed, total):
                progress = completed * 100 / total if total > 0 else 0
                self._set_progress(progress)
                self._set_status(self._build_stats_text(completed, total, total_chars))
                self._run_on_ui_thread(self._update_stat_cards, completed, total, total_chars)

            def on_item(src, dst):
                self._run_on_ui_thread(self._update_realtime, src, dst)

            self._set_status(f"开始翻译... 文本块:{total_texts} | 字符:{total_chars}")

            results = self.translator.translate_batch(
                all_texts,
                progress_callback=on_progress,
                item_callback=on_item,
            )

            if self.cancel_event.is_set() or not self.running:
                self._set_status("已取消")
                self._set_progress(0)
                self._reset_buttons_async()
                self._show_info("取消", "翻译已取消")
                return

            for record in text_tag_map:
                mode, doc_idx, tag = record[0], record[1], record[2]

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
                logger.info(f"应用 {len(toc_translations)} 个目录标题翻译")
                apply_toc_translations(book, toc_translations)

            self._set_status("写入 EPUB 中...")
            chinese_mode = self.direction_var.get() == "zh"
            save_book(out, book, chinese_mode=chinese_mode)

            self.translator.flush_cache()

            self.completed = True
            self._set_progress(100)
            self._run_on_ui_thread(self._update_stat_cards, total_texts, total_texts, total_chars)
            final_stats = self._build_stats_text(total_texts, total_texts, total_chars)
            self._set_status(f"{final_stats} | 输出: {out}")
            self._reset_buttons_async()

            logger.info(f"翻译完成: {out}")
            self._show_info("完成", f"翻译完成\n输出文件: {out}")

        except Exception as e:
            logger.error(f"翻译失败: {e}\n{traceback.format_exc()}")
            self._set_status(f"失败: {str(e)}")
            self._set_progress(0)
            self._reset_buttons_async()
            self._show_error("错误", f"翻译失败:\n{e}")

    def _reset_buttons(self):
        self.running = False
        self.cancel_btn.config(state="disabled")
        self.start_btn.config(state="normal")


if __name__ == "__main__":
    setup_logging()
    # 预释放提示词模板到用户目录（打包 exe 首次运行时需要）
    from translator import get_dict_dir
    get_dict_dir()
    app = App()
    app.mainloop()
