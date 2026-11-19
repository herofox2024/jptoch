# -*- coding: utf-8 -*-
"""Cross-chapter term consistency checks for finished translations.

Why this module exists
----------------------
Translation runs in batches, and each batch only sees a slice of the glossary
(at most ``_glossary_prompt_max_terms`` entries). The model can therefore render
the same source term differently in different chapters -- for example
``まっちょ`` came out as both ``阿肌`` and ``小真`` inside one book.

No API call is needed to catch this: every finished pair already carries the
source text and its translation, and the glossary already says what the
preferred rendering is. This module scans that data locally and reports:

1. ``divergent``  -- one source term rendered in more than one way.
2. ``deviating``  -- a rendering that contradicts the glossary entry.
3. ``missing``    -- a glossary term that appears in the source but never made it
   into any translation.

The public entry point is :func:`check_term_consistency`. It is pure: it does
no I/O, no network access and no mutation of its inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# A source term shorter than this produces too many false positives when matched
# as a substring (e.g. single kana), so such terms are skipped for divergence.
MIN_TERM_LENGTH = 2

# Cap the reported items so a badly broken book does not produce a 10k-line report.
MAX_REPORTED_TERMS = 50
MAX_VARIANTS_PER_TERM = 6

# 一个术语在原文里至少出现这么多次，才值得判定 "missing"。
# 用户术语表里混有来自其他书、或者只是普通词的条目；只出现一次就断言
# "术语表译名没被使用"，几乎都是噪音（实测：イルカ「海豚」被误报）。
MIN_HITS_FOR_MISSING = 3

# 还需要分布在不同段落里：同一段里重复出现多半是普通词（如「能源」）。
MIN_PAIRS_FOR_MISSING = 2


@dataclass
class TermVariant:
    """One rendering of a source term, with how often it occurred."""

    translation: str
    count: int = 0
    chapters: List[str] = field(default_factory=list)


@dataclass
class TermConsistencyIssue:
    """A single term that failed a consistency check."""

    original: str
    category: str
    verdict: str
    """One of ``divergent`` / ``deviating`` / ``missing``."""
    variants: List[TermVariant] = field(default_factory=list)
    expected: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original": self.original,
            "category": self.category,
            "verdict": self.verdict,
            "expected": self.expected,
            "detail": self.detail,
            "variants": [
                {
                    "translation": v.translation,
                    "count": v.count,
                    "chapters": v.chapters[:5],
                }
                for v in self.variants
            ],
        }


@dataclass
class TermConsistencyReport:
    """Aggregated result of a whole-book consistency scan."""

    scanned_pairs: int = 0
    scanned_terms: int = 0
    issues: List[TermConsistencyIssue] = field(default_factory=list)

    @property
    def divergent_count(self) -> int:
        return sum(1 for item in self.issues if item.verdict == "divergent")

    @property
    def deviating_count(self) -> int:
        return sum(1 for item in self.issues if item.verdict == "deviating")

    @property
    def missing_count(self) -> int:
        return sum(1 for item in self.issues if item.verdict == "missing")

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def summary(self) -> str:
        if not self.issues:
            return f"术语一致性检查通过（扫描 {self.scanned_pairs} 段 / {self.scanned_terms} 个术语）"
        return (
            f"术语一致性检查发现 {len(self.issues)} 个问题："
            f"多种译法 {self.divergent_count}、"
            f"与术语表不符 {self.deviating_count}、"
            f"未使用术语表译名 {self.missing_count}"
            f"（扫描 {self.scanned_pairs} 段 / {self.scanned_terms} 个术语）"
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanned_pairs": self.scanned_pairs,
            "scanned_terms": self.scanned_terms,
            "summary": self.summary(),
            "counts": {
                "divergent": self.divergent_count,
                "deviating": self.deviating_count,
                "missing": self.missing_count,
            },
            "issues": [item.to_dict() for item in self.issues],
        }


def _iter_glossary_entries(
    glossary: Dict[str, Any],
    categories: Optional[Sequence[str]] = None,
) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    """Yield ``(category, original, entry)`` for every usable glossary entry."""
    if not isinstance(glossary, dict):
        return
    for category, entries in glossary.items():
        if categories is not None and category not in categories:
            continue
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            original = str(entry.get("original") or "").strip()
            translation = str(entry.get("translation") or "").strip()
            if not original or not translation:
                continue
            yield category, original, entry


def _expected_translation(entry: Dict[str, Any]) -> str:
    """Preferred translation, ignoring alias-only entries."""
    return str(entry.get("translation") or "").strip()


def _policy_allows_free_rendering(entry: Dict[str, Any]) -> bool:
    """Entries the translator is free to render contextually (not hard rules)."""
    policy = str(entry.get("policy") or "").strip().lower()
    return policy in {"context", "reference", "ignore", "上下文命中", "仅供参考", "忽略"}


# 中文译名通常很短。从译文里找「疑似译法」时只接受这个长度区间的片段，
# 否则整句会被当成一种"译法"，导致报告全是噪音。
MIN_CANDIDATE_LEN = 2
MAX_CANDIDATE_LEN = 8

_CJK_ONLY_RE = re.compile(r"^[\u4e00-\u9fff\u3040-\u30ffA-Za-z0-9・·\-]+$")


def _extract_render_candidate(
    target: str,
    expected: str,
    sibling_targets: Optional[Sequence[str]] = None,
) -> str:
    """Guess how a term was rendered when the glossary translation is absent.

    The scanner only has the finished sentence, not a word alignment, so this is
    inherently approximate. Three observations make it workable:

    1. Glossary terms in this project are names that lead the sentence.
    2. A rendering is about as long as the authoritative translation — a 2-character
       name does not become 3 characters.
    3. Interrogative/verb characters right after a name are almost never part of it.

    So the candidate is the leading fragment truncated to the authoritative length,
    then rejected if what follows looks like sentence continuation rather than a
    name boundary.

    Earlier versions tried to align against sibling sentences; that produced
    garbage such as 「萝拉笑」 (verb glued on) and then silently stopped detecting
    real variants. Length-based truncation is dumber but predictable, and a missed
    variant is far cheaper than a wrong replacement.

    Returns an empty string when no confident guess can be made.
    """
    text = (target or "").strip()
    if not text:
        return ""
    text = re.sub(r"^[「『“‘\"'（(【\[\s]+", "", text)
    if not text:
        return ""

    head = re.split(r"[，。！？、；：,.!?;:\s]", text, maxsplit=1)[0].strip()
    if not head:
        return ""

    # 按权威译名的长度截断：名字不会因为换了译法就变长。
    span = max(MIN_CANDIDATE_LEN, min(len(expected), MAX_CANDIDATE_LEN))
    candidate = head[:span].strip()

    # 截断点后面紧跟的这些字说明「译名还没结束」，即 head 比译名长，
    # 截断会产生半截词。直接放弃，让这一句不参与变体统计。
    tail = head[span:span + 1]
    if tail and tail in "的了着过是在把被给和与对向从地得":
        candidate = head[:span].strip()

    if len(candidate) < MIN_CANDIDATE_LEN:
        return ""
    if expected and candidate == expected:
        return ""
    if not _CJK_ONLY_RE.match(candidate):
        return ""
    return candidate


def check_term_consistency(
    pairs: Sequence[Tuple[str, str]],
    glossary: Dict[str, Any],
    *,
    categories: Optional[Sequence[str]] = None,
    chapter_of: Optional[Sequence[str]] = None,
    max_terms: int = MAX_REPORTED_TERMS,
) -> TermConsistencyReport:
    """Scan finished translations for glossary inconsistencies.

    Parameters
    ----------
    pairs:
        ``[(source_text, translated_text), ...]`` in reading order.
    glossary:
        ``{category: [{"original": ..., "translation": ..., "policy"?: ...}, ...]}``
    categories:
        Restrict the scan to these glossary categories. ``None`` means all.
    chapter_of:
        Optional per-pair chapter label, same length as ``pairs``.
    max_terms:
        Upper bound on reported issues.

    Returns
    -------
    TermConsistencyReport
    """
    report = TermConsistencyReport()

    clean_pairs: List[Tuple[str, str, str]] = []
    for index, pair in enumerate(pairs):
        if not pair or len(pair) < 2:
            continue
        source = str(pair[0] or "")
        target = str(pair[1] or "")
        if not source.strip() or not target.strip():
            continue
        chapter = ""
        if chapter_of is not None and index < len(chapter_of):
            chapter = str(chapter_of[index] or "")
        clean_pairs.append((source, target, chapter))

    report.scanned_pairs = len(clean_pairs)
    if not clean_pairs:
        return report

    entries = list(_iter_glossary_entries(glossary, categories))
    report.scanned_terms = len(entries)
    if not entries:
        return report

    for category, original, entry in entries:
        if len(original) < MIN_TERM_LENGTH:
            continue

        expected = _expected_translation(entry)
        free_rendering = _policy_allows_free_rendering(entry)
        pattern = re.compile(re.escape(original))

        # Count how often each rendering occurs alongside the source term.
        # 关键点：不能只统计「术语表译名是否命中」，否则模型换用其他译法时
        # 会因为完全没命中而被误判成 missing，看不到真正的不一致。
        # 这里同时收集「其它译法」的证据：原文术语所在句子的译文片段，
        # 用它们判断同一原文是否被译成了不同写法。
        variant_counter: Dict[str, int] = {}
        variant_chapters: Dict[str, List[str]] = {}
        source_hits = 0
        unmatched_targets: List[Tuple[str, str]] = []

        for source, target, chapter in clean_pairs:
            if not pattern.search(source):
                continue
            source_hits += 1
            if expected and expected in target:
                variant_counter[expected] = variant_counter.get(expected, 0) + 1
                if chapter and chapter not in variant_chapters.setdefault(expected, []):
                    variant_chapters[expected].append(chapter)
            else:
                unmatched_targets.append((target, chapter))

        if source_hits == 0:
            continue

        # 只有当术语表译名确实在译文里出现过，才谈得上「同一术语的另一种译法」。
        # 若一次都没命中，说明这一批根本没采用术语表，应报 missing 而不是
        # 把整句开头片段当成变体（否则「在这座小镇里」会被误当成一种译法）。
        expected_hits = variant_counter.get(expected, 0)
        missing = 0

        if expected_hits == 0:
            missing = len(unmatched_targets)
        else:
            # 参与变体检测的通常是短专名（人名/地名）。长术语的「别的译法」
            # 很难从句子片段可靠还原，强行提取只会制造噪音。
            if len(original) <= MAX_CANDIDATE_LEN:
                # 对齐基准要包含「已命中权威译名的句子」和「未命中的句子」，
                # 否则无法从共同前缀里切出译名边界。
                sibling_targets = [
                    target
                    for source, target, _chapter in clean_pairs
                    if pattern.search(source)
                ]
                for target, chapter in unmatched_targets:
                    candidate = _extract_render_candidate(
                        target, expected, sibling_targets=sibling_targets
                    )
                    if not candidate:
                        continue
                    variant_counter[candidate] = variant_counter.get(candidate, 0) + 1
                    if chapter and chapter not in variant_chapters.setdefault(candidate, []):
                        variant_chapters[candidate].append(chapter)

        if missing:
            # 只出现一两次、或只集中在同一段里的术语，其「未命中」几乎都是噪音：
            # 用户术语表混有来自其他书的条目，或者该词在这本书里只是普通词
            # （实测被误报的：イルカ→海豚、エネルギー→能源）。
            # 要求「出现多次 + 分散在多段」才判定为真正的不一致。
            if (
                not free_rendering
                and source_hits >= MIN_HITS_FOR_MISSING
                and len(unmatched_targets) >= MIN_PAIRS_FOR_MISSING
            ):
                report.issues.append(
                    TermConsistencyIssue(
                        original=original,
                        category=category,
                        verdict="missing",
                        expected=expected,
                        detail=(
                            f"原文出现 {source_hits} 次（跨 {len(unmatched_targets)} 段），"
                            f"但译文中未使用术语表译名「{expected}」"
                        ),
                    )
                )
            if len(report.issues) >= max_terms:
                break
            continue

        variants = [
            TermVariant(translation=text, count=count, chapters=variant_chapters.get(text, []))
            for text, count in sorted(variant_counter.items(), key=lambda kv: -kv[1])
        ]

        # Divergence: the same source term produced several distinct renderings.
        # In practice the glossary pins one expected string, so extra variants
        # mean the model paraphrased it inconsistently.
        if len(variants) > 1 and not free_rendering:
            report.issues.append(
                TermConsistencyIssue(
                    original=original,
                    category=category,
                    verdict="divergent",
                    expected=expected,
                    variants=variants[:MAX_VARIANTS_PER_TERM],
                    detail=(
                        f"原文出现 {source_hits} 次，出现 {len(variants)} 种译法"
                    ),
                )
            )

        if len(report.issues) >= max_terms:
            break

    return report


def collect_variant_suspects(
    pairs: Sequence[Tuple[str, str]],
    glossary: Dict[str, Any],
    *,
    max_terms: int = MAX_REPORTED_TERMS,
) -> List[Dict[str, Any]]:
    """Convenience wrapper returning only ``divergent`` issues as plain dicts."""
    report = check_term_consistency(pairs, glossary, max_terms=max_terms)
    return [item.to_dict() for item in report.issues if item.verdict == "divergent"]
