import logging
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback
import json
import shutil

from bs4 import NavigableString

from epub_io import (
    apply_toc_translations,
    extract_toc_titles,
    iter_text_nodes,
    load_book,
    save_book,
    set_reading_direction,
)
from translator import JaZhTranslator, get_data_dir, PERFORMANCE_PRESETS

logger = logging.getLogger(__name__)


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EPUB 日译中 (DeepSeek)")
        self.geometry("920x500")
        self.minsize(760, 460)
        self.default_dir = os.getcwd()

        self._running_event = threading.Event()  # 线程安全的运行状态标志
        self.completed = False
        self.translator = None
        self.cancel_event = threading.Event()
        self.translation_start_time = 0.0

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output_zh.epub")
        self.api_key_var = tk.StringVar(value="")
        self.provider_var = tk.StringVar(value="deepseek")
        self.api_url_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="准备就绪")
        self.estimate_var = tk.StringVar(value="预估字符: -")
        self.progress_var = tk.DoubleVar(value=0)
        self.direction_var = tk.StringVar(value="zh")
        self.extract_glossary_var = tk.BooleanVar(value=False)
        self.enable_glossary_var = tk.BooleanVar(value=False)
        self.preset_var = tk.StringVar(value="default")  # 性能预设：default/balanced/extreme
        self._estimate_after_id = None
        self._estimate_seq = 0

        self.input_var.trace_add("write", self._on_input_var_change)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    @property
    def running(self) -> bool:
        """线程安全地获取运行状态。"""
        return self._running_event.is_set()

    @running.setter
    def running(self, value: bool):
        """线程安全地设置运行状态。"""
        if value:
            self._running_event.set()
        else:
            self._running_event.clear()

    def _run_on_ui_thread(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def _set_status(self, text: str):
        self._run_on_ui_thread(self.status_var.set, text)

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
        # 根据完成状态显示不同文案
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

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        tk.Label(self, text="输入 EPUB:").grid(row=0, column=0, sticky="w", **pad)
        self.input_entry = tk.Entry(self, textvariable=self.input_var)
        self.input_entry.grid(row=0, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择...", command=self.pick_input, width=8).grid(row=0, column=2, **pad)
        tk.Label(self, textvariable=self.estimate_var, fg="#666", anchor="w").grid(
            row=0, column=3, sticky="w", **pad
        )

        tk.Label(self, text="输出 EPUB:").grid(row=1, column=0, sticky="w", **pad)
        self.output_entry = tk.Entry(self, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择...", command=self.pick_output, width=8).grid(row=1, column=2, **pad)

        tk.Label(self, text="API Key:").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.api_key_var, show="*").grid(row=2, column=1, sticky="ew", **pad)

        tk.Label(self, text="服务提供方:").grid(row=3, column=0, sticky="w", **pad)
        provider_frame = tk.Frame(self)
        provider_frame.grid(row=3, column=1, sticky="w", **pad)
        tk.Radiobutton(provider_frame, text="DeepSeek", variable=self.provider_var, value="deepseek", command=self._on_provider_change).pack(side="left")
        tk.Radiobutton(provider_frame, text="Sakura", variable=self.provider_var, value="sakura", command=self._on_provider_change).pack(side="left", padx=(20, 0))
        tk.Radiobutton(provider_frame, text="Gemini", variable=self.provider_var, value="gemini", command=self._on_provider_change).pack(side="left", padx=(20, 0))
        tk.Radiobutton(provider_frame, text="自定义", variable=self.provider_var, value="custom", command=self._on_provider_change).pack(side="left", padx=(20, 0))

        tk.Label(self, text="Base URL:").grid(row=4, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.api_url_var).grid(row=4, column=1, sticky="ew", **pad)

        tk.Label(self, text="模型名:").grid(row=5, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.model_var).grid(row=5, column=1, sticky="ew", **pad)

        tk.Label(self, text="翻页方向:").grid(row=6, column=0, sticky="w", **pad)
        dir_frame = tk.Frame(self)
        dir_frame.grid(row=6, column=1, sticky="w", **pad)
        tk.Radiobutton(dir_frame, text="中文习惯（从左到右）", variable=self.direction_var, value="zh").pack(side="left")
        tk.Radiobutton(dir_frame, text="保持原版（从右到左）", variable=self.direction_var, value="ja").pack(side="left", padx=(20, 0))

        # 性能预设选择
        tk.Label(self, text="性能预设:").grid(row=7, column=0, sticky="w", **pad)
        preset_frame = tk.Frame(self)
        preset_frame.grid(row=7, column=1, sticky="w", **pad)
        self.preset_combo = ttk.Combobox(
            preset_frame,
            textvariable=self.preset_var,
            values=["default", "balanced", "extreme"],
            state="readonly",
            width=12,
        )
        self.preset_combo.pack(side="left")
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)

        self.preset_desc_label = tk.Label(
            preset_frame,
            text=PERFORMANCE_PRESETS["default"]["description"],
            fg="#666",
            anchor="w",
        )
        self.preset_desc_label.pack(side="left", padx=(10, 0))

        self.bar = ttk.Progressbar(self, maximum=100, variable=self.progress_var)
        self.bar.grid(row=8, column=1, sticky="ew", **pad)

        tk.Label(self, textvariable=self.status_var, fg="#333", anchor="w", justify="left", wraplength=700).grid(
            row=9, column=1, sticky="ew", **pad
        )

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=10, column=1, sticky="w", **pad)

        self.start_btn = tk.Button(btn_frame, text="开始翻译", command=self.start, width=12)
        self.start_btn.pack(side="left", padx=(0, 10))

        self.cancel_btn = tk.Button(btn_frame, text="取消", command=self.cancel, state="disabled", width=8)
        self.cancel_btn.pack(side="left")

        self.import_glossary_btn = tk.Button(
            btn_frame,
            text="导入术语表JSON",
            command=self.import_glossary_json,
            width=14,
        )
        self.import_glossary_btn.pack(side="left", padx=(10, 0))

        self.extract_glossary_cb = tk.Checkbutton(
            btn_frame,
            text="自动提取术语（实验）",
            variable=self.extract_glossary_var,
            onvalue=True,
            offvalue=False,
        )
        self.extract_glossary_cb.pack(side="left", padx=(10, 0))

        self.enable_glossary_cb = tk.Checkbutton(
            btn_frame,
            text="启用术语表",
            variable=self.enable_glossary_var,
            onvalue=True,
            offvalue=False,
        )
        self.enable_glossary_cb.pack(side="left", padx=(10, 0))

        self.glossary_notice_label = tk.Label(
            self,
            text="提示：开启术语表后默认读取 C:\\Users\\HUAWEI\\.epub_translator\\glossary.json，token 消耗会翻倍，请谨慎使用。",
            fg="#b45309",
            anchor="w",
            justify="left",
            wraplength=760,
        )
        self.glossary_notice_label.grid(row=11, column=1, columnspan=3, sticky="ew", padx=10, pady=(0, 2))

        data_dir = get_data_dir()
        tk.Label(self, text=f"缓存: {data_dir}", fg="#999", font=("Arial", 8), anchor="w").grid(
            row=12, column=1, columnspan=3, sticky="ew", padx=10, pady=(0, 6)
        )

        self.columnconfigure(1, weight=1)
        self._on_provider_change()

    def _on_provider_change(self):
        provider = self.provider_var.get().strip().lower()
        if provider == "sakura":
            self.api_url_var.set("http://127.0.0.1:8080/v1/chat/completions")
            self.model_var.set("sakura-v1.0")
        elif provider == "gemini":
            self.api_url_var.set("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
            self.model_var.set("gemini-2.5-pro")
        elif provider == "custom":
            self.api_url_var.set("")
            self.model_var.set("")
        else:
            self.api_url_var.set("https://api.deepseek.com/chat/completions")
            self.model_var.set("deepseek-chat")

    def _on_preset_change(self, event=None):
        """处理性能预设变化，选择极端模式时弹出警告。"""
        preset = self.preset_var.get()
        preset_config = PERFORMANCE_PRESETS.get(preset, PERFORMANCE_PRESETS["default"])
        self.preset_desc_label.config(text=preset_config["description"])

        # 极端模式警告
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
            self.api_url_var.set("https://api.deepseek.com/chat/completions")
            self.model_var.set("deepseek-chat")

    @staticmethod
    def _extract_text(tag) -> str:
        return tag.get_text(" ", strip=True)

    @staticmethod
    def _is_translatable(text: str) -> bool:
        text = text.replace("\ufffc", "").strip()
        if not text:
            return False
        has_japanese_kana = any("\u3040" <= c <= "\u30ff" for c in text)
        has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
        has_latin = any(("a" <= c.lower() <= "z") for c in text)
        has_digit = any(c.isdigit() for c in text)
        if has_japanese_kana:
            return True
        if has_cjk and not has_latin:
            return True
        if has_cjk and has_digit and not has_latin:
            return True
        return False

    def pick_input(self):
        path = filedialog.askopenfilename(
            title="选择输入 EPUB",
            initialdir=self.default_dir,
            filetypes=[("EPUB files", "*.epub"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)
            base = os.path.splitext(os.path.basename(path))[0]
            out_path = os.path.join(os.path.dirname(path), f"{base}_zh.epub")
            self.output_var.set(out_path)
            logger.info(f"选择输入文件: {path}")
            self._schedule_estimate(path)

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
            has_existing = glossary_path.exists()
            if glossary_path.exists():
                shutil.copy2(glossary_path, backup_path)

            JaZhTranslator._atomic_write_json(glossary_path, normalized_glossary)

            if self.translator is not None:
                self.translator.replace_glossary(normalized_glossary)

            accepted = import_stats.get("accepted", 0)
            skipped = import_stats.get("skipped", 0)
            conflicts = import_stats.get("conflicts", 0)
            logger.info(
                "Glossary imported: %s -> %s (accepted=%s skipped=%s conflicts=%s)",
                path,
                glossary_path,
                accepted,
                skipped,
                conflicts,
            )
            self.status_var.set(f"Glossary imported: 新增{accepted} 跳过{skipped} 冲突{conflicts}")
            messagebox.showinfo(
                "Done",
                (
                    "Glossary import succeeded\n"
                    f"Accepted: {accepted}\nSkipped: {skipped}\nConflicts: {conflicts}\n"
                    f"Target: {glossary_path}\n"
                    f"Backup: {backup_path if has_existing else 'N/A'}"
                ),
            )
        except Exception as e:
            logger.error(f"Glossary import failed: {e}")
            messagebox.showerror("Error", f"Glossary import failed:\n{e}")

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
        if provider in {"deepseek", "gemini", "custom"} and not api_key:
            provider_name = "DeepSeek" if provider == "deepseek" else ("Gemini" if provider == "gemini" else "自定义")
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

        thread = threading.Thread(
            target=self.run_translate,
            args=(inp, out, api_key, provider, api_url, model, extract_glossary, enable_glossary),
            daemon=True
        )
        thread.start()
        logger.info(f"开始翻译: {inp} -> {out}")

    def cancel(self):
        self.running = False
        self.cancel_event.set()
        self.status_var.set("正在取消...")
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

            self._set_status(f"开始翻译... 文本块:{total_texts} | 字符:{total_chars}")

            results = self.translator.translate_batch(
                all_texts,
                progress_callback=on_progress,
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
            save_book(out, book)

            chinese_mode = self.direction_var.get() == "zh"
            set_reading_direction(out, chinese_mode)

            self.translator.flush_cache()

            self.completed = True
            self._set_progress(100)
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
    app = App()
    app.mainloop()
