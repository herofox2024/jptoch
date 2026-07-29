from __future__ import annotations

import unittest

import requests

import translation_models
from translation_async_http import HttpxResponseAdapter
from translation_batching import smart_batch_task_keys, smart_batch_texts, smart_split_text
from translation_json_parser import extract_json_object, extract_lenient_indexed_items
from translator import (
    BatchJsonResult,
    ContentModerationError,
    FastFailError,
    JaZhTranslator,
    SingleChunkResult,
    TranslationIncompleteError,
)


class TranslationArchitectureTests(unittest.TestCase):
    def test_translator_keeps_public_result_and_error_exports(self):
        self.assertIs(SingleChunkResult, translation_models.SingleChunkResult)
        self.assertIs(BatchJsonResult, translation_models.BatchJsonResult)
        self.assertIs(FastFailError, translation_models.FastFailError)
        self.assertIs(ContentModerationError, translation_models.ContentModerationError)
        self.assertIs(TranslationIncompleteError, translation_models.TranslationIncompleteError)

    def test_json_parser_handles_fenced_object_and_translation_array(self):
        fenced = '说明\n```json\n{"translations":[{"idx":0,"zh":"她笑了。"}]}\n```'
        self.assertEqual(
            extract_json_object(fenced),
            {"translations": [{"idx": 0, "zh": "她笑了。"}]},
        )
        self.assertEqual(
            extract_json_object('["第一条", "第二条"]'),
            {"translations": ["第一条", "第二条"], "new_terms": []},
        )

    def test_json_parser_distinguishes_glossary_array(self):
        raw = '[{"original":"黒猫","translation":"黑猫","category":"其他"}]'
        self.assertEqual(
            extract_json_object(raw, prefer_new_terms=True),
            {
                "new_terms": [
                    {"original": "黒猫", "translation": "黑猫", "category": "其他"}
                ]
            },
        )

    def test_lenient_parser_recovers_unescaped_quotes(self):
        raw = (
            '{"items":['
            '{"idx":0,"zh":"她说"你好"。"},'
            '{"idx":1,"zh":"结束。"}'
            ']}'
        )
        self.assertEqual(
            extract_lenient_indexed_items(raw),
            [
                {"idx": 0, "zh": '她说"你好"。'},
                {"idx": 1, "zh": "结束。"},
            ],
        )

    def test_translator_json_methods_are_compatibility_wrappers(self):
        raw = '{"items":[{"idx":0,"revised":"已修正"}]}'
        self.assertEqual(JaZhTranslator._extract_json_object(raw), extract_json_object(raw))
        self.assertEqual(
            JaZhTranslator._extract_lenient_indexed_items(raw, value_keys=["revised"]),
            extract_lenient_indexed_items(raw, value_keys=["revised"]),
        )

    def test_httpx_response_adapter_matches_requests_contract(self):
        response = HttpxResponseAdapter(
            429,
            '{"error":"rate limited"}',
            "https://example.invalid/v1/chat/completions",
            headers={"Retry-After": "8"},
        )
        self.assertEqual(response.json(), {"error": "rate limited"})
        self.assertEqual(response.headers["Retry-After"], "8")
        with self.assertRaises(requests.exceptions.HTTPError) as raised:
            response.raise_for_status()
        self.assertIs(raised.exception.response, response)

    def test_incomplete_error_keeps_structured_diagnostics(self):
        error = TranslationIncompleteError(
            failed_texts=["原文一"],
            residue_texts=["原文二"],
            residue_details=[
                {
                    "original": "原文二",
                    "translated": "译文でも残留",
                    "fragments": ["でも"],
                }
            ],
        )
        diagnostics = error.format_diagnostics()
        self.assertIn("未成功翻译 1 条", diagnostics)
        self.assertIn("残留片段: でも", diagnostics)

    def test_batching_module_keeps_order_and_length_tiers(self):
        short = "短句"
        medium = "中" * 40
        long = "长" * 220
        self.assertEqual(
            smart_batch_texts(
                [short, medium, long],
                4,
                short_threshold=30,
                long_threshold=200,
                max_batch_length=500,
            ),
            [[short], [medium], [long]],
        )
        self.assertEqual(smart_split_text("第一句。第二句。", 4), ["第一句。", "第二句。"])

    def test_fast_task_batching_uses_source_lengths_not_keys(self):
        task_texts = {"short-key": "短", "long-key": "长" * 240}
        batches = smart_batch_task_keys(
            ["short-key", "long-key"],
            task_texts,
            4,
            short_threshold=30,
            long_threshold=200,
            max_batch_length=500,
            fast_mode=False,
            fast_max_items=8,
            fast_max_chars=2400,
            provider="deepseek",
        )
        self.assertEqual(batches, [["short-key"], ["long-key"]])


if __name__ == "__main__":
    unittest.main()
