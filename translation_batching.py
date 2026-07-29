"""Pure text splitting and batch grouping algorithms."""

from __future__ import annotations

import logging
import re
from typing import Dict, List


logger = logging.getLogger(__name__)


def smart_split_text(text: str, chunk_size: int) -> List[str]:
    """Split by paragraphs and sentence endings before falling back to characters."""

    value = text.strip()
    if not value:
        return []
    if len(value) <= chunk_size:
        return [value]

    paragraphs = [paragraph for paragraph in value.split("\n") if paragraph]
    chunks: List[str] = []
    current = ""

    def flush_current() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for paragraph in paragraphs:
        if len(paragraph) > chunk_size:
            sentences = re.split(r"(?<=[。！？!?…])", paragraph)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(sentence) > chunk_size:
                    flush_current()
                    for index in range(0, len(sentence), chunk_size):
                        chunks.append(sentence[index:index + chunk_size])
                    continue
                if not current:
                    current = sentence
                elif len(current) + 1 + len(sentence) <= chunk_size:
                    current += "\n" + sentence
                else:
                    flush_current()
                    current = sentence
            continue

        if not current:
            current = paragraph
        elif len(current) + 1 + len(paragraph) <= chunk_size:
            current += "\n" + paragraph
        else:
            flush_current()
            current = paragraph

    flush_current()
    return chunks


def smart_batch_texts(
    texts: List[str],
    effective_batch_size: int,
    *,
    short_threshold: int,
    long_threshold: int,
    max_batch_length: int,
) -> List[List[str]]:
    """Group source texts by length while respecting item and character limits."""

    short: List[str] = []
    medium: List[str] = []
    long: List[str] = []
    for text in texts:
        if len(text) <= short_threshold:
            short.append(text)
        elif len(text) <= long_threshold:
            medium.append(text)
        else:
            long.append(text)

    batches: List[List[str]] = []

    def flush_group(values: List[str], max_items: int, max_chars: int) -> None:
        current: List[str] = []
        current_length = 0
        for value in values:
            value_length = len(value)
            if current and (len(current) >= max_items or current_length + value_length >= max_chars):
                batches.append(current)
                current = []
                current_length = 0
            current.append(value)
            current_length += value_length
        if current:
            batches.append(current)

    flush_group(short, min(effective_batch_size * 2, 20), max_batch_length * 2)
    flush_group(medium, effective_batch_size, max_batch_length)
    batches.extend([[text] for text in long])
    _log_batch_stats(batches, short, medium, long, len, short_threshold, long_threshold)
    return batches


def smart_batch_task_keys(
    task_keys: List[str],
    task_texts: Dict[str, str],
    effective_batch_size: int,
    *,
    short_threshold: int,
    long_threshold: int,
    max_batch_length: int,
    fast_mode: bool,
    fast_max_items: int,
    fast_max_chars: int,
    provider: str,
) -> List[List[str]]:
    """Group internal task keys using their source text lengths."""

    short: List[str] = []
    medium: List[str] = []
    long: List[str] = []
    for key in task_keys:
        text_length = len(task_texts.get(key, ""))
        if text_length <= short_threshold:
            short.append(key)
        elif text_length <= long_threshold:
            medium.append(key)
        else:
            long.append(key)

    batches: List[List[str]] = []

    def flush_group(keys: List[str], max_items: int, max_chars: int) -> None:
        current: List[str] = []
        current_length = 0
        for key in keys:
            text_length = len(task_texts.get(key, ""))
            if current and (len(current) >= max_items or current_length + text_length >= max_chars):
                batches.append(current)
                current = []
                current_length = 0
            current.append(key)
            current_length += text_length
        if current:
            batches.append(current)

    if fast_mode:
        max_items = min(max(effective_batch_size, 1), fast_max_items)
        max_chars = max(max_batch_length, fast_max_chars)
        short_max_items = max_items if provider == "longcat" else min(max_items * 2, 32)
        flush_group(short, short_max_items, max_chars * 2)
        flush_group(medium, max_items, max_chars)
    else:
        flush_group(short, min(effective_batch_size * 2, 20), max_batch_length * 2)
        flush_group(medium, effective_batch_size, max_batch_length)
    batches.extend([[key] for key in long])

    def key_length(key: str) -> int:
        return len(task_texts.get(key, ""))

    _log_batch_stats(
        batches,
        short,
        medium,
        long,
        key_length,
        short_threshold,
        long_threshold,
        fast_mode=fast_mode,
    )
    return batches


def _log_batch_stats(
    batches,
    short,
    medium,
    long,
    length_fn,
    short_threshold: int,
    long_threshold: int,
    *,
    fast_mode: bool = False,
) -> None:
    short_count = len([batch for batch in batches if batch and length_fn(batch[0]) <= short_threshold])
    medium_count = len(
        [batch for batch in batches if batch and short_threshold < length_fn(batch[0]) <= long_threshold]
    )
    long_count = len([batch for batch in batches if batch and length_fn(batch[0]) > long_threshold])
    logger.info(
        "智能分批: 短文本 %s→%s批, 中文本 %s→%s批, 长文本 %s→%s批%s",
        len(short),
        short_count,
        len(medium),
        medium_count,
        len(long),
        long_count,
        "，大书快速模式已启用" if fast_mode else "",
    )
