from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List


GENRE_GENERAL = "general"
GENRE_MYSTERY = "mystery"
GENRE_SCIFI = "scifi"
GENRE_FANTASY = "fantasy"

TONE_NEUTRAL = "neutral"
TONE_LIGHT = "light"
TONE_LITERARY = "literary"

GENRE_LABELS = {
    GENRE_GENERAL: "通用小说",
    GENRE_MYSTERY: "推理小说",
    GENRE_SCIFI: "科幻小说",
    GENRE_FANTASY: "奇幻小说",
}

TONE_LABELS = {
    TONE_NEUTRAL: "中性口吻",
    TONE_LIGHT: "轻小说口吻",
    TONE_LITERARY: "文学化口吻",
}


@dataclass(frozen=True)
class StyleDetectionResult:
    genre: str = GENRE_GENERAL
    tone: str = TONE_NEUTRAL
    confidence: int = 0
    reason: str = "未检测到明确类型特征，使用通用小说 + 中性口吻"

    @property
    def genre_label(self) -> str:
        return GENRE_LABELS.get(self.genre, GENRE_LABELS[GENRE_GENERAL])

    @property
    def tone_label(self) -> str:
        return TONE_LABELS.get(self.tone, TONE_LABELS[TONE_NEUTRAL])

    @property
    def display_text(self) -> str:
        return f"{self.genre_label} + {self.tone_label}"

    def to_dict(self) -> dict:
        return {
            "genre": self.genre,
            "tone": self.tone,
            "confidence": self.confidence,
            "reason": self.reason,
            "genre_label": self.genre_label,
            "tone_label": self.tone_label,
            "display_text": self.display_text,
        }


GENRE_KEYWORDS = {
    GENRE_MYSTERY: {
        "探偵": 5, "侦探": 5, "推理": 5, "事件": 4, "謎": 4, "谜": 4,
        "殺人": 5, "杀人": 5, "密室": 5, "アリバイ": 4, "不在場証明": 4,
        "刑事": 3, "警部": 3, "警察": 2, "犯人": 4, "容疑者": 4,
        "证词": 3, "証言": 3, "凶器": 4, "死体": 4, "尸体": 4,
    },
    GENRE_SCIFI: {
        "宇宙": 5, "AI": 4, "人工知能": 4, "机器人": 4, "ロボット": 4,
        "量子": 5, "未来": 3, "実験": 3, "实验": 3, "研究所": 3,
        "星舰": 4, "宇宙船": 4, "タイムマシン": 5, "时间机器": 5,
        "サイボーグ": 4, "電脳": 4, "仮想現実": 4, "虚拟现实": 4,
    },
    GENRE_FANTASY: {
        "魔法": 5, "勇者": 5, "魔王": 5, "スキル": 4, "技能": 3,
        "ダンジョン": 4, "迷宫": 4, "王国": 3, "王女": 3, "騎士": 3,
        "骑士": 3, "冒険者": 4, "冒险者": 4, "ギルド": 4, "公会": 4,
        "異世界": 5, "异世界": 5, "精霊": 3, "精灵": 3, "ドラゴン": 4,
    },
}

LIGHT_TONE_KEYWORDS = {
    "ライトノベル": 5, "ラノベ": 5, "学園": 3, "学院": 2, "高校": 2,
    "先輩": 2, "後輩": 2, "幼馴染": 3, "妹": 2, "部活": 2,
    "えっ": 1, "うわ": 1, "なんで": 1, "じゃない": 1, "だよ": 1,
    "だろ": 1, "かな": 1, "って": 1,
}

LITERARY_TONE_KEYWORDS = {
    "純文学": 5, "文学": 3, "随筆": 3, "詩": 2, "孤独": 2,
    "記憶": 2, "回想": 2, "余韻": 2, "静謐": 3,
}


def _join_context(title: str, toc_titles: Iterable[str], samples: Iterable[str], max_chars: int = 12000) -> str:
    parts: List[str] = []
    if title:
        parts.append(str(title))
    parts.extend(str(item) for item in toc_titles if str(item).strip())
    for sample in samples:
        if sample and str(sample).strip():
            parts.append(str(sample))
        if sum(len(part) for part in parts) >= max_chars:
            break
    return "\n".join(parts)[:max_chars]


def _score_keywords(text: str, keywords: dict) -> tuple[int, list[str]]:
    score = 0
    hits = []
    for keyword, weight in keywords.items():
        count = len(re.findall(re.escape(keyword), text, flags=re.IGNORECASE))
        if count:
            score += min(count, 4) * int(weight)
            hits.append(keyword)
    return score, hits[:8]


def _dialogue_score(text: str) -> int:
    quotes = text.count("「") + text.count("」") + text.count("『") + text.count("』")
    excited = text.count("！") + text.count("!?") + text.count("？！")
    compact_len = max(1, len(re.sub(r"\s+", "", text)))
    quote_density = min(20, int(quotes * 1800 / compact_len))
    return quote_density + min(excited, 10)


def detect_novel_style(
    title: str = "",
    toc_titles: Iterable[str] | None = None,
    samples: Iterable[str] | None = None,
    min_confidence: int = 60,
) -> StyleDetectionResult:
    """Detect novel proofread style from title, TOC and a small text sample."""
    text = _join_context(title, toc_titles or [], samples or [])
    if not text.strip():
        return StyleDetectionResult()

    genre_scores = {}
    genre_hits = {}
    for genre, keywords in GENRE_KEYWORDS.items():
        score, hits = _score_keywords(text, keywords)
        genre_scores[genre] = score
        genre_hits[genre] = hits

    best_genre = max(genre_scores, key=genre_scores.get)
    best_genre_score = genre_scores.get(best_genre, 0)
    sorted_scores = sorted(genre_scores.values(), reverse=True)
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0
    genre_confidence = min(100, best_genre_score * 8 + max(0, best_genre_score - second_score) * 4)
    if best_genre_score <= 0 or genre_confidence < min_confidence:
        best_genre = GENRE_GENERAL
        genre_confidence = 40 if best_genre_score > 0 else 0

    light_score, light_hits = _score_keywords(text, LIGHT_TONE_KEYWORDS)
    literary_score, literary_hits = _score_keywords(text, LITERARY_TONE_KEYWORDS)
    light_score += _dialogue_score(text)

    if light_score >= max(8, literary_score + 3):
        tone = TONE_LIGHT
        tone_confidence = min(100, light_score * 6)
        tone_hits = light_hits[:6] or ["对白密度较高"]
    elif literary_score >= 10:
        tone = TONE_LITERARY
        tone_confidence = min(100, literary_score * 7)
        tone_hits = literary_hits[:6]
    else:
        tone = TONE_NEUTRAL
        tone_confidence = 50
        tone_hits = []

    confidence = int(round((genre_confidence * 0.65) + (tone_confidence * 0.35)))
    if best_genre == GENRE_GENERAL and tone == TONE_NEUTRAL:
        confidence = min(confidence, 50)

    reason_parts = []
    if best_genre != GENRE_GENERAL:
        reason_parts.append(f"类型关键词: {'、'.join(genre_hits.get(best_genre) or [])}")
    else:
        reason_parts.append("类型特征不明确，回退通用小说")

    if tone != TONE_NEUTRAL:
        reason_parts.append(f"口吻依据: {'、'.join(tone_hits)}")
    else:
        reason_parts.append("口吻特征不明确，回退中性口吻")

    return StyleDetectionResult(
        genre=best_genre,
        tone=tone,
        confidence=max(0, min(100, confidence)),
        reason="；".join(reason_parts),
    )


def resolve_style_selection(
    selected_genre: str,
    selected_tone: str,
    detected: StyleDetectionResult,
) -> StyleDetectionResult:
    """Apply manual overrides to the auto-detected result."""
    genre = detected.genre if selected_genre == "auto" else (selected_genre or GENRE_GENERAL)
    tone = detected.tone if selected_tone == "auto" else (selected_tone or TONE_NEUTRAL)
    if genre not in GENRE_LABELS:
        genre = GENRE_GENERAL
    if tone not in TONE_LABELS:
        tone = TONE_NEUTRAL

    manual_bits = []
    if selected_genre != "auto":
        manual_bits.append(f"作品类型手动选择为 {GENRE_LABELS[genre]}")
    if selected_tone != "auto":
        manual_bits.append(f"叙事口吻手动选择为 {TONE_LABELS[tone]}")

    reason = detected.reason
    if manual_bits:
        reason = "；".join(manual_bits + [f"自动识别参考: {detected.reason}"])

    return StyleDetectionResult(
        genre=genre,
        tone=tone,
        confidence=100 if manual_bits else detected.confidence,
        reason=reason,
    )
