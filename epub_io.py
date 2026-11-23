import logging
import html
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Generator, Tuple, Any, Dict, Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import epub, ITEM_DOCUMENT

logger = logging.getLogger(__name__)

TARGET_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"]
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

def _default_translation_notice_text() -> str:
    """Build the default notice text without importing UI modules at module load."""
    try:
        from backend.app_info import APP_DISPLAY_NAME
    except Exception:  # pragma: no cover - core module can run without the QML package
        try:
            from experimental.qml_v4.backend.app_info import APP_DISPLAY_NAME
        except Exception:  # pragma: no cover
            # 注意：这是运行在源码树根目录时的常见路径，回退值是预期行为，
            # 因此用 debug 级别，避免每次生成版权页都刷一条告警。
            logger.debug("未能导入 APP_DISPLAY_NAME，使用内置产品名", exc_info=True)
            APP_DISPLAY_NAME = "AI日译中（EPUB）"
    return (
        f"本书由 {APP_DISPLAY_NAME} 辅助翻译。\n"
        "译文仅供个人学习、研究与阅读辅助使用，请勿传播或用于商业用途。\n"
        "请支持并购买正版书籍。"
    )


def default_notice_extra_note() -> str:
    """Default footnote describing what this edition normalised.

    Shown at the bottom of the notice page, in smaller type. Kept separate from
    the legal text so users can edit the disclaimer without losing it.
    """
    return "本译本已做术语与语言风格统一（人物昵称全书一致、去除文言腔与对白成语化）。"


DEFAULT_TRANSLATION_NOTICE_TEXT = _default_translation_notice_text()
TRANSLATION_NOTICE_UID = "ai-jp-zh-translation-notice"
TRANSLATION_NOTICE_FILE_NAME = "translation_notice.xhtml"


def extract_book_bibliography(book: epub.EpubBook) -> Dict[str, str]:
    """Read title / author / publisher from EPUB metadata.

    Used by the notice page so the version info is accompanied by the actual
    book identity instead of a bare "translated by ..." line.

    Returns a dict with any of: ``title``, ``author``, ``publisher``, ``language``.
    Missing values are simply absent; never raises.
    """
    result: Dict[str, str] = {}

    def _first(namespace: str, name: str) -> str:
        try:
            values = book.get_metadata(namespace, name) or []
        except Exception:
            # 元数据缺失是常态（很多 EPUB 没有 dc:creator），按不存在处理；
            # 但 DUBLIN CORE 读取异常会让书名/作者静默变空，值得留痕。
            logger.debug("读取 EPUB 元数据失败: %s:%s", namespace, name, exc_info=True)
            return ""
        for value in values:
            # ebooklib returns [(text, attributes_dict), ...]
            if isinstance(value, (tuple, list)) and value:
                text = str(value[0] or "").strip()
            else:
                text = str(value or "").strip()
            if text:
                return text
        return ""

    try:
        title = _first("DC", "title")
        if title:
            result["title"] = title
        creator = _first("DC", "creator")
        if creator:
            result["author"] = creator
        publisher = _first("DC", "publisher")
        if publisher:
            result["publisher"] = publisher
        language = _first("DC", "language")
        if language:
            result["language"] = language
    except Exception as exc:  # pragma: no cover - metadata access is defensive
        logger.debug("读取书目信息失败: %s", exc)
    return result


def extract_visible_text(node: Any) -> str:
    """Extract display text while skipping ruby annotations and hidden tags.

    Elements marked ``lang="ja"`` are emitted wrapped in the authorized-span
    delimiter (``[[ja:...]]``). The notice page uses that to keep the Japanese
    original title while telling the residue checker the Japanese is intentional
    rather than untranslated text.
    """
    parts = []

    def _is_authorized_japanese(current: Any) -> bool:
        try:
            lang = str(current.get("lang") or current.get("xml:lang") or "").lower()
        except Exception:
            logger.debug("读取节点 lang 属性失败，按非日文处理", exc_info=True)
            return False
        return lang.startswith("ja")

    def _walk(current):
        if isinstance(current, NavigableString):
            parts.append(str(current))
            return
        if not isinstance(current, Tag):
            return
        if current.name in HIDDEN_TEXT_TAGS:
            return
        authorized = _is_authorized_japanese(current)
        if authorized:
            inner = []
            for child in current.children:
                if isinstance(child, NavigableString):
                    inner.append(str(child))
                elif isinstance(child, Tag) and child.name not in HIDDEN_TEXT_TAGS:
                    inner.append(child.get_text())
            literal = "".join(inner).strip()
            if literal:
                parts.append(f"[[ja:{literal}]]")
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


def _content_body_visible_text(content: Any) -> str:
    if content is None:
        return ""
    try:
        soup = BeautifulSoup(content, "html.parser")
        return extract_visible_text(soup.find("body") or soup)
    except Exception as exc:
        logger.debug("解析文档可见文本失败: %s", exc)
        return ""


def _document_content_for_parsing(item: Any) -> Any:
    content = item.get_content()
    raw_content = getattr(item, "content", None)
    if raw_content and _compact_text_len(_content_body_visible_text(content)) == 0:
        if _compact_text_len(_content_body_visible_text(raw_content)) > 0:
            return raw_content
    return content


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
    if body_chars == 0 or not _has_japanese_text(body_text):
        return False

    target_chars = sum(_compact_text_len(extract_visible_text(tag)) for tag in tags)
    if target_chars == 0:
        return True

    if body_chars < BODY_FALLBACK_MIN_CHARS:
        return False

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
            for root, _dirs, files in os.walk(temp_dir):
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
        # 这里会重新抛出更明确的错误，但原始异常类型对定位很关键
        # （例如 BadZipFile vs PermissionError 的处理方式完全不同）。
        logger.error("EPUB 修复失败: %s", temp_epub, exc_info=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        # 保留原始异常链：BadZipFile / PermissionError 等底层原因对定位至关重要。
        raise RuntimeError(f"EPUB 修复失败: {e}") from e
    finally:
        # success path cleanup is delegated to save_book via _repaired_temp_path
        pass


def _epub_opf_dir(path: str) -> str:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            container = zf.read("META-INF/container.xml").decode("utf-8", errors="ignore")
        soup = BeautifulSoup(container, "xml")
        rootfile = soup.find("rootfile")
        opf_path = rootfile.get("full-path") if rootfile else ""
        return str(Path(opf_path).parent).replace("\\", "/").strip(".")
    except Exception as exc:
        logger.debug("读取 EPUB OPF 目录失败: %s", exc)
        return ""


def _restore_raw_document_content(book: epub.EpubBook, path: str) -> None:
    """Restore raw XHTML when ebooklib drops body-direct text during read."""
    try:
        opf_dir = _epub_opf_dir(path)
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            for item in book.get_items():
                if not _is_document_item(item):
                    continue
                file_name = str(getattr(item, "file_name", "") or "").replace("\\", "/")
                if not file_name:
                    continue
                candidates = [file_name]
                if opf_dir:
                    candidates.append(f"{opf_dir}/{file_name}".strip("/"))
                raw_name = next((name for name in candidates if name in names), "")
                if not raw_name:
                    continue
                raw = zf.read(raw_name)
                if not raw or not raw.strip():
                    continue
                try:
                    current_soup = BeautifulSoup(item.get_content() or b"", "html.parser")
                    raw_soup = BeautifulSoup(raw, "html.parser")
                    current_visible = extract_visible_text(current_soup.find("body") or current_soup)
                    raw_visible = extract_visible_text(raw_soup.find("body") or raw_soup)
                except Exception as exc:
                    logger.debug("解析文档内容失败，跳过 raw 恢复: %s (%s)", file_name, exc)
                    continue
                if _compact_text_len(current_visible) == 0 and _compact_text_len(raw_visible) > 0:
                    item.content = raw
                    logger.info("Restored raw XHTML content dropped by ebooklib: %s", file_name)
    except Exception as exc:
        logger.debug("Skipping raw XHTML restore: %s", exc)



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
        book = epub.read_epub(path)
        _restore_raw_document_content(book, path)
        return book
    except (KeyError, zipfile.BadZipFile, ValueError, OSError) as e:
        if not try_repair:
            # 带上原始异常，否则调用方只能看到 "EPUB 文件损坏" 而不知是哪种损坏。
            raise RuntimeError(f"EPUB 文件损坏: {e}") from e

        logger.warning(f"EPUB 加载失败，尝试自动修复: {e}")

        repaired_path = repair_epub(path)
        try:
            book = epub.read_epub(repaired_path)
        except Exception:
            # 修复后仍读不出来，说明文件确实不可用；这里会向上抛，
            # 但要记录一次，否则日志里只有「尝试自动修复」而没有失败结局。
            logger.error("修复后的 EPUB 仍无法读取: %s", repaired_path, exc_info=True)
            # repaired temp should not leak when read still fails
            repaired_dir = os.path.dirname(repaired_path)
            shutil.rmtree(repaired_dir, ignore_errors=True)
            raise
        _restore_raw_document_content(book, repaired_path)
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
            content = _document_content_for_parsing(item)
            # Guard against empty/whitespace-only documents that cause
            # BeautifulSoup to raise Document is empty on Python 3.12+.
            if content is None or not content.strip():
                logger.debug("Skipping empty document: %s", getattr(item, "file_name", "?"))
                continue
            soup = BeautifulSoup(content, "html.parser")
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
    except Exception as exc:
        logger.debug("设置阅读方向失败: %s", exc)
    try:
        book.set_language(language)
    except Exception as exc:
        logger.debug("设置语言元数据失败: %s", exc)

    metadata_list = book.metadata.setdefault("http://www.idpf.org/2007/opf", {})
    metadata_list["meta"] = [
        entry for entry in metadata_list.get("meta", [])
        if not (len(entry) >= 2 and isinstance(entry[1], dict) and entry[1].get("name") == "primary-writing-mode")
    ]
    metadata_list.setdefault("meta", []).append((None, {"name": "primary-writing-mode", "content": writing_mode}))


def set_book_title_metadata(book: epub.EpubBook, title: str) -> bool:
    """Replace EPUB dc:title metadata with a single validated title."""
    clean_title = str(title or "").strip()
    if not clean_title:
        return False

    dc_namespace = "http://purl.org/dc/elements/1.1/"
    metadata_list = book.metadata.setdefault(dc_namespace, {})
    existing_titles = metadata_list.get("title", [])
    attrs = None
    if existing_titles:
        first = existing_titles[0]
        if len(first) >= 2 and isinstance(first[1], dict):
            attrs = dict(first[1])
    metadata_list["title"] = [(clean_title, attrs)]
    try:
        book.title = clean_title
    except Exception as exc:
        logger.debug("设置书名 title 属性失败: %s", exc)
    return True


def _to_simplified(text: str) -> str:
    """Best-effort conversion of Japanese/traditional kanji to Simplified Chinese.

    EPUB metadata frequently carries the original Japanese author and publisher
    (e.g. ``浅倉秋成`` / ``講談社``). They contain no kana so the residue checker
    passes them, but printing traditional forms on a Simplified Chinese notice
    page is still wrong.

    Uses a small explicit map instead of a full conversion table: these values are
    short proper nouns, and a dependency-free lookup keeps the core module light.
    Unknown characters are left untouched.
    """
    mapping = {
        "倉": "仓", "講": "讲", "談": "谈", "淺": "浅",
        "島": "岛", "澤": "泽", "邊": "边", "國": "国", "學": "学",
        "會": "会", "實": "实", "寫": "写", "說": "说", "讀": "读",
        "書": "书", "畫": "画", "點": "点", "數": "数", "據": "据",
        "東": "东", "戶": "户", "馬": "马", "鳥": "鸟", "魚": "鱼",
        "龍": "龙", "鳳": "凤", "藝": "艺", "術": "术", "廣": "广",
        "場": "场", "館": "馆", "閣": "阁", "產": "产", "業": "业",
        "經": "经", "濟": "济", "週": "周", "間": "间", "開": "开",
        "關": "关", "門": "门", "題": "题", "報": "报", "紙": "纸",
        "筆": "笔", "記": "记", "話": "话", "語": "语", "譯": "译",
        "誤": "误", "訂": "订", "嶋": "岛", "齋": "斋", "藤": "藤",
    }
    return "".join(mapping.get(ch, ch) for ch in (text or ""))


def _looks_like_japanese_title(text: str) -> bool:
    """True when the string contains Japanese kana (i.e. it is an original title)."""
    return bool(re.search(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]", text or ""))


def _looks_like_chinese_title(text: str) -> bool:
    """True when the string reads as Chinese rather than leftover Japanese.

    A title with no CJK characters at all (e.g. an English name) is treated as
    acceptable, since it carries no residue risk. Kana anywhere disqualifies it.
    """
    value = (text or "").strip()
    if not value:
        return False
    if _looks_like_japanese_title(value):
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", value)) or bool(re.search(r"[A-Za-z]", value))


def _translation_notice_html(
    notice_text: str,
    bibliography: Optional[Dict[str, str]] = None,
    extra_note: str = "",
    show_original_title: bool = False,
) -> str:
    """Build the notice page markup.

    Layout: a book-identity block (only the fields actually present), a rule, then
    the free-form notice lines. Keeping the identity block optional means callers
    that only pass plain text still get a valid, minimal page.

    ``show_original_title`` keeps the Japanese original title on the page. It is
    wrapped in ``<span lang="ja">`` for readers and additionally marker-delimited
    when the visible text is produced, so the residue checker treats it as an
    authorized citation rather than untranslated text.
    """
    text = (notice_text or DEFAULT_TRANSLATION_NOTICE_TEXT).strip() or DEFAULT_TRANSLATION_NOTICE_TEXT
    paragraphs = [
        f"<p>{html.escape(line.strip())}</p>"
        for line in text.splitlines()
        if line.strip()
    ]
    body = "\n        ".join(paragraphs) or f"<p>{html.escape(DEFAULT_TRANSLATION_NOTICE_TEXT)}</p>"

    meta_rows = []
    bib = dict(bibliography or {})

    # dc:title 在翻译前是原文标题。含假名说明它是日文原题，
    # 不能当「中文书名」用。
    chinese_title = str(bib.get("title") or "").strip()
    japanese_original = ""
    if chinese_title and _looks_like_japanese_title(chinese_title):
        japanese_original = chinese_title
        chinese_title = ""

    # 「原书名」：调用方显式给了就用它；否则在开关打开时回退到日文原题。
    original_title_value = str(bib.get("original_title") or "").strip()
    if not original_title_value and show_original_title:
        original_title_value = japanese_original

    # 日文原题只有在开关打开时才渲染，并用 <span lang="ja"> 标记，
    # 既让阅读器按日文字体排版，也便于后续识别为"授权引用"。
    original_is_japanese = bool(original_title_value) and _looks_like_japanese_title(original_title_value)
    if original_is_japanese and not show_original_title:
        original_title_value = ""

    for label, value in (
        ("原书名", original_title_value),
        ("中文书名", chinese_title),
        ("作者", _to_simplified(str(bib.get("author") or "").strip())),
        ("出版", _to_simplified(str(bib.get("publisher") or "").strip())),
    ):
        if not value:
            continue
        if label == "原书名" and original_is_japanese:
            rendered = (
                f'<span lang="ja" class="notice-ja">{html.escape(value)}</span>'
            )
        else:
            rendered = html.escape(value)
        meta_rows.append(
            f'<p class="notice-meta">{html.escape(label)}：{rendered}</p>'
        )

    meta_block = ""
    if meta_rows:
        meta_block = (
            '<div class="notice-book">\n        '
            + "\n        ".join(meta_rows)
            + '\n      </div>\n      <hr/>'
        )

    extra_block = ""
    if extra_note.strip():
        extra_block = f'\n      <p class="notice-tip">{html.escape(extra_note.strip())}</p>'

    return f"""<html>
  <head>
    <style>
      body {{ margin: 2.5em; line-height: 1.8; font-family: serif; }}
      h1 {{ font-size: 1.4em; margin-bottom: 1.5em; }}
      p {{ margin: 0 0 0.9em 0; }}
      .notice-book p {{ margin: 0.2em 0; }}
      hr {{ margin: 1.2em 0; border: none; border-top: 1px solid #ccc; }}
      .notice-tip {{ margin-top: 1.2em; font-size: 0.85em; opacity: 0.75; }}
    </style>
  </head>
  <body>
    <section epub:type="notice">
      <h1>版权提示</h1>
      {meta_block}
      {body}{extra_block}
    </section>
  </body>
</html>
"""


def add_translation_notice_page(
    book: epub.EpubBook,
    notice_text: Optional[str] = None,
    *,
    original_title: str = "",
    extra_note: str = "",
    show_original_title: bool = False,
) -> None:
    """Insert a standalone notice page after the cover when it can be detected.

    Parameters
    ----------
    notice_text:
        Free-form notice body (one line per paragraph). Falls back to the default.
    original_title:
        The source book's original title. EPUB metadata holds the *translated*
        title after ``set_book_title_metadata`` runs, so the original has to be
        passed in explicitly if it should appear on the page.
    extra_note:
        Optional footnote, used for "this edition was normalised" style remarks.
    show_original_title:
        When True, a Japanese original title is kept on the page wrapped in
        ``<span lang="ja">`` and marked as an authorized citation, so residue
        checks ignore it. When False (default) Japanese titles are omitted.
    """
    def _resolve_spine_entry(entry: Any) -> Any:
        candidate = entry[0] if isinstance(entry, tuple) and entry else entry
        if isinstance(candidate, str):
            try:
                return book.get_item_with_id(candidate)
            except Exception as exc:
                logger.debug("按 id 解析 spine 条目失败: %s (%s)", candidate, exc)
                return None
        return candidate

    def _spine_entry_key(entry: Any) -> str:
        original = entry[0] if isinstance(entry, tuple) and entry else entry
        resolved = _resolve_spine_entry(entry)
        if resolved is None:
            return str(original or "").lower()
        parts = [
            str(original or ""),
            str(getattr(resolved, "id", "") or ""),
            str(getattr(resolved, "file_name", "") or ""),
            str(getattr(resolved, "title", "") or ""),
            str(getattr(resolved, "media_type", "") or ""),
        ]
        if hasattr(resolved, "get_id"):
            try:
                parts.append(str(resolved.get_id() or ""))
            except Exception as exc:
                logger.debug("读取 spine 条目 id 失败: %s", exc)
        return " ".join(parts).lower()

    def _is_cover_spine_entry(entry: Any) -> bool:
        key = _spine_entry_key(entry)
        if any(marker in key for marker in ("cover", "frontcover", "titlepage", "封面")):
            return True
        item = _resolve_spine_entry(entry)
        if item is None:
            return False
        try:
            raw = item.get_content() if hasattr(item, "get_content") else getattr(item, "content", b"")
        except Exception as exc:
            logger.debug("读取封面条目内容失败，回退 content 属性: %s", exc)
            raw = getattr(item, "content", b"")
        if isinstance(raw, bytes):
            markup = raw.decode("utf-8", errors="ignore")
        else:
            markup = str(raw or "")
        if not markup:
            return False
        soup = BeautifulSoup(markup, "html.parser")
        has_cover_image = soup.find(["img", "svg", "image"]) is not None
        visible = extract_visible_text(soup.body or soup)
        return has_cover_image and _compact_text_len(visible) <= 20

    def _is_notice_spine_entry(entry: Any) -> bool:
        item = _resolve_spine_entry(entry)
        if item is existing:
            return True
        key = _spine_entry_key(entry)
        return TRANSLATION_NOTICE_UID in key or TRANSLATION_NOTICE_FILE_NAME.lower() in key

    existing = None
    for item in book.get_items():
        item_id = item.get_id() if hasattr(item, "get_id") else getattr(item, "uid", None)
        if item_id == TRANSLATION_NOTICE_UID:
            existing = item
            break

    content = _translation_notice_html(
        notice_text,
        bibliography={
            "original_title": original_title,
            **extract_book_bibliography(book),
        },
        extra_note=extra_note,
        show_original_title=show_original_title,
    )
    if existing is None:
        existing = epub.EpubHtml(
            uid=TRANSLATION_NOTICE_UID,
            file_name=TRANSLATION_NOTICE_FILE_NAME,
            title="版权提示",
            lang="zh-CN",
        )
        book.add_item(existing)

    existing.set_content(content.encode("utf-8"))

    spine = list(getattr(book, "spine", []) or [])
    spine = [entry for entry in spine if not _is_notice_spine_entry(entry)]
    insert_at = 0
    for index, entry in enumerate(spine[:3]):
        if _is_cover_spine_entry(entry):
            insert_at = index + 1
            break
    spine.insert(insert_at, existing)
    book.spine = spine


def save_book(path: str, book: epub.EpubBook, chinese_mode: Optional[bool] = None) -> None:
    """保存 EPUB 文件。"""
    # 修复 uid=None 的 toc 项目
    if hasattr(book, 'toc') and book.toc:
        book.toc = _fix_toc_uids(book.toc)
    if chinese_mode is not None:
        _apply_reading_direction_to_book(book, chinese_mode)

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_output = tempfile.mkstemp(
        prefix=f".{output_path.stem}.",
        suffix=".tmp.epub",
        dir=str(output_path.parent),
    )
    os.close(temp_fd)
    try:
        # ebooklib's EPUB3 page-list generation fails on valid XHTML whose body
        # contains direct text nodes but no child tags. Disable it; the normal
        # table of contents is still written.
        logger.info("正在写入 EPUB (page-list 已禁用)...")
        epub.write_epub(temp_output, book, {"epub3_pages": False})
        logger.info("EPUB 已写入临时文件: %s (%d bytes)", temp_output, os.path.getsize(temp_output))
        os.replace(temp_output, path)
        logger.info("EPUB 已保存: %s (%d bytes)", path, os.path.getsize(path))
    except Exception:
        logger.exception("EPUB 写入失败，路径: %s", path)
        try:
            os.remove(temp_output)
        except OSError as exc:
            logger.debug("清理临时 EPUB 文件失败: %s (%s)", temp_output, exc)
        raise

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
            for root, _dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, temp_dir).replace("\\", "/")
                    if arc_name == "mimetype":
                        continue
                    zf.write(file_path, arc_name)

        logger.info(f"设置翻页方向: {page_direction}, {writing_mode}, language={language}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
