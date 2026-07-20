from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub

from epub_io import (
    add_translation_notice_page,
    apply_toc_translations,
    extract_toc_titles,
    extract_visible_text,
    iter_text_nodes,
    load_book,
    save_book,
)
from experimental.qml_v4.backend.book_translation_service import build_book_text_plan
from experimental.qml_v4.backend.pipeline import (
    ApplyBookTranslationsStage,
    BuildTextPlanStage,
    FinalizeBookContentStage,
    LoadEpubStage,
    PipelineContext,
    TranslationPipeline,
)

QML_ROOT = Path(__file__).resolve().parents[1] / "experimental" / "qml_v4"
if str(QML_ROOT) not in sys.path:
    sys.path.insert(0, str(QML_ROOT))
from backend.translate_bridge import _clean_translated_toc_title, _looks_like_model_refusal


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00"
    b"\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
DIRECT_BODY_TEXT = (
    (
        "旅ゆけば風の音だけが残った。"
        "山道を越えると、古い宿場の灯がひとつだけ見えた。"
        "誰もいないはずの橋の上で、私は小さな鈴の音を聞いた。"
        "それは遠い昔に失われた約束を思い出させる音だった。"
        "夜明けまで歩き続けても、背後の足音は消えなかった。"
    )
    * 3
)


def _build_complex_epub() -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier("complex-fixture")
    book.set_title("複雑な実例EPUB")
    book.set_language("ja")

    cover_img = epub.EpubItem(
        uid="cover-image",
        file_name="Images/cover.png",
        media_type="image/png",
        content=PNG_1X1,
    )
    cover = epub.EpubHtml(uid="cover", file_name="Text/cover.xhtml", title="Cover")
    cover.set_content(
        b'<html xmlns="http://www.w3.org/1999/xhtml"><body><img src="../Images/cover.png" alt="cover"/></body></html>'
    )

    empty = epub.EpubHtml(uid="empty", file_name="Text/empty.xhtml", title="Empty")
    empty.set_content(b"")

    chapter1 = epub.EpubHtml(uid="chap1", file_name="Text/part0001.xhtml", title="尼俄泊")
    chapter1.set_content(
        """<html xmlns="http://www.w3.org/1999/xhtml"><body>
        <h1 id="c1">尼俄泊</h1>
        旅ゆけば<br/>風の音だけが残った。<br/>
        <p><ruby>前<rt>まえ</rt>口上<rt>こうじょう</rt></ruby>を聞いた。</p>
        </body></html>""".encode("utf-8")
    )

    chapter2 = epub.EpubHtml(uid="chap2", file_name="Text/part0002.xhtml", title="正月女")
    chapter2.set_content(
        """<html xmlns="http://www.w3.org/1999/xhtml"><body>
        <section><h2 id="c2">正月女</h2><p>名前はまだ無い。</p></section>
        </body></html>""".encode("utf-8")
    )
    chapter3 = epub.EpubItem(
        uid="chap3",
        file_name="Text/part0003.xhtml",
        media_type="application/xhtml+xml",
        content=f"""<html xmlns="http://www.w3.org/1999/xhtml"><body>{DIRECT_BODY_TEXT}</body></html>""".encode("utf-8"),
    )

    book.add_item(cover_img)
    for item in (cover, empty, chapter1, chapter2, chapter3):
        book.add_item(item)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [cover, empty, chapter1, chapter2, chapter3]
    section = epub.Section("角川恐怖文庫精选集", "Text/part0001.xhtml")
    book.toc = [
        (section, [
            epub.Link("Text/part0001.xhtml#c1", "尼俄泊", None),
            epub.Link("Text/part0002.xhtml#c2", "正月女", None),
            epub.Link("Text/part0003.xhtml", "直書き本文", None),
        ])
    ]
    return book


def _spine_ids(book: epub.EpubBook) -> list[str]:
    result = []
    for entry in list(getattr(book, "spine", []) or []):
        candidate = entry[0] if isinstance(entry, tuple) and entry else entry
        if isinstance(candidate, str):
            result.append(candidate)
        elif hasattr(candidate, "get_id"):
            result.append(candidate.get_id())
    return result


def _visible_text(book: epub.EpubBook) -> str:
    return "\n".join(
        extract_visible_text(tag)
        for _, _, tags in iter_text_nodes(book)
        for tag in tags
    )


def _zip_text(path: Path, suffix: str) -> str:
    with zipfile.ZipFile(path, "r") as zf:
        names = [name for name in zf.namelist() if name.lower().endswith(suffix.lower())]
        return "\n".join(zf.read(name).decode("utf-8", errors="ignore") for name in names)


def test_complex_epub_roundtrip_keeps_spine_toc_and_notice_after_cover(tmp_path: Path):
    book = _build_complex_epub()
    add_translation_notice_page(book, "本书由 AI 日译中测试生成。")

    out_path = tmp_path / "complex.epub"
    save_book(str(out_path), book, chinese_mode=True)

    assert out_path.stat().st_size > 0
    loaded = load_book(str(out_path), try_repair=False)
    ids = _spine_ids(loaded)
    assert ids[:4] == ["cover", "ai-jp-zh-translation-notice", "empty", "chap1"]
    assert extract_toc_titles(loaded) == ["角川恐怖文庫精选集", "尼俄泊", "正月女", "直書き本文"]
    assert "本书由 AI 日译中测试生成。" in _visible_text(loaded)

    opf_text = _zip_text(out_path, ".opf")
    assert 'page-progression-direction="ltr"' in opf_text
    assert "primary-writing-mode" in opf_text
    assert "horizontal-lr" in opf_text
    assert ">zh<" in opf_text

    nav_text = _zip_text(out_path, "nav.xhtml")
    assert "page-list" not in nav_text.lower()


def test_full_epub_writeback_fixture_cleans_polluted_titles_and_reloads(tmp_path: Path):
    source_path = tmp_path / "source.epub"
    save_book(str(source_path), _build_complex_epub(), chinese_mode=False)

    ctx = PipelineContext(
        config={"inp": str(source_path), "enable_notice_page": True, "notice_page_text": "版权提示测试。"},
        extra={
            "clean_title": _clean_translated_toc_title,
            "looks_like_refusal": _looks_like_model_refusal,
        },
    )
    ctx = (
        TranslationPipeline()
        .add_stage(LoadEpubStage())
        .add_stage(BuildTextPlanStage())
        .run(ctx)
    )

    assert DIRECT_BODY_TEXT in ctx.texts
    assert "前口上を聞いた。" in ctx.texts

    polluted_title = "尼俄泊（尼俄柏之穴的简写，尼俄柏是希腊神话中坦塔罗斯之女，身体化作泉水）恒川光太郎"
    translations = {
        "尼俄泊": polluted_title,
        "正月女": "正月女",
        DIRECT_BODY_TEXT: "旅行途中，只剩风声。",
        "前口上を聞いた。": "听了开场白。",
        "名前はまだ無い。": "还没有名字。",
        "角川恐怖文庫精选集": "角川恐怖文库精选集",
        "直書き本文": "直写正文",
    }
    ctx.results = translations
    ctx.ordered_results = [translations.get(text) for text in ctx.texts]
    ctx = (
        TranslationPipeline()
        .add_stage(ApplyBookTranslationsStage())
        .add_stage(FinalizeBookContentStage())
        .run(ctx)
    )

    out_path = tmp_path / "translated.epub"
    save_book(str(out_path), ctx.book, chinese_mode=True)
    loaded = load_book(str(out_path), try_repair=False)

    visible = _visible_text(loaded)
    titles = extract_toc_titles(loaded)
    assert "旅行途中，只剩风声。" in visible
    assert "听了开场白。" in visible
    assert "还没有名字。" in visible
    assert "版权提示测试。" in visible
    assert "尼俄泊" in titles
    assert all("希腊神话" not in title for title in titles)
    assert all("恒川光太郎" not in title for title in titles)
    assert "Document is empty" not in visible


def test_empty_document_and_body_direct_text_do_not_break_roundtrip(tmp_path: Path):
    book = _build_complex_epub()
    out_path = tmp_path / "empty-direct-text.epub"

    save_book(str(out_path), book, chinese_mode=True)
    loaded = load_book(str(out_path), try_repair=False)
    docs = list(iter_text_nodes(loaded))
    plan = build_book_text_plan(docs, extract_toc_titles(loaded))

    assert out_path.stat().st_size > 0
    assert DIRECT_BODY_TEXT in plan.all_texts
    assert "名前はまだ無い。" in plan.all_texts
    assert not any(getattr(item, "file_name", "") == "Text/empty.xhtml" for item, _, tags in docs if tags)
