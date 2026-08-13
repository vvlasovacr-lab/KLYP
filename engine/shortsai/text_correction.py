from __future__ import annotations

import json
import re
from pathlib import Path

from .transcription import Transcript, TranscriptSegment, TranscriptWord


def _match_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _replace_token(text: str, corrections: dict[str, str]) -> str:
    match = re.match(r"^(\W*)(.*?)(\W*)$", text, flags=re.UNICODE)
    if not match:
        return text
    prefix, token, suffix = match.groups()
    replacement = corrections.get(token.lower())
    return text if replacement is None else prefix + _match_case(token, replacement) + suffix


def load_corrections(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not path.exists():
        return {}, {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return (
        {str(key).lower(): str(value) for key, value in data.get("words", {}).items()},
        {str(key): str(value) for key, value in data.get("phrases", {}).items()},
    )


def _token_key(value: str) -> str:
    return re.sub(r"^\W+|\W+$", "", value, flags=re.UNICODE).lower()


def _apply_phrase_corrections(
    words: tuple[TranscriptWord, ...], phrase_map: dict[str, str],
) -> tuple[TranscriptWord, ...]:
    """Apply phrase corrections to timestamped words, not only segment text.

    A phrase replacement may contain a different number of words (for example
    when Whisper joins a brand name to the preceding word).  The replacement
    inherits the original phrase interval and receives deterministic,
    character-weighted word timestamps.  This keeps downstream retiming and
    kinetic typography synchronized while making ``corrections.json.phrases``
    effective throughout the production pipeline.
    """
    if not words or not phrase_map:
        return words
    patterns = sorted(
        ((tuple(_token_key(part) for part in source.split()), replacement)
         for source, replacement in phrase_map.items()),
        key=lambda item: len(item[0]), reverse=True,
    )
    output: list[TranscriptWord] = []
    cursor = 0
    while cursor < len(words):
        matched: tuple[tuple[str, ...], str] | None = None
        for tokens, replacement in patterns:
            if tokens and cursor + len(tokens) <= len(words) and tuple(
                _token_key(word.text) for word in words[cursor:cursor + len(tokens)]
            ) == tokens:
                matched = (tokens, replacement)
                break
        if matched is None:
            output.append(words[cursor])
            cursor += 1
            continue

        tokens, replacement = matched
        source_words = words[cursor:cursor + len(tokens)]
        replacement_words = replacement.split()
        if not replacement_words:
            cursor += len(tokens)
            continue
        trailing = re.search(r"(\W+)$", source_words[-1].text, flags=re.UNICODE)
        if trailing and not re.search(r"\W$", replacement_words[-1], flags=re.UNICODE):
            replacement_words[-1] += trailing.group(1)
        start, end = source_words[0].start, source_words[-1].end
        duration = max(0.001, end - start)
        weights = [max(1, len(_token_key(value))) for value in replacement_words]
        total_weight = sum(weights)
        probability = sum(word.probability for word in source_words) / len(source_words)
        elapsed = 0.0
        for index, (value, weight) in enumerate(zip(replacement_words, weights)):
            word_start = start + duration * elapsed / total_weight
            elapsed += weight
            word_end = end if index == len(replacement_words) - 1 else start + duration * elapsed / total_weight
            output.append(TranscriptWord(word_start, word_end, value, probability))
        cursor += len(tokens)
    return tuple(output)


def correct_transcript(transcript: Transcript, corrections_path: Path) -> Transcript:
    word_map, phrase_map = load_corrections(corrections_path)
    segments: list[TranscriptSegment] = []
    for segment in transcript.segments:
        corrected_words = tuple(
            TranscriptWord(word.start, word.end, _replace_token(word.text, word_map), word.probability)
            for word in segment.words
        )
        corrected_words = _apply_phrase_corrections(corrected_words, phrase_map)
        corrected_text = " ".join(word.text for word in corrected_words) if corrected_words else segment.text
        if not corrected_words:
            for source, replacement in phrase_map.items():
                corrected_text = re.sub(re.escape(source), replacement, corrected_text, flags=re.IGNORECASE)
        segments.append(
            TranscriptSegment(segment.start, segment.end, corrected_text.strip(), corrected_words)
        )
    return Transcript(
        transcript.language,
        transcript.language_probability,
        transcript.duration,
        tuple(segments),
    )
