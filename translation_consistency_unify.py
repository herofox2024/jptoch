# -*- coding: utf-8 -*-
"""Unify term renderings inside a finished translation.

Why this is separate from ``translation_consistency_apply``
-----------------------------------------------------------
That module writes findings back into the *glossary*, which only affects the
**next** translation run. This module fixes the text you already have: it rewrites
minority renderings so the current book reads consistently, with no extra API
calls and no re-translation.

The hard part is knowing *what* the minority rendering looks like
------------------------------------------------------------------
The scanner reports that 「ローラ」 became 劳拉 / 萝拉 / 罗拉, so the variant strings
are already known — they come straight from the report's ``variants`` list. This
module therefore never guesses: it takes the exact variant strings and replaces
only those, inside sentences where the Japanese source really contains the term.

Extra safety rules
------------------
1. Only sentences whose **Japanese original** contains the term are touched. A
   string like 「丰」 appears in unrelated Chinese words, so context is required.
2. A variant that is a substring of another variant, or of *any other* glossary
   translation, is skipped: it belongs to something else or would corrupt text.
3. The authoritative translation must already dominate; otherwise there is no
   clear winner and nothing is rewritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Replacing a single CJK character is almost always wrong: such characters appear
# inside unrelated words. Require at least two characters.
MIN_REPLACE_LEN = 2


@dataclass
class TextReplacement:
    """One term unification applied to the text."""

    original: str
    to_text: str
    variants: List[str] = field(default_factory=list)
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "to": self.to_text,
            "variants": list(self.variants),
            "count": self.count,
        }


@dataclass
class UnifyResult:
    """Outcome of unifying one book's term renderings."""

    pairs_changed: int = 0
    replacements: List[TextReplacement] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def total_replacements(self) -> int:
        return sum(r.count for r in self.replacements)

    def summary(self) -> str:
        if not self.replacements:
            return "无需统一术语（未发现可安全替换的多余译法）"
        return (
            f"已统一 {len(self.replacements)} 个术语，"
            f"改写 {self.total_replacements} 处（涉及 {self.pairs_changed} 段）"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "pairs_changed": self.pairs_changed,
            "total_replacements": self.total_replacements,
            "replacements": [r.to_dict() for r in self.replacements],
            "skipped": list(self.skipped),
        }


def _all_other_translations(glossary: Dict[str, Any], excluding: str) -> List[str]:
    """Translations of every other glossary entry, for collision detection."""
    others: List[str] = []
    for entries in (glossary or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("original") or "").strip() == excluding:
                continue
            translation = str(entry.get("translation") or "").strip()
            if translation:
                others.append(translation)
    return others


def _safe_variants(
    variants: Sequence[str],
    winner: str,
    other_terms: Sequence[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Filter the variant list down to strings that are safe to replace."""
    safe: List[str] = []
    skipped: List[Dict[str, Any]] = []

    for raw in variants:
        variant = str(raw or "").strip()
        if not variant or variant == winner:
            continue

        # 危险情形：变体是权威译名的一部分（幸 ⊂ 阿幸）。
        # 把「幸」换成「阿幸」会把已有的「阿幸」撑成「阿阿幸」。
        if variant in winner and variant != winner:
            skipped.append(
                {
                    "variant": variant,
                    "reason": f"「{variant}」是权威译名「{winner}」的一部分，替换会破坏原文",
                }
            )
            continue

        # 安全情形：权威译名是变体的一部分（丰 ⊂ 小丰）。
        # 把「小丰」换成「丰」不会误伤，这是正常的收敛方向。
        # 但变体自身仍需够长，否则可能就是普通词。
        if len(variant) < MIN_REPLACE_LEN:
            skipped.append(
                {"variant": variant, "reason": "过短，替换容易误伤"}
            )
            continue
        # 该串属于别的术语时，不是在改我们关心的词
        collision = next((o for o in other_terms if o and variant in o), "")
        if collision:
            skipped.append(
                {
                    "variant": variant,
                    "reason": f"属于其他术语「{collision}」，跳过",
                }
            )
            continue
        safe.append(variant)

    return safe, skipped


def unify_term_renderings(
    pairs: Sequence[Tuple[str, str]],
    glossary: Dict[str, Any],
    *,
    variants_by_term: Optional[Dict[str, Sequence[str]]] = None,
    min_winning_count: int = 2,
) -> Tuple[List[Tuple[str, str]], UnifyResult]:
    """Rewrite minority term renderings so the book reads consistently.

    Parameters
    ----------
    pairs:
        ``[(source_japanese, translated_chinese), ...]`` in reading order.
    glossary:
        ``{category: [{"original": ..., "translation": ...}, ...]}``.
        The glossary translation is authoritative.
    variants_by_term:
        ``{original: [other_rendering, ...]}`` — the alternative strings found in
        this book, normally taken straight from a consistency report's
        ``variants``. When omitted, nothing is rewritten (there is nothing to
        identify the alternatives by).
    min_winning_count:
        The authoritative translation must already appear at least this often.

    Returns
    -------
    ``(new_pairs, result)``. The input list is not mutated.
    """
    result = UnifyResult()
    if not pairs or not isinstance(glossary, dict) or not variants_by_term:
        return list(pairs or []), result

    updated = [[str(src or ""), str(dst or "")] for src, dst in pairs]
    changed_pairs: set[int] = set()

    for entries in glossary.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            original = str(entry.get("original") or "").strip()
            winner = str(entry.get("translation") or "").strip()
            if not original or not winner:
                continue
            raw_variants = variants_by_term.get(original) or []
            if not raw_variants:
                continue

            other_terms = _all_other_translations(glossary, original)
            safe_variants, skipped = _safe_variants(raw_variants, winner, other_terms)
            result.skipped.extend(
                [{"original": original, **item} for item in skipped]
            )
            if not safe_variants:
                continue

            pattern = re.compile(re.escape(original))
            hit_indexes = [
                i for i, (src, _) in enumerate(updated) if pattern.search(src)
            ]
            if not hit_indexes:
                continue

            # 权威译名必须已经占多数，否则没有统一方向
            winner_hits = sum(1 for i in hit_indexes if winner in updated[i][1])
            if winner_hits < min_winning_count:
                result.skipped.append(
                    {
                        "original": original,
                        "variant": "",
                        "reason": (
                            f"权威译名「{winner}」仅出现 {winner_hits} 次，"
                            "不足以判定统一方向"
                        ),
                    }
                )
                continue

            replaced = 0
            used_variants: set[str] = set()
            for i in hit_indexes:
                text = updated[i][1]
                for variant in safe_variants:
                    if variant not in text:
                        continue
                    before = text
                    text = text.replace(variant, winner)
                    if text != before:
                        replaced += before.count(variant)
                        used_variants.add(variant)
                if text != updated[i][1]:
                    updated[i][1] = text
                    changed_pairs.add(i)

            if replaced:
                result.replacements.append(
                    TextReplacement(
                        original=original,
                        to_text=winner,
                        variants=sorted(used_variants),
                        count=replaced,
                    )
                )

    result.pairs_changed = len(changed_pairs)
    return [(s, d) for s, d in updated], result
