import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import traceback

from epub_io import load_book, iter_text_nodes, save_book, extract_toc_titles, apply_toc_translations, set_reading_direction
from translator import JaZhTranslator, get_data_dir

# 配置日志
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

        # 状态控制
        self.running = False
        self.completed = False  # 翻译是否已完成
        self.translator = None

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value="output_zh.epub")
        self.api_key_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="准备就绪")
        self.progress_var = tk.DoubleVar(value=0)
        self.direction_var = tk.StringVar(value="zh")  # zh=中文习惯, ja=保持原版

        self._build_ui()

        # 程序退出时保存缓存
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # ---- 输入 EPUB ----
        tk.Label(self, text="输入 EPUB:").grid(row=0, column=0, sticky="w", **pad)
        self.input_entry = tk.Entry(self, textvariable=self.input_var)
        self.input_entry.grid(row=0, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择...", command=self.pick_input, width=8).grid(row=0, column=2, **pad)

        # ---- 输出 EPUB ----
        tk.Label(self, text="输出 EPUB:").grid(row=1, column=0, sticky="w", **pad)
        self.output_entry = tk.Entry(self, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", **pad)
        tk.Button(self, text="选择...", command=self.pick_output, width=8).grid(row=1, column=2, **pad)

        # ---- API Key ----
        tk.Label(self, text="API Key:").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self, textvariable=self.api_key_var, show="*").grid(row=2, column=1, sticky="ew", **pad)

        # ---- 翻页方向 ----
        tk.Label(self, text="翻页方向:").grid(row=3, column=0, sticky="w", **pad)
        dir_frame = tk.Frame(self)
        dir_frame.grid(row=3, column=1, sticky="w", **pad)
        tk.Radiobutton(dir_frame, text="中文习惯（从左到右）", variable=self.direction_var, value="zh").pack(side="left")
        tk.Radiobutton(dir_frame, text="保持原版（从右到左）", variable=self.direction_var, value="ja").pack(side="left", padx=(20, 0))

        # ---- 进度条 ----
        self.bar = ttk.Progressbar(self, maximum=100, variable=self.progress_var)
        self.bar.grid(row=4, column=1, sticky="ew", **pad)

        # ---- 状态标签 ----
        tk.Label(self, textvariable=self.status_var, fg="#333", anchor="w").grid(
            row=5, column=1, sticky="ew", **pad
        )

        # ---- 按钮区域 ----
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=6, column=1, sticky="w", **pad)

        self.start_btn = tk.Button(btn_frame, text="开始翻译", command=self.start, width=12)
        self.start_btn.pack(side="left", padx=(0, 10))

        self.cancel_btn = tk.Button(btn_frame, text="取消", command=self.cancel, state="disabled", width=8)
        self.cancel_btn.pack(side="left")

        # ---- 缓存目录信息 ----
        data_dir = get_data_dir()
        tk.Label(self, text=f"缓存: {data_dir}", fg="#999", font=("Arial", 8), anchor="w").grid(
            row=7, column=1, sticky="ew", padx=10, pady=(0, 6)
        )

        # 列权重：让输入框随窗口伸缩
        self.columnconfigure(1, weight=1)

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

        # 禁用开始按钮，启用取消按钮
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.running = True
        self.completed = False

        thread = threading.Thread(target=self.run_translate, args=(inp, out, api_key), daemon=True)
        thread.start()
        logger.info(f"开始翻译: {inp} -> {out}")

    def cancel(self):
        """取消翻译"""
        self.running = False
        self.status_var.set("正在取消...")
        logger.info("用户请求取消翻译")

    def _on_close(self):
        """程序关闭时处理"""
        if self.running:
            if messagebox.askyesno("确认", "翻译正在进行中，确定要退出吗？"):
                self.running = False
                if self.translator:
                    self.translator.flush_cache()
            else:
                return
        elif self.completed:
            if not messagebox.askyesno("确认", "翻译已完成，是否退出？"):
                return

        # 保存缓存
        if self.translator:
            try:
                self.translator.flush_cache()
            except Exception as e:
                logger.error(f"保存缓存失败: {e}")

        self.destroy()

    def run_translate(self, inp, out, api_key):
        """执行翻译流程"""
        try:
            self.status_var.set("初始化翻译器...")
            self.translator = JaZhTranslator(api_key=api_key)

            self.status_var.set("读取 EPUB 中...")
            book = load_book(inp)

            # 提取目录标题
            toc_titles = extract_toc_titles(book)
            logger.info(f"发现 {len(toc_titles)} 个目录标题")

            # 收集所有文档项和文本
            docs = []
            all_texts = []
            text_tag_map = []  # (doc_idx, tag) 映射

            for item, soup, tags in iter_text_nodes(book):
                doc_idx = len(docs)
                docs.append((item, soup, tags))
                for tag in tags:
                    # 使用 get_text() 获取完整文本（包括嵌套标签如 ruby）
                    text = tag.get_text(strip=True)
                    # 移除图片占位符 ￼ (U+FFFC) 后检查是否还有有效文本
                    text_clean = text.replace('\ufffc', '').strip()
                    if text_clean:
                        all_texts.append(text)
                        text_tag_map.append((doc_idx, tag))

            # 添加目录标题到翻译列表
            toc_indices_start = len(all_texts)
            for title in toc_titles:
                all_texts.append(title)
            toc_indices_end = len(all_texts)

            total_chars = sum(len(t) for t in all_texts) or 1
            total_texts = len(all_texts)

            logger.info(f"共 {len(docs)} 个文档，{total_texts} 个文本块，{total_chars} 字符")

            # 进度回调
            def on_progress(completed, total):
                progress = completed * 100 / total if total > 0 else 0
                self.progress_var.set(progress)
                self.status_var.set(f"翻译中... {completed}/{total} ({progress:.1f}%)")

            self.status_var.set(f"开始翻译... 共 {total_texts} 个文本块")

            # 批量并发翻译
            results = self.translator.translate_batch(
                all_texts,
                progress_callback=on_progress,
                batch_size=4
            )

            # 检查是否取消
            if not self.running:
                self.status_var.set("已取消")
                self.progress_var.set(0)
                self._reset_buttons()
                messagebox.showinfo("取消", "翻译已取消")
                return

            # 应用翻译结果到正文内容
            for (doc_idx, tag), original in zip(text_tag_map, all_texts[:toc_indices_start]):
                if original in results:
                    translated = results[original]
                    # 查找标签内是否有 <a> 超链接标签
                    anchor = tag.find('a')
                    if anchor:
                        # 保留 <a> 结构，清空后设置翻译文本
                        anchor.clear()
                        anchor.string = translated
                    else:
                        # 没有超链接，整体替换
                        tag.clear()
                        tag.string = translated

            # 更新文档内容
            for item, soup, tags in docs:
                item.set_content(str(soup).encode("utf-8"))

            # 应用翻译结果到目录标题
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

            # 设置翻页方向
            chinese_mode = self.direction_var.get() == "zh"
            set_reading_direction(out, chinese_mode)

            # 强制保存缓存
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

            error_detail = str(e)
            if hasattr(e, '__cause__'):
                error_detail += f"\n原因: {e.__cause__}"

            messagebox.showerror("错误", f"翻译失败:\n{error_detail}")

    def _reset_buttons(self):
        """重置按钮状态"""
        self.running = False
        self.start_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")


if __name__ == "__main__":
    app = App()
    app.mainloop()