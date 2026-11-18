"""版权提示页格式测试：结构化书目区 + 无日文残留 + spine 位置。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup
from ebooklib import epub

from epub_io import (
    TRANSLATION_NOTICE_UID,
    _translation_notice_html,
    add_translation_notice_page,
    extract_book_bibliography,
    extract_visible_text,
)


def _book(title="", author="", publisher="", language="ja"):
    book = epub.EpubBook()
    book.set_identifier("notice-test")
    if title:
        book.set_title(title)
    if author:
        book.add_author(author)
    if publisher:
        book.add_metadata("DC", "publisher", publisher)
    if language:
        book.set_language(language)
    chapter = epub.EpubHtml(uid="chap1", file_name="Text/c1.xhtml", title="一章")
    chapter.set_content("<html><body><p>本文。</p></body></html>".encode("utf-8"))
    book.add_item(chapter)
    book.spine = [chapter]
    return book


def _notice_text(book) -> str:
    for item in book.get_items():
        if item.get_id() == TRANSLATION_NOTICE_UID:
            soup = BeautifulSoup(item.get_content().decode("utf-8"), "html.parser")
            return extract_visible_text(soup.body or soup)
    return ""


# ---------- 书目信息提取 ----------


def test_extract_book_bibliography_reads_dc_fields():
    book = _book(title="请做好失恋的准备", author="浅仓秋成", publisher="讲谈社")
    bib = extract_book_bibliography(book)
    assert bib.get("title") == "请做好失恋的准备"
    assert bib.get("author") == "浅仓秋成"
    assert bib.get("publisher") == "讲谈社"


def test_extract_book_bibliography_is_empty_safe():
    book = epub.EpubBook()
    book.set_identifier("x")
    assert extract_book_bibliography(book) == {}


# ---------- 页面结构 ----------


def test_notice_page_renders_book_identity_block():
    """版权页应包含书目区：中文书名 / 作者 / 出版。"""
    book = _book(title="请做好失恋的准备", author="浅仓秋成", publisher="讲谈社")
    add_translation_notice_page(book, "译文仅供学习。")
    text = _notice_text(book)

    assert "版权提示" in text
    assert "中文书名：请做好失恋的准备" in text
    assert "作者：浅仓秋成" in text
    assert "出版：讲谈社" in text
    assert "译文仅供学习。" in text


def test_notice_page_renders_original_title_when_given():
    """显式传入中文写法的原书名时必须渲染。"""
    book = _book(title="请做好失恋的准备", author="浅仓秋成")
    add_translation_notice_page(book, "说明。", original_title="失恋的准备")
    text = _notice_text(book)
    assert "原书名：失恋的准备" in text


def test_notice_page_renders_extra_note():
    """附加说明（如"本译本已做统一"）应出现在页面末尾。"""
    book = _book(title="测试书")
    add_translation_notice_page(book, "正文说明。", extra_note="本译本已统一术语。")
    text = _notice_text(book)
    assert "本译本已统一术语。" in text


# ---------- 日文残留防护 ----------


def test_japanese_dc_title_is_not_rendered():
    """dc:title 是日文原题时，不能出现在中文版权页上。"""
    book = _book(title="失恋の準備をお願いします", language="ja")
    add_translation_notice_page(book, "译文仅供学习。")
    text = _notice_text(book)

    assert "失恋の準備" not in text, f"日文原题泄漏到版权页: {text}"
    assert "版权提示" in text


def test_japanese_original_title_param_is_not_rendered():
    """即便调用方误传日文原书名，也不应渲染出来。"""
    book = _book(title="请做好失恋的准备")
    add_translation_notice_page(book, "说明。", original_title="失恋の準備をお願いします")
    text = _notice_text(book)
    assert "失恋の準備" not in text


def test_notice_page_has_no_japanese_residue():
    """整页不得触发日文残留判定（成书会被质检拦下）。"""
    from translator import JaZhTranslator

    book = _book(title="実例EPUBテスト", author="山田太郎", publisher="講談社")
    add_translation_notice_page(book, "本书由测试流程生成。")
    text = _notice_text(book)

    assert not JaZhTranslator.has_blocking_japanese_residue(text), text


def test_japanese_original_title_is_rendered_when_enabled():
    """开关打开时，日文原书名应显示并被标记为「授权引用」。"""
    book = _book(title="请做好失恋的准备", author="浅仓秋成")
    add_translation_notice_page(
        book,
        "说明。",
        original_title="失恋の準備をお願いします",
        show_original_title=True,
    )
    text = _notice_text(book)

    assert "失恋の準備" in text, f"日文原书名未显示: {text}"
    assert "[[ja:" in text, "日文原书名应带授权标记"
    assert "原书名" in text


def test_japanese_original_title_uses_lang_attribute():
    """页面 HTML 里日文应包在 lang="ja" 中，便于阅读器按日文字体排版。"""
    book = _book(title="请做好失恋的准备")
    add_translation_notice_page(
        book,
        "说明。",
        original_title="失恋の準備をお願いします",
        show_original_title=True,
    )
    for item in book.get_items():
        if item.get_id() == TRANSLATION_NOTICE_UID:
            html_text = item.get_content().decode("utf-8")
            assert 'lang="ja"' in html_text
            assert "失恋の準備" in html_text
            return
    raise AssertionError("未找到版权页")


def test_authorized_japanese_span_is_skipped_by_residue_check():
    """授权标记内的日文不触发残留；标记外的日文仍然触发。"""
    from translation_quality import has_blocking_japanese_residue, mark_authorized_japanese

    plain = "原书名：失恋の準備をお願いします"
    assert has_blocking_japanese_residue(plain), "未标记时应当判定为残留"

    marked = "原书名：" + mark_authorized_japanese("失恋の準備をお願いします")
    assert not has_blocking_japanese_residue(marked), "标记后不应判定为残留"

    # 标记旁如果有真正漏译的日文，仍必须检出
    leak = marked + " これは漏译です"
    assert has_blocking_japanese_residue(leak), "标记外的日文泄漏必须仍被检出"


def test_authorized_span_marking_is_idempotent():
    """重复标记不应产生嵌套。"""
    from translation_quality import mark_authorized_japanese

    once = mark_authorized_japanese("テスト")
    twice = mark_authorized_japanese(once)
    assert once == twice == "[[ja:テスト]]"


def test_authorized_span_strip_removes_only_marked_parts():
    from translation_quality import strip_authorized_japanese_spans

    text = "中文[[ja:テスト]]中文"
    assert strip_authorized_japanese_spans(text) == "中文中文"


# ---------- spine 位置 ----------


def test_notice_page_is_inserted_as_own_spine_item():
    book = _book(title="测试书")
    add_translation_notice_page(book, "说明。")
    ids = [
        entry.get_id() if hasattr(entry, "get_id") else str(entry)
        for entry in book.spine
    ]
    assert TRANSLATION_NOTICE_UID in ids


def test_notice_page_inserted_after_cover():
    book = _book(title="测试书")
    cover = epub.EpubHtml(uid="cover", file_name="cover.xhtml", title="封面")
    cover.set_content(b'<html><body><img src="c.jpg"/></body></html>')
    book.add_item(cover)
    book.spine = [cover] + list(book.spine)

    add_translation_notice_page(book, "说明。")
    ids = [
        entry.get_id() if hasattr(entry, "get_id") else str(entry)
        for entry in book.spine
    ]
    assert ids[0] == "cover"
    assert ids[1] == TRANSLATION_NOTICE_UID


def test_repeated_calls_do_not_duplicate_notice():
    """重复调用应更新同一页，而不是插入多份。"""
    book = _book(title="测试书")
    add_translation_notice_page(book, "第一版。")
    add_translation_notice_page(book, "第二版。")
    ids = [
        entry.get_id() if hasattr(entry, "get_id") else str(entry)
        for entry in book.spine
    ]
    assert ids.count(TRANSLATION_NOTICE_UID) == 1
    assert "第二版。" in _notice_text(book)


# ---------- 纯文本回退 ----------


def test_notice_html_without_bibliography_is_still_valid():
    html_text = _translation_notice_html("只有一段说明。")
    soup = BeautifulSoup(html_text, "html.parser")
    assert "只有一段说明。" in soup.get_text()
    assert "版权提示" in soup.get_text()
