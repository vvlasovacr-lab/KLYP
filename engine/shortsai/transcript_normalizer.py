from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence

from .transcription import Transcript, TranscriptSegment, TranscriptWord


TOKEN_RE = re.compile(r"[^0-9A-Za-zА-Яа-яЁё.,%-]+", re.UNICODE)
TRAILING_RE = re.compile(r"([,.;:!?]+)$")

NUMBER_VALUES: dict[str, float] = {
    "ноль": 0, "нуль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19, "двадцать": 20, "тридцать": 30,
    "сорок": 40, "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100, "двести": 200,
    "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
    "полтора": 1.5, "полторы": 1.5,
}
MAGNITUDES = {
    "тысяча", "тысячи", "тысяч", "миллион", "миллиона", "миллионов",
    "миллиард", "миллиарда", "миллиардов",
}
AMOUNT_UNITS = {
    "рубль", "рубля", "рублей", "доллар", "доллара", "долларов", "евро",
    "процент", "процента", "процентов", "%",
}
BROKEN_MAGNITUDES = {
    "1000": "тысяч", "1 000": "тысяч",
    "1000000": "миллионов", "1 000 000": "миллионов",
    "1000000000": "миллиардов", "1 000 000 000": "миллиардов",
}


def _token(value: str) -> str:
    return TOKEN_RE.sub("", value).lower().replace("ё", "е").rstrip(".,;:!?")


def _punctuation(value: str) -> str:
    match = TRAILING_RE.search(value)
    return match.group(1) if match else ""


def _format(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _join(words: Sequence[TranscriptWord]) -> str:
    return " ".join(word.text for word in words if word.text).strip()


@dataclass(frozen=True)
class NormalizationResult:
    transcript: Transcript
    report: dict[str, Any]


def _normalize_segment(segment: TranscriptSegment) -> tuple[TranscriptSegment, list[dict[str, Any]]]:
    source = list(segment.words)
    if not source:
        return segment, []
    output: list[TranscriptWord] = []
    changes: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(source):
        current_token = _token(source[cursor].text)

        # Defensive repair for artifacts produced by older display formatting:
        # "70 1000 рублей" becomes conversational "70 тысяч рублей".
        previous_token = _token(output[-1].text) if output else ""
        next_token = _token(source[cursor + 1].text) if cursor + 1 < len(source) else ""
        if current_token in BROKEN_MAGNITUDES and previous_token.replace(".", "", 1).isdigit() and next_token in AMOUNT_UNITS:
            replacement = BROKEN_MAGNITUDES[current_token] + _punctuation(source[cursor].text)
            output.append(TranscriptWord(source[cursor].start, source[cursor].end, replacement, source[cursor].probability))
            changes.append({
                "start": round(source[cursor].start, 3), "end": round(source[cursor].end, 3),
                "before": source[cursor].text, "after": replacement,
                "rule": "repair_numeric_magnitude_artifact",
            })
            cursor += 1
            continue

        start = cursor
        value = 0.0
        while cursor < len(source) and _token(source[cursor].text) in NUMBER_VALUES:
            value += NUMBER_VALUES[_token(source[cursor].text)]
            cursor += 1
        if cursor == start:
            output.append(source[cursor])
            cursor += 1
            continue

        context = _token(source[cursor].text) if cursor < len(source) else ""
        # Convert only when the words unambiguously form an amount. Ordinary
        # phrases such as "один человек" stay conversational text.
        if context not in MAGNITUDES and context not in AMOUNT_UNITS:
            output.extend(source[start:cursor])
            continue
        original = " ".join(word.text for word in source[start:cursor])
        replacement = _format(value) + _punctuation(source[cursor - 1].text)
        probability = sum(word.probability for word in source[start:cursor]) / max(1, cursor - start)
        output.append(TranscriptWord(
            source[start].start, source[cursor - 1].end, replacement, probability,
        ))
        changes.append({
            "start": round(source[start].start, 3), "end": round(source[cursor - 1].end, 3),
            "before": original, "after": replacement,
            "context": context, "rule": "conversational_amount",
        })

    normalized = tuple(output)
    return TranscriptSegment(segment.start, segment.end, _join(normalized), normalized), changes


def normalize_transcript(transcript: Transcript) -> NormalizationResult:
    """Normalize display text without changing speech time.

    Magnitude nouns remain words: ``семьдесят тысяч`` -> ``70 тысяч``.
    This is deliberately different from accounting formatting (``70 000``).
    """
    segments: list[TranscriptSegment] = []
    changes: list[dict[str, Any]] = []
    for segment in transcript.segments:
        normalized, segment_changes = _normalize_segment(segment)
        segments.append(normalized)
        changes.extend(segment_changes)
    normalized_transcript = Transcript(
        transcript.language, transcript.language_probability, transcript.duration, tuple(segments),
    )
    return NormalizationResult(normalized_transcript, {
        "version": 1,
        "policy": "conversational_numbers_preserve_magnitude_words",
        "changes": changes,
        "summary": {"changed_phrases": len(changes)},
    })


def chunks_from_normalized(source_chunks: Sequence[dict[str, Any]], transcript: Transcript) -> list[dict[str, Any]]:
    """Rebuild timestamp chunks after safe word merging in normalization."""
    normalized_words = [word for segment in transcript.segments for word in segment.words]
    result: list[dict[str, Any]] = []
    for word in normalized_words:
        sources = [
            item for item in source_chunks
            if float(item["end"]) > word.start - 0.002 and float(item["start"]) < word.end + 0.002
        ]
        result.append({
            "source_word": " ".join(str(item.get("source_word", item.get("word", ""))) for item in sources).strip() or word.text,
            "word": word.text,
            "start": round(word.start, 3), "end": round(word.end, 3),
            "probability": round(word.probability, 4),
        })
    return result
