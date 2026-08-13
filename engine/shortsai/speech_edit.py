from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Sequence

from .config import SpeechEditConfig
from .transcription import Transcript, TranscriptSegment, TranscriptWord


@dataclass(frozen=True)
class RemovalDecision:
    start: float
    end: float
    reason: str
    text: str = ""


@dataclass(frozen=True)
class TimelineSegment:
    source_start: float
    source_end: float
    output_start: float
    output_end: float
    speed: float
    transition: str
    segment_type: str = "SPEECH"
    reason: str = "natural_delivery"


@dataclass(frozen=True)
class SpeechEditPlan:
    version: int
    source_duration: float
    output_duration: float
    hook: dict[str, Any]
    removals: tuple[RemovalDecision, ...]
    timeline: tuple[TimelineSegment, ...]
    removed_duration: float
    removed_fillers: tuple[str, ...]
    contextual_keeps: tuple[dict[str, Any], ...]
    weak_phrases: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        silence_reasons = {"silence", "thought_pause", "leading_silence", "trailing_silence"}
        removed_silence = sum(
            item.end - item.start
            for item in self.removals
            if any(reason in silence_reasons for reason in item.reason.split("+"))
        )
        filler_duration = sum(
            item.end - item.start for item in self.removals if "filler" in item.reason.split("+")
        )
        compression_saved = sum(
            max(0.0, (item.source_end - item.source_start) - (item.output_end - item.output_start))
            for item in self.timeline
        )
        value["cuts"] = [
            {
                "type": "REMOVE_FILLER" if "filler" in item.reason else "REMOVE_SILENCE",
                "start": round(item.start, 3),
                "end": round(item.end, 3),
                "duration": round(item.end - item.start, 3),
                "reason": item.reason,
                "text": item.text,
            }
            for item in self.removals
        ]
        value["segments"] = [
            {
                "sourceStart": item.source_start,
                "sourceEnd": item.source_end,
                "outputStart": item.output_start,
                "outputEnd": item.output_end,
                "speed": item.speed,
                "transition": item.transition,
                "type": item.segment_type,
                "reason": item.reason,
            }
            for item in self.timeline
        ]
        value["statistics"] = {
            "sourceDuration": round(self.source_duration, 3),
            "outputDuration": round(self.output_duration, 3),
            "removedTotal": round(self.removed_duration, 3),
            "removedSilence": round(removed_silence, 3),
            "removedFillers": round(filler_duration, 3),
            "savedByCompression": round(compression_saved, 3),
            "jumpCuts": sum(item.transition == "JUMP_CUT" for item in self.timeline),
            "speedChanges": sum(item.transition == "SPEED_CHANGE" for item in self.timeline),
        }
        return value


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё-]", "", text).lower()


def _analyze_hook(words: Sequence[dict[str, Any]], config: SpeechEditConfig) -> dict[str, Any]:
    window_end = min(
        float(words[-1]["end"]),
        max(1.0, config.hook_window_ms / 1000),
    )
    hook_words = [word for word in words if float(word["start"]) < window_end]
    text = " ".join(str(word["word"]) for word in hook_words).strip()
    normalized = {_normalize(str(word["word"])) for word in hook_words}
    signals: list[str] = []
    score = 0.12
    if "?" in text or normalized.intersection({"почему", "зачем", "как", "что"}):
        signals.append("question")
        score += 0.34
    if normalized.intersection({"не", "никогда", "ошибка", "проблема", "провал", "теряешь", "потеряешь"}):
        signals.append("conflict")
        score += 0.20
    if normalized.intersection({"получишь", "станешь", "изменить", "результат", "успех", "решение", "выгода"}):
        signals.append("result_promise")
        score += 0.18
    if normalized.intersection({"деньги", "миллионер", "миллион", "доход", "цена", "богатый", "богатым"}):
        signals.append("money_or_status")
        score += 0.18
    if any(re.search(r"\d", str(word["word"])) for word in hook_words):
        signals.append("number")
        score += 0.14
    if "!" in text or normalized.intersection({"всегда", "главное", "правда", "секрет"}):
        signals.append("strong_claim")
        score += 0.12
    score = round(min(1.0, score), 3)
    return {
        "start": 0.0,
        "end": round(window_end, 3),
        "text": text,
        "score": score,
        "level": "HIGH" if score >= 0.72 else "MEDIUM" if score >= 0.45 else "LOW",
        "signals": signals,
        "reason": "semantic_opening_analysis",
    }


def _semantic_clauses(words: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clauses: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        current.append(word)
        token = str(word["word"]).rstrip()
        following = words[index + 1] if index + 1 < len(words) else None
        pause = float(following["start"]) - float(word["end"]) if following else 0.0
        sentence_end = token.endswith((".", "!", "?", ":", ";"))
        soft_break = token.endswith(",") and len(current) >= 3
        if sentence_end or soft_break or pause >= 0.45:
            clauses.append(current)
            current = []
    if current:
        clauses.append(current)
    return clauses


def _compression_ranges(
    words: Sequence[dict[str, Any]], hook: dict[str, Any], config: SpeechEditConfig,
    director_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    if config.preserve_speech_rate or not config.speech_compression:
        return ()
    weak_openers = {"вот", "короче", "кстати", "просто", "вообще", "скажем", "допустим"}
    strong = {
        "деньги", "миллион", "миллионер", "богатым", "результат", "дисциплина", "цена",
        "проблема", "ошибка", "провал", "никогда", "всегда", "изменить", "жизнь", "важное",
    }
    minimum = max(0.6, config.min_compress_segment_ms / 1000)
    ranges: list[dict[str, Any]] = []
    speed = round(min(config.max_speed, max(1.0, config.compression_speed)), 3)
    for segment in (director_plan or {}).get("segments", []):
        start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
        if segment.get("speech_action") != "COMPRESS" or start < float(hook["end"]) - 0.05 or end - start < minimum:
            continue
        ranges.append({
            "start": round(start, 3), "end": round(end, 3), "speed": speed,
            "reason": "ai_director_low_retention",
            "text": segment.get("text", ""),
        })
    for clause in _semantic_clauses(words):
        start = float(clause[0]["start"])
        end = float(clause[-1]["end"])
        tokens = [_normalize(str(word["word"])) for word in clause]
        if start < float(hook["end"]) - 0.05 or end - start < minimum:
            continue
        if str(clause[-1]["word"]).rstrip().endswith(("!", "?")):
            continue
        opener = bool(tokens and tokens[0] in weak_openers)
        low_density = sum(token in weak_openers for token in tokens) >= 2
        long_and_flat = len(tokens) >= 10 and end - start >= 3.2
        contains_strong = bool(set(tokens).intersection(strong)) or any(re.search(r"\d", token) for token in tokens)
        if not (opener or low_density or long_and_flat) or contains_strong:
            continue
        if speed <= 1.001:
            continue
        if any(min(end, float(item["end"])) - max(start, float(item["start"])) > 0.2 for item in ranges):
            continue
        ranges.append({
            "start": round(start, 3), "end": round(end, 3), "speed": speed,
            "reason": "low_information_intro" if opener else "long_low_energy_clause" if long_and_flat else "low_information_density",
            "text": " ".join(str(word["word"]) for word in clause),
        })
    return tuple(ranges)


def _merge_removals(removals: Sequence[RemovalDecision], duration: float) -> list[RemovalDecision]:
    ordered = sorted(
        (RemovalDecision(max(0.0, item.start), min(duration, item.end), item.reason, item.text) for item in removals if item.end - item.start >= 0.025),
        key=lambda item: item.start,
    )
    merged: list[RemovalDecision] = []
    for item in ordered:
        if merged and item.start <= merged[-1].end + 0.015:
            previous = merged.pop()
            reasons = sorted(set(previous.reason.split("+") + item.reason.split("+")))
            text = " ".join(value for value in (previous.text, item.text) if value).strip()
            merged.append(RemovalDecision(previous.start, max(previous.end, item.end), "+".join(reasons), text))
        else:
            merged.append(item)
    return merged


def _filler_ranges(
    words: Sequence[dict[str, Any]], config: SpeechEditConfig,
) -> tuple[list[RemovalDecision], tuple[dict[str, Any], ...]]:
    """Find only acoustically isolated fillers.

    Discourse markers such as ``короче`` often connect two parts of a thought.
    Removing a marker that touches the surrounding speech creates an audible
    micro-acceleration and can also change the meaning.  A filler is therefore
    removable only when Whisper timestamps show a real pause on both sides.
    """
    if not config.remove_fillers:
        return [], ()
    normalized = [_normalize(str(word["word"])) for word in words]
    phrases = sorted((tuple(_normalize(part) for part in filler.split()) for filler in config.filler_words), key=len, reverse=True)
    removals: list[RemovalDecision] = []
    contextual_keeps: list[dict[str, Any]] = []
    used: set[int] = set()
    for index in range(len(words)):
        if index in used:
            continue
        for phrase in phrases:
            end_index = index + len(phrase)
            if tuple(normalized[index:end_index]) != phrase:
                continue
            previous = words[index - 1] if index else None
            following = words[end_index] if end_index < len(words) else None
            gap_before = float(words[index]["start"]) - float(previous["end"]) if previous else 1.0
            gap_after = float(following["start"]) - float(words[end_index - 1]["end"]) if following else 1.0
            isolated = gap_before >= config.filler_min_gap and gap_after >= config.filler_min_gap
            if not isolated:
                contextual_keeps.append({
                    "start": round(float(words[index]["start"]), 3),
                    "end": round(float(words[end_index - 1]["end"]), 3),
                    "text": " ".join(str(words[pos]["word"]) for pos in range(index, end_index)),
                    "reason": "connected_to_sentence",
                    "gap_before": round(max(0.0, gap_before), 3),
                    "gap_after": round(max(0.0, gap_after), 3),
                })
                continue
            start = float(words[index]["start"])
            end = float(words[end_index - 1]["end"])
            if end - start > 0.9:
                continue
            # Cut only the spoken filler. Adjacent room tone remains as a natural
            # micro-pause, avoiding the audible impression of a speed ramp.
            left = start
            right = end
            removals.append(RemovalDecision(left, right, "filler", " ".join(str(words[pos]["word"]) for pos in range(index, end_index))))
            used.update(range(index, end_index))
            break
    return removals, tuple(contextual_keeps)


def _weak_phrases(words: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Flag low-information spans without deleting meaning on a heuristic alone."""
    weak_tokens = {
        "ну", "вот", "как", "бы", "какбы", "вообще", "просто", "значит",
        "скажем", "допустим", "тоесть", "например", "собственно", "впринципе",
    }
    phrases: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        current.append(word)
        if str(word["word"]).rstrip().endswith((".", "!", "?", ":", ";")):
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)
    decisions: list[dict[str, Any]] = []
    for phrase in phrases:
        if len(phrase) < 5:
            continue
        normalized = [_normalize(str(item["word"])).replace("-", "") for item in phrase]
        weak_count = sum(token in weak_tokens for token in normalized)
        duration = float(phrase[-1]["end"]) - float(phrase[0]["start"])
        if weak_count < 2 and not (duration > 4.5 and len(phrase) / max(duration, 0.1) < 2.0):
            continue
        decisions.append({
            "start": round(float(phrase[0]["start"]), 3),
            "end": round(float(phrase[-1]["end"]), 3),
            "text": " ".join(str(item["word"]) for item in phrase),
            "score": round(min(1.0, weak_count / max(2, len(phrase) * 0.35)), 3),
            "decision": "KEEP_AND_TIGHTEN",
            "reason": "low_information_density",
        })
    return tuple(decisions)


def build_speech_edit_plan(
    words: Sequence[dict[str, Any]],
    duration: float,
    config: SpeechEditConfig,
    director_plan: dict[str, Any] | None = None,
) -> SpeechEditPlan:
    if not words or not config.enabled:
        segment = TimelineSegment(0.0, duration, 0.0, duration, 1.0, "CONTINUE")
        return SpeechEditPlan(3, duration, duration, {"start": 0.0, "end": min(duration, 3.0), "score": 0.0, "level": "LOW", "signals": [], "reason": "opening"}, (), (segment,), 0.0, (), (), ())

    hook = _analyze_hook(words, config)
    removals, contextual_keeps = _filler_ranges(words, config)
    first_start = float(words[0]["start"])
    last_end = float(words[-1]["end"])
    if first_start > 0.16:
        removals.append(RemovalDecision(0.0, max(0.0, first_start - 0.08), "leading_silence"))
    if duration - last_end > 0.2:
        removals.append(RemovalDecision(min(duration, last_end + 0.12), duration, "trailing_silence"))

    for previous, following in zip(words, words[1:]):
        gap_start = float(previous["end"])
        gap_end = float(following["start"])
        gap = gap_end - gap_start
        thought_boundary = str(previous["word"]).rstrip().endswith((".", "!", "?", ":", ";"))
        threshold = max(config.min_silence_remove_ms / 1000, config.thought_pause_threshold if thought_boundary else config.silence_threshold)
        if gap <= threshold:
            continue
        previous_token = _normalize(str(previous["word"]))
        following_token = _normalize(str(following["word"]))
        phrase_connectors = {"и", "но", "а", "или", "что", "чтобы", "если", "когда", "потому"}
        if not thought_boundary and (previous_token in phrase_connectors or following_token in phrase_connectors) and gap < threshold * 1.6:
            continue
        # Never collapse a breath to zero. Sentence boundaries preserve the
        # configured maximum natural pause, inner-clause gaps stay shorter.
        allowed_pause = max(0.18, config.max_allowed_pause_ms / 1000)
        keep_pause = min(allowed_pause, config.retained_thought_pause if thought_boundary else config.retained_pause)
        trim = max(0.0, gap - keep_pause)
        if trim >= 0.04:
            left = gap_start + keep_pause / 2
            right = gap_end - keep_pause / 2
            removals.append(RemovalDecision(left, right, "thought_pause" if thought_boundary else "silence"))

    merged = _merge_removals(removals, duration)
    weak_phrases = _weak_phrases(words)
    compression_ranges = _compression_ranges(words, hook, config, director_plan)
    weak_phrases = tuple(
        {
            **phrase,
            "decision": "COMPRESS" if any(
                min(float(phrase["end"]), float(item["end"])) - max(float(phrase["start"]), float(item["start"])) > 0.4
                for item in compression_ranges
            ) else "KEEP",
        }
        for phrase in weak_phrases
    )
    keep_ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for removal in merged:
        if removal.start - cursor >= 0.08:
            keep_ranges.append((cursor, removal.start))
        cursor = max(cursor, removal.end)
    if duration - cursor >= 0.08:
        keep_ranges.append((cursor, duration))
    if not keep_ranges:
        keep_ranges = [(0.0, duration)]

    split_ranges: list[tuple[float, float]] = []
    # Timeline boundaries exist only where playback actually changes. Analysis
    # markers must not create 50-100 ms media segments around a natural breath.
    edit_boundaries = sorted({
        float(value)
        for item in compression_ranges
        for value in (item["start"], item["end"])
    })
    for start, end in keep_ranges:
        boundaries = [start, *(value for value in edit_boundaries if start + 0.12 < value < end - 0.12), end]
        split_ranges.extend((left, right) for left, right in zip(boundaries, boundaries[1:]) if right - left >= 0.08)
    keep_ranges = split_ranges or keep_ranges

    timeline: list[TimelineSegment] = []
    output_cursor = 0.0
    for index, (start, end) in enumerate(keep_ranges):
        segment_words = [word for word in words if start <= (float(word["start"]) + float(word["end"])) / 2 <= end]
        spoken = sum(max(0.0, float(word["end"]) - float(word["start"])) for word in segment_words)
        word_rate = len(segment_words) / max(0.2, end - start)
        compression = next((
            item for item in compression_ranges
            if min(end, float(item["end"])) - max(start, float(item["start"])) >= (end - start) * 0.75
        ), None)
        speed = float(compression["speed"]) if compression else 1.0
        speed = round(min(config.max_speed, max(1.0, speed)), 3)
        segment_type = "HOOK" if start < float(hook["end"]) - 0.05 else "COMPRESSED" if compression else "SPEECH"
        reason = str(compression["reason"]) if compression else "protected_hook" if segment_type == "HOOK" else "natural_delivery"
        output_length = (end - start) / speed
        output_end = output_cursor + output_length
        if timeline and abs(start - timeline[-1].source_end) <= 0.02 and abs(speed - timeline[-1].speed) <= 0.001 and segment_type == timeline[-1].segment_type:
            previous = timeline[-1]
            timeline[-1] = TimelineSegment(
                previous.source_start, round(end, 3), previous.output_start,
                round(output_end, 3), speed, previous.transition, previous.segment_type, previous.reason,
            )
            output_cursor = output_end
            continue
        if index == 0 and start <= 0.01:
            transition = "CONTINUE"
        elif timeline and abs(start - timeline[-1].source_end) <= 0.02:
            transition = "SPEED_CHANGE"
        else:
            transition = "JUMP_CUT"
        timeline.append(TimelineSegment(
            round(start, 3), round(end, 3), round(output_cursor, 3), round(output_end, 3),
            speed, transition, segment_type, reason,
        ))
        output_cursor = output_end

    removed_fillers = tuple(item.text for item in merged if "filler" in item.reason and item.text)
    removed_duration = duration - output_cursor
    return SpeechEditPlan(
        3, round(duration, 3), round(output_cursor, 3), hook,
        tuple(merged), tuple(timeline), round(max(0.0, removed_duration), 3),
        removed_fillers, contextual_keeps, weak_phrases,
    )


def apply_speech_edit(words: Sequence[dict[str, Any]], plan: SpeechEditPlan) -> list[dict[str, Any]]:
    edited: list[dict[str, Any]] = []
    for word in words:
        center = (float(word["start"]) + float(word["end"])) / 2
        segment = next((item for item in plan.timeline if item.source_start <= center <= item.source_end), None)
        if segment is None:
            continue
        item = dict(word)
        item["source_start"] = round(float(word["start"]), 3)
        item["source_end"] = round(float(word["end"]), 3)
        mapped_start = segment.output_start + (float(word["start"]) - segment.source_start) / segment.speed
        mapped_end = segment.output_start + (float(word["end"]) - segment.source_start) / segment.speed
        # Whisper can occasionally emit a real token with a zero-length timestamp.
        # Keep the token at its recognized position while giving renderers a tiny,
        # valid interval. This is a transport invariant, not an editorial retime.
        mapped_start = max(0.0, min(plan.output_duration, mapped_start))
        mapped_end = max(mapped_start + 0.02, mapped_end)
        if mapped_end > plan.output_duration:
            mapped_end = plan.output_duration
            mapped_start = max(0.0, min(mapped_start, mapped_end - 0.02))
        item["start"] = round(mapped_start, 3)
        item["end"] = round(max(mapped_start + 0.001, mapped_end), 3)
        edited.append(item)
    return edited


def transcript_from_edited_words(source: Transcript, words: Sequence[dict[str, Any]], duration: float) -> Transcript:
    segments: list[TranscriptSegment] = []
    current: list[TranscriptWord] = []
    for item in words:
        word = TranscriptWord(float(item["start"]), float(item["end"]), str(item["word"]), float(item.get("probability", 0.0)))
        if current and (word.start - current[-1].end >= 0.28 or current[-1].text.rstrip().endswith((".", "!", "?", ":", ";"))):
            segments.append(TranscriptSegment(current[0].start, current[-1].end, " ".join(value.text for value in current), tuple(current)))
            current = []
        current.append(word)
    if current:
        segments.append(TranscriptSegment(current[0].start, current[-1].end, " ".join(value.text for value in current), tuple(current)))
    return Transcript(source.language, source.language_probability, duration, tuple(segments))
