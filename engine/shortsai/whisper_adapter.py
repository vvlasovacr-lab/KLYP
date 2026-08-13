from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .transcription import Transcript


def transcript_to_chunks(transcript: Transcript) -> list[dict[str, Any]]:
    """Flatten a typed Whisper transcript without losing word timestamps."""
    return [
        {
            "word": word.text,
            "start": round(word.start, 3),
            "end": round(word.end, 3),
            "probability": round(word.probability, 4),
        }
        for segment in transcript.segments
        for word in segment.words
    ]


def transcript_json_to_chunks(source: Path) -> list[dict[str, Any]]:
    data = json.loads(source.read_text(encoding="utf-8"))
    return [
        {
            "word": str(word["text"]),
            "start": round(float(word["start"]), 3),
            "end": round(float(word["end"]), 3),
            "probability": round(float(word.get("probability", 0.0)), 4),
        }
        for segment in data.get("segments", [])
        for word in segment.get("words", [])
    ]


def write_chunks(chunks: list[dict[str, Any]], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination
