from __future__ import annotations

import re
from typing import Any, Sequence


VALUES = {
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30,
    "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200,
    "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900, "полтора": 1.5, "полторы": 1.5,
}
SCALES = {
    "тысяча": 1_000, "тысячи": 1_000, "тысяч": 1_000,
    "миллион": 1_000_000, "миллиона": 1_000_000, "миллионов": 1_000_000,
    "миллиард": 1_000_000_000, "миллиарда": 1_000_000_000, "миллиардов": 1_000_000_000,
}
AMOUNT_CONTEXT = {
    "рубль", "рубля", "рублей", "доллар", "доллара", "долларов", "евро",
    "процент", "процента", "процентов", "ноль", "нуля", "нулей",
}
ROLE_WEIGHT = {"ordinary": 0, "emphasis": 1, "strong_emphasis": 2, "punch_word": 3}


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё-]", "", value).lower()


def _punctuation(value: str) -> str:
    match = re.search(r"([,.;:!?]+)$", value)
    return match.group(1) if match else ""


def _formatted(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def format_numeric_words(
    words: Sequence[dict[str, Any]],
    emphasis_indices: Sequence[int],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Collapse spoken monetary/magnitude numbers into readable display tokens."""
    result: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(words):
        start = cursor
        current = 0.0
        while cursor < len(words):
            token = _normalize(str(words[cursor].get("word", "")))
            if token in VALUES:
                current += VALUES[token]
                cursor += 1
                continue
            break
        if cursor == start:
            item = dict(words[cursor])
            item["_source_indices"] = [cursor]
            result.append(item)
            cursor += 1
            continue
        context = _normalize(str(words[cursor].get("word", ""))) if cursor < len(words) else ""
        # Keep magnitude nouns as words. This prevents an already-normalized
        # ``70 тысяч`` from becoming the broken ``70 1000`` and preserves the
        # conversational subtitle style requested for Shorts.
        if context not in AMOUNT_CONTEXT and context not in SCALES:
            for source_index in range(start, cursor):
                item = dict(words[source_index])
                item["_source_indices"] = [source_index]
                result.append(item)
            continue
        source_items = list(words[start:cursor])
        strongest = max(source_items, key=lambda item: ROLE_WEIGHT.get(str(item.get("role", "ordinary")), 0))
        merged = dict(source_items[0])
        merged.update({key: strongest[key] for key in ("role", "effect", "scale", "intensity", "duration", "color") if key in strongest})
        merged["word"] = _formatted(current) + _punctuation(str(source_items[-1].get("word", "")))
        merged["start"] = source_items[0]["start"]
        merged["end"] = source_items[-1]["end"]
        merged["category"] = "number"
        merged["_source_indices"] = list(range(start, cursor))
        result.append(merged)

    mapped_emphasis = [
        index for index, item in enumerate(result)
        if any(source_index in emphasis_indices for source_index in item.pop("_source_indices", []))
    ]
    return result, mapped_emphasis
