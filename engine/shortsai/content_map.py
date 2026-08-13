from __future__ import annotations

from difflib import SequenceMatcher
import math
import re
from typing import Any, Sequence

from .transcription import Transcript, TranscriptWord


WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё%]+", re.UNICODE)
STOP = frozenset(
    "и а но или в во на с со к у от до из за по для о об про это этот эта эти что как я ты он она мы вы они "
    "не ни то так же уже еще только вот потому если когда где который которая которые быть был была были есть".split()
)
CONCEPT_STEMS: dict[str, tuple[str, ...]] = {
    "MONEY": ("деньг", "доход", "заработ", "рубл", "доллар", "миллион", "тысяч"),
    "SALES": ("продаж", "продав", "клиент", "сделк", "оффер"),
    "DISCIPLINE": ("дисцип", "привыч", "регуляр", "кажд", "ежеднев"),
    "PROBLEM": ("проблем", "ошиб", "потер", "провал", "мешает", "никогда"),
    "RESULT": ("результ", "получ", "достиг", "стан", "смож", "выгод"),
    "ACTION": ("начн", "сдел", "попроб", "возьм", "науч", "перестан"),
    "EXPERTISE": ("навык", "опыт", "знан", "умени", "понима"),
}
EXAMPLE_MARKERS = ("например", "история", "клиент", "случай", "однажды", "представьте")
CONCLUSION_MARKERS = ("итого", "в итоге", "поэтому", "вывод", "главное", "таким образом")
CTA_STEMS = ("подпиш", "напиш", "сохран", "начн", "сдел", "переход", "смотри")
CONTRAST_MARKERS = ("но", "зато", "вместо", "наоборот", "однако")
CAUSE_MARKERS = ("потому", "поэтому", "без", "чтобы", "значит")


def _tokens(text: str, *, content: bool = False) -> list[str]:
    values = [item.lower().replace("ё", "е") for item in WORD_RE.findall(text)]
    return [item for item in values if not content or (item not in STOP and len(item) > 2)]


def _stem(token: str) -> str:
    for suffix in ("иями", "ами", "ями", "ого", "ему", "ому", "ение", "ений", "ать", "ять", "ить", "ться", "ешь", "ете", "ов", "ев", "ам", "ям", "ах", "ях", "ый", "ий", "ая", "ое", "ые", "ого", "ему", "ами", "ами", "у", "а", "ы", "и"):
        if len(token) >= len(suffix) + 4 and token.endswith(suffix):
            return token[:-len(suffix)]
    return token[:7]


def _concepts(tokens: Sequence[str]) -> set[str]:
    return {
        name for name, stems in CONCEPT_STEMS.items()
        if any(any(token.startswith(stem) for stem in stems) for token in tokens)
    }


def _role(text: str, index: int, count: int) -> str:
    normalized = " ".join(_tokens(text))
    tokens = _tokens(text)
    if index == 0 and (text.rstrip().endswith("?") or any(char.isdigit() for char in text) or (tokens and tokens[0] in {"почему", "как", "зачем", "сколько"})):
        return "HOOK"
    if index >= count - 2 and any(any(token.startswith(stem) for stem in CTA_STEMS) for token in tokens):
        return "CTA"
    if any(marker in normalized for marker in EXAMPLE_MARKERS):
        return "EXAMPLE"
    conclusion_markers = tuple(marker for marker in CONCLUSION_MARKERS if marker != "главное")
    if any(marker in normalized for marker in conclusion_markers) or (index == count - 1 and len(tokens) >= 4):
        return "CONCLUSION"
    if any(marker in tokens for marker in CONTRAST_MARKERS):
        return "CONTRAST"
    if any(char.isdigit() for char in text) or any(marker in tokens for marker in CAUSE_MARKERS):
        return "EVIDENCE"
    return "POINT"


def _words_in_ranges(transcript: Transcript, ranges: Sequence[dict[str, Any]]) -> list[TranscriptWord]:
    return [
        word for segment in transcript.segments for word in segment.words
        if any(float(item["source_start"]) <= (word.start + word.end) / 2 <= float(item["source_end"]) for item in ranges)
    ]


def _phrase_units(transcript: Transcript, ranges: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    words = _words_in_ranges(transcript, ranges)
    groups: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in words:
        if current and word.start - current[-1].end >= 0.72:
            groups.append(current); current = []
        current.append(word)
        if word.text.rstrip().endswith((".", "!", "?", ";")) or len(current) >= 20:
            groups.append(current); current = []
    if current:
        groups.append(current)
    units: list[dict[str, Any]] = []
    for index, group in enumerate(groups):
        text = " ".join(word.text for word in group).strip()
        content = _tokens(text, content=True)
        stems = {_stem(token) for token in content}
        probabilities = [float(word.probability) for word in group]
        units.append({
            "id": f"content-{index + 1:03d}", "start": round(group[0].start, 3),
            "end": round(group[-1].end, 3), "text": text,
            "narrative_function": _role(text, index, len(groups)),
            "concepts": sorted(_concepts(content)), "semantic_terms": sorted(stems),
            "delivery_quality": round(sum(probabilities) / max(1, len(probabilities)), 3),
        })
    return units


def _overlap(left: set[str], right: set[str]) -> float:
    return len(left & right) / max(1, min(len(left), len(right)))


def _semantic_similarity(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, dict[str, float]]:
    left_terms, right_terms = set(left["semantic_terms"]), set(right["semantic_terms"])
    left_concepts, right_concepts = set(left["concepts"]), set(right["concepts"])
    term_overlap = _overlap(left_terms, right_terms)
    concept_overlap = _overlap(left_concepts, right_concepts) if left_concepts and right_concepts else 0.0
    sequence = SequenceMatcher(None, " ".join(_tokens(left["text"], content=True)), " ".join(_tokens(right["text"], content=True))).ratio()
    same_function = float(
        left["narrative_function"] == right["narrative_function"]
        or {left["narrative_function"], right["narrative_function"]} <= {"POINT", "EVIDENCE"}
    )
    causal_left = any(marker in _tokens(left["text"]) for marker in CAUSE_MARKERS)
    causal_right = any(marker in _tokens(right["text"]) for marker in CAUSE_MARKERS)
    relation = float(causal_left == causal_right)
    score = term_overlap * 0.43 + concept_overlap * 0.22 + sequence * 0.16 + same_function * 0.14 + relation * 0.05
    if len(left_concepts & right_concepts) >= 2 and same_function and term_overlap >= 0.30:
        score = max(score, 0.82 + min(0.10, (term_overlap - 0.30) * 0.25))
    # A single broad category (for example MONEY) must never be sufficient.
    if len(left_terms & right_terms) < 2 and term_overlap < 0.72:
        score = min(score, 0.66)
    return round(min(1.0, score), 3), {
        "term_overlap": round(term_overlap, 3), "concept_overlap": round(concept_overlap, 3),
        "sequence_similarity": round(sequence, 3), "same_narrative_function": round(same_function, 3),
    }


def _remove_span(
    ranges: Sequence[dict[str, Any]], start: float, end: float, minimum_keep: float,
) -> list[dict[str, float]] | None:
    result: list[dict[str, float]] = []
    changed = False
    for item in ranges:
        left, right = float(item["source_start"]), float(item["source_end"])
        if end <= left or start >= right:
            result.append({"source_start": round(left, 3), "source_end": round(right, 3)})
            continue
        changed = True
        before, after = start - left, right - end
        if 0.02 < before < minimum_keep or 0.02 < after < minimum_keep:
            return None
        if before >= minimum_keep:
            result.append({"source_start": round(left, 3), "source_end": round(start, 3)})
        if after >= minimum_keep:
            result.append({"source_start": round(end, 3), "source_end": round(right, 3)})
    return result if changed and result else None


def build_content_map(
    transcript: Transcript, selected_ranges: Sequence[dict[str, Any]], *,
    duplicate_threshold: float = 0.80, review_threshold: float = 0.68,
    minimum_keep: float = 0.85,
) -> dict[str, Any]:
    """Build an episode-wide story map and remove only high-confidence repeats."""
    units = _phrase_units(transcript, selected_ranges)
    ranges = [dict(item) for item in selected_ranges]
    kept: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for unit in units:
        best: tuple[dict[str, Any], float, dict[str, float]] | None = None
        for previous in kept:
            score, evidence = _semantic_similarity(previous, unit)
            if best is None or score > best[1]:
                best = previous, score, evidence
        decision, reason = "KEEP", "adds a new narrative function or argument"
        duplicate_of = None
        if best and best[1] >= duplicate_threshold:
            previous, score, evidence = best
            duplicate_of = previous["id"]
            better_take = float(unit["delivery_quality"]) >= float(previous["delivery_quality"]) + 0.06
            target = previous if better_take else unit
            updated = _remove_span(ranges, float(target["start"]), float(target["end"]), minimum_keep)
            if updated is not None:
                ranges = updated
                if better_take:
                    previous["decision"] = "REPLACE_TAKE"
                    previous["replacement_take"] = unit["id"]
                    previous["duplicate_score"] = score
                    decision, reason = "KEEP", "stronger delivery replaces an earlier equivalent argument"
                    kept.remove(previous); kept.append(unit)
                    actions.append({
                        "type": "REPLACE_TAKE", "target": previous["id"], "replacement": unit["id"],
                        "source_coordinates": {"start": previous["start"], "end": previous["end"]},
                        "semantic_similarity": score, "evidence": evidence,
                    })
                else:
                    decision, reason = "TRIM", "repeats the same argument and narrative function"
                    actions.append({
                        "type": "TRIM", "target": unit["id"], "duplicate_of": previous["id"],
                        "source_coordinates": {"start": unit["start"], "end": unit["end"]},
                        "semantic_similarity": score, "evidence": evidence,
                    })
            else:
                decision, reason = "REVIEW_REQUIRED", "semantic duplicate found but no speech-safe full-phrase cut exists"
                warnings.append("semantic_duplicate_review_required")
        elif best and best[1] >= review_threshold:
            decision, reason = "REVIEW_REQUIRED", "probable paraphrase requires episode-level editorial review"
            duplicate_of = best[0]["id"]
            warnings.append("semantic_duplicate_review_required")
        duplicate_score = best[1] if best else 0.0
        unit.update({
            "decision": decision, "reason": reason, "duplicate_of": duplicate_of,
            "duplicate_score": duplicate_score,
            "novelty_score": round(max(0.0, 1.0 - duplicate_score), 3),
        })
        if decision == "KEEP" and unit not in kept:
            kept.append(unit)

    functions = [unit["narrative_function"] for unit in units if unit.get("decision") in {"KEEP", "REPLACE_TAKE"}]
    has_opening = bool(functions and functions[0] in {"HOOK", "POINT", "EVIDENCE", "CONTRAST"})
    has_close = bool(set(functions) & {"CONCLUSION", "CTA"})
    if not has_opening: warnings.append("content_structure_missing_opening")
    if not has_close: warnings.append("content_structure_missing_close")
    return {
        "version": 1, "method": "episode_wide_narrative_function_and_semantic_argument_map",
        "units": units, "actions": actions, "selected_ranges": ranges,
        "structure": {
            "functions": functions, "has_opening": has_opening, "has_conclusion_or_cta": has_close,
            "outline": [{"function": unit["narrative_function"], "text": unit["text"], "decision": unit["decision"]} for unit in units],
        },
        "warnings": sorted(set(warnings)),
        "summary": {
            "units": len(units), "kept": sum(unit["decision"] == "KEEP" for unit in units),
            "trimmed_duplicates": sum(unit["decision"] == "TRIM" for unit in units),
            "replacement_takes": sum(unit["decision"] == "REPLACE_TAKE" for unit in units),
            "review_required": sum(unit["decision"] == "REVIEW_REQUIRED" for unit in units),
        },
    }
