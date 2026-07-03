import logging
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Generator, Tuple, Any, Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub, ITEM_DOCUMENT

logger = logging.getLogger(__name__)

TARGET_TAGS = ["p", "h1", "h2", "h3", "li", "blockquote"]
DOCUMENT_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
BODY_FALLBACK_MIN_CHARS = 200
TOC_LINK_MIN_COUNT = 3
HIDDEN_TEXT_TAGS = {"rt", "rp", "script", "style", "noscript"}
BLOCK_SPLIT_TAGS = {
    "address",
    "article",
    "aside",
    "div",
    "dl",
    "figure",
    "footer",
    "header",
    "main",
    "nav",
    "ol",
    "section",
    "table",
    "ul",
}


def extract_visible_text(node: Any) -> str:
    """Extract display text while skipping ruby annotations and hidden tags."""
    parts = []

    def _walk(current):
        if isinstance(current, NavigableString):
            parts.append(str(current))
            return
        if not isinstance(current, Tag):
            return
        if current.name in HIDDEN_TEXT_TAGS:
            return
        for child in current.children:
            _walk(child)

    _walk(node)
    text = "".join(parts).replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    return text.strip()


def _compact_text_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


def _has_japanese_text(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text or ""))


def _is_document_item(item: Any) -> bool:
    if item.get_type() == ITEM_DOCUMENT:
        return True
    media_type = str(getattr(item, "media_type", "") or "").lower()
    file_name = str(getattr(item, "file_name", "") or "").lower()
    return media_type in DOCUMENT_MEDIA_TYPES or file_name.endswith((".html", ".xhtml", ".htm"))


def _first_anchor_attrs(node: Any) -> dict:
    """Return the first id/name anchor attributes found in a node tree."""
    if not isinstance(node, Tag):
        return {}
    search_nodes = [node]
    search_nodes.extend(node.find_all(True))
    for tag in search_nodes:
        attrs = {}
        if tag.get("id"):
            attrs["id"] = tag.get("id")
        if tag.name == "a" and tag.get("name"):
            attrs["name"] = tag.get("name")
        if attrs:
            return attrs
    return {}


def _should_use_body_fallback(soup: BeautifulSoup, tags: list) -> bool:
    body = soup.find("body")
    if body is None:
        return False

    body_text = extract_visible_text(body)
    body_chars = _compact_text_len(body_text)
    if body_chars < BODY_FALLBACK_MIN_CHARS or not _has_japanese_text(body_text):
        return False

    target_chars = sum(_compact_text_len(extract_visible_text(tag)) for tag in tags)
    if target_chars == 0:
        return True

    # Some EPUBs put only a title in h1/h2 and the actual body directly under
    # body with <br>. Treat that as the same malformed layout, but do not touch
    # normal EPUBs where target tags already cover most text.
    return target_chars < body_chars * 0.2 and (body_chars - target_chars) >= BODY_FALLBACK_MIN_CHARS


def _is_descendant_of_any(tag: Tag, containers: list) -> bool:
    container_ids = {id(container) for container in containers}
    return any(id(parent) in container_ids for parent in tag.parents)


def _find_inbook_toc_link_tags(soup: BeautifulSoup, tags: list) -> list:
    """Find short in-book TOC pages whose entries are bare <a href> links."""
    body = soup.find("body")
    if body is None:
        return []

    links = []
    for link in body.find_all("a", href=True):
        text = extract_visible_text(link)
        if _compact_text_len(text) and _has_japanese_text(text):
            links.append(link)

    if len(links) < TOC_LINK_MIN_COUNT:
        return []

    link_chars = sum(_compact_text_len(extract_visible_text(link)) for link in links)
    target_chars = sum(_compact_text_len(extract_visible_text(tag)) for tag in tags)
    if target_chars >= link_chars:
        return []

    return [link for link in links if not _is_descendant_of_any(link, tags)]


def _build_body_fallback_tags(soup: BeautifulSoup) -> list:
    """Convert body-level text split by <br> into temporary paragraph tags."""
    body = soup.find("body")
    if body is None:
        return []

    rebuilt_nodes = []
    fallback_tags = []
    segment_parts = []
    segment_attrs = {}

    def _add_attrs(attrs: dict):
        for key, value in attrs.items():
            if value and key not in segment_attrs:
                segment_attrs[key] = value

    def _append_text(text: str):
        if text:
            segment_parts.append(text)

    def _flush_segment():
        nonlocal segment_parts, segment_attrs
        text = "".join(segment_parts)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n+ *", "\n", text).strip()
        if _compact_text_len(text):
            p_tag = soup.new_tag("p")
            for key, value in segment_attrs.items():
                p_tag[key] = value
            p_tag.append(NavigableString(text))
            rebuilt_nodes.append(p_tag)
            fallback_tags.append(p_tag)
        segment_parts = []
        segment_attrs = {}

    def _append_preserved_tag(tag: Tag):
        _flush_segment()
        rebuilt_nodes.append(tag.extract())

    for child in list(body.contents):
        if isinstance(child, NavigableString):
            _append_text(str(child))
            continue

        if not isinstance(child, Tag):
            continue

        name = child.name
        if name in HIDDEN_TEXT_TAGS:
            child.extract()
            continue

        if name == "br":
            _flush_segment()
            child.extract()
            continue

        if name == "img":
            _append_preserved_tag(child)
            continue

        if name in BLOCK_SPLIT_TAGS:
            _flush_segment()
            text = extract_visible_text(child)
            if _compact_text_len(text):
                p_tag = soup.new_tag("p")
                for key, value in _first_anchor_attrs(child).items():
                    p_tag[key] = value
                p_tag.append(NavigableString(text))
                rebuilt_nodes.append(p_tag)
                fallback_tags.append(p_tag)
            elif child.find("img"):
                _append_preserved_tag(child)
            else:
                child.extract()
            continue

        _add_attrs(_first_anchor_attrs(child))
        _append_text(extract_visible_text(child))
        child.extract()

    _flush_segment()

    body.clear()
    for node in rebuilt_nodes:
        body.append(node)
        body.append(NavigableString("\n"))

    return fallback_tags


def extract_toc_titles(book: epub.EpubBook) -> list:
    """
    提取 EPUB 目录中的所有标题。

    Args:
        book: EPUB 电子书对象

    Returns:
        标题列表。
    """
    titles = []

    def _extract_from_item(item):
        """递归遍历目录项提取标题文本。"""
        if isinstance(item, (list, tuple)):
            if len(item) == 2:
                # 结构形式: (section, children)
                section, children = item
                _extract_from_item(section)
                for child in children:
                    _extract_from_item(child)
            elif len(item) >= 3:
                # 元组形式: (uid, href, title) 或更长
                title = item[2] if len(item) > 2 else None
                if title and isinstance(title, str) and title.strip():
                    titles.append(title.strip())
        elif hasattr(item, 'title'):
            # EpubLink 或 EpubNaviItem 对象
            if item.title and isinstance(item.title, str) and item.title.strip():
                titles.append(item.title.strip())
        elif isinstance(item, str) and item.strip():
            # 纯字符串标题
            titles.append(item.strip())

    if hasattr(book, 'toc') and book.toc:
        for item in book.toc:
            _extract_from_item(item)

    return titles


def apply_toc_translations(book: epub.EpubBook, translations: dict) -> None:
    """
    将翻译后的标题应用到 EPUB 目录中。

    Args:
        book: EPUB 电子书对象
        translations: {原标题: 翻译后的标题} 字典映射
    """
    def _apply_to_item(item):
        """递归遍历并替换对象属性中的标题。"""
        if isinstance(item, (list, tuple)):
            if len(item) == 2:
                section, children = item
                _apply_to_item(section)
                for child in children:
                    _apply_to_item(child)
            elif len(item) >= 3:
                # 元组形式: 此处不处理，由下面的 _update_tuple_item 处理
                pass
        elif hasattr(item, 'title'):
            # EpubLink 或 EpubNaviItem 对象 - 直接修改属性
            if item.title and item.title in translations:
                item.title = translations[item.title]

    def _update_tuple_item(item):
        """处理元组形式的目录项，创建新元组替换标题。"""
        if isinstance(item, (list, tuple)):
            if len(item) == 2:
                section, children = item
                new_section = _update_tuple_item(section)
                new_children = [_update_tuple_item(child) for child in children]
                return (new_section, new_children)
            elif len(item) >= 3:
                # 元组形式: (uid, href, title, ...)
                title = item[2] if len(item) > 2 else None
                if title and title in translations:
                    new_item = list(item)
                    new_item[2] = translations[title]
                    return tuple(new_item)
        return item

    if hasattr(book, 'toc') and book.toc:
        # 处理对象属性形式的目录项
        for item in book.toc:
            _apply_to_item(item)

        # 处理元组形式的目录项，需要创建新元组替换
        new_toc = []
        for item in book.toc:
            new_item = _update_tuple_item(item)
            new_toc.append(new_item)
        book.toc = new_toc


def repair_epub(path: str) -> str:
    """
    尝试修复损坏的 EPUB 文件，移除 manifest 中缺失的文件引用。

    返回修复后的临时文件路径。
    """
    logger.info(f"尝试修复损坏的 EPUB: {path}")

    temp_dir = tempfile.mkdtemp(prefix="epub_repair_")
    temp_epub = os.path.join(temp_dir, "repaired.epub")

    try:
        # 解压 EPUB
        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(temp_dir)

        # 查找 OPF 文件
        container_path = os.path.join(temp_dir, "META-INF", "container.xml")
        if not os.path.exists(container_path):
            raise ValueError("EPUB 缺少 META-INF/container.xml")

        container_soup = BeautifulSoup(
            Path(container_path).read_text(encoding="utf-8"),
            "xml"
        )
        opf_path = container_soup.find("rootfile").get("full-path")
        opf_full_path = os.path.join(temp_dir, opf_path)
        opf_dir = os.path.dirname(opf_full_path)

        # 解析 OPF
        opf_content = Path(opf_full_path).read_text(encoding="utf-8")
        opf_soup = BeautifulSoup(opf_content, "xml")

        # 检查并移除 manifest 中引用但实际缺失的文件

        # 遍历 manifest 中的每个 item
        manifest = opf_soup.find("manifest")
        removed_ids = []

        for item in list(manifest.find_all("item")):
            href = item.get("href")
            if not href:
                continue

            # URL 解码 + 处理路径中的特殊字符
            decoded_href = unquote(href)
            candidates = [href, decoded_href]

            found = False
            for candidate in candidates:
                file_path = os.path.join(opf_dir, candidate)
                if os.path.exists(file_path):
                    found = True
                    break

            if not found:
                item_id = item.get("id", "unknown")
                logger.warning(f"文件缺失: {href} (id={item_id})")
                item.decompose()
                removed_ids.append(item_id)

        logger.info(f"移除 {len(removed_ids)} 个缺失的文件引用: {removed_ids}")

        # 同步清理 spine 中的无效引用
        spine = opf_soup.find("spine")
        if spine and removed_ids:
            spine_removed = 0
            for itemref in list(spine.find_all("itemref")):
                idref = itemref.get("idref")
                if idref in removed_ids:
                    itemref.decompose()
                    spine_removed += 1
            if spine_removed > 0:
                logger.info(f"从 spine 移除 {spine_removed} 个无效引用")

        # 同步清理 guide 中的无效引用
        guide = opf_soup.find("guide")
        if guide and removed_ids:
            guide_removed = 0
            for reference in list(guide.find_all("reference")):
                href_ref = reference.get("href", "")
                # 检查引用是否包含已移除的文件名
                for removed_id in removed_ids:
                    if removed_id in href_ref:
                        reference.decompose()
                        guide_removed += 1
                        break
            if guide_removed > 0:
                logger.info(f"从 guide 移除 {guide_removed} 个无效引用")

        # 保存 OPF
        Path(opf_full_path).write_text(str(opf_soup), encoding="utf-8")

        # 重新打包 EPUB
        with zipfile.ZipFile(temp_epub, 'w', zipfile.ZIP_DEFLATED) as zf:
            mimetype_path = os.path.join(temp_dir, "mimetype")
            if os.path.exists(mimetype_path):
                zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, dirs, files in os.walk(temp_dir):
                if "repaired.epub" in files:
                    files.remove("repaired.epub")
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, temp_dir).replace("\\", "/")
                    if arc_name == "mimetype":
                        continue
                    zf.write(file_path, arc_name)

        logger.info(f"EPUB 修复完成: {temp_epub}")
        return temp_epub

    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(f"EPUB 修复失败: {e}")
    finally:
        # success path cleanup is delegated to save_book via _repaired_temp_path
        pass



def load_book(path: str, try_repair: bool = True) -> epub.EpubBook:
    """
    加载 EPUB 文件，失败时尝试自动修复。

    Args:
        path: EPUB 文件路径
        try_repair: 是否在加载失败时尝试修复损坏的 EPUB

    Returns:
        epub.EpubBook 对象
    """
    try:
        return epub.read_epub(path)
    except (KeyError, zipfile.BadZipFile, ValueError, OSError) as e:
        if not try_repair:
            raise RuntimeError(f"EPUB 文件损坏: {e}")

        logger.warning(f"EPUB 加载失败，尝试自动修复: {e}")

        repaired_path = repair_epub(path)
        try:
            book = epub.read_epub(repaired_path)
        except Exception:
            # repaired temp should not leak when read still fails
            repaired_dir = os.path.dirname(repaired_path)
            shutil.rmtree(repaired_dir, ignore_errors=True)
            raise
        book._repaired_temp_path = repaired_path
        return book


def iter_text_nodes(book: epub.EpubBook) -> Generator[Tuple[Any, BeautifulSoup, list], None, None]:
    """
    迭代 EPUB 文档中需要翻译的文本节点。

    Yields:
        (item, soup, tags): 文档项、解析后的 BeautifulSoup 对象、目标标签列表
    """
    for item in book.get_items():
        if _is_document_item(item):
            content = item.get_content()
            # Guard against empty/whitespace-only documents that cause
            # BeautifulSoup to raise Document is empty on Python 3.12+.
            raw = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content or "")
            if not raw.strip():
                logger.debug("Skipping empty document: %s", getattr(item, "file_name", "?"))
                continue
            soup = BeautifulSoup(raw, "html.parser")
            tags = soup.find_all(TARGET_TAGS)
            toc_link_tags = _find_inbook_toc_link_tags(soup, tags)
            if toc_link_tags:
                tags = tags + toc_link_tags
            elif _should_use_body_fallback(soup, tags):
                tags = _build_body_fallback_tags(soup)
            yield item, soup, tags


def _fix_toc_uids(toc, counter=None):
    """
    递归修复 toc 中 uid 为 None 的项目，生成有效的唯一 uid。

    ebooklib 的 read_epub 在某些 EPUB 中会解析出 uid 为 None，
    这是因为 NCX 文件中的 navPoint 可能没有指定 uid 属性。
    如果不修复，在写入时会因 uid=None 而导致格式错误。

    Args:
        toc: 目录列表，元素为对象或元组形式的 EpubNaviItem
        counter: 计数器列表，用于生成递增的 uid

    Returns:
        修复后的目录列表
    """
    if not toc:
        return []

    if counter is None:
        counter = [0]

    def _fix_item_uid(item):
        if isinstance(item, epub.Link) and item.uid is None:
            counter[0] += 1
            item.uid = f"navpoint-{counter[0]}"
        elif hasattr(item, "uid") and getattr(item, "uid", None) is None:
            counter[0] += 1
            item.uid = f"navpoint-{counter[0]}"
        return item

    def _is_supported_toc_object(item):
        return isinstance(item, (epub.Section, epub.Link, epub.EpubHtml)) or hasattr(item, "title")

    fixed = []
    for item in toc:
        # 处理嵌套结构 (section, children)
        if isinstance(item, (list, tuple)) and len(item) == 2:
            section, children = item
            if _is_supported_toc_object(section):
                section = _fix_item_uid(section)
                fixed_children = _fix_toc_uids(children, counter)
                fixed.append((section, fixed_children))
            elif isinstance(section, (list, tuple)):
                # 元组形式: (uid, href, title)
                section = list(section)
                if section[0] is None:
                    counter[0] += 1
                    section[0] = f"navpoint-{counter[0]}"
                section = tuple(section)
                fixed_children = _fix_toc_uids(children, counter)
                fixed.append((section, fixed_children))
        # 处理单独的对象项
        elif _is_supported_toc_object(item):
            item = _fix_item_uid(item)
            fixed.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 1:
            item = list(item)
            if item[0] is None:
                counter[0] += 1
                item[0] = f"navpoint-{counter[0]}"
            fixed.append(tuple(item))

    return fixed


def _apply_reading_direction_to_book(book: epub.EpubBook, chinese_mode: bool) -> None:
    """Apply page direction and language metadata before write."""
    if chinese_mode:
        page_direction = "ltr"
        writing_mode = "horizontal-lr"
        language = "zh"
    else:
        page_direction = "rtl"
        writing_mode = "vertical-rl"
        language = "ja"

    try:
        book.set_direction(page_direction)
    except Exception:
        pass
    try:
        book.set_language(language)
    except Exception:
        pass

    metadata_list = book.metadata.setdefault("http://www.idpf.org/2007/opf", {})
    metadata_list["meta"] = [
        entry for entry in metadata_list.get("meta", [])
        if not (len(entry) >= 2 and isinstance(entry[1], dict) and entry[1].get("name") == "primary-writing-mode")
    ]
    metadata_list.setdefault("meta", []).append((None, {"name": "primary-writing-mode", "content": writing_mode}))


def save_book(path: str, book: epub.EpubBook, chinese_mode: Optional[bool] = None) -> None:
    """保存 EPUB 文件。"""
    # 修复 uid=None 的 toc 项目
    if hasattr(book, 'toc') and book.toc:
        book.toc = _fix_toc_uids(book.toc)
    if chinese_mode is not None:
        _apply_reading_direction_to_book(book, chinese_mode)

    epub.write_epub(path, book, {})

    temp_path = getattr(book, '_repaired_temp_path', None)
    if temp_path and os.path.exists(temp_path):
        temp_dir = os.path.dirname(temp_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"清理临时目录: {temp_dir}")


def set_reading_direction(epub_path: str, chinese_mode: bool = True) -> None:
    """
    设置 EPUB 电子书的翻页方向。

    Args:
        epub_path: EPUB 文件路径
        chinese_mode: True 表示中文习惯从左到右，False 保持原版从右到左的日文排版
    """
    if chinese_mode:
        # 中文习惯横向排版从左到右
        page_direction = "ltr"
        writing_mode = "horizontal-lr"
        language = "zh"
    else:
        # 保持日文习惯纵向排版从右到左
        page_direction = "rtl"
        writing_mode = "vertical-rl"
        language = "ja"

    # 解压 EPUB
    temp_dir = tempfile.mkdtemp(prefix="epub_direction_")

    try:
        with zipfile.ZipFile(epub_path, 'r') as zf:
            zf.extractall(temp_dir)

        # 查找 OPF 文件
        container_path = os.path.join(temp_dir, "META-INF", "container.xml")
        if not os.path.exists(container_path):
            raise ValueError("EPUB 缺少 META-INF/container.xml")

        container_soup = BeautifulSoup(
            Path(container_path).read_text(encoding="utf-8"),
            "xml"
        )
        opf_path = container_soup.find("rootfile").get("full-path")
        opf_full_path = os.path.join(temp_dir, opf_path)

        # 解析并修改 OPF
        opf_content = Path(opf_full_path).read_text(encoding="utf-8")
        opf_soup = BeautifulSoup(opf_content, "xml")

        # 设置 page-progression-direction
        spine = opf_soup.find("spine")
        if spine:
            spine["page-progression-direction"] = page_direction

        # 设置 primary-writing-mode
        metadata = opf_soup.find("metadata")
        if metadata:
            # 查找并更新现有的 primary-writing-mode
            writing_mode_meta = metadata.find("meta", attrs={"name": "primary-writing-mode"})
            if writing_mode_meta:
                writing_mode_meta["content"] = writing_mode
            else:
                # 创建新的 meta
                new_meta = opf_soup.new_tag("meta")
                new_meta["name"] = "primary-writing-mode"
                new_meta["content"] = writing_mode
                metadata.append(new_meta)

            # 设置 dc:language
            dc_language = metadata.find("dc:language")
            if dc_language:
                dc_language.string = language
            else:
                # 创建新的 dc:language
                ns = {"dc": "http://purl.org/dc/elements/1.1/"}
                new_lang = opf_soup.new_tag("dc:language")
                new_lang.string = language
                metadata.append(new_lang)

        # 保存 OPF
        Path(opf_full_path).write_text(str(opf_soup), encoding="utf-8")

        # 重新打包 EPUB
        with zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            mimetype_path = os.path.join(temp_dir, "mimetype")
            if os.path.exists(mimetype_path):
                zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, temp_dir).replace("\\", "/")
                    if arc_name == "mimetype":
                        continue
                    zf.write(file_path, arc_name)

        logger.info(f"设置翻页方向: {page_direction}, {writing_mode}, language={language}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
