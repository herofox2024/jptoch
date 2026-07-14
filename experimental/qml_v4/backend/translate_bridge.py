# -*- coding: utf-8 -*-
"""
翻译桥接器：包装 JaZhTranslator，通过 QThread worker 运行翻译，信号通知 QML。
"""

import os
import math
import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Optional, Any

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread

import translation_quality as tq
from backend.toast_bridge import ToastBridge

CANCELLED_RESULT = "__CANCELLED__"
STOPPED_RESULT = "__STOPPED__"
logger = logging.getLogger(__name__)

_FILENAME_EXPLANATION_MARKERS = (
    "或依意译",
    "意译处理",
    "没有更多信息",
    "没更多信息",
    "暂无更多信息",
    "暂无信息",
    "这里保留",
    "此处保留",
    "可译为",
    "也可译作",
    "翻译为",
    "译作",
    "直译",
    "音译",
    "合适名",
    "说明",
    "注：",
    "注:",
)

_TOC_EXPLANATION_MARKERS = _FILENAME_EXPLANATION_MARKERS + (
    "简写",
    "简称",
    "希腊神话",
    "神话中",
    "之女",
    "意为",
    "意思是",
    "指的是",
    "源自",
    "来自",
    "出处",
    "典故",
    "可理解为",
    "补充",
    "背景",
    "炫耀",
    "射杀",
    "化作",
    "永远流动",
)


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


def _strip_model_explanation_notes(text, markers):
    value = str(text or "").strip()
    if not value:
        return ""

    # Remove model notes such as "（或依意译处理...这里保留...）" while keeping
    # normal book-title/author parentheses.
    changed = True
    while changed:
        changed = False
        for left, right in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")):
            start = value.find(left)
            while start != -1:
                depth = 1
                end = start + 1
                while end < len(value) and depth > 0:
                    if value.startswith(left, end):
                        depth += 1
                        end += len(left)
                        continue
                    if value.startswith(right, end):
                        depth -= 1
                        if depth == 0:
                            break
                        end += len(right)
                        continue
                    end += 1
                if end == -1:
                    break
                if depth > 0:
                    break
                segment = value[start + 1:end]
                if any(marker in segment for marker in markers):
                    value = value[:start] + value[end + 1:]
                    changed = True
                    start = value.find(left, max(0, start - 1))
                    continue
                start = value.find(left, end + 1)

    value = value.replace(" _ ", " ").replace("_", " ")
    value = " ".join(value.split())
    for mark in ("，)", "、)", "(，", "(、", "，）", "、）", "（，", "（、"):
        value = value.replace(mark, mark[-1] if mark[0] in "，、" else mark[0])
    value = value.replace(" ,", ",").replace(" ，", "，").replace(" 、", "、")
    return value.strip(" ._+-＋，、")


def _strip_filename_explanations(text):
    return _strip_model_explanation_notes(text, _FILENAME_EXPLANATION_MARKERS)


def _clean_translated_filename_candidate(candidate):
    if _looks_like_model_refusal(candidate):
        return ""
    cleaned = _strip_filename_explanations(candidate)
    if not cleaned:
        return ""
    if any(marker in cleaned for marker in _FILENAME_EXPLANATION_MARKERS):
        return ""
    return _sanitize_filename(cleaned)


def _clean_translated_toc_title(candidate):
    if _looks_like_model_refusal(candidate):
        return ""
    value = str(candidate or "").strip()
    for marker in ("【前文", "【后文", "[前文", "[后文"):
        index = value.find(marker)
        if index > 0:
            value = value[:index].strip()

    for prefix in ("【待翻译文本】", "【待翻译标题】", "[待翻译文本]", "[待翻译标题]"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()

    cleaned = _strip_model_explanation_notes(value, _TOC_EXPLANATION_MARKERS)
    if not cleaned:
        return ""

    for prefix in ("译文：", "译文:", "翻译：", "翻译:", "标题：", "标题:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()

    for suffix in ("等内容", "等说明", "的说明", "的解释"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip(" ，,、")

    # If explanatory prose survived outside brackets, keep only the title-like
    # prefix. TOC entries should be short labels, not encyclopedia notes.
    for marker in _TOC_EXPLANATION_MARKERS:
        index = cleaned.find(marker)
        if index > 0:
            prefix = cleaned[:index].rstrip(" ，,、；;：:-—（(")
            if prefix:
                cleaned = prefix
                break

    return cleaned.strip(" ._+-＋，、")


def _looks_like_model_refusal(text):
    value = str(text or "").strip().lower()
    if not value:
        return True

    hard_markers = (
        "请提供具体的日文段落",
        "请提供具体的日文",
        "不是需要翻译的日文内容",
        "并非需要翻译的日文内容",
        "书名或文件名称",
        "似乎是书名",
        "无法按照要求翻译",
        "无法翻译该内容",
        "不能翻译该内容",
        "please provide the japanese",
        "please provide specific japanese",
        "not a japanese text",
        "not text to translate",
    )
    if any(marker in value for marker in hard_markers):
        return True

    apology_markers = ("抱歉", "对不起", "sorry", "apologize")
    task_markers = ("请提供", "无法", "不能", "不是", "并非", "文本", "内容", "翻译", "provide", "cannot", "can't", "unable")
    if any(marker in value for marker in apology_markers) and any(marker in value for marker in task_markers):
        return True

    sentence_marks = sum(value.count(ch) for ch in "。！？!?")
    meta_words = ("文本", "内容", "翻译", "提供", "段落", "句子", "文件", "text", "content", "translate", "provide")
    return sentence_marks >= 2 and any(word in value for word in meta_words)

def _is_usable_translated_filename(candidate):
    return bool(_clean_translated_filename_candidate(candidate))

def _source_title_for_filename(stem):
    value = str(stem or "").strip()
    if not value:
        return ""
    for marker in ("+(", "＋("):
        if marker in value:
            value = value.split(marker, 1)[0]
            break
    return value.strip(" ._+-＋")

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
        "hymt2": {"batch_seconds": 4.0, "chars_per_second": 35.0},
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


def _build_quality_self_check_report(translator, cfg, proofread_style, total_texts, total_chars, elapsed, weak_residue_total, final_out):
    stats = translator.get_stats() if translator else {}
    api_total = int(stats.get("api_requests_total", 0))
    api_failed = int(stats.get("api_requests_failed", 0))
    dynamic_events = int(stats.get("dynamic_limit_events", 0))
    batch_parse_fail = int(stats.get("batch_json_parse_fail", 0))
    batch_lenient = int(stats.get("batch_json_lenient_success", 0))
    proofread_suspicious = int(stats.get("proofread_suspicious", 0))
    proofread_fixed = int(stats.get("proofread_fixed", 0))
    proofread_rejected = int(stats.get("proofread_rejected", 0))
    quality_retranslate = int(stats.get("quality_retranslate", 0))
    tokens_total = int(stats.get("tokens_total", 0))

    warnings = []
    suggestions = []
    if weak_residue_total:
        warnings.append(f"发现 {weak_residue_total} 处弱日文残留，已提示但不阻塞保存。")
        suggestions.append("抽查弱残留样例；只有确认必须保留的片段才加入白名单。")
    if api_failed:
        warnings.append(f"API 失败/异常次数 {api_failed} 次。")
        suggestions.append("免费模型建议降低并发和批量；如果连续触发限流，切换付费模型或稍后恢复续译。")
    if dynamic_events:
        warnings.append(f"动态限流/格式降级触发 {dynamic_events} 次。")
    if batch_parse_fail:
        warnings.append(f"批量 JSON 解析失败 {batch_parse_fail} 次，宽松解析成功 {batch_lenient} 次。")
        suggestions.append("如果 JSON 失败频繁，降低批量大小或对免费模型使用 batch_size=1。")
    if proofread_rejected:
        warnings.append(f"校对结果因疑似错误术语注入被拒绝 {proofread_rejected} 次。")
        suggestions.append("检查术语表中多义词，优先标为“仅供参考”或“上下文命中”。")
    if not bool(cfg.get("enable_proofread", False)):
        warnings.append("译后校对未启用，本次未做日文残留/术语一致性 AI 校对。")
        suggestions.append("正式出书建议启用译后校对，免费模型可使用低并发低批量。")

    status = "通过" if not warnings else "有提醒"
    style_text = getattr(proofread_style, "display_text", "") or "未识别"
    metrics = [
        f"输出文件: {final_out}",
        f"文本块: {total_texts}",
        f"总字符: {total_chars}",
        f"耗时: {_format_duration(elapsed)}",
        f"Prompt 风格: {style_text}",
        f"API 请求: {api_total}",
        f"Token: {tokens_total if tokens_total > 0 else '--'}",
        f"可疑译文: {proofread_suspicious}",
        f"校对修复: {proofread_fixed}",
        f"重译次数: {quality_retranslate}",
    ]
    if not suggestions:
        suggestions.append("本次没有发现明显流程风险；如修改 Prompt 或术语策略后需要重译，请先清理当前 EPUB 缓存。")
    summary = (
        f"本次翻译完成，质量自检结果：{status}。"
        f"校对发现 {proofread_suspicious} 条可疑译文，修复 {proofread_fixed} 条。"
    )
    return {
        "status": status,
        "summary": summary,
        "metricsText": "\n".join(metrics),
        "warningsText": "\n".join(f"- {item}" for item in warnings) if warnings else "未发现需要阻塞保存的问题。",
        "suggestionsText": "\n".join(f"- {item}" for item in suggestions),
        "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


class _TranslateWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    progressChanged = Signal(int, int, int)
    itemTranslated = Signal(str, str)
    proofreadDetail = Signal(str, str, str, str, bool, bool, bool)
    proofreadStyleDetected = Signal(str, str, int, str)
    statusChanged = Signal(str)
    statUpdate = Signal(int, int, int, int, int, float, int, int, int, int)
    qualityStatUpdate = Signal(int, int, int, int, int, int, int, int, int, int)
    qualityReportReady = Signal("QVariantMap")
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
            from translator import JaZhTranslator, TranslationIncompleteError
            from epub_io import (
                load_book,
                save_book,
                iter_text_nodes,
                extract_toc_titles,
                apply_toc_translations,
                add_translation_notice_page,
            )
            from backend.book_translation_service import (
                BookTranslationService,
            )
            from text_utils import is_translatable

            book = load_book(cfg["inp"])
            docs = list(iter_text_nodes(book))
            toc_titles = extract_toc_titles(book)
            book_service = BookTranslationService()
            book_text_plan = book_service.build_text_plan(docs, toc_titles)
            all_texts = book_text_plan.all_texts

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
                allow_text_cache_reuse=bool(cfg.get("allow_text_cache_reuse", True)),
                prompt_extra_instruction=cfg.get("prompt_extra_instruction", ""),
                enable_prompt_examples=bool(cfg.get("enable_prompt_examples", True)),
                hymt2_generation_mode=cfg.get("hymt2_generation_mode", "stable"),
                hymt2_prompt_mode=cfg.get("hymt2_prompt_mode", "official"),
                hymt2_runtime_mode=cfg.get("hymt2_runtime_mode", "cpu"),
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
                    int(stats.get("proofread_suspicious", 0)),
                    int(stats.get("proofread_fixed", 0)),
                    int(stats.get("quality_retranslate", 0)),
                    int(stats.get("japanese_residue_remaining", 0)),
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
                message = (
                    f"翻译未完成：{failed_count} 条未成功翻译，"
                    f"{residue_count} 条疑似日文残留。"
                    "已保留成功译文缓存，请降低并发/批量或切换模型后点击恢复续译。"
                )
                if hasattr(e, "format_diagnostics"):
                    detail = e.format_diagnostics(max_items=5)
                else:
                    samples = "\n".join(f"- {text[:120]}" for text in e.failed_texts[:5])
                    detail = message + (f"\n样例:\n{samples}" if samples else "")
                if residue_count:
                    try:
                        allowlist_path = JaZhTranslator.japanese_residue_allowlist_path()
                    except Exception:
                        allowlist_path = ""
                    known_terms_path = tq.known_katakana_terms_path()
                    detail += (
                        "\n\n处理建议：如果残留片段是真正未翻译的日文，请不要加入白名单，"
                        "建议降低批量/并发或切换模型后恢复续译。"
                        "\n如果残留片段是器物名、外来语或专有名词，且应该固定译成中文，"
                        "请在 设置 -> 风格与校对 -> 片假名术语修复词表 添加。"
                        "\n如果残留片段是必须保留的字形、符号或原文标记，"
                        "可在 设置 -> 风格与校对 -> 日文残留白名单 添加。"
                    )
                    detail += f"\n片假名修复词表: {known_terms_path}"
                    if allowlist_path:
                        detail += f"\n白名单文件: {allowlist_path}"
                self.statusChanged.emit(message)
                self.errorDetail.emit(detail)
                self.failed.emit(message)
                return

            if self._cancel_event.is_set():
                self.finished.emit(CANCELLED_RESULT)
                return

            ordered_results = getattr(translator, "last_ordered_results", [])
            if not isinstance(ordered_results, list) or len(ordered_results) != len(all_texts):
                ordered_results = []
            book_service.apply_translations(
                book_text_plan,
                results,
                ordered_results,
                _clean_translated_toc_title,
                _looks_like_model_refusal,
            )

            repair_report = book_service.repair_known_katakana_terms(docs)
            if repair_report.repaired_total:
                logger.info(
                    "保存前自动修复日文残留 %s 处。样例: %s",
                    repair_report.repaired_total,
                    " | ".join(repair_report.samples),
                )

            residue_scan = book_service.scan_japanese_residue(docs)
            residue_total = residue_scan.blocking_total
            residue_samples = residue_scan.blocking_samples
            weak_residue_total = residue_scan.weak_total
            weak_residue_samples = residue_scan.weak_samples

            if residue_total:
                translator.flush_cache()
                samples = "\n".join(f"- {text}" for text in residue_samples)
                logger.error(
                    "保存前检查发现 %s 处疑似日文残留，已阻止保存。样例:\n%s",
                    residue_total,
                    samples,
                )
                message = (
                    f"保存前检查发现 {residue_total} 处疑似日文残留。"
                    "已阻止保存完成品，请调整参数或切换模型后恢复续译。"
                )
                self.statusChanged.emit(message)
                allowlist_path = JaZhTranslator.japanese_residue_allowlist_path()
                known_terms_path = tq.known_katakana_terms_path()
                hint = (
                    "\n处理建议：如果片段应该译成中文，例如器物名、外来语或专有名词，"
                    "请加入 设置 -> 风格与校对 -> 片假名术语修复词表。"
                    f"\n片假名修复词表: {known_terms_path}"
                    "\n如果确认某个片段是必须保留的字形、符号或原文标记，"
                    f"才加入日文残留白名单: {allowlist_path}"
                )
                self.errorDetail.emit(message + hint + (f"\n样例:\n{samples}" if samples else ""))
                self.failed.emit(message)
                return
            if weak_residue_total:
                logger.warning(
                    "保存前检查发现 %s 处弱日文残留，已提示但不阻塞保存。样例: %s",
                    weak_residue_total,
                    " | ".join(weak_residue_samples),
                )

            for item, soup, _ in docs:
                item.set_content(str(soup).encode("utf-8"))

            toc_translations = book_service.build_toc_translation_map(
                book_text_plan,
                results,
                ordered_results,
                _clean_translated_toc_title,
                _looks_like_model_refusal,
            )

            if toc_translations:
                apply_toc_translations(book, toc_translations)

            if bool(cfg.get("enable_notice_page", False)):
                add_translation_notice_page(book, cfg.get("notice_page_text") or "")
                logger.info("已添加版权提示页")

            try:
                logger.info("开始保存 EPUB: %s", cfg["out"])
                save_book(cfg["out"], book, chinese_mode=(cfg["direction"] == "zh"))
            except Exception:
                logger.exception("EPUB 保存失败: %s", cfg["out"])
                raise
            final_out = cfg["out"]

            # Smart output filename: translate the EPUB filename
            try:
                source_path = __import__("pathlib", fromlist=["Path"]).Path(cfg["out"])
                source_base = __import__("pathlib", fromlist=["Path"]).Path(cfg["inp"]).stem
                import os as _os
                candidates = []
                source_title = _source_title_for_filename(source_base)
                if source_title and source_title in results and results[source_title]:
                    candidates.append(str(results[source_title]))
                if source_title and is_translatable(source_title):
                    try:
                        name_results = translator.translate_batch([source_title])
                        t_name = name_results.get(source_title)
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
                    safe = _clean_translated_filename_candidate(candidate)
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
            quality_report = _build_quality_self_check_report(
                translator,
                cfg,
                proofread_style,
                total_texts,
                total_chars,
                max(0.0, time.time() - start_ts),
                weak_residue_total,
                final_out,
            )
            logger.info("翻译质量自检报告: %s", quality_report.get("summary", ""))
            self.qualityReportReady.emit(quality_report)
            self.finished.emit(final_out)

        except Exception as e:
            if self._cancel_event.is_set():
                self.finished.emit(CANCELLED_RESULT)
                return
            logger.exception("翻译任务失败")
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
                hymt2_generation_mode=cfg.get("hymt2_generation_mode", "stable"),
                hymt2_prompt_mode=cfg.get("hymt2_prompt_mode", "official"),
                hymt2_runtime_mode=cfg.get("hymt2_runtime_mode", "cpu"),
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
        except requests.exceptions.ConnectionError as e:
            message = str(e)
            if "10061" in message or "Connection refused" in message or "actively refused" in message:
                self.result.emit(
                    "失败: 本地服务未启动或端口未监听。"
                    "请在下方 Hy-MT2 本地模型区域选择 llama-server 后点击“启动本地服务”，"
                    "或确认外部 llama-server 正在监听当前 API URL。"
                )
            else:
                self.result.emit(f"失败: 网络连接失败 — {message[:240]}")
        except Exception as e:
            self.result.emit(f"失败: {e}")


class TranslateBridge(QObject):

    progressChanged = Signal(int, int, int)
    itemTranslated = Signal(str, str)
    proofreadDetail = Signal(str, str, str, str, bool, bool, bool)
    proofreadStyleDetected = Signal(str, str, int, str)
    statusChanged = Signal(str)
    statUpdate = Signal(int, int, int, int, int, float, int, int, int, int)
    qualityStatUpdate = Signal(int, int, int, int, int, int, int, int, int, int)
    qualityReportReady = Signal("QVariantMap")
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

    def _request_active_cancel(self, close_session: bool = True):
        self._cancel_event.set()
        translator = self._active_translator
        if translator and hasattr(translator, "request_cancel"):
            try:
                translator.request_cancel(close_session=close_session)
            except Exception:
                pass

    @Slot()
    def shutdown(self):
        """Best-effort cancellation for application shutdown."""
        self._request_active_cancel(close_session=True)
        for _, thread in list(self._pending_workers):
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait(1500)
            except Exception:
                pass

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
            "allow_text_cache_reuse": getattr(cfg, "allowTextCacheReuse", True),
            "prompt_extra_instruction": getattr(cfg, "promptExtraInstruction", ""),
            "enable_prompt_examples": getattr(cfg, "enablePromptExamples", True),
            "enable_notice_page": getattr(cfg, "enableNoticePage", False),
            "notice_page_text": getattr(cfg, "noticePageText", ""),
            "hymt2_generation_mode": getattr(cfg, "hymt2GenerationMode", "stable"),
            "hymt2_prompt_mode": getattr(cfg, "hymt2PromptMode", "official"),
            "hymt2_runtime_mode": getattr(cfg, "hymt2RuntimeMode", "cpu"),
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
                (worker.qualityReportReady, self.qualityReportReady),
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
        self._request_active_cancel(close_session=True)
        self.statusChanged.emit("正在取消...")
        ToastBridge.info("正在取消翻译...")

    @Slot()
    def stopTranslation(self):
        self._is_paused = False
        self._stop_requested = True
        self._request_active_cancel(close_session=True)
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
        self._request_active_cancel(close_session=True)
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

    @Slot("QVariant", str, result="QVariantMap")
    def addNoticePageToBooks(self, paths: Any, notice_text: str):
        try:
            from epub_io import load_book, save_book, add_translation_notice_page

            if hasattr(paths, "toVariant"):
                paths = paths.toVariant()
            if isinstance(paths, (str, bytes)):
                paths = [paths]
            if paths is None:
                paths = []

            source_paths = []
            for item in paths:
                path = str(item or "").strip()
                if path.lower().startswith("file:///"):
                    path = path[8:]
                elif path.lower().startswith("file://"):
                    path = path[7:]
                path = path.replace("/", os.sep)
                if path and path.lower().endswith(".epub") and os.path.exists(path):
                    source_paths.append(path)

            source_paths = list(dict.fromkeys(source_paths))
            if not source_paths:
                return {"ok": False, "message": "请选择有效的 EPUB 文件", "succeeded": 0, "failed": 0}

            succeeded = 0
            failed = []
            for source in source_paths:
                try:
                    book = load_book(source)
                    add_translation_notice_page(book, notice_text)
                    src_path = Path(source)
                    out_path = _unique_epub_path(src_path.with_name(src_path.stem + "_notice.epub"))
                    save_book(str(out_path), book, chinese_mode=True)
                    succeeded += 1
                    logger.info("已添加版权提示页: %s -> %s", source, out_path)
                except Exception as exc:
                    failed.append(f"{Path(source).name}: {exc}")
                    logger.exception("批量添加版权提示页失败: %s", source)

            if failed:
                message = f"版权提示页批量处理完成: 成功 {succeeded} 本，失败 {len(failed)} 本"
                return {
                    "ok": succeeded > 0,
                    "message": message + "\n" + "\n".join(failed[:5]),
                    "succeeded": succeeded,
                    "failed": len(failed),
                }
            return {
                "ok": True,
                "message": f"已为 {succeeded} 本 EPUB 生成 _notice 副本",
                "succeeded": succeeded,
                "failed": 0,
            }
        except Exception as exc:
            logger.exception("批量添加版权提示页异常")
            return {"ok": False, "message": f"批量添加失败: {exc}", "succeeded": 0, "failed": 0}

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
        if hasattr(cfg, "allowTextCacheReuse"):
            try:
                cfg.allowTextCacheReuse = True
                cfg.saveToDisk()
            except Exception:
                logger.debug("恢复续译时启用跨模型缓存复用失败", exc_info=True)
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
        import json
        import zipfile
        from backend.diagnostics import load_redacted_config_snapshot
        from translator import get_data_dir

        try:
            data_dir = get_data_dir()
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                config_path = data_dir / "config.json"
                if config_path.exists():
                    snapshot = load_redacted_config_snapshot(config_path)
                    zf.writestr(
                        "config_snapshot.json",
                        json.dumps(snapshot, ensure_ascii=False, indent=2),
                    )
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

