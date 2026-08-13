from __future__ import annotations

from difflib import SequenceMatcher
import re
from statistics import mean
from typing import Any, Sequence

from .transcription import Transcript


TOKEN_RE = re.compile(r"[^0-9a-zа-яё%]+", re.IGNORECASE)
FILLERS = {"ээ", "эм", "ну", "короче", "вот", "типа"}


def token(value: str) -> str:
    return TOKEN_RE.sub("", value.casefold().replace("ё", "е"))


def words(transcript: Transcript) -> list[dict[str, Any]]:
    return [
        {"text": word.text, "token": token(word.text), "start": word.start, "end": word.end, "probability": word.probability}
        for segment in transcript.segments for word in segment.words if token(word.text)
    ]


def _join(items: Sequence[dict[str, Any]]) -> str:
    return " ".join(str(item["text"]) for item in items).strip()


def _range(items: Sequence[dict[str, Any]]) -> tuple[float, float]:
    return (round(float(items[0]["start"]), 3), round(float(items[-1]["end"]), 3))


def _transformation(raw: Sequence[dict[str, Any]], final: Sequence[dict[str, Any]]) -> str:
    raw_duration = max(0.001, float(raw[-1]["end"]) - float(raw[0]["start"]))
    final_duration = max(0.001, float(final[-1]["end"]) - float(final[0]["start"]))
    ratio = raw_duration / final_duration
    raw_internal_pause = max(0.0, raw_duration - sum(max(0.0, item["end"] - item["start"]) for item in raw))
    final_internal_pause = max(0.0, final_duration - sum(max(0.0, item["end"] - item["start"]) for item in final))
    if ratio >= 1.12:
        return "SPEED_UP" if final_internal_pause >= raw_internal_pause * 0.65 else "PAUSE_COMPRESSION"
    if ratio <= 0.88:
        return "SLOWED_OR_EXTENDED"
    return "RETAINED"


def _semantic_slices(items: Sequence[dict[str, Any]], maximum_words: int = 12) -> list[tuple[int, int]]:
    """Bound long exact matches so downstream visual comparisons stay local."""
    slices: list[tuple[int, int]] = []
    start = 0
    for index, item in enumerate(items, 1):
        length = index - start
        phrase_end = bool(re.search(r"[.!?…,:;]$", str(item.get("text", "")).strip()))
        if length >= maximum_words or (length >= 5 and phrase_end):
            slices.append((start, index))
            start = index
    if start < len(items):
        slices.append((start, len(items)))
    return slices


def align_transcripts(raw_transcript: Transcript, reference_transcript: Transcript) -> dict[str, Any]:
    raw, final = words(raw_transcript), words(reference_transcript)
    matcher = SequenceMatcher(None, [item["token"] for item in raw], [item["token"] for item in final], autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    aligned: list[dict[str, Any]] = []
    raw_cursor = final_cursor = 0
    for block in blocks:
        if block.a > raw_cursor:
            gap = raw[raw_cursor:block.a]
            start, end = _range(gap)
            aligned.append({
                "raw_start": start, "raw_end": end,
                "reference_start": None, "reference_end": None,
                "transcript": _join(gap), "alignment_confidence": 0.0,
                "transformation_type": "FILLER_REMOVED" if all(item["token"] in FILLERS for item in gap) else "REMOVED",
            })
        if block.b > final_cursor:
            gap = final[final_cursor:block.b]
            start, end = _range(gap)
            aligned.append({
                "raw_start": None, "raw_end": None,
                "reference_start": start, "reference_end": end,
                "transcript": _join(gap), "alignment_confidence": 0.0,
                "transformation_type": "UNALIGNED_REFERENCE",
            })
        raw_block, final_block = raw[block.a:block.a + block.size], final[block.b:block.b + block.size]
        for start_index, end_index in _semantic_slices(final_block):
            raw_slice = raw_block[start_index:end_index]
            final_slice = final_block[start_index:end_index]
            raw_start, raw_end = _range(raw_slice)
            final_start, final_end = _range(final_slice)
            probability = mean([item["probability"] for item in raw_slice + final_slice]) if raw_slice else 0.0
            length_confidence = min(1.0, len(raw_slice) / 5.0)
            aligned.append({
                "raw_start": raw_start, "raw_end": raw_end,
                "reference_start": final_start, "reference_end": final_end,
                "transcript": _join(final_slice),
                "alignment_confidence": round(0.58 * length_confidence + 0.42 * max(0.0, min(1.0, probability)), 3),
                "transformation_type": _transformation(raw_slice, final_slice),
                "word_count": len(raw_slice),
            })
        raw_cursor, final_cursor = block.a + block.size, block.b + block.size
    if raw_cursor < len(raw):
        gap = raw[raw_cursor:]
        start, end = _range(gap)
        aligned.append({
            "raw_start": start, "raw_end": end, "reference_start": None, "reference_end": None,
            "transcript": _join(gap), "alignment_confidence": 0.0,
            "transformation_type": "FILLER_REMOVED" if all(item["token"] in FILLERS for item in gap) else "REMOVED",
        })
    if final_cursor < len(final):
        gap = final[final_cursor:]
        start, end = _range(gap)
        aligned.append({
            "raw_start": None, "raw_end": None, "reference_start": start, "reference_end": end,
            "transcript": _join(gap), "alignment_confidence": 0.0,
            "transformation_type": "UNALIGNED_REFERENCE",
        })
    merged: list[dict[str, Any]] = []
    for item in aligned:
        previous = merged[-1] if merged else None
        compatible = previous and item["transformation_type"] == previous["transformation_type"] and item["transformation_type"] in {"RETAINED", "SPEED_UP", "PAUSE_COMPRESSION"}
        bounded = compatible and (
            int(previous.get("word_count", 0)) + int(item.get("word_count", 0)) <= 12
            and float(item["raw_end"]) - float(previous["raw_start"]) <= 5.5
            and float(item["reference_end"]) - float(previous["reference_start"]) <= 5.5
        )
        close = bounded and item["raw_start"] - previous["raw_end"] <= 0.75 and item["reference_start"] - previous["reference_end"] <= 0.75
        if close:
            previous["raw_end"] = item["raw_end"]
            previous["reference_end"] = item["reference_end"]
            previous["transcript"] = f"{previous['transcript']} {item['transcript']}".strip()
            previous["word_count"] = int(previous.get("word_count", 0)) + int(item.get("word_count", 0))
            previous["alignment_confidence"] = round((previous["alignment_confidence"] + item["alignment_confidence"]) / 2, 3)
        else:
            merged.append(dict(item))
    matched_words = sum(int(item.get("word_count", 0)) for item in merged if item.get("raw_start") is not None and item.get("reference_start") is not None)
    weighted = [item["alignment_confidence"] for item in merged if item.get("word_count")]
    return {
        "version": 1,
        "method": "normalized_word_sequence_alignment_v1",
        "segments": merged,
        "summary": {
            "raw_words": len(raw), "reference_words": len(final), "matched_words": matched_words,
            "raw_word_coverage": round(matched_words / max(1, len(raw)), 3),
            "reference_word_coverage": round(matched_words / max(1, len(final)), 3),
            "mean_alignment_confidence": round(mean(weighted), 3) if weighted else 0.0,
            "removed_segments": sum(item["transformation_type"] in {"REMOVED", "FILLER_REMOVED"} for item in merged),
            "ambiguous_segments": sum(item["transformation_type"].startswith("UNALIGNED") for item in merged),
        },
    }


def reference_content_map(transcript: Transcript) -> dict[str, Any]:
    segments = list(transcript.segments)
    units: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        text = segment.text.strip()
        value = token(text)
        lower = text.casefold()
        if index == 0 or segment.start < 3.5:
            function = "HOOK"
        elif any(mark in lower for mark in ("например", "история", "однажды")):
            function = "EXAMPLE"
        elif any(mark in lower for mark in ("потому что", "доказ", "поэтому")):
            function = "EVIDENCE"
        elif any(mark in lower for mark in ("но ", "однако", "вместо", "наоборот")):
            function = "CONTRAST"
        elif re.search(r"\d", text):
            function = "NUMBER"
        elif index == len(segments) - 1 and any(mark in lower for mark in ("подпис", "пиши", "смотри", "ссылка")):
            function = "CTA"
        elif index == len(segments) - 1:
            function = "CONCLUSION"
        else:
            function = "POINT"
        units.append({
            "id": f"reference-unit-{index + 1:02d}", "start": round(segment.start, 3), "end": round(segment.end, 3),
            "function": function, "text": text, "word_count": len([word for word in segment.words if token(word.text)]),
        })
    return {"version": 1, "units": units, "summary": {"units": len(units), "functions": [item["function"] for item in units]}}
