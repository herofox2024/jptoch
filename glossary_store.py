import json
from typing import Any, Dict, Iterable, List, Optional, Tuple


DEFAULT_GLOSSARY_CATEGORIES = ["Person", "Location", "Org", "Item", "Skill", "Creature"]


def normalize_glossary_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, int]]:
    normalized: Dict[str, List[Dict[str, str]]] = {c: [] for c in DEFAULT_GLOSSARY_CATEGORIES}
    stats = {"accepted": 0, "skipped": 0, "conflicts": 0}
    seen_by_original: Dict[str, str] = {}

    def _add_entry(src_raw: Any, dst_raw: Any, category: str = "Item", info_raw: Any = "", source_raw: Any = ""):
        src = str(src_raw).strip()
        dst = str(dst_raw).strip()
        info = str(info_raw).strip()
        source = str(source_raw).strip()
        if not src or not dst:
            stats["skipped"] += 1
            return
        if category not in DEFAULT_GLOSSARY_CATEGORIES:
            category = "Item"
        prev = seen_by_original.get(src)
        if prev is not None:
            if prev != dst:
                stats["conflicts"] += 1
            stats["skipped"] += 1
            return
        seen_by_original[src] = dst
        entry = {"original": src, "translation": dst}
        if info:
            entry["info"] = info
        if source:
            entry["source"] = source
        normalized[category].append(entry)
        stats["accepted"] += 1

    if not isinstance(payload, dict):
        return normalized, stats

    has_category_key = any(k in payload and isinstance(payload.get(k), list) for k in DEFAULT_GLOSSARY_CATEGORIES)
    if has_category_key:
        for category in DEFAULT_GLOSSARY_CATEGORIES:
            entries = payload.get(category, [])
            if not isinstance(entries, list):
                continue
            for item in entries:
                if not isinstance(item, dict):
                    stats["skipped"] += 1
                    continue
                src = item.get("original", item.get("src", ""))
                dst = item.get("translation", item.get("dst", ""))
                info = item.get("info", "")
                source = item.get("source", "")
                _add_entry(src, dst, category=category, info_raw=info, source_raw=source)
        return normalized, stats

    for src, value in payload.items():
        if isinstance(value, dict):
            dst = value.get("dst", value.get("translation", ""))
            info = value.get("info", "")
            source = value.get("source", "")
        else:
            dst = value
            info = ""
            source = ""
        _add_entry(src, dst, category="Item", info_raw=info, source_raw=source)

    return normalized, stats


def merge_glossaries(
    existing: Dict[str, List[Dict[str, str]]],
    incoming: Dict[str, List[Dict[str, str]]],
) -> Tuple[Dict[str, List[Dict[str, str]]], Dict[str, int]]:
    merged = {c: list(existing.get(c, [])) for c in DEFAULT_GLOSSARY_CATEGORIES}
    stats = {"added": 0, "skipped": 0, "conflicts": 0}
    seen: Dict[str, str] = {}
    for cat in DEFAULT_GLOSSARY_CATEGORIES:
        for entry in merged[cat]:
            original = str(entry.get("original", "")).strip()
            translation = str(entry.get("translation", "")).strip()
            if original and original not in seen:
                seen[original] = translation

    for cat in DEFAULT_GLOSSARY_CATEGORIES:
        for entry in incoming.get(cat, []):
            src = str(entry.get("original", entry.get("src", ""))).strip()
            dst = str(entry.get("translation", entry.get("dst", ""))).strip()
            if not src or not dst:
                stats["skipped"] += 1
                continue
            prev = seen.get(src)
            if prev is not None:
                if prev != dst:
                    stats["conflicts"] += 1
                stats["skipped"] += 1
                continue
            new_entry = {"original": src, "translation": dst}
            for k in ("info", "source"):
                if k in entry and entry[k]:
                    new_entry[k] = entry[k]
            merged[cat].append(new_entry)
            seen[src] = dst
            stats["added"] += 1
    return merged, stats


def clean_new_terms(raw_terms: List[dict]) -> List[Dict[str, Any]]:
    if not raw_terms:
        return []
    stop_words = {
        "我们", "你们", "他们", "这个", "那个", "这里", "那里", "然后", "但是", "因为", "所以",
        "可以", "不会", "已经", "正在", "没有", "非常", "真的", "老师", "学校", "城市", "国家",
        "魔法", "剑", "勇者", "魔王", "世界", "时间", "地方", "事情", "东西", "样子",
        "之后", "之前", "起来", "下去", "出来", "进去", "回来", "过来",
    }
    category_map = {
        "person": "Person", "角色": "Person", "人物": "Person",
        "location": "Location", "地点": "Location", "场所": "Location",
        "org": "Org", "organization": "Org", "组织": "Org", "团体": "Org",
        "item": "Item", "物品": "Item", "装备": "Item", "道具": "Item",
        "skill": "Skill", "技能": "Skill", "招式": "Skill", "魔法": "Skill",
        "creature": "Creature", "生物": "Creature", "怪物": "Creature", "宠物": "Creature",
    }
    cleaned: List[Dict[str, Any]] = []
    seen = set()
    for item in raw_terms:
        if not isinstance(item, dict):
            continue
        src = str(item.get("src", item.get("original", ""))).strip()
        dst = str(item.get("dst", item.get("translation", ""))).strip()
        raw_category = item.get("category", item.get("cat", ""))
        info = str(item.get("info", "")).strip()
        source = str(item.get("source", "auto")).strip() or "auto"
        if not src or not dst or len(src) < 2 or len(dst) < 2:
            continue
        if src in stop_words or dst in stop_words:
            continue
        category = "Item"
        if raw_category:
            normalized = str(raw_category).lower().strip()
            category = category_map.get(normalized, raw_category if raw_category in DEFAULT_GLOSSARY_CATEGORIES else "Item")
        key = (src, dst)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"src": src, "dst": dst, "category": category, "info": info, "source": source})
    return cleaned


def _is_katakana_boundary_char(ch: str) -> bool:
    if not ch:
        return False
    code = ord(ch)
    return (
        0x30A0 <= code <= 0x30FF
        or 0x31F0 <= code <= 0x31FF
        or 0xFF66 <= code <= 0xFF9F
        or ch == "\u30fc"
    )


def _has_katakana_boundary_char(text: str) -> bool:
    return any(_is_katakana_boundary_char(ch) for ch in text or "")


def _valid_katakana_term_boundary(context_text: str, original: str, start: int, end: int) -> bool:
    if not _has_katakana_boundary_char(original):
        return True
    if original and _is_katakana_boundary_char(original[0]):
        if start > 0 and _is_katakana_boundary_char(context_text[start - 1]):
            return False
    if original and _is_katakana_boundary_char(original[-1]):
        if end < len(context_text) and _is_katakana_boundary_char(context_text[end]):
            return False
    return True


def find_glossary_match_spans(context_text: str, original: str) -> List[Tuple[int, int]]:
    context_text = str(context_text or "")
    original = str(original or "").strip()
    if not context_text or not original:
        return []

    spans: List[Tuple[int, int]] = []
    pos = 0
    while True:
        start = context_text.find(original, pos)
        if start < 0:
            break
        end = start + len(original)
        if _valid_katakana_term_boundary(context_text, original, start, end):
            spans.append((start, end))
        pos = start + 1
    return spans


def has_valid_glossary_match(context_text: str, original: str) -> bool:
    return bool(find_glossary_match_spans(context_text, original))


def _iter_glossary_candidates(
    glossary_snapshot: Dict[str, Any],
    categories: List[str],
) -> Iterable[Tuple[str, str, str]]:
    is_categorized = any(key in glossary_snapshot and isinstance(glossary_snapshot.get(key), list) for key in categories)
    if is_categorized:
        for category in categories:
            entries = glossary_snapshot.get(category, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                original = str(entry.get("original", entry.get("src", ""))).strip()
                translation = str(entry.get("translation", entry.get("dst", ""))).strip()
                source = str(entry.get("source", "")).strip()
                if original and translation:
                    yield original, translation, source
        return

    for k, v in glossary_snapshot.items():
        original = str(k).strip()
        if not original:
            continue
        if isinstance(v, dict):
            translation = str(v.get("dst", v.get("translation", ""))).strip()
            source = str(v.get("source", "")).strip()
        else:
            translation = str(v).strip()
            source = ""
        if translation:
            yield original, translation, source


def _spans_overlap(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _select_matched_candidates(
    context_text: str,
    candidates: Iterable[Tuple[str, str, str]],
    max_terms: int,
) -> List[Dict[str, str]]:
    matched = []
    seen_original = set()
    for original, translation, source in candidates:
        original = str(original).strip()
        translation = str(translation).strip()
        source = str(source or "").strip()
        if not original or not translation or original in seen_original:
            continue
        spans = find_glossary_match_spans(context_text, original)
        if not spans:
            continue
        seen_original.add(original)
        matched.append((original, translation, source, spans))

    matched.sort(key=lambda item: (-len(item[0]), item[3][0][0], item[0]))

    selected: List[Dict[str, str]] = []
    selected_spans: List[Tuple[int, int]] = []
    for original, translation, source, spans in matched:
        span = next(
            (s for s in spans if not any(_spans_overlap(s, selected_span) for selected_span in selected_spans)),
            None,
        )
        if span is None:
            continue
        item = {"original": original, "translation": translation}
        if source:
            item["source"] = source
        selected.append(item)
        selected_spans.append(span)
        if len(selected) >= max_terms:
            break
    return selected


def rebuild_glossary_index(glossary: Dict[str, Any], categories: Optional[List[str]] = None) -> Dict[str, List[Tuple[str, str, str]]]:
    categories = categories or DEFAULT_GLOSSARY_CATEGORIES
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    seen_original = set()
    is_categorized = any(key in glossary and isinstance(glossary.get(key), list) for key in categories)

    def _add(original: str, translation: str, source: str = "") -> None:
        original = str(original).strip()
        translation = str(translation).strip()
        source = str(source or "").strip()
        if not original or not translation or original in seen_original:
            return
        seen_original.add(original)
        index.setdefault(original[0], []).append((original, translation, source))

    if is_categorized:
        for category in categories:
            entries = glossary.get(category, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                _add(
                    entry.get("original", entry.get("src", "")),
                    entry.get("translation", entry.get("dst", "")),
                    entry.get("source", ""),
                )
    else:
        for k, v in glossary.items():
            if isinstance(v, dict):
                translation = v.get("dst", v.get("translation", ""))
                source = v.get("source", "")
            else:
                translation = v
                source = ""
            _add(k, translation, source)

    for entries in index.values():
        entries.sort(key=lambda item: len(item[0]), reverse=True)
    return index


def select_glossary_entries(
    context_text: str,
    glossary_snapshot: Dict[str, Any],
    categories: List[str],
    max_terms: int,
    glossary_index: Optional[Dict[str, List[Tuple[str, str, str]]]] = None,
) -> List[Dict[str, str]]:
    context_text = str(context_text or "")
    if not context_text or max_terms <= 0:
        return []

    if glossary_index:
        candidates: List[Tuple[str, str, str]] = []
        seen_candidate = set()
        for first_char in dict.fromkeys(context_text):
            indexed = glossary_index.get(first_char)
            if not indexed:
                continue
            for original, translation, source in indexed:
                if original in seen_candidate:
                    continue
                seen_candidate.add(original)
                candidates.append((original, translation, source))
        return _select_matched_candidates(context_text, candidates, max_terms)

    return _select_matched_candidates(
        context_text,
        _iter_glossary_candidates(glossary_snapshot, categories),
        max_terms,
    )


def build_glossary_text(
    glossary_snapshot: Dict[str, Any],
    categories: List[str],
    selected_entries: Optional[List[Dict[str, str]]] = None,
) -> str:
    if selected_entries is not None:
        if not selected_entries:
            return "无术语表。"
        lines = []
        for item in selected_entries:
            original = str(item.get("original", "")).strip()
            translation = str(item.get("translation", "")).strip()
            if original and translation:
                lines.append(f"{original}->{translation}")
        return "\n".join(lines) if lines else "无术语表。"

    if not glossary_snapshot:
        return "无术语表。"
    lines = []
    is_categorized = any(key in glossary_snapshot and isinstance(glossary_snapshot.get(key), list) for key in categories)
    if is_categorized:
        for category in categories:
            entries = glossary_snapshot.get(category, [])
            if not isinstance(entries, list) or not entries:
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                original = entry.get("original", entry.get("src", ""))
                translation = entry.get("translation", entry.get("dst", ""))
                if original and translation:
                    lines.append(f"{original}->{translation}")
    else:
        for k, v in glossary_snapshot.items():
            if isinstance(v, dict):
                dst = str(v.get("dst", "")).strip()
                info = str(v.get("info", "")).strip()
                if dst and info:
                    lines.append(f"{k}->{dst} #{info}")
                elif dst:
                    lines.append(f"{k}->{dst}")
                else:
                    lines.append(f"{k} => {json.dumps(v, ensure_ascii=False)}")
            else:
                lines.append(f"{k} => {v}")
    return "\n".join(lines) if lines else "无术语表。"
