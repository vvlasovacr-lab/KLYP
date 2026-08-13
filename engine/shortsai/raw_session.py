from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import html
import math
import re
from pathlib import Path
import subprocess
from typing import Any, Iterable, Sequence

from .transcription import Transcript, TranscriptSegment, TranscriptWord


WORD_RE = re.compile(r"[\w\d]+", re.UNICODE)
STOP_WORDS = frozenset(
    "и а но или в во на с со к у от до из за по для о об это этот эта эти что как я ты он она мы вы они "
    "не ни то так же уже еще только вот потому если когда где который которая которые мой твой свой наш ваш "
    "бы было была были будет есть очень просто вообще типа ну блин".split()
)
FILLERS = frozenset("ээ эм ну короче как бы вот типа значит блин".split())
FORMAT_CUES = (
    "storytelling", "сторителлинг", "подкаст", "podcast", "номберс", "numbers",
    "эксперт клин", "clean expert", "moving person", "face tracking", "фейс трекинг",
    "мессис пич", "message speech", "следующий вариант",
)
RECORDING_CUES = (
    "настройка камеры", "настроить камеру", "настройка микрофона", "проверка микрофона",
    "проверяем звук", "звук ставить", "проверяем что-то", "проверяем что то",
    "тест монтаж", "тестовый монтаж", "позиционирование субтитров", "трекинг",
    "человек перемещается по кадру", "перемещается по кадру", "ходить по кадру", "не нужно ходить", "во время записи",
    "сейчас записывал", "записываем", "запись пошла", "свет поставить",
)
RESTART_CUES = (
    "еще раз", "ещё раз", "давай заново", "сначала заново", "следующий дубль",
    "следующая попытка", "нет не так", "стоп", "подожди",
)
ERROR_CUES = (
    "херню какую-то несу", "хуйню какую-то несу", "бред ебаный", "ладно похуй",
    "не получилось", "оговорился", "ошибся", "запорол",
)
PROFANITY = frozenset("бля блядь ебаный ебаная ебаное пиздец хуйню херню похуй проебал".split())

TOPIC_STEMS: dict[str, tuple[str, ...]] = {
    "finance": ("деньг", "зарплат", "доход", "заработ", "миллион", "тысяч", "рубл", "эконом", "откладыв", "трат", "расход", "накоп"),
    "advertising": ("реклам", "клиент", "оффер", "бюджет", "продукт", "услуг", "клик", "лид", "эксперт"),
    "work": ("работ", "труд", "задач", "результат", "цель", "созвон", "компьютер", "дела", "навык", "состояни"),
    "online_business": ("интернет", "онлайн", "ниш", "направлен", "бизнес", "продаж"),
    "story": ("истори", "случ", "однажды", "потер", "произош", "оказал"),
}


def _tokens(text: str, *, content_only: bool = False) -> list[str]:
    values = [token.lower().replace("ё", "е") for token in WORD_RE.findall(text)]
    return [token for token in values if not content_only or token not in STOP_WORDS and len(token) > 2]


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    normalized = " ".join(_tokens(text))
    return any(" ".join(_tokens(phrase)) in normalized for phrase in phrases)


def _similarity(left: str, right: str) -> float:
    left_tokens, right_tokens = _tokens(left, content_only=True), _tokens(right, content_only=True)
    if not left_tokens or not right_tokens:
        return 0.0
    left_set, right_set = set(left_tokens), set(right_tokens)
    overlap = len(left_set & right_set) / max(1, min(len(left_set), len(right_set)))
    sequence = SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio()
    prefix_size = min(8, len(left_tokens), len(right_tokens))
    prefix = SequenceMatcher(None, left_tokens[:prefix_size], right_tokens[:prefix_size]).ratio()
    return round(max(overlap * 0.72 + sequence * 0.28, prefix * 0.86), 3)


def _unit_from_words(words_source: Sequence[TranscriptWord]) -> dict[str, Any]:
    text = " ".join(word.text for word in words_source).strip()
    words = [{"word": word.text, "start": word.start, "end": word.end, "probability": word.probability} for word in words_source]
    return {
        "start": float(words_source[0].start), "end": float(words_source[-1].end), "text": text,
        "words": words, "format_cue": _contains_any(text, FORMAT_CUES),
        "recording_cue": _contains_any(text, RECORDING_CUES),
        "restart_cue": _contains_any(text, RESTART_CUES),
        "error_cue": _contains_any(text, ERROR_CUES),
    }


def _units_from_segment(segment: TranscriptSegment) -> list[dict[str, Any]]:
    """Split Whisper segments into semantic micro-phrases before classifying takes."""
    if not segment.words:
        return []
    groups: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in segment.words:
        if current and word.start - current[-1].end >= 0.9:
            groups.append(current); current = []
        current.append(word)
        if word.text.rstrip().endswith((".", "!", "?", ":", ";")):
            groups.append(current); current = []
    if current:
        groups.append(current)
    return [_unit_from_words(group) for group in groups if group]


def _topic_categories(text: str) -> set[str]:
    tokens = _tokens(text, content_only=True)
    return {
        category for category, stems in TOPIC_STEMS.items()
        if any(any(token.startswith(stem) for stem in stems) for token in tokens)
    }


def _unit_non_content(unit: dict[str, Any], index: int, duration: float) -> tuple[str, float, str]:
    text = str(unit["text"])
    tokens = _tokens(text)
    profanity = sum(token in PROFANITY for token in tokens)
    if unit["format_cue"]:
        return "NON_CONTENT", 0.92, "explicit recording-format marker"
    if unit["recording_cue"]:
        return "NON_CONTENT", 0.94, "camera/audio/subtitle setup language"
    if unit["restart_cue"] and len(tokens) <= 12:
        return "NON_CONTENT", 0.88, "explicit restart or take-control phrase"
    if unit["error_cue"]:
        return "NON_CONTENT", 0.91, "speaker comments on a failed recording attempt"
    if profanity >= 2 and len(tokens) <= 14:
        return "REVIEW_REQUIRED", 0.66, "ambiguous emotional recording-side comment"
    if len(tokens) <= 2 and profanity:
        return "NON_CONTENT", 0.82, "isolated error reaction"
    return "CONTENT", 0.72, "viewer-facing speech"


def _merge_units(units: Sequence[dict[str, Any]], gap_threshold: float) -> list[dict[str, Any]]:
    takes: list[dict[str, Any]] = []
    for unit in units:
        classification = unit["classification"]
        if (
            takes and classification == takes[-1]["classification"]
            and float(unit["start"]) - float(takes[-1]["end"]) < gap_threshold
            and not unit.get("format_cue")
        ):
            take = takes[-1]
            take["end"] = unit["end"]
            take["text"] = f"{take['text']} {unit['text']}".strip()
            take["words"].extend(unit["words"])
            take["units"].append(unit)
            take["confidence"] = round((take["confidence"] + unit["confidence"]) / 2, 3)
            take["reasons"] = sorted(set([*take["reasons"], unit["reason"]]))
        else:
            takes.append({
                "id": f"take-{len(takes)+1:03d}", "start": unit["start"], "end": unit["end"],
                "text": unit["text"], "words": list(unit["words"]), "units": [unit],
                "classification": classification, "confidence": unit["confidence"],
                "reasons": [unit["reason"]], "format_boundary": bool(unit.get("format_cue")),
            })
        takes[-1]["topic_categories"] = sorted(_topic_categories(str(takes[-1]["text"])))
    return takes


def _take_score(take: dict[str, Any]) -> dict[str, float]:
    words = take.get("words", [])
    tokens = _tokens(str(take.get("text", "")))
    probabilities = [float(word.get("probability", 0.0)) for word in words]
    avg_probability = sum(probabilities) / max(1, len(probabilities))
    filler_rate = sum(token in FILLERS for token in tokens) / max(1, len(tokens))
    profanity_rate = sum(token in PROFANITY for token in tokens) / max(1, len(tokens))
    duration = max(0.1, float(take["end"]) - float(take["start"]))
    words_per_second = len(tokens) / duration
    pace_score = max(0.0, 1.0 - abs(words_per_second - 2.7) / 4.0)
    complete = 1.0 if str(take.get("text", "")).rstrip().endswith((".", "!", "?")) else 0.65
    length_score = min(1.0, math.log2(max(2, len(tokens))) / 6.0)
    error_penalty = 1.0 if _contains_any(str(take.get("text", "")), ERROR_CUES) else 0.0
    score = (
        avg_probability * 0.30 + complete * 0.18 + pace_score * 0.14 + length_score * 0.18
        + (1.0 - min(1.0, filler_rate * 5)) * 0.12
        + (1.0 - min(1.0, profanity_rate * 4)) * 0.08
        - error_penalty * 0.24
    )
    return {
        "score": round(max(0.0, min(1.0, score)), 3),
        "word_probability": round(avg_probability, 3), "completeness": complete,
        "filler_rate": round(filler_rate, 3), "pace_score": round(pace_score, 3),
        "error_penalty": error_penalty,
    }


def _topic_similarity(left: Sequence[dict[str, Any]], right: dict[str, Any]) -> float:
    recent = " ".join(str(take["text"]) for take in left[-3:])
    return _similarity(recent, str(right["text"]))


def _looks_like_hook(text: str) -> bool:
    stripped = text.strip()
    tokens = _tokens(stripped)
    return (
        stripped.endswith("?") or any(char.isdigit() for char in stripped)
        or (tokens and tokens[0] in {"почему", "как", "зачем", "сколько", "пять", "три", "два", "первое"})
    )


def _deduplicate_units(take: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for unit in take.get("units", []):
        unit_tokens = _tokens(unit["text"], content_only=True)
        duplicate = next((
            previous for previous in reversed(selected[-3:])
            if len(_tokens(previous["text"], content_only=True)) >= 3 and len(unit_tokens) >= 3
            and _similarity(previous["text"], unit["text"]) >= 0.82
        ), None)
        if duplicate:
            def local_score(value: dict[str, Any]) -> float:
                tokens = _tokens(value["text"])
                complete = 0.35 if str(value["text"]).rstrip().endswith((".", "!", "?")) else 0.0
                fillers = sum(token in FILLERS for token in tokens) / max(1, len(tokens))
                return len(tokens) * 0.04 + complete - fillers * 0.5
            if local_score(unit) > local_score(duplicate):
                selected.remove(duplicate); selected.append(unit)
                rejected.append({"start": duplicate["start"], "end": duplicate["end"], "text": duplicate["text"], "reason": f"lower-quality repeated sentence; replaced by {unit['start']:.3f}"})
            else:
                rejected.append({"start": unit["start"], "end": unit["end"], "text": unit["text"], "reason": f"repeated sentence inside selected take; duplicates {duplicate['start']:.3f}"})
        else:
            if selected:
                previous_tokens = _tokens(selected[-1]["text"], content_only=True)
                normalized_current = " ".join(unit_tokens)
                normalized_previous = " ".join(previous_tokens)
                if len(previous_tokens) <= 4 and previous_tokens and normalized_previous in normalized_current and float(unit["start"]) - float(selected[-1]["end"]) < 4.0:
                    prefix = selected.pop()
                    rejected.append({"start": prefix["start"], "end": prefix["end"], "text": prefix["text"], "reason": f"abandoned phrase prefix; completed at {unit['start']:.3f}"})
            selected.append(unit)
    return selected, rejected


def _merge_ranges(ranges: Sequence[dict[str, Any]], maximum_gap: float = 0.08) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in sorted(ranges, key=lambda value: float(value["source_start"])):
        start, end = float(item["source_start"]), float(item["source_end"])
        if merged and start - float(merged[-1]["source_end"]) <= maximum_gap:
            merged[-1]["source_end"] = round(max(float(merged[-1]["source_end"]), end), 3)
        else:
            merged.append({"source_start": round(start, 3), "source_end": round(end, 3)})
    return merged


def classify_session(transcript: Transcript, duration: float) -> dict[str, Any]:
    text = " ".join(segment.text for segment in transcript.segments)
    gaps = [
        float(right.start) - float(left.end)
        for left, right in zip(transcript.segments, transcript.segments[1:])
    ]
    long_gaps = sum(gap >= 4.0 for gap in gaps)
    format_cues = sum(_contains_any(segment.text, FORMAT_CUES) for segment in transcript.segments)
    recording_cues = sum(_contains_any(segment.text, (*RECORDING_CUES, *RESTART_CUES, *ERROR_CUES)) for segment in transcript.segments)
    score = (
        (0.40 if duration >= 180 else 0.15 if duration >= 110 else 0.0)
        + min(0.25, long_gaps / 20.0)
        + min(0.22, format_cues * 0.06)
        + min(0.20, recording_cues * 0.05)
    )
    classification = "RAW_MULTI_TAKE_SESSION" if score >= 0.55 else "SINGLE_READY_CLIP"
    reasons = []
    if duration >= 180: reasons.append("long source duration")
    if long_gaps: reasons.append(f"{long_gaps} long speech gaps")
    if format_cues: reasons.append(f"{format_cues} explicit format/take markers")
    if recording_cues: reasons.append(f"{recording_cues} recording-side comments")
    if not reasons: reasons.append("continuous short viewer-facing speech")
    return {
        "classification": classification, "confidence": round(min(0.99, 0.5 + abs(score - 0.55)), 3),
        "raw_score": round(score, 3), "reason": reasons,
        "features": {"duration": round(duration, 3), "long_gaps": long_gaps, "format_cues": format_cues, "recording_cues": recording_cues},
    }


def analyze_raw_session(transcript: Transcript, duration: float) -> dict[str, Any]:
    classification = classify_session(transcript, duration)
    units = [unit for segment in transcript.segments for unit in _units_from_segment(segment)]
    pending_format_setup_until = -1.0
    for index, unit in enumerate(units):
        label, confidence, reason = _unit_non_content(unit, index, duration)
        if unit.get("format_cue") or (unit.get("recording_cue") and float(unit["start"]) > duration * 0.80):
            pending_format_setup_until = float(unit["end"]) + 24.0
        elif pending_format_setup_until >= float(unit["start"]):
            if label == "CONTENT" and _looks_like_hook(str(unit["text"])):
                pending_format_setup_until = -1.0
            elif label == "CONTENT":
                label, confidence, reason = "NON_CONTENT", 0.78, "recording-side setup after a format marker"
        unit.update({"classification": label, "confidence": confidence, "reason": reason})
    takes = _merge_units(units, 2.5)
    for take in takes:
        take["quality"] = _take_score(take)

    if classification["classification"] == "SINGLE_READY_CLIP":
        selected = _merge_ranges([{"source_start": 0.0, "source_end": duration}])
        return {
            "version": 1, **classification, "source_duration": round(duration, 3),
            "ranges": [{"source_start": 0.0, "source_end": round(duration, 3), "classification": "EPISODE", "episode_id": "episode-001", "confidence": classification["confidence"], "reason": "single ready clip passthrough"}],
            "take_groups": [], "episodes": [{
                "episode_id": "episode-001", "selected_ranges": selected, "rejected_ranges": [],
                "topic": "single ready clip", "summary": transcript.segments[0].text if transcript.segments else "",
                "confidence": classification["confidence"], "source_duration": round(duration, 3), "episode_duration": round(duration, 3),
            }],
        }

    episode_take_lists: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    pending_boundary = False
    non_content = [take for take in takes if take["classification"] == "NON_CONTENT"]
    review_takes = [take for take in takes if take["classification"] == "REVIEW_REQUIRED"]
    for take in takes:
        if take["classification"] != "CONTENT":
            if take.get("format_boundary"):
                if current:
                    episode_take_lists.append(current); current = []
                pending_boundary = True
            continue
        if not current:
            current = [take]; pending_boundary = False; continue
        gap = float(take["start"]) - float(current[-1]["end"])
        similarity = _topic_similarity(current, take)
        current_topics = set().union(*(set(item.get("topic_categories", [])) for item in current))
        take_topics = set(take.get("topic_categories", []))
        topic_continuity = bool(current_topics & take_topics)
        semantic_boundary = (
            pending_boundary
            or (not topic_continuity and gap >= 7.0 and similarity < 0.16 and _looks_like_hook(str(take["text"])))
            or (not topic_continuity and gap >= 14.0 and similarity < 0.22)
        )
        if semantic_boundary:
            episode_take_lists.append(current); current = [take]
        else:
            current.append(take)
        pending_boundary = False
    if current:
        episode_take_lists.append(current)

    episodes: list[dict[str, Any]] = []
    take_groups: list[dict[str, Any]] = []
    all_rejected: list[dict[str, Any]] = []
    for candidates in episode_take_lists:
        grouped: list[list[dict[str, Any]]] = []
        consumed: set[str] = set()
        for take in candidates:
            if take["id"] in consumed: continue
            group = [take]; consumed.add(take["id"])
            for other in candidates:
                if other["id"] in consumed: continue
                common = _similarity(str(take["text"]), str(other["text"]))
                if common >= 0.58 and abs(float(other["start"]) - float(take["start"])) <= 75:
                    group.append(other); consumed.add(other["id"])
            grouped.append(group)

        selected_units: list[dict[str, Any]] = []
        rejected_ranges: list[dict[str, Any]] = []
        for group in grouped:
            selected_take = max(group, key=lambda value: float(value["quality"]["score"]))
            units_kept, internal_rejected = _deduplicate_units(selected_take)
            selected_units.extend(units_kept)
            rejected_ranges.extend(internal_rejected)
            if len(group) > 1:
                group_id = f"retake-{len(take_groups)+1:03d}"
                rejected = [item for item in group if item is not selected_take]
                for item in rejected:
                    rejected_ranges.append({"start": item["start"], "end": item["end"], "text": item["text"], "reason": f"lower take quality than {selected_take['id']}"})
                take_groups.append({
                    "take_group_id": group_id, "selected_take_id": selected_take["id"],
                    "selected_score": selected_take["quality"],
                    "candidates": [{"take_id": item["id"], "start": item["start"], "end": item["end"], "text": item["text"], "quality": item["quality"], "selected": item is selected_take} for item in group],
                    "reason": "semantic repetition; selected by completeness, fluency, fillers, ASR confidence and pace",
                })
        selected_ranges = _merge_ranges([{"source_start": unit["start"], "source_end": unit["end"]} for unit in selected_units])
        episode_duration = sum(float(item["source_end"]) - float(item["source_start"]) for item in selected_ranges)
        if episode_duration < 10.0:
            all_rejected.extend({"start": item["source_start"], "end": item["source_end"], "reason": "insufficient standalone content; REVIEW_REQUIRED"} for item in selected_ranges)
            continue
        text = " ".join(unit["text"] for unit in selected_units)
        keywords = [token for token, _ in Counter(_tokens(text, content_only=True)).most_common(7)]
        episode_id = f"episode-{len(episodes)+1:03d}"
        episodes.append({
            "episode_id": episode_id, "selected_ranges": selected_ranges,
            "rejected_ranges": rejected_ranges, "topic": " ".join(keywords[:4]),
            "keywords": keywords, "summary": " ".join(text.split()[:18]),
            "confidence": round(min(0.94, 0.68 + len(selected_ranges) * 0.02), 3),
            "source_start": selected_ranges[0]["source_start"], "source_end": selected_ranges[-1]["source_end"],
            "source_duration": round(float(selected_ranges[-1]["source_end"]) - float(selected_ranges[0]["source_start"]), 3),
            "episode_duration": round(episode_duration, 3),
        })

    ranges: list[dict[str, Any]] = []
    speech_intervals = sorted((float(unit["start"]), float(unit["end"])) for unit in units)
    silence_cursor = 0.0
    for start, end in speech_intervals:
        if start - silence_cursor >= 0.35:
            ranges.append({"source_start": round(silence_cursor, 3), "source_end": round(start, 3), "classification": "NON_CONTENT", "confidence": 0.98, "reason": "no detected speech"})
        silence_cursor = max(silence_cursor, end)
    if duration - silence_cursor >= 0.35:
        ranges.append({"source_start": round(silence_cursor, 3), "source_end": round(duration, 3), "classification": "NON_CONTENT", "confidence": 0.98, "reason": "no detected speech"})
    for take in non_content:
        ranges.append({"source_start": round(take["start"], 3), "source_end": round(take["end"], 3), "classification": "NON_CONTENT", "confidence": take["confidence"], "reason": "; ".join(take["reasons"]), "text": take["text"]})
    for take in review_takes:
        ranges.append({"source_start": round(take["start"], 3), "source_end": round(take["end"], 3), "classification": "REVIEW_REQUIRED", "confidence": take["confidence"], "reason": "; ".join(take["reasons"]), "text": take["text"]})
    for group in take_groups:
        for item in group["candidates"]:
            if not item["selected"]:
                ranges.append({"source_start": round(item["start"], 3), "source_end": round(item["end"], 3), "classification": "RETAKE", "take_group_id": group["take_group_id"], "confidence": 0.82, "reason": "rejected lower-quality duplicate", "text": item["text"]})
    for episode in episodes:
        for selected in episode["selected_ranges"]:
            ranges.append({**selected, "classification": "EPISODE", "episode_id": episode["episode_id"], "confidence": episode["confidence"], "reason": "selected viewer-facing range"})
    ranges.extend({"source_start": round(item["start"], 3), "source_end": round(item["end"], 3), "classification": "REVIEW_REQUIRED", "confidence": 0.5, "reason": item["reason"]} for item in all_rejected)
    ranges.sort(key=lambda item: (float(item["source_start"]), float(item["source_end"])))
    return {
        "version": 1, **classification, "source_duration": round(duration, 3),
        "ranges": ranges, "take_groups": take_groups, "episodes": episodes,
        "summary": {
            "non_content_seconds": round(sum(float(t["end"]) - float(t["start"]) for t in non_content), 3),
            "silence_seconds": round(sum(float(item["source_end"]) - float(item["source_start"]) for item in ranges if item.get("reason") == "no detected speech"), 3),
            "take_groups": len(take_groups), "rejected_takes": sum(len(group["candidates"]) - 1 for group in take_groups),
            "episodes": len(episodes), "review_required": len(all_rejected),
            "review_required_takes": len(review_takes),
        },
    }


def extract_episode_source(
    source: Path, selected_ranges: Sequence[dict[str, Any]], destination: Path,
    ffmpeg: Path, *, has_audio: bool,
) -> None:
    """Create a normalized child source; FFmpeg applies source rotation metadata."""
    if not selected_ranges:
        raise ValueError("Episode has no selected source ranges")
    filters: list[str] = []
    concat_inputs: list[str] = []
    command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error"]
    for index, item in enumerate(selected_ranges):
        start, end = float(item["source_start"]), float(item["source_end"])
        command.extend(["-ss", f"{start:.3f}", "-t", f"{max(0.02, end-start):.3f}", "-i", str(source)])
        filters.append(f"[{index}:v]setpts=PTS-STARTPTS[v{index}]")
        concat_inputs.append(f"[v{index}]")
        if has_audio:
            filters.append(f"[{index}:a]asetpts=PTS-STARTPTS[a{index}]")
            concat_inputs.append(f"[a{index}]")
    streams = "".join(concat_inputs)
    filters.append(f"{streams}concat=n={len(selected_ranges)}:v=1:a={1 if has_audio else 0}[vout]{'[aout]' if has_audio else ''}")
    command.extend(["-filter_complex", ";".join(filters), "-map", "[vout]"])
    if has_audio:
        command.extend(["-map", "[aout]"])
    command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"])
    if has_audio:
        command.extend(["-c:a", "aac", "-b:a", "192k"])
    command.extend(["-metadata:s:v:0", "rotate=0", "-movflags", "+faststart", str(destination)])
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, check=True)


def write_session_preview(analysis: dict[str, Any], destination: Path) -> None:
    duration = max(0.001, float(analysis.get("source_duration", 0.0)))
    colors = {"EPISODE": "#22c55e", "RETAKE": "#f59e0b", "NON_CONTENT": "#64748b", "REVIEW_REQUIRED": "#ef4444"}
    bars = []
    for item in analysis.get("ranges", []):
        start, end = float(item["source_start"]), float(item["source_end"])
        left, width = start / duration * 100, max(0.25, (end - start) / duration * 100)
        label = html.escape(f"{item.get('classification')} {start:.1f}-{end:.1f}: {item.get('text', item.get('reason', ''))}")
        bars.append(f'<span title="{label}" style="left:{left:.4f}%;width:{width:.4f}%;background:{colors.get(str(item.get("classification")), "#94a3b8")}"></span>')
    rows = []
    for episode in analysis.get("episodes", []):
        rows.append(f"<tr><td>{html.escape(str(episode['episode_id']))}</td><td>{float(episode['source_start']):.1f}–{float(episode['source_end']):.1f}</td><td>{float(episode['episode_duration']):.1f}s</td><td>{html.escape(str(episode.get('topic', '')))}</td><td>{float(episode.get('confidence', 0)):.2f}</td></tr>")
    document = f"""<!doctype html><meta charset='utf-8'><title>ShortsAI Raw Session</title><style>body{{font:15px system-ui;background:#0f172a;color:#e2e8f0;padding:28px}}.timeline{{height:54px;background:#1e293b;position:relative;border-radius:8px;overflow:hidden}}.timeline span{{position:absolute;top:0;height:100%;opacity:.9;border-right:1px solid #0f172a}}table{{width:100%;border-collapse:collapse;margin-top:24px}}td,th{{padding:9px;border-bottom:1px solid #334155;text-align:left}}code{{color:#fbbf24}}</style><h1>Raw Session Analysis</h1><p><code>{html.escape(str(analysis.get('classification')))}</code> · confidence {float(analysis.get('confidence', 0)):.2f} · source {duration:.1f}s</p><div class='timeline'>{''.join(bars)}</div><p>Green: episode · orange: retake · gray: non-content · red: review</p><table><thead><tr><th>Episode</th><th>Source</th><th>Selected</th><th>Topic</th><th>Confidence</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")


def build_episode_transcript(
    source: Transcript, selected_ranges: Sequence[dict[str, Any]],
) -> tuple[Transcript, list[dict[str, Any]], list[dict[str, Any]]]:
    mapping: list[dict[str, Any]] = []
    cursor = 0.0
    for item in selected_ranges:
        source_start, source_end = float(item["source_start"]), float(item["source_end"])
        duration = max(0.0, source_end - source_start)
        mapping.append({
            "source_start": round(source_start, 3), "source_end": round(source_end, 3),
            "episode_start": round(cursor, 3), "episode_end": round(cursor + duration, 3),
        })
        cursor += duration
    words: list[dict[str, Any]] = []
    for segment in source.segments:
        for word in segment.words:
            center = (word.start + word.end) / 2
            piece = next((item for item in mapping if item["source_start"] <= center <= item["source_end"]), None)
            if piece is None: continue
            start = float(piece["episode_start"]) + max(0.0, word.start - float(piece["source_start"]))
            end = float(piece["episode_start"]) + max(0.0, word.end - float(piece["source_start"]))
            if end <= start: end = start + 0.02
            words.append({
                "word": word.text, "start": round(start, 3), "end": round(min(float(piece["episode_end"]), end), 3),
                "probability": word.probability, "original_source_start": round(word.start, 3),
                "original_source_end": round(word.end, 3),
            })
    segments: list[TranscriptSegment] = []
    current: list[TranscriptWord] = []
    previous_piece: dict[str, Any] | None = None
    for item in words:
        piece = next(value for value in mapping if value["episode_start"] <= item["start"] <= value["episode_end"])
        word = TranscriptWord(item["start"], item["end"], item["word"], item["probability"])
        boundary = previous_piece is not None and piece is not previous_piece
        if current and (boundary or word.start - current[-1].end >= 0.4 or current[-1].text.endswith((".", "!", "?"))):
            segments.append(TranscriptSegment(current[0].start, current[-1].end, " ".join(value.text for value in current), tuple(current))); current = []
        current.append(word); previous_piece = piece
    if current:
        segments.append(TranscriptSegment(current[0].start, current[-1].end, " ".join(value.text for value in current), tuple(current)))
    return Transcript(source.language, source.language_probability, round(cursor, 3), tuple(segments)), mapping, words
