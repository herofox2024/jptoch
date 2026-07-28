import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from translation_cache import model_cache_key, text_cache_key
from translation_cache_db import SQLiteCacheMapping, TranslationCacheDB, cache_db_path_for
from translator import JaZhTranslator


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_cache_db_path_keeps_prompt_preview_separate(tmp_path: Path):
    assert cache_db_path_for(tmp_path / "cache.json") == tmp_path / "cache.db"
    assert cache_db_path_for(tmp_path / ".prompt_preview_cache.json") == tmp_path / ".prompt_preview_cache.db"


def test_three_json_caches_migrate_and_sources_remain(tmp_path: Path):
    source = "彼女は笑った。"
    digest = text_cache_key(source)
    model_key = model_cache_key("deepseek", "deepseek-chat", source)
    model_json = tmp_path / "cache.json"
    text_json = tmp_path / "text_cache.json"
    manual_json = tmp_path / "manual_cache.json"
    write_json(model_json, {model_key: "她笑了。"})
    write_json(text_json, {digest: {"translation": "她笑了。", "verified": True, "updated_at": 10}})
    write_json(manual_json, {digest: {"source": source, "translation": "她微微一笑。", "trusted": True, "updated_at": 11}})

    database = TranslationCacheDB(tmp_path / "cache.db")
    assert database.migrate_json(model_json, "model").imported == 1
    assert database.migrate_json(text_json, "text").imported == 1
    assert database.migrate_json(manual_json, "manual").imported == 1

    assert database.count() == 3
    assert database.get("model", model_key) == "她笑了。"
    assert database.get("text", digest)["verified"] is True
    assert database.get("manual", digest)["trusted"] is True
    assert database.find_model_translation(digest) == "她笑了。"
    assert model_json.exists() and text_json.exists() and manual_json.exists()
    database.close()


def test_json_migration_is_idempotent_and_reimports_changed_source(tmp_path: Path):
    source = tmp_path / "cache.json"
    write_json(source, {"legacy": "译文一"})
    database = TranslationCacheDB(tmp_path / "cache.db")

    first = database.migrate_json(source, "model")
    second = database.migrate_json(source, "model")
    assert first.imported == 1
    assert second.skipped is True

    write_json(source, {"legacy": "更新译文", "legacy-2": "译文二"})
    changed = database.migrate_json(source, "model")
    assert changed.imported == 2
    assert database.count("model") == 2
    assert database.get("model", "legacy") == "更新译文"
    database.close()


def test_sqlite_mapping_supports_concurrent_writes_and_deletes(tmp_path: Path):
    database = TranslationCacheDB(tmp_path / "cache.db")
    mapping = SQLiteCacheMapping(database, "model")

    def write(index: int):
        mapping[model_cache_key("deepseek", "m", f"原文-{index}")] = f"译文-{index}"

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(100)))

    assert len(mapping) == 100
    sample_key = model_cache_key("deepseek", "m", "原文-25")
    assert mapping[sample_key] == "译文-25"
    assert mapping.pop(sample_key) == "译文-25"
    assert sample_key not in mapping
    assert len(mapping) == 99
    database.close()


def test_buffered_mapping_flushes_as_one_batch(tmp_path: Path):
    database = TranslationCacheDB(tmp_path / "cache.db")
    mapping = SQLiteCacheMapping(database, "model", buffer_size=3)
    mapping["one"] = "一"
    mapping["two"] = "二"

    assert database.count("model") == 0
    assert mapping["one"] == "一"
    assert len(mapping) == 2

    mapping["three"] = "三"
    assert database.count("model") == 3
    mapping["four"] = "四"
    mapping.flush()
    assert database.count("model") == 4
    database.close()


def test_cross_model_lookup_uses_source_and_context_indexes(tmp_path: Path):
    database = TranslationCacheDB(tmp_path / "cache.db")
    source = "はい"
    deepseek_key = model_cache_key("deepseek", "deepseek-chat", source)
    longcat_key = model_cache_key("longcat", "LongCat-2.0", source)
    database.put("model", deepseek_key, "是的")

    digest = text_cache_key(source)
    assert database.find_model_translation(digest, exclude_key=longcat_key) == "是的"
    assert database.find_model_translation("missing") is None
    database.close()


def test_scope_and_expiry_cleanup_preserve_manual_and_verified_text(tmp_path: Path):
    database = TranslationCacheDB(tmp_path / "cache.db")
    old = int(time.time()) - 800 * 86400
    source = "古い文"
    digest = text_cache_key(source)
    deepseek_key = model_cache_key("deepseek", "deepseek-chat", source)
    longcat_key = model_cache_key("longcat", "LongCat-2.0", source)
    database.put("model", deepseek_key, "旧译文")
    database.put("model", longcat_key, "旧译文二")
    database.put("text", digest, {"translation": "已验证", "verified": True, "updated_at": old})
    database.put("manual", digest, {"source": source, "translation": "人工译文", "trusted": True, "updated_at": old})
    with database._lock:
        database._connection.execute(
            "UPDATE cache_entries SET updated_at=? WHERE cache_type='model'",
            (old,),
        )
        database._connection.commit()

    assert database.delete_model_scope(provider="longcat", model="LongCat-2.0") == 1
    assert database.cleanup_expired(730) == 1
    assert database.count("model") == 0
    assert database.count("text") == 1
    assert database.count("manual") == 1
    database.close()


def test_translator_migrates_json_and_hits_sqlite_after_restart(tmp_path: Path):
    source = "彼女は笑った。"
    model_key = model_cache_key("deepseek", "deepseek-v4-flash", source)
    cache_json = tmp_path / "cache.json"
    glossary_json = tmp_path / "glossary.json"
    write_json(cache_json, {model_key: "她笑了。"})
    write_json(glossary_json, {})

    first = JaZhTranslator(
        api_key="test",
        provider="deepseek",
        model="deepseek-v4-flash",
        cache_path=str(cache_json),
        glossary_path=str(glossary_json),
    )
    assert isinstance(first.cache, SQLiteCacheMapping)
    first._call_deepseek = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("API should not run"))
    assert first.translate(source) == "她笑了。"
    first.flush_cache()
    first._cache_db.close()

    second = JaZhTranslator(
        api_key="test",
        provider="deepseek",
        model="deepseek-v4-flash",
        cache_path=str(cache_json),
        glossary_path=str(glossary_json),
    )
    second._call_deepseek = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("API should not run"))
    assert second.translate(source) == "她笑了。"
    assert cache_json.exists()
    second._cache_db.close()


def test_translator_clear_removes_all_cache_layers(tmp_path: Path):
    source = "彼女は笑った。"
    cache_json = tmp_path / "cache.json"
    glossary_json = tmp_path / "glossary.json"
    write_json(cache_json, {})
    write_json(glossary_json, {})
    translator = JaZhTranslator(
        api_key="test",
        provider="deepseek",
        model="deepseek-v4-flash",
        cache_path=str(cache_json),
        glossary_path=str(glossary_json),
    )
    translator.cache[translator._cache_key(source)] = "她笑了。"
    translator._save_text_cache_entry(source, "她笑了。", verified=True)
    translator.save_manual_translation(source, "她微微一笑。")

    removed = translator.clear_cache_for_texts(
        [source],
        include_text_cache=True,
        all_models=True,
    )

    assert removed == 3
    assert translator._cache_db.count() == 0
    translator._cache_db.close()
