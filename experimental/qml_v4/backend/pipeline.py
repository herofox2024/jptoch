# -*- coding: utf-8 -*-
"""Lightweight pipeline primitives for the QML/V4 translation workflow.

The production workflow currently uses this module for style detection only.
Translation, cache lookup, proofreading, EPUB mutation, and saving remain in
``JaZhTranslator`` / ``BookTranslationService`` until those phases are migrated
behind tests.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineContext:
    """Shared state passed between pipeline stages."""

    config: Dict[str, Any]
    translator: Any = None
    texts: List[str] = field(default_factory=list)
    results: Dict[str, str] = field(default_factory=dict)
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
