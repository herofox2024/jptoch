import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from glossary_store import (
    DEFAULT_GLOSSARY_CATEGORIES,
    merge_glossaries,
    normalize_glossary_payload,
)
from translation_cache import atomic_write_json, load_json_file


PROFILE_SCOPES = {"genre", "series", "book"}
SCOPE_PRIORITY = {"genre": 1, "series": 2, "book": 3}


def glossary_profiles_dir(data_dir: Path) -> Path:
    path = Path(data_dir) / "glossary_profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", str(value or "").strip()).strip("-").lower()
    return (slug or "profile")[:64]


def _name_key(value: str) -> str:
    return _slugify(value)


def _profile_path(data_dir: Path, profile_id: str) -> Path:
    clean_id = re.sub(r"[^0-9A-Za-z_-]+", "", str(profile_id or "").strip())
    if not clean_id:
        raise ValueError("术语配置 ID 不能为空")
    return glossary_profiles_dir(data_dir) / f"{clean_id}.json"


def _count_terms(glossary: Dict[str, Any]) -> int:
    total = 0
    for category in DEFAULT_GLOSSARY_CATEGORIES:
        entries = glossary.get(category, [])
        if isinstance(entries, list):
            total += len(entries)
    return total


def normalize_profile(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    name = str(payload.get("name") or "").strip()
    scope = str(payload.get("scope") or "book").strip().lower()
    if scope not in PROFILE_SCOPES:
        scope = "book"
    profile_id = str(payload.get("id") or "").strip()
    if not profile_id:
        profile_id = f"{scope}-{_slugify(name)}-{uuid.uuid4().hex[:8]}"
    terms, _ = normalize_glossary_payload(payload.get("terms") or {})
    created_at = int(payload.get("created_at") or time.time())
    updated_at = int(payload.get("updated_at") or created_at)
    return {
        "id": profile_id,
        "name": name or profile_id,
        "scope": scope,
        "description": str(payload.get("description") or "").strip(),
        "source_book": str(payload.get("source_book") or "").strip(),
        "created_at": created_at,
        "updated_at": updated_at,
        "terms": terms,
        "term_count": _count_terms(terms),
    }


def list_profiles(data_dir: Path) -> List[Dict[str, Any]]:
    profiles = []
    for path in glossary_profiles_dir(data_dir).glob("*.json"):
        profile = normalize_profile(load_json_file(path, {}))
        if profile:
            profiles.append(profile)
    profiles.sort(
        key=lambda item: (
            SCOPE_PRIORITY.get(item.get("scope", "book"), 9),
            str(item.get("name") or "").lower(),
        )
    )
    return profiles


def find_profile(data_dir: Path, *, scope: str, name: str) -> Dict[str, Any]:
    scope = str(scope or "").strip().lower()
    target = _name_key(name)
    if scope not in PROFILE_SCOPES or not target:
        return {}
    matches = [
        profile
        for profile in list_profiles(data_dir)
        if profile.get("scope") == scope and _name_key(profile.get("name") or "") == target
    ]
    if not matches:
        return {}
    matches.sort(
        key=lambda item: (
            int(item.get("updated_at") or 0),
            int(item.get("created_at") or 0),
        ),
        reverse=True,
    )
    return dict(matches[0])


def load_profile(data_dir: Path, profile_id: str) -> Dict[str, Any]:
    return normalize_profile(load_json_file(_profile_path(data_dir, profile_id), {}))


def save_profile(
    data_dir: Path,
    *,
    name: str,
    scope: str,
    terms: Dict[str, Any],
    profile_id: str = "",
    description: str = "",
    source_book: str = "",
    merge_existing: bool = True,
) -> Dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("术语配置名称不能为空")
    scope = str(scope or "book").strip().lower()
    if scope not in PROFILE_SCOPES:
        raise ValueError("术语配置类型必须是 genre、series 或 book")

    normalized_terms, _ = normalize_glossary_payload(terms or {})
    existing = load_profile(data_dir, profile_id) if profile_id else {}
    if existing and merge_existing:
        normalized_terms, _ = merge_glossaries(existing.get("terms") or {}, normalized_terms)

    now = int(time.time())
    profile = normalize_profile(
        {
            "id": profile_id or f"{scope}-{_slugify(name)}-{uuid.uuid4().hex[:8]}",
            "name": name,
            "scope": scope,
            "description": description,
            "source_book": source_book,
            "created_at": existing.get("created_at") or now,
            "updated_at": now,
            "terms": normalized_terms,
        }
    )
    atomic_write_json(_profile_path(data_dir, profile["id"]), profile)
    return profile


def upsert_profile(
    data_dir: Path,
    *,
    name: str,
    scope: str,
    terms: Dict[str, Any],
    description: str = "",
    source_book: str = "",
) -> Dict[str, Any]:
    existing = find_profile(data_dir, scope=scope, name=name)
    return save_profile(
        data_dir,
        name=name,
        scope=scope,
        terms=terms,
        profile_id=str(existing.get("id") or ""),
        description=description,
        source_book=source_book,
        merge_existing=True,
    )


def delete_profile(data_dir: Path, profile_id: str) -> bool:
    path = _profile_path(data_dir, profile_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def merge_selected_profiles(
    data_dir: Path,
    profile_ids: Iterable[str],
    base_glossary: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, int]]:
    merged, _ = normalize_glossary_payload(base_glossary or {})
    selected = []
    stats = {"added": 0, "skipped": 0, "conflicts": 0}

    profiles = []
    seen_ids = set()
    for profile_id in profile_ids or []:
        profile_id = str(profile_id or "").strip()
        if not profile_id or profile_id in seen_ids:
            continue
        seen_ids.add(profile_id)
        profile = load_profile(data_dir, profile_id)
        if profile:
            profiles.append(profile)

    # Higher-priority profiles are merged first. Existing entries win, so this
    # keeps book > series > genre > global deterministic on conflicts.
    profiles.sort(key=lambda item: SCOPE_PRIORITY.get(item.get("scope", "book"), 0), reverse=True)
    selected_base = {category: [] for category in DEFAULT_GLOSSARY_CATEGORIES}
    for profile in profiles:
        selected_base, merge_stats = merge_glossaries(selected_base, profile.get("terms") or {})
        for key in stats:
            stats[key] += int(merge_stats.get(key, 0))

    # Selected profiles override the global glossary on conflicts.
    merged, global_stats = merge_glossaries(selected_base, merged)
    for key in stats:
        stats[key] += int(global_stats.get(key, 0))
    selected.extend(profiles)
    return merged, selected, stats


def resolve_profile_ids(
    data_dir: Path,
    *,
    use_genre: bool = False,
    use_series: bool = False,
    use_book: bool = False,
    genre_name: str = "",
    series_name: str = "",
    book_name: str = "",
) -> Tuple[List[str], List[Dict[str, Any]]]:
    targets = []
    if use_genre and str(genre_name or "").strip():
        targets.append(("genre", genre_name))
    if use_series and str(series_name or "").strip():
        targets.append(("series", series_name))
    if use_book and str(book_name or "").strip():
        targets.append(("book", book_name))

    profile_ids: List[str] = []
    profiles: List[Dict[str, Any]] = []
    seen_ids = set()
    for scope, name in targets:
        profile = find_profile(data_dir, scope=scope, name=name)
        if not profile:
            continue
        profile_id = str(profile.get("id") or "").strip()
        if not profile_id or profile_id in seen_ids:
            continue
        seen_ids.add(profile_id)
        profile_ids.append(profile_id)
        profiles.append(profile)
    return profile_ids, profiles


def glossary_fingerprint(glossary: Dict[str, Any]) -> str:
    normalized, _ = normalize_glossary_payload(glossary or {})
    compact = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(compact.encode("utf-8")).hexdigest()
