"""Output EPUB filename and translated TOC title normalization."""

from __future__ import annotations

import time
from pathlib import Path

import translation_quality as tq


FILENAME_EXPLANATION_MARKERS = (
    "或依意译", "意译处理", "没有更多信息", "没更多信息", "暂无更多信息", "暂无信息",
    "这里保留", "此处保留", "可译为", "也可译作", "翻译为", "译作", "直译", "音译",
    "合适名", "说明", "注：", "注:",
)

TOC_EXPLANATION_MARKERS = FILENAME_EXPLANATION_MARKERS + (
    "简写", "简称", "希腊神话", "神话中", "之女", "意为", "意思是", "指的是", "源自",
    "来自", "出处", "典故", "可理解为", "补充", "背景", "炫耀", "射杀", "化作", "永远流动",
)

TOC_TRAILING_AUTHOR_NAMES = (
    "恒川光太郎", "坂东真砂子", "宇佐美诚", "宇佐美まこと", "小林泰三", "竹本健治",
    "小松左京", "平山梦明", "服部麻由美",
)


def sanitize_filename(name: str) -> str:
    invalid = '<>:"/\\|?*'
    cleaned = "".join("_" if char in invalid or ord(char) < 32 else char for char in name)
    cleaned = " ".join(cleaned.split()).strip(" ._")
    if cleaned.lower().endswith(".epub"):
        cleaned = cleaned[:-5].strip(" ._")
    cleaned = cleaned[:120].strip(" ._")
    if not cleaned:
        return ""
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved |= {f"COM{index}" for index in range(1, 10)} | {f"LPT{index}" for index in range(1, 10)}
    if cleaned.split(".", 1)[0].upper() in reserved:
        cleaned += "_"
    return cleaned


def strip_model_explanation_notes(text: str, markers) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    changed = True
    while changed:
        changed = False
        for left, right in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")):
            start = value.find(left)
            while start != -1:
                depth = 1
                end = start + 1
                while end < len(value) and depth > 0:
                    if value.startswith(left, end):
                        depth += 1
                        end += len(left)
                        continue
                    if value.startswith(right, end):
                        depth -= 1
                        if depth == 0:
                            break
                        end += len(right)
                        continue
                    end += 1
                if depth > 0:
                    break
                segment = value[start + 1:end]
                if any(marker in segment for marker in markers):
                    value = value[:start] + value[end + 1:]
                    changed = True
                    start = value.find(left, max(0, start - 1))
                    continue
                start = value.find(left, end + 1)

    value = value.replace(" _ ", " ").replace("_", " ")
    value = " ".join(value.split())
    for mark in ("，)", "、)", "(，", "(、", "，）", "、）", "（，", "（、"):
        value = value.replace(mark, mark[-1] if mark[0] in "，、" else mark[0])
    value = value.replace(" ,", ",").replace(" ，", "，").replace(" 、", "、")
    return value.strip(" ._+-＋，、")


def looks_like_model_refusal(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return True
    hard_markers = (
        "请提供具体的日文段落", "请提供具体的日文", "不是需要翻译的日文内容", "并非需要翻译的日文内容",
        "书名或文件名称", "似乎是书名", "无法按照要求翻译", "无法翻译该内容", "不能翻译该内容",
        "please provide the japanese", "please provide specific japanese", "not a japanese text", "not text to translate",
    )
    if any(marker in value for marker in hard_markers):
        return True
    apology_markers = ("抱歉", "对不起", "sorry", "apologize")
    task_markers = ("请提供", "无法", "不能", "不是", "并非", "文本", "内容", "翻译", "provide", "cannot", "can't", "unable")
    if any(marker in value for marker in apology_markers) and any(marker in value for marker in task_markers):
        return True
    sentence_marks = sum(value.count(char) for char in "。！？!?")
    meta_words = ("文本", "内容", "翻译", "提供", "段落", "句子", "文件", "text", "content", "translate", "provide")
    return sentence_marks >= 2 and any(word in value for word in meta_words)


def clean_translated_filename_candidate(candidate: str) -> str:
    if looks_like_model_refusal(candidate):
        return ""
    cleaned = strip_model_explanation_notes(candidate, FILENAME_EXPLANATION_MARKERS)
    if not cleaned or tq.has_japanese_residue(cleaned):
        return ""
    if any(marker in cleaned for marker in FILENAME_EXPLANATION_MARKERS):
        return ""
    return sanitize_filename(cleaned)


def clean_translated_toc_title(candidate: str) -> str:
    if looks_like_model_refusal(candidate):
        return ""
    value = str(candidate or "").strip()
    for marker in ("【前文", "【后文", "[前文", "[后文"):
        index = value.find(marker)
        if index > 0:
            value = value[:index].strip()
    for prefix in ("【待翻译文本】", "【待翻译标题】", "[待翻译文本]", "[待翻译标题]"):
        if value.startswith(prefix):
            value = value[len(prefix):].strip()

    cleaned = strip_model_explanation_notes(value, TOC_EXPLANATION_MARKERS)
    if not cleaned:
        return ""
    if any(marker in value for marker in TOC_EXPLANATION_MARKERS):
        for author in TOC_TRAILING_AUTHOR_NAMES:
            if cleaned.endswith(author) and len(cleaned) > len(author):
                cleaned = cleaned[:-len(author)].strip()
                break
    for prefix in ("译文：", "译文:", "翻译：", "翻译:", "标题：", "标题:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    for suffix in ("等内容", "等说明", "的说明", "的解释"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip(" ，,、")
    for marker in TOC_EXPLANATION_MARKERS:
        index = cleaned.find(marker)
        if index > 0:
            prefix = cleaned[:index].rstrip(" ，,、；;：:-—（(")
            if prefix:
                cleaned = prefix
                break
    return cleaned.strip(" ._+-＋，、")


def source_title_for_filename(stem: str) -> str:
    value = str(stem or "").strip()
    if not value:
        return ""
    for marker in ("+(", "＋("):
        if marker in value:
            value = value.split(marker, 1)[0]
            break
    return value.strip(" ._+-＋")


def unique_epub_path(path) -> Path:
    target = Path(path)
    if not target.exists():
        return target
    for index in range(2, 1000):
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
    return target.with_name(f"{target.stem}_{int(time.time())}{target.suffix}")
