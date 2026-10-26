# -*- coding: utf-8 -*-
"""P6 润色档测试：只测本地检测逻辑，不调用 API。"""

from __future__ import annotations

import shutil
import sys
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from translator import JaZhTranslator  # noqa: E402


@contextmanager
def temp_test_dir():
    """Mirror the project's existing helper so SQLite handles are released."""
    root = Path(__file__).resolve().parent / "_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield str(path)
    finally:
        from translation_cache_db import TranslationCacheDB

        TranslationCacheDB.close_open_under(path)
        shutil.rmtree(path, ignore_errors=True)


def _make_translator(tmp_dir: str, **kwargs) -> JaZhTranslator:
    return JaZhTranslator(
        api_key="test-key",
        provider="deepseek",
        glossary_path=str(Path(tmp_dir) / "glossary.json"),
        cache_path=str(Path(tmp_dir) / "cache.json"),
        **kwargs,
    )


class PolishIssueDetectionTests(unittest.TestCase):
    def test_polish_disabled_by_default_returns_no_issues(self):
        with temp_test_dir() as d:
            t = _make_translator(d)
            self.assertFalse(t.enable_polish)
            self.assertEqual(
                t._find_polish_issues(
                    "遠くで犬の吠える声が消えた。",
                    "远处狗吠声持续了一段时间后消失了。",
                ),
                [],
            )

    def test_polish_disabled_has_no_prompt_suffix(self):
        with temp_test_dir() as d:
            t = _make_translator(d)
            self.assertEqual(t._build_polish_user_prompt_suffix(), "")

    def test_polish_detects_missing_sensory_verb(self):
        with temp_test_dir() as d:
            t = _make_translator(d, enable_proofread=True, enable_polish=True)
            issues = t._find_polish_issues(
                "遠くで犬の吠える声が、しばらく尾を引いて消えた。",
                "远处狗吠声持续了一段时间后消失了。",
            )
            self.assertTrue(issues)
            self.assertTrue(any("感官" in i or "翻译腔" in i for i in issues))

    def test_polish_detects_lost_concessive_tone(self):
        with temp_test_dir() as d:
            t = _make_translator(d, enable_proofread=True, enable_polish=True)
            issues = t._find_polish_issues(
                "俺はただ、普通に生きていたかっただけなのに。",
                "我只是想正常地生活而已。",
            )
            self.assertTrue(any("转折" in i or "遗憾" in i for i in issues))

    def test_polish_accepts_natural_translation(self):
        with temp_test_dir() as d:
            t = _make_translator(d, enable_proofread=True, enable_polish=True)
            self.assertEqual(
                t._find_polish_issues("彼は本を読んだ。", "他读了那本书。"),
                [],
            )

    def test_polish_accepts_translation_that_keeps_tone(self):
        with temp_test_dir() as d:
            t = _make_translator(d, enable_proofread=True, enable_polish=True)
            self.assertEqual(
                t._find_polish_issues(
                    "俺はただ、普通に生きていたかっただけなのに。",
                    "我明明只是想普普通通地活着而已，却变成了这样。",
                ),
                [],
            )

    def test_polish_skips_very_short_text(self):
        with temp_test_dir() as d:
            t = _make_translator(d, enable_proofread=True, enable_polish=True)
            self.assertEqual(t._find_polish_issues("はい。", "好。"), [])

    def test_polish_prompt_suffix_present_when_enabled(self):
        with temp_test_dir() as d:
            t = _make_translator(d, enable_proofread=True, enable_polish=True)
            suffix = t._build_polish_user_prompt_suffix()
            self.assertIn("润色要求", suffix)
            self.assertIn("翻译腔", suffix)
            self.assertIn("明明", suffix)


if __name__ == "__main__":
    unittest.main()
