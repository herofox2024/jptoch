# -*- coding: utf-8 -*-
"""
翻译管线阶段抽象模块

参考 manga-translator-ui 的 dispatch 模式，将翻译流程拆分为可独立配置、
可开关的管线阶段。每阶段实现 prepare() → process() 接口。

阶段列表（按执行顺序）：
    1. StyleDetectStage  — 风格检测（genre/tone）
    2. CacheLookupStage  — 缓存查找
    3. TranslateStage    — 批量翻译（核心）
    4. ProofreadStage    — 校对修正

用法：
    pipeline = TranslationPipeline()
    pipeline.add_stage(StyleDetectStage(enabled=True))
    pipeline.add_stage(CacheLookupStage(enabled=True))
    pipeline.add_stage(TranslateStage(enabled=True))
    pipeline.add_stage(ProofreadStage(enabled=True))
    results = pipeline.run(context)
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 管线上下文：在阶段间传递数据
# ---------------------------------------------------------------------------
class PipelineContext:
    """管线执行上下文，阶段间通过此对象共享数据。"""

    __slots__ = ("config", "translator", "texts", "results",
                 "detected_style", "proofread_style",
                 "progress_callback", "item_callback", "proofread_callback",
                 "cancel_event", "extra")

    def __init__(
        self,
        config: Dict[str, Any],
        translator: Any = None,
        texts: Optional[List[str]] = None,
        results: Optional[Dict[str, str]] = None,
        progress_callback: Any = None,
        item_callback: Any = None,
        proofread_callback: Any = None,
        cancel_event: Any = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.config = config
        self.translator = translator
        self.texts = texts or []
        self.results = results or {}
        self.detected_style = None
        self.proofread_style = None
        self.progress_callback = progress_callback
        self.item_callback = item_callback
        self.proofread_callback = proofread_callback
        self.cancel_event = cancel_event
        self.extra = extra or {}


# ---------------------------------------------------------------------------
# 管线阶段基类
# ---------------------------------------------------------------------------
class PipelineStage(ABC):
    """管线阶段抽象基类。"""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled

    @abstractmethod
    def process(self, ctx: PipelineContext) -> PipelineContext:
        """执行阶段逻辑，返回更新后的上下文。"""
        ...

    def __repr__(self):
        status = "ON" if self.enabled else "OFF"
        return f"<{self.__class__.__name__}({self.name}) [{status}]>"


# ---------------------------------------------------------------------------
# 具体阶段实现
# ---------------------------------------------------------------------------

class StyleDetectStage(PipelineStage):
    """
    风格检测阶段：分析 EPUB 标题、目录、样本文本，检测小说类型和语调。
    参考 manga-translator-ui 的 detect/dispatch 分离模式。
    """

    def __init__(self, enabled: bool = True):
        super().__init__("style_detect", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[style_detect] 阶段已禁用，跳过")
            return ctx

        try:
            from style_detector import detect_novel_style, resolve_style_selection

            cfg = ctx.config
            detected = detect_novel_style(
                title=cfg.get("title", ""),
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
            logger.info(f"[style_detect] 检测结果: {proofread_style.display_text} (置信度: {proofread_style.confidence})")
        except Exception as e:
            logger.warning(f"[style_detect] 风格检测失败（非致命）: {e}")

        return ctx


class CacheLookupStage(PipelineStage):
    """
    缓存查找阶段：从翻译缓存中查找已有结果，减少 API 调用。
    """

    def __init__(self, enabled: bool = True):
        super().__init__("cache_lookup", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[cache_lookup] 阶段已禁用，跳过")
            return ctx

        translator = ctx.translator
        if not translator or not ctx.texts:
            return ctx

        hit_count = 0
        uncached = []
        for text in ctx.texts:
            cache_key = translator._cache_key(text)
            with translator._cache_lock:
                if cache_key in translator.cache:
                    ctx.results[text] = translator.cache[cache_key]
                    hit_count += 1
                else:
                    uncached.append(text)

        ctx.extra["uncached_texts"] = uncached
        logger.info(f"[cache_lookup] 缓存命中: {hit_count}/{len(ctx.texts)}")

        if ctx.progress_callback:
            ctx.progress_callback(hit_count, len(ctx.texts))

        return ctx


class TranslateStage(PipelineStage):
    """
    翻译阶段：将未缓存的文本批量发送到 LLM API 进行翻译。
    """

    def __init__(self, enabled: bool = True):
        super().__init__("translate", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[translate] 阶段已禁用，跳过")
            return ctx

        translator = ctx.translator
        uncached = ctx.extra.get("uncached_texts", ctx.texts)

        if not translator or not uncached:
            return ctx

        logger.info(f"[translate] 开始翻译 {len(uncached)} 条文本")
        try:
            new_results = translator.translate_batch(
                uncached,
                progress_callback=ctx.progress_callback,
                item_callback=ctx.item_callback,
                proofread_callback=None,  # Proofread 由独立阶段处理
            )
            ctx.results.update(new_results or {})
        except Exception as e:
            logger.error(f"[translate] 翻译失败: {e}")
            raise

        return ctx


class ProofreadStage(PipelineStage):
    """
    校对阶段：检查翻译结果中的日语残留、术语不一致、格式异常。
    参考 manga-translator-ui 的 multi-stage pipeline 设计。
    """

    def __init__(self, enabled: bool = True):
        super().__init__("proofread", enabled)

    def process(self, ctx: PipelineContext) -> PipelineContext:
        if not self.enabled:
            logger.debug("[proofread] 阶段已禁用，跳过")
            return ctx

        cfg = ctx.config
        if not cfg.get("enable_proofread", False):
            logger.debug("[proofread] 校对功能未开启")
            return ctx

        translator = ctx.translator
        if not translator or not ctx.results:
            return ctx

        # 校对在 translator.translate_batch 内部已通过 proofread_callback 处理
        # 此阶段负责将 proofread_style 设置到 translator 上
        if ctx.proofread_style:
            translator.proofread_genre = ctx.proofread_style.genre
            translator.proofread_tone = ctx.proofread_style.tone
            logger.info(f"[proofread] 校对参数已设置: genre={ctx.proofread_style.genre}, tone={ctx.proofread_style.tone}")

        return ctx


# ---------------------------------------------------------------------------
# 管线编排器
# ---------------------------------------------------------------------------
class TranslationPipeline:
    """
    翻译管线编排器。

    用法：
        pipeline = TranslationPipeline()
        pipeline.add_stage(StyleDetectStage())
        pipeline.add_stage(TranslateStage())
        ctx = PipelineContext(config={...}, texts=[...], translator=t)
        result_ctx = pipeline.run(ctx)
    """

    def __init__(self):
        self._stages: List[PipelineStage] = []

    def add_stage(self, stage: PipelineStage) -> "TranslationPipeline":
        self._stages.append(stage)
        return self

    def remove_stage(self, name: str) -> "TranslationPipeline":
        self._stages = [s for s in self._stages if s.name != name]
        return self

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        for s in self._stages:
            if s.name == name:
                return s
        return None

    @property
    def stages(self) -> List[PipelineStage]:
        return list(self._stages)

    @property
    def active_stages(self) -> List[PipelineStage]:
        return [s for s in self._stages if s.enabled]

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """按顺序执行所有启用的阶段。"""
        active = self.active_stages
        if not active:
            logger.warning("没有启用的管线阶段")
            return ctx

        logger.info(f"开始执行管线: {' → '.join(s.name for s in active)}")
        for stage in active:
            if ctx.cancel_event and ctx.cancel_event.is_set():
                logger.info(f"管线执行被取消（阶段: {stage.name}）")
                break
            try:
                ctx = stage.process(ctx)
            except Exception as e:
                logger.error(f"管线阶段 [{stage.name}] 执行失败: {e}")
                raise

        return ctx
