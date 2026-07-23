# -*- coding: utf-8 -*-
"""Pipeline primitives for the QML/V4 translation workflow.

The QML worker owns UI signals and user-facing error handling. This module owns
the pure workflow stages so the bridge does not grow into one large procedure.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _book_glossary_name(ctx: "PipelineContext") -> str:
    value = str(ctx.config.get("book_glossary_name") or "").strip()
    if value:
        return value
    title = str(ctx.extra.get("title") or "").strip()
    if title:
        return Path(title).stem if title.lower().endswith(".epub") else title
    source = str(ctx.config.get("inp") or "").strip()
    return Path(source).stem if source else ""


def _genre_glossary_name(ctx: "PipelineContext") -> str:
    style = ctx.proofread_style or ctx.detected_style
    if not style:
        return ""
    return str(getattr(style, "genre_label", "") or getattr(style, "genre", "") or "").strip()


def _resolve_glossary_profile_ids(ctx: "PipelineContext") -> Tuple[List[str], List[Dict[str, Any]]]:
    if not bool(ctx.config.get("enable_glossary", True)):
        return [], []
    configured_ids = ctx.extra.get("glossary_profile_ids") or ctx.config.get("glossary_profile_ids") or []
    if not bool(ctx.config.get("enable_layered_glossary", False)) and not configured_ids:
        return [], []

    from glossary_profiles import load_profile, resolve_profile_ids
    from translator import get_data_dir

    data_dir = get_data_dir()
    if isinstance(configured_ids, (list, tuple)) and configured_ids:
        profiles = []
        ids = []
        seen = set()
        for profile_id in configured_ids:
            profile_id = str(profile_id or "").strip()
            if not profile_id or profile_id in seen:
                continue
            seen.add(profile_id)
            profile = load_profile(data_dir, profile_id)
            if profile:
                ids.append(str(profile.get("id") or profile_id))
                profiles.append(profile)
        return ids, profiles

    ids, profiles = resolve_profile_ids(
        data_dir,
        use_genre=bool(ctx.config.get("use_genre_glossary", False)),
        use_series=bool(ctx.config.get("use_series_glossary", False)),
        use_book=bool(ctx.config.get("use_book_glossary", False)),
        genre_name=_genre_glossary_name(ctx),
        series_name=str(ctx.config.get("series_glossary_name") or "").strip(),
        book_name=_book_glossary_name(ctx),
    )
    return ids, profiles


def _build_glossary_override(ctx: "PipelineContext") -> Tuple[Optional[Dict[str, Any]], str]:
    if not bool(ctx.config.get("enable_glossary", True)):
        return None, ""
    configured_ids = ctx.extra.get("glossary_profile_ids") or ctx.config.get("glossary_profile_ids") or []
    if not bool(ctx.config.get("enable_layered_glossary", False)) and not configured_ids:
        ctx.extra["glossary_profile_ids"] = []
        ctx.extra["glossary_profiles"] = []
        ctx.extra["glossary_merge_stats"] = {}
        ctx.extra["glossary_fingerprint"] = ""
        return None, ""

    use_global = bool(ctx.config.get("use_global_glossary", True))
    profile_ids, profiles = _resolve_glossary_profile_ids(ctx)
    if use_global and not profile_ids:
        return None, ""

    from glossary_profiles import glossary_fingerprint, merge_selected_profiles
    from translation_cache import load_json_file
    from translator import get_data_dir

    data_dir = get_data_dir()
    base_glossary = {}
    if use_global:
        base_glossary = load_json_file(data_dir / "glossary.json", {})

    merged, selected_profiles, merge_stats = merge_selected_profiles(
        data_dir,
        profile_ids,
        base_glossary=base_glossary,
    )
    has_terms = any(isinstance(entries, list) and bool(entries) for entries in (merged or {}).values())
    fingerprint = glossary_fingerprint(merged)[:16] if has_terms else ""

    ctx.extra["glossary_profile_ids"] = profile_ids
    ctx.extra["glossary_profiles"] = selected_profiles or profiles
    ctx.extra["glossary_merge_stats"] = merge_stats
    ctx.extra["glossary_fingerprint"] = fingerprint

    logger.info(
        "[translator_init] glossary profiles=%s, use_global=%s, fingerprint=%s",
        len(profile_ids),
        use_global,
        fingerprint or "-",
    )
    return merged, fingerprint


@dataclass
class PipelineContext:
    """Shared state passed between pipeline stages."""

    config: Dict[str, Any]
    book: Any = None
    translator: Any = None
    book_service: Any = None
    docs: List[Any] = field(default_factory=list)
    toc_titles: List[str] = field(default_factory=list)
    text_plan: Any = None
    texts: List[str] = field(default_factory=list)
    results: Dict[str, str] = field(default_factory=dict)
    ordered_results: List[Optional[str]] = field(default_factory=list)
    repair_report: Any = None
    residue_scan: Any = None
    toc_translations: Dict[str, str] = field(default_factory=dict)
    detected_style: Any = None
    proofread_style: Any = None
    progress_callback: Any = None
    item_callback: Any = None
    proofread_callback: Any = None
    cancel_event: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)


class PipelineStage(ABC):
    """Base class for a small, synchronous pipeline stage."""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def process(self, ctx: PipelineContext) -> PipelineContext:
        """Run the stage and return the updated context."""
        raise NotImplementedError

    def __repr__(self) -> str:
        status = "ON" if self.enabled else "OFF"
        return f"<{self.__class__.__name__}({self.name}) [{status}]>"


class StyleDetectStage(PipelineStage):
    """Detect and resolve the proofread style used by the translator."""

    def __init__(self, enabled: bool = True):
        super().__init__("style_detect", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[style_detect] stage disabled; skipping")
            return ctx

        try:
            from style_detector import detect_novel_style, resolve_style_selection

            cfg = ctx.config
            title = str(cfg.get("title") or ctx.extra.get("title") or "")
            detected = detect_novel_style(
                title=title,
                toc_titles=ctx.extra.get("toc_titles", []),
                samples=ctx.texts[:80] if ctx.texts else [],
            )
            ctx.detected_style = detected

            proofread_style = resolve_style_selection(
                cfg.get("proofread_genre", "auto"),
                cfg.get("proofread_tone", "auto"),
                detected,
            )
            ctx.proofread_style = proofread_style
            logger.info(
                "[style_detect] result: %s (confidence: %s)",
                proofread_style.display_text,
                proofread_style.confidence,
            )
        except Exception as exc:
            logger.warning("[style_detect] failed, continuing with defaults: %s", exc)

        return ctx


class LoadEpubStage(PipelineStage):
    """Load the EPUB and collect text-node documents plus TOC titles."""

    def __init__(self, enabled: bool = True):
        super().__init__("epub_load", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[epub_load] stage disabled; skipping")
            return ctx

        from epub_io import extract_toc_titles, iter_text_nodes, load_book

        input_path = ctx.config["inp"]
        ctx.book = load_book(input_path)
        ctx.docs = list(iter_text_nodes(ctx.book))
        ctx.toc_titles = extract_toc_titles(ctx.book)
        ctx.extra["title"] = ctx.extra.get("title") or str(input_path)
        ctx.extra["toc_titles"] = ctx.toc_titles
        logger.info(
            "[epub_load] docs=%s, toc_titles=%s",
            len(ctx.docs),
            len(ctx.toc_titles),
        )
        return ctx


class BuildTextPlanStage(PipelineStage):
    """Build the ordered list of translatable text blocks."""

    def __init__(self, enabled: bool = True):
        super().__init__("text_extract", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[text_extract] stage disabled; skipping")
            return ctx

        from .book_translation_service import BookTranslationService

        ctx.book_service = ctx.book_service or BookTranslationService()
        ctx.text_plan = ctx.book_service.build_text_plan(ctx.docs, ctx.toc_titles)
        ctx.texts = list(ctx.text_plan.all_texts)
        ctx.extra["total_texts"] = ctx.text_plan.total_texts
        ctx.extra["total_chars"] = ctx.text_plan.total_chars
        logger.info(
            "[text_extract] texts=%s, chars=%s",
            ctx.text_plan.total_texts,
            ctx.text_plan.total_chars,
        )
        return ctx


class CreateTranslatorStage(PipelineStage):
    """Create the configured JaZhTranslator instance."""

    def __init__(self, enabled: bool = True):
        super().__init__("translator_init", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[translator_init] stage disabled; skipping")
            return ctx

        from translator import JaZhTranslator

        cfg = ctx.config
        style = ctx.proofread_style
        if style is None:
            from style_detector import StyleDetectionResult

            style = StyleDetectionResult(
                genre=cfg.get("proofread_genre", "general"),
                tone=cfg.get("proofread_tone", "neutral"),
                confidence=0,
                reason="",
            )
            ctx.proofread_style = style

        factory = ctx.extra.get("translator_factory") or JaZhTranslator
        glossary_override, glossary_fp = _build_glossary_override(ctx)
        ctx.translator = factory(
            api_key=cfg["api_key"],
            provider=cfg["provider"],
            api_url=cfg["api_url"],
            model=cfg["model"],
            max_workers=cfg["max_workers"],
            batch_size=cfg["batch_size"],
            max_batch_length=cfg["max_batch_length"],
            max_text_size_for_batch=cfg["max_text_size_for_batch"],
            api_timeout=cfg["api_timeout"],
            cancel_event=ctx.cancel_event,
            extract_glossary=cfg["extract_glossary"],
            enable_glossary=cfg["enable_glossary"],
            enable_thinking=cfg["enable_thinking"],
            enable_proofread=cfg["enable_proofread"],
            proofread_genre=style.genre,
            proofread_tone=style.tone,
            proofread_model=cfg.get("proofread_model") or None,
            proofread_provider=cfg.get("proofread_provider") or None,
            proofread_api_key=cfg.get("proofread_api_key") or None,
            proofread_api_url=cfg.get("proofread_api_url") or None,
            allow_text_cache_reuse=bool(cfg.get("allow_text_cache_reuse", True)),
            prompt_extra_instruction=cfg.get("prompt_extra_instruction", ""),
            enable_prompt_examples=bool(cfg.get("enable_prompt_examples", True)),
            hymt2_generation_mode=cfg.get("hymt2_generation_mode", "stable"),
            hymt2_prompt_mode=cfg.get("hymt2_prompt_mode", "official"),
            hymt2_runtime_mode=cfg.get("hymt2_runtime_mode", "cpu"),
            glossary_extraction_mode=cfg.get("glossary_extraction_mode", "novel"),
            glossary_override=glossary_override,
            glossary_fingerprint=glossary_fp,
        )
        logger.info(
            "[translator_init] provider=%s, model=%s, workers=%s, batch=%s",
            cfg.get("provider"),
            cfg.get("model"),
            cfg.get("max_workers"),
            cfg.get("batch_size"),
        )
        return ctx


class BatchTranslateStage(PipelineStage):
    """Translate all extracted text blocks."""

    def __init__(self, enabled: bool = True):
        super().__init__("model_translate", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[model_translate] stage disabled; skipping")
            return ctx
        if ctx.translator is None:
            raise RuntimeError("BatchTranslateStage requires ctx.translator")

        ctx.results = ctx.translator.translate_batch(
            ctx.texts,
            progress_callback=ctx.progress_callback,
            item_callback=ctx.item_callback,
            proofread_callback=ctx.proofread_callback,
            context_texts=ctx.texts,
        )
        ordered = getattr(ctx.translator, "last_ordered_results", [])
        if isinstance(ordered, list) and len(ordered) == len(ctx.texts):
            ctx.ordered_results = ordered
        else:
            ctx.ordered_results = []
        logger.info("[model_translate] translated=%s", len(ctx.results or {}))
        return ctx


class ApplyBookTranslationsStage(PipelineStage):
    """Write translations into the in-memory EPUB and scan residue."""

    def __init__(self, enabled: bool = True):
        super().__init__("book_apply", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[book_apply] stage disabled; skipping")
            return ctx
        if ctx.book_service is None or ctx.text_plan is None:
            raise RuntimeError("ApplyBookTranslationsStage requires text_plan and book_service")

        clean_title = ctx.extra["clean_title"]
        looks_like_refusal = ctx.extra["looks_like_refusal"]
        ctx.book_service.apply_translations(
            ctx.text_plan,
            ctx.results,
            ctx.ordered_results,
            clean_title,
            looks_like_refusal,
        )
        ctx.repair_report = ctx.book_service.repair_known_katakana_terms(ctx.docs)
        ctx.residue_scan = ctx.book_service.scan_japanese_residue(ctx.docs)
        logger.info(
            "[book_apply] repaired=%s, residue=%s",
            getattr(ctx.repair_report, "repaired_total", 0),
            getattr(ctx.residue_scan, "blocking_total", 0),
        )
        return ctx


class FinalizeBookContentStage(PipelineStage):
    """Finalize document content, TOC translations, and optional notice page."""

    def __init__(self, enabled: bool = True):
        super().__init__("book_finalize", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[book_finalize] stage disabled; skipping")
            return ctx
        if ctx.book_service is None or ctx.text_plan is None:
            raise RuntimeError("FinalizeBookContentStage requires text_plan and book_service")

        from epub_io import add_translation_notice_page, apply_toc_translations

        clean_title = ctx.extra["clean_title"]
        looks_like_refusal = ctx.extra["looks_like_refusal"]
        for item, soup, _ in ctx.docs:
            item.set_content(str(soup).encode("utf-8"))

        ctx.toc_translations = ctx.book_service.build_toc_translation_map(
            ctx.text_plan,
            ctx.results,
            ctx.ordered_results,
            clean_title,
            looks_like_refusal,
        )
        if ctx.toc_translations:
            apply_toc_translations(ctx.book, ctx.toc_translations)

        if bool(ctx.config.get("enable_notice_page", False)):
            add_translation_notice_page(ctx.book, ctx.config.get("notice_page_text") or "")
            logger.info("[book_finalize] translation notice page added")

        logger.info("[book_finalize] toc_translations=%s", len(ctx.toc_translations))
        return ctx


class TranslationPipeline:
    """Run enabled stages in order."""

    def __init__(self):
        self._stages: List[PipelineStage] = []

    def add_stage(self, stage: PipelineStage) -> "TranslationPipeline":
        self._stages.append(stage)
        return self

    def remove_stage(self, name: str) -> "TranslationPipeline":
        self._stages = [stage for stage in self._stages if stage.name != name]
        return self

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        for stage in self._stages:
            if stage.name == name:
                return stage
        return None

    @property
    def stages(self) -> List[PipelineStage]:
        return list(self._stages)

    @property
    def active_stages(self) -> List[PipelineStage]:
        return [stage for stage in self._stages if stage.enabled]

    def run(self, ctx: PipelineContext) -> PipelineContext:
        active = self.active_stages
        if not active:
            logger.warning("No enabled pipeline stages; returning context unchanged")
            return ctx

        logger.info("Starting pipeline: %s", " -> ".join(stage.name for stage in active))
        for stage in active:
            if ctx.cancel_event and ctx.cancel_event.is_set():
                logger.info("Pipeline cancelled before stage: %s", stage.name)
                break
            try:
                ctx = stage.process(ctx)
            except Exception:
                logger.exception("Pipeline stage failed: %s", stage.name)
                raise

        return ctx
