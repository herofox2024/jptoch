# -*- coding: utf-8 -*-
"""
翻译桥接器：包装 JaZhTranslator，通过 QThread worker 运行翻译，信号通知 QML。
"""

import os
import math
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread

from backend.toast_bridge import ToastBridge

CANCELLED_RESULT = "__CANCELLED__"
STOPPED_RESULT = "__STOPPED__"
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


def _format_duration(seconds):
    seconds = max(0, int(math.ceil(seconds)))
    if seconds < 60:
        return "不足 1 分钟" if seconds < 30 else f"约 {seconds} 秒"
    minutes = int(math.ceil(seconds / 60))
    if minutes < 60:
        return f"约 {minutes} 分钟"
    hours = minutes // 60
    remain_minutes = minutes % 60
    if remain_minutes:
        return f"约 {hours} 小时 {remain_minutes} 分钟"
    return f"约 {hours} 小时"


def _estimate_translation_duration(total_chars, total_texts, cfg):
    provider = str(cfg.get("provider", "") or "").lower()
    provider_profile = {
        "deepseek": {"batch_seconds": 2.0, "chars_per_second": 120.0},
        "doubao": {"batch_seconds": 2.5, "chars_per_second": 90.0},
        "glm": {"batch_seconds": 4.0, "chars_per_second": 35.0},
        "gemini": {"batch_seconds": 6.0, "chars_per_second": 30.0},
        "wenxin": {"batch_seconds": 4.0, "chars_per_second": 45.0},
        "sakura": {"batch_seconds": 1.5, "chars_per_second": 80.0},
        "custom": {"batch_seconds": 3.0, "chars_per_second": 60.0},
    }
    profile = provider_profile.get(provider, provider_profile["custom"])
    batch_size = max(1, int(cfg.get("batch_size") or 1))
    max_workers = max(1, int(cfg.get("max_workers") or 1))
    estimated_batches = max(1, math.ceil(max(1, total_texts) / batch_size))
    active_workers = min(max_workers, estimated_batches)
    effective_workers = 1.0 + max(0, active_workers - 1) * 0.65
    batch_seconds = estimated_batches * profile["batch_seconds"] / effective_workers
    char_seconds = max(1, total_chars) / max(1.0, profile["chars_per_second"] * effective_workers)
    overhead_seconds = max(10.0, total_texts * 0.02)
    return max(batch_seconds, char_seconds) + overhead_seconds



class _TranslateWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    progressChanged = Signal(int, int, int)
    itemTranslated = Signal(str, str)
    proofreadDetail = Signal(str, str, str, str, bool, bool, bool)
    proofreadStyleDetected = Signal(str, str, int, str)
    statusChanged = Signal(str)
    statUpdate = Signal(int, int, int, int, int, float, int, int, int, int)
    qualityStatUpdate = Signal(int, int, int, int, int, int)
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
            from bs4 import NavigableString
            from translator import JaZhTranslator, TranslationIncompleteError
            from epub_io import (
                load_book,
                save_book,
                iter_text_nodes,
                extract_toc_titles,
                apply_toc_translations,
                extract_visible_text,
            )
            from text_utils import is_translatable

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
                    text = extract_visible_text(tag)
                    if is_translatable(text):
                        all_texts.append(text)
                        mode = "single_anchor" if len(anchors) == 1 else "plain"
                        text_tag_map.append((mode, doc_idx, tag, text))

            toc_indices_start = len(all_texts)
            all_texts.extend(toc_titles)
            toc_indices_end = len(all_texts)

            # ====== 管线方式：风格检测阶段 ======
            from backend.pipeline import (
                PipelineContext,
                StyleDetectStage,
                TranslationPipeline,
            )

            pipeline = TranslationPipeline()
            pipeline.add_stage(StyleDetectStage(enabled=True))

            ctx = PipelineContext(
                config=cfg,
                texts=all_texts,
                cancel_event=self._cancel_event,
                extra={
                    "title": os.path.basename(cfg["inp"]),
                    "toc_titles": toc_titles,
                },
            )
            ctx = pipeline.run(ctx)

            # 发射风格检测信号
            if ctx.proofread_style:
                proofread_style = ctx.proofread_style
                self.proofreadStyleDetected.emit(
                    proofread_style.display_text,
                    proofread_style.reason,
                    proofread_style.confidence,
                    "auto" if cfg.get("proofread_genre") == "auto" or cfg.get("proofread_tone") == "auto" else "manual",
                )
                cfg["proofread_genre"] = proofread_style.genre
                cfg["proofread_tone"] = proofread_style.tone
            else:
                # 风格检测未启用时使用默认值
                from style_detector import StyleDetectionResult
                proofread_style = StyleDetectionResult(
                    genre=cfg.get("proofread_genre", "general"),
                    tone=cfg.get("proofread_tone", "neutral"),
                    confidence=0,
                    reason="",
                )

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
                proofread_genre=proofread_style.genre,
                proofread_tone=proofread_style.tone,
                proofread_model=cfg.get("proofread_model") or None,  # P3-⑥
                proofread_provider=cfg.get("proofread_provider") or None,
                proofread_api_key=cfg.get("proofread_api_key") or None,
                proofread_api_url=cfg.get("proofread_api_url") or None,
                allow_text_cache_reuse=bool(cfg.get("allow_text_cache_reuse", False)),
            )
            self._translator = translator
            if self._bridge:
                self._bridge._active_translator = translator

            total_chars = sum(len(t) for t in all_texts) or 1
            total_texts = len(all_texts)
            if self._bridge:
                self._bridge._register_active_texts(all_texts, translator)
            estimated_seconds = _estimate_translation_duration(total_chars, total_texts, cfg)
            self.statusChanged.emit(f"开始翻译 预计翻译时长: {_format_duration(estimated_seconds)}")

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
                self.qualityStatUpdate.emit(
                    int(stats.get("dynamic_limit_events", 0)),
                    int(stats.get("rate_limit_events", 0)),
                    int(stats.get("dynamic_limit_workers", cfg.get("max_workers") or 0)),
                    int(stats.get("dynamic_limit_batch_size", cfg.get("batch_size") or 0)),
                    int(stats.get("proofread_batch_requests", 0)),
                    int(stats.get("proofread_batch_success", 0)),
                )

            def on_progress(completed, total):
                self.progressChanged.emit(completed, total, total_chars)
                _emit_stat(completed, total)

            def on_item(src, dst):
                self.itemTranslated.emit(src, dst)

            def on_proofread_detail(detail):
                issues = detail.get("issues") or []
                if isinstance(issues, str):
                    issues = [issues]
                reason = "；".join(str(issue) for issue in issues if str(issue).strip()) or "-"
                draft = str(detail.get("draft", detail.get("before", "")))
                revised = str(detail.get("revised", detail.get("after", "")))
                self.proofreadDetail.emit(
                    str(detail.get("original", "")),
                    draft,
                    revised,
                    reason,
                    bool(detail.get("japanese_residue", False)),
                    bool(detail.get("glossary_mismatch", False)),
                    draft.strip() != revised.strip(),
                )

            try:
                results = translator.translate_batch(
                    all_texts,
                    progress_callback=on_progress,
                    item_callback=on_item,
                    proofread_callback=on_proofread_detail,
                    context_texts=all_texts,
                )
            except TranslationIncompleteError as e:
                translator.flush_cache()
                failed_count = len(e.failed_texts)
                residue_count = len(e.residue_texts)
                samples = "\n".join(f"- {text[:120]}" for text in e.failed_texts[:5])
                message = (
                    f"翻译未完成：{failed_count} 条未成功翻译，"
                    f"{residue_count} 条疑似日文残留。"
                    "已保留成功译文缓存，请降低并发/批量或切换模型后点击恢复续译。"
                )
                self.statusChanged.emit(message)
                self.errorDetail.emit(message + (f"\n样例:\n{samples}" if samples else ""))
                self.failed.emit(message)
                return

            if self._cancel_event.is_set():
                self.finished.emit(CANCELLED_RESULT)
                return

            ordered_results = getattr(translator, "last_ordered_results", [])
            if not isinstance(ordered_results, list) or len(ordered_results) != len(all_texts):
                ordered_results = []
            ordered_cursor = 0

            def next_translated(original):
                nonlocal ordered_cursor
                translated = None
                if ordered_results and ordered_cursor < len(ordered_results):
                    translated = ordered_results[ordered_cursor]
                ordered_cursor += 1
                return translated or results.get(original)

            for record in text_tag_map:
                mode, _, tag = record[0], record[1], record[2]
                if mode == "multi_anchor":
                    node_records = record[3]
                    for node, original in node_records:
                        translated = next_translated(original)
                        if translated:
                            node.replace_with(NavigableString(translated))
                    continue
                original = record[3]
                translated = next_translated(original)
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

            hidden_tags = {"rt", "rp", "script", "style", "noscript"}
            residue_samples = []
            residue_total = 0
            for _, soup, _ in docs:
                root = soup.find("body") or soup
                for node in root.find_all(string=True):
                    parent_name = getattr(getattr(node, "parent", None), "name", "")
                    if parent_name in hidden_tags:
                        continue
                    raw = str(node).strip()
                    if not raw:
                        continue
                    if JaZhTranslator.has_japanese_residue(raw):
                        residue_total += 1
                        if len(residue_samples) < 8:
                            residue_samples.append(raw[:120])

            if residue_total:
                translator.flush_cache()
                samples = "\n".join(f"- {text}" for text in residue_samples)
                message = (
                    f"保存前检查发现 {residue_total} 处疑似日文残留。"
                    "已阻止保存完成品，请调整参数或切换模型后恢复续译。"
                )
                self.statusChanged.emit(message)
                self.errorDetail.emit(message + (f"\n样例:\n{samples}" if samples else ""))
                self.failed.emit(message)
                return

            for item, soup, _ in docs:
                item.set_content(str(soup).encode("utf-8"))

            toc_translations = {}
            for i in range(toc_indices_start, toc_indices_end):
                original = all_texts[i]
                translated = ordered_results[i] if ordered_results and i < len(ordered_results) else results.get(original)
                if translated:
                    toc_translations[original] = translated

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
                    title_index = all_texts.index(title) if title in all_texts else -1
                    tt = ordered_results[title_index] if ordered_results and title_index >= 0 else results.get(title)
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

            on_progress(total_texts, total_texts)
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
            from epub_io import load_book, iter_text_nodes, extract_toc_titles, extract_visible_text

            book = load_book(self._path)
            all_texts = []
            for _, _, tags in iter_text_nodes(book):
                for tag in tags:
                    text = extract_visible_text(tag)
                    if text:
                        all_texts.append(text)
            all_texts.extend(extract_toc_titles(book))
            total = sum(len(t) for t in all_texts)
            self.finished.emit(self._path, total)
        except Exception as e:
            self.failed.emit(self._path, str(e))


def _collect_translatable_texts(epub_path: str):
    from epub_io import load_book, iter_text_nodes, extract_toc_titles, extract_visible_text
    from text_utils import is_translatable

    book = load_book(epub_path)
    texts = []
    for _, _, tags in iter_text_nodes(book):
        for tag in tags:
            anchors = tag.find_all("a")
            if len(anchors) > 1:
                for node in tag.find_all(string=True):
                    raw = str(node).strip()
                    if is_translatable(raw):
                        texts.append(raw)
                continue
            text = extract_visible_text(tag)
            if is_translatable(text):
                texts.append(text)
    texts.extend(extract_toc_titles(book))
    return texts


class _ClearBookCacheWorker(QObject):
    finished = Signal(int, int)
    failed = Signal(str)

    def __init__(self, config: dict):
        super().__init__()
        self._config = config

    def run(self):
        try:
            from translator import JaZhTranslator

            cfg = self._config
            texts = _collect_translatable_texts(cfg["inp"])
            translator = JaZhTranslator(
                api_key=cfg.get("api_key") or "cache-clear",
                provider=cfg.get("provider") or "deepseek",
                api_url=cfg.get("api_url") or None,
                model=cfg.get("model") or None,
                max_workers=1,
                batch_size=1,
                max_batch_length=cfg.get("max_batch_length", 800),
                max_text_size_for_batch=cfg.get("max_text_size_for_batch", 200),
                api_timeout=cfg.get("api_timeout", 120),
                enable_glossary=False,
            )
            removed = translator.clear_cache_for_texts(
                texts,
                include_text_cache=True,
                all_models=True,
            )
            self.finished.emit(removed, len(set(str(text or "").strip() for text in texts if str(text or "").strip())))
        except Exception as e:
            self.failed.emit(str(e))


class _TestWorker(QObject):
    result = Signal(str)

    def __init__(self, api_key, api_url, model, timeout):
        super().__init__()
        self._api_key = api_key
        self._api_url = api_url
        self._model = model
        self._timeout = timeout

    def run(self):
        import requests

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
    proofreadDetail = Signal(str, str, str, str, bool, bool, bool)
    proofreadStyleDetected = Signal(str, str, int, str)
    statusChanged = Signal(str)
    statUpdate = Signal(int, int, int, int, int, float, int, int, int, int)
    qualityStatUpdate = Signal(int, int, int, int, int, int)
    finished = Signal(str)
    failed = Signal(str)
    errorDetail = Signal(str)
    connectionResult = Signal(str)
    estimateFinished = Signal(str, int)
    estimateFailed = Signal(str, str)
    cacheClearFinished = Signal(int, int)
    cacheClearFailed = Signal(str)
    runtimeCleared = Signal()
    manualTranslationLookup = Signal(str)
    manualTranslationSaved = Signal(str)

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
        self._active_texts = []
        self._stop_requested = False

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

    def _start_worker(self, worker, signal_connections, quit_signals):
        """Start a QObject worker on QThread and wire common lifetime handling."""
        thread = QThread(self)
        self._track_worker_thread(worker, thread)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        for signal, slot in signal_connections:
            signal.connect(slot)
        for signal in quit_signals:
            signal.connect(thread.quit)
        thread.start()
        return thread

    def _register_active_texts(self, texts, translator):
        self._active_texts = list(texts or [])
        self._active_translator = translator
        if self._stop_requested:
            self._discard_and_clear_active_cache()

    def _discard_and_clear_active_cache(self):
        translator = self._active_translator
        if not translator:
            return 0
        try:
            translator.disable_cache_writes()
            return translator.clear_cache_for_texts(self._active_texts)
        except Exception as e:
            self.errorDetail.emit(f"停止清理缓存失败: {e}")
            return 0

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
            "proofread_genre": cfg.proofreadGenre, "proofread_tone": cfg.proofreadTone,
            "proofread_provider": getattr(cfg, "proofreadProvider", ""),
            "proofread_api_key": getattr(cfg, "proofreadApiKey", ""),
            "proofread_api_url": getattr(cfg, "proofreadApiUrl", ""),
            "proofread_model": getattr(cfg, "proofreadModel", ""),  # P3-⑥
            "allow_text_cache_reuse": getattr(cfg, "allowTextCacheReuse", False),
        }

    @Slot("QVariant")
    def startTranslation(self, cfg):
        config = self._make_config(cfg)
        if not config["inp"] or not os.path.exists(config["inp"]):
            self.failed.emit("请选择有效的输入 EPUB")
            ToastBridge.warning("请先选择要翻译的 EPUB 文件")
            return
        if not config["out"]:
            self.failed.emit("请填写输出文件路径")
            ToastBridge.warning("请填写输出文件保存路径")
            return
        if config["provider"] in {"deepseek", "doubao", "gemini", "glm", "wenxin", "custom"} and not config["api_key"]:
            self.failed.emit("该提供方需要 API Key")
            ToastBridge.warning("请先在 API 页面配置 API Key")
            return
        if not config["api_url"] or not config["model"]:
            self.failed.emit("请填写 Base URL 和模型")
            ToastBridge.warning("请填写 API 地址和模型名称")
            return
        proofread_provider = config.get("proofread_provider") or ""
        if config.get("enable_proofread") and proofread_provider and proofread_provider != config["provider"]:
            if proofread_provider in {"deepseek", "doubao", "gemini", "glm", "wenxin", "custom"} and not config.get("proofread_api_key"):
                self.failed.emit("校对供应商需要单独填写 API Key")
                ToastBridge.warning("请填写校对模型 API Key")
                return
            if not config.get("proofread_api_url") or not config.get("proofread_model"):
                self.failed.emit("请填写校对模型 Base URL 和模型名")
                ToastBridge.warning("请填写校对模型地址和模型名称")
                return

        self._last_cfg = config
        self._cancel_event.clear()
        self._is_paused = False
        self._stop_requested = False
        self._active_texts = []
        self.busy = True
        self.progressValue = 0.0
        ToastBridge.info("正在加载 EPUB 并开始翻译...")

        worker = _TranslateWorker(config, self._cancel_event)
        worker._bridge = self
        self._start_worker(
            worker,
            [
                (worker.progressChanged, self._on_progress),
                (worker.itemTranslated, self.itemTranslated),
                (worker.proofreadDetail, self.proofreadDetail),
                (worker.proofreadStyleDetected, self.proofreadStyleDetected),
                (worker.statusChanged, self.statusChanged),
                (worker.statUpdate, self.statUpdate),
                (worker.qualityStatUpdate, self.qualityStatUpdate),
                (worker.errorDetail, self.errorDetail),
                (worker.finished, self._on_finished),
                (worker.failed, self._on_failed),
            ],
            [worker.finished, worker.failed],
        )

    def _on_progress(self, completed, total, total_chars):
        self.progressChanged.emit(completed, total, total_chars)
        self.progressValue = float(completed) / float(total) if total > 0 else 0.0

    def _on_finished(self, out_path):
        was_stopped = self._stop_requested
        if was_stopped:
            self._discard_and_clear_active_cache()
        self._active_translator = None
        self._active_texts = []
        self.busy = False
        if out_path == CANCELLED_RESULT:
            if was_stopped:
                self.progressValue = 0.0
                self.runtimeCleared.emit()
                self.finished.emit(STOPPED_RESULT)
                ToastBridge.info("翻译已停止")
            else:
                self.finished.emit(CANCELLED_RESULT)
                ToastBridge.warning("翻译已取消")
        else:
            self.progressValue = 1.0
            self.finished.emit(out_path)
            self.playCompletionVoice()
            ToastBridge.success(f"翻译完成！已保存到: {os.path.basename(out_path)}")
        self._stop_requested = False

    def _on_failed(self, msg):
        self._active_translator = None
        self._active_texts = []
        self.busy = False
        text = str(msg or "")
        if text.startswith("翻译未完成"):
            self._is_paused = True
            self.statusChanged.emit("翻译未完成，可调整参数或切换模型后恢复续译")
            ToastBridge.warning("翻译未完成，可恢复续译")
        else:
            self._is_paused = False
            ToastBridge.error("翻译失败")
        self.failed.emit(text)

    @Slot()
    def cancelTranslation(self):
        self._cancel_event.set()
        self.statusChanged.emit("正在取消...")
        ToastBridge.info("正在取消翻译...")

    @Slot()
    def stopTranslation(self):
        self._is_paused = False
        self._stop_requested = True
        self._cancel_event.set()
        removed = self._discard_and_clear_active_cache()
        self.progressValue = 0.0
        self.runtimeCleared.emit()
        if removed:
            self.statusChanged.emit(f"正在停止... 已清理 {removed} 条本次译文缓存")
        else:
            self.statusChanged.emit("正在停止... 将清空本次译文缓存")

    @Slot()
    def pauseTranslation(self):
        self._is_paused = True
        self._stop_requested = False
        self._cancel_event.set()
        self.statusChanged.emit("暂停中 — 等待当前请求完成...")
        ToastBridge.info("翻译已暂停，可切换模型后继续")

    @Slot("QVariant")
    def clearCurrentBookCache(self, cfg):
        if self.busy:
            self.failed.emit("翻译运行中，不能清理缓存")
            ToastBridge.warning("请先暂停或停止翻译，再清理缓存")
            return
        config = self._make_config(cfg)
        if not config["inp"] or not os.path.exists(config["inp"]):
            self.cacheClearFailed.emit("请选择有效的输入 EPUB")
            ToastBridge.warning("请先选择要清理缓存的 EPUB")
            return
        if not config["api_url"]:
            config["api_url"] = "https://api.deepseek.com/chat/completions"
        if not config["model"]:
            config["model"] = "deepseek-v4-flash"

        self.statusChanged.emit("正在清理当前 EPUB 缓存...")
        ToastBridge.info("正在清理当前 EPUB 缓存...")

        worker = _ClearBookCacheWorker(config)
        self._start_worker(
            worker,
            [
                (worker.finished, self._on_cache_clear_finished),
                (worker.failed, self._on_cache_clear_failed),
            ],
            [worker.finished, worker.failed],
        )

    def _on_cache_clear_finished(self, removed, total_texts):
        self.cacheClearFinished.emit(removed, total_texts)
        self.statusChanged.emit(f"当前 EPUB 缓存清理完成: 删除 {removed} 条，文本 {total_texts} 条")
        ToastBridge.success(f"已清理当前 EPUB 缓存: {removed} 条")

    def _on_cache_clear_failed(self, error):
        self.cacheClearFailed.emit(error)
        self.statusChanged.emit(f"当前 EPUB 缓存清理失败: {error}")
        ToastBridge.error("当前 EPUB 缓存清理失败")

    @Slot(str, str)
    def saveManualTranslation(self, src: str, dst: str):
        """保存人工修改译文。人工译文下次翻译/恢复续译时最高优先级命中。"""
        if not src or not dst:
            self.failed.emit("原文和译文不能为空")
            return
        src = src.strip()
        dst = dst.strip()
        try:
            from translator import JaZhTranslator

            if self._active_translator:
                self._active_translator.save_manual_translation(src, dst)
            else:
                translator = JaZhTranslator(api_key="manual", enable_glossary=False)
                translator.save_manual_translation(src, dst)
            self.manualTranslationSaved.emit(dst)
            self.statusChanged.emit("人工修改已保存，下次翻译/恢复续译时优先使用")
            ToastBridge.success("人工修改已保存")
        except Exception as e:
            self.failed.emit(f"保存人工修改失败: {e}")
            ToastBridge.error("保存人工修改失败")

    @Slot(str)
    def lookupTranslation(self, src: str):
        """在人工缓存、文本缓存和模型缓存中查找已有译文。"""
        if not src:
            return
        src = src.strip()
        try:
            from translator import JaZhTranslator

            translator = self._active_translator or JaZhTranslator(api_key="manual", enable_glossary=False)
            translation, source = translator.lookup_cached_translation(src)
            if translation:
                self.manualTranslationLookup.emit(translation)
                source_labels = {
                    "manual": "人工修改译文",
                    "text_cache": "文本缓存译文",
                    "model_cache": "模型缓存译文",
                }
                self.statusChanged.emit("已找到" + source_labels.get(source, "缓存译文"))
                return
            self.failed.emit("未找到该原文的缓存译文")
            self.statusChanged.emit("未找到缓存译文，可以手动输入")
        except Exception as e:
            self.failed.emit(f"查找译文失败: {e}")
            self.statusChanged.emit(f"查找译文失败: {e}")

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
        self._start_worker(
            worker,
            [
                (worker.result, self.connectionResult),
                (worker.result, self._on_connection_result),
            ],
            [worker.result],
        )

    def _on_connection_result(self, msg):
        if msg and "成功" in msg:
            ToastBridge.success("API 连接测试成功")
        elif msg:
            ToastBridge.error("API 连接测试失败")

    # --- Estimate chars ---
    @Slot(str)
    def startEstimateChars(self, inp_path):
        if not inp_path or not os.path.exists(inp_path):
            self.estimateFinished.emit(inp_path, -1); return
        worker = _EstimateWorker(inp_path)
        self._start_worker(
            worker,
            [
                (worker.finished, self.estimateFinished),
                (worker.failed, self.estimateFailed),
            ],
            [worker.finished, worker.failed],
        )


    @Slot(str, result=bool)
    def exportDiagnostic(self, output_path):
        """Export diagnostic bundle as ZIP: config + logs + glossary."""
        import zipfile
        import os as _os
        from pathlib import Path as _Path
        from translator import get_data_dir

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
        from translator import get_data_dir

        return str(get_data_dir())

