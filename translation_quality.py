# -*- coding: utf-8 -*-
"""Local translation quality heuristics and Japanese residue detection."""

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


logger = logging.getLogger(__name__)

JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
JAPANESE_KANA_FRAGMENT_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]+")
JAPANESE_QUOTED_TEXT_RE = re.compile(r"[「『“\"'（(【\[]\s*([^\r\n]{1,80}?)\s*[」』”\"'）)】\]]")
JAPANESE_SHORT_QUOTED_TEXT_RE = re.compile(r"^[「『“\"'（(【\[]\s*([^\r\n]{1,6}?)\s*[」』”\"'）)】\]]$")
JAPANESE_SINGLE_KATAKANA_RE = re.compile(r"^[\u30a0-\u30ff\uff66-\uff9f]$")
JAPANESE_O_NAME_PREFIX_RE = re.compile(r"お[\u3400-\u9fff々]{1,3}(?![\u3400-\u9fff々])")
JAPANESE_O_PREFIX_NON_PERSON_STEMS = {
    "茶", "金", "酒", "湯", "水", "米", "菓子", "店", "客", "宅", "礼",
    "話", "願", "詫", "前", "母", "父", "兄", "姉", "祖母", "祖父",
    "嬢", "姫", "寺", "盆", "祭", "守", "札", "膳", "椀", "箸",
    "上", "役", "家", "国", "城", "蔵", "手", "腹", "目", "顔", "心",
    "足", "口", "腰", "命",
}
JAPANESE_RESIDUE_ALLOWLIST_FILE = "japanese_residue_allowlist.json"
KNOWN_KATAKANA_TERMS_FILE = "known_katakana_terms.json"
DEFAULT_KNOWN_KATAKANA_TERMS: Dict[str, str] = {
    "チロリ": "烫酒壶",
}
ALLOWED_JAPANESE_SHAPE_NOTATION_RE = re.compile(
    r"[「『“\"'（(【\[]?\s*[\u30a0-\u30ff\uff66-\uff9f]\s*[」』”\"'）)】\]]?\s*(?:の\s*)?(?:字形|字型|字状|形|型|状|字)"
)
ALLOWED_LATIN_MIDDLE_DOT_RE = re.compile(r"(?<=[A-Za-z0-9])・(?=[A-Za-z0-9])")
JAPANESE_EXPLANATORY_QUOTE_CUE_RE = re.compile(
    r"(?:说法|所谓|写作|写成|写出来|读作|读成|发音|原文|日文|词语|词|意思|叫做|称作|表示)"
)
JAPANESE_READING_PUZZLE_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9])[\u30a0-\u30ff\uff66-\uff9f](?:[、,，・･\s]*[\u30a0-\u30ff\uff66-\uff9f]){2,}(?![A-Za-z0-9])"
)
JAPANESE_READING_PUZZLE_CONTEXT_RE = re.compile(
    r"(?:首音|读|讀|发音|發音|音读|音讀|读音|讀音|拼读|拼讀|"
    r"左往右|右往左|从左|從左|从右|從右|横排|橫排|竖排|豎排|"
    r"连起来|連起來|串字符|字符|字串|片假名|假名|暗号|谜题|謎題|谜面|謎面|藏头|藏尾)"
)

_allowlist_cache: Optional[Dict[str, Any]] = None
_allowlist_mtime: Optional[float] = None
_allowlist_checked_at = 0.0
_allowlist_check_interval = 5.0
_known_terms_cache: Optional[Dict[str, str]] = None
_known_terms_mtime: Optional[float] = None
_known_terms_checked_at = 0.0
_known_terms_check_interval = 5.0
_data_dir_provider: Optional[Callable[[], Path]] = None


def configure_data_dir(provider: Callable[[], Path]) -> None:
    """Set the app data-dir provider used by the user-editable allowlist."""
    global _data_dir_provider
    global _allowlist_cache, _allowlist_mtime, _allowlist_checked_at
    global _known_terms_cache, _known_terms_mtime, _known_terms_checked_at
    _data_dir_provider = provider
    _allowlist_cache = None
    _allowlist_mtime = None
    _allowlist_checked_at = 0.0
    _known_terms_cache = None
    _known_terms_mtime = None
    _known_terms_checked_at = 0.0


def japanese_residue_allowlist_path() -> str:
    if _data_dir_provider is None:
        return str(Path.home() / ".epub_translator" / JAPANESE_RESIDUE_ALLOWLIST_FILE)
    return str(_data_dir_provider() / JAPANESE_RESIDUE_ALLOWLIST_FILE)


def known_katakana_terms_path() -> str:
    if _data_dir_provider is None:
        return str(Path.home() / ".epub_translator" / KNOWN_KATAKANA_TERMS_FILE)
    return str(_data_dir_provider() / KNOWN_KATAKANA_TERMS_FILE)


def _clean_known_katakana_terms(payload: Any) -> Dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, str] = {}
    for key, value in payload.items():
        source = str(key or "").strip()
        target = str(value or "").strip()
        if source and target and JAPANESE_KANA_RE.search(source):
            result[source] = target
    return result


def load_known_katakana_terms() -> Dict[str, str]:
    """Load user-editable katakana term repairs, merged over safe defaults."""
    global _known_terms_cache, _known_terms_mtime, _known_terms_checked_at

    now = time.time()
    if _known_terms_cache is not None and now - _known_terms_checked_at < _known_terms_check_interval:
        return dict(_known_terms_cache)

    _known_terms_checked_at = now
    path = Path(known_katakana_terms_path())
    terms = dict(DEFAULT_KNOWN_KATAKANA_TERMS)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        _known_terms_mtime = None
        _known_terms_cache = terms
        return dict(terms)

    if _known_terms_cache is not None and _known_terms_mtime == mtime:
        return dict(_known_terms_cache)

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        terms.update(_clean_known_katakana_terms(payload))
        _known_terms_mtime = mtime
    except Exception as exc:
        logger.warning("加载片假名术语修复词表失败: %s (%s)", path, exc)

    _known_terms_cache = terms
    return dict(terms)


def load_user_known_katakana_terms() -> Dict[str, str]:
    """Load only the user-editable katakana term repairs from disk."""
    path = Path(known_katakana_terms_path())
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return _clean_known_katakana_terms(payload)
    except Exception as exc:
        logger.warning("加载用户片假名术语修复词表失败: %s (%s)", path, exc)
        return {}


def save_known_katakana_terms(terms: Dict[str, str]) -> None:
    """Persist user-editable katakana term repairs."""
    global _known_terms_cache, _known_terms_mtime, _known_terms_checked_at

    cleaned = _clean_known_katakana_terms(terms)
    path = Path(known_katakana_terms_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    _known_terms_cache = dict(DEFAULT_KNOWN_KATAKANA_TERMS)
    _known_terms_cache.update(cleaned)
    _known_terms_mtime = path.stat().st_mtime
    _known_terms_checked_at = time.time()


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text_item = str(item or "").strip()
        if text_item:
            result.append(text_item)
    return list(dict.fromkeys(result))


def load_japanese_residue_allowlist() -> Dict[str, Any]:
    """Load user-configurable residue allowlist with lightweight mtime caching."""
    global _allowlist_cache, _allowlist_mtime, _allowlist_checked_at

    now = time.time()
    if _allowlist_cache is not None and now - _allowlist_checked_at < _allowlist_check_interval:
        return _allowlist_cache

    _allowlist_checked_at = now
    path = Path(japanese_residue_allowlist_path())
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        _allowlist_mtime = None
        _allowlist_cache = {"quoted": set(), "exact": [], "quoted_regex": [], "regex": []}
        return _allowlist_cache

    if _allowlist_cache is not None and _allowlist_mtime == mtime:
        return _allowlist_cache

    cache = {"quoted": set(), "exact": [], "quoted_regex": [], "regex": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("allowlist root must be a JSON object")

        cache["quoted"] = set(_as_str_list(payload.get("quoted")))
        cache["exact"] = _as_str_list(payload.get("exact"))
        for pattern in _as_str_list(payload.get("quoted_regex")):
            try:
                cache["quoted_regex"].append(re.compile(pattern))
            except re.error as exc:
                logger.warning("日文残留允许列表 quoted_regex 无效: %s (%s)", pattern, exc)
        for pattern in _as_str_list(payload.get("regex")):
            try:
                cache["regex"].append(re.compile(pattern))
            except re.error as exc:
                logger.warning("日文残留允许列表 regex 无效: %s (%s)", pattern, exc)
    except Exception as exc:
        logger.warning("加载日文残留允许列表失败: %s (%s)", path, exc)

    _allowlist_mtime = mtime
    _allowlist_cache = cache
    return cache


def strip_user_allowed_japanese_literals(text: str) -> str:
    """Strip user-approved literals from residue detection only."""
    if not text:
        return ""
    allowlist = load_japanese_residue_allowlist()
    stripped = text

    quoted_literals = allowlist.get("quoted") or set()
    quoted_regexes = allowlist.get("quoted_regex") or []
    if quoted_literals or quoted_regexes:
        def replace_quoted(match: re.Match) -> str:
            literal = (match.group(1) or "").strip()
            if literal in quoted_literals:
                return ""
            for pattern in quoted_regexes:
                if pattern.fullmatch(literal):
                    return ""
            return match.group(0)

        stripped = JAPANESE_QUOTED_TEXT_RE.sub(replace_quoted, stripped)

    for literal in allowlist.get("exact") or []:
        stripped = stripped.replace(literal, "")
    for pattern in allowlist.get("regex") or []:
        stripped = pattern.sub("", stripped)
    return stripped


def strip_builtin_allowed_quoted_literals(text: str) -> str:
    if not text:
        return ""

    def replace(match: re.Match) -> str:
        literal = (match.group(1) or "").strip()
        if JAPANESE_SINGLE_KATAKANA_RE.fullmatch(literal):
            return ""
        if JAPANESE_KANA_RE.search(literal):
            context_start = max(0, match.start() - 30)
            context_end = min(len(text), match.end() + 30)
            context = text[context_start:context_end]
            if JAPANESE_EXPLANATORY_QUOTE_CUE_RE.search(context):
                return ""
        return match.group(0)

    return JAPANESE_QUOTED_TEXT_RE.sub(replace, text)


def strip_builtin_allowed_reading_puzzle_runs(text: str) -> str:
    if not text:
        return ""

    def replace(match: re.Match) -> str:
        context_start = max(0, match.start() - 60)
        context_end = min(len(text), match.end() + 60)
        context = text[context_start:context_end]
        if JAPANESE_READING_PUZZLE_CONTEXT_RE.search(context):
            return ""
        return match.group(0)

    return JAPANESE_READING_PUZZLE_RUN_RE.sub(replace, text)


def strip_allowed_japanese_notation(text: str) -> str:
    """Ignore approved literal Japanese snippets that are not untranslated residue."""
    if not text:
        return ""
    stripped = ALLOWED_LATIN_MIDDLE_DOT_RE.sub("", text)
    stripped = ALLOWED_JAPANESE_SHAPE_NOTATION_RE.sub("", stripped)
    stripped = strip_builtin_allowed_quoted_literals(stripped)
    stripped = strip_builtin_allowed_reading_puzzle_runs(stripped)
    return strip_user_allowed_japanese_literals(stripped)


def has_japanese_residue(text: str) -> bool:
    stripped = strip_allowed_japanese_notation(text or "")
    return bool(JAPANESE_KANA_RE.search(stripped))


def extract_japanese_residue_fragments(text: str) -> List[str]:
    if not text:
        return []
    stripped = strip_allowed_japanese_notation(text)
    fragments = JAPANESE_O_NAME_PREFIX_RE.findall(stripped)
    fragments.extend(JAPANESE_KANA_FRAGMENT_RE.findall(stripped))
    return [frag for frag in dict.fromkeys(fragments) if frag.strip()]


def has_likely_o_name_prefix_residue(text: str) -> bool:
    stripped = strip_allowed_japanese_notation(text or "")
    for match in re.finditer(r"お([\u3400-\u9fff々])", stripped):
        stem = match.group(1)
        if stem not in JAPANESE_O_PREFIX_NON_PERSON_STEMS:
            return True
    return False


def has_weak_japanese_residue(text: str) -> bool:
    stripped = strip_allowed_japanese_notation(text or "")
    if not JAPANESE_KANA_RE.search(stripped):
        return False
    if JAPANESE_O_NAME_PREFIX_RE.search(stripped) or has_likely_o_name_prefix_residue(stripped):
        return False
    fragments = [frag for frag in JAPANESE_KANA_FRAGMENT_RE.findall(stripped) if frag.strip()]
    if not fragments:
        return False
    if any(len(fragment) > 1 for fragment in fragments):
        return False
    return len(fragments) <= 3 and len(set(fragments)) <= 3


def is_short_quoted_japanese_literal(text: str) -> bool:
    match = JAPANESE_SHORT_QUOTED_TEXT_RE.fullmatch((text or "").strip())
    if not match:
        return False
    literal = (match.group(1) or "").strip()
    return bool(literal and JAPANESE_KANA_RE.search(literal))


def has_blocking_japanese_residue(text: str) -> bool:
    raw = text or ""
    if is_short_quoted_japanese_literal(raw):
        return False
    stripped = strip_allowed_japanese_notation(raw)
    if not JAPANESE_KANA_RE.search(stripped):
        return False
    return not has_weak_japanese_residue(stripped)


def repair_japanese_o_name_prefix_residue(src: str, dst: str) -> str:
    """Convert likely Japanese female-name prefixes left by the model, e.g. お仲 -> 阿仲."""
    source = str(src or "")
    translated = str(dst or "")
    if "お" not in source or "お" not in translated:
        return translated

    def source_has_name_context(literal: str) -> bool:
        escaped = re.escape(literal)
        if re.search(rf"{escaped}という(?:女|男|娘|人|者)?", source):
            return True
        if re.search(rf"{escaped}(?:は|が|を|に|へ|と|の|、|。|」|』|$)", source):
            return True
        return False

    for match in JAPANESE_O_NAME_PREFIX_RE.finditer(source):
        literal = match.group(0)
        stem = literal[1:]
        if stem in JAPANESE_O_PREFIX_NON_PERSON_STEMS:
            continue
        if literal not in translated:
            continue
        if not source_has_name_context(literal):
            continue
        translated = translated.replace(literal, "阿" + stem)
    return translated


def repair_known_katakana_terms(src: str, dst: str) -> str:
    """Translate known katakana item names that models sometimes preserve."""
    translated = str(dst or "")
    if not translated:
        return ""

    for source, target in load_known_katakana_terms().items():
        escaped_source = re.escape(source)
        escaped_target = re.escape(target)
        translated = re.sub(
            rf'叫作["“「]?{escaped_source}["”」]?的{escaped_target}',
            target,
            translated,
        )
        translated = re.sub(rf'["“「]{escaped_source}["”」]', target, translated)
        if source == "チロリ":
            translated = translated.replace(f"{source}的", f"{target}里的")
        translated = translated.replace(source, target)
    return translated


def postprocess_translation(src: str, dst: Optional[str]) -> str:
    translated = str(dst or "").strip()
    if not translated:
        return ""
    translated = repair_japanese_o_name_prefix_residue(src, translated)
    return repair_known_katakana_terms(src, translated)


def has_only_trivial_japanese_noise(text: str) -> bool:
    if not text:
        return False
    stripped = strip_allowed_japanese_notation(text)
    if not JAPANESE_KANA_RE.search(stripped):
        return False
    han_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    kana_fragments = [f for f in JAPANESE_KANA_FRAGMENT_RE.findall(stripped) if f.strip()]
    total_kana = sum(len(f) for f in kana_fragments)
    if han_count < 8:
        return False
    if len(kana_fragments) > 3 or total_kana > max(3, han_count * 0.05):
        return False
    return True


def is_incomplete_translation(src: str, dst: Optional[str]) -> bool:
    source = (src or "").strip()
    translated = postprocess_translation(source, dst)
    if not translated:
        return True
    if source and translated == source:
        if has_blocking_japanese_residue(source):
            if has_only_trivial_japanese_noise(source):
                return False
            return True
        bare = source.strip('「」『』').strip()
        if len(bare) <= 6:
            return False
    if has_blocking_japanese_residue(translated):
        if has_only_trivial_japanese_noise(translated):
            return False
        return True
    return False
