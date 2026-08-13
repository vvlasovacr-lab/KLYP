from __future__ import annotations

import copy
from hashlib import sha256
import json
import math
import statistics
from typing import Any, Iterable, Sequence


def _duration(intervals: Iterable[tuple[float, float]]) -> float:
    ordered = sorted((max(0.0, start), max(start, end)) for start, end in intervals)
    merged: list[list[float]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def _median(values: Sequence[float]) -> float:
    return round(statistics.median(values), 4) if values else 0.0


def production_metrics(plan: dict[str, Any], source_duration: float) -> dict[str, Any]:
    duration = float(plan.get("output", {}).get("duration") or plan.get("video", {}).get("duration") or source_duration)
    scenes = [item for item in plan.get("scenes", []) if item.get("enabled", True)]
    execution = plan.get("execution", {})
    camera = [item for item in execution.get("camera_actions", plan.get("camera", [])) if item.get("enabled", True)]
    broll = [item for item in execution.get("broll_actions", plan.get("broll", [])) if item.get("enabled", True)]
    visual = [item for item in execution.get("visual_actions", plan.get("visual", [])) if item.get("enabled", True)]
    sfx = [item for item in execution.get("audio_actions", plan.get("sfx", [])) if item.get("enabled", True)]
    text_intervals = [(float(item.get("start", 0)), float(item.get("end", 0))) for item in scenes]
    text_duration = _duration(text_intervals)
    roles: dict[str, int] = {}
    templates: list[str] = []
    words_per_scene = []
    for scene in scenes:
        role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
        roles[role] = roles.get(role, 0) + 1
        templates.append(str(scene.get("template", "NORMAL")))
        words_per_scene.append(len(str(scene.get("text", "")).split()))
    repeated = sum(templates[index] == templates[index - 1] for index in range(1, len(templates)))
    broll_duration = _duration((float(item.get("from", item.get("start", 0))), float(item.get("to", item.get("end", 0)))) for item in broll)
    strong_text = [(float(item.get("start", 0)), float(item.get("end", 0))) for item in scenes if str(item.get("semanticRole", item.get("type", "NORMAL"))).upper() in {"HOOK", "HERO", "PUNCH", "NUMBER"}]
    stimulation = strong_text + [(float(item.get("from", item.get("time", 0))), float(item.get("to", item.get("time", 0) + 0.5))) for item in broll]
    stimulation += [(float(item.get("time", 0)) - 0.2, float(item.get("time", 0)) + 0.5) for item in camera + visual]
    stimulated = min(duration, _duration(stimulation))
    strengths = [float(item.get("strength", item.get("intensity", 0.0))) for item in camera]
    timeline = plan.get("speechEdit", {}).get("timeline", [])
    retained = sum(max(0.0, float(item.get("sourceEnd", item.get("source_end", 0))) - float(item.get("sourceStart", item.get("source_start", 0)))) for item in timeline) if timeline else duration
    return {
        "final_duration": round(duration, 3), "retained_raw_coverage": round(retained / max(source_duration, 0.001), 3),
        "hook_start": min((float(item.get("start", 0)) for item in scenes if str(item.get("semanticRole", item.get("type", ""))).upper() == "HOOK"), default=None),
        "hook_duration": round(sum(end - start for start, end in strong_text if start < 3.5), 3),
        "first_visual_impact": min([float(item.get("start", 999)) for item in scenes if str(item.get("semanticRole", item.get("type", ""))).upper() in {"HOOK", "HERO", "PUNCH", "NUMBER"}] + [float(item.get("time", 999)) for item in camera + visual], default=None),
        "text_coverage": round(text_duration / max(duration, 0.001), 3), "text_free_coverage": round(max(0.0, 1 - text_duration / max(duration, 0.001)), 3),
        "median_words_per_scene": _median(words_per_scene), "maximum_words": max(words_per_scene, default=0),
        "hero_count": roles.get("HERO", 0), "number_count": roles.get("NUMBER", 0), "accent_count": roles.get("ACCENT", 0),
        "composition_diversity": len(set(templates)), "repeated_composition": repeated,
        "camera_count": len(camera), "camera_strength": round(statistics.mean(strengths), 3) if strengths else 0.0,
        "camera_recovery": sum(str(item.get("effect", item.get("type", ""))).upper() in {"RECOVERY", "RETURN_BASELINE", "BASELINE"} or abs(float(item.get("return_scale", 999)) - 1.0) < 0.001 for item in camera),
        "broll_count": len(broll), "broll_coverage": round(broll_duration / max(duration, 0.001), 3),
        "broll_duration": round(broll_duration / max(1, len(broll)), 3),
        "visual_rest": round(max(0.0, 1 - stimulated / max(duration, 0.001)), 3),
        "visual_effect_density": round(len(visual) / max(duration, 0.001), 3),
        "sfx_density": round(len(sfx) / max(duration, 0.001), 3),
        "average_cut_cadence": round(duration / max(1, len(plan.get("speechEdit", {}).get("cuts", []))), 3),
        "speaker_only_coverage": round(max(0.0, 1 - broll_duration / max(duration, 0.001)), 3),
        "scene_distribution": roles,
    }


def reference_metrics(analysis: dict[str, Any], alignment: dict[str, Any] | None, raw_duration: float | None) -> dict[str, Any]:
    typography = analysis["typography"]["summary"]
    camera = analysis["camera"]["summary"]
    broll = analysis["broll"]["summary"]
    cuts = analysis["cuts"]["summary"]
    duration = float(analysis.get("duration", 0) or max((item.get("end", 0) for item in analysis.get("composition_rhythm", [])), default=0))
    aligned = alignment.get("summary", {}) if alignment else {}
    first_text = min((item["start"] for item in analysis["typography"]["scenes"]), default=None)
    hook_scenes = [item for item in analysis["typography"]["scenes"] if item["start"] < 3.5]
    return {
        "final_duration": round(duration, 3),
        "retained_raw_coverage": aligned.get("raw_word_coverage") if raw_duration else None,
        "hook_start": 0.0, "hook_duration": round(max((item["end"] for item in hook_scenes), default=0.0), 3),
        "first_visual_impact": first_text,
        "text_coverage": typography["text_coverage"], "text_free_coverage": typography["text_free_coverage"],
        "median_words_per_scene": typography["median_words_per_scene"], "maximum_words": typography["maximum_words"],
        "hero_count": typography["hero_count"], "number_count": typography["number_count"], "accent_count": typography["accent_count"],
        "composition_diversity": len({item["role"] + ":" + item["position"] for item in analysis["typography"]["scenes"]}),
        "repeated_composition": sum(analysis["typography"]["scenes"][i]["role"] == analysis["typography"]["scenes"][i - 1]["role"] for i in range(1, len(analysis["typography"]["scenes"]))),
        "camera_count": camera["count"], "camera_strength": round(statistics.mean(abs(item.get("scale_delta", 0)) for item in analysis["camera"]["events"]), 3) if analysis["camera"]["events"] else 0.0,
        "camera_recovery": sum(item["effect"] == "RECOVERY" for item in analysis["camera"]["events"]),
        "broll_count": broll["count"], "broll_coverage": broll["coverage"], "broll_duration": broll["average_duration"],
        "visual_rest": analysis["visual_rest"]["summary"]["coverage"],
        "visual_effect_density": analysis["motion"]["summary"]["event_density"], "sfx_density": analysis["sfx"]["summary"]["event_density"],
        "average_cut_cadence": cuts["average_cadence"], "speaker_only_coverage": analysis["speaker"]["speaker_only_coverage"],
    }


def compare_metrics(reference: dict[str, Any], before: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = {
        "final_duration": 1.5, "text_coverage": 0.10, "text_free_coverage": 0.10, "median_words_per_scene": 1.0,
        "hero_count": 2, "accent_count": 3, "camera_count": 3, "camera_strength": 0.025, "broll_count": 2,
        "broll_coverage": 0.08, "broll_duration": 0.7, "visual_rest": 0.10, "visual_effect_density": 0.05,
        "sfx_density": 0.05, "speaker_only_coverage": 0.10, "repeated_composition": 5,
    }
    likely = {"text_coverage", "text_free_coverage", "median_words_per_scene", "visual_rest", "repeated_composition", "camera_count", "camera_strength", "broll_duration"}
    style = {"hero_count", "accent_count", "broll_count", "broll_coverage", "visual_effect_density", "sfx_density"}
    rows = []
    for metric, reference_value in reference.items():
        if metric not in before or not isinstance(reference_value, (int, float)) or not isinstance(before[metric], (int, float)):
            continue
        difference = round(float(before[metric]) - float(reference_value), 4)
        significant = abs(difference) >= thresholds.get(metric, max(0.1, abs(float(reference_value)) * 0.3))
        if not significant:
            classification, confidence = "STYLE_DIFFERENCE", 0.56
        elif metric in likely:
            classification, confidence = "LIKELY_IMPROVEMENT", 0.72
        elif metric in style:
            classification, confidence = "STYLE_DIFFERENCE", 0.63
        else:
            classification, confidence = "INSUFFICIENT_EVIDENCE", 0.48
        rows.append({
            "metric": metric, "reference": reference_value, "shortsai_before": before[metric], "difference_before_minus_reference": difference,
            "classification": classification, "confidence": confidence, "significant": significant,
        })
    return rows


def build_calibration_candidate(
    comparisons: list[dict[str, Any]], reference: dict[str, Any], before: dict[str, Any],
    *, raw_pair_count: int, visual_reference_count: int,
) -> dict[str, Any]:
    suggestions = []
    mapping = {
        "text_coverage": ("Caption Engine", "target_text_coverage", "Increase intentional speaker-only space"),
        "median_words_per_scene": ("Caption Engine", "target_words_per_scene", "Match readable phrase density"),
        "hero_count": ("Visual Director", "hero_frequency_target", "Strengthen semantic hierarchy"),
        "repeated_composition": ("Typography", "composition_cooldown", "Reduce repeated layouts"),
        "camera_count": ("Camera", "camera_event_target", "Keep semantic camera movement intentional"),
        "camera_strength": ("Camera", "camera_strength_target", "Calibrate push intensity"),
        "broll_coverage": ("B-roll", "broll_coverage_target", "Calibrate visual replacement"),
        "broll_duration": ("B-roll", "broll_duration_target", "Keep inserts concise"),
        "visual_rest": ("Visual Director", "visual_rest_target", "Alternate stimulation and rest"),
        "visual_effect_density": ("Motion", "effect_density_target", "Remove effects without semantic need"),
    }
    parameters: dict[str, Any] = {}
    for row in comparisons:
        if row["metric"] not in mapping or row["classification"] != "LIKELY_IMPROVEMENT" or not row["significant"]:
            continue
        layer, parameter, benefit = mapping[row["metric"]]
        reference_value, current = float(row["reference"]), float(row["shortsai_before"])
        candidate = round(current * 0.65 + reference_value * 0.35, 4)
        parameters[parameter] = candidate
        can_execute = row["metric"] in {"text_coverage", "median_words_per_scene", "camera_strength", "broll_duration"} and not (row["metric"] == "broll_duration" and current <= 0)
        suggestions.append({
            "metric": row["metric"], "evidence": {"reference": reference_value, "current": current},
            "sample_count": 1, "confidence": min(0.74, row["confidence"]), "affected_layer": layer,
            "proposed_universal_change": f"Move {parameter} conservatively toward {candidate}",
            "expected_benefit": benefit, "overfitting_risk": "HIGH" if raw_pair_count < 3 else "MEDIUM",
            "status": "SAFE_FOR_ISOLATED_CANDIDATE" if can_execute else "NEEDS_MORE_PAIRS",
        })
    return {
        "version": 1, "mode": "ISOLATED_REFERENCE_CANDIDATE", "production_applied": False,
        "evidence": {"raw_to_final_pairs": raw_pair_count, "visual_references": visual_reference_count},
        "promotion_guard": {"minimum_raw_pairs": 3, "current_raw_pairs": raw_pair_count, "allowed": raw_pair_count >= 3, "reason": "At least three RAW→FINAL pairs and holdout validation are required"},
        "parameters": parameters, "suggestions": suggestions,
        "candidate_id": sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()[:12],
    }


def apply_candidate(plan: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply only bounded existing-system parameter changes to a copied plan."""
    result = copy.deepcopy(plan)
    params = candidate.get("parameters", {})
    changes: list[dict[str, Any]] = []
    duration = float(result.get("output", {}).get("duration", 0))
    scenes = [scene for scene in result.get("scenes", []) if scene.get("enabled", True)]
    current_coverage = _duration((float(s.get("start", 0)), float(s.get("end", 0))) for s in scenes) / max(duration, 0.001)
    target_coverage = float(params.get("target_text_coverage", current_coverage))
    if target_coverage < current_coverage - 0.03:
        removable = sorted(
            (scene for scene in scenes if str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper() == "NORMAL"),
            key=lambda scene: (float(scene.get("importance", scene.get("executionAction", {}).get("importance", 0.5))), float(scene.get("start", 0))),
        )
        remove_need = (current_coverage - target_coverage) * duration
        removed = 0.0
        for scene in removable:
            if removed >= remove_need:
                break
            scene["enabled"] = False
            removed += max(0.0, float(scene.get("end", 0)) - float(scene.get("start", 0)))
            changes.append({"type": "TEXT_REST", "start": scene.get("start"), "reason": "candidate target_text_coverage"})
    target_words = float(params.get("target_words_per_scene", 0.0))
    if target_words > 3.2:
        maximum_words = max(4, min(6, math.ceil(target_words)))
        merged_scenes: list[dict[str, Any]] = []
        for scene in result.get("scenes", []):
            previous = merged_scenes[-1] if merged_scenes else None
            role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
            previous_role = str(previous.get("semanticRole", previous.get("type", "NORMAL"))).upper() if previous else None
            same_segment = previous and previous.get("executionAction", {}).get("segment_id") == scene.get("executionAction", {}).get("segment_id")
            combined_words = len(previous.get("words", [])) + len(scene.get("words", [])) if previous else 999
            close = previous and float(scene.get("start", 0)) - float(previous.get("end", 0)) <= 0.24
            if previous and role == previous_role == "NORMAL" and same_segment and close and combined_words <= maximum_words:
                previous["end"] = scene.get("end")
                previous["text"] = f"{previous.get('text', '')} {scene.get('text', '')}".strip()
                previous["words"] = list(previous.get("words", [])) + list(scene.get("words", []))
                action = previous.get("executionAction", {})
                action["end"] = previous["end"]; action["text"] = previous["text"]
                previous.setdefault("layout", {}).pop("compositionSafety", None)
                changes.append({"type": "SEMANTIC_TEXT_MERGE", "start": previous.get("start"), "end": previous.get("end"), "words": combined_words})
            else:
                merged_scenes.append(scene)
        result["scenes"] = merged_scenes
    execution = result.setdefault("execution", {})
    camera = execution.get("camera_actions", result.get("camera", []))
    target_camera = int(round(float(params.get("camera_event_target", len(camera)))))
    if target_camera < len(camera):
        keep = sorted(camera, key=lambda event: float(event.get("strength", event.get("intensity", 0.0))), reverse=True)[:max(0, target_camera)]
        keep_ids = {id(item) for item in keep}
        filtered = [item for item in camera if id(item) in keep_ids or str(item.get("effect", item.get("type", ""))).upper() in {"RECOVERY", "RETURN_BASELINE", "BASELINE"}]
        execution["camera_actions"] = filtered
        changes.append({"type": "CAMERA_DENSITY", "before": len(camera), "after": len(filtered)})
    target_strength = float(params.get("camera_strength_target", 0.0))
    current_strengths = [float(item.get("strength", item.get("intensity", 0.0))) for item in execution.get("camera_actions", camera)]
    average_strength = statistics.mean(current_strengths) if current_strengths else 0.0
    if 0 < target_strength < average_strength:
        ratio = max(0.72, target_strength / average_strength)
        for event in execution.get("camera_actions", camera):
            if "strength" in event: event["strength"] = round(float(event["strength"]) * ratio, 3)
            if "intensity" in event: event["intensity"] = round(float(event["intensity"]) * ratio, 3)
            if "scale" in event: event["scale"] = round(1.0 + (float(event["scale"]) - 1.0) * ratio, 4)
            if "movement" in event: event["movement"] = round(float(event["movement"]) * ratio, 3)
        changes.append({"type": "CAMERA_STRENGTH", "before": round(average_strength, 3), "after": round(target_strength, 3)})
    broll = execution.get("broll_actions", result.get("broll", []))
    target_broll_duration = float(params.get("broll_duration_target", 0.0))
    if target_broll_duration > 0:
        for event in broll:
            start, end = float(event.get("from", event.get("start", 0))), float(event.get("to", event.get("end", 0)))
            if end - start > target_broll_duration * 1.15:
                new_end = round(start + target_broll_duration, 3)
                if "to" in event: event["to"] = new_end
                else: event["end"] = new_end
                changes.append({"type": "BROLL_DURATION", "start": start, "before": round(end - start, 3), "after": target_broll_duration})
    result.setdefault("calibration", {}).update({"candidate": candidate, "changes": changes, "production_applied": False})
    return result, {"changes": changes, "summary": {"count": len(changes)}}


def distribution(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"sample_count": 0, "mean": None, "median": None, "min": None, "max": None, "percentiles": {}, "confidence": 0.0}
    def percentile(p: float) -> float:
        return round(ordered[min(len(ordered) - 1, round((len(ordered) - 1) * p))], 4)
    return {
        "sample_count": len(ordered), "mean": round(statistics.mean(ordered), 4), "median": round(statistics.median(ordered), 4),
        "min": round(ordered[0], 4), "max": round(ordered[-1], 4),
        "percentiles": {"p10": percentile(0.1), "p25": percentile(0.25), "p75": percentile(0.75), "p90": percentile(0.9)},
        "confidence": round(min(0.92, 0.32 + 0.12 * math.sqrt(len(ordered))), 3),
    }


def aggregate_style_statistics(reports: list[dict[str, Any]]) -> dict[str, Any]:
    paths = {
        "text_coverage": lambda a: a["typography"]["summary"]["text_coverage"],
        "text_free_coverage": lambda a: a["typography"]["summary"]["text_free_coverage"],
        "median_text_scene_duration": lambda a: a["typography"]["summary"]["median_scene_duration"],
        "median_words_per_scene": lambda a: a["typography"]["summary"]["median_words_per_scene"],
        "hero_count": lambda a: a["typography"]["summary"]["hero_count"],
        "accent_count": lambda a: a["typography"]["summary"]["accent_count"],
        "camera_count": lambda a: a["camera"]["summary"]["count"],
        "camera_calm_coverage": lambda a: a["camera"]["summary"]["calm_coverage"],
        "broll_count": lambda a: a["broll"]["summary"]["count"],
        "broll_coverage": lambda a: a["broll"]["summary"]["coverage"],
        "broll_median_duration": lambda a: a["broll"]["summary"]["median_duration"],
        "visual_rest_coverage": lambda a: a["visual_rest"]["summary"]["coverage"],
        "motion_density": lambda a: a["motion"]["summary"]["event_density"],
        "sfx_density": lambda a: a["sfx"]["summary"]["event_density"],
    }
    return {"version": 1, "principle": "distributions_not_rules", "sample_count": len(reports), "metrics": {name: distribution([getter(report) for report in reports]) for name, getter in paths.items()}}
