from __future__ import annotations

from html import escape
import json
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _time(item: dict[str, Any]) -> float:
    return float(item.get("time", item.get("start", item.get("from", 0.0))))


def _overlaps(item: dict[str, Any], start: float, end: float) -> bool:
    item_start = _time(item)
    item_end = float(item.get("end", item.get("to", item_start + float(item.get("duration", 0.0)))))
    return item_start < end + 0.001 and item_end >= start - 0.001


def _matching(items: list[dict[str, Any]], segment: dict[str, Any]) -> list[dict[str, Any]]:
    segment_id = segment.get("id")
    direct = [item for item in items if segment_id and item.get("segment_id") == segment_id]
    if direct:
        return direct
    start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
    return [item for item in items if _overlaps(item, start, end)]


def _action_summary(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]] | str:
    if not items:
        return "NONE"
    result: list[dict[str, Any]] = []
    for item in items:
        row = {key: item[key] for key in keys if key in item}
        if "reason" in item:
            row["reason"] = item["reason"]
        row["enabled"] = item.get("enabled", True)
        result.append(row)
    return result


def build_director_debug(artifacts: Path, *, job_id: str, final_video: Path | None = None) -> dict[str, Any]:
    director = _read(artifacts / "director_plan.json")
    execution = _read(artifacts / "director_execution_plan.json")
    quality = _read(artifacts / "quality_report.json")
    style = _read(artifacts / "director_style.json")
    text_actions = list(execution.get("text_actions", []))
    camera_actions = list(execution.get("camera_actions", []))
    broll_actions = list(execution.get("broll_actions", []))
    broll_requests = list(execution.get("broll_requests", []))
    visual_actions = list(execution.get("visual_actions", []))
    audio_actions = list(execution.get("audio_actions", []))
    warnings = quality.get("metrics", {}).get("visual_penalties", {})
    timeline: list[dict[str, Any]] = []
    for segment in director.get("segments", []):
        text = _matching(text_actions, segment)
        camera = _matching(camera_actions, segment)
        broll = _matching(broll_actions, segment)
        requests = _matching(broll_requests, segment)
        visual = _matching(visual_actions, segment)
        audio = _matching(audio_actions, segment)
        selected_assets = sorted({
            str(shot.get("file"))
            for event in broll for shot in event.get("shots", [event]) if shot.get("file")
        })
        rejected = [request for request in requests if not request.get("enabled", request.get("resolved", False))]
        timeline.append({
            "segment_id": segment.get("id"),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": segment.get("text", ""),
            "semantic_type": segment.get("type", "NONE"),
            "importance": segment.get("importance"),
            "decision_strength": segment.get("decision_strength"),
            "hook_strength": segment.get("hook_strength"),
            "emotional_intensity": segment.get("emotional_intensity"),
            "information_value": segment.get("information_value"),
            "visual_importance": segment.get("visual_importance"),
            "retention_reason": segment.get("retention_reason") or "NONE",
            "text_decision": _action_summary(text, ("start", "end", "scene_type", "template", "animation", "layout")),
            "camera_decision": _action_summary(camera, ("time", "duration", "effect", "scale", "strength", "return_to_baseline")),
            "visual_decision": _action_summary(visual, ("time", "duration", "type", "intensity")),
            "sfx_decision": _action_summary(audio, ("time", "type", "file")),
            "broll_decision": "EXECUTED" if broll else "SKIPPED",
            "broll_necessity": segment.get("broll_necessity", segment.get("visual_importance")),
            "broll_actions": _action_summary(broll, ("from", "to", "category", "query", "brollNecessity")),
            "selected_assets": selected_assets or "NONE",
            "asset_skip_reason": (
                [item.get("reason", item.get("skip_reason", "SKIPPED")) for item in rejected]
                if rejected else ("NONE" if broll else "SKIPPED: no executed B-roll action")
            ),
            "layout_face_avoidance": [item.get("layout", "NONE") for item in text] or "NONE",
            "quality_warnings": {key: value for key, value in warnings.items() if value} or "NONE",
        })
    return {
        "version": 1,
        "job_id": job_id,
        "source": "existing Director/Execution/Quality artifacts; no second analysis",
        "profile": style.get("profile", director.get("profile", "NONE")),
        "style_confidence": style.get("confidence"),
        "style_reason": style.get("reason", "NONE"),
        "final_video": str(final_video.resolve()) if final_video and final_video.exists() else None,
        "timeline": timeline,
    }


def write_debug_inspector(debug: dict[str, Any], json_path: Path, html_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = []
    for item in debug.get("timeline", []):
        rows.append("<tr>" + "".join(
            f"<td>{escape(str(value))}</td>" for value in (
                f"{item.get('start', 0):.2f}–{item.get('end', 0):.2f}", item.get("semantic_type"),
                item.get("text"), item.get("decision_strength"), item.get("camera_decision"),
                item.get("broll_decision"), item.get("selected_assets"), item.get("retention_reason"),
            )
        ) + "</tr>")
    video = debug.get("final_video")
    video_tag = f'<video controls preload="metadata" src="{Path(video).as_uri()}"></video>' if video else "<p>MP4 not rendered (preview/debug data only).</p>"
    document = f"""<!doctype html><html><head><meta charset="utf-8"><title>ShortsAI Director Inspector</title>
<style>body{{font:14px Segoe UI,sans-serif;background:#111;color:#eee;margin:24px}}video{{width:320px;max-height:570px;background:#000}}table{{border-collapse:collapse;width:100%;margin-top:20px}}th,td{{border:1px solid #444;padding:7px;vertical-align:top}}th{{position:sticky;top:0;background:#292929}}td:nth-child(3){{min-width:250px}}code{{color:#ffd000}}</style></head>
<body><h1>Director Inspector — {escape(str(debug.get('job_id')))}</h1><p>Profile: <code>{escape(str(debug.get('profile')))}</code>, confidence: {escape(str(debug.get('style_confidence')))}</p>{video_tag}
<table><thead><tr><th>Time</th><th>Type</th><th>Text</th><th>Strength</th><th>Camera</th><th>B-roll</th><th>Asset</th><th>Reason</th></tr></thead><tbody>{''.join(rows)}</tbody></table></body></html>"""
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(document, encoding="utf-8")
