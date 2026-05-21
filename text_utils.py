def is_translatable(text: str) -> bool:
    """Return whether a text fragment should be sent to translation."""
    text = text.replace("\ufffc", "").strip()
    if not text:
        return False
    has_japanese_kana = any("\u3040" <= c <= "\u30ff" for c in text)
    has_cjk = any("\u4e00" <= c <= "\u9fff" for c in text)
    has_latin = any(("a" <= c.lower() <= "z") for c in text)
    has_digit = any(c.isdigit() for c in text)
    if has_japanese_kana:
        return True
    if has_cjk and not has_latin:
        return True
    if has_cjk and has_digit and not has_latin:
        return True
    return False
