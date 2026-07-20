# -*- coding: utf-8 -*-
"""EPUB book-level translation helpers for the QML/V4 workflow."""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from bs4 import NavigableString

from epub_io import extract_visible_text
from text_utils import is_translatable
from translator import JaZhTranslator
import translation_quality as tq


CleanTitle = Callable[[str], str]
RefusalCheck = Callable[[str], bool]


@dataclass
class BookTextPlan:
    docs: List[Any]
    toc_titles: List[str]
    all_texts: List[str]
    text_tag_map: List[Any]
    toc_indices_start: int
    toc_indices_end: int

    @property
    def total_texts(self) -> int:
        return len(self.all_texts)

    @property
    def total_chars(self) -> int:
        return sum(len(text) for text in self.all_texts) or 1


@dataclass
class JapaneseResidueScan:
    blocking_total: int
    blocking_samples: List[str]
    weak_total: int
    weak_samples: List[str]
    hard_blocking_total: int = 0
    hard_blocking_samples: List[str] = field(default_factory=list)
    low_risk_total: int = 0
    low_risk_samples: List[str] = field(default_factory=list)
    high_risk_total: int = 0
    high_risk_samples: List[str] = field(default_factory=list)
    medium_risk_total: int = 0
    medium_risk_samples: List[str] = field(default_factory=list)
    structured_samples: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class JapaneseResidueRepairReport:
    repaired_total: int
    samples: List[str]


class BookTranslationService:
    """Pure EPUB text-plan service used by UI workers."""

    def build_text_plan(self, docs: List[Any], toc_titles: List[str]) -> BookTextPlan:
        return build_book_text_plan(docs, toc_titles)

    def apply_translations(
        self,
        plan: BookTextPlan,
        results: Dict[str, str],
        ordered_results: Optional[List[Optional[str]]],
        clean_title: CleanTitle,
        looks_like_refusal: RefusalCheck,
    ) -> None:
        apply_translations_to_book(plan, results, ordered_results, clean_title, looks_like_refusal)

    def build_toc_translation_map(
        self,
        plan: BookTextPlan,
        results: Dict[str, str],
        ordered_results: Optional[List[Optional[str]]],
        clean_title: CleanTitle,
        looks_like_refusal: RefusalCheck,
    ) -> Dict[str, str]:
        return build_toc_translation_map(plan, results, ordered_results, clean_title, looks_like_refusal)

    def scan_japanese_residue(self, docs: List[Any]) -> JapaneseResidueScan:
        return scan_japanese_residue_in_docs(docs)

    def repair_known_katakana_terms(self, docs: List[Any]) -> JapaneseResidueRepairReport:
        return repair_known_katakana_terms_in_docs(docs)


def build_book_text_plan(docs: List[Any], toc_titles: List[str]) -> BookTextPlan:
    all_texts: List[str] = []
    text_tag_map: List[Any] = []

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
    all_texts.extend(toc_titles or [])
    toc_indices_end = len(all_texts)

    return BookTextPlan(
        docs=docs,
        toc_titles=list(toc_titles or []),
        all_texts=all_texts,
        text_tag_map=text_tag_map,
        toc_indices_start=toc_indices_start,
        toc_indices_end=toc_indices_end,
    )


def _ordered_translation(
    original: str,
    index: int,
    results: Dict[str, str],
    ordered_results: Optional[List[Optional[str]]],
) -> Optional[str]:
    if ordered_results and index < len(ordered_results):
        translated = ordered_results[index]
        if translated:
            return translated
    return results.get(original)


def _clean_node_translation(
    original: str,
    translated: Optional[str],
    mode: str,
    tag: Any,
    toc_title_set: set,
    clean_title: CleanTitle,
    looks_like_refusal: RefusalCheck,
) -> Optional[str]:
    if not translated:
        return translated
    tag_name = str(getattr(tag, "name", "") or "").lower()
    is_heading = tag_name in {"h1", "h2", "h3"}
    if mode in ("single_anchor", "multi_anchor") or original in toc_title_set or is_heading:
        cleaned = clean_title(translated)
        if cleaned:
            return cleaned
        if looks_like_refusal(translated):
            return original
    return translated


def apply_translations_to_book(
    plan: BookTextPlan,
    results: Dict[str, str],
    ordered_results: Optional[List[Optional[str]]],
    clean_title: CleanTitle,
    looks_like_refusal: RefusalCheck,
) -> None:
    toc_title_set = set(plan.toc_titles or [])
    ordered_cursor = 0

    for record in plan.text_tag_map:
        mode, _, tag = record[0], record[1], record[2]
        if mode == "multi_anchor":
            node_records = record[3]
            for node, original in node_records:
                translated = _ordered_translation(original, ordered_cursor, results, ordered_results)
                ordered_cursor += 1
                translated = _clean_node_translation(
                    original,
                    translated,
                    mode,
                    tag,
                    toc_title_set,
                    clean_title,
                    looks_like_refusal,
                )
                if translated:
                    node.replace_with(NavigableString(translated))
            continue

        original = record[3]
        translated = _ordered_translation(original, ordered_cursor, results, ordered_results)
        ordered_cursor += 1
        translated = _clean_node_translation(
            original,
            translated,
            mode,
            tag,
            toc_title_set,
            clean_title,
            looks_like_refusal,
        )
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


def build_toc_translation_map(
    plan: BookTextPlan,
    results: Dict[str, str],
    ordered_results: Optional[List[Optional[str]]],
    clean_title: CleanTitle,
    looks_like_refusal: RefusalCheck,
) -> Dict[str, str]:
    toc_translations: Dict[str, str] = {}
    for index in range(plan.toc_indices_start, plan.toc_indices_end):
        original = plan.all_texts[index]
        translated = _ordered_translation(original, index, results, ordered_results)
        if not translated:
            continue
        cleaned_title = clean_title(translated)
        if cleaned_title:
            toc_translations[original] = cleaned_title
        elif not looks_like_refusal(translated):
            toc_translations[original] = translated
    return toc_translations


def scan_japanese_residue_in_docs(docs: List[Any]) -> JapaneseResidueScan:
    hidden_tags = {"rt", "rp", "script", "style", "noscript"}
    blocking_samples: List[str] = []
    hard_blocking_samples: List[str] = []
    low_risk_samples: List[str] = []
    weak_samples: List[str] = []
    high_risk_samples: List[str] = []
    medium_risk_samples: List[str] = []
    structured_samples: List[Dict[str, Any]] = []
    blocking_total = 0
    hard_blocking_total = 0
    low_risk_total = 0
    weak_total = 0
    high_risk_total = 0
    medium_risk_total = 0

    def add_structured_sample(risk: str, raw: str, fragments: List[str], reason: str) -> None:
        if len(structured_samples) >= 24:
            return
        structured_samples.append(
            {
                "risk": risk,
                "fragments": list(fragments[:8]),
                "reason": reason,
                "text": raw[:240],
            }
        )

    for _, soup, _ in docs:
        root = soup.find("body") or soup
        for node in root.find_all(string=True):
            parent_name = getattr(getattr(node, "parent", None), "name", "")
            if parent_name in hidden_tags:
                continue
            raw = str(node).strip()
            if not raw:
                continue
            classification = tq.classify_japanese_residue(raw)
            risk = str(classification.get("risk") or "none")
            fragments = list(classification.get("fragments") or [])
            reason = str(classification.get("reason") or "")
            if risk in {"high", "medium", "low"} and classification.get("blocking"):
                blocking_total += 1
                fragment_text = " / ".join(fragments[:5]) if fragments else "unknown"
                sample = f"fragment: {fragment_text} | text: {raw[:120]}"
                add_structured_sample(risk, raw, fragments, reason)
                if len(blocking_samples) < 8:
                    blocking_samples.append(sample)
                if risk == "low":
                    low_risk_total += 1
                    if len(low_risk_samples) < 8:
                        low_risk_samples.append(sample)
                else:
                    hard_blocking_total += 1
                    if len(hard_blocking_samples) < 8:
                        hard_blocking_samples.append(sample)
                    if risk == "high":
                        high_risk_total += 1
                        if len(high_risk_samples) < 8:
                            high_risk_samples.append(sample)
                    else:
                        medium_risk_total += 1
                        if len(medium_risk_samples) < 8:
                            medium_risk_samples.append(sample)
            elif risk == "weak":
                weak_total += 1
                add_structured_sample(risk, raw, fragments, reason)
                if len(weak_samples) < 5:
                    fragment_text = " / ".join(fragments[:5]) if fragments else "unknown"
                    weak_samples.append(f"fragment: {fragment_text} | text: {raw[:120]}")

    return JapaneseResidueScan(
        blocking_total=blocking_total,
        blocking_samples=blocking_samples,
        weak_total=weak_total,
        weak_samples=weak_samples,
        hard_blocking_total=hard_blocking_total,
        hard_blocking_samples=hard_blocking_samples,
        low_risk_total=low_risk_total,
        low_risk_samples=low_risk_samples,
        high_risk_total=high_risk_total,
        high_risk_samples=high_risk_samples,
        medium_risk_total=medium_risk_total,
        medium_risk_samples=medium_risk_samples,
        structured_samples=structured_samples,
    )


def repair_known_katakana_terms_in_docs(docs: List[Any]) -> JapaneseResidueRepairReport:
    hidden_tags = {"rt", "rp", "script", "style", "noscript"}
    repaired_total = 0
    samples: List[str] = []

    for _, soup, _ in docs:
        root = soup.find("body") or soup
        for node in root.find_all(string=True):
            parent_name = getattr(getattr(node, "parent", None), "name", "")
            if parent_name in hidden_tags:
                continue
            raw = str(node)
            if not raw.strip():
                continue
            repaired = tq.repair_save_time_japanese_residue("", raw)
            if repaired == raw:
                continue
            node.replace_with(NavigableString(repaired))
            repaired_total += 1
            if len(samples) < 8:
                samples.append(f"{raw[:80]} -> {repaired[:80]}")

    return JapaneseResidueRepairReport(repaired_total=repaired_total, samples=samples)
