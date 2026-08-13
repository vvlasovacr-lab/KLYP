from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _rect_overlap(left: dict[str, float], right: dict[str, float]) -> float:
    x1, y1 = max(left["x"], right["x"]), max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1) / max(0.001, min(left["w"] * left["h"], right["w"] * right["h"]))


def _text_rect(scene: dict[str, Any]) -> dict[str, float]:
    measured = scene.get("layout", {}).get("compositionSafety", {}).get("bounding_box")
    if measured:
        return {key: float(measured[key]) for key in ("x", "y", "w", "h")}
    position = str(scene.get("layout", {}).get("position", "lower"))
    values = {
        "lower": {"x": 0.08, "y": 0.58, "w": 0.84, "h": 0.22},
        "center_lower": {"x": 0.08, "y": 0.48, "w": 0.84, "h": 0.30},
        "top": {"x": 0.08, "y": 0.08, "w": 0.84, "h": 0.20},
        "side_left": {"x": 0.04, "y": 0.34, "w": 0.40, "h": 0.34},
        "side_right": {"x": 0.56, "y": 0.34, "w": 0.40, "h": 0.34},
    }
    return values.get(position, values["lower"])


def _face_overlap(scenes: list[dict[str, Any]], face: dict[str, Any]) -> tuple[float, int]:
    if not face.get("detected") or not scenes:
        return 1.0, 0
    average = face.get("averageFace", {})
    face_rect = {
        "x": float(average.get("x", 0.5)) - float(average.get("w", 0.2)) / 2,
        "y": float(average.get("y", 0.35)) - float(average.get("h", 0.18)) / 2,
        "w": float(average.get("w", 0.2)), "h": float(average.get("h", 0.18)),
    }
    risks = sum(_rect_overlap(_text_rect(scene), face_rect) > 0.12 for scene in scenes)
    return _clamp(1.0 - risks / max(1, len(scenes)) * 2.2), risks


def _readability(scenes: list[dict[str, Any]]) -> tuple[float, list[dict[str, Any]]]:
    penalties = 0.0
    issues: list[dict[str, Any]] = []
    for scene in scenes:
        words = scene.get("words", [])
        count = len(words) or len(str(scene.get("text", "")).split())
        duration = max(0.1, float(scene.get("end", 0)) - float(scene.get("start", 0)))
        reading_rate = count / duration
        max_words = 6 if str(scene.get("type", "NORMAL")).upper() in {"HERO", "HOOK"} else 5
        penalty = max(0, count - max_words) * 0.10 + max(0.0, reading_rate - 5.2) * 0.05
        if penalty > 0:
            issues.append({"start": scene.get("start"), "text": scene.get("text"), "words": count, "wordsPerSecond": round(reading_rate, 2)})
        penalties += min(0.45, penalty)
    return _clamp(1.0 - penalties / max(1, len(scenes))), issues[:8]


def build_rendered_frame_qc(
    video: Path, montage_plan: dict[str, Any], preview_dir: Path | None = None,
) -> dict[str, Any]:
    """Sample the encoded result using local pixel/geometry evidence.

    This intentionally avoids a new external vision dependency. It verifies
    sharpness, local text-region contrast, planned final geometry and face
    overlap at the moments most likely to expose editorial/layout failures.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return {"available": False, "reason": "opencv unavailable", "samples": [], "warnings": []}
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return {"available": False, "reason": "render cannot be opened", "samples": [], "warnings": ["bad_transition_frame"]}
    duration = max(0.1, float(montage_plan.get("output", {}).get("duration", 0.0)))
    scenes = [item for item in montage_plan.get("scenes", []) if item.get("enabled", True)]
    broll = [item for item in montage_plan.get("broll", []) if item.get("enabled", True)]
    targets: list[tuple[float, str]] = [(min(duration - 0.02, value), "opening") for value in (0.18, 1.0, 2.0) if value < duration]
    for scene in scenes:
        role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
        position = str(scene.get("layout", {}).get("position", "lower"))
        if role in {"HOOK", "HERO", "NUMBER", "PUNCH"} or position.startswith("side_"):
            start, end = float(scene.get("start", 0)), float(scene.get("end", 0))
            motion_duration = float(scene.get("executionAction", {}).get("motion", {}).get("duration", 0.22))
            peak = min(end - 0.03, start + max(0.06, motion_duration * 0.58))
            targets.append((peak, f"typography_peak_{role.lower()}"))
            # Inspect the settled composition, not a legitimate word-build
            # frame where later words have not appeared yet.
            settled = min(end - 0.08, max(start + 0.28, end - 0.22))
            targets.append((settled, f"typography_{role.lower()}"))
        longest_word = max((len(str(word.get("word", "")).strip(".,!?;:—-")) for word in scene.get("words", [])), default=0)
        if longest_word >= 11:
            start, end = float(scene.get("start", 0)), float(scene.get("end", 0))
            targets.append((min(end - 0.03, start + 0.14), "typography_long_word_peak"))
    for event in broll:
        start, end = float(event.get("from", 0)), float(event.get("to", 0))
        targets.extend([
            (max(0.0, start - 0.06), "broll_transition_in"),
            (min(duration - 0.02, start + max(0.08, (end - start) * 0.50)), "broll_active"),
            (min(duration - 0.02, end + 0.06), "broll_transition_out"),
        ])
    for action in montage_plan.get("editorialQuality", {}).get("editorial_internal_actions", []):
        if action.get("type") not in {"TRIM", "REPLACE_TAKE", "REVIEW_REQUIRED"}:
            continue
        output = action.get("final_output_coordinates") or action.get("output_coordinates") or {}
        targets.append((max(0.0, float(output.get("start", 0)) - 0.04), f"editorial_{str(action.get('type')).lower()}"))
        targets.append((min(duration - 0.02, float(output.get("end", output.get("start", 0))) + 0.04), f"editorial_{str(action.get('type')).lower()}"))
    unique: list[tuple[float, str]] = []
    for timestamp, reason in sorted(targets):
        timestamp = max(0.0, min(duration - 0.02, timestamp))
        if any(abs(timestamp - existing[0]) < 0.08 and reason == existing[1] for existing in unique):
            continue
        unique.append((timestamp, reason))
    unique = unique[:40]
    if preview_dir:
        preview_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, (timestamp, reason) in enumerate(unique):
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = capture.read()
        if not ok:
            samples.append({"time": round(timestamp, 3), "reason": reason, "decoded": False})
            warnings.append("bad_transition_frame")
            continue
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_value = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        frame_contrast = float(gray.std()) / 64.0
        active = [scene for scene in scenes if float(scene.get("start", 0)) <= timestamp <= float(scene.get("end", 0))]
        text_metrics: list[dict[str, Any]] = []
        for scene in active:
            safety = scene.get("layout", {}).get("compositionSafety", {})
            box = safety.get("bounding_box")
            if not box:
                continue
            x1 = max(0, min(width - 1, round(float(box["x"]) * width)))
            y1 = max(0, min(height - 1, round(float(box["y"]) * height)))
            x2 = max(x1 + 1, min(width, round((float(box["x"]) + float(box["w"])) * width)))
            y2 = max(y1 + 1, min(height, round((float(box["y"]) + float(box["h"])) * height)))
            roi = gray[y1:y2, x1:x2]
            if roi.size:
                low, high = (float(value) for value in __import__("numpy").percentile(roi, [8, 92]))
                local_contrast = _clamp((high - low) / 150.0)
            else:
                local_contrast = 0.0
            text_metrics.append({
                "text": scene.get("text", ""), "role": scene.get("semanticRole", scene.get("type")),
                "local_contrast": local_contrast,
                "readability_score": safety.get("readability_score"),
                "edge_proximity_px": safety.get("edge_proximity"),
                "violations": safety.get("violations_after", []),
            })
            if local_contrast < 0.30 and reason.startswith("typography_"):
                warnings.append("poor_text_contrast")
        preview = None
        if preview_dir:
            preview_path = preview_dir / f"{index + 1:02d}_{timestamp:07.3f}_{reason}.jpg"
            cv2.imwrite(str(preview_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            preview = str(preview_path.resolve())
        sample = {
            "time": round(timestamp, 3), "reason": reason, "decoded": True,
            "width": width, "height": height, "blur": round(blur_value, 2),
            "frame_contrast": round(min(1.0, frame_contrast), 3),
            "active_text": text_metrics, "preview": preview,
        }
        if blur_value < 18.0 and reason.startswith(("opening", "editorial_", "broll_transition")):
            sample["transition_frame_risk"] = True
            warnings.append("bad_transition_frame")
        samples.append(sample)
    capture.release()
    decoded = sum(bool(item.get("decoded")) for item in samples)
    text_values = [
        float(text["local_contrast"])
        for item in samples if str(item.get("reason", "")).startswith("typography_")
        for text in item.get("active_text", [])
    ]
    return {
        "available": True, "method": "opencv_post_render_sampling_v1",
        "video": str(video.resolve()), "samples": samples,
        "summary": {
            "requested": len(samples), "decoded": decoded,
            "decode_rate": round(decoded / max(1, len(samples)), 3),
            "average_text_region_contrast": round(sum(text_values) / max(1, len(text_values)), 3),
            "low_contrast_text_frames": sum(value < 0.30 for value in text_values),
            "transition_frame_risks": sum(bool(item.get("transition_frame_risk")) for item in samples),
        },
        "warnings": sorted(set(warnings)),
    }


def _merge_intervals(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    values = sorted((max(0.0, start), min(duration, end)) for start, end in intervals if end > start)
    merged: list[tuple[float, float]] = []
    for start, end in values:
        if merged and start <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _calm_intervals(intervals: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in _merge_intervals(intervals, duration):
        if start - cursor >= 0.8:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= 0.8:
        result.append((cursor, duration))
    return result


def _visual_polish_metrics(
    scenes: list[dict[str, Any]], camera: list[dict[str, Any]], visual: list[dict[str, Any]],
    broll: list[dict[str, Any]], strong: list[dict[str, Any]], sfx: list[dict[str, Any]], duration: float,
) -> dict[str, Any]:
    end_zone_start = max(0.0, duration - max(3.5, min(6.0, duration * 0.10)))
    local_relevances = [
        float(event.get("brollNecessity", {}).get(
            "local_semantic_relevance",
            event.get("selectionDiagnostics", {}).get("localRelevance", 0.0),
        ))
        for event in broll
    ]
    broll_local_relevance = round(sum(local_relevances) / max(1, len(local_relevances)), 3)
    broll_intervals = sorted(
        (float(event.get("from", 0)), float(event.get("to", event.get("from", 0))))
        for event in broll
    )
    broll_coverage = sum(max(0.0, end - start) for start, end in _merge_intervals(broll_intervals, duration)) / max(0.1, duration)
    short_gaps = sum(right[0] - left[1] < 6.0 for left, right in zip(broll_intervals, broll_intervals[1:]))
    expected_max_events = max(1, min(6, round(duration / 10.0)))
    broll_overuse = int(broll_coverage > 0.14) + short_gaps + int(len(broll) > expected_max_events)
    used_assets = [str(shot.get("assetId", shot.get("file", ""))) for event in broll for shot in event.get("shots", [])]
    broll_repetition = max(0, len(used_assets) - len(set(used_assets)))
    broll_near_hook = sum(float(event.get("from", 0)) < 3.0 for event in broll)
    strong_intervals = [
        (float(scene.get("start", 0)), float(scene.get("end", scene.get("start", 0))))
        for scene in strong
    ]
    broll_blocks_strong_text = sum(
        any(start < strong_end and end > strong_start for strong_start, strong_end in strong_intervals)
        for start, end in broll_intervals
    )
    broll_text_mismatch = sum(
        float(event.get("brollNecessity", {}).get("local_semantic_relevance", 1.0)) < 0.45
        for event in broll
    )
    end_zone_broll = sum(
        float(event.get("from", 0)) >= end_zone_start
        and float(event.get("brollNecessity", {}).get("local_semantic_relevance", 0.0)) < 0.84
        for event in broll
    )
    awkward_side_layout = 0
    vertical_text_stack = 0
    text_near_edge = 0
    unbalanced_side_layout = 0
    narrow_text_column = 0
    face_text_collision = 0
    safe_area_violation = 0
    text_edge_violation = 0
    animation_edge_violation = 0
    body_text_too_small = 0
    stroke_too_heavy = 0
    body_text_unreadable = 0
    excessive_line_count = 0
    excessive_font_weight = 0
    readability_values: list[float] = []
    for scene in scenes:
        layout = scene.get("layout", {})
        safety = layout.get("compositionSafety", {})
        violations = set(safety.get("violations_after", safety.get("violations", [])))
        if float(safety.get("edge_proximity", 1000)) < 20: text_near_edge += 1
        if "safe_area_violation" in violations: safe_area_violation += 1
        if "text_edge_violation" in violations: text_edge_violation += 1
        if "animation_edge_violation" in violations: animation_edge_violation += 1
        if "body_text_too_small" in violations: body_text_too_small += 1
        if "stroke_too_heavy" in violations: stroke_too_heavy += 1
        if "body_text_unreadable" in violations: body_text_unreadable += 1
        if "excessive_line_count" in violations: excessive_line_count += 1
        profile_name = str(safety.get("font_profile", "body"))
        weight = int(safety.get("font_weight", 800) or 800)
        if weight > (920 if profile_name == "display" else 820): excessive_font_weight += 1
        if safety.get("readability_score") is not None:
            readability_values.append(float(safety["readability_score"]))
        if "narrow_text_column" in violations: narrow_text_column += 1
        if "face_text_collision" in violations or float(safety.get("face_overlap", 0)) > 0.10: face_text_collision += 1
        if str(layout.get("position", "lower")) not in {"side_left", "side_right"}:
            continue
        if float(safety.get("layout_balance", 1.0)) < 0.34: unbalanced_side_layout += 1
        side = layout.get("side_layout", layout.get("sideLayout", {}))
        words = len(scene.get("words", [])) or len(str(scene.get("text", "")).split())
        estimated_lines = int(side.get("estimated_lines", side.get("estimatedLines", 0)) or 0)
        available = float(side.get("available_width", side.get("availableWidth", 1.0)) or 0)
        if side.get("valid") is False or words > 4 or available < 0.31:
            awkward_side_layout += 1
        if estimated_lines > 2:
            vertical_text_stack += 1

    repeated_composition = 0
    maximum_composition_run = 0
    previous: tuple[str, str, str] | None = None
    run = 0
    for scene in sorted(scenes, key=lambda item: float(item.get("start", 0))):
        signature = (
            str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper(),
            str(scene.get("template", "PHRASE_BUILD")).upper(),
            str(scene.get("layout", {}).get("position", "lower")),
        )
        run = run + 1 if signature == previous else 1
        previous = signature
        maximum_composition_run = max(maximum_composition_run, run)
        if run > 6:
            repeated_composition += 1

    effect_times = sorted([
        *(float(event.get("time", 0)) for event in camera),
        *(float(event.get("time", 0)) for event in visual),
        *(float(event.get("from", 0)) for event in broll),
        *(float(scene.get("start", 0)) for scene in strong),
    ])
    maximum_effects_in_two_seconds = max(
        (sum(timestamp <= other < timestamp + 2.0 for other in effect_times) for timestamp in effect_times),
        default=0,
    )
    strong_camera = [item for item in camera if str(item.get("effect", "")).upper() == "PUNCH_ZOOM" or float(item.get("strength", 0)) >= 0.72]
    camera_overactivity = max(0, len(camera) - max(2, round(duration / 3.5))) + max(0, len(strong_camera) - max(1, round(duration / 9.0)))
    effect_overactivity = max(0, len(visual) - max(1, round(duration / 8.0)))
    sfx_overactivity = max(0, len(sfx) - max(2, round(duration / 5.0)))
    sorted_sfx = sorted(sfx, key=lambda item: float(item.get("time", 0)))
    sfx_overactivity += sum(
        str(right.get("type")) == str(left.get("type")) and float(right.get("time", 0)) - float(left.get("time", 0)) < 2.0
        for left, right in zip(sorted_sfx, sorted_sfx[1:])
    )
    return {
        "broll_local_relevance": broll_local_relevance,
        "broll_mismatch": broll_text_mismatch,
        "broll_overuse": broll_overuse,
        "broll_coverage": round(broll_coverage, 4),
        "broll_repetition": broll_repetition,
        "broll_near_hook": broll_near_hook,
        "broll_in_cta_zone": end_zone_broll,
        "broll_blocks_strong_text": broll_blocks_strong_text,
        "broll_text_mismatch": broll_text_mismatch,
        "end_zone_broll": end_zone_broll,
        "awkward_side_layout": awkward_side_layout,
        "vertical_text_stack": vertical_text_stack,
        "text_near_edge": text_near_edge,
        "unbalanced_side_layout": unbalanced_side_layout,
        "narrow_text_column": narrow_text_column,
        "safe_area_violation": safe_area_violation,
        "face_text_collision": face_text_collision,
        "text_edge_violation": text_edge_violation,
        "animation_edge_violation": animation_edge_violation,
        "body_text_too_small": body_text_too_small,
        "stroke_too_heavy": stroke_too_heavy,
        "body_text_unreadable": body_text_unreadable,
        "excessive_line_count": excessive_line_count,
        "excessive_font_weight": excessive_font_weight,
        "typography_readability": round(sum(readability_values) / max(1, len(readability_values)), 3),
        "repeated_composition": repeated_composition,
        "maximum_composition_run": maximum_composition_run,
        "effect_overdensity": max(0, maximum_effects_in_two_seconds - 4),
        "maximum_effects_in_two_seconds": maximum_effects_in_two_seconds,
        "camera_overactivity": camera_overactivity,
        "strong_camera_events": len(strong_camera),
        "effect_overactivity": effect_overactivity,
        "sfx_overactivity": sfx_overactivity,
    }


def build_quality_report(
    montage_plan: dict[str, Any],
    audio_measurement: dict[str, Any] | None = None,
    *,
    finalized: bool,
    rendered_frame_qc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    duration = max(0.1, float(montage_plan.get("output", {}).get("duration", 0)))
    all_scenes = list(montage_plan.get("scenes", []))
    scenes = [scene for scene in all_scenes if scene.get("enabled", True)]
    strong = [scene for scene in scenes if scene.get("semanticRole", scene.get("type")) in {"HOOK", "HERO", "PUNCH", "NUMBER"}]
    camera = [event for event in montage_plan.get("camera", []) if event.get("enabled", True)]
    visual = [event for event in montage_plan.get("visual", []) if event.get("enabled", True)]
    broll = [event for event in montage_plan.get("broll", []) if event.get("enabled", True)]
    text_intervals = _merge_intervals([
        (float(scene.get("start", 0)), float(scene.get("end", scene.get("start", 0))))
        for scene in scenes
    ], duration)
    body_intervals = _merge_intervals([
        (float(scene.get("start", 0)), float(scene.get("end", scene.get("start", 0))))
        for scene in scenes
        if str(scene.get("captionState", "BODY_CAPTION")) in {"BODY_CAPTION", "REDUCED_CAPTION"}
    ], duration)
    strong_caption_intervals = _merge_intervals([
        (float(scene.get("start", 0)), float(scene.get("end", scene.get("start", 0))))
        for scene in scenes
        if str(scene.get("captionState", "")) == "STRONG_TYPOGRAPHY"
    ], duration)
    text_coverage = sum(end - start for start, end in text_intervals) / duration
    body_caption_coverage = sum(end - start for start, end in body_intervals) / duration
    strong_typography_coverage = sum(end - start for start, end in strong_caption_intervals) / duration
    speaker_only_text_coverage = max(0.0, 1.0 - text_coverage)
    caption_states = Counter(str(scene.get("captionState", "BODY_CAPTION")) for scene in all_scenes)
    camera_under_broll = sum(
        any(
            float(event.get("time", 0)) < float(insert.get("to", 0))
            and float(event.get("time", 0)) + float(event.get("duration", 0)) > float(insert.get("from", 0))
            for insert in broll
        )
        for event in camera
    )
    unreturned_camera = sum(abs(float(event.get("return_scale", 1.0)) - 1.0) > 0.001 for event in camera)
    overlapping_camera = sum(
        float(right.get("time", 0)) < float(left.get("time", 0)) + float(left.get("duration", 0))
        for left, right in zip(sorted(camera, key=lambda item: float(item.get("time", 0))), sorted(camera, key=lambda item: float(item.get("time", 0)))[1:])
    )
    content_format = str(
        montage_plan.get("director", {}).get("profile_decision", {}).get("metrics", {}).get("format", "unknown")
    ).lower()
    hook_scenes = [scene for scene in scenes if float(scene.get("start", 0)) < 3.0]
    hook_changes = sum(float(event.get("time", event.get("from", 99))) < 3.0 for event in [*camera, *visual, *broll])
    declared_hook = float(montage_plan.get("speechEdit", {}).get("hook", {}).get("score", 0))
    hook_strength = max((float(scene.get("importance", 0)) for scene in hook_scenes), default=0.0)
    hook_score = _clamp(declared_hook * 0.55 + min(1.0, hook_changes / 2.0) * 0.20 + min(1.0, len(hook_scenes) / 2.0) * 0.10 + hook_strength * 0.15)

    word_motion_times = [
        float(word.get("start", scene.get("start", 0)))
        for scene in scenes for word in scene.get("words", [])
        if word.get("effect") and float(word.get("intensity", 0)) >= 0.52
    ]
    change_times = sorted({
        0.0, duration,
        *(float(scene["start"]) for scene in strong),
        *(float(scene.get("end", scene["start"])) for scene in strong),
        *(float(event.get("time", 0)) for event in camera),
        *(float(event.get("time", 0)) + float(event.get("duration", 0)) for event in camera),
        *(float(event.get("time", 0)) for event in visual),
        *(float(event.get("time", 0)) + float(event.get("duration", 0)) for event in visual),
        *(float(event.get("from", 0)) for event in broll),
        *(float(event.get("to", event.get("from", 0))) for event in broll),
        *word_motion_times,
    })
    gaps = [right - left for left, right in zip(change_times, change_times[1:])]
    max_static_gap = max(gaps, default=duration)
    boring_intervals = [{"start": round(left, 3), "end": round(right, 3), "duration": round(right - left, 3)} for left, right in zip(change_times, change_times[1:]) if right - left > 5.5]
    cadence_score = _clamp(1.0 - max(0.0, max_static_gap - 6.0) / 8.0)
    change_rate = max(0, len(change_times) - 2) / duration
    density_score = _clamp(1.0 - max(0.0, 0.16 - change_rate) / 0.16 - max(0.0, change_rate - 0.78) / 0.55)
    ideal_strong = max(2.0, duration / 16.0)
    strong_score = _clamp(1.0 - abs(len(strong) - ideal_strong) / max(2.0, ideal_strong * 1.45))
    coverage = sum(max(0.0, float(event["to"]) - float(event["from"])) for event in broll) / duration
    if content_format == "talking_head":
        broll_score = (
            0.62 if not broll
            else _clamp(coverage / 0.04) if coverage < 0.04
            else 1.0 if coverage <= 0.12
            else _clamp(1.0 - (coverage - 0.12) / 0.12)
        )
    else:
        broll_score = _clamp(coverage / 0.14) if broll else 0.45
    readability_score, readability_issues = _readability(scenes)
    face_score, overlap_risks = _face_overlap(scenes, montage_plan.get("face", {}))
    busy_intervals = [
        *((float(event.get("from", 0)), float(event.get("to", event.get("from", 0)))) for event in broll),
        *((float(event.get("time", 0)), float(event.get("time", 0)) + float(event.get("duration", 0))) for event in camera),
        *((float(event.get("time", 0)), float(event.get("time", 0)) + float(event.get("duration", 0))) for event in visual),
        *((float(scene.get("start", 0)), float(scene.get("end", scene.get("start", 0)))) for scene in strong),
    ]
    speaker_only = _calm_intervals(busy_intervals, duration)
    calm_coverage = sum(end - start for start, end in speaker_only) / duration
    calm_score = _clamp(
        1.0 - max(0.0, 0.42 - calm_coverage) / 0.42
        - max(0.0, calm_coverage - 0.82) / 0.18
    )
    roles = {str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper() for scene in scenes}
    role_diversity_score = _clamp((len(roles) - 1) / 3.0)
    normal_ratio = sum(str(scene.get("type", "NORMAL")).upper() == "NORMAL" for scene in scenes) / max(1, len(scenes))
    strong_ratio = len(strong) / max(1, len(scenes))
    hierarchy_score = _clamp(
        1.0 - max(0.0, 0.50 - normal_ratio) / 0.40 - max(0.0, normal_ratio - 0.90) / 0.10
        - max(0.0, 0.03 - strong_ratio) / 0.03 - max(0.0, strong_ratio - 0.22) / 0.20
    )
    sfx = [event for event in montage_plan.get("sfx", []) if event.get("enabled", True)]
    polish = _visual_polish_metrics(scenes, camera, visual, broll, strong, sfx, duration)
    polish["visual_rest_balance"] = round(calm_score, 3)
    editorial = montage_plan.get("editorialQuality", {})
    content_map = editorial.get("content_map", {})
    content_summary = content_map.get("summary", {})
    content_structure = content_map.get("structure", {})
    editorial_warnings = set(editorial.get("warnings", []))
    weak_visual_start = float(editorial.get("start", {}).get("visual_readiness") or 1.0) < 0.56
    subject_not_ready = "SUBJECT_NOT_READY_AT_START" in editorial_warnings
    excessive_off_camera = "EXCESSIVE_OFF_CAMERA_START" in editorial_warnings
    weak_episode_tail = "WEAK_EPISODE_TAIL" in editorial_warnings
    weak_hook_visual = float(editorial.get("start", {}).get("strong_opening") or 1.0) < 0.62
    transition_frame_retained = "START_QUALITY_WARNING" in editorial_warnings
    internal_actions = editorial.get("editorial_internal_actions", [])
    poor_internal_performance = "poor_internal_performance" in editorial_warnings
    sustained_downward_gaze = "sustained_downward_gaze" in editorial_warnings
    weak_camera_engagement = "weak_camera_engagement" in editorial_warnings
    bad_transition_frame = "bad_transition_frame" in editorial_warnings
    review_required = sum(item.get("type") == "REVIEW_REQUIRED" for item in internal_actions)
    semantic_review_required = int(content_summary.get("review_required", 0))
    structure_score = _clamp(
        float(bool(content_structure.get("has_opening", True))) * 0.48
        + float(bool(content_structure.get("has_conclusion_or_cta", True))) * 0.42
        + min(0.10, len(set(content_structure.get("functions", []))) * 0.025)
    )
    content_score = _clamp(
        structure_score
        - min(0.42, semantic_review_required * 0.12)
        - ("semantic_duplicate_review_required" in editorial_warnings) * 0.10
    )
    rendered = rendered_frame_qc or {}
    rendered_warnings = set(rendered.get("warnings", []))
    rendered_summary = rendered.get("summary", {})
    rendered_penalty = _clamp(
        ("poor_text_contrast" in rendered_warnings) * 0.10
        + ("bad_transition_frame" in rendered_warnings) * 0.13
        + max(0.0, 1.0 - float(rendered_summary.get("decode_rate", 1.0))) * 0.35
    )
    editorial_penalty = _clamp(
        weak_visual_start * 0.22 + subject_not_ready * 0.20 + excessive_off_camera * 0.16
        + transition_frame_retained * 0.15 + weak_episode_tail * 0.12 + weak_hook_visual * 0.15
        + poor_internal_performance * 0.20 + sustained_downward_gaze * 0.14
        + weak_camera_engagement * 0.12 + bad_transition_frame * 0.12
        + min(0.20, review_required * 0.08)
        + min(0.24, semantic_review_required * 0.08)
    )
    font_selection = montage_plan.get("styleProfile", {}).get("fontSelection", {})
    font_fallbacks = int(font_selection.get("font_fallbacks", 0) or 0)
    font_fallback_penalty = min(0.30, font_fallbacks * 0.10)
    polish_penalty = _clamp(
        min(1.0, polish["broll_text_mismatch"] / max(1, len(broll))) * 0.24
        + min(1.0, polish["end_zone_broll"] / max(1, len(broll))) * 0.24
        + min(1.0, polish["broll_overuse"] / 3.0) * 0.16
        + min(1.0, polish["broll_repetition"] / max(1, len(broll))) * 0.14
        + min(1.0, polish["broll_near_hook"] / max(1, len(broll))) * 0.18
        + min(1.0, polish["broll_blocks_strong_text"] / max(1, len(broll))) * 0.20
        + min(1.0, polish["awkward_side_layout"] / max(1, len(scenes))) * 0.14
        + min(1.0, polish["vertical_text_stack"] / max(1, len(scenes))) * 0.12
        + min(1.0, polish["repeated_composition"] / max(1, len(scenes) * 0.35)) * 0.12
        + min(1.0, polish["effect_overdensity"] / 3.0) * 0.14
        + min(1.0, polish["text_near_edge"] / max(1, len(scenes))) * 0.16
        + min(1.0, polish["unbalanced_side_layout"] / max(1, len(scenes))) * 0.14
        + min(1.0, polish["narrow_text_column"] / max(1, len(scenes))) * 0.16
        + min(1.0, polish["safe_area_violation"] / max(1, len(scenes))) * 0.22
        + min(1.0, polish["face_text_collision"] / max(1, len(scenes))) * 0.22
        + min(1.0, polish["text_edge_violation"] / max(1, len(scenes))) * 0.22
        + min(1.0, polish["animation_edge_violation"] / max(1, len(scenes))) * 0.20
        + min(1.0, polish["body_text_too_small"] / max(1, len(scenes))) * 0.18
        + min(1.0, polish["stroke_too_heavy"] / max(1, len(scenes))) * 0.14
        + min(1.0, polish["body_text_unreadable"] / max(1, len(scenes))) * 0.22
        + min(1.0, polish["excessive_font_weight"] / max(1, len(scenes))) * 0.12
        + min(1.0, polish["camera_overactivity"] / 3.0) * 0.14
        + min(1.0, polish["effect_overactivity"] / 3.0) * 0.12
        + min(1.0, polish["sfx_overactivity"] / 3.0) * 0.10
        + editorial_penalty * 0.34
        + rendered_penalty * 0.35
        + font_fallback_penalty
    )
    polish_score = _clamp(1.0 - polish_penalty)
    visual_score = _clamp((
        cadence_score * 0.26 + density_score * 0.12 + strong_score * 0.13
        + broll_score * 0.12 + face_score * 0.15 + calm_score * 0.12 + role_diversity_score * 0.10
    ) - polish_penalty * 0.38)

    effects_per_second = (len(camera) + len(visual) + len(broll) + len(strong)) / duration
    effect_balance_score = _clamp(
        1.0 - max(0.0, 0.12 - effects_per_second) / 0.12
        - max(0.0, effects_per_second - 0.30) / 0.32
    )
    retention_score = _clamp(
        hook_score * 0.24 + cadence_score * 0.20 + readability_score * 0.17
        + effect_balance_score * 0.16 + broll_score * 0.08 + face_score * 0.07 + calm_score * 0.08
        - polish_penalty * 0.24
    )

    audio = audio_measurement or {}
    lufs, peak = audio.get("integratedLufs"), audio.get("truePeak")
    if lufs is None:
        audio_score = 0.72 if montage_plan.get("audio", {}).get("enabled") else 0.35
    else:
        loudness_score = _clamp(1.0 - abs(float(lufs) + 14.0) / 4.0)
        peak_score = 1.0 if peak is not None and float(peak) <= -1.0 else _clamp(1.0 - max(0.0, float(peak or 0) + 1.0) / 2.0)
        audio_score = _clamp(loudness_score * 0.72 + peak_score * 0.28)
    layout_penalty = min(0.35, (polish["awkward_side_layout"] + polish["vertical_text_stack"]) / max(1, len(scenes)) * 1.8)
    text_score = _clamp((
        readability_score * 0.55 + strong_score * 0.15
        + (0.10 if len({scene.get("template") for scene in scenes}) >= 3 else 0.0)
        + role_diversity_score * 0.10 + hierarchy_score * 0.10
    ) - layout_penalty)
    output = montage_plan.get("output", {})
    expected_geometry = (
        int(output.get("width", 0)) == 1080 and int(output.get("height", 0)) == 1920
        and float(output.get("fps", 0)) >= 29.0
    )
    decode_rate = float(rendered_summary.get("decode_rate", 1.0 if not finalized else 0.0))
    technical_score = _clamp(float(expected_geometry) * 0.72 + decode_rate * 0.28)
    camera_score = _clamp(
        1.0 - min(0.55, camera_under_broll * 0.28)
        - min(0.40, unreturned_camera * 0.20)
        - min(0.25, overlapping_camera * 0.08)
        - min(0.25, polish["camera_overactivity"] * 0.08)
    )
    overall_score = _clamp((
        content_score * 0.18 + hook_score * 0.12 + visual_score * 0.14 + retention_score * 0.16
        + audio_score * 0.13 + text_score * 0.10 + face_score * 0.05 + polish_score * 0.07
        + technical_score * 0.05
    ) - editorial_penalty * 0.18)
    recommendations: list[str] = []
    if hook_score < 0.68: recommendations.append("Первые 3 секунды недостаточно динамичны: усилить hook-композицию и первый смысловой удар.")
    if max_static_gap > 6.0: recommendations.append("После 15-й секунды есть длинный статичный участок: добавить смысловое движение камеры или релевантный B-roll.")
    if coverage < 0.05: recommendations.append("Мало релевантного B-roll: расширить локальную библиотеку по теме ролика.")
    if readability_score < 0.88: recommendations.append("Некоторые текстовые блоки читаются слишком быстро: сократить количество слов или увеличить экспозицию.")
    if font_fallbacks:
        recommendations.append("Project-local font fallback occurred; inspect requested/resolved role before release.")
    if overlap_risks: recommendations.append("Обнаружен риск перекрытия лица текстом: скорректировать safe-zone для указанных сцен.")
    if effect_balance_score < 0.62: recommendations.append("Перебалансировать эффекты: сохранить визуальные паузы между сильными событиями.")
    if finalized and lufs is not None and abs(float(lufs) + 14.0) > 1.0: recommendations.append("Повторно откалибровать финальную нормализацию громкости.")
    if polish["broll_text_mismatch"]:
        recommendations.append("B-roll does not match the local spoken phrase; global topic similarity is insufficient.")
    if polish["end_zone_broll"]:
        recommendations.append("B-roll intrudes into the final CTA zone; keep the speaker unless local relevance is exceptional.")
    if polish["broll_overuse"]:
        recommendations.append("B-roll density is excessive for talking-head pacing; preserve at least 6–8 seconds between inserts and stay below 14% coverage.")
    if polish["broll_repetition"]:
        recommendations.append("The same B-roll asset is reused too soon; choose a new local match or leave the speaker visible.")
    if polish["broll_near_hook"]:
        recommendations.append("B-roll competes with the opening hook; keep the first three seconds focused on the speaker and hook typography.")
    if polish["broll_blocks_strong_text"]:
        recommendations.append("B-roll overlaps a HOOK/HERO/NUMBER/PUNCH composition; cancel or defer the insert.")
    if polish["awkward_side_layout"] or polish["vertical_text_stack"]:
        recommendations.append("Side typography is not compact; use CENTER_LOWER or TOP_CAPTION fallback.")
    if polish["effect_overdensity"]:
        recommendations.append("Too many strong events occur inside a two-second window; add visual rest.")
    if weak_visual_start or subject_not_ready or excessive_off_camera:
        recommendations.append("Opening frame is editorially weak: use a visually ready take or preserve START_QUALITY_WARNING for review.")
    if weak_episode_tail:
        recommendations.append("Episode tail loses delivery readiness; tighten only at a speech-safe boundary.")
    if polish["text_near_edge"] or polish["safe_area_violation"]:
        recommendations.append("Rendered text bounding box approaches the frame edge; apply the symmetric safe-area fallback.")
    if polish["unbalanced_side_layout"] or polish["narrow_text_column"]:
        recommendations.append("Side composition is unbalanced or too narrow; fall back to CENTER_LOWER/TOP_CAPTION.")
    if polish["face_text_collision"]:
        recommendations.append("Measured text bounding box overlaps the face; move the complete composition, not only its anchor.")
    if poor_internal_performance or sustained_downward_gaze or weak_camera_engagement:
        recommendations.append("Internal delivery contains a sustained weak segment; use an equivalent take or review the speech-safe boundary manually.")
    if polish["body_text_too_small"] or polish["body_text_unreadable"]:
        recommendations.append("Body typography falls below the phone-legibility threshold; use a safer fallback instead of further shrinking.")
    if polish["stroke_too_heavy"]:
        recommendations.append("Stroke is too heavy relative to the final font size; use the configured proportional clamp.")
    if polish["camera_overactivity"]: recommendations.append("Camera activity is too dense; preserve CALM and explicit recovery intervals.")
    if polish["effect_overactivity"]: recommendations.append("Visual effects exceed the semantic-event budget; increase effect cooldown.")
    if polish["sfx_overactivity"]: recommendations.append("Sound effects repeat too frequently; enforce global and same-cue cooldowns.")
    if semantic_review_required:
        recommendations.append("Episode contains probable paraphrased arguments that require an editorial KEEP/TRIM decision before release.")
    if not content_structure.get("has_conclusion_or_cta", True):
        recommendations.append("Content map has no conclusion or CTA; review the selected episode boundary before visual polish.")
    if "poor_text_contrast" in rendered_warnings:
        recommendations.append("Post-render text-region contrast is weak in sampled frames; strengthen only the configured outline/shadow treatment.")
    warning_names = []
    if weak_visual_start: warning_names.append("weak_visual_start")
    if subject_not_ready: warning_names.append("subject_not_ready_at_start")
    if excessive_off_camera: warning_names.append("excessive_off_camera_start")
    if transition_frame_retained: warning_names.append("transition_frame_retained")
    if weak_episode_tail: warning_names.append("weak_episode_tail")
    if weak_hook_visual: warning_names.append("weak_hook_visual")
    for name in ("broll_mismatch", "broll_overuse", "broll_repetition", "broll_near_hook", "broll_in_cta_zone", "broll_blocks_strong_text", "text_near_edge", "unbalanced_side_layout", "narrow_text_column", "vertical_text_stack", "face_text_collision", "text_edge_violation", "animation_edge_violation", "body_text_too_small", "stroke_too_heavy", "body_text_unreadable", "excessive_line_count", "excessive_font_weight", "camera_overactivity", "effect_overactivity", "sfx_overactivity"):
        if polish.get(name): warning_names.append(name)
    if polish.get("repeated_composition"): warning_names.append("repeated_composition")
    if polish.get("effect_overdensity"): warning_names.append("effect_overdensity")
    warning_names.extend(name for name in (
        "poor_internal_performance", "sustained_downward_gaze", "weak_camera_engagement", "bad_transition_frame",
    ) if name in editorial_warnings or name in rendered_warnings)
    if "poor_text_contrast" in rendered_warnings: warning_names.append("poor_text_contrast")
    if semantic_review_required: warning_names.append("semantic_duplicate_review_required")
    if not content_structure.get("has_opening", True): warning_names.append("content_structure_missing_opening")
    if not content_structure.get("has_conclusion_or_cta", True): warning_names.append("content_structure_missing_close")
    if not expected_geometry: warning_names.append("technical_output_contract_failed")
    if font_fallbacks: warning_names.append("font_role_fallback")
    broll_requests = montage_plan.get("brollRequests", [])
    broll_decisions = {
        "executed": [
            {
                "from": event.get("from"), "to": event.get("to"), "reason": event.get("reason"),
                "local_relevance": event.get("brollNecessity", {}).get("local_semantic_relevance"),
                "insert_value": event.get("insertValue"),
                "assets": [shot.get("file") for shot in event.get("shots", [])],
            }
            for event in broll
        ],
        "rejected": [
            {
                "time": request.get("time"), "text": request.get("text"), "status": request.get("status"),
                "local_relevance": request.get("brollNecessity", {}).get("local_semantic_relevance"),
                "candidate": request.get("assetCandidate"), "decision_stages": request.get("decisionStages", {}),
            }
            for request in broll_requests if request.get("status") != "MATCHED"
        ],
        "speaker_only_intervals": [
            {"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)}
            for start, end in speaker_only
        ],
    }
    return {
        "version": 7, "status": "FINAL" if finalized else "PLANNED", "profile": montage_plan.get("styleProfile", {}).get("name"),
        "duration": round(duration, 3), "hook_score": hook_score, "visual_score": visual_score,
        "retention_score": retention_score, "readability_score": readability_score,
        "face_safety_score": face_score, "effect_balance_score": effect_balance_score,
        "audio_score": audio_score, "broll_score": broll_score, "text_score": text_score,
        "visual_polish_score": polish_score, "editorial_score": _clamp(1.0 - editorial_penalty),
        "content_score": content_score, "technical_score": technical_score,
        "quality_dimensions": {
            "CONTENT": content_score, "EDITORIAL": _clamp(1.0 - editorial_penalty),
            "TYPOGRAPHY": text_score, "VISUAL": visual_score, "BROLL": broll_score,
            "CAMERA": camera_score, "AUDIO": audio_score, "TECHNICAL": technical_score,
        },
        "overall_score": overall_score, "final_score": overall_score,
        "metrics": {"visual_changes": max(0, len(change_times) - 2), "word_motion_events": len(word_motion_times), "max_static_gap": round(max_static_gap, 3), "boring_intervals": boring_intervals, "strong_text_events": len(strong), "camera_events": len(camera), "camera_punch_events": sum(str(item.get("effect", "")).upper() == "PUNCH_ZOOM" for item in camera), "camera_under_broll": camera_under_broll, "unreturned_camera_events": unreturned_camera, "overlapping_camera_events": overlapping_camera, "visual_events": len(visual), "sfx_events": len(sfx), "broll_events": len(broll), "rejected_inserts": sum(str(item.get("status", "")).startswith("SKIPPED") for item in broll_requests), "broll_coverage": round(coverage, 4), "text_coverage": round(text_coverage, 4), "body_caption_coverage": round(body_caption_coverage, 4), "strong_typography_coverage": round(strong_typography_coverage, 4), "speaker_only_text_coverage": round(speaker_only_text_coverage, 4), "caption_states": dict(caption_states), "unique_text_roles": sorted(roles), "role_diversity_score": role_diversity_score, "hierarchy_score": hierarchy_score, "speaker_only_coverage": round(calm_coverage, 4), "visual_rest_coverage": round(calm_coverage, 4), "speaker_only_intervals": [{"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)} for start, end in speaker_only], "visual_rest_intervals": [{"start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3)} for start, end in speaker_only], "calm_score": calm_score, "face_overlap_risks": overlap_risks, "effects_per_second": round(effects_per_second, 3), "visual_penalties": polish, "polish_penalty": polish_penalty, "editorial_penalty": editorial_penalty, "rendered_penalty": rendered_penalty, "font_profile": font_selection.get("font_profile_id"), "font_variant": font_selection.get("variant_id"), "font_fallbacks": font_fallbacks, "font_fallback_penalty": font_fallback_penalty, "content_map": content_summary, "content_structure": content_structure, "internal_actions": {"trim": sum(item.get("type") == "TRIM" for item in internal_actions), "replace_take": sum(item.get("type") == "REPLACE_TAKE" for item in internal_actions), "review_required": review_required, "semantic_review_required": semantic_review_required}, "technical_contract": {"width": output.get("width"), "height": output.get("height"), "fps": output.get("fps"), "decode_rate": decode_rate}, "rendered_frame_qc": rendered_summary, "integrated_lufs": lufs, "true_peak_dbtp": peak},
        "warnings": sorted(set(warning_names)),
        "broll_decisions": broll_decisions,
        "readability_issues": readability_issues, "rendered_frame_qc": rendered,
        "recommendations": recommendations,
    }
