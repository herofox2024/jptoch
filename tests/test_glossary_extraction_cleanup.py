from glossary_store import clean_new_terms
from tests.test_translation_pipeline import DummyTranslator
from translation_models import BatchJsonResult, ContentModerationError


def test_extraction_removes_detached_particle_and_preserves_hiragana_name():
    cleaned = clean_new_terms([
        {"src": "はミーコ", "dst": "美子", "category": "Person"},
        {"src": "はるか", "dst": "遥香", "category": "Person"},
    ])

    assert cleaned[0]["src"] == "ミーコ"
    assert cleaned[0]["category"] == "Person"
    assert cleaned[1]["src"] == "はるか"


def test_extraction_merges_same_source_translations_as_aliases():
    cleaned = clean_new_terms([
        {"src": "ミーコ", "dst": "美子", "category": "Person"},
        {"src": "はミーコ", "dst": "咪可", "category": "Creature"},
        {"src": "ミーコ", "dst": "美子", "category": "Person"},
    ])

    assert len(cleaned) == 1
    assert cleaned[0]["src"] == "ミーコ"
    assert cleaned[0]["category"] == "Creature"
    assert cleaned[0]["aliases"] == ["咪可"]


def test_extraction_profile_keeps_creature_aliases():
    translator = DummyTranslator()
    translator.glossary_extraction_mode = "novel"
    translator._call_glossary_extraction_json = lambda *args, **kwargs: BatchJsonResult(
        translations=[],
        new_terms=[
            {
                "src": "はミーコ",
                "dst": "美子",
                "category": "Creature",
                "aliases": ["咪可", "米可"],
            }
        ],
        missing_indices=[],
    )

    result = translator.extract_glossary_candidates(
        ["猫の名前はミーコだった。"],
        batch_size=1,
        extraction_mode="novel",
    )

    assert result["glossary"]["Creature"] == [
        {
            "original": "ミーコ",
            "translation": "美子",
            "source": "preextract",
            "aliases": ["咪可", "米可"],
        }
    ]


def test_extraction_splits_moderated_batch_and_continues_later_batches():
    translator = DummyTranslator()
    calls = []
    progress = []

    def extract(texts, **_kwargs):
        calls.append(list(texts))
        if texts == ["第三段", "第四段"] or texts == ["第四段"]:
            raise ContentModerationError("security_audit_fail")
        return BatchJsonResult(
            translations=[],
            new_terms=[
                {
                    "src": texts[0],
                    "dst": f"译-{texts[0]}",
                    "category": "Person",
                }
            ],
            missing_indices=[],
        )

    translator._call_glossary_extraction_json = extract
    result = translator.extract_glossary_candidates(
        ["第一段", "第二段", "第三段", "第四段", "第五段"],
        batch_size=2,
        extraction_mode="novel",
        progress_callback=lambda current, total: progress.append((current, total)),
    )

    assert result["moderation_skipped"] == 1
    assert [term["src"] for term in result["terms"]] == ["第一段", "第三段", "第五段"]
    assert calls == [
        ["第一段", "第二段"],
        ["第三段", "第四段"],
        ["第三段"],
        ["第四段"],
        ["第五段"],
    ]
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_extraction_does_not_retry_single_moderated_payload():
    translator = DummyTranslator()
    calls = []

    def reject(texts, **_kwargs):
        calls.append(list(texts))
        raise ContentModerationError("security_audit_fail")

    translator._call_glossary_extraction_json = reject
    result = translator.extract_glossary_candidates(
        ["被审核文本"],
        batch_size=1,
        extraction_mode="lite",
    )

    assert result["moderation_skipped"] == 1
    assert result["terms"] == []
    assert calls == [["被审核文本"]]
