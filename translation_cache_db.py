"""SQLite-backed translation cache with backward-compatible JSON migration."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import weakref
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from translation_cache import parse_model_cache_key, text_cache_key


logger = logging.getLogger(__name__)

CACHE_TYPES = frozenset({"model", "text", "manual"})
SCHEMA_VERSION = 1


def cache_db_path_for(cache_path: str | Path) -> Path:
    source = Path(cache_path)
    if source.name.lower() == "cache.json":
        return source.with_name("cache.db")
    return source.with_suffix(".db")


@dataclass(frozen=True)
class MigrationResult:
    imported: int = 0
    skipped: bool = False
    error: str = ""


class TranslationCacheDB:
    """Thread-safe SQLite store shared by model, text, and manual caches."""

    _instances: "weakref.WeakSet[TranslationCacheDB]" = weakref.WeakSet()
    _instances_lock = threading.Lock()

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._pending_usage: Dict[Tuple[str, str], Tuple[int, int]] = {}
        self._connection = sqlite3.connect(
            str(self.path),
            timeout=30.0,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA busy_timeout=30000")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._create_schema()
        with self._instances_lock:
            self._instances.add(self)

    @classmethod
    def close_open_under(cls, root: str | Path) -> None:
        """Close live databases below a directory before Windows removes it."""
        base = Path(root).resolve()
        with cls._instances_lock:
            instances = list(cls._instances)
        for instance in instances:
            try:
                instance.path.resolve().relative_to(base)
            except (ValueError, OSError):
                continue
            instance.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_type TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                source_hash TEXT,
                context_hash TEXT,
                source_text TEXT,
                translated_text TEXT NOT NULL,
                provider TEXT,
                model TEXT,
                glossary_fingerprint TEXT,
                trusted INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                last_used_at INTEGER,
                hit_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (cache_type, cache_key)
            );
            CREATE INDEX IF NOT EXISTS idx_cache_source
                ON cache_entries(cache_type, source_hash, context_hash);
            CREATE INDEX IF NOT EXISTS idx_cache_provider_model
                ON cache_entries(cache_type, provider, model);
            CREATE INDEX IF NOT EXISTS idx_cache_updated
                ON cache_entries(cache_type, updated_at);
            CREATE TABLE IF NOT EXISTS cache_metadata (
                meta_key TEXT PRIMARY KEY,
                meta_value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )
        self._set_metadata_locked("schema_version", str(SCHEMA_VERSION))
        self._connection.commit()

    @staticmethod
    def _validate_type(cache_type: str) -> str:
        value = str(cache_type or "").strip().lower()
        if value not in CACHE_TYPES:
            raise ValueError(f"Unsupported cache type: {cache_type}")
        return value

    @staticmethod
    def _model_key_fields(
        cache_key: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
        kind, source_hash, context_hash = parse_model_cache_key(cache_key)
        provider = None
        model = None
        glossary_fingerprint = None
        parts = str(cache_key or "").split(":")
        if kind and len(parts) >= 4:
            provider = parts[1] or None
            middle = parts[2:-1] if kind == "text" else parts[2:-2]
            if middle and middle[-1].startswith("g") and len(middle[-1]) > 1:
                glossary_fingerprint = middle.pop()[1:]
            model = ":".join(middle) or None
        return source_hash, context_hash, provider, model, glossary_fingerprint

    @classmethod
    def _normalize_entry(cls, cache_type: str, cache_key: str, value: Any) -> Dict[str, Any]:
        cache_type = cls._validate_type(cache_type)
        key = str(cache_key)
        payload = value if isinstance(value, dict) else None
        translated = value if isinstance(value, str) else (payload or {}).get("translation", "")
        translated = str(translated or "")
        if not translated:
            raise ValueError("Cache translation cannot be empty")

        source_hash = None
        context_hash = None
        provider = None
        model = None
        glossary_fingerprint = None
        source_text = None
        trusted = False
        verified = False
        updated_at = int(time.time())

        if cache_type == "model":
            source_hash, context_hash, provider, model, glossary_fingerprint = cls._model_key_fields(key)
            if not source_hash and key:
                source_text = key
                source_hash = text_cache_key(key)
        else:
            source_hash = key
            if payload:
                source_text = str(payload.get("source") or "") or None
                trusted = bool(payload.get("trusted", cache_type == "manual"))
                verified = bool(payload.get("verified", False))
                try:
                    updated_at = int(payload.get("updated_at") or updated_at)
                except (TypeError, ValueError):
                    pass

        return {
            "cache_type": cache_type,
            "cache_key": key,
            "source_hash": source_hash,
            "context_hash": context_hash,
            "source_text": source_text,
            "translated_text": translated,
            "provider": provider,
            "model": model,
            "glossary_fingerprint": glossary_fingerprint,
            "trusted": int(trusted),
            "verified": int(verified),
            "payload_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else None,
            "created_at": updated_at,
            "updated_at": updated_at,
        }

    def put(self, cache_type: str, cache_key: str, value: Any) -> None:
        self.put_many(cache_type, [(cache_key, value)])

    def put_many(self, cache_type: str, entries: Iterable[Tuple[str, Any]]) -> int:
        normalized = []
        for key, value in entries:
            try:
                normalized.append(self._normalize_entry(cache_type, key, value))
            except (TypeError, ValueError):
                logger.debug("Skipping invalid cache entry: type=%s key=%s", cache_type, key)
        if not normalized:
            return 0
        sql = """
            INSERT INTO cache_entries (
                cache_type, cache_key, source_hash, context_hash, source_text,
                translated_text, provider, model, glossary_fingerprint,
                trusted, verified, payload_json, created_at, updated_at
            ) VALUES (
                :cache_type, :cache_key, :source_hash, :context_hash, :source_text,
                :translated_text, :provider, :model, :glossary_fingerprint,
                :trusted, :verified, :payload_json, :created_at, :updated_at
            )
            ON CONFLICT(cache_type, cache_key) DO UPDATE SET
                source_hash=excluded.source_hash,
                context_hash=excluded.context_hash,
                source_text=COALESCE(excluded.source_text, cache_entries.source_text),
                translated_text=excluded.translated_text,
                provider=excluded.provider,
                model=excluded.model,
                glossary_fingerprint=excluded.glossary_fingerprint,
                trusted=excluded.trusted,
                verified=excluded.verified,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
        """
        with self._lock:
            self._connection.executemany(sql, normalized)
            self._connection.commit()
        return len(normalized)

    def get(self, cache_type: str, cache_key: str) -> Any:
        cache_type = self._validate_type(cache_type)
        with self._lock:
            row = self._connection.execute(
                "SELECT translated_text, payload_json FROM cache_entries WHERE cache_type=? AND cache_key=?",
                (cache_type, str(cache_key)),
            ).fetchone()
        if row is None:
            raise KeyError(cache_key)
        self._record_usage(cache_type, str(cache_key))
        if row["payload_json"]:
            try:
                return json.loads(row["payload_json"])
            except json.JSONDecodeError:
                pass
        return row["translated_text"]

    def contains(self, cache_type: str, cache_key: str) -> bool:
        cache_type = self._validate_type(cache_type)
        with self._lock:
            row = self._connection.execute(
                "SELECT 1 FROM cache_entries WHERE cache_type=? AND cache_key=? LIMIT 1",
                (cache_type, str(cache_key)),
            ).fetchone()
        return row is not None

    def count(self, cache_type: Optional[str] = None) -> int:
        with self._lock:
            if cache_type is None:
                row = self._connection.execute("SELECT COUNT(*) FROM cache_entries").fetchone()
            else:
                row = self._connection.execute(
                    "SELECT COUNT(*) FROM cache_entries WHERE cache_type=?",
                    (self._validate_type(cache_type),),
                ).fetchone()
        return int(row[0] if row else 0)

    def keys(self, cache_type: str) -> list[str]:
        cache_type = self._validate_type(cache_type)
        with self._lock:
            rows = self._connection.execute(
                "SELECT cache_key FROM cache_entries WHERE cache_type=?",
                (cache_type,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def delete(self, cache_type: str, cache_key: str) -> bool:
        cache_type = self._validate_type(cache_type)
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM cache_entries WHERE cache_type=? AND cache_key=?",
                (cache_type, str(cache_key)),
            )
            self._connection.commit()
        return cursor.rowcount > 0

    def delete_many(self, cache_type: str, cache_keys: Iterable[str]) -> int:
        cache_type = self._validate_type(cache_type)
        keys = list(dict.fromkeys(str(key) for key in cache_keys if str(key)))
        if not keys:
            return 0
        with self._lock:
            before = self._connection.total_changes
            self._connection.executemany(
                "DELETE FROM cache_entries WHERE cache_type=? AND cache_key=?",
                [(cache_type, key) for key in keys],
            )
            self._connection.commit()
            return self._connection.total_changes - before

    def delete_model_sources(
        self,
        source_hashes: Iterable[str],
        cache_keys: Iterable[str] = (),
    ) -> int:
        hashes = list(dict.fromkeys(str(value) for value in source_hashes if str(value)))
        keys = list(dict.fromkeys(str(value) for value in cache_keys if str(value)))
        removed = 0
        with self._lock:
            for column, values in (("source_hash", hashes), ("cache_key", keys)):
                for start in range(0, len(values), 400):
                    chunk = values[start:start + 400]
                    placeholders = ",".join("?" for _ in chunk)
                    cursor = self._connection.execute(
                        f"DELETE FROM cache_entries WHERE cache_type='model' AND {column} IN ({placeholders})",
                        chunk,
                    )
                    removed += max(0, int(cursor.rowcount))
            self._connection.commit()
        return removed

    def clear(self, cache_type: Optional[str] = None) -> int:
        with self._lock:
            if cache_type is None:
                cursor = self._connection.execute("DELETE FROM cache_entries")
            else:
                cursor = self._connection.execute(
                    "DELETE FROM cache_entries WHERE cache_type=?",
                    (self._validate_type(cache_type),),
                )
            self._connection.commit()
        return max(0, int(cursor.rowcount))

    def find_model_translation(
        self,
        source_hash: str,
        *,
        context_hash: Optional[str] = None,
        exclude_key: Optional[str] = None,
    ) -> Optional[str]:
        clauses = ["cache_type='model'", "source_hash=?", "glossary_fingerprint IS NULL"]
        params: list[Any] = [str(source_hash)]
        if context_hash:
            clauses.append("context_hash=?")
            params.append(str(context_hash))
        else:
            clauses.append("context_hash IS NULL")
        if exclude_key:
            clauses.append("cache_key<>?")
            params.append(str(exclude_key))
        sql = (
            "SELECT cache_key, translated_text FROM cache_entries WHERE "
            + " AND ".join(clauses)
            + " ORDER BY updated_at DESC LIMIT 1"
        )
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        if not row or not row["translated_text"]:
            return None
        self._record_usage("model", str(row["cache_key"]))
        return str(row["translated_text"])

    def delete_model_scope(
        self,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        updated_before: Optional[int] = None,
    ) -> int:
        clauses = ["cache_type='model'"]
        params: list[Any] = []
        if provider:
            clauses.append("provider=?")
            params.append(str(provider).lower())
        if model:
            clauses.append("LOWER(model)=LOWER(?)")
            params.append(str(model))
        if updated_before is not None:
            clauses.append("updated_at<?")
            params.append(int(updated_before))
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM cache_entries WHERE " + " AND ".join(clauses),
                params,
            )
            self._connection.commit()
        return max(0, int(cursor.rowcount))

    def cleanup_expired(self, max_age_days: int = 730) -> int:
        """Delete stale ordinary entries while preserving manual and verified text caches."""
        days = max(30, int(max_age_days or 730))
        cutoff = int(time.time()) - days * 86400
        self._flush_usage()
        with self._lock:
            cursor = self._connection.execute(
                """
                DELETE FROM cache_entries
                WHERE COALESCE(last_used_at, updated_at) < ?
                  AND (cache_type='model' OR (cache_type='text' AND verified=0))
                """,
                (cutoff,),
            )
            self._connection.commit()
        return max(0, int(cursor.rowcount))

    def _record_usage(self, cache_type: str, cache_key: str) -> None:
        now = int(time.time())
        identity = (cache_type, cache_key)
        with self._lock:
            hits, _last_used = self._pending_usage.get(identity, (0, now))
            self._pending_usage[identity] = (hits + 1, now)
            should_flush = len(self._pending_usage) >= 250
        if should_flush:
            self._flush_usage()

    def _flush_usage(self) -> None:
        with self._lock:
            if self._closed:
                self._pending_usage.clear()
                return
            if not self._pending_usage:
                return
            pending = [
                (hits, last_used, cache_type, cache_key)
                for (cache_type, cache_key), (hits, last_used) in self._pending_usage.items()
            ]
            self._pending_usage.clear()
            self._connection.executemany(
                """
                UPDATE cache_entries
                SET hit_count=hit_count+?, last_used_at=?
                WHERE cache_type=? AND cache_key=?
                """,
                pending,
            )
            self._connection.commit()

    def _metadata_locked(self, key: str) -> Optional[str]:
        row = self._connection.execute(
            "SELECT meta_value FROM cache_metadata WHERE meta_key=?",
            (str(key),),
        ).fetchone()
        return str(row[0]) if row else None

    def _set_metadata_locked(self, key: str, value: str) -> None:
        self._connection.execute(
            """
            INSERT INTO cache_metadata(meta_key, meta_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(meta_key) DO UPDATE SET
                meta_value=excluded.meta_value,
                updated_at=excluded.updated_at
            """,
            (str(key), str(value), int(time.time())),
        )

    def migrate_json(self, path: str | Path, cache_type: str) -> MigrationResult:
        source = Path(path)
        cache_type = self._validate_type(cache_type)
        if not source.exists():
            return MigrationResult(skipped=True)
        try:
            stat = source.stat()
            fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
            marker = f"json_migration:{cache_type}:{source.resolve()}"
            with self._lock:
                if self._metadata_locked(marker) == fingerprint:
                    return MigrationResult(skipped=True)
            payload = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return MigrationResult(error="JSON cache root is not an object")
            imported = self.put_many(cache_type, payload.items())
            with self._lock:
                self._set_metadata_locked(marker, fingerprint)
                self._connection.commit()
            return MigrationResult(imported=imported)
        except Exception as exc:
            logger.warning("Cache JSON migration failed: %s (%s)", source, exc)
            return MigrationResult(error=str(exc))

    def checkpoint(self) -> None:
        if self._closed:
            return
        self._flush_usage()
        with self._lock:
            self._connection.commit()
            self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def close(self) -> None:
        if self._closed:
            return
        self._flush_usage()
        with self._lock:
            if self._closed:
                return
            try:
                self._connection.commit()
                self._connection.close()
            except sqlite3.Error:
                pass
            self._closed = True


class SQLiteCacheMapping(MutableMapping[str, Any]):
    """Dictionary-compatible view over one cache type."""

    def __init__(self, database: TranslationCacheDB, cache_type: str, buffer_size: int = 1):
        self.database = database
        self.cache_type = database._validate_type(cache_type)
        self.buffer_size = max(1, int(buffer_size or 1))
        self._pending: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def __getitem__(self, key: str) -> Any:
        with self._lock:
            if key in self._pending:
                return self._pending[key]
        return self.database.get(self.cache_type, key)

    def __setitem__(self, key: str, value: Any) -> None:
        if self.buffer_size <= 1:
            self.database.put(self.cache_type, key, value)
            return
        pending = None
        with self._lock:
            self._pending[str(key)] = value
            if len(self._pending) >= self.buffer_size:
                pending = list(self._pending.items())
                self._pending.clear()
        if pending:
            self.database.put_many(self.cache_type, pending)

    def __delitem__(self, key: str) -> None:
        pending_removed = False
        with self._lock:
            if key in self._pending:
                self._pending.pop(key, None)
                pending_removed = True
        database_removed = self.database.delete(self.cache_type, key)
        if not pending_removed and not database_removed:
            raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        database_keys = self.database.keys(self.cache_type)
        with self._lock:
            pending_keys = list(self._pending)
        return iter(list(dict.fromkeys(database_keys + pending_keys)))

    def __len__(self) -> int:
        database_count = self.database.count(self.cache_type)
        with self._lock:
            pending_keys = list(self._pending)
        new_pending = sum(
            1 for key in pending_keys if not self.database.contains(self.cache_type, key)
        )
        return database_count + new_pending

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        with self._lock:
            if key in self._pending:
                return True
        return self.database.contains(self.cache_type, key)

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()
        self.database.clear(self.cache_type)

    def flush(self) -> None:
        with self._lock:
            pending = list(self._pending.items())
            self._pending.clear()
        if pending:
            try:
                self.database.put_many(self.cache_type, pending)
            except Exception:
                with self._lock:
                    for key, value in pending:
                        self._pending.setdefault(key, value)
                raise
        self.database.checkpoint()
