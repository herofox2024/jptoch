# -*- coding: utf-8 -*-
"""Local quality heuristics for translated text."""

import re


def is_suspicious_translation_pair(src: str, dst: str) -> bool:
    source = (src or "").strip()
    translated = (dst or "").strip()
    if not translated:
        return True
    if len(source) >= 20 and len(translated) <= 1:
        return True
    if len(translated) >= 8:
        most_common = max(translated.count(ch) for ch in set(translated))
        if most_common / max(1, len(translated)) >= 0.65:
            return True
    if re.search(r"(.{2,10})\1{3,}", translated):
        return True
    return False
