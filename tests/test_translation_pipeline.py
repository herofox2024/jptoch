import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from bs4 import BeautifulSoup

from app import App
from translator import FastFailError, JaZhTranslator


class DummyTranslator(JaZhTranslator):
    def __init__(self):
        self.provider = "deepseek"
        self.api_key = "x"
        self.enable_glossary = True
        self.glossary = {}
        self.cache = {}
        self._cache_dirty = False
        self._save_counter = 0
        self._cache_lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self._glossary_prompt_max_terms = 120
        self.stats = {
            "api_requests_total": 0,
            "batch_total": 0,
            "batch_json_success": 0,
            "batch_fallback": 0,
            "batch_split_mismatch": 0,
        }
        self.max_workers = 2
        self.batch_size = 4
        self.max_batch_length = 800
        self.max_text_size_for_batch = 200
        self.chunk_size = 1200
        self.cancel_event = threading.Event()

    def _save_cache(self, force: bool = False):
        return


class TranslatorTests(unittest.TestCase):
    def test_smart_split_text(self):
        text = "第一段。第二段！\n第三段？第四段。"
        parts = JaZhTranslator._smart_split_text(text, chunk_size=8)
        self.assertTrue(len(parts) >= 2)
        self.assertEqual("".join(p.replace("\n", "") for p in parts), text.replace("\n", ""))

    def test_translate_batch_dedup(self):
        t = DummyTranslator()
        calls = {"n": 0}

        def fake_call(text, max_retries=3, text_separator=None):
            calls["n"] += 1
            return f"ZH:{text}"

        t._call_deepseek = fake_call  # type: ignore
        res = t.translate_batch(["A", "A", "B"], batch_size=1)
        self.assertEqual(res["A"], "ZH:A")
        self.assertEqual(res["B"], "ZH:B")
        self.assertEqual(calls["n"], 2)

    def test_cancel_event(self):
        t = DummyTranslator()
        t.cancel_event.set()
        with self.assertRaises(RuntimeError):
            t._translate_chunk("test")

    def test_batch_json_path(self):
        t = DummyTranslator()
        t._call_deepseek_batch_json = lambda batch, max_retries=2: [f"ZH:{x}" for x in batch]  # type: ignore
        t._call_deepseek = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not be called"))  # type: ignore
        res = t.translate_batch(["A", "B"], batch_size=4)
        self.assertEqual(res["A"], "ZH:A")
        self.assertEqual(res["B"], "ZH:B")

    def test_fast_fail_502_not_swallowed(self):
        t = DummyTranslator()
        t.cancel_event = threading.Event()
        t.api_key = "x"
        t.api_url = "http://example.com/v1/chat/completions"
        t.model = "m"
        t.temperature = 0.1
        t.top_p = None
        t.frequency_penalty = None
        t.extract_glossary = False
        t.session = mock.Mock()
        resp = mock.Mock()
        resp.status_code = 502
        resp.raise_for_status = mock.Mock()
        t.session.post.return_value = resp

        with self.assertRaises(FastFailError):
            t._call_deepseek("abc")

    def test_replace_glossary_thread_safe(self):
        t = DummyTranslator()
        with tempfile.TemporaryDirectory() as d:
            t.glossary_path = os.path.join(d, "glossary.json")
            t.replace_glossary({"A": "甲"})
            self.assertIn("Item", t.glossary)
            self.assertEqual(t.glossary["Item"][0]["original"], "A")
            self.assertEqual(t.glossary["Item"][0]["translation"], "甲")

    def test_normalize_glossary_payload_flat_and_object(self):
        payload = {
            "勇者": "Hero",
            "王都": {"dst": "Royal Capital", "info": "地名"},
        }
        normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["conflicts"], 0)
        self.assertEqual(len(normalized["Item"]), 2)

    def test_normalize_glossary_payload_categorized_and_conflict_keep_old(self):
        payload = {
            "Person": [
                {"original": "アリス", "translation": "爱丽丝"},
                {"original": "アリス", "translation": "艾莉丝"},
            ],
            "Location": [{"src": "王都", "dst": "王都"}],
        }
        normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["conflicts"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(normalized["Person"][0]["translation"], "爱丽丝")

    def test_atomic_write_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "glossary.json")
            JaZhTranslator._atomic_write_json(path, {"Item": [{"original": "A", "translation": "甲"}]})
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertIn("Item", data)
            self.assertEqual(data["Item"][0]["original"], "A")

    def test_select_glossary_entries_filters_by_context(self):
        t = DummyTranslator()
        t.enable_glossary = True
        t.glossary_categories = ["Person", "Location", "Org", "Item", "Skill", "Creature"]
        t.glossary = {
            "Person": [{"original": "アリス", "translation": "爱丽丝"}],
            "Location": [{"original": "王都", "translation": "王都"}],
            "Org": [],
            "Item": [],
            "Skill": [],
            "Creature": [],
        }
        selected = t._select_glossary_entries("アリスは王都へ行く")
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]["original"], "アリス")
        self.assertEqual(selected[1]["original"], "王都")

    def test_select_glossary_entries_respects_max_terms(self):
        t = DummyTranslator()
        t.enable_glossary = True
        t.glossary_categories = ["Person", "Location", "Org", "Item", "Skill", "Creature"]
        t.glossary = {
            "Person": [
                {"original": "A", "translation": "甲"},
                {"original": "B", "translation": "乙"},
                {"original": "C", "translation": "丙"},
            ],
            "Location": [],
            "Org": [],
            "Item": [],
            "Skill": [],
            "Creature": [],
        }
        selected = t._select_glossary_entries("A B C", max_terms=2)
        self.assertEqual(len(selected), 2)

    def test_merge_new_terms_into_glossary_keep_old_and_preserve_source(self):
        t = DummyTranslator()
        t.glossary_categories = ["Person", "Location", "Org", "Item", "Skill", "Creature"]
        t.glossary = {
            "Person": [{"original": "アリス", "translation": "爱丽丝"}],
            "Location": [],
            "Org": [],
            "Item": [],
            "Skill": [],
            "Creature": [],
        }
        with tempfile.TemporaryDirectory() as d:
            t.glossary_path = os.path.join(d, "glossary.json")
            added = t._merge_new_terms_into_glossary(
                [
                    {"src": "アリス", "dst": "艾莉丝", "category": "Person", "source": "auto"},
                    {"src": "剣聖", "dst": "剑圣", "category": "Person", "info": "称号", "source": "auto"},
                ]
            )
            self.assertEqual(added, 1)
            self.assertEqual(t.glossary["Person"][0]["translation"], "爱丽丝")
            self.assertEqual(t.glossary["Person"][1]["original"], "剣聖")
            self.assertEqual(t.glossary["Person"][1]["source"], "auto")
            self.assertEqual(t.glossary["Person"][1]["info"], "称号")

    def test_merge_new_terms_into_glossary_upgrades_flat_schema(self):
        t = DummyTranslator()
        t.glossary_categories = ["Person", "Location", "Org", "Item", "Skill", "Creature"]
        t.glossary = {"王都": "王都"}
        with tempfile.TemporaryDirectory() as d:
            t.glossary_path = os.path.join(d, "glossary.json")
            added = t._merge_new_terms_into_glossary(
                [{"src": "ギルド", "dst": "公会", "category": "Org", "source": "auto"}]
            )
            self.assertEqual(added, 1)
            self.assertIn("Item", t.glossary)
            self.assertIn("Org", t.glossary)
            self.assertEqual(t.glossary["Item"][0]["original"], "王都")
            self.assertEqual(t.glossary["Org"][0]["original"], "ギルド")


class AppLogicTests(unittest.TestCase):
    def test_is_translatable_prefers_japanese(self):
        self.assertTrue(App._is_translatable("こんにちは"))
        self.assertTrue(App._is_translatable("漢字だけ"))
        self.assertFalse(App._is_translatable("Hello world"))

    def test_multi_anchor_node_replacement(self):
        html = '<p>前文 <a href="a">链接A</a> 中间 <a href="b">链接B</a> 后文</p>'
        soup = BeautifulSoup(html, "html.parser")
        p = soup.find("p")
        nodes = []
        for node in p.find_all(string=True):
            raw = str(node).strip()
            if raw in {"前文", "中间", "后文", "链接A", "链接B"}:
                nodes.append((node, raw))

        mapping = {
            "前文": "前文ZH",
            "中间": "中间ZH",
            "后文": "后文ZH",
            "链接A": "链接AZH",
            "链接B": "链接BZH",
        }
        for node, original in nodes:
            node.replace_with(mapping[original])

        self.assertIn('href="a"', str(soup))
        self.assertIn('href="b"', str(soup))
        self.assertIn("链接AZH", str(soup))
        self.assertIn("链接BZH", str(soup))


if __name__ == "__main__":
    unittest.main()
