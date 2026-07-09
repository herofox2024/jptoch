import json
import os
import shutil
import sys
import threading
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import requests
import translation_quality as tq
from bs4 import BeautifulSoup
from ebooklib import ITEM_DOCUMENT, epub

from epub_io import (
    _fix_toc_uids,
    add_translation_notice_page,
    apply_toc_translations,
    extract_toc_titles,
    extract_visible_text,
    iter_text_nodes,
    load_book,
    save_book,
)
from style_detector import detect_novel_style, resolve_style_selection
from text_utils import is_translatable
from translator import FastFailError, JaZhTranslator, BatchJsonResult, TranslationIncompleteError
from glossary_store import rebuild_glossary_index
from provider_registry import normalize_api_url, provider_default_model, provider_default_url
from provider_client import apply_payload_options, is_content_moderation_http_error
from quality_rules import is_suspicious_translation_pair
from translation_cache import atomic_write_json, load_json_file
from experimental.qml_v4.backend.diagnostics import build_redacted_config_snapshot
from experimental.qml_v4.backend.book_translation_service import (
    apply_translations_to_book,
    build_book_text_plan,
    build_toc_translation_map,
    scan_japanese_residue_in_docs,
)
from experimental.qml_v4.backend.pipeline import (
    PipelineContext,
    StyleDetectStage,
    TranslationPipeline,
)
from style_detector import StyleDetectionResult


@contextmanager
def temp_test_dir():
    root = Path(__file__).resolve().parent / "_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield str(path)
    finally:
        shutil.rmtree(path, ignore_errors=True)


class FakeEpubItem:
    def __init__(self, html: str, item_type=ITEM_DOCUMENT, media_type="application/xhtml+xml", file_name="content.xhtml"):
        self._html = html.encode("utf-8")
        self._item_type = item_type
        self.media_type = media_type
        self.file_name = file_name

    def get_type(self):
        return self._item_type

    def get_content(self):
        return self._html


class FakeEpubBook:
    def __init__(self, html: str, **item_kwargs):
        self.item = FakeEpubItem(html, **item_kwargs)

    def get_items(self):
        return [self.item]


class DummyTranslator(JaZhTranslator):
    def __init__(self):
        self.provider = "deepseek"
        self.model = "deepseek-v4-flash"
        self.api_key = "x"
        self.enable_glossary = True
        self.extract_glossary = False
        self.enable_thinking = False
        self.enable_proofread = False
        self.proofread_genre = "general"
        self.proofread_tone = "neutral"
        self.proofread_model = None
        self.proofread_provider = None
        self.proofread_api_key = None
        self._proofread_api_url = None
        self.prompt_extra_instruction = ""
        self.enable_prompt_examples = True
        self.glossary_categories = ["Person", "Location", "Org", "Item", "Skill", "Creature"]
        self._glossary_index = {}
        self.glossary = {}
        self.cache = {}
        self._cache_dirty = False
        self._save_counter = 0
        self._cache_lock = threading.RLock()
        self._stats_lock = threading.Lock()
        self._glossary_prompt_max_terms = 120
        self._output_format_data = None
        self._extraction_prompt_data = None
        self.stats = {
            "api_requests_total": 0,
            "batch_total": 0,
            "batch_json_success": 0,
            "batch_json_partial_success": 0,
            "batch_partial_retry": 0,
            "batch_fallback": 0,
            "batch_split_mismatch": 0,
            "batch_json_parse_fail": 0,
            "truncation_continuation": 0,
            "proofread_suspicious": 0,
            "proofread_fixed": 0,
            "proofread_rejected": 0,
        }
        self.max_workers = 2
        self.batch_size = 4
        self.max_batch_length = 800
        self.max_text_size_for_batch = 200
        self.chunk_size = 1200
        self.top_p = None
        self.frequency_penalty = None
        self.temperature = 0.3
        self.api_url = "http://example.com/v1/chat/completions"
        self.cancel_event = threading.Event()

    def _save_cache(self, force: bool = False):
        return


class ExtractedModuleTests(unittest.TestCase):
    def test_translation_quality_module_matches_translator_entrypoints(self):
        text = "\u9003\u3052\u308b"
        self.assertEqual(tq.has_blocking_japanese_residue(text), JaZhTranslator.has_blocking_japanese_residue(text))
        self.assertEqual(tq.is_incomplete_translation(text, text), JaZhTranslator._is_incomplete_translation(text, text))
        self.assertEqual(tq.extract_japanese_residue_fragments(text), JaZhTranslator.japanese_residue_fragments(text))

    def test_postprocess_repairs_known_katakana_item_name(self):
        samples = [
            (
                "回来的妻子，手里拿着一个叫作\"チロリ\"的烫酒壶。",
                "回来的妻子，手里拿着一个烫酒壶。",
            ),
            (
                "チロリ的酒也喝光了。",
                "烫酒壶里的酒也喝光了。",
            ),
        ]
        for raw, expected in samples:
            with self.subTest(raw=raw):
                repaired = tq.postprocess_translation("source", raw)
                self.assertEqual(repaired, expected)
                self.assertFalse(tq.has_blocking_japanese_residue(repaired))

    def test_provider_client_detects_moderation_and_applies_payload_options(self):
        payload = {}
        apply_payload_options(payload, "longcat", enable_thinking=False)
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})

        response = requests.Response()
        response.status_code = 400
        response._content = b'{"error":{"code":"security_audit_fail"}}'
        error = requests.exceptions.HTTPError(response=response)
        self.assertTrue(is_content_moderation_http_error(error))

    def test_translation_cache_json_helpers_roundtrip(self):
        with temp_test_dir() as tmp:
            path = Path(tmp) / "cache.json"
            atomic_write_json(path, {"hello": "world"})
            self.assertEqual(load_json_file(path, {}), {"hello": "world"})
            self.assertEqual(load_json_file(Path(tmp) / "missing.json", {"fallback": True}), {"fallback": True})


class RealEpubFixtureTests(unittest.TestCase):
    FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_japanese_fixture.epub"

    def test_real_epub_fixture_translates_saves_and_reloads(self):
        book = load_book(str(self.FIXTURE), try_repair=False)
        docs = list(iter_text_nodes(book))
        toc_titles = extract_toc_titles(book)
        plan = build_book_text_plan(docs, toc_titles)

        self.assertIn("\u543e\u8f29\u306f\u732b\u3067\u3042\u308b\u3002", plan.all_texts)
        self.assertIn("\u540d\u524d\u306f\u307e\u3060\u7121\u3044\u3002", plan.all_texts)
        self.assertIn("\u7b2c\u4e00\u7ae0 \u732b\u306e\u63a8\u7406", plan.all_texts)

        translations = {
            "\u5b9f\u4f8bEPUB\u30c6\u30b9\u30c8": "\u5b9e\u4f8b EPUB \u6d4b\u8bd5",
            "\u7b2c\u4e00\u7ae0 \u732b\u306e\u63a8\u7406": "\u7b2c\u4e00\u7ae0 \u732b\u7684\u63a8\u7406",
            "\u543e\u8f29\u306f\u732b\u3067\u3042\u308b\u3002": "\u6211\u662f\u4e00\u53ea\u732b\u3002",
            "\u540d\u524d\u306f\u307e\u3060\u7121\u3044\u3002": "\u8fd8\u6ca1\u6709\u540d\u5b57\u3002",
        }
        ordered_results = [translations.get(text) for text in plan.all_texts]

        apply_translations_to_book(
            plan,
            translations,
            ordered_results,
            lambda value: value,
            lambda _value: False,
        )
        for item, soup, _ in docs:
            item.set_content(str(soup).encode("utf-8"))

        toc_translations = build_toc_translation_map(
            plan,
            translations,
            ordered_results,
            lambda value: value,
            lambda _value: False,
        )
        apply_toc_translations(book, toc_translations)
        book.set_title(translations["\u5b9f\u4f8bEPUB\u30c6\u30b9\u30c8"])
        add_translation_notice_page(book, "\u672c\u4e66\u7531 AI \u65e5\u8bd1\u4e2d\u6d4b\u8bd5\u6d41\u7a0b\u751f\u6210\u3002")

        with temp_test_dir() as tmp:
            out_path = Path(tmp) / "translated-fixture.epub"
            save_book(str(out_path), book, chinese_mode=True)
            self.assertGreater(out_path.stat().st_size, 0)
            reloaded = load_book(str(out_path), try_repair=False)

        reloaded_docs = list(iter_text_nodes(reloaded))
        visible_text = "\n".join(
            extract_visible_text(tag)
            for _, _, tags in reloaded_docs
            for tag in tags
        )
        self.assertIn("\u6211\u662f\u4e00\u53ea\u732b\u3002", visible_text)
        self.assertIn("\u8fd8\u6ca1\u6709\u540d\u5b57\u3002", visible_text)
        self.assertIn("\u672c\u4e66\u7531 AI \u65e5\u8bd1\u4e2d\u6d4b\u8bd5\u6d41\u7a0b\u751f\u6210\u3002", visible_text)
        self.assertIn("\u7b2c\u4e00\u7ae0 \u732b\u7684\u63a8\u7406", extract_toc_titles(reloaded))
        self.assertFalse(JaZhTranslator.has_blocking_japanese_residue(visible_text))


class PipelineTests(unittest.TestCase):
    def test_style_detect_stage_uses_extra_title_and_resolves_manual_style(self):
        detected = StyleDetectionResult(genre="general", tone="neutral", confidence=42, reason="fixture")
        ctx = PipelineContext(
            config={"proofread_genre": "mystery", "proofread_tone": "light"},
            texts=["sample"],
            extra={"title": "fixture-title.epub", "toc_titles": ["Chapter 1"]},
        )

        with mock.patch("style_detector.detect_novel_style", return_value=detected) as detect_mock:
            out = TranslationPipeline().add_stage(StyleDetectStage()).run(ctx)

        detect_mock.assert_called_once()
        self.assertEqual(detect_mock.call_args.kwargs["title"], "fixture-title.epub")
        self.assertEqual(out.detected_style, detected)
        self.assertEqual(out.proofread_style.genre, "mystery")
        self.assertEqual(out.proofread_style.tone, "light")
        self.assertEqual(out.proofread_style.confidence, 100)

    def test_pipeline_skips_disabled_stages(self):
        ctx = PipelineContext(config={}, texts=["sample"], extra={"title": "unused"})
        out = TranslationPipeline().add_stage(StyleDetectStage(enabled=False)).run(ctx)
        self.assertIs(out, ctx)
        self.assertIsNone(out.proofread_style)


class TranslatorTests(unittest.TestCase):
    def test_translated_filename_removes_model_explanation_notes(self):
        qml_root = Path(__file__).resolve().parents[1] / "experimental" / "qml_v4"
        if str(qml_root) not in sys.path:
            sys.path.insert(0, str(qml_root))
        from backend.translate_bridge import _clean_translated_filename_candidate

        candidate = (
            "恐怖 角川恐怖文库精选集(恒川光太郎、坂东真砂子、"
            "宇佐美诚（颇 _ 或依意译处理为其它合适名，但没更多信息，这里保留“诚”的翻译 ）、"
            "小林泰三、竹本健治、小松左京等)"
        )

        cleaned = _clean_translated_filename_candidate(candidate)

        self.assertEqual(
            cleaned,
            "恐怖 角川恐怖文库精选集(恒川光太郎、坂东真砂子、宇佐美诚、小林泰三、竹本健治、小松左京等)",
        )
        self.assertNotIn("或依意译", cleaned)
        self.assertNotIn("没更多信息", cleaned)

    def test_translated_toc_title_removes_mythology_explanation_notes(self):
        qml_root = Path(__file__).resolve().parents[1] / "experimental" / "qml_v4"
        if str(qml_root) not in sys.path:
            sys.path.insert(0, str(qml_root))
        from backend.translate_bridge import _clean_translated_toc_title

        candidate = (
            "尼俄泊（尼俄柏之穴的简写（译者注），尼俄柏是希腊神话中坦塔罗斯之女，"
            "因炫耀自己的子女，悲叹七子七女被阿波罗和阿尔忒弥斯射杀，"
            "悲痛永无止息，身体化作泉水，永远流动。） 恒川光太郎\n\n"
            "【前文（无需翻译）】\n《正月女》 坂东真砂子\n\n"
            "【后文（无需翻译）】\n《某个堕落者的死亡》 平山梦明"
        )

        cleaned = _clean_translated_toc_title(candidate)

        self.assertEqual(cleaned, "尼俄泊 恒川光太郎")
        self.assertNotIn("希腊神话", cleaned)
        self.assertNotIn("永远流动", cleaned)
        self.assertNotIn("前文", cleaned)
        self.assertNotIn("后文", cleaned)

    def test_fix_toc_uids_preserves_section_children_without_uid(self):
        section = epub.Section("Magazine Excerpt", "text/part0003.html")
        children = [
            epub.Link("text/part0004.html", "Chapter 1", "num_2"),
            epub.Link("text/part0005.html", "Chapter 2", None),
        ]
        book = type("Book", (), {"toc": [(section, children)]})()
        original_titles = extract_toc_titles(book)

        fixed = _fix_toc_uids(book.toc)
        fixed_book = type("Book", (), {"toc": fixed})()

        self.assertEqual(len(fixed), 1)
        fixed_section, fixed_children = fixed[0]
        self.assertIs(fixed_section, section)
        self.assertEqual(len(fixed_children), 2)
        self.assertEqual(fixed_children[0].uid, "num_2")
        self.assertIsNotNone(fixed_children[1].uid)
        self.assertEqual(extract_toc_titles(fixed_book), original_titles)

    def test_fix_toc_uids_preserves_empty_section(self):
        section = epub.Section("Empty Section", "text/empty.html")

        fixed = _fix_toc_uids([(section, [])])

        self.assertEqual(len(fixed), 1)
        self.assertIs(fixed[0][0], section)
        self.assertEqual(fixed[0][1], [])

    def test_add_translation_notice_page_inserts_standalone_spine_item(self):
        book = epub.EpubBook()
        chapter = epub.EpubHtml(uid="chap1", file_name="chap1.xhtml", title="Chapter 1")
        chapter.content = "<html><body><p>正文</p></body></html>"
        book.add_item(chapter)
        book.spine = [chapter]

        add_translation_notice_page(book, "提示 A\n提示 B")

        notice_items = [
            item for item in book.get_items()
            if item.get_id() == "ai-jp-zh-translation-notice"
        ]
        self.assertEqual(len(notice_items), 1)
        self.assertIs(book.spine[0], notice_items[0])
        self.assertIn("提示 A".encode("utf-8"), notice_items[0].content)
        self.assertIn("提示 B".encode("utf-8"), notice_items[0].content)
        self.assertIs(book.spine[1], chapter)

    def test_add_translation_notice_page_inserts_after_cover(self):
        book = epub.EpubBook()
        cover = epub.EpubHtml(uid="cover", file_name="cover.xhtml", title="Cover")
        cover.content = "<html><body><p>Cover</p></body></html>"
        chapter = epub.EpubHtml(uid="chap1", file_name="chap1.xhtml", title="Chapter 1")
        chapter.content = "<html><body><p>正文</p></body></html>"
        book.add_item(cover)
        book.add_item(chapter)
        book.spine = [cover, chapter]

        add_translation_notice_page(book, "提示")

        self.assertIs(book.spine[0], cover)
        self.assertEqual(book.spine[1].get_id(), "ai-jp-zh-translation-notice")
        self.assertIs(book.spine[2], chapter)

    def test_add_translation_notice_page_inserts_after_image_only_cover(self):
        book = epub.EpubBook()
        cover = epub.EpubHtml(uid="page001", file_name="Text/part0001.xhtml", title="")
        cover.content = '<html><body><img src="../Images/cover.jpg" alt=""/></body></html>'
        chapter = epub.EpubHtml(uid="chap1", file_name="chap1.xhtml", title="Chapter 1")
        chapter.content = "<html><body><p>正文</p></body></html>"
        book.add_item(cover)
        book.add_item(chapter)
        book.spine = [cover, chapter]

        add_translation_notice_page(book, "提示")

        self.assertIs(book.spine[0], cover)
        self.assertEqual(book.spine[1].get_id(), "ai-jp-zh-translation-notice")
        self.assertIs(book.spine[2], chapter)

    def test_add_translation_notice_page_resolves_string_spine_cover(self):
        book = epub.EpubBook()
        cover = epub.EpubHtml(uid="page001", file_name="Text/part0001.xhtml", title="")
        cover.content = "<html><body><svg><image href='../Images/cover.jpg'/></svg></body></html>"
        chapter = epub.EpubHtml(uid="chap1", file_name="chap1.xhtml", title="Chapter 1")
        chapter.content = "<html><body><p>正文</p></body></html>"
        book.add_item(cover)
        book.add_item(chapter)
        book.spine = ["page001", "chap1"]

        add_translation_notice_page(book, "提示")

        self.assertEqual(book.spine[0], "page001")
        self.assertEqual(book.spine[1].get_id(), "ai-jp-zh-translation-notice")
        self.assertEqual(book.spine[2], "chap1")

    def test_real_epub_notice_page_roundtrip_stays_after_image_cover(self):
        def spine_ids(book):
            result = []
            for entry in list(getattr(book, "spine", []) or []):
                candidate = entry[0] if isinstance(entry, tuple) and entry else entry
                if isinstance(candidate, str):
                    result.append(candidate)
                elif hasattr(candidate, "get_id"):
                    result.append(candidate.get_id())
            return result

        png_1x1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
            b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00"
            b"\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        book = epub.EpubBook()
        book.set_identifier("real-notice-test")
        book.set_title("Real Notice Test")
        book.set_language("ja")
        cover_img = epub.EpubItem(
            uid="cover-image",
            file_name="Images/cover.png",
            media_type="image/png",
            content=png_1x1,
        )
        cover = epub.EpubHtml(uid="page001", file_name="Text/page001.xhtml", title="")
        cover.set_content(b'<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="../Images/cover.png" alt=""/></body></html>')
        chapter = epub.EpubHtml(uid="chap1", file_name="Text/chapter.xhtml", title="Chapter")
        chapter.set_content("<html><body><p>本文です。</p></body></html>".encode("utf-8"))
        book.add_item(cover_img)
        book.add_item(cover)
        book.add_item(chapter)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [cover, chapter]
        book.toc = [epub.Link("Text/chapter.xhtml", "Chapter", "chap1")]

        add_translation_notice_page(book, "notice")

        with temp_test_dir() as d:
            path = os.path.join(d, "notice.epub")
            save_book(path, book, chinese_mode=True)
            loaded = load_book(path, try_repair=False)

        ids = spine_ids(loaded)
        self.assertGreaterEqual(len(ids), 3)
        self.assertEqual(ids[0], "page001")
        self.assertEqual(ids[1], "ai-jp-zh-translation-notice")

    def test_real_epub_save_handles_body_direct_text_node(self):
        book = epub.EpubBook()
        book.set_identifier("direct-text-test")
        book.set_title("Direct Text Test")
        book.set_language("ja")
        chapter = epub.EpubHtml(uid="chap1", file_name="Text/chapter.xhtml", title="Chapter")
        chapter.set_content("<html><body>直接テキストです。</body></html>".encode("utf-8"))
        book.add_item(chapter)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = [chapter]
        book.toc = [epub.Link("Text/chapter.xhtml", "Chapter", "chap1")]

        with temp_test_dir() as d:
            path = os.path.join(d, "direct-text.epub")
            save_book(path, book, chinese_mode=True)
            self.assertTrue(os.path.getsize(path) > 0)
            loaded = load_book(path, try_repair=False)

        self.assertTrue(getattr(loaded, "spine", None))

    def test_qml_diagnostic_config_snapshot_redacts_api_keys(self):
        snapshot = build_redacted_config_snapshot(
            {
                "provider": "deepseek",
                "api_key": "sk-1234567890",
                "proofread_api_key": "short",
                "model": "deepseek-v4-flash",
            }
        )
        payload = json.dumps(snapshot, ensure_ascii=False)

        self.assertNotIn("api_key", snapshot)
        self.assertNotIn("proofread_api_key", snapshot)
        self.assertEqual(snapshot["api_key_masked"], "sk-1***7890")
        self.assertEqual(snapshot["proofread_api_key_masked"], "*****")
        self.assertEqual(snapshot["provider"], "deepseek")
        self.assertNotIn("sk-1234567890", payload)
        self.assertNotIn("short", payload)

    def test_iter_text_nodes_keeps_normal_paragraph_mode_and_skips_ruby_rt(self):
        html = """
        <html><body>
          <p><ruby>能<rt>のう</rt>面<rt>めん</rt></ruby>島へ行く。</p>
          <span>これは段落外なので通常モードでは拾わない。</span>
        </body></html>
        """
        docs = list(iter_text_nodes(FakeEpubBook(html)))
        tags = docs[0][2]

        self.assertEqual(len(tags), 1)
        self.assertEqual(extract_visible_text(tags[0]), "能面島へ行く。")

    def test_iter_text_nodes_falls_back_to_body_br_layout_and_preserves_anchor(self):
        long_line = "これは本文です。" * 30
        html = f"""
        <html><body>
          <span id="toc-001"></span>{long_line}<br/>
          <ruby>久<rt>く</rt>堂<rt>どう</rt></ruby>は尾根を歩いた。<br/>
        </body></html>
        """
        docs = list(iter_text_nodes(FakeEpubBook(html)))
        tags = docs[0][2]
        texts = [extract_visible_text(tag) for tag in tags]

        self.assertGreaterEqual(len(tags), 2)
        self.assertEqual(tags[0].get("id"), "toc-001")
        self.assertEqual(texts[0], long_line)
        self.assertEqual(texts[1], "久堂は尾根を歩いた。")

    def test_iter_text_nodes_accepts_text_html_items(self):
        html = "<html><body><p>これはHTML本文です。</p></body></html>"
        docs = list(iter_text_nodes(FakeEpubBook(
            html,
            item_type=0,
            media_type="text/html",
            file_name="content.html",
        )))

        self.assertEqual(len(docs), 1)
        self.assertEqual(extract_visible_text(docs[0][2][0]), "これはHTML本文です。")

    def test_iter_text_nodes_extracts_short_inbook_toc_links(self):
        html = """
        <html><body>
          <span>\u76ee\u6b21</span><br/>
          <a href="content_1.html#toc-001">\u7b2c\u4e00\u7ae0\u3000\u63a2\u5075\u529b</a><br/>
          <a href="content_2.html#toc-002">\u7b2c\u4e8c\u7ae0\u3000\u306a\u3093\u3060\u304b\u3059\u3054\u3044\u3053\u3068\u306b\u306a\u3063\u3066\u304d\u307e\u3057\u305f</a><br/>
          <a href="content_3.html#toc-003"><ruby>\u524d<rt>\u307e\u3048</rt>\u53e3\u4e0a<rt>\u3053\u3046\u3058\u3087\u3046</rt></ruby></a><br/>
        </body></html>
        """
        docs = list(iter_text_nodes(FakeEpubBook(
            html,
            item_type=0,
            media_type="text/html",
            file_name="content.html",
        )))
        tags = docs[0][2]

        self.assertEqual([tag.name for tag in tags], ["a", "a", "a"])
        self.assertEqual(tags[0].get("href"), "content_1.html#toc-001")
        self.assertEqual(extract_visible_text(tags[2]), "\u524d\u53e3\u4e0a")

    def test_detect_novel_style_handles_light_mystery(self):
        result = detect_novel_style(
            title="女学生探偵シリーズ",
            toc_titles=["第一章 探偵力", "第二章 密室の謎", "第三章 アリバイ"],
            samples=["「えっ、なんでですか先輩！」事件の犯人はまだ分からない。"],
        )

        self.assertEqual(result.genre, "mystery")
        self.assertEqual(result.tone, "light")
        self.assertGreaterEqual(result.confidence, 60)

    def test_detect_novel_style_handles_historical_mystery(self):
        result = detect_novel_style(
            title="玄白歌麿捕物帳",
            toc_titles=["第一章 江戸の町火消し", "第二章 奉行所の同心"],
            samples=[
                "旗本の屋敷を訪ねた辰造は、町奉行所の与力から事件の仔細を聞いた。",
                "『か組』の纏持ちと岡っ引きが番屋で証言を交わしていた。",
            ],
        )

        self.assertEqual(result.genre, "historical_mystery")
        self.assertGreaterEqual(result.confidence, 60)

    def test_resolve_style_selection_manual_override(self):
        detected = detect_novel_style(
            title="宇宙船とAI",
            toc_titles=["第一章 量子実験"],
            samples=["研究所のロボットが静かに起動した。"],
        )
        resolved = resolve_style_selection("mystery", "light", detected)

        self.assertEqual(resolved.genre, "mystery")
        self.assertEqual(resolved.tone, "light")
        self.assertEqual(resolved.confidence, 100)

    def test_translation_and_proofread_prompts_combine_genre_and_tone(self):
        t = DummyTranslator()
        t.proofread_genre = "mystery"
        t.proofread_tone = "light"

        proofread_prompt = t._build_proofread_system_prompt()
        batch_prompt = t._build_batch_system_prompt()
        single_prompt = t._build_style_guidance("translation")

        for prompt in (proofread_prompt, batch_prompt, single_prompt):
            self.assertIn("推理小说", prompt)
            self.assertIn("轻小说口吻", prompt)
            self.assertIn("不要替读者解释谜题", prompt)
            self.assertIn("对白要自然", prompt)
            self.assertIn("示例引导", prompt)

    def test_custom_prompt_instruction_is_included_in_translation_and_proofread(self):
        t = DummyTranslator()
        t.proofread_genre = "historical_mystery"
        t.prompt_extra_instruction = "保留江户时代称谓，不要现代网络口吻。"

        proofread_prompt = t._build_proofread_system_prompt()
        translation_prompt = t._build_style_guidance("translation")
        preview = t.build_prompt_preview()

        for prompt in (proofread_prompt, translation_prompt, preview):
            self.assertIn("用户补充要求", prompt)
            self.assertIn("保留江户时代称谓", prompt)

    def test_smart_split_text(self):
        text = "第一段。第二段！\n第三段？第四段。"
        parts = JaZhTranslator._smart_split_text(text, chunk_size=8)
        self.assertTrue(len(parts) >= 2)
        self.assertEqual("".join(p.replace("\n", "") for p in parts), text.replace("\n", ""))

    def test_translate_batch_dedup(self):
        t = DummyTranslator()
        t.max_workers = 1
        calls = {"n": 0}
        progress = []

        def fake_call(text, max_retries=3, text_separator=None, prev_text=None, next_text=None):
            calls["n"] += 1
            return f"ZH:{text}"

        t._call_deepseek = fake_call  # type: ignore
        res = t.translate_batch(["A", "A", "B"], batch_size=1, progress_callback=lambda done, total: progress.append((done, total)))
        self.assertEqual(res["A"], "ZH:A")
        self.assertEqual(res["B"], "ZH:B")
        self.assertEqual(calls["n"], 2)
        self.assertIn((2, 3), progress)
        self.assertEqual(progress[-1], (3, 3))

    def test_context_sensitive_short_text_keeps_ordered_results(self):
        t = DummyTranslator()
        t.max_workers = 1
        t.max_batch_length = 1

        def fake_call(text, max_retries=3, text_separator=None, prev_text=None, next_text=None):
            if text == "え？":
                if prev_text and "太郎" in prev_text:
                    return "咦，是太郎？"
                if prev_text and "花子" in prev_text:
                    return "咦，是花子？"
            return "中文旁白"

        t._call_deepseek = fake_call  # type: ignore
        texts = ["太郎が来た。", "え？", "花子が来た。", "え？"]
        res = t.translate_batch(texts, batch_size=1, context_texts=texts)

        self.assertEqual(res["え？"], "咦，是太郎？")
        self.assertEqual(t.last_ordered_results[1], "咦，是太郎？")
        self.assertEqual(t.last_ordered_results[3], "咦，是花子？")

    def test_glossary_policy_controls_proofread_enforcement(self):
        t = DummyTranslator()
        t.glossary = {
            "Item": [
                {"original": "グラス", "translation": "杯子", "policy": "reference"},
                {"original": "サングラス", "translation": "墨镜", "policy": "force"},
                {"original": "ルビ", "translation": "注音", "policy": "contextual"},
                {"original": "API", "translation": "应用接口", "policy": "preserve"},
                {"original": "バグ", "translation": "故障", "policy": "ignore"},
            ]
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)

        reference_entries = t._select_proofread_glossary_entries("グラスを置いた。")
        force_entries = t._select_proofread_glossary_entries("サングラスをかけた。")
        contextual_entries = t._select_proofread_glossary_entries("ルビを見る。")
        preserve_entries = t._select_proofread_glossary_entries("APIを呼び出す。")
        prompt_entries = t._select_glossary_entries("バグが出た。")

        self.assertEqual(reference_entries, [])
        self.assertEqual(force_entries[0]["translation"], "墨镜")
        self.assertEqual(contextual_entries, [])
        self.assertEqual(preserve_entries[0]["original"], "API")
        self.assertIn("术语应保留原文", t._find_proofread_issues("APIを呼び出す。", "调用应用接口。")[0])
        self.assertEqual(prompt_entries, [])

    def test_cancel_event(self):
        t = DummyTranslator()
        t.cancel_event.set()
        with self.assertRaises(RuntimeError):
            t._translate_chunk("test")

    def test_batch_json_path(self):
        t = DummyTranslator()
        t._call_deepseek_batch_json = lambda batch, max_retries=2, prev_text=None, next_text=None: BatchJsonResult(
            translations=[f"ZH:{x}" for x in batch],
            new_terms=[],
            missing_indices=[],
            finish_reason="stop",
        )
        t._call_deepseek = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not be called"))  # type: ignore
        res = t.translate_batch(["A", "B"], batch_size=4)
        self.assertEqual(res["A"], "ZH:A")
        self.assertEqual(res["B"], "ZH:B")
        self.assertEqual(t.cache[t._cache_key("A")], "ZH:A")
        self.assertEqual(t.cache[t._cache_key("B")], "ZH:B")

    def test_batch_json_total_failure_falls_back_to_single_translation(self):
        t = DummyTranslator()
        t.max_workers = 1
        t.batch_size = 4
        t._call_deepseek_batch_json = lambda batch, max_retries=2, prev_text=None, next_text=None, item_contexts=None: BatchJsonResult(
            translations=None,
            new_terms=[],
            missing_indices=list(range(len(batch))),
            finish_reason="stop",
        )
        t._call_deepseek = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("delimiter fallback should not be called"))  # type: ignore
        single_calls = []

        def fake_translate_chunk(text, *args, **kwargs):
            single_calls.append(text)
            return f"SINGLE:{text}"

        t._translate_chunk = fake_translate_chunk  # type: ignore

        res = t.translate_batch(["A", "B", "C"], batch_size=4)

        self.assertEqual(res["A"], "SINGLE:A")
        self.assertEqual(res["B"], "SINGLE:B")
        self.assertEqual(res["C"], "SINGLE:C")
        self.assertEqual(single_calls, ["A", "B", "C"])
        self.assertEqual(t.stats.get("batch_fallback"), 1)

    def test_batch_json_parse_failure_retries_before_fallback(self):
        class FakeCancel:
            def is_set(self):
                return False

            def wait(self, _seconds):
                return False

        class FakeResponse:
            def __init__(self, content):
                self.status_code = 200
                self.url = "http://example.com/v1/chat/completions"
                self._content = content

            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": self._content}, "finish_reason": "stop"}]}

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def post(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return FakeResponse("not json")
                return FakeResponse('{"translations":[{"idx":0,"zh":"ZH:A"}],"new_terms":[]}')

        t = DummyTranslator()
        t.cancel_event = FakeCancel()
        t.session = FakeSession()

        result = t._call_deepseek_batch_json(["A"], max_retries=2)

        self.assertEqual(t.session.calls, 2)
        self.assertEqual(result.translations, ["ZH:A"])
        self.assertEqual(result.missing_indices, [])

    def test_translate_batch_does_not_write_original_when_retries_fail(self):
        t = DummyTranslator()
        src = "\u5f7c\u5973\u306f\u7b11\u3063\u305f\u3002"
        t.max_workers = 1
        t.batch_size = 1

        def fail_translate(*args, **kwargs):
            raise RuntimeError("rate limited")

        t._translate_chunk = fail_translate  # type: ignore

        with self.assertRaises(TranslationIncompleteError) as ctx:
            t.translate_batch([src], batch_size=1)

        self.assertIn(src, ctx.exception.failed_texts)
        self.assertNotIn(src, ctx.exception.partial_results)
        self.assertNotIn(t._cache_key(src), t.cache)
        self.assertEqual(t.stats.get("translation_incomplete"), 1)

    def test_translate_batch_ignores_bad_japanese_residue_cache_and_retries(self):
        t = DummyTranslator()
        src = "\u5f7c\u5973\u306f\u7b11\u3063\u305f\u3002"
        t.cache[t._cache_key(src)] = src
        t.max_workers = 1
        t.batch_size = 1
        t._translate_chunk = lambda text, prev_text=None, next_text=None: "\u5979\u7b11\u4e86\u3002"  # type: ignore

        res = t.translate_batch([src], batch_size=1)

        self.assertEqual(res[src], "\u5979\u7b11\u4e86\u3002")
        self.assertEqual(t.cache[t._cache_key(src)], "\u5979\u7b11\u4e86\u3002")

    def test_manual_cache_has_highest_priority_without_text_cache_reuse(self):
        t = DummyTranslator()
        src = "\u5f7c\u5973\u306f\u7b11\u3063\u305f\u3002"
        t.allow_text_cache_reuse = False
        t._manual_cache_loaded = True
        t._manual_cache = {
            t._manual_cache_key(src): {
                "source": src,
                "translation": "\u5979\u5fae\u5fae\u4e00\u7b11\u3002",
                "updated_at": 1,
            }
        }
        t._translate_chunk = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("should not call api"))  # type: ignore

        res = t.translate_batch([src], batch_size=1)

        self.assertEqual(res[src], "\u5979\u5fae\u5fae\u4e00\u7b11\u3002")
        self.assertEqual(t.cache[t._cache_key(src)], "\u5979\u5fae\u5fae\u4e00\u7b11\u3002")

    def test_cache_key_is_model_scoped(self):
        t = DummyTranslator()
        calls = {"n": 0}

        def fake_call(text, max_retries=3, text_separator=None, prev_text=None, next_text=None):
            calls["n"] += 1
            return f"{t.model}:{text}"

        t._call_deepseek = fake_call  # type: ignore
        self.assertEqual(t.translate("A"), "deepseek-v4-flash:A")
        self.assertEqual(t.translate("A"), "deepseek-v4-flash:A")
        self.assertEqual(calls["n"], 1)

        t.model = "other-model"
        self.assertEqual(t.translate("A"), "other-model:A")
        self.assertEqual(calls["n"], 2)

    def test_wenxin_provider_defaults(self):
        with temp_test_dir() as d:
            t = JaZhTranslator(
                api_key="test-key",
                provider="wenxin",
                glossary_path=os.path.join(d, "glossary.json"),
                cache_path=os.path.join(d, "cache.json"),
            )

            self.assertEqual(t.provider, "wenxin")
            self.assertEqual(t.api_url, "https://qianfan.baidubce.com/v2/chat/completions")
            self.assertEqual(t.model, "ernie-4.5-turbo-128k")

    def test_provider_registry_drives_translator_defaults(self):
        self.assertEqual(provider_default_url("longcat"), "https://api.longcat.chat/openai/v1/chat/completions")
        self.assertEqual(provider_default_model("longcat"), "LongCat-2.0")
        self.assertEqual(
            normalize_api_url("https://example.com/v1"),
            "https://example.com/v1/chat/completions",
        )
        self.assertEqual(
            JaZhTranslator._get_provider_default_url("longcat"),
            provider_default_url("longcat"),
        )

    def test_quality_rule_detects_suspicious_translation_pairs(self):
        self.assertTrue(is_suspicious_translation_pair("長い原文です。" * 3, "x"))
        self.assertTrue(is_suspicious_translation_pair("原文", "哈哈哈哈哈哈哈哈"))
        self.assertFalse(is_suspicious_translation_pair("彼女は笑った。", "她笑了。"))

    def test_discard_cache_writes_and_clear_texts(self):
        t = DummyTranslator()
        t._call_deepseek = lambda text, max_retries=3, text_separator=None, prev_text=None, next_text=None: f"ZH:{text}"  # type: ignore

        self.assertEqual(t.translate("A"), "ZH:A")
        self.assertIn(t._cache_key("A"), t.cache)

        removed = t.clear_cache_for_texts(["A", "A"])
        self.assertEqual(removed, 1)
        self.assertNotIn(t._cache_key("A"), t.cache)

        t.discard_cache_writes()
        self.assertEqual(t.translate("B"), "ZH:B")
        self.assertNotIn(t._cache_key("B"), t.cache)

    def test_proofread_detects_japanese_residue(self):
        t = DummyTranslator()
        issues = t._find_proofread_issues("彼女は笑った。", "她は笑った。")
        self.assertTrue(any("日文" in issue for issue in issues))

    def test_reading_puzzle_kana_runs_do_not_block_completion(self):
        samples = [
            (
                "小、日、死、轩、园、之、信、煮，这几个字之间本无任何关联。"
                "可若是只取每个字的首音连起来，便是コ、ニ、シ、ノ、ソ、ノ、シ、ニ。"
                "换成横排书写后，我试着从左往右读，就成了ニ、シ、ノ、ソ、ノ、シ、ニ、コ，"
                "一个名字赫然浮现了出来。"
            ),
            (
                "这串字符从左往右读的话，就是ク、ハ、ク、タ、ノ、ミ、マ、ス。"
                "把前后所有内容连起来，就是ニシノソノシニコクハクタノミマス。"
                "如此一来，便组成了一句表意完整的话。"
            ),
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertFalse(JaZhTranslator.has_blocking_japanese_residue(text))
                self.assertFalse(JaZhTranslator._is_incomplete_translation("source", text))
                self.assertEqual(JaZhTranslator.japanese_residue_fragments(text), [])

    def test_reading_puzzle_rule_does_not_allow_ordinary_kana_residue(self):
        text = "她は笑った。"
        self.assertTrue(JaZhTranslator.has_blocking_japanese_residue(text))
        self.assertTrue(JaZhTranslator._is_incomplete_translation("source", text))

    def test_pre_translate_strips_japanese_quotes(self):
        t = DummyTranslator()
        result = t._pre_translate("「はい」")
        self.assertEqual(result, "是的")

    def test_pre_translate_short_poetic_title(self):
        t = DummyTranslator()
        result = t._pre_translate("旅ゆけば")
        self.assertEqual(result, "旅行之中")
        self.assertFalse(JaZhTranslator._is_incomplete_translation("旅ゆけば", result))

    def test_short_quoted_text_same_as_source_is_not_incomplete(self):
        self.assertFalse(JaZhTranslator._is_incomplete_translation("「猿とな」", "「猿とな」"))
        self.assertFalse(JaZhTranslator.has_blocking_japanese_residue("「猿とな」"))

    def test_short_unquoted_japanese_same_as_source_is_incomplete(self):
        src = "\u9003\u3052\u308b"
        self.assertTrue(JaZhTranslator._is_incomplete_translation(src, src))

    def test_long_text_same_as_source_with_kana_is_still_incomplete(self):
        long_text = "彼女は笑った。そして走った。そして泣いた。"
        self.assertTrue(JaZhTranslator._is_incomplete_translation(long_text, long_text))
        self.assertTrue(JaZhTranslator.has_blocking_japanese_residue(long_text))

    def test_proofread_detects_glossary_mismatch(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [{"original": "アリス", "translation": "爱丽丝"}],
            "Location": [],
            "Org": [],
            "Item": [],
            "Skill": [],
            "Creature": [],
        }
        issues = t._find_proofread_issues("アリスは王都へ行った。", "阿丽丝去了王都。")
        self.assertTrue(any("アリス -> 爱丽丝" in issue for issue in issues))

    def test_proofread_ignores_punctuation_only_glossary_terms(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [],
            "Location": [],
            "Org": [],
            "Item": [
                {"original": "「", "translation": "「"},
                {"original": "」", "translation": "」"},
            ],
            "Skill": [],
            "Creature": [],
        }
        issues = t._find_proofread_issues("「待ってくれ。」", "等等。")
        self.assertEqual(issues, [])

    def test_proofread_repairs_only_suspicious_translation(self):
        t = DummyTranslator()
        t.enable_proofread = True
        t.max_workers = 1
        t.batch_size = 2
        t.max_batch_length = 100
        t.max_text_size_for_batch = 100
        t._call_deepseek_batch_json = lambda batch, max_retries=2, prev_text=None, next_text=None: BatchJsonResult(
            translations=["她は笑った。", "她笑了。"],
            new_terms=[],
            missing_indices=[],
            finish_reason="stop",
        )
        calls = {"n": 0}

        def fake_proofread(src, draft, issues):
            calls["n"] += 1
            return "她笑了。"

        t._proofread_translation = fake_proofread  # type: ignore
        details = []
        res = t.translate_batch(["彼女は笑った。", "彼女は笑った。二"], batch_size=2, proofread_callback=details.append)
        self.assertEqual(res["彼女は笑った。"], "她笑了。")
        self.assertEqual(res["彼女は笑った。二"], "她笑了。")
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["original"], "彼女は笑った。")
        self.assertEqual(details[0]["draft"], "她は笑った。")
        self.assertEqual(details[0]["revised"], "她笑了。")
        self.assertTrue(details[0]["japanese_residue"])


    def test_batch_proofread_repairs_multiple_suspicious_translations(self):
        t = DummyTranslator()
        t.enable_proofread = True
        t.max_workers = 1
        t.batch_size = 2
        t.max_batch_length = 100
        t.max_text_size_for_batch = 100
        srcs = [
            "\u5f7c\u5973\u306f\u7b11\u3063\u305f\u3002",
            "\u5f7c\u5973\u304c\u9814\u3044\u305f\u3002",
        ]
        drafts = [
            "\u5979\u306f\u7b11\u4e86\u3002",
            "\u5979\u304c\u70b9\u5934\u4e86\u3002",
        ]
        t._call_deepseek_batch_json = lambda batch, max_retries=2, prev_text=None, next_text=None, item_contexts=None: BatchJsonResult(
            translations=list(drafts),
            new_terms=[],
            missing_indices=[],
            finish_reason="stop",
        )
        batch_calls = []

        def fake_batch_proofread(items):
            batch_calls.append(items)
            return {
                items[0]["idx"]: "\u5979\u7b11\u4e86\u3002",
                items[1]["idx"]: "\u5979\u70b9\u4e86\u70b9\u5934\u3002",
            }

        t._proofread_translations_batch = fake_batch_proofread  # type: ignore
        t._proofread_translation = mock.Mock(side_effect=AssertionError("single proofread should not run"))

        details = []
        res = t.translate_batch(srcs, batch_size=2, proofread_callback=details.append)

        self.assertEqual(len(batch_calls), 1)
        self.assertEqual(len(batch_calls[0]), 2)
        self.assertEqual(res[srcs[0]], "\u5979\u7b11\u4e86\u3002")
        self.assertEqual(res[srcs[1]], "\u5979\u70b9\u4e86\u70b9\u5934\u3002")
        self.assertEqual(len(details), 2)
        self.assertEqual(t._proofread_translation.call_count, 0)

    def test_dynamic_limiter_reduces_workers_and_batch_size(self):
        t = DummyTranslator()
        t.max_workers = 10
        t.batch_size = 8

        t._record_dynamic_limit_event("HTTP 429", kind="rate")

        self.assertLess(t._current_dynamic_workers(), 10)
        self.assertLess(t._current_dynamic_batch_size(), 8)
        self.assertEqual(t.stats["rate_limit_events"], 1)
        self.assertEqual(t.stats["dynamic_limit_workers"], t._current_dynamic_workers())
        self.assertEqual(t.stats["dynamic_limit_batch_size"], t._current_dynamic_batch_size())

    def test_repeated_japanese_residue_across_different_sentences_skips_repeated_proofread(self):
        t = DummyTranslator()
        t.enable_proofread = True
        t.max_workers = 1
        t.batch_size = 3
        t.max_batch_length = 200
        t.max_text_size_for_batch = 100
        srcs = [
            "\u5f7c\u5973\u306f\u7b11\u3063\u305f\u3002",
            "\u5f7c\u5973\u306f\u9814\u3044\u305f\u3002",
            "\u5f7c\u5973\u306f\u8d70\u3063\u305f\u3002",
        ]
        drafts = [
            "\u5979\u4e0e\u304a\u304d\u306c\u8bf4\u8bdd\u3002",
            "\u5979\u89c1\u5230\u304a\u304d\u306c\u3002",
            "\u5979\u8ffd\u4e0a\u304a\u304d\u306c\u3002",
        ]
        t._call_deepseek_batch_json = lambda batch, max_retries=2, prev_text=None, next_text=None, item_contexts=None: BatchJsonResult(
            translations=list(drafts),
            new_terms=[],
            missing_indices=[],
            finish_reason="stop",
        )
        proofread_calls = []
        retranslate_calls = []
        residue_guidance_calls = []

        def fake_proofread(src, draft, issues, **kwargs):
            proofread_calls.append((src, draft, list(issues)))
            return "\u5979\u7b11\u4e86\u3002"

        def fake_retranslate(src, prev_text=None, next_text=None, residue_guidance=""):
            retranslate_calls.append(src)
            residue_guidance_calls.append(residue_guidance)
            return "\u91cd\u8bd1\u5b8c\u6210\u3002"

        t._proofread_translation = fake_proofread  # type: ignore
        t._translate_chunk = fake_retranslate  # type: ignore

        res = t.translate_batch(srcs, batch_size=3)

        self.assertEqual(len(proofread_calls), 1)
        self.assertEqual(len(retranslate_calls), 2)
        self.assertEqual(len(residue_guidance_calls), 2)
        self.assertTrue(all("\u6b8b\u7559\u7247\u6bb5" in guidance for guidance in residue_guidance_calls))
        self.assertTrue(all("\u5979\u7b11\u4e86\u3002" in guidance for guidance in residue_guidance_calls))
        self.assertEqual(res[srcs[0]], "\u5979\u7b11\u4e86\u3002")
        self.assertEqual(res[srcs[1]], "\u91cd\u8bd1\u5b8c\u6210\u3002")
        self.assertEqual(res[srcs[2]], "\u91cd\u8bd1\u5b8c\u6210\u3002")

    def test_proofread_falls_back_to_single_retranslate_when_japanese_remains(self):
        t = DummyTranslator()
        t.enable_proofread = True
        t.max_workers = 1
        t.batch_size = 2
        t.max_batch_length = 100
        t.max_text_size_for_batch = 100
        t._call_deepseek_batch_json = lambda batch, max_retries=2, prev_text=None, next_text=None: BatchJsonResult(
            translations=["彼女は笑った。", "她点头。"],
            new_terms=[],
            missing_indices=[],
            finish_reason="stop",
        )
        t._proofread_translation = lambda src, draft, issues: draft  # type: ignore
        t._translate_chunk = lambda src: "她笑了。"  # type: ignore
        details = []

        res = t.translate_batch(["彼女は笑った。", "彼女は頷いた。"], batch_size=2, proofread_callback=details.append)

        self.assertEqual(res["彼女は笑った。"], "她笑了。")
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["draft"], "彼女は笑った。")
        self.assertEqual(details[0]["revised"], "她笑了。")
        self.assertTrue(any("单条重译" in issue for issue in details[0]["issues"]))

    def test_proofread_strips_model_explanation_note(self):
        raw = "治疗出了bug。\n（说明：根据术语表修正了专有名词，但原文未出现该词；调整了标点。）"
        cleaned = DummyTranslator._strip_proofread_explanations(raw, fallback="处理出了bug。")
        self.assertEqual(cleaned, "治疗出了bug。")

    def test_proofread_explanation_only_falls_back_to_draft(self):
        raw = "（说明：根据术语表修正了专有名词，但原文未出现该词。）"
        cleaned = DummyTranslator._strip_proofread_explanations(raw, fallback="处理出了bug。")
        self.assertEqual(cleaned, "处理出了bug。")

    def test_proofread_prompt_includes_context_window(self):
        t = DummyTranslator()
        t.enable_proofread = True
        t.session = mock.Mock()
        resp = mock.Mock()
        resp.status_code = 200
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "她笑了。"}}],
            "usage": {"total_tokens": 10},
        }
        t.session.post.return_value = resp

        revised = t._proofread_translation(
            "彼女は笑った。",
            "她笑了。",
            ["译文中疑似残留日文假名"],
            prev_text="前文：彼女は安心した。",
            next_text="后文：彼は頷いた。",
        )

        self.assertEqual(revised, "她笑了。")
        payload = t.session.post.call_args.kwargs["json"]
        user_prompt = payload["messages"][1]["content"]
        self.assertIn("前文上下文", user_prompt)
        self.assertIn("前文：彼女は安心した。", user_prompt)
        self.assertIn("后文上下文", user_prompt)
        self.assertIn("后文：彼は頷いた。", user_prompt)

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

    def test_gemini_payload_does_not_include_thinking(self):
        t = DummyTranslator()
        t.provider = "gemini"
        t.enable_thinking = False
        payload = {}
        t._apply_provider_payload_options(payload)
        self.assertNotIn("thinking", payload)

    def test_deepseek_payload_can_disable_thinking(self):
        t = DummyTranslator()
        t.provider = "deepseek"
        t.enable_thinking = False
        payload = {}
        t._apply_provider_payload_options(payload)
        self.assertEqual(payload.get("thinking"), {"type": "disabled"})

    def test_replace_glossary_thread_safe(self):
        t = DummyTranslator()
        with temp_test_dir() as d:
            t.glossary_path = os.path.join(d, "glossary.json")
            t.replace_glossary({"A": "甲"})
            self.assertIn("Item", t.glossary)
            self.assertEqual(t.glossary["Item"][0]["original"], "A")
            self.assertEqual(t.glossary["Item"][0]["translation"], "甲")

    def test_normalize_glossary_payload_flat_and_object(self):
        payload = {
            "勇者": "Hero",
            "王都": {"dst": "Royal Capital", "info": "地名", "source": "manual"},
        }
        normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["conflicts"], 0)
        self.assertEqual(len(normalized["Item"]), 2)
        self.assertEqual(normalized["Item"][1]["source"], "manual")

    def test_normalize_glossary_payload_categorized_and_conflict_keep_old(self):
        payload = {
            "Person": [
                {"original": "アリス", "translation": "爱丽丝", "source": "auto"},
                {"original": "アリス", "translation": "艾莉丝"},
            ],
            "Location": [{"src": "王都", "dst": "王都"}],
        }
        normalized, stats = JaZhTranslator.normalize_glossary_payload(payload)
        self.assertEqual(stats["accepted"], 2)
        self.assertEqual(stats["conflicts"], 1)
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(normalized["Person"][0]["translation"], "爱丽丝")
        self.assertEqual(normalized["Person"][0]["source"], "auto")

    def test_atomic_write_json(self):
        with temp_test_dir() as d:
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

    def test_select_glossary_entries_does_not_match_katakana_substring(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [],
            "Location": [],
            "Org": [],
            "Item": [
                {"original": "\u30b0\u30e9\u30b9", "translation": "\u676f\u5b50"},
                {"original": "\u30b5\u30f3\u30b0\u30e9\u30b9", "translation": "\u58a8\u955c"},
            ],
            "Skill": [],
            "Creature": [],
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)

        selected = t._select_glossary_entries("\u5f7c\u306f\u30b5\u30f3\u30b0\u30e9\u30b9\u3092\u304b\u3051\u305f\u3002")

        self.assertEqual([item["original"] for item in selected], ["\u30b5\u30f3\u30b0\u30e9\u30b9"])

    def test_select_glossary_entries_prefers_longer_overlapping_term(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [],
            "Location": [
                {"original": "\u6771\u4eac", "translation": "\u4e1c\u4eac"},
                {"original": "\u6771\u4eac\u90fd", "translation": "\u4e1c\u4eac\u90fd"},
            ],
            "Org": [],
            "Item": [],
            "Skill": [],
            "Creature": [],
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)

        selected = t._select_glossary_entries("\u6771\u4eac\u90fd\u3078\u884c\u304f", max_terms=1)

        self.assertEqual(selected[0]["original"], "\u6771\u4eac\u90fd")

    def test_proofread_rejects_new_glossary_translation_without_valid_source_match(self):
        t = DummyTranslator()
        t.enable_proofread = True
        t.glossary = {
            "Person": [],
            "Location": [],
            "Org": [],
            "Item": [{"original": "\u30b0\u30e9\u30b9", "translation": "\u676f\u5b50"}],
            "Skill": [],
            "Creature": [],
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)
        resp = mock.Mock()
        resp.status_code = 200
        resp.raise_for_status = mock.Mock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "\u4ed6\u6234\u4e0a\u4e86\u676f\u5b50\u3002"}}],
            "usage": {"total_tokens": 10},
        }
        t.session = mock.Mock()
        t.session.post.return_value = resp

        revised = t._proofread_translation(
            "\u5f7c\u306f\u30b5\u30f3\u30b0\u30e9\u30b9\u3092\u304b\u3051\u305f\u3002",
            "\u4ed6\u6234\u4e0a\u4e86\u58a8\u955c\u3002",
            ["\u672f\u8bed\u672a\u6309\u672f\u8bed\u8868\u7ffb\u8bd1: dummy"],
        )

        self.assertEqual(revised, "\u4ed6\u6234\u4e0a\u4e86\u58a8\u955c\u3002")
        self.assertEqual(t.stats["proofread_rejected"], 1)

    def test_proofread_treats_short_katakana_item_as_reference_only(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [],
            "Location": [],
            "Org": [],
            "Item": [{"original": "\u30b0\u30e9\u30b9", "translation": "\u676f\u5b50"}],
            "Skill": [],
            "Creature": [],
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)

        issues = t._find_proofread_issues("\u5f7c\u306f\u30b0\u30e9\u30b9\u3092\u7f6e\u3044\u305f\u3002", "\u4ed6\u653e\u4e0b\u4e86\u73bb\u7483\u676f\u3002")

        self.assertEqual(issues, [])

    def test_proofread_can_force_short_item_with_explicit_marker(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [],
            "Location": [],
            "Org": [],
            "Item": [{"original": "\u30b0\u30e9\u30b9", "translation": "\u676f\u5b50", "info": "\u5f3a\u5236"}],
            "Skill": [],
            "Creature": [],
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)

        issues = t._find_proofread_issues("\u5f7c\u306f\u30b0\u30e9\u30b9\u3092\u7f6e\u3044\u305f\u3002", "\u4ed6\u653e\u4e0b\u4e86\u73bb\u7483\u676f\u3002")

        self.assertTrue(any("\u30b0\u30e9\u30b9 -> \u676f\u5b50" in issue for issue in issues))

    def test_invalid_glossary_injection_allows_same_translation_when_source_term_absent(self):
        t = DummyTranslator()
        t.glossary = {
            "Person": [],
            "Location": [],
            "Org": [],
            "Item": [{"original": "\u30b0\u30e9\u30b9", "translation": "\u676f\u5b50"}],
            "Skill": [],
            "Creature": [],
        }
        t._glossary_index = rebuild_glossary_index(t.glossary, t.glossary_categories)

        invalid = t._find_invalid_glossary_injections(
            "\u5f7c\u306f\u30b3\u30c3\u30d7\u3092\u6301\u3063\u305f\u3002",
            "\u4ed6\u62ff\u8d77\u4e86\u6c34\u676f\u3002",
            "\u4ed6\u62ff\u8d77\u4e86\u676f\u5b50\u3002",
        )

        self.assertEqual(invalid, [])

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
        with temp_test_dir() as d:
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
        with temp_test_dir() as d:
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
        self.assertTrue(is_translatable("こんにちは"))
        self.assertTrue(is_translatable("漢字だけ"))
        self.assertFalse(is_translatable("Hello world"))

    def test_book_translation_service_replaces_multi_anchor_text_without_removing_links(self):
        html = '<html><body><p>前文 <a href="a">リンクA</a> 中間 <a href="b">リンクB</a> 後文</p></body></html>'
        docs = list(iter_text_nodes(FakeEpubBook(html)))
        plan = build_book_text_plan(docs, [])

        apply_translations_to_book(
            plan,
            {},
            ["前文ZH", "链接AZH", "中间ZH", "链接BZH", "后文ZH"],
            lambda text: text,
            lambda text: False,
        )

        rendered = str(docs[0][1])
        self.assertIn('href="a"', rendered)
        self.assertIn('href="b"', rendered)
        self.assertIn("链接AZH", rendered)
        self.assertIn("链接BZH", rendered)

    def test_book_translation_service_scans_blocking_japanese_residue(self):
        html = "<html><body><p>逃げる</p><rt>よみ</rt><p>她笑了。</p></body></html>"
        docs = list(iter_text_nodes(FakeEpubBook(html)))

        scan = scan_japanese_residue_in_docs(docs)

        self.assertEqual(scan.blocking_total, 1)
        self.assertEqual(scan.weak_total, 0)
        self.assertIn("逃げる", scan.blocking_samples[0])

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
