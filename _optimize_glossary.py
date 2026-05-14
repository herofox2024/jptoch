#!/usr/bin/env python3
"""Optimize glossary.json: clean format, merge duplicates, remove honorific variants, categorize."""

import json
import re
import shutil
from pathlib import Path

GLOSSARY_PATH = Path.home() / ".epub_translator" / "glossary.json"
BACKUP_PATH = Path.home() / ".epub_translator" / "glossary.backup.before_optimize.json"

with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
    raw = json.load(f)

# Backup
shutil.copy2(GLOSSARY_PATH, BACKUP_PATH)
print(f"Backup: {BACKUP_PATH}")

# Step 1: Parse entries - extract translation and info
entries = {}
for k, v in raw.items():
    if isinstance(v, dict):
        translation = str(v.get("dst", "")).strip()
        info = str(v.get("info", "")).strip()
    else:
        val = str(v).strip()
        match = re.match(r'^(.+?)\s*((?:\s#[^\s#]+)*)$', val)
        if match:
            translation = match.group(1).strip()
            notes_str = match.group(2).strip()
            info = notes_str.replace(' #', '; ').replace('#', '').strip()
        else:
            translation = val
            info = ""
    entries[k] = {"translation": translation, "info": info}

print(f"Original: {len(entries)} entries")

# Step 2: Merge duplicates (only clear duplicates - typos, spacing variants)
merge_map = {
    "スペース・ドウェルグ": ["スペース・ドヴェルグ", "スペースドウェルグ"],
    "ステラオンライン": ["すてらおんらいん", "テスラオンライン"],
    "マザー・クリスタル": ["マザークリスタル"],
    "グラヴィティ・ジャマー": ["グラヴィティジャマー"],
    "ホロディスプレイ": ["ホロ・ディスプレイ", "ホログラムディスプレイ"],
    "メインジェネレーター": ["メインジェネレータ"],
    "フレンドリーファイア": ["フレンドリーファイヤー"],
    "ボムディフェンス・ニンジャ装束": ["ボムディフェンスニンジャ装束"],
    "ポンコツ": ["ぽんこつ"],
    "ジェ◯イ": ["ジェ○イ"],
    "シスコン": ["マイコ"],  # same meaning: 妹控
    "ドワーフ": ["ドウェルグ"],  # same meaning: 矮人
    "ゲロビーム": ["ゲロビ"],  # abbreviation
    "クリスタル": ["レアクリス"],  # variant
    "シールドジェネレーター": ["シールドセル"],  # sub-component
    "カーボンフスマ": ["カーボン・フスマ"],  # spacing
    "メイドロボ": ["メイドロイド"],  # same thing
}

# Remove 错字 entries
for k, v in list(entries.items()):
    if "错字" in v.get("info", ""):
        del entries[k]
        print(f"  Removed (错字): {k}")

# Apply merges
merged = 0
for canonical, variants in merge_map.items():
    for v in variants:
        if v in entries:
            del entries[v]
            merged += 1

print(f"Merged: {merged} duplicates")

# Step 3: Remove honorific variants
base_names = [
    "エルマ", "ミミ", "ヒロ", "セレナ", "クリスティーナ", "クリス",
    "フォルト", "エルフィン", "コーネル", "ワムド", "エルドムア",
    "ティーナ", "ウィスカ", "クギ", "メイ", "サラ", "ミロ",
    "ミルファ", "イゾルデ", "ティニア", "デルシュ", "ヒィシ",
    "リリウム", "フリードリヒ", "ウェルズ", "ラウレンツ", "オータム",
    "フウシン", "ブーボ", "アメノ", "アイリア", "アンネリーゼ",
    "ベアトリクス", "ヒルデガルド", "ネクト", "クライアス",
    "セレス", "セレスティア", "ヒルデ", "ナハタ", "モリタ",
    "フジキド", "ダークニンジャ",
]

honorific_suffixes = [
    "さん", "様", "君", "くん", "嬢", "ちゃん", "ちゃーん", "氏", "卿", "殿",
]

honorific_removed = 0
for k in list(entries.keys()):
    for base in base_names:
        for suffix in honorific_suffixes:
            if k == base + suffix and base in entries:
                del entries[k]
                honorific_removed += 1
                break

# Also remove redundant title combos where base already has the info
redundant = [
    "グラッカン帝国",   # グラッカン already has 帝国 info
    "ベレベレム連邦軍",  # ベレベレム連邦 exists
    "港湾管理局員",      # 港湾管理局 exists
    "ショーコ先生",      # ショーコ exists
]
for combo in redundant:
    if combo in entries:
        del entries[combo]
        honorific_removed += 1

# Remove pure punctuation entries (no translation value)
for k in list(entries.keys()):
    if k in {'「', '」', '『', '』', 'Ⅰ', 'Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ'}:
        del entries[k]
        honorific_removed += 1

# Remove chapter markers (no translation value)
for k in list(entries.keys()):
    if re.match(r'^[一二三四五六七八九十]+章$', k):
        del entries[k]
        honorific_removed += 1

print(f"Removed: {honorific_removed} honorific/redundant entries")

# Step 4: Categorize
categories = {"Person": [], "Location": [], "Org": [], "Item": [], "Skill": [], "Creature": []}

# Category hints from info field
INFO_PERSON = {"皇女", "皇太子妃", "伯爵", "侯爵", "子爵", "男爵", "准男爵",
               "女性", "母亲", "父亲", "叔父", "祖母", "姐姐"}
INFO_LOCATION = {"星系", "行星", "殖民卫星", "度假行星"}
INFO_ORG = {"氏族", "連邦", "帝国", "管理局", "軍", "帮派"}

KEY_LOCATION = {"星系", "行星", "殖民卫星", "都市", "街", "区", "村", "店", "施設", "館", "院", "ドック", "船坞"}
KEY_ORG = {"クラン", "シンジケート", "社", "公司", "工業", "科技", "管理局", "軍"}
KEY_ITEM = {"艦", "舰", "銃", "枪", "炮", "装甲", "导弹", "パック", "ポッド"}
KEY_SKILL = {"ジツ", "の術", "カラテ", "空手", "柔术", "居合", "道場", "ドージョー"}
KEY_CREATURE = {"ニンジャ", "エルフ", "ボット", "ロボット", "アンドロイド"}

def detect_category(key, translation, info):
    all_text = f"{key} {translation} {info}"
    for hint in INFO_PERSON:
        if hint in info:
            return "Person"
    for hint in INFO_LOCATION:
        if hint in info:
            return "Location"
    for hint in INFO_ORG:
        if hint in info:
            return "Org"
    for hint in KEY_LOCATION:
        if hint in all_text:
            return "Location"
    for hint in KEY_ORG:
        if hint in all_text:
            return "Org"
    for hint in KEY_SKILL:
        if hint in all_text:
            return "Skill"
    for hint in KEY_CREATURE:
        if hint in all_text:
            return "Creature"
    for hint in KEY_ITEM:
        if hint in all_text:
            return "Item"
    # Short katakana-only = likely a name
    if re.match(r'^[ァ-ヶー・]{2,8}$', key):
        return "Person"
    return "Item"

# Category hints to drop from info (they're now redundant with category)
CATEGORY_HINTS = {"舰", "星系", "氏族", "連邦", "帝国", "男", "女性", "男性", "错字"}

for k, v in entries.items():
    cat = detect_category(k, v["translation"], v["info"])
    # Clean info: remove category hints that are now redundant
    info_parts = [p.strip() for p in v["info"].split(";") if p.strip()]
    cleaned_info = []
    for part in info_parts:
        if part not in CATEGORY_HINTS:
            cleaned_info.append(part)
    info_str = "; ".join(cleaned_info) if cleaned_info else ""

    entry = {"original": k, "translation": v["translation"]}
    if info_str:
        entry["info"] = info_str
    categories[cat].append(entry)

# Sort each category
for cat in categories:
    categories[cat].sort(key=lambda x: x["original"])

# Write
with open(GLOSSARY_PATH, "w", encoding="utf-8") as f:
    json.dump(categories, f, ensure_ascii=False, indent=2)

total = sum(len(v) for v in categories.values())
print(f"\nOptimized: {total} entries (was {len(raw)})")
for cat, items in categories.items():
    if items:
        print(f"  [{cat}] {len(items)}")
