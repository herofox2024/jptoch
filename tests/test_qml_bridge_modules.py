from __future__ import annotations

from pathlib import Path
import sys

QML_ROOT = Path(__file__).resolve().parents[1] / "experimental" / "qml_v4"
if str(QML_ROOT) not in sys.path:
    sys.path.insert(0, str(QML_ROOT))

from backend.bridge_workers import (
    ClearBookCacheWorker,
    EstimateWorker,
    TestConnectionWorker as ConnectionTestWorker,
)
from backend.output_naming import (
    clean_translated_filename_candidate,
    clean_translated_toc_title,
    sanitize_filename,
    source_title_for_filename,
    unique_epub_path,
)
from backend.translation_reports import (
    build_quality_self_check_report,
    estimate_translation_duration,
    format_duration,
)
from backend import translate_bridge


def test_bridge_preserves_output_helper_compatibility(tmp_path):
    filename_candidate = "献给你的终极纯爱小说（说明：采用意译）"
    toc_candidate = "译文：星之女（希腊神话中的补充说明）"
    assert translate_bridge._clean_translated_filename_candidate(filename_candidate) == clean_translated_filename_candidate(filename_candidate)
    assert translate_bridge._clean_translated_toc_title(toc_candidate) == clean_translated_toc_title(toc_candidate)
    assert translate_bridge._source_title_for_filename("书名+(扫图版)") == source_title_for_filename("书名+(扫图版)")
    assert sanitize_filename("CON.epub") == "CON_"

    occupied = tmp_path / "book.epub"
    occupied.write_bytes(b"epub")
    assert unique_epub_path(occupied) == Path(tmp_path / "book_2.epub")


def test_bridge_preserves_estimate_and_duration_helpers():
    cfg = {"provider": "deepseek", "batch_size": 4, "max_workers": 5}
    expected = estimate_translation_duration(50_000, 2_000, cfg)
    assert translate_bridge._estimate_translation_duration(50_000, 2_000, cfg) == expected
    assert translate_bridge._format_duration(expected) == format_duration(expected)


def test_quality_report_is_independent_from_qml_bridge():
    class Translator:
        @staticmethod
        def get_stats():
            return {
                "api_requests_total": 12,
                "proofread_suspicious": 2,
                "proofread_fixed": 2,
                "tokens_total": 800,
            }

    class Style:
        display_text = "推理小说 + 中性口吻"

    report = build_quality_self_check_report(
        Translator(),
        {"enable_proofread": True},
        Style(),
        100,
        20_000,
        90,
        0,
        "translated.epub",
    )
    assert report["status"] == "通过"
    assert "API 请求: 12" in report["metricsText"]
    assert "校对发现 2 条可疑译文，修复 2 条" in report["summary"]


def test_bridge_uses_extracted_auxiliary_workers():
    assert translate_bridge._EstimateWorker is EstimateWorker
    assert translate_bridge._ClearBookCacheWorker is ClearBookCacheWorker
    assert translate_bridge._TestWorker is ConnectionTestWorker
