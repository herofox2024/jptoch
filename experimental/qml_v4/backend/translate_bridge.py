# -*- coding: utf-8 -*-
"""
翻译桥接器：包装 JaZhTranslator，通过 QThread worker 运行翻译，信号通知 QML。
"""

import os
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread

from bs4 import NavigableString

import requests
from translator import JaZhTranslator, get_data_dir
from epub_io import load_book, save_book, iter_text_nodes, extract_toc_titles, apply_toc_translations
from text_utils import is_translatable

CANCELLED_RESULT = "__CANCELLED__"
def _sanitize_filename(name):
    invalid = '<>:"/\\\\|?*'
    cleaned = ''.join('_' if c in invalid or ord(c) < 32 else c for c in name)
    cleaned = ' '.join(cleaned.split()).strip(' ._')
    if cleaned.lower().endswith('.epub'):
        cleaned = cleaned[:-5].strip(' ._')
    cleaned = cleaned[:120].strip(' ._')
    if not cleaned:
        return ''
    reserved = {'CON','PRN','AUX','NUL','CONIN$','CONOUT$'}
    reserved |= {f'COM{i}' for i in range(1,10)} | {f'LPT{i}' for i in range(1,10)}
    if cleaned.split('.', 1)[0].upper() in reserved:
        cleaned = cleaned + '_'
    return cleaned

def _unique_epub_path(path):
    from pathlib import Path
    import time
    p = Path(path)
    if not p.exists():
        return p
    for index in range(2, 1000):
        candidate = p.with_name(f'{p.stem}_{index}{p.suffix}')
        if not candidate.exists():
            return candidate
    return p.with_name(f'{p.stem}_{int(time.time())}{p.suffix}')



class _TranslateWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    progressChanged = Signal(int, int, int)
    itemTranslated = Signal(str, str)
    proofreadDetail = Signal(str, str, str)
    statusChanged = Signal(str)
    statUpdate = Signal(int, int, int, int, int, float, int, int, int, int)
    errorDetail = Signal(str)

    def __init__(self, config: dict, cancel_event: threading.Event):
        super().__init__()
        self._config = config
        self._cancel_event = cancel_event
        self._translator = None
        self._bridge = None

    def run(self):
        cfg = self._config
        start_ts = time.time()
        try:
            translator = JaZhTranslator(
                api_key=cfg["api_key"],
                provider=cfg["provider"],
                api_url=cfg["api_url"],
                model=cfg["model"],
                max_workers=cfg["max_workers"],
                batch_size=cfg["batch_size"],
                max_batch_length=cfg["max_batch_length"],
                max_text_size_for_batch=cfg["max_text_size_for_batch"],
                api_timeout=cfg["api_timeout"],
                cancel_event=self._cancel_event,
                extract_glossary=cfg["extract_glossary"],
                enable_glossary=cfg["enable_glossary"],
                enable_thinking=cfg["enable_thinking"],
                enable_proofread=cfg["enable_proofread"],
            )
            self._translator = translator
            if self._bridge:
                self._bridge._active_translator = translator

            book = load_book(cfg["inp"])
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
                            if is_translatable(raw):
                                all_texts.append(raw)
                                node_records.append((node, raw))
                        if node_records:
                            text_tag_map.append(("multi_anchor", doc_idx, tag, node_records))
                        continue
                    text = tag.get_text(" ", strip=True)
                    if is_translatable(text):
                        all_texts.append(text)
                        mode = "single_anchor" if len(anchors) == 1 else "plain"
                        text_tag_map.append((mode, doc_idx, tag, text))

            toc_indices_start = len(all_texts)
            all_texts.extend(toc_titles)
            toc_indices_end = len(all_texts)

            total_chars = sum(len(t) for t in all_texts) or 1
            total_texts = len(all_texts)
            self.statusChanged.emit(f"开始翻译 文本块:{total_texts} 字符:{total_chars}")

            def _emit_stat(completed, total):
                stats = translator.get_stats() if translator else {}
                elapsed = max(0.0, time.time() - start_ts)
                api_total = int(stats.get("api_requests_total", 0))
                batch_total = int(stats.get("batch_total", 0))
                batch_ok = int(stats.get("batch_json_success", 0)) + int(stats.get("batch_delimiter_success", 0))
                fail_count = int(stats.get("api_requests_failed", 0))
                terms = int(stats.get("glossary_new_terms_added", 0))
                success_rate = (batch_ok * 100.0 / batch_total) if batch_total else 100.0
                speed = int(completed / elapsed) if elapsed > 0 else 0
                translated_chars = int((completed / total) * total_chars) if total > 0 else 0
                char_speed = int(translated_chars / elapsed) if elapsed > 0 else 0
                token_total = int(stats.get("tokens_total", 0))
                self.statUpdate.emit(completed, total, terms, api_total, fail_count, success_rate, speed, char_speed, translated_chars, token_total)

            def on_progress(completed, total):
                self.progressChanged.emit(completed, total, total_chars)
                _emit_stat(completed, total)

            def on_item(src, dst):
                self.itemTranslated.emit(src, dst)

            def on_proofread_detail(detail):
                self.proofreadDetail.emit(
                    str(detail.get("original", "")),
                    str(detail.get("draft", detail.get("before", ""))),
                    str(detail.get("revised", detail.get("after", ""))),
                )

            results = translator.translate_batch(
                all_texts,
                progress_callback=on_progress,
                item_callback=on_item,
                proofread_callback=on_proofread_detail,
            )

            if self._cancel_event.is_set():
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

            save_book(cfg["out"], book, chinese_mode=(cfg["direction"] == "zh"))
            final_out = cfg["out"]

            # Smart output filename: translate the EPUB filename
            try:
                source_path = __import__("pathlib", fromlist=["Path"]).Path(cfg["out"])
                source_base = __import__("pathlib", fromlist=["Path"]).Path(cfg["inp"]).stem
                import os as _os
                candidates = []
                if source_base in results and results[source_base]:
                    candidates.append(str(results[source_base]))
                if is_translatable(source_base):
                    try:
                        name_results = translator.translate_batch([source_base])
                        t_name = name_results.get(source_base)
                        if t_name:
                            candidates.append(str(t_name))
                    except Exception:
                        pass
                for title in toc_titles:
                    tt = results.get(title)
                    if tt:
                        candidates.append(str(tt))
                        break
                for candidate in candidates:
                    safe = _sanitize_filename(candidate)
                    if not safe:
                        continue
                    target = source_path.with_name(safe + ".epub")
                    if _os.path.normcase(_os.path.abspath(str(target))) == _os.path.normcase(_os.path.abspath(str(source_path))):
                        final_out = str(source_path)
                        break
                    candidate_path = str(_unique_epub_path(target))
                    __import__("pathlib", fromlist=["Path"]).Path(cfg["out"]).rename(candidate_path)
                    final_out = candidate_path
                    break
            except Exception:
                pass

            translator.flush_cache()
            self.finished.emit(final_out)

        except Exception as e:
            if self._cancel_event.is_set():
                self.finished.emit(CANCELLED_RESULT)
                return
            self.errorDetail.emit(traceback.format_exc())
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


class _EstimateWorker(QObject):
    finished = Signal(str, int)
    failed = Signal(str, str)

    def __init__(self, path: str):
        super().__init__()
        self._path = path

    def run(self):
        try:
            book = load_book(self._path)
            all_texts = []
            for _, _, tags in iter_text_nodes(book):
                for tag in tags:
                    text = tag.get_text(" ", strip=True)
                    if text:
                        all_texts.append(text)
            all_texts.extend(extract_toc_titles(book))
            total = sum(len(t) for t in all_texts)
            self.finished.emit(self._path, total)
        except Exception as e:
            self.failed.emit(self._path, str(e))


class _TestWorker(QObject):
    result = Signal(str)

    def __init__(self, api_key, api_url, model, timeout):
        super().__init__()
        self._api_key = api_key
        self._api_url = api_url
        self._model = model
        self._timeout = timeout

    def run(self):
        try:
            headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self._model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 10,
                "temperature": 0.1,
            }
            resp = requests.post(self._api_url, headers=headers, json=payload, timeout=int(self._timeout) if self._timeout else 15)
            if resp.status_code == 200:
                self.result.emit(f"连接成功 ({resp.status_code}) — 模型: {self._model}")
            else:
                body = resp.text[:200]
                self.result.emit(f"失败: HTTP {resp.status_code} — {body}")
        except requests.exceptions.Timeout:
            self.result.emit(f"失败: 连接超时 ({self._timeout}秒)")
        except Exception as e:
            self.result.emit(f"失败: {e}")


class TranslateBridge(QObject):

    progressChanged = Signal(int, int, int)
    itemTranslated = Signal(str, str)
    proofreadDetail = Signal(str, str, str)
    statusChanged = Signal(str)
    statUpdate = Signal(int, int, int, int, int, float, int, int, int, int)
    finished = Signal(str)
    failed = Signal(str)
    errorDetail = Signal(str)
    connectionResult = Signal(str)
    estimateFinished = Signal(str, int)
    estimateFailed = Signal(str, str)

    _progressValueChanged = Signal()
    _busyChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress_value = 0.0
        self._busy = False
        self._cancel_event = threading.Event()
        self._translator = None
        self._bridge = None
        self._is_paused = False
        self._last_cfg = None
        # Hold references to prevent GC of workers during async operations
        self._pending_workers = []
        self._active_translator = None

    def _track_worker_thread(self, worker, thread):
        """Prevent GC by holding a reference until thread finishes."""
        pair = (worker, thread)
        self._pending_workers.append(pair)
        def _cleanup():
            if pair in self._pending_workers:
                self._pending_workers.remove(pair)
            worker.deleteLater()
            thread.deleteLater()
        thread.finished.connect(_cleanup)
        return pair

    @Property(float, notify=_progressValueChanged)
    def progressValue(self) -> float:
        return self._progress_value

    @progressValue.setter
    def progressValue(self, val: float):
        if abs(val - self._progress_value) > 0.001:
            self._progress_value = val
            self._progressValueChanged.emit()

    @Property(bool, notify=_busyChanged)
    def busy(self) -> bool:
        return self._busy

    @busy.setter
    def busy(self, val: bool):
        if val != self._busy:
            self._busy = val
            self._busyChanged.emit()

    def _make_config(self, cfg):
        return {
            "inp": cfg.inp, "out": cfg.out, "api_key": cfg.apiKey,
            "provider": cfg.provider, "api_url": cfg.apiUrl, "model": cfg.model,
            "extract_glossary": cfg.extractGlossary, "enable_glossary": cfg.enableGlossary,
            "max_workers": cfg.maxWorkers, "batch_size": cfg.batchSize,
            "max_batch_length": cfg.maxBatchLength, "max_text_size_for_batch": cfg.maxTextSizeForBatch,
            "api_timeout": cfg.apiTimeout, "direction": cfg.direction,
            "enable_thinking": cfg.enableThinking, "enable_proofread": cfg.enableProofread,
        }

    @Slot("QVariant")
    def startTranslation(self, cfg):
        config = self._make_config(cfg)
        if not config["inp"] or not os.path.exists(config["inp"]):
            self.failed.emit("请选择有效的输入 EPUB"); return
        if not config["out"]:
            self.failed.emit("请填写输出文件路径"); return
        if config["provider"] in {"deepseek", "doubao", "gemini", "glm", "custom"} and not config["api_key"]:
            self.failed.emit("该提供方需要 API Key"); return
        if not config["api_url"] or not config["model"]:
            self.failed.emit("请填写 Base URL 和模型"); return

        self._last_cfg = config
        self._cancel_event.clear()
        self._is_paused = False
        self.busy = True
        self.progressValue = 0.0

        worker = _TranslateWorker(config, self._cancel_event)
        worker._bridge = self
        thread = QThread(self)
        self._track_worker_thread(worker, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progressChanged.connect(self._on_progress)
        worker.itemTranslated.connect(self.itemTranslated)
        worker.proofreadDetail.connect(self.proofreadDetail)
        worker.statusChanged.connect(self.statusChanged)
        worker.statUpdate.connect(self.statUpdate)
        worker.errorDetail.connect(self.errorDetail)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self.failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_progress(self, completed, total, total_chars):
        self.progressChanged.emit(completed, total, total_chars)
        self.progressValue = float(completed) / float(total) if total > 0 else 0.0

    def _on_finished(self, out_path):
        self._active_translator = None
        self.busy = False
        if out_path == CANCELLED_RESULT:
            self.finished.emit(CANCELLED_RESULT)
        else:
            self.progressValue = 1.0
            self.finished.emit(out_path)

    @Slot()
    def cancelTranslation(self):
        self._cancel_event.set()
        self.statusChanged.emit("正在取消...")

    @Slot()
    def pauseTranslation(self):
        self._is_paused = True
        self._cancel_event.set()
        self.statusChanged.emit("暂停中 — 等待当前请求完成...")

    @Slot("QVariant")
    def resumeTranslation(self, cfg):
        if not self._is_paused:
            self.failed.emit("当前没有可恢复的暂停任务"); return
        self._cancel_event.clear()
        self._is_paused = False
        self.startTranslation(cfg)

    # --- API test ---
    @Slot(str, str, str, int)
    def testConnection(self, api_key, api_url, model, timeout):
        worker = _TestWorker(api_key, api_url, model, timeout)
        thread = QThread(self)
        self._track_worker_thread(worker, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self.connectionResult)
        worker.result.connect(thread.quit)
        thread.start()

    # --- Estimate chars ---
    @Slot(str)
    def startEstimateChars(self, inp_path):
        if not inp_path or not os.path.exists(inp_path):
            self.estimateFinished.emit(inp_path, -1); return
        worker = _EstimateWorker(inp_path)
        thread = QThread(self)
        self._track_worker_thread(worker, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.estimateFinished)
        worker.failed.connect(self.estimateFailed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()


    @Slot(str, result=bool)
    def exportDiagnostic(self, output_path):
        """Export diagnostic bundle as ZIP: config + logs + glossary."""
        import zipfile
        import os as _os
        from pathlib import Path as _Path
        try:
            data_dir = get_data_dir()
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # Config
                config_path = data_dir / "config.json"
                if config_path.exists():
                    zf.write(str(config_path), "config.json")
                # Glossary
                glossary_path = data_dir / "glossary.json"
                if glossary_path.exists():
                    zf.write(str(glossary_path), "glossary.json")
                # Logs
                log_dir = data_dir / "logs"
                if log_dir.exists():
                    for log_file in sorted(log_dir.iterdir()):
                        if log_file.is_file():
                            zf.write(str(log_file), f"logs/{log_file.name}")
            return True
        except Exception as e:
            self.errorDetail.emit(f"Diagnostic export failed: {e}")
            return False

    @Slot()
    def playCompletionVoice(self):
        """Play Windows TTS notification on completion."""
        import subprocess as _sp
        try:
            cmd = 'Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = 0; $s.Speak("翻译完成")'
            _sp.Popen(["powershell", "-NoProfile", "-Command", cmd],
                      creationflags=0x08000000 if hasattr(_sp, "CREATE_NO_WINDOW") else 0,
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
        except Exception:
            pass


    @Slot(result=str)
    def dataDir(self) -> str:
        return str(get_data_dir())
