from glossary_store import clean_new_terms
from tests.test_translation_pipeline import DummyTranslator
from translation_models import BatchJsonResult


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
