# -*- coding: utf-8 -*-
"""Turn term-consistency findings back into glossary profiles.

Why this exists
---------------
The consistency scanner (``translation_consistency``) can tell you that
「ローラ」 was rendered as 劳拉 / 萝拉 / 罗拉 in one book, but until now that
report was read-only: nothing carried the conclusion back into the glossary, so
the next translation run repeated the same mistake.

This module closes the loop. It converts a report into concrete glossary entries
that ``glossary_profiles.save_profile`` can persist, and it deliberately keeps the
*pick* of the winning translation explicit instead of guessing:

* ``divergent`` -- several renderings seen. The most frequent one is proposed by
  default, because it already dominates the finished text; switching to a
  minority variant would mean rewriting more sentences than it fixes.
* ``missing``   -- the glossary entry was never used. Nothing is auto-added here:
  the scanner cannot tell whether the glossary was wrong or the text was right,
  so these are surfaced for human review instead of silently "fixing" the book.
* ``deviating`` -- same situation as ``missing``.

The public entry point is :func:`build_glossary_updates`. It is pure: it returns
a proposal and never writes files. Persisting is the caller's decision.

Scope of the fix
----------------
Writing back to the glossary affects the **next** translation run. It does not
rewrite text that is already translated: a book that already contains both 阿肌
and 小真 will keep reporting ``divergent`` for that term, because the scanner
reads finished sentences. Fixing an existing book means editing its text (or
re-translating it), which is a separate operation.

That distinction matters when reading the report: after a successful write-back,
a re-scan of the *same* output still shows the issue, while a fresh translation
of the same book passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Minimum occurrences before a divergent term is worth writing back. Below this
# the evidence is thin and the scanner is more likely to be misreading context.
MIN_OCCURRENCES = 2


@dataclass
class GlossaryUpdate:
    """One proposed glossary entry derived from a consistency finding."""

    original: str
    translation: str
    category: str
    reason: str
    """Why this translation won: ``most_frequent`` / ``only_variant``."""
    winning_count: int = 0
    total_variants: int = 0
    alternatives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "translation": self.translation,
            "category": self.category,
            "reason": self.reason,
            "winning_count": self.winning_count,
            "total_variants": self.total_variants,
            "alternatives": list(self.alternatives),
        }


@dataclass
class GlossaryUpdatePlan:
    """Result of analysing a consistency report."""

    updates: List[GlossaryUpdate] = field(default_factory=list)
    needs_review: List[Dict[str, Any]] = field(default_factory=list)
    """Findings the scanner cannot resolve safely (missing / deviating)."""

    @property
    def has_updates(self) -> bool:
        return bool(self.updates)

    def summary(self) -> str:
        if not self.updates and not self.needs_review:
            return "术语一致性检查未发现需要写回的内容"
        parts = []
        if self.updates:
            parts.append(f"可写回 {len(self.updates)} 条")
        if self.needs_review:
            parts.append(f"需人工确认 {len(self.needs_review)} 条")
        return "，".join(parts)

    def to_terms(self) -> Dict[str, List[Dict[str, Any]]]:
        """Group updates into the ``{category: [entries]}`` glossary shape."""
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for update in self.updates:
            entry = {
                "original": update.original,
                "translation": update.translation,
                "source": "consistency_fix",
            }
            if update.alternatives:
                entry["aliases"] = list(update.alternatives)
            grouped.setdefault(update.category or "Item", []).append(entry)
        return grouped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary(),
            "updates": [u.to_dict() for u in self.updates],
            "needs_review": list(self.needs_review),
        }


def build_glossary_updates(
    report: Dict[str, Any],
    *,
    min_occurrences: int = MIN_OCCURRENCES,
) -> GlossaryUpdatePlan:
    """Turn a consistency report into a glossary update proposal.

    Parameters
    ----------
    report:
        A ``TermConsistencyReport.to_dict()`` payload (or any dict with an
        ``issues`` list of the same shape).
    min_occurrences:
        A divergent term must have been seen at least this many times in total
        before it is proposed for write-back.

    Returns
    -------
    GlossaryUpdatePlan
    """
    plan = GlossaryUpdatePlan()
    if not isinstance(report, dict):
        return plan

    for issue in report.get("issues") or []:
        if not isinstance(issue, dict):
            continue
        verdict = str(issue.get("verdict") or "")
        original = str(issue.get("original") or "").strip()
        category = str(issue.get("category") or "Item").strip() or "Item"
        if not original:
            continue

        if verdict == "divergent":
            variants = [v for v in (issue.get("variants") or []) if isinstance(v, dict)]
            if not variants:
                continue

            # 按出现次数排序，次数相同则保持扫描器给出的顺序（通常是先出现者）
            ranked = sorted(
                variants,
                key=lambda v: -int(v.get("count") or 0),
            )
            winner = ranked[0]
            translation = str(winner.get("translation") or "").strip()
            if not translation:
                continue

            total = sum(int(v.get("count") or 0) for v in variants)
            winning = int(winner.get("count") or 0)
            # 判断依据是「获胜译法出现了几次」，不是总数。
            # 例：甲1次 / 乙1次，总数 2 看似够，但没有任何一方占优，
            # 这种情况写入术语表等于瞎猜。
            if winning < min_occurrences:
                plan.needs_review.append(
                    {
                        "original": original,
                        "category": category,
                        "verdict": verdict,
                        "reason": (
                            f"最高频译法仅出现 {winning} 次（共 {total} 次），"
                            "证据不足以自动判定"
                        ),
                        "variants": [v.get("translation") for v in variants],
                    }
                )
                continue

            plan.updates.append(
                GlossaryUpdate(
                    original=original,
                    translation=translation,
                    category=category,
                    reason="most_frequent",
                    winning_count=winning,
                    total_variants=len(ranked),
                    alternatives=[
                        str(v.get("translation") or "").strip()
                        for v in ranked[1:]
                        if str(v.get("translation") or "").strip()
                    ],
                )
            )
        else:
            # missing / deviating：无法判断是术语表错还是译文对，只提示不写入
            plan.needs_review.append(
                {
                    "original": original,
                    "category": category,
                    "verdict": verdict,
                    "reason": str(issue.get("detail") or "术语表译名未被使用"),
                    "expected": str(issue.get("expected") or ""),
                }
            )

    return plan


def apply_updates_to_terms(
    plan: GlossaryUpdatePlan,
    existing_terms: Optional[Dict[str, Any]],
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Merge a plan into an existing glossary term mapping.

    ``overwrite=False`` (default) keeps any entry the glossary already has, so a
    human-authored translation is never replaced by a statistical guess. Set it to
    True only when the caller has explicitly decided the scanner wins.

    Returns a new dict; the input is not mutated.
    """
    merged: Dict[str, Any] = {}
    if isinstance(existing_terms, dict):
        for category, entries in existing_terms.items():
            if isinstance(entries, list):
                merged[category] = [dict(e) if isinstance(e, dict) else e for e in entries]

    for update in plan.updates:
        category = update.category or "Item"
        bucket = merged.setdefault(category, [])
        if not isinstance(bucket, list):
            bucket = []
            merged[category] = bucket

        existing_index = None
        for index, entry in enumerate(bucket):
            if isinstance(entry, dict) and str(entry.get("original") or "").strip() == update.original:
                existing_index = index
                break

        if existing_index is not None:
            if not overwrite:
                # 已有条目（多半是人工整理的）优先，不覆盖
                continue
            bucket[existing_index] = {
                "original": update.original,
                "translation": update.translation,
                "source": "consistency_fix",
            }
        else:
            entry: Dict[str, Any] = {
                "original": update.original,
                "translation": update.translation,
                "source": "consistency_fix",
            }
            if update.alternatives:
                entry["aliases"] = list(update.alternatives)
            bucket.append(entry)

    return merged
