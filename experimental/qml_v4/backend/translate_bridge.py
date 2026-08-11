# -*- coding: utf-8 -*-
"""
翻译桥接器：包装 JaZhTranslator，通过 QThread worker 运行翻译，信号通知 QML。
"""

import os
import json
import logging
import threading
import time
import traceback
from pathlib import Path
from typing import Optional, Any, Dict, List, Tuple

from PySide6.QtCore import QObject, Signal, Slot, Property, QThread

import translation_quality as tq
from provider_registry import API_KEY_REQUIRED_PROVIDERS, provider_default_model, provider_default_url
from backend.toast_bridge import ToastBridge
from backend.task_history import (
    TranslationTaskHistoryStore,
    make_task_id,
    normalize_failed_blocks,
    sanitize_config,
)
from backend.bridge_workers import (
    ClearBookCacheWorker as _ClearBookCacheWorker,
    EstimateWorker as _EstimateWorker,
    TestConnectionWorker as _TestWorker,
    collect_translatable_texts as _collect_translatable_texts,
)
from backend.output_naming import (
    FILENAME_EXPLANATION_MARKERS as _OUTPUT_FILENAME_MARKERS,
    clean_translated_filename_candidate as _clean_filename,
    clean_translated_toc_title as _clean_toc_title,
    looks_like_model_refusal as _is_model_refusal,
    sanitize_filename as _sanitize_output_filename,
    source_title_for_filename as _source_output_title,
    strip_model_explanation_notes as _strip_output_notes,
    unique_epub_path as _next_epub_path,
)
from backend.translation_reports import (
    build_quality_self_check_report as _build_quality_report,
    estimate_translation_duration as _estimate_duration,
    format_duration as _display_duration,
    write_japanese_residue_report as _write_residue_report,
)

CANCELLED_RESULT = "__CANCELLED__"
STOPPED_RESULT = "__STOPPED__"
logger = logging.getLogger(__name__)

JAPANESE_RESIDUE_POLICIES = {"strict", "balanced", "lenient"}

def _sanitize_filename(name):
    return _sanitize_output_filename(name)


def _write_japanese_residue_report(
    *,
    output_path: str,
    policy: str,
    blocked_total: int,
    scan: Any,
) -> str:
    return _write_residue_report(
        output_path=output_path,
        policy=policy,
        blocked_total=blocked_total,
        scan=scan,
    )


def _strip_model_explanation_notes(text, markers):
    return _strip_output_notes(text, markers)


def _strip_filename_explanations(text):
    return _strip_output_notes(text, _OUTPUT_FILENAME_MARKERS)


def _clean_translated_filename_candidate(candidate):
    return _clean_filename(candidate)


def _clean_translated_toc_title(candidate):
    return _clean_toc_title(candidate)


def _looks_like_model_refusal(text):
    return _is_model_refusal(text)

def _is_usable_translated_filename(candidate):
    return bool(_clean_translated_filename_candidate(candidate))

def _source_title_for_filename(stem):
    return _source_output_title(stem)

def _unique_epub_path(path):
    return _next_epub_path(path)


def _format_duration(seconds):
    return _display_duration(seconds)


def _estimate_translation_duration(total_chars, total_texts, cfg):
    return _estimate_duration(total_chars, total_texts, cfg)


def _preextract_glossary_profiles(
    cfg,
    proofread_style,
    texts,
    cancel_event,
    status_callback=None,
    progress_callback=None,
    *,
    force: bool = False,
    target_scopes: Optional[List[Any]] = None,
):
    from glossary_profiles import upsert_profile
    from translator import JaZhTranslator, get_data_dir

    def _emit_status(message: str) -> None:
        if status_callback:
            try:
                status_callback(message)
            except Exception:
                pass

    if not force and not bool(cfg.get("pre_extract_glossary", False)):
        return {"ok": True, "message": "未启用术语提取", "profile_ids": [], "profiles": [], "text_count": 0, "char_count": 0}

    source_book = Path(str(cfg.get("inp") or "")).stem.strip()
    if not source_book:
        source_book = "book"

    targets = []
    genre_name = str(getattr(proofread_style, "genre_label", "") or getattr(proofread_style, "genre", "") or "").strip()
    series_name = str(cfg.get("series_glossary_name") or "").strip()
    if target_scopes is not None:
        for item in target_scopes:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                scope, name = item[0], item[1]
            elif isinstance(item, dict):
                scope, name = item.get("scope"), item.get("name")
            else:
                continue
            scope = str(scope or "").strip().lower()
            name = str(name or "").strip()
            if scope in {"genre", "series", "book"} and name:
                targets.append((scope, name))
    else:
        if bool(cfg.get("use_genre_glossary", False)):
            if genre_name:
                targets.append(("genre", genre_name))
            else:
                _emit_status("术语提取：已启用题材术语，但未识别到题材名称")
        if bool(cfg.get("use_series_glossary", False)):
            if series_name:
                targets.append(("series", series_name))
            else:
                _emit_status("术语提取：已启用系列术语，但未填写系列名")
        if bool(cfg.get("use_book_glossary", False)) or not targets:
            targets.append(("book", source_book))

    targets = list(dict.fromkeys(targets))
    if not texts:
        return {
            "ok": True,
            "message": "未找到可用于术语提取的文本",
            "profile_ids": [],
            "profiles": [],
            "text_count": 0,
            "char_count": 0,
        }

    provider = str(cfg.get("provider") or "deepseek").strip().lower()
    api_url = str(cfg.get("api_url") or "").strip() or None
    model = str(cfg.get("model") or "").strip() or None
    api_key = str(cfg.get("api_key") or "").strip()
    glossary_extraction_mode = str(cfg.get("glossary_extraction_mode") or "lite").strip().lower()
    if glossary_extraction_mode not in {"novel", "lite"}:
        glossary_extraction_mode = "lite"
    if provider in {"hymt2", "sakura"} and not api_key:
        api_key = "sk-local"
    configured_timeout = int(cfg.get("api_timeout") or 120)
    extraction_timeout = (
        max(120, min(configured_timeout, 300))
        if provider in {"hymt2", "sakura"}
        else max(30, min(configured_timeout, 90))
    )
    logger.info(
        "术语提取准备: provider=%s, model=%s, mode=%s, texts=%s, chars<=%s, max_texts=%s, timeout=%ss",
        provider,
        model or "",
        glossary_extraction_mode,
        len(texts or []),
        30000,
        120,
        extraction_timeout,
    )
    _emit_status(
        f"术语提取使用模型: {provider}/{model or ''}，模式={glossary_extraction_mode}，超时={extraction_timeout}s"
    )

    extractor = None
    try:
        extractor = JaZhTranslator(
            api_key=api_key,
            provider=provider,
            api_url=api_url,
            model=model,
            max_workers=max(1, min(int(cfg.get("max_workers") or 1), 4)),
            batch_size=max(1, min(int(cfg.get("batch_size") or 1), 4)),
            max_batch_length=max(100, min(int(cfg.get("max_batch_length") or 800), 1000)),
            max_text_size_for_batch=max(60, min(int(cfg.get("max_text_size_for_batch") or 200), 250)),
            api_timeout=extraction_timeout,
            cancel_event=cancel_event,
            extract_glossary=False,
            enable_glossary=False,
            enable_thinking=bool(cfg.get("enable_thinking", False)),
            enable_proofread=False,
            proofread_genre=str(cfg.get("proofread_genre") or "general"),
            proofread_tone=str(cfg.get("proofread_tone") or "neutral"),
            prompt_extra_instruction=str(cfg.get("prompt_extra_instruction") or ""),
            enable_prompt_examples=bool(cfg.get("enable_prompt_examples", True)),
            hymt2_generation_mode=str(cfg.get("hymt2_generation_mode") or "stable"),
            hymt2_prompt_mode=str(cfg.get("hymt2_prompt_mode") or "official"),
            hymt2_runtime_mode=str(cfg.get("hymt2_runtime_mode") or "cpu"),
            glossary_extraction_mode=glossary_extraction_mode,
            allow_text_cache_reuse=False,
        )

        def _progress(batch_index, total_batches):
            if progress_callback:
                try:
                    progress_callback(batch_index, total_batches)
                except Exception:
                    pass
            _emit_status(f"正在提取术语 {batch_index}/{total_batches}: {provider}/{model or ''}")

        extracted = extractor.extract_glossary_candidates(
            list(texts),
            batch_size=max(1, min(int(cfg.get("batch_size") or 1), 4)),
            max_chars=30000,
            max_texts=120,
            extraction_mode=glossary_extraction_mode,
            progress_callback=_progress,
        )
    finally:
        try:
            if extractor is not None:
                extractor.request_cancel(close_session=True)
        except Exception:
            pass

    profile_ids = []
    profiles = []
    terms = extracted.get("glossary") if isinstance(extracted, dict) else {}
    candidate_count = int(extracted.get("text_count") or 0) if isinstance(extracted, dict) else 0
    char_count = int(extracted.get("char_count") or 0) if isinstance(extracted, dict) else 0
    moderation_skipped = int(extracted.get("moderation_skipped") or 0) if isinstance(extracted, dict) else 0
    has_terms = bool(
        isinstance(terms, dict)
        and any(isinstance(entries, list) and entries for entries in terms.values())
    )
    if has_terms:
        data_dir = get_data_dir()
        for scope, name in targets:
            profile = upsert_profile(
                data_dir,
                name=name,
                scope=scope,
                terms=terms,
                description=f"模型提取自 {source_book}",
                source_book=source_book,
            )
            if profile and profile.get("id"):
                profile_ids.append(str(profile["id"]))
                profiles.append(profile)

    profile_ids = list(dict.fromkeys(profile_ids))
    if profile_ids:
        message = f"术语提取完成: {len(profile_ids)} 个 profile，候选文本 {candidate_count} 条"
        if moderation_skipped:
            message += f"，内容审核跳过 {moderation_skipped} 条"
    elif moderation_skipped:
        message = f"术语提取完成，内容审核跳过 {moderation_skipped} 条，没有生成可保存的术语候选"
    else:
        message = "术语提取完成，但没有生成可保存的术语候选"
    _emit_status(message)
    return {
        "ok": True,
        "message": message,
        "profile_ids": profile_ids,
        "profiles": profiles,
        "text_count": candidate_count,
        "char_count": char_count,
        "moderation_skipped": moderation_skipped,
        "term_count": sum(len(entries) for entries in terms.values()) if isinstance(terms, dict) else 0,
    }


def _build_quality_self_check_report(translator, cfg, proofread_style, total_texts, total_chars, elapsed, weak_residue_total, final_out):
    return _build_quality_report(
        translator,
        cfg,
        proofread_style,
        total_texts,
        total_chars,
        elapsed,
        weak_residue_total,
        final_out,
    )


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
            from epub_io import save_book, set_book_title_metadata
            from backend.pipeline import (
                BatchTranslateStage,
                CreateTranslatorStage,
                PipelineContext,
                TranslationPipeline,
                run_apply_pipeline,
                run_finalize_pipeline,
                run_ingest_pipeline,
            )
            from text_utils import is_translatable

            ctx = PipelineContext(
                config=cfg,
                cancel_event=self._cancel_event,
                extra={
                    "title": os.path.basename(cfg["inp"]),
                    "clean_title": _clean_translated_toc_title,
                    "looks_like_refusal": _looks_like_model_refusal,
                },
            )
            ctx = run_ingest_pipeline(ctx)

            book = ctx.book
            docs = ctx.docs
            toc_titles = ctx.toc_titles
            book_service = ctx.book_service
            book_text_plan = ctx.text_plan
            all_texts = ctx.texts

            # 发送风格检测信号
            proofread_style = ctx.proofread_style
            if proofread_style:
                self.proofreadStyleDetected.emit(
                    proofread_style.display_text,
                    proofread_style.reason,
                    proofread_style.confidence,
                    "auto" if cfg.get("proofread_genre") == "auto" or cfg.get("proofread_tone") == "auto" else "manual",
                )
                cfg["proofread_genre"] = proofread_style.genre
                cfg["proofread_tone"] = proofread_style.tone

            ctx = CreateTranslatorStage().process(ctx)

            translator = ctx.translator
            self._translator = translator
            if self._bridge:
                self._bridge._active_translator = translator

            total_chars = sum(len(t) for t in all_texts) or 1
            total_texts = len(all_texts)
            if self._bridge:
                self._bridge._record_translation_task_text_plan(all_texts)
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

            last_progress_emit_ts = 0.0
            last_progress_completed = -1
            progress_emit_interval = 0.5
            progress_emit_step = 20
            last_item_emit_ts = 0.0
            item_emit_interval = 0.3

            def on_progress(completed, total):
                nonlocal last_progress_emit_ts, last_progress_completed
                now = time.time()
                force = completed <= 0 or completed >= total
                enough_time = now - last_progress_emit_ts >= progress_emit_interval
                enough_step = completed - last_progress_completed >= progress_emit_step
                if not (force or enough_time or enough_step):
                    return
                last_progress_emit_ts = now
                last_progress_completed = completed
                self.progressChanged.emit(completed, total, total_chars)
                _emit_stat(completed, total)

            def on_item(src, dst):
                nonlocal last_item_emit_ts
                if self._bridge:
                    self._bridge._record_translation_item_success(src, dst)
                now = time.time()
                if now - last_item_emit_ts >= item_emit_interval:
                    last_item_emit_ts = now
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
                ctx.progress_callback = on_progress
                ctx.item_callback = on_item
                ctx.proofread_callback = on_proofread_detail
                ctx = TranslationPipeline().add_stage(BatchTranslateStage()).run(ctx)
                results = ctx.results
                ordered_results = ctx.ordered_results
            except TranslationIncompleteError as e:
                translator.flush_cache()
                failed_count = len(e.failed_texts)
                residue_count = len(e.residue_texts)
                if self._bridge:
                    self._bridge._record_translation_task_failures(e)
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

            ctx.results = results
            ctx.ordered_results = ordered_results
            ctx = run_apply_pipeline(ctx)
            repair_report = ctx.repair_report
            if repair_report and repair_report.repaired_total:
                logger.info(
                    "保存前自动修复日文残留 %s 处。样例: %s",
                    repair_report.repaired_total,
                    " | ".join(repair_report.samples),
                )

            residue_scan = ctx.residue_scan
            residue_total = residue_scan.blocking_total
            residue_samples = residue_scan.blocking_samples
            hard_residue_total = getattr(residue_scan, "hard_blocking_total", residue_total)
            hard_residue_samples = getattr(residue_scan, "hard_blocking_samples", residue_samples)
            high_residue_total = getattr(residue_scan, "high_risk_total", 0)
            medium_residue_total = getattr(residue_scan, "medium_risk_total", 0)
            low_risk_residue_total = getattr(residue_scan, "low_risk_total", 0)
            low_risk_residue_samples = getattr(residue_scan, "low_risk_samples", [])
            weak_residue_total = residue_scan.weak_total
            weak_residue_samples = residue_scan.weak_samples
            residue_policy = str(cfg.get("japanese_residue_policy") or "balanced").strip().lower()
            if residue_policy not in JAPANESE_RESIDUE_POLICIES:
                residue_policy = "balanced"

            if residue_policy == "strict":
                blocking_residue_total = residue_total
                blocking_residue_samples = residue_samples
            elif residue_policy == "balanced":
                blocking_residue_total = hard_residue_total
                blocking_residue_samples = hard_residue_samples
            else:
                blocking_residue_total = 0
                blocking_residue_samples = []

            if blocking_residue_total:
                translator.flush_cache()
                report_path = _write_japanese_residue_report(
                    output_path=cfg.get("out", ""),
                    policy=residue_policy,
                    blocked_total=blocking_residue_total,
                    scan=residue_scan,
                )
                samples = "\n".join(f"- {text}" for text in blocking_residue_samples)
                if self._bridge:
                    self._bridge._record_translation_task_save_residue(
                        blocking_residue_samples,
                        blocking_residue_total,
                        report_path,
                    )
                logger.error(
                    "保存前检查发现 %s 处阻断级日文残留，策略=%s，高风险=%s，中风险=%s，低风险=%s，已阻止保存。报告: %s\n样例:\n%s",
                    blocking_residue_total,
                    residue_policy,
                    high_residue_total,
                    medium_residue_total,
                    low_risk_residue_total,
                    report_path,
                    samples,
                )
                message = (
                    f"保存前检查发现 {blocking_residue_total} 处阻断级日文残留"
                    f"（高风险 {high_residue_total}，中风险 {medium_residue_total}，低风险 {low_risk_residue_total}）。"
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
                self.errorDetail.emit(
                    message
                    + hint
                    + f"\n残留报告: {report_path}"
                    + (f"\n样例:\n{samples}" if samples else "")
                )
                self.failed.emit(message)
                return
            if residue_total:
                report_path = _write_japanese_residue_report(
                    output_path=cfg.get("out", ""),
                    policy=residue_policy,
                    blocked_total=0,
                    scan=residue_scan,
                )
                logger.warning(
                    "保存前检查发现 %s 处日文残留，策略=%s，高风险=%s，中风险=%s，低风险=%s，硬残留=%s，已允许保存并写入报告: %s。样例: %s",
                    residue_total,
                    residue_policy,
                    high_residue_total,
                    medium_residue_total,
                    low_risk_residue_total,
                    hard_residue_total,
                    report_path,
                    " | ".join((low_risk_residue_samples or residue_samples)[:8]),
                )
                self.statusChanged.emit(
                    f"保存前检查发现 {residue_total} 处日文残留（高 {high_residue_total} / 中 {medium_residue_total} / 低 {low_risk_residue_total}），已按{residue_policy}策略允许保存。报告: {report_path}"
                )
            if weak_residue_total:
                logger.warning(
                    "保存前检查发现 %s 处弱日文残留，已提示但不阻塞保存。样例: %s",
                    weak_residue_total,
                    " | ".join(weak_residue_samples),
                )

            safe_output_title = ""
            try:
                source_base = Path(cfg["inp"]).stem
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
                    if safe:
                        safe_output_title = safe
                        break
            except Exception:
                safe_output_title = ""

            if safe_output_title and cfg.get("direction") == "zh":
                set_book_title_metadata(book, safe_output_title)

            ctx = run_finalize_pipeline(ctx)

            try:
                logger.info("开始保存 EPUB: %s", cfg["out"])
                save_book(cfg["out"], book, chinese_mode=(cfg["direction"] == "zh"))
            except Exception:
                logger.exception("EPUB 保存失败: %s", cfg["out"])
                raise
            final_out = cfg["out"]

            # Smart output filename: use the same safe title written to EPUB metadata.
            if safe_output_title:
                try:
                    source_path = Path(cfg["out"])
                    target = source_path.with_name(safe_output_title + ".epub")
                    if os.path.normcase(os.path.abspath(str(target))) == os.path.normcase(os.path.abspath(str(source_path))):
                        final_out = str(source_path)
                    else:
                        candidate_path = str(_unique_epub_path(target))
                        Path(cfg["out"]).rename(candidate_path)
                        final_out = candidate_path
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


class _RetranslateFailedBlocksWorker(QObject):
    finished = Signal("QVariantMap")
    failed = Signal(str)
    statusChanged = Signal(str)

    def __init__(self, config: Dict[str, Any], blocks: List[Dict[str, Any]], cancel_event):
        super().__init__()
        self._config = dict(config or {})
        self._blocks = list(blocks or [])
        self._cancel_event = cancel_event

    @staticmethod
    def _block_source(block: Dict[str, Any]) -> str:
        kind = str(block.get("kind") or "")
        if kind not in {"failed", "residue"}:
            return ""
        return str(block.get("text") or "").strip()

    def run(self):
        try:
            from translator import JaZhTranslator, TranslationIncompleteError
            from translation_models import RecoveryAction, RecoveryIssue
            from backend.recovery_agent import RecoveryAgent
            from backend.recovery_executor import RecoveryExecutor
            from backend.recovery_workflow import RecoveryWorkflow

            cfg = self._config
            sources = []
            recovery_blocks = []
            skipped = 0
            for block in self._blocks:
                if not isinstance(block, dict):
                    skipped += 1
                    continue
                source = self._block_source(block)
                if source:
                    if isinstance(block.get("recovery_decision"), dict) and isinstance(block.get("recovery_issue"), dict):
                        recovery_blocks.append((source, block))
                    else:
                        sources.append(source)
                else:
                    skipped += 1
            sources = list(dict.fromkeys(sources))
            if not sources and not recovery_blocks:
                self.finished.emit(
                    {
                        "ok": False,
                        "message": "没有可自动重译的失败块；保存前残留块需要人工定位或继续整本续译。",
                        "total": 0,
                        "success": 0,
                        "failed": 0,
                        "skipped": skipped,
                        "translations": {},
                    }
                )
                return

            total_sources = len(sources) + len(recovery_blocks)
            self.statusChanged.emit(f"开始重译失败块: {total_sources} 条")
            translator = JaZhTranslator(
                api_key=cfg.get("api_key") or "",
                provider=cfg.get("provider") or "deepseek",
                api_url=cfg.get("api_url") or None,
                model=cfg.get("model") or None,
                max_workers=max(1, min(int(cfg.get("max_workers") or 1), 2)),
                batch_size=1,
                max_batch_length=cfg.get("max_batch_length", 800),
                max_text_size_for_batch=cfg.get("max_text_size_for_batch", 200),
                api_timeout=cfg.get("api_timeout", 120),
                cancel_event=self._cancel_event,
                extract_glossary=False,
                enable_glossary=bool(cfg.get("enable_glossary", True)),
                enable_thinking=bool(cfg.get("enable_thinking", False)),
                enable_proofread=bool(cfg.get("enable_proofread", False)),
                proofread_genre=cfg.get("proofread_genre", "general"),
                proofread_tone=cfg.get("proofread_tone", "neutral"),
                proofread_model=cfg.get("proofread_model") or None,
                proofread_provider=cfg.get("proofread_provider") or None,
                proofread_api_key=cfg.get("proofread_api_key") or None,
                proofread_api_url=cfg.get("proofread_api_url") or None,
                allow_text_cache_reuse=True,
                prompt_extra_instruction=cfg.get("prompt_extra_instruction", ""),
                enable_prompt_examples=bool(cfg.get("enable_prompt_examples", True)),
                hymt2_generation_mode=cfg.get("hymt2_generation_mode", "stable"),
                hymt2_prompt_mode=cfg.get("hymt2_prompt_mode", "official"),
                hymt2_runtime_mode=cfg.get("hymt2_runtime_mode", "cpu"),
            )

            translations: Dict[str, str] = {}
            recovery_results: Dict[str, Dict[str, Any]] = {}
            failed = 0
            if sources:
                try:
                    batch_results = translator.translate_batch(sources, batch_size=1)
                    translations.update(
                        {
                            str(src): str(dst)
                            for src, dst in dict(batch_results or {}).items()
                            if str(src or "").strip() and str(dst or "").strip()
                        }
                    )
                except TranslationIncompleteError as exc:
                    translations.update(
                        {
                            str(src): str(dst)
                            for src, dst in dict(getattr(exc, "partial_results", {}) or {}).items()
                            if str(src or "").strip() and str(dst or "").strip()
                        }
                    )
                    failed = len(getattr(exc, "failed_texts", []) or []) + len(getattr(exc, "residue_texts", []) or [])
                    logger.warning("失败块重译部分完成: %s", exc)

            if recovery_blocks:
                fallback_provider = str(
                    cfg.get("recovery_fallback_provider") or cfg.get("proofread_provider") or ""
                ).strip()
                fallback_model = str(
                    cfg.get("recovery_fallback_model") or cfg.get("proofread_model") or ""
                ).strip()
                fallback_api_url = str(
                    cfg.get("recovery_fallback_api_url") or cfg.get("proofread_api_url") or ""
                ).strip()
                fallback_api_key = str(
                    cfg.get("recovery_fallback_api_key") or cfg.get("proofread_api_key") or ""
                ).strip()
                agent = RecoveryAgent(
                    provider=str(cfg.get("provider") or ""),
                    model=str(cfg.get("model") or ""),
                    fallback_provider=fallback_provider,
                    fallback_model=fallback_model,
                    enabled=True,
                )
                executor = RecoveryExecutor(max_attempts=int(cfg.get("recovery_max_attempts") or 2))
                fallback_translator = None
                workflow = None
                for source, block in recovery_blocks:
                    issue_payload = dict(block.get("recovery_issue") or {})
                    issue_payload.setdefault("original", source)
                    issue_payload.setdefault("provider", str(cfg.get("provider") or ""))
                    issue_payload.setdefault("model", str(cfg.get("model") or ""))
                    issue_payload.setdefault("attempts", int(block.get("recovery_attempts") or 0))
                    issue = RecoveryIssue.from_dict(issue_payload)
                    decision = agent.parse_response(dict(block.get("recovery_decision") or {}), issue)
                    if (
                        decision.action == RecoveryAction.USE_FALLBACK_PROVIDER.value
                        and fallback_translator is None
                        and fallback_provider
                        and fallback_model
                        and fallback_api_url
                        and (fallback_provider not in API_KEY_REQUIRED_PROVIDERS or fallback_api_key)
                    ):
                        fallback_translator = JaZhTranslator(
                            api_key=fallback_api_key or "sk-local",
                            provider=fallback_provider,
                            api_url=fallback_api_url,
                            model=fallback_model,
                            max_workers=1,
                            batch_size=1,
                            api_timeout=cfg.get("api_timeout", 120),
                            cancel_event=self._cancel_event,
                            extract_glossary=False,
                            enable_glossary=bool(cfg.get("enable_glossary", True)),
                            enable_thinking=False,
                            enable_proofread=False,
                            allow_text_cache_reuse=True,
                            prompt_extra_instruction=cfg.get("prompt_extra_instruction", ""),
                        )
                    if workflow is None:
                        workflow = RecoveryWorkflow(
                            agent=agent,
                            executor=executor,
                            translator=translator,
                            fallback_translator=fallback_translator,
                        )
                    execution = workflow.execute(issue, decision)
                    recovery_results[source] = execution.to_dict()
                    if execution.status == "success" and execution.translation:
                        translations[source] = execution.translation
                    else:
                        failed += 1

            safe_translations: Dict[str, str] = {}
            for src, dst in translations.items():
                if translator._is_incomplete_translation(src, dst):
                    continue
                safe_translations[src] = dst
                translator.save_manual_translation(src, dst, trusted=False)
            translations = safe_translations

            success = len(translations)
            failed = max(failed, total_sources - success)
            recovery_success = sum(1 for item in recovery_results.values() if item.get("status") == "success")
            recovery_summary = {
                "attempted": len(recovery_results),
                "success": recovery_success,
                "needs_review": sum(1 for item in recovery_results.values() if item.get("status") == "needs_review"),
                "failed": sum(1 for item in recovery_results.values() if item.get("status") not in {"success", "needs_review"}),
            }
            self.finished.emit(
                {
                    "ok": success > 0,
                    "message": f"失败块重译完成: 成功 {success}/{total_sources}，失败 {failed}，跳过 {skipped}，恢复执行成功 {recovery_success}",
                    "total": total_sources,
                    "success": success,
                    "failed": failed,
                    "skipped": skipped,
                    "translations": translations,
                    "recovery_results": recovery_results,
                    "recovery_summary": recovery_summary,
                }
            )
        except Exception as exc:
            logger.exception("失败块重译异常")
            self.failed.emit(str(exc))


class _GlossaryBooksExtractionWorker(QObject):
    finished = Signal("QVariantMap")
    failed = Signal(str)
    statusChanged = Signal(str)
    errorDetail = Signal(str)
    progressChanged = Signal(int, int)

    def __init__(self, config: Dict[str, Any], source_paths: Any, cancel_event):
        super().__init__()
        self._config = dict(config or {})
        if isinstance(source_paths, (str, bytes)):
            source_paths = [source_paths]
        self._source_paths = [str(item or "") for item in (source_paths or [])]
        self._cancel_event = cancel_event

    def run(self):
        try:
            from backend.pipeline import (
                PipelineContext,
                run_ingest_pipeline,
            )

            source_paths = []
            for item in self._source_paths:
                path = str(item or "").strip()
                if path and os.path.exists(path) and path.lower().endswith(".epub"):
                    source_paths.append(path)
            source_paths = list(dict.fromkeys(source_paths))
            if not source_paths:
                self.failed.emit("请选择需要提取术语的 EPUB 文件")
                return

            total_books = len(source_paths)
            profile_ids: List[str] = []
            profiles: List[Dict[str, Any]] = []
            book_results: List[Dict[str, Any]] = []
            failed_books: List[Dict[str, str]] = []
            text_count = 0
            char_count = 0
            term_count = 0
            moderation_skipped = 0
            self.progressChanged.emit(0, total_books)

            for index, input_path in enumerate(source_paths):
                if self._cancel_event.is_set():
                    self.failed.emit("批量术语提取已取消")
                    return

                source_book = Path(input_path).stem.strip() or f"book-{index + 1}"
                cfg = dict(self._config)
                cfg["inp"] = input_path
                cfg["book_glossary_name"] = source_book
                self.statusChanged.emit(f"正在提取术语 {index + 1}/{total_books}: {source_book}")

                try:
                    ctx = PipelineContext(
                        config=cfg,
                        cancel_event=self._cancel_event,
                        extra={"title": os.path.basename(input_path)},
                    )
                    ctx = run_ingest_pipeline(ctx)

                    result = _preextract_glossary_profiles(
                        cfg,
                        ctx.proofread_style,
                        ctx.texts,
                        self._cancel_event,
                        status_callback=lambda msg, book=source_book: self.statusChanged.emit(f"{book}: {msg}"),
                        force=True,
                        target_scopes=[("book", source_book)],
                    )
                    result = dict(result or {})
                    result["source_path"] = input_path
                    result["book_name"] = source_book
                    book_results.append(result)
                    profile_ids.extend(str(item) for item in (result.get("profile_ids") or []) if str(item or "").strip())
                    profiles.extend([item for item in (result.get("profiles") or []) if isinstance(item, dict)])
                    text_count += int(result.get("text_count") or 0)
                    char_count += int(result.get("char_count") or 0)
                    term_count += int(result.get("term_count") or 0)
                    moderation_skipped += int(result.get("moderation_skipped") or 0)
                except Exception as exc:
                    logger.exception("批量提取术语失败: %s", input_path)
                    failed_books.append({"path": input_path, "book_name": source_book, "error": str(exc)})

                self.progressChanged.emit(index + 1, total_books)

            profile_ids = list(dict.fromkeys(profile_ids))
            if not profile_ids and failed_books:
                self.failed.emit(f"批量术语提取失败: {failed_books[0].get('book_name')}: {failed_books[0].get('error')}")
                return

            ok_books = len(book_results)
            message = (
                f"批量术语提取完成: 成功 {ok_books}/{total_books} 本，"
                f"生成 {len(profile_ids)} 个 profile，术语 {term_count} 条"
            )
            if failed_books:
                message += f"，失败 {len(failed_books)} 本"
            if moderation_skipped:
                message += f"，内容审核跳过 {moderation_skipped} 条"
            self.finished.emit(
                {
                    "ok": bool(book_results),
                    "message": message if profile_ids else (
                        f"批量术语提取完成，内容审核跳过 {moderation_skipped} 条，没有生成可保存的术语候选"
                        if moderation_skipped
                        else "批量术语提取完成，但没有生成可保存的术语候选"
                    ),
                    "profile_ids": profile_ids,
                    "profiles": profiles,
                    "books": book_results,
                    "failed_books": failed_books,
                    "book_count": total_books,
                    "success_count": ok_books,
                    "failed_count": len(failed_books),
                    "text_count": text_count,
                    "char_count": char_count,
                    "term_count": term_count,
                    "moderation_skipped": moderation_skipped,
                }
            )
        except Exception as exc:
            logger.exception("批量本书术语提取异常")
            self.errorDetail.emit(traceback.format_exc())
            self.failed.emit(str(exc))


class _GlossaryPostApplyWorker(QObject):
    finished = Signal("QVariantMap")
    failed = Signal(str)
    statusChanged = Signal(str)
    progressChanged = Signal(int, int)
    errorDetail = Signal(str)

    def __init__(self, config: Dict[str, Any], source_paths: Any, cancel_event):
        super().__init__()
        self._config = dict(config or {})
        if isinstance(source_paths, (str, bytes)):
            source_paths = [source_paths]
        self._source_paths = [str(item or "") for item in (source_paths or [])]
        self._cancel_event = cancel_event

    def run(self):
        try:
            from backend.glossary_post_apply import apply_glossary_to_epub, resolve_effective_glossary

            if self._cancel_event.is_set():
                self.failed.emit("术语后处理已取消")
                return

            source_paths = []
            for item in self._source_paths:
                path = str(item or "").strip()
                if path and os.path.exists(path):
                    source_paths.append(path)
            source_paths = list(dict.fromkeys(source_paths))
            if not source_paths:
                self.failed.emit("请选择已经存在的已翻译 EPUB 文件")
                return

            self.statusChanged.emit("正在解析当前术语范围...")
            self.progressChanged.emit(0, 1)
            glossary, meta = resolve_effective_glossary(self._config)
            logger.info(
                "术语统一范围: source=%s, profile_count=%s, profile_ids=%s",
                meta.get("source", "-"),
                meta.get("profile_count", 0),
                ",".join(meta.get("profile_ids", []) or []) or "-",
            )
            if self._cancel_event.is_set():
                self.failed.emit("术语后处理已取消")
                return

            succeeded = []
            failed = []
            total_files = max(1, len(source_paths))
            progress_units = total_files * 1000
            for file_index, source_path in enumerate(source_paths):
                if self._cancel_event.is_set():
                    self.failed.emit("术语后处理已取消")
                    return
                self.statusChanged.emit(f"正在统一术语: {Path(source_path).name} ({file_index + 1}/{total_files})")

                def _file_progress(done, total, base=file_index):
                    total = max(1, int(total or 1))
                    done = max(0, min(int(done or 0), total))
                    completed_units = base * 1000 + int(done * 1000 / total)
                    self.progressChanged.emit(completed_units, progress_units)

                try:
                    result = apply_glossary_to_epub(
                        source_path,
                        glossary,
                        progress_callback=_file_progress,
                    )
                    result = dict(result or {})
                    if result.get("ok"):
                        succeeded.append(result)
                        logger.info(
                            "术语统一单本完成: input=%s, output=%s, 替换 %s 处, 变更文档 %s 个, report=%s",
                            result.get("input_path", source_path),
                            result.get("output_path", ""),
                            int(result.get("replacement_total") or 0),
                            int(result.get("changed_documents") or 0),
                            result.get("report_path", ""),
                        )
                    else:
                        logger.info(
                            "术语统一单本未替换: input=%s, reason=%s",
                            source_path,
                            str(result.get("message") or "没有执行替换"),
                        )
                        failed.append(
                            {
                                "input_path": source_path,
                                "message": str(result.get("message") or "没有执行替换"),
                            }
                        )
                except Exception as exc:
                    logger.exception("术语后处理失败: %s", source_path)
                    failed.append({"input_path": source_path, "message": str(exc)})
                self.progressChanged.emit((file_index + 1) * 1000, progress_units)

            payload = {
                "ok": bool(succeeded),
                "glossary_meta": meta,
                "succeeded": len(succeeded),
                "failed": len(failed),
                "results": succeeded,
                "failed_items": failed,
                "output_paths": [item.get("output_path", "") for item in succeeded if item.get("output_path")],
                "input_count": len(source_paths),
                "replacement_total": sum(int(item.get("replacement_total") or 0) for item in succeeded),
            }
            if len(source_paths) == 1 and succeeded:
                payload.update(succeeded[0])
            elif succeeded:
                payload["message"] = f"术语统一完成: 成功 {len(succeeded)}/{len(source_paths)} 本，失败 {len(failed)} 本"
            else:
                first_error = failed[0]["message"] if failed else "没有生成输出 EPUB"
                payload["message"] = f"术语统一失败: {first_error}"
            logger.info(
                "术语统一批处理完成: 成功 %s/%s 本, 失败 %s 本, 总替换 %s 处",
                len(succeeded),
                len(source_paths),
                len(failed),
                int(payload.get("replacement_total") or 0),
            )
            self.progressChanged.emit(1, 1)
            self.finished.emit(payload)
        except Exception as exc:
            logger.exception("术语后处理异常")
            self.errorDetail.emit(traceback.format_exc())
            self.failed.emit(str(exc))


class TranslateBridge(QObject):
    TASK_SUCCESS_FLUSH_SIZE = 100
    TASK_SUCCESS_FLUSH_INTERVAL = 10.0


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
    translationTaskHistoryChanged = Signal()
    failedBlocksRetranslated = Signal("QVariantMap")
    glossaryBookExtractionFinished = Signal("QVariantMap")
    glossaryBookExtractionFailed = Signal(str)
    glossaryBookExtractionProgressChanged = Signal(int, int)
    glossaryPostApplyFinished = Signal("QVariantMap")
    glossaryPostApplyFailed = Signal(str)

    _progressValueChanged = Signal()
    _glossaryProgressValueChanged = Signal()
    _busyChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progress_value = 0.0
        self._glossary_progress_value = 0.0
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
        self._task_history = TranslationTaskHistoryStore()
        self._current_task_id = ""
        self._resume_task_id = ""
        self._last_task_history_update_ts = 0.0
        self._task_progress_snapshot = {}
        self._task_success_lock = threading.RLock()
        self._pending_task_successes: List[Tuple[str, str]] = []
        self._last_task_success_flush_ts = 0.0

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

    @staticmethod
    def _repair_provider_endpoint_config(config, reason: str = ""):
        provider = str((config or {}).get("provider") or "").strip().lower()
        if not provider or provider == "custom":
            return config
        saved_url = str(config.get("api_url") or "").strip()
        saved_model = str(config.get("model") or "").strip()
        known_provider_hints = {
            "deepseek": ("deepseek",),
            "doubao": ("volces", "ark.cn", "doubao"),
            "sakura": ("sakura",),
            "hymt2": ("hymt2", "hy-mt2"),
            "gemini": ("gemini", "generativelanguage"),
            "glm": ("glm", "bigmodel", "zhipu"),
            "wenxin": ("wenxin", "qianfan", "baidu", "ernie"),
            "longcat": ("longcat",),
        }
        endpoint_hint = f"{saved_url} {saved_model}".lower()
        mismatched_known_provider = any(
            other != provider and any(marker in endpoint_hint for marker in markers)
            for other, markers in known_provider_hints.items()
        )
        if not mismatched_known_provider:
            return config
        repaired = dict(config)
        repaired["api_url"] = provider_default_url(provider)
        repaired["model"] = provider_default_model(provider)
        logger.warning(
            "修正 provider/API 混合配置%s: provider=%s, old_url=%s, old_model=%s, new_url=%s, new_model=%s",
            f" ({reason})" if reason else "",
            provider,
            saved_url,
            saved_model,
            repaired.get("api_url", ""),
            repaired.get("model", ""),
        )
        return repaired

    def _update_translation_task_history(self, changes):
        task_id = self._current_task_id
        if not task_id:
            return {}
        try:
            payload = dict(self._task_progress_snapshot)
            payload.update(dict(changes or {}))
            record = self._task_history.upsert(task_id, payload)
            self.translationTaskHistoryChanged.emit()
            return record
        except Exception as exc:
            logger.warning("保存翻译任务历史失败: %s", exc)
            return {}

    def _record_translation_task_started(self, config):
        self._current_task_id = self._resume_task_id or make_task_id()
        self._resume_task_id = ""
        self._last_task_history_update_ts = 0.0
        self._task_progress_snapshot = {}
        with self._task_success_lock:
            self._pending_task_successes = []
            self._last_task_success_flush_ts = time.time()
        payload = {
            "status": "running",
            "started_at": int(time.time()),
            "input_path": config.get("inp", ""),
            "output_path": config.get("out", ""),
            "provider": config.get("provider", ""),
            "model": config.get("model", ""),
            "max_workers": int(config.get("max_workers") or 0),
            "batch_size": int(config.get("batch_size") or 0),
            "config": sanitize_config(config),
        }
        self._update_translation_task_history(payload)

    def _record_translation_task_text_plan(self, texts):
        if not self._current_task_id:
            return
        try:
            self._task_history.initialize_subtasks(self._current_task_id, list(texts or []), preserve_existing=True)
            self.translationTaskHistoryChanged.emit()
        except Exception as exc:
            logger.warning("保存翻译文本块任务记录失败: %s", exc)

    def _record_translation_task_preextract(self, preextract_result):
        if not self._current_task_id:
            return
        payload = dict(preextract_result or {})
        if not payload:
            return
        try:
            self._update_translation_task_history(
                {
                    "glossary_preextract": {
                        "ok": bool(payload.get("ok", True)),
                        "message": str(payload.get("message") or ""),
                        "profile_ids": list(payload.get("profile_ids") or []),
                        "text_count": int(payload.get("text_count") or 0),
                        "char_count": int(payload.get("char_count") or 0),
                        "term_count": int(payload.get("term_count") or 0),
                    }
                }
            )
        except Exception as exc:
            logger.debug("保存术语提取记录失败: %s", exc, exc_info=True)

    def _record_translation_item_success(self, src, dst):
        if not self._current_task_id:
            return
        now = time.time()
        with self._task_success_lock:
            self._pending_task_successes.append((str(src or ""), str(dst or "")))
            should_flush = (
                len(self._pending_task_successes) >= self.TASK_SUCCESS_FLUSH_SIZE
                or now - self._last_task_success_flush_ts >= self.TASK_SUCCESS_FLUSH_INTERVAL
            )
        if should_flush:
            self._flush_translation_item_successes()

    def _flush_translation_item_successes(self, force: bool = False):
        if not self._current_task_id:
            return
        with self._task_success_lock:
            if not self._pending_task_successes:
                if force:
                    self._last_task_success_flush_ts = time.time()
                return
            pending = list(self._pending_task_successes)
            self._pending_task_successes = []
            self._last_task_success_flush_ts = time.time()

        translations = {}
        for src, dst in pending:
            if src.strip() and dst.strip():
                translations[src] = dst
        if not translations:
            return
        try:
            self._task_history.mark_subtasks_success(self._current_task_id, translations)
            self.translationTaskHistoryChanged.emit()
        except Exception as exc:
            with self._task_success_lock:
                self._pending_task_successes = pending + self._pending_task_successes
            if force:
                logger.warning("保存文本块成功状态失败: %s", exc)
            else:
                logger.debug("保存文本块成功状态失败: %s", exc, exc_info=True)

    def _record_translation_task_progress(self, completed, total, total_chars):
        if not self._current_task_id:
            return
        progress = float(completed) / float(total) if total > 0 else 0.0
        self._task_progress_snapshot = {
            "completed_texts": int(completed),
            "total_texts": int(total),
            "total_chars": int(total_chars),
            "progress": round(progress, 4),
        }

    def _record_translation_task_failures(self, exc):
        if not self._current_task_id:
            return
        self._flush_translation_item_successes(force=True)
        failed_texts = list(getattr(exc, "failed_texts", []) or [])
        residue_texts = list(getattr(exc, "residue_texts", []) or [])
        blocks = normalize_failed_blocks(
            failed_details=list(getattr(exc, "failed_details", []) or []),
            residue_details=list(getattr(exc, "residue_details", []) or []),
        )
        self._update_translation_task_history(
            {
                "failure_summary": {
                    "failed_count": len(failed_texts),
                    "residue_count": len(residue_texts),
                    "block_count": len(blocks),
                },
                "failed_blocks": blocks,
            }
        )
        try:
            self._task_history.mark_subtasks_problem(self._current_task_id, blocks)
        except Exception as mark_exc:
            logger.debug("标记失败文本块状态失败: %s", mark_exc, exc_info=True)
        if residue_texts:
            try:
                from backend import request_log

                request_log.record_event(
                    context="translation residue diagnostic",
                    outcome="residue",
                    category="residue",
                    source_text=list(getattr(exc, "residue_details", []) or residue_texts)[:12],
                    error=str(exc),
                )
            except Exception:
                pass

    def _record_translation_task_save_residue(self, residue_samples, residue_total, report_path):
        if not self._current_task_id:
            return
        self._flush_translation_item_successes(force=True)
        blocks = normalize_failed_blocks(residue_samples=list(residue_samples or []))
        self._update_translation_task_history(
            {
                "failure_summary": {
                    "failed_count": 0,
                    "residue_count": int(residue_total or 0),
                    "block_count": len(blocks),
                    "report_path": str(report_path or ""),
                },
                "failed_blocks": blocks,
            }
        )
        try:
            self._task_history.mark_subtasks_problem(self._current_task_id, blocks)
        except Exception as mark_exc:
            logger.debug("标记保存前残留文本块状态失败: %s", mark_exc, exc_info=True)
        try:
            from backend import request_log

            request_log.record_event(
                context="pre-save residue diagnostic",
                outcome="residue",
                category="residue",
                source_text=list(residue_samples or [])[:12],
                error=f"pre-save residue count={residue_total}; report={report_path or ''}",
            )
        except Exception:
            pass

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

    @Property(float, notify=_glossaryProgressValueChanged)
    def glossaryProgressValue(self) -> float:
        return self._glossary_progress_value

    @glossaryProgressValue.setter
    def glossaryProgressValue(self, val: float):
        val = max(0.0, min(1.0, float(val or 0.0)))
        if abs(val - self._glossary_progress_value) > 0.001:
            self._glossary_progress_value = val
            self._glossaryProgressValueChanged.emit()

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
            "extract_glossary": False, "enable_glossary": cfg.enableGlossary,
            "enable_layered_glossary": getattr(cfg, "enableLayeredGlossary", False),
            "use_global_glossary": getattr(cfg, "useGlobalGlossary", True),
            "use_genre_glossary": getattr(cfg, "useGenreGlossary", False),
            "use_series_glossary": getattr(cfg, "useSeriesGlossary", False),
            "use_book_glossary": getattr(cfg, "useBookGlossary", False),
            "pre_extract_glossary": False,
            "series_glossary_name": getattr(cfg, "seriesGlossaryName", ""),
            "book_glossary_name": getattr(cfg, "bookGlossaryName", ""),
            "glossary_profile_ids": list(getattr(cfg, "selectedGlossaryProfileIds", []) or []),
            "glossary_extraction_mode": getattr(cfg, "glossaryExtractionMode", "novel"),
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
            "japanese_residue_policy": getattr(cfg, "japaneseResiduePolicy", "balanced"),
            "enable_recovery_agent": getattr(cfg, "enableRecoveryAgent", False),
            "recovery_min_confidence": getattr(cfg, "recoveryMinConfidence", 0.85),
            "recovery_max_attempts": getattr(cfg, "recoveryMaxAttempts", 2),
            "recovery_fallback_provider": getattr(cfg, "recoveryFallbackProvider", ""),
            "recovery_fallback_api_key": getattr(cfg, "recoveryFallbackApiKey", ""),
            "recovery_fallback_api_url": getattr(cfg, "recoveryFallbackApiUrl", ""),
            "recovery_fallback_model": getattr(cfg, "recoveryFallbackModel", ""),
        }

    @Slot("QVariant")
    def startTranslation(self, cfg):
        config = self._repair_provider_endpoint_config(self._make_config(cfg), reason="start")
        if not config["inp"] or not os.path.exists(config["inp"]):
            self._resume_task_id = ""
            self.failed.emit("请选择有效的输入 EPUB")
            ToastBridge.warning("请先选择要翻译的 EPUB 文件")
            return
        if not config["out"]:
            self._resume_task_id = ""
            self.failed.emit("请填写输出文件路径")
            ToastBridge.warning("请填写输出文件保存路径")
            return
        if config["provider"] in API_KEY_REQUIRED_PROVIDERS and not config["api_key"]:
            self._resume_task_id = ""
            self.failed.emit("该提供方需要 API Key")
            ToastBridge.warning("请先在 API 页面配置 API Key")
            return
        if not config["api_url"] or not config["model"]:
            self._resume_task_id = ""
            self.failed.emit("请填写 Base URL 和模型")
            ToastBridge.warning("请填写 API 地址和模型名称")
            return
        proofread_provider = config.get("proofread_provider") or ""
        if config.get("enable_proofread") and proofread_provider and proofread_provider != config["provider"]:
            if proofread_provider in API_KEY_REQUIRED_PROVIDERS and not config.get("proofread_api_key"):
                self._resume_task_id = ""
                self.failed.emit("校对供应商需要单独填写 API Key")
                ToastBridge.warning("请填写校对模型 API Key")
                return
            if not config.get("proofread_api_url") or not config.get("proofread_model"):
                self._resume_task_id = ""
                self.failed.emit("请填写校对模型 Base URL 和模型名")
                ToastBridge.warning("请填写校对模型地址和模型名称")
                return

        self._last_cfg = config
        logger.info(
            "启动翻译配置: provider=%s, model=%s, api_url=%s, workers=%s, batch=%s, timeout=%s, resume_task_id=%s",
            config.get("provider", ""),
            config.get("model", ""),
            config.get("api_url", ""),
            config.get("max_workers", ""),
            config.get("batch_size", ""),
            config.get("api_timeout", ""),
            self._resume_task_id or "",
        )
        self._record_translation_task_started(config)
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

    @Slot("QVariant", "QVariant")
    def extractGlossaryFromBooks(self, cfg, paths):
        if self.busy:
            self.failed.emit("当前有任务运行中，不能批量提取术语")
            ToastBridge.warning("请等待当前任务完成后再批量提取术语")
            return
        config = self._make_config(cfg)
        source_paths = self._normalize_epub_paths(paths)
        if not source_paths:
            self.failed.emit("请选择需要提取术语的 EPUB 文件")
            ToastBridge.warning("请先选择待抽取术语的 EPUB 文件")
            return
        if config["provider"] in API_KEY_REQUIRED_PROVIDERS and not config["api_key"]:
            self.failed.emit("术语提取 provider 需要 API Key")
            ToastBridge.warning("请先在 API 页面配置 API Key")
            return
        if not config["api_url"] or not config["model"]:
            self.failed.emit("术语提取缺少 Base URL 或模型名")
            ToastBridge.warning("请填写 API 地址和模型名称")
            return

        self._cancel_event.clear()
        self.busy = True
        self.glossaryProgressValue = 0.0
        self.statusChanged.emit(f"正在批量提取术语: {len(source_paths)} 本 EPUB")
        ToastBridge.info("正在批量提取术语")
        worker = _GlossaryBooksExtractionWorker(config, source_paths, self._cancel_event)
        self._start_worker(
            worker,
            [
                (worker.statusChanged, self.statusChanged),
                (worker.progressChanged, self._on_glossary_progress),
                (worker.errorDetail, self.errorDetail),
                (worker.finished, self._on_book_glossary_extracted),
                (worker.failed, self._on_book_glossary_extract_failed),
            ],
            [worker.finished, worker.failed],
        )

    def _on_glossary_progress(self, completed, total):
        total = max(1, int(total or 1))
        completed = max(0, min(int(completed or 0), total))
        self.glossaryBookExtractionProgressChanged.emit(completed, total)
        self.glossaryProgressValue = float(completed) / float(total)

    def _on_book_glossary_extracted(self, result):
        self.busy = False
        self.glossaryProgressValue = 1.0
        payload = dict(result or {})
        message = str(payload.get("message") or "本书术语提取完成")
        self.glossaryBookExtractionFinished.emit(payload)
        self.statusChanged.emit(message)
        if payload.get("ok") and int(payload.get("failed_count") or 0) <= 0:
            ToastBridge.success(message)
        else:
            ToastBridge.warning(message)

    def _on_book_glossary_extract_failed(self, error):
        self.busy = False
        self.glossaryProgressValue = 0.0
        text = str(error or "本书术语提取失败")
        self.statusChanged.emit(text)
        self.glossaryBookExtractionFailed.emit(text)
        self.failed.emit(text)
        ToastBridge.error("本书术语提取失败")

    @Slot("QVariant")
    def applyGlossaryToTranslatedBook(self, cfg):
        config = self._make_config(cfg)
        self._start_glossary_post_apply(config, [str(config.get("out") or "").strip()])

    @Slot("QVariant", "QVariant")
    def applyGlossaryToTranslatedBooks(self, cfg, paths):
        config = self._make_config(cfg)
        self._start_glossary_post_apply(config, self._normalize_epub_paths(paths))

    def _normalize_epub_paths(self, paths):
        if hasattr(paths, "toVariant"):
            try:
                paths = paths.toVariant()
            except Exception:
                paths = []
        if isinstance(paths, (str, bytes)):
            paths = [paths]
        if paths is None:
            paths = []
        result = []
        for item in paths:
            path = str(item or "").strip()
            if path.lower().startswith("file:///"):
                path = path[8:]
            elif path.lower().startswith("file://"):
                path = path[7:]
            path = path.replace("/", os.sep)
            if path and path.lower().endswith(".epub") and os.path.exists(path):
                result.append(path)
        return list(dict.fromkeys(result))

    def _start_glossary_post_apply(self, config, source_paths):
        if self.busy:
            self.failed.emit("当前有任务运行中，不能执行术语后处理")
            ToastBridge.warning("请等待当前任务完成后再应用术语")
            return
        if not config.get("enable_glossary", True):
            self.failed.emit("术语表未启用，不能应用术语")
            ToastBridge.warning("请先启用术语表")
            return
        source_paths = self._normalize_epub_paths(source_paths)
        if not source_paths:
            self.failed.emit("请选择已经存在的翻译后 EPUB 输出文件")
            ToastBridge.warning("请先确认输出 EPUB 已存在，再应用术语")
            return

        self._cancel_event.clear()
        self.busy = True
        self.glossaryProgressValue = 0.0
        self.statusChanged.emit("正在执行术语后处理...")
        ToastBridge.info("正在应用术语到已翻译 EPUB")
        worker = _GlossaryPostApplyWorker(config, source_paths, self._cancel_event)
        self._start_worker(
            worker,
            [
                (worker.statusChanged, self.statusChanged),
                (worker.progressChanged, self._on_glossary_progress),
                (worker.errorDetail, self.errorDetail),
                (worker.finished, self._on_glossary_post_apply_finished),
                (worker.failed, self._on_glossary_post_apply_failed),
            ],
            [worker.finished, worker.failed],
        )

    def _on_glossary_post_apply_finished(self, result):
        self.busy = False
        self.glossaryProgressValue = 1.0
        payload = dict(result or {})
        message = str(payload.get("message") or "术语后处理完成")
        self.glossaryPostApplyFinished.emit(payload)
        self.statusChanged.emit(message)
        if payload.get("ok"):
            ToastBridge.success(message)
        else:
            ToastBridge.warning(message)

    def _on_glossary_post_apply_failed(self, error):
        self.busy = False
        self.glossaryProgressValue = 0.0
        text = str(error or "术语后处理失败")
        self.statusChanged.emit(text)
        self.glossaryPostApplyFailed.emit(text)
        self.failed.emit(text)
        ToastBridge.error("术语后处理失败")

    def _on_progress(self, completed, total, total_chars):
        self.progressChanged.emit(completed, total, total_chars)
        self.progressValue = float(completed) / float(total) if total > 0 else 0.0
        self._record_translation_task_progress(completed, total, total_chars)

    def _on_finished(self, out_path):
        was_stopped = self._stop_requested
        self._flush_translation_item_successes(force=True)
        if was_stopped:
            self._discard_and_clear_active_cache()
        self._active_translator = None
        self._active_texts = []
        self.busy = False
        if out_path == CANCELLED_RESULT:
            if was_stopped:
                self.progressValue = 0.0
                self._update_translation_task_history(
                    {
                        "status": "stopped",
                        "finished_at": int(time.time()),
                        "output_path": "",
                    }
                )
                self.runtimeCleared.emit()
                self.finished.emit(STOPPED_RESULT)
                ToastBridge.info("翻译已停止")
            else:
                self._update_translation_task_history(
                    {
                        "status": "cancelled",
                        "finished_at": int(time.time()),
                        "output_path": "",
                    }
                )
                self.finished.emit(CANCELLED_RESULT)
                ToastBridge.warning("翻译已取消")
        else:
            self.progressValue = 1.0
            self._update_translation_task_history(
                {
                    "status": "completed",
                    "finished_at": int(time.time()),
                    "output_path": out_path,
                }
            )
            self.finished.emit(out_path)
            self.playCompletionVoice()
            ToastBridge.success(f"翻译完成！已保存到: {os.path.basename(out_path)}")
        self._current_task_id = ""
        self._stop_requested = False

    def _on_failed(self, msg):
        self._flush_translation_item_successes(force=True)
        self._active_translator = None
        self._active_texts = []
        self.busy = False
        text = str(msg or "")
        status = "paused" if text.startswith("翻译未完成") else "failed"
        self._update_translation_task_history(
            {
                "status": status,
                "finished_at": int(time.time()),
                "error_message": text[:2000],
            }
        )
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
        self._flush_translation_item_successes(force=True)
        self._update_translation_task_history({"status": "cancelling"})
        self._request_active_cancel(close_session=True)
        self.statusChanged.emit("正在取消...")
        ToastBridge.info("正在取消翻译...")

    @Slot()
    def stopTranslation(self):
        self._is_paused = False
        self._stop_requested = True
        self._flush_translation_item_successes(force=True)
        self._update_translation_task_history({"status": "stopping"})
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
        self._flush_translation_item_successes(force=True)
        self._update_translation_task_history({"status": "pausing"})
        self._request_active_cancel(close_session=True)
        self.statusChanged.emit("暂停中 — 等待当前请求完成...")
        ToastBridge.info("翻译已暂停，可切换模型后继续")

    @Slot(int, result="QVariantList")
    def getTranslationTaskHistory(self, limit: int = 20):
        try:
            return self._task_history.list_recent(limit)
        except Exception as exc:
            logger.warning("读取翻译任务历史失败: %s", exc)
            return []

    @Slot(result="QVariantMap")
    def getLatestTranslationTask(self):
        try:
            return self._task_history.latest()
        except Exception as exc:
            logger.warning("读取最近翻译任务失败: %s", exc)
            return {}

    @Slot(result="QVariantMap")
    def getLatestUnfinishedTranslationTask(self):
        try:
            return self._task_history.latest_unfinished()
        except Exception as exc:
            logger.warning("读取最近未完成翻译任务失败: %s", exc)
            return {}

    @Slot(str, "QVariant", result="QVariantMap")
    def loadTranslationTaskConfig(self, task_id: str, cfg):
        task_id = str(task_id or "").strip()
        if not task_id:
            return {"ok": False, "message": "缺少任务 ID"}
        try:
            for record in self._task_history.load():
                if str(record.get("task_id") or "") != task_id:
                    continue
                self._apply_task_record_to_config(cfg, record)
                return {
                    "ok": True,
                    "message": "已载入任务配置",
                    "provider": str(record.get("provider") or ""),
                    "model": str(record.get("model") or ""),
                }
            return {"ok": False, "message": "未找到任务记录"}
        except Exception as exc:
            logger.warning("载入任务配置失败: %s", exc)
            return {"ok": False, "message": str(exc)}

    @Slot(int, result="QVariantList")
    def getLatestFailedTranslationBlocks(self, limit: int = 20):
        try:
            record = self._task_history.latest()
            blocks = record.get("failed_blocks", []) if isinstance(record, dict) else []
            if not isinstance(blocks, list):
                return []
            limit = max(1, int(limit or 20))
            return [dict(item) for item in blocks[:limit] if isinstance(item, dict)]
        except Exception as exc:
            logger.warning("读取最近失败文本块失败: %s", exc)
            return []

    @Slot("QVariant", int, result="QVariantMap")
    def analyzeLatestFailedBlocks(self, cfg=None, limit: int = 20):
        """Classify failed blocks and persist a user-confirmation suggestion."""
        try:
            from backend.recovery_classifier import classify_recovery_issue
            from translation_models import RecoveryAction
            record = self._task_history.latest()
            task_id = str(record.get("task_id") or "") if isinstance(record, dict) else ""
            blocks = record.get("failed_blocks", []) if isinstance(record, dict) else []
            blocks = blocks if isinstance(blocks, list) else []
            limit = max(1, min(int(limit or 20), 200))
            selected = []
            for original in blocks:
                if not isinstance(original, dict):
                    continue
                block = dict(original)
                issue = classify_recovery_issue(
                    original=block.get("text") or "",
                    translation=block.get("translation") or "",
                    reason=block.get("reason") or "",
                    fragments=block.get("fragments") or [],
                    provider=(record or {}).get("provider", "") if isinstance(record, dict) else "",
                    model=(record or {}).get("model", "") if isinstance(record, dict) else "",
                    attempts=int(block.get("recovery_attempts") or 0),
                )
                issue_value = issue.issue_type
                if issue_value in {"CONTENT_MODERATION", "JAPANESE_RESIDUE_HIGH"}:
                    action, reason = RecoveryAction.REQUIRE_USER_REVIEW.value, "高风险内容需要人工确认"
                elif issue_value == "JAPANESE_RESIDUE_LOW":
                    action, reason = RecoveryAction.ALLOW_LOW_RISK.value, "低风险残留，可由用户确认放行"
                elif issue_value == "JAPANESE_RESIDUE_MEDIUM":
                    action, reason = RecoveryAction.RETRANSLATE.value, "建议单块重译后再次质检"
                elif issue_value in {"TIMEOUT", "EMPTY_RESPONSE", "JSON_PARSE_ERROR", "PROVIDER_ERROR"}:
                    action, reason = RecoveryAction.RETRANSLATE.value, "建议降低负载后单块重译"
                else:
                    action, reason = RecoveryAction.REQUIRE_USER_REVIEW.value, "建议人工检查后决定处理方式"
                block["recovery_issue"] = issue.to_dict()
                block["recovery_decision"] = {"action": action, "reason": reason, "confidence": 1.0,
                                               "provider": issue.provider, "model": issue.model,
                                               "prompt_preset": "failed_block_repair"}
                block["recovery_recommendation"] = reason
                selected.append(block)
                if len(selected) >= limit:
                    break
            if task_id and selected:
                selected_by_text = {str(item.get("text") or ""): item for item in selected}
                updated_blocks = [selected_by_text.get(str(item.get("text") or ""), dict(item))
                                  if isinstance(item, dict) else item for item in blocks]
                self._task_history.upsert(task_id, {"failed_blocks": updated_blocks})
                self.translationTaskHistoryChanged.emit()
            enabled = bool(getattr(cfg, "enableRecoveryAgent", False)) if cfg is not None else False
            return {"ok": True, "task_id": task_id, "enabled": enabled, "total": len(selected),
                    "items": selected,
                    "message": "已生成恢复建议，请确认后执行" if selected else "当前没有可分析的失败块"}
        except Exception as exc:
            logger.warning("分析失败块恢复建议失败: %s", exc, exc_info=True)
            return {"ok": False, "total": 0, "items": [], "message": str(exc)}

    def _latest_failed_blocks_for_retranslate(self, limit: int = 50):
        record = self._task_history.latest()
        task_id = str(record.get("task_id", "") if isinstance(record, dict) else "")
        blocks = record.get("failed_blocks", []) if isinstance(record, dict) else []
        if not task_id or not isinstance(blocks, list):
            return task_id, []
        limit = max(1, min(int(limit or 50), 200))
        actionable = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if str(block.get("kind") or "") not in {"failed", "residue"}:
                continue
            if str(block.get("text") or "").strip():
                actionable.append(dict(block))
            if len(actionable) >= limit:
                break
        return task_id, actionable

    @staticmethod
    def _apply_retranslate_provider_mode(config, mode):
        mode = str(mode or "current").strip().lower()
        if mode != "proofread":
            return config, ""
        provider = str(config.get("proofread_provider") or "").strip()
        api_url = str(config.get("proofread_api_url") or "").strip()
        model = str(config.get("proofread_model") or "").strip()
        api_key = str(config.get("proofread_api_key") or "").strip()
        if not provider or not api_url or not model:
            return config, "校对模型未配置完整，不能作为失败块重译备用 provider"
        config = dict(config)
        config["provider"] = provider
        config["api_url"] = api_url
        config["model"] = model
        config["api_key"] = api_key or config.get("api_key", "")
        config["enable_proofread"] = False
        return config, ""

    @Slot("QVariant", str, int)
    def retranslateLatestFailedBlocks(self, cfg, provider_mode: str = "current", limit: int = 50):
        if self.busy:
            self.failed.emit("当前有任务运行中，不能重译失败块")
            ToastBridge.warning("请等待当前任务完成后再重译失败块")
            return
        task_id, blocks = self._latest_failed_blocks_for_retranslate(limit)
        if not task_id or not blocks:
            self.failed.emit("没有可自动重译的失败块")
            ToastBridge.warning("没有可自动重译的失败块")
            return
        config = self._make_config(cfg)
        config, provider_error = self._apply_retranslate_provider_mode(config, provider_mode)
        if provider_error:
            self.failed.emit(provider_error)
            ToastBridge.warning(provider_error)
            return
        if config["provider"] in API_KEY_REQUIRED_PROVIDERS and not config.get("api_key"):
            self.failed.emit("重译 provider 需要 API Key")
            ToastBridge.warning("请先配置重译 provider 的 API Key")
            return
        if not config.get("api_url") or not config.get("model"):
            self.failed.emit("重译 provider 缺少 Base URL 或模型名")
            ToastBridge.warning("请先配置重译 provider 的 Base URL 和模型名")
            return

        self._cancel_event.clear()
        self.busy = True
        self.statusChanged.emit(f"正在重译失败块: {len(blocks)} 条")
        ToastBridge.info("正在重译失败块")
        worker = _RetranslateFailedBlocksWorker(config, blocks, self._cancel_event)
        worker._task_id = task_id
        self._start_worker(
            worker,
            [
                (worker.statusChanged, self.statusChanged),
                (worker.finished, self._on_failed_blocks_retranslated),
                (worker.failed, self._on_failed_blocks_retranslate_failed),
            ],
            [worker.finished, worker.failed],
        )

    def _on_failed_blocks_retranslated(self, result):
        self.busy = False
        payload = dict(result or {})
        translations = dict(payload.get("translations") or {})
        try:
            record = self._task_history.latest()
            task_id = str(record.get("task_id", "") if isinstance(record, dict) else "")
            if task_id and translations:
                recovery_results = dict(payload.get("recovery_results") or {})
                if recovery_results:
                    self._task_history.record_recovery_results(task_id, recovery_results)
                update = self._task_history.mark_blocks_success(task_id, translations)
                remaining = int(update.get("remaining_blocks") or 0)
                status = "paused" if remaining else "partial"
                self._task_history.upsert(
                    task_id,
                    {
                        "status": status,
                        "failure_summary": {
                            **dict((update.get("record") or {}).get("failure_summary") or {}),
                            "block_count": remaining,
                        },
                        "recovery_summary": {
                            **dict(payload.get("recovery_summary") or {}),
                            "results": dict(payload.get("recovery_results") or {}),
                        },
                    },
                )
                self.translationTaskHistoryChanged.emit()
            elif task_id and payload.get("recovery_results"):
                recovery_results = dict(payload.get("recovery_results") or {})
                self._task_history.record_recovery_results(
                    task_id,
                    recovery_results,
                )
                self._task_history.upsert(
                    task_id,
                    {
                        "recovery_summary": {
                            **dict(payload.get("recovery_summary") or {}),
                            "results": recovery_results,
                        }
                    },
                )
                self.translationTaskHistoryChanged.emit()
        except Exception as exc:
            logger.warning("更新失败块重译任务历史失败: %s", exc)
        self.failedBlocksRetranslated.emit(payload)
        self.statusChanged.emit(str(payload.get("message") or "失败块重译完成"))
        if payload.get("ok"):
            ToastBridge.success(str(payload.get("message") or "失败块重译完成"))
        else:
            ToastBridge.warning(str(payload.get("message") or "失败块重译未成功"))

    def _on_failed_blocks_retranslate_failed(self, error):
        self.busy = False
        text = str(error or "失败块重译失败")
        self.statusChanged.emit(text)
        self.failed.emit(text)
        ToastBridge.error("失败块重译失败")

    @Slot(result="QVariantMap")
    def clearTranslationTaskHistory(self):
        try:
            removed = self._task_history.clear()
            self.translationTaskHistoryChanged.emit()
            return {"ok": True, "removed": removed, "message": f"已清空 {removed} 条任务历史"}
        except Exception as exc:
            logger.warning("清空翻译任务历史失败: %s", exc)
            return {"ok": False, "removed": 0, "message": str(exc)}

    @Slot("QVariant")
    def clearCurrentBookCache(self, cfg):
        if self.busy:
            self.failed.emit("翻译运行中，不能清理缓存")
            ToastBridge.warning("请先暂停或停止翻译，再清理缓存")
            return
        config = self._make_config(cfg)
        if not config["inp"] or not os.path.exists(config["inp"]):
            self._resume_task_id = ""
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
            try:
                record = self._task_history.latest()
                task_id = str(record.get("task_id", "") if isinstance(record, dict) else "")
                if task_id:
                    update = self._task_history.mark_blocks_success(task_id, {src: dst})
                    remaining = int(update.get("remaining_blocks") or 0)
                    self._task_history.upsert(
                        task_id,
                        {
                            "status": "paused" if remaining else "partial",
                            "failure_summary": {
                                **dict((update.get("record") or {}).get("failure_summary") or {}),
                                "block_count": remaining,
                            },
                        },
                    )
                    self.translationTaskHistoryChanged.emit()
            except Exception:
                logger.debug("人工译文同步任务失败块状态失败", exc_info=True)
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

    def _apply_task_record_to_config(self, cfg, record):
        if not cfg or not record:
            return
        config = record.get("config", {}) if isinstance(record, dict) else {}
        values = dict(config or {})
        values.setdefault("inp", record.get("input_path", ""))
        values.setdefault("out", record.get("output_path", ""))
        values.setdefault("provider", record.get("provider", ""))
        values.setdefault("model", record.get("model", ""))
        values = self._repair_provider_endpoint_config(values, reason="resume")
        provider = str(values.get("provider") or "").strip().lower()
        if provider:
            if hasattr(cfg, "setProvider"):
                try:
                    cfg.setProvider(provider)
                    logger.info(
                        "恢复任务 provider: task_id=%s, provider=%s, api_url=%s, model=%s",
                        record.get("task_id", ""),
                        provider,
                        values.get("api_url", ""),
                        values.get("model", ""),
                    )
                except Exception:
                    logger.debug("恢复任务 provider 失败: %s", provider, exc_info=True)
        mapping = {
            "inp": "inp",
            "out": "out",
            "api_url": "apiUrl",
            "model": "model",
            "max_workers": "maxWorkers",
            "batch_size": "batchSize",
            "max_batch_length": "maxBatchLength",
            "max_text_size_for_batch": "maxTextSizeForBatch",
            "api_timeout": "apiTimeout",
            "direction": "direction",
            "enable_thinking": "enableThinking",
            "enable_proofread": "enableProofread",
            "proofread_genre": "proofreadGenre",
            "proofread_tone": "proofreadTone",
            "proofread_provider": "proofreadProvider",
            "proofread_api_url": "proofreadApiUrl",
            "proofread_model": "proofreadModel",
            "allow_text_cache_reuse": "allowTextCacheReuse",
            "prompt_extra_instruction": "promptExtraInstruction",
            "enable_prompt_examples": "enablePromptExamples",
            "enable_layered_glossary": "enableLayeredGlossary",
            "use_global_glossary": "useGlobalGlossary",
            "use_genre_glossary": "useGenreGlossary",
            "use_series_glossary": "useSeriesGlossary",
            "use_book_glossary": "useBookGlossary",
            "series_glossary_name": "seriesGlossaryName",
            "book_glossary_name": "bookGlossaryName",
            "glossary_profile_ids": "selectedGlossaryProfileIds",
            "glossary_extraction_mode": "glossaryExtractionMode",
            "hymt2_generation_mode": "hymt2GenerationMode",
            "hymt2_prompt_mode": "hymt2PromptMode",
            "hymt2_runtime_mode": "hymt2RuntimeMode",
            "japanese_residue_policy": "japaneseResiduePolicy",
            "enable_recovery_agent": "enableRecoveryAgent",
            "recovery_min_confidence": "recoveryMinConfidence",
            "recovery_max_attempts": "recoveryMaxAttempts",
            "recovery_fallback_provider": "recoveryFallbackProvider",
            "recovery_fallback_api_url": "recoveryFallbackApiUrl",
            "recovery_fallback_model": "recoveryFallbackModel",
        }
        for source_key, attr in mapping.items():
            if source_key not in values:
                continue
            value = values.get(source_key)
            if value is None:
                continue
            try:
                setattr(cfg, attr, value)
            except Exception:
                logger.debug("恢复任务配置字段失败: %s -> %s", source_key, attr, exc_info=True)
        try:
            cfg.allowTextCacheReuse = True
            cfg.saveToDisk()
        except Exception:
            logger.debug("恢复任务时启用缓存复用失败", exc_info=True)

    @Slot("QVariant")
    def resumeLatestTranslation(self, cfg):
        if self.busy:
            self.failed.emit("翻译运行中，不能继续历史任务")
            return
        record = self.getLatestUnfinishedTranslationTask()
        task_id = str(record.get("task_id", "") if isinstance(record, dict) else "")
        if not task_id:
            self.failed.emit("没有可继续的未完成任务")
            ToastBridge.warning("没有可继续的未完成任务")
            return
        self._apply_task_record_to_config(cfg, record)
        self._resume_task_id = task_id
        self._is_paused = False
        self.statusChanged.emit("正在继续上次未完成任务...")
        ToastBridge.info("正在继续上次未完成任务")
        self.startTranslation(cfg)

    @Slot("QVariant")
    def resumeTranslation(self, cfg):
        if not self._is_paused:
            self.resumeLatestTranslation(cfg)
            return
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
