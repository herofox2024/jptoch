import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Generator, Tuple, Any
from urllib.parse import unquote

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT

logger = logging.getLogger(__name__)

TARGET_TAGS = ["p", "h1", "h2", "h3", "li", "blockquote"]


def extract_toc_titles(book: epub.EpubBook) -> list:
    """
    提取 EPUB 目录中的所有标题

    Args:
        book: EPUB 书籍对象

    Returns:
        标题文本列表
    """
    titles = []

    def _extract_from_item(item):
        """递归提取目录项中的标题"""
        if isinstance(item, (list, tuple)):
            if len(item) == 2:
                # 嵌套结构: (section, children)
                section, children = item
                _extract_from_item(section)
                for child in children:
                    _extract_from_item(child)
            elif len(item) >= 3:
                # 元组形式: (uid, href, title) 或类似
                title = item[2] if len(item) > 2 else None
                if title and isinstance(title, str) and title.strip():
                    titles.append(title.strip())
        elif hasattr(item, 'title'):
            # EpubLink 或 EpubNaviItem 对象
            if item.title and isinstance(item.title, str) and item.title.strip():
                titles.append(item.title.strip())
        elif isinstance(item, str) and item.strip():
            # 纯字符串
            titles.append(item.strip())

    if hasattr(book, 'toc') and book.toc:
        for item in book.toc:
            _extract_from_item(item)

    return titles


def apply_toc_translations(book: epub.EpubBook, translations: dict) -> None:
    """
    将翻译后的标题应用到 EPUB 目录

    Args:
        book: EPUB 书籍对象
        translations: {原文标题: 翻译后标题} 字典
    """
    def _apply_to_item(item):
        """递归应用翻译到目录项"""
        if isinstance(item, (list, tuple)):
            if len(item) == 2:
                section, children = item
                _apply_to_item(section)
                for child in children:
                    _apply_to_item(child)
            elif len(item) >= 3:
                # 元组形式: 修改标题（元组需要整体替换）
                pass
        elif hasattr(item, 'title'):
            # EpubLink 或 EpubNaviItem 对象 - 直接修改属性
            if item.title and item.title in translations:
                item.title = translations[item.title]

    def _update_tuple_item(item):
        """处理元组形式的目录项，返回更新后的元组"""
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
        # 处理对象形式的目录项
        for item in book.toc:
            _apply_to_item(item)

        # 处理元组形式的目录项（需要整体替换）
        new_toc = []
        for item in book.toc:
            new_item = _update_tuple_item(item)
            new_toc.append(new_item)
        book.toc = new_toc


def repair_epub(path: str) -> str:
    """
    修复损坏的 EPUB 文件（manifest 引用了不存在的文件）

    返回修复后的临时文件路径
    """
    logger.info(f"尝试修复 EPUB: {path}")

    temp_dir = tempfile.mkdtemp(prefix="epub_repair_")
    temp_epub = os.path.join(temp_dir, "repaired.epub")

    try:
        # 解压 EPUB
        with zipfile.ZipFile(path, 'r') as zf:
            zf.extractall(temp_dir)

        # 找到 OPF 文件
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

        # 收集解压后实际存在的文件路径（用于模糊匹配）
        existing_files = set()
        for root, dirs, files in os.walk(opf_dir):
            for f in files:
                existing_files.add(os.path.join(root, f))

        # 检查 manifest 中每个 item 是否存在
        manifest = opf_soup.find("manifest")
        removed_ids = []

        for item in list(manifest.find_all("item")):
            href = item.get("href")
            if not href:
                continue

            # URL 解码 + 原始路径都检查
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
                logger.warning(f"缺失文件: {href} (id={item_id})")
                item.decompose()
                removed_ids.append(item_id)

        logger.info(f"已移除 {len(removed_ids)} 个缺失文件引用: {removed_ids}")

        # 清理 spine 中对已删除文件的引用
        spine = opf_soup.find("spine")
        if spine and removed_ids:
            spine_removed = 0
            for itemref in list(spine.find_all("itemref")):
                idref = itemref.get("idref")
                if idref in removed_ids:
                    itemref.decompose()
                    spine_removed += 1
            if spine_removed > 0:
                logger.info(f"已清理 spine 中 {spine_removed} 个无效引用")

        # 清理 guide 中对已删除文件的引用
        guide = opf_soup.find("guide")
        if guide and removed_ids:
            guide_removed = 0
            for reference in list(guide.find_all("reference")):
                href_ref = reference.get("href", "")
                # 检查引用的文件是否在移除列表中
                for removed_id in removed_ids:
                    if removed_id in href_ref:
                        reference.decompose()
                        guide_removed += 1
                        break
            if guide_removed > 0:
                logger.info(f"已清理 guide 中 {guide_removed} 个无效引用")

        # 写回 OPF
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


def load_book(path: str, try_repair: bool = True) -> epub.EpubBook:
    """
    加载 EPUB 文件，支持自动修复损坏文件

    Args:
        path: EPUB 文件路径
        try_repair: 是否尝试修复损坏的 EPUB

    Returns:
        epub.EpubBook 对象
    """
    try:
        return epub.read_epub(path)
    except (KeyError, zipfile.BadZipFile, ValueError, OSError) as e:
        if not try_repair:
            raise RuntimeError(f"EPUB 文件损坏: {e}")

        logger.warning(f"EPUB 读取失败，尝试修复: {e}")

        repaired_path = repair_epub(path)
        book = epub.read_epub(repaired_path)
        book._repaired_temp_path = repaired_path

        return book


def iter_text_nodes(book: epub.EpubBook) -> Generator[Tuple[Any, BeautifulSoup, list], None, None]:
    """
    迭代 EPUB 中的所有文本节点

    Yields:
        (item, soup, tags): 文档项、解析树、目标标签列表
    """
    for item in book.get_items():
        if item.get_type() == ITEM_DOCUMENT:
            content = item.get_content()
            soup = BeautifulSoup(content, "html.parser")
            tags = soup.find_all(TARGET_TAGS)
            yield item, soup, tags


def _fix_toc_uids(toc, counter=None):
    """
    递归修复 toc 中 uid 为 None 的条目，为其分配自增 uid

    ebooklib 的 read_epub 读取时，很多 EPUB 的目录条目 uid 为 None，
    这本身是合法的，但 ebooklib 写入 NCX 时需要 uid 才能生成正确的 navPoint。
    之前的做法是移除 uid=None 的条目，导致目录被清空。

    Args:
        toc: 目录列表，每个元素可能是元组或 EpubNaviItem
        counter: 计数器，用于生成唯一 uid

    Returns:
        修复后的目录列表
    """
    if not toc:
        return []

    if counter is None:
        counter = [0]

    fixed = []
    for item in toc:
        # 处理嵌套结构: (section, children)
        if isinstance(item, (list, tuple)) and len(item) == 2:
            section, children = item
            if hasattr(section, 'uid'):
                if section.uid is None:
                    counter[0] += 1
                    section.uid = f"navpoint-{counter[0]}"
                fixed_children = _fix_toc_uids(children, counter)
                if fixed_children:
                    fixed.append((section, fixed_children))
            elif isinstance(section, (list, tuple)):
                # 元组形式: (uid, href, title)
                section = list(section)
                if section[0] is None:
                    counter[0] += 1
                    section[0] = f"navpoint-{counter[0]}"
                section = tuple(section)
                fixed_children = _fix_toc_uids(children, counter)
                if fixed_children:
                    fixed.append((section, fixed_children))
        # 处理普通条目
        elif hasattr(item, 'uid'):
            if item.uid is None:
                counter[0] += 1
                item.uid = f"navpoint-{counter[0]}"
            fixed.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 1:
            item = list(item)
            if item[0] is None:
                counter[0] += 1
                item[0] = f"navpoint-{counter[0]}"
            fixed.append(tuple(item))

    return fixed


def save_book(path: str, book: epub.EpubBook) -> None:
    """保存 EPUB 文件"""
    # 修复 uid=None 的 toc 条目
    if hasattr(book, 'toc') and book.toc:
        book.toc = _fix_toc_uids(book.toc)

    epub.write_epub(path, book, {})

    temp_path = getattr(book, '_repaired_temp_path', None)
    if temp_path and os.path.exists(temp_path):
        temp_dir = os.path.dirname(temp_path)
        shutil.rmtree(temp_dir, ignore_errors=True)
        logger.info(f"已清理临时文件: {temp_dir}")


def set_reading_direction(epub_path: str, chinese_mode: bool = True) -> None:
    """
    设置 EPUB 的阅读方向

    Args:
        epub_path: EPUB 文件路径
        chinese_mode: True 为中文习惯（从左到右），False 保持原版（日文从右到左）
    """
    if chinese_mode:
        # 中文习惯：从左到右
        page_direction = "ltr"
        writing_mode = "horizontal-lr"
        language = "zh"
    else:
        # 日文习惯：从右到左
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

        # 修改 page-progression-direction
        spine = opf_soup.find("spine")
        if spine:
            spine["page-progression-direction"] = page_direction

        # 修改 primary-writing-mode
        metadata = opf_soup.find("metadata")
        if metadata:
            # 查找并修改现有的 primary-writing-mode
            writing_mode_meta = metadata.find("meta", attrs={"name": "primary-writing-mode"})
            if writing_mode_meta:
                writing_mode_meta["content"] = writing_mode
            else:
                # 添加新的 meta
                new_meta = opf_soup.new_tag("meta")
                new_meta["name"] = "primary-writing-mode"
                new_meta["content"] = writing_mode
                metadata.append(new_meta)

            # 修改 dc:language
            dc_language = metadata.find("dc:language")
            if dc_language:
                dc_language.string = language
            else:
                # 添加新的 dc:language
                ns = {"dc": "http://purl.org/dc/elements/1.1/"}
                new_lang = opf_soup.new_tag("dc:language")
                new_lang.string = language
                metadata.append(new_lang)

        # 写回 OPF
        Path(opf_full_path).write_text(str(opf_soup), encoding="utf-8")

        # 重新打包 EPUB
        with zipfile.ZipFile(epub_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_name = os.path.relpath(file_path, temp_dir).replace("\\", "/")
                    if file == "mimetype":
                        zf.write(file_path, arc_name, compress_type=zipfile.ZIP_STORED)
                    else:
                        zf.write(file_path, arc_name)

        logger.info(f"已设置阅读方向: {page_direction}, {writing_mode}, language={language}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
