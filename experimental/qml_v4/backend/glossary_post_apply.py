# -*- coding: utf-8 -*-
"""Apply selected glossary terms to an already translated EPUB.

This is intentionally conservative: it replaces exact source-side glossary
terms that still appear in the translated EPUB, then writes a new EPUB copy and
a report. It does not try to guess or rewrite inconsistent Chinese synonyms.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from bs4 import NavigableString, Tag

from epub_io import (
    HIDDEN_TEXT_TAGS,
    apply_toc_translations,
    extract_toc_titles,
    iter_text_nodes,
    load_book,
    save_book,
    set_book_title_metadata,
)
from glossary_store import (
    DEFAULT_GLOSSARY_CATEGORIES,
    find_glossary_match_spans,
    normalize_aliases,
    normalize_glossary_payload,
    normalize_policy,
)
from translation_cache import load_json_file

logger = logging.getLogger(__name__)


def _empty_glossary() -> Dict[str, List[Dict[str, str]]]:
    return {category: [] for category in DEFAULT_GLOSSARY_CATEGORIES}


def _safe_stem(value: str) -> str:
    stem = Path(str(value or "epub")).stem.strip() or "epub"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip(" ._")[:96] or "epub"


def _unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def glossary_apply_report_dir() -> Path:
    from translator import get_data_dir

    path = get_data_dir() / "glossary_apply_reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_effective_glossary(config: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, Any]]:
    """Resolve the same glossary selection that translation uses."""
    cfg = dict(config or {})
    if not bool(cfg.get("enable_glossary", True)):
        return _empty_glossary(), {"source": "disabled", "profile_ids": [], "profile_count": 0}

    from translator import get_data_dir

    data_dir = get_data_dir()
    meta: Dict[str, Any] = {"source": "global", "profile_ids": [], "profile_count": 0}

    configured_ids = [
        str(item or "").strip()
        for item in (cfg.get("glossary_profile_ids") or [])
        if str(item or "").strip()
    ]
    if bool(cfg.get("enable_layered_glossary", False)) or configured_ids:
        from .pipeline import PipelineContext, _build_glossary_override

        ctx = PipelineContext(
            config=cfg,
            extra={"title": Path(str(cfg.get("inp") or cfg.get("out") or "")).name},
        )
        merged, fingerprint = _build_glossary_override(ctx)
        meta = {
            "source": "layered",
            "profile_ids": list(ctx.extra.get("glossary_profile_ids") or []),
            "profile_count": len(ctx.extra.get("glossary_profile_ids") or []),
            "fingerprint": fingerprint,
            "merge_stats": dict(ctx.extra.get("glossary_merge_stats") or {}),
        }
        if merged is not None:
            normalized, _ = normalize_glossary_payload(merged)
            return normalized, meta
        if not bool(cfg.get("use_global_glossary", True)):
            return _empty_glossary(), meta

    normalized, _ = normalize_glossary_payload(load_json_file(data_dir / "glossary.json", {}))
    return normalized, meta


def flatten_replacement_terms(glossary: Dict[str, Any]) -> List[Dict[str, str]]:
    normalized, _ = normalize_glossary_payload(glossary or {})
    terms: List[Dict[str, str]] = []
    seen = set()

    def _add_match(match: str, translation: str, *, category: str, policy: str, original: str, kind: str) -> None:
        match = str(match or "").strip()
        translation = str(translation or "").strip()
        if not match or not translation or match == translation:
            return
        if len(match) < 2:
            return
        key = (match, translation)
        if key in seen:
            return
        seen.add(key)
        terms.append(
            {
                "match": match,
                "original": original,
                "translation": translation,
                "category": category,
                "policy": policy,
                "kind": kind,
            }
        )

    for category in DEFAULT_GLOSSARY_CATEGORIES:
        for entry in normalized.get(category, []):
            if not isinstance(entry, dict):
                continue
            original = str(entry.get("original", "")).strip()
            translation = str(entry.get("translation", "")).strip()
            policy = normalize_policy(entry.get("policy", entry.get("enforcement", "")))
            if not original or not translation or original == translation:
                continue
            if policy in {"ignore", "preserve"}:
                continue
            _add_match(original, translation, category=category, policy=policy, original=original, kind="source")
            for alias in normalize_aliases(entry.get("aliases")):
                if alias in {original, translation}:
                    continue
                _add_match(alias, translation, category=category, policy=policy, original=original, kind="alias")
    terms.sort(key=lambda item: (-len(item["match"]), item["match"], item["translation"]))
    return terms


def apply_terms_to_text(text: str, terms: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, Any]]]:
    value = str(text or "")
    changes: List[Dict[str, Any]] = []
    if not value or not terms:
        return value, changes

    for term in terms:
        match = term.get("match") or term["original"]
        translation = term["translation"]
        spans = find_glossary_match_spans(value, match)
        if not spans:
            continue
        for start, end in reversed(spans):
            value = value[:start] + translation + value[end:]
        changes.append(
            {
                "match": match,
                "original": term.get("original", match),
                "translation": translation,
                "category": term.get("category", "Item"),
                "kind": term.get("kind", "source"),
                "count": len(spans),
            }
        )
    return value, changes


def _iter_visible_string_nodes(tag: Tag):
    # Replacements mutate the BeautifulSoup tree, so callers need a stable
    # snapshot instead of a live descendants iterator.
    for node in list(tag.descendants):
        if not isinstance(node, NavigableString):
            continue
        hidden = False
        for parent in node.parents:
            if isinstance(parent, Tag) and parent.name in HIDDEN_TEXT_TAGS:
                hidden = True
                break
            if parent is tag:
                break
        if not hidden:
            yield node


def _write_report(payload: Dict[str, Any]) -> Tuple[str, str]:
    report_dir = glossary_apply_report_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = _safe_stem(payload.get("output_path") or payload.get("input_path") or "epub")
    json_path = report_dir / f"{stamp}-{stem}-glossary-apply.json"
    text_path = report_dir / f"{stamp}-{stem}-glossary-apply.txt"
    payload = dict(payload)
    payload["text_report_path"] = str(text_path)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "EPUB Glossary Apply Report",
        f"created_at: {payload.get('created_at', '')}",
        f"input_path: {payload.get('input_path', '')}",
        f"output_path: {payload.get('output_path', '')}",
        f"terms: {payload.get('term_count', 0)}",
        f"replacements: {payload.get('replacement_total', 0)}",
        f"changed_documents: {payload.get('changed_documents', 0)}",
        "",
        "Samples",
    ]
    samples = payload.get("samples") or []
    if not samples:
        lines.append("- none")
    else:
        for sample in samples:
            source = sample.get("match") or sample.get("original", "")
            lines.append(
                "- {file}: {source} -> {translation} ({count})".format(
                    file=sample.get("file", "-"),
                    source=source,
                    translation=sample.get("translation", ""),
                    count=sample.get("count", 0),
                )
            )
    text_path.write_text("\n".join(lines), encoding="utf-8")
    return str(json_path), str(text_path)


def apply_glossary_to_epub(
    input_path: str,
    glossary: Dict[str, Any],
    *,
    output_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Dict[str, Any]:
    source_path = Path(str(input_path or "")).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"EPUB 文件不存在: {source_path}")

    terms = flatten_replacement_terms(glossary)
    if not terms:
        logger.info("术语后处理跳过: 当前术语范围没有可用于替换的术语, input=%s", source_path)
        return {
            "ok": False,
            "message": "当前术语范围没有可用于后处理替换的术语",
            "input_path": str(source_path),
            "output_path": "",
            "term_count": 0,
            "replacement_total": 0,
            "changed_documents": 0,
            "samples": [],
        }

    book = load_book(str(source_path))
    docs = list(iter_text_nodes(book))
    total_units = max(1, len(docs) + 2)
    completed_units = 0

    def _emit_progress() -> None:
        if progress_callback:
            progress_callback(completed_units, total_units)

    _emit_progress()
    replacement_total = 0
    changed_documents = 0
    samples: List[Dict[str, Any]] = []
    aggregate = defaultdict(int)

    for item, soup, tags in docs:
        item_changed = False
        seen_nodes = set()
        file_name = str(getattr(item, "file_name", "") or "?")
        for tag in tags:
            if not isinstance(tag, Tag):
                continue
            for node in _iter_visible_string_nodes(tag):
                node_id = id(node)
                if node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                old_text = str(node)
                new_text, changes = apply_terms_to_text(old_text, terms)
                if new_text == old_text:
                    continue
                node.replace_with(NavigableString(new_text))
                item_changed = True
                for change in changes:
                    count = int(change.get("count") or 0)
                    replacement_total += count
                    source_text = change.get("match") or change["original"]
                    key = (file_name, source_text, change["translation"])
                    aggregate[key] += count
                    if len(samples) < 30:
                        samples.append(
                            {
                                "file": file_name,
                                "original": change["original"],
                                "match": source_text,
                                "translation": change["translation"],
                                "kind": change.get("kind", "source"),
                                "count": count,
                            }
                        )
        if item_changed:
            item.set_content(str(soup).encode("utf-8"))
            changed_documents += 1
        completed_units += 1
        _emit_progress()

    toc_map = {}
    for title in extract_toc_titles(book):
        new_title, changes = apply_terms_to_text(title, terms)
        if new_title != title:
            toc_map[title] = new_title
            for change in changes:
                count = int(change.get("count") or 0)
                replacement_total += count
                source_text = change.get("match") or change["original"]
                key = ("toc", source_text, change["translation"])
                aggregate[key] += count
                if len(samples) < 30:
                    samples.append(
                        {
                            "file": "toc",
                            "original": change["original"],
                            "match": source_text,
                            "translation": change["translation"],
                            "kind": change.get("kind", "source"),
                            "count": count,
                        }
                    )
    if toc_map:
        apply_toc_translations(book, toc_map)
    completed_units += 1
    _emit_progress()

    try:
        metadata_titles = book.get_metadata("DC", "title") or []
        if metadata_titles:
            current_title = str(metadata_titles[0][0] or "").strip()
            new_title, changes = apply_terms_to_text(current_title, terms)
            if new_title and new_title != current_title:
                set_book_title_metadata(book, new_title)
                for change in changes:
                    count = int(change.get("count") or 0)
                    replacement_total += count
                    source_text = change.get("match") or change["original"]
                    key = ("metadata:title", source_text, change["translation"])
                    aggregate[key] += count
    except Exception:
        pass

    if replacement_total <= 0:
        completed_units = total_units
        _emit_progress()
        logger.info(
            "术语后处理未匹配: input=%s, terms=%s, changed_documents=0",
            source_path,
            len(terms),
        )
        return {
            "ok": False,
            "message": "没有在已翻译 EPUB 中匹配到需要替换的术语原文或中文别名",
            "input_path": str(source_path),
            "output_path": "",
            "term_count": len(terms),
            "replacement_total": 0,
            "changed_documents": 0,
            "samples": [],
        }

    out_path = Path(output_path) if output_path else source_path.with_name(f"{source_path.stem}_glossary_fixed.epub")
    out_path = _unique_output_path(out_path)
    save_book(str(out_path), book, chinese_mode=True)
    completed_units = total_units
    _emit_progress()

    report_payload = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "input_path": str(source_path),
        "output_path": str(out_path),
        "term_count": len(terms),
        "replacement_total": replacement_total,
        "changed_documents": changed_documents,
        "samples": samples,
        "aggregate": [
            {"file": file_name, "original": original, "translation": translation, "count": count}
            for (file_name, original, translation), count in sorted(aggregate.items())
        ],
    }
    report_path, text_report_path = _write_report(report_payload)
    sample_text = " | ".join(
        f"{item.get('match') or item.get('original')}->{item.get('translation')}({item.get('count')})"
        for item in samples[:8]
    )
    logger.info(
        "术语后处理完成: input=%s, output=%s, 替换 %s 处, 变更文档 %s 个, 术语候选 %s 条, 报告=%s%s",
        source_path,
        out_path,
        replacement_total,
        changed_documents,
        len(terms),
        report_path,
        f", 样例: {sample_text}" if sample_text else "",
    )
    return {
        "ok": True,
        "message": f"术语后处理完成: 替换 {replacement_total} 处，输出 {out_path.name}",
        "input_path": str(source_path),
        "output_path": str(out_path),
        "report_path": report_path,
        "text_report_path": text_report_path,
        "term_count": len(terms),
        "replacement_total": replacement_total,
        "changed_documents": changed_documents,
        "samples": samples,
    }
