from __future__ import annotations

from typing import Any, Sequence


def _map_time(timestamp: float, timeline: Sequence[dict[str, Any]]) -> float | None:
    for item in timeline:
        start, end = float(item["source_start"]), float(item["source_end"])
        if start - 0.015 <= timestamp <= end + 0.015:
            speed = max(0.001, float(item.get("speed", 1.0)))
            return round(float(item["output_start"]) + max(0.0, timestamp - start) / speed, 3)
    return None


def build_timeline_plan(
    speech_edit: dict[str, Any], content_map: dict[str, Any] | None,
) -> dict[str, Any]:
    """Construct the edit sequence without typography or motion decisions."""
    speech_timeline = [dict(item) for item in speech_edit.get("timeline", [])]
    sequence: list[dict[str, Any]] = []
    for unit in (content_map or {}).get("units", []):
        if unit.get("decision") == "TRIM":
            continue
        coordinates = unit.get("editorial_output_coordinates")
        if not coordinates:
            continue
        output_start = _map_time(float(coordinates["start"]), speech_timeline)
        output_end = _map_time(float(coordinates["end"]), speech_timeline)
        if output_start is None or output_end is None or output_end <= output_start:
            continue
        narrative_function = str(unit.get("narrative_function", "POINT"))
        sequence.append({
            "id": unit.get("id"), "output_start": output_start, "output_end": output_end,
            "editorial_start": coordinates["start"], "editorial_end": coordinates["end"],
            "text": unit.get("text", ""), "narrative_function": narrative_function,
            "editorial_decision": unit.get("decision", "KEEP"),
            "broll_eligible": narrative_function in {"EXAMPLE", "EVIDENCE", "POINT", "CONTRAST"},
        })
    return {
        "version": 1, "layer": "TIMELINE_CONSTRUCTION",
        "principle": "sequence and duration only; no typography, camera, animation, or effect decisions",
        "output_duration": speech_edit.get("output_duration", 0),
        "speech_timeline": speech_timeline, "sequence": sequence,
        "broll_slots": [
            {"segment_id": item["id"], "start": item["output_start"], "end": item["output_end"], "reason": item["narrative_function"]}
            for item in sequence if item["broll_eligible"]
        ],
        "summary": {
            "segments": len(sequence),
            "broll_eligible_segments": sum(bool(item["broll_eligible"]) for item in sequence),
        },
    }
