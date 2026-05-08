import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback

from bs4 import BeautifulSoup, NavigableString

from epub_io import (
    apply_toc_translations,
    extract_toc_titles,
    iter_text_nodes,
    load_book,
    save_book,
    set_reading_direction,
)
from translator import JaZhTranslator, get_data_dir

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("EPUB 日译中 (DeepSeek)")
        self.geometry("700x310")
        self.minsize(500, 200)
        self.default_dir = os.getcwd()

        self.running = False
        self.completed = False
        self.translator = None
        self.cancel_event = threading.Event()

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output_zh.epub")
        self.api_key_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="准备就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.direction_var = tk.StringVar(value="zh")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        tk.Label(self, text="输入 EPUB:").grid(row=0, column=0, sticky="w", **pad)
        self.input_entry = tk.Entry(self, textvariable=self.input_var)
        self.input_entry.grid(row=0, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择...", command=self.pick_input, width=8).grid(row=0, column=2, **pad)

        tk.Label(self, text="输出 EPUB:").grid(row=1, column=0, sticky="w", **pad)
        self.output_entry = tk.Entry(self, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择...", command=self.pick_output, width=8).grid(row=1, column=2, **pad)

        tk.Label(self, text="API Key:").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.api_key_var, show="*").grid(row=2, column=1, sticky="ew", **pad)

        tk.Label(self, text="翻页方向:").grid(row=3, column=0, sticky="w", **pad)
        dir_frame = tk.Frame(self)
        dir_frame.grid(row=3, column=1, sticky="w", **pad)
        tk.Radiobutton(dir_frame, text="中文习惯（从左到右）", variable=self.direction_var, value="zh").pack(side="left")
        tk.Radiobutton(dir_frame, text="保持原版（从右到左）", variable=self.direction_var, value="ja").pack(side="left", padx=(20, 0))

        self.bar = ttk.Progressbar(self, maximum=100, variable=self.progress_var)
        self.bar.grid(row=4, column=1, sticky="ew", **pad)

        tk.Label(self, textvariable=self.status_var, fg="#333", anchor="w").grid(
            row=5, column=1, sticky="ew", **pad
        )

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=6, column=1, sticky="w", **pad)

        self.start_btn = tk.Button(btn_frame, text="开始翻译", command=self.start, width=12)
        self.start_btn.pack(side="left", padx=(0, 10))

        self.cancel_btn = tk.Button(btn_frame, text="取消", command=self.cancel, state="disabled", width=8)
        self.cancel_btn.pack(side="left")

        data_dir = get_data_dir()
        tk.Label(self, text=f"缓存: {data_dir}", fg="#999", font=("Arial", 8), anchor="w").grid(
            row=7, column=1, sticky="ew", padx=10, pady=(0, 6)
        )

        self.columnconfigure(1, weight=1)

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

    def start(self):
        inp = self.input_var.get().strip()
        out = self.output_var.get().strip()
        api_key = self.api_key_var.get().strip()

        if not inp or not os.path.exists(inp):
            messagebox.showerror("错误", "请选择有效的输入 EPUB")
            return
        if not out:
            messagebox.showerror("错误", "请填写输出文件名")
            return
        if not api_key:
            messagebox.showerror("错误", "请填写 DeepSeek API Key")
            return

        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.running = True
        self.completed = False
        self.cancel_event.clear()

        thread = threading.Thread(target=self.run_translate, args=(inp, out, api_key), daemon=True)
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

    def run_translate(self, inp, out, api_key):
        try:
            self.status_var.set("初始化翻译器...")
            self.translator = JaZhTranslator(api_key=api_key, cancel_event=self.cancel_event)

            self.status_var.set("读取 EPUB 中...")
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
                self.progress_var.set(progress)
                self.status_var.set(f"翻译中... {completed}/{total} ({progress:.1f}%)")

            self.status_var.set(f"开始翻译... 共 {total_texts} 个文本块")

            results = self.translator.translate_batch(
                all_texts,
                progress_callback=on_progress,
                batch_size=4,
            )

            if self.cancel_event.is_set() or not self.running:
                self.status_var.set("已取消")
                self.progress_var.set(0)
                self._reset_buttons()
                messagebox.showinfo("取消", "翻译已取消")
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

            self.status_var.set("写入 EPUB 中...")
            save_book(out, book)

            chinese_mode = self.direction_var.get() == "zh"
            set_reading_direction(out, chinese_mode)

            self.translator.flush_cache()

            self.completed = True
            self.progress_var.set(100)
            self.status_var.set(f"完成: {out}")
            self._reset_buttons()

            logger.info(f"翻译完成: {out}")
            messagebox.showinfo("完成", f"翻译完成\n输出文件: {out}")

        except Exception as e:
            logger.error(f"翻译失败: {e}\n{traceback.format_exc()}")
            self.status_var.set(f"失败: {str(e)}")
            self.progress_var.set(0)
            self._reset_buttons()

            messagebox.showerror("错误", f"翻译失败:\n{e}")

    def _reset_buttons(self):
        self.running = False
        self.cancel_btn.config(state="disabled")
        self.start_btn.config(state="normal")


if __name__ == "__main__":
    app = App()
    app.mainloop()
