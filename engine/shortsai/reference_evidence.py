from __future__ import annotations

from collections import Counter, defaultdict
import copy
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable, Sequence

from .transcription import Transcript


TOKEN_RE = re.compile(r"[0-9a-zа-яё%]+", re.IGNORECASE)
STRONG_ROLES = {"HOOK", "HERO", "NUMBER", "PUNCH", "ACCENT", "DISPLAY"}
OBJECT_MARKERS = {
    "банк", "кредит", "кредитка", "карта", "платеж", "долг", "ставка", "процент",
    "деньги", "документ", "экран", "чат", "комментарий", "телефон", "продукт",
    "автомобиль", "дом", "офис", "магазин", "человек", "клиент", "таблица",
}
EXTERNAL_MARKERS = {"история", "клиент", "пример", "рынок", "город", "страна", "компания", "банк", "суд", "новость"}
PROOF_MARKERS = {"доказательство", "результат", "скрин", "покажу", "видно", "цифра", "статистика", "пример"}
PROCESS_MARKERS = {"сделать", "делать", "работает", "происходит", "получить", "платить", "пользоваться", "создать", "отправить", "написать"}
EMOTION_MARKERS = {"страх", "опасно", "ошибка", "проблема", "нищий", "долговая", "провал", "успех", "важно"}


def _tokens(text: str | None) -> list[str]:
    return [item.casefold().replace("ё", "е") for item in TOKEN_RE.findall(text or "")]


def _duration(intervals: Iterable[tuple[float, float]]) -> float:
    merged: list[list[float]] = []
    for start, end in sorted((max(0.0, float(start)), max(float(start), float(end))) for start, end in intervals):
        if not merged or start > merged[-1][1] + 0.001:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return sum(end - start for start, end in merged)


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.mean(values), 4) if values else None


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * fraction
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 4)
    return round(ordered[lower] * (upper - position) + ordered[upper] * (position - lower), 4)


def observed_distribution(values: Sequence[float], source_ids: Sequence[str]) -> dict[str, Any]:
    clean = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    q1, q3 = _percentile(clean, 0.25), _percentile(clean, 0.75)
    spread = (q3 - q1) if q1 is not None and q3 is not None else 0.0
    scale = max(abs(_median(clean) or 0.0), 0.05)
    consistency = max(0.0, 1.0 - min(1.0, spread / scale))
    confidence = min(0.9, 0.22 + 0.11 * len(set(source_ids)) + 0.24 * consistency)
    level = "HIGH" if len(set(source_ids)) >= 5 and confidence >= 0.75 else "MEDIUM" if len(set(source_ids)) >= 3 and confidence >= 0.55 else "LOW"
    return {
        "sample_count": len(clean), "reference_count": len(set(source_ids)),
        "median": _median(clean), "q1": q1, "q3": q3,
        "observed_min": round(min(clean), 4) if clean else None,
        "observed_max": round(max(clean), 4) if clean else None,
        "mean": _mean(clean), "confidence": round(confidence, 3) if clean else 0.0,
        "confidence_level": level if clean else "LOW",
    }


def _spoken_text(transcript: Transcript | None, start: float, end: float) -> str | None:
    if transcript is None:
        return None
    words = [word.text for segment in transcript.segments for word in segment.words if word.end >= start and word.start <= end]
    return " ".join(words).strip() or None


def _collapse_states(rhythm: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    for item in sorted(rhythm, key=lambda row: float(row.get("start", 0))):
        role = str(item.get("state", "UNKNOWN")).upper()
        if collapsed and collapsed[-1]["role"] == role and float(item.get("start", 0)) <= collapsed[-1]["end"] + 0.02:
            collapsed[-1]["end"] = float(item.get("end", collapsed[-1]["end"]))
        else:
            collapsed.append({"role": role, "start": float(item.get("start", 0)), "end": float(item.get("end", 0))})
    return collapsed


def composition_transition_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    scenes = list(analysis.get("typography", {}).get("scenes", []))
    role_map = {"BODY": "NORMAL", "DISPLAY": "ACCENT", "HERO": "HERO", "NUMBER": "NUMBER"}
    sequence = [
        {"role": role_map.get(str(item.get("role", "")).upper(), str(item.get("role", "UNKNOWN")).upper()),
         "start": float(item.get("start", 0)), "end": float(item.get("end", 0)), "layout": item.get("position")}
        for item in scenes
    ]
    non_text = [item for item in analysis.get("composition_rhythm", []) if item.get("state") in {"BROLL", "SPEAKER_ONLY", "VISUAL_EVENT"}]
    sequence.extend(_collapse_states(non_text))
    sequence.sort(key=lambda item: (item["start"], item["end"]))
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for previous, current in zip(sequence, sequence[1:]):
        counts[previous["role"]][current["role"]] += 1
    matrix = {
        source: {
            target: {"count": count, "probability": round(count / max(1, sum(targets.values())), 3)}
            for target, count in sorted(targets.items())
        }
        for source, targets in sorted(counts.items())
    }
    runs: dict[str, list[int]] = defaultdict(list)
    current_role, current_length = None, 0
    for item in sequence:
        if item["role"] == current_role:
            current_length += 1
        else:
            if current_role is not None:
                runs[current_role].append(current_length)
            current_role, current_length = item["role"], 1
    if current_role is not None:
        runs[current_role].append(current_length)
    strong_repeats = sum(
        str(current.get("role", "")).upper() in {"HERO", "DISPLAY", "NUMBER"}
        and str(previous.get("role", "")).upper() == str(current.get("role", "")).upper()
        and previous.get("position") == current.get("position")
        for previous, current in zip(scenes, scenes[1:])
    )
    patterns = [(sequence[index]["role"], sequence[index + 1]["role"], sequence[index + 2]["role"]) for index in range(max(0, len(sequence) - 2))]
    pattern_repeats = sum(count - 1 for count in Counter(patterns).values() if count > 1)
    layout_counts = Counter(f"{item.get('role')}:{item.get('position')}" for item in scenes)
    total = sum(layout_counts.values())
    entropy = -sum((count / total) * math.log2(count / total) for count in layout_counts.values()) if total else 0.0
    normalized_entropy = entropy / math.log2(len(layout_counts)) if len(layout_counts) > 1 else 0.0
    role_stats = {
        role: {"runs": values, "median": _median(values), "maximum": max(values, default=0), "mean": _mean(values)}
        for role, values in sorted(runs.items())
    }
    normal_runs = role_stats.get("NORMAL", {"median": 0, "maximum": 0, "mean": 0})
    strong_run_values = [value for role, values in runs.items() if role in {"HERO", "ACCENT", "NUMBER"} for value in values]
    return {
        "sequence": sequence, "distribution": dict(Counter(item["role"] for item in sequence)),
        "transition_matrix": matrix, "run_length_by_role": role_stats,
        "normal_run_length": normal_runs,
        "strong_scene_run_length": {"median": _median(strong_run_values), "maximum": max(strong_run_values, default=0), "mean": _mean(strong_run_values)},
        "same_layout_strong_repeat": strong_repeats,
        "composition_entropy": round(normalized_entropy, 4),
        "visual_pattern_repetition": round(pattern_repeats / max(1, len(patterns)), 4),
        "interpretation": "Entropy and repetition describe identity/rhythm; neither is minimized automatically.",
    }


def _camera_class(event: dict[str, Any]) -> str:
    effect = str(event.get("effect", event.get("type", ""))).upper()
    strength = abs(float(event.get("scale_delta", event.get("strength", event.get("intensity", 0.0)))))
    if effect in {"RECOVERY", "RETURN_BASELINE", "BASELINE"} or float(event.get("scale_delta", 0.0)) < 0:
        return "RECOVERY"
    if effect in {"PUNCH_ZOOM", "CUT_TO_CLOSER", "PUNCH"} or strength >= 0.16:
        return "PUNCH_LIKE"
    return "SUBTLE_PUSH"


def _camera_profile(events: list[dict[str, Any]], duration: float, calm_coverage: float | None = None) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        groups[_camera_class(event)].append(event)
    by_type = {}
    for role in ("SUBTLE_PUSH", "PUNCH_LIKE", "RECOVERY"):
        values = groups.get(role, [])
        strengths = [abs(float(item.get("scale_delta", item.get("strength", item.get("intensity", 0.0))))) for item in values]
        durations = [float(item.get("duration", item.get("settle_duration", 0.0))) for item in values]
        by_type[role] = {"count": len(values), "rate_per_minute": round(len(values) * 60 / max(duration, 0.001), 3), "strength_median": _median(strengths), "strength_mean": _mean(strengths), "duration_median": _median(durations)}
    pushes = len(groups.get("SUBTLE_PUSH", [])) + len(groups.get("PUNCH_LIKE", []))
    times = sorted(float(item.get("time", item.get("start", 0))) for item in events)
    return {
        "event_count": len(events), "event_rate_per_minute": round(len(events) * 60 / max(duration, 0.001), 3),
        "by_type": by_type,
        "recovery_behavior": {"recovery_count": len(groups.get("RECOVERY", [])), "recovery_per_push": round(len(groups.get("RECOVERY", [])) / max(1, pushes), 3)},
        "baseline_hold_median": _median([times[index] - times[index - 1] for index in range(1, len(times))]),
        "calm_coverage": calm_coverage,
    }


def _semantic_features(text: str | None) -> dict[str, Any]:
    tokens = _tokens(text)
    token_set = set(tokens)
    has_number = any(any(char.isdigit() for char in token) for token in tokens)
    objects = sorted(token for token in token_set if any(token.startswith(marker[:5]) for marker in OBJECT_MARKERS))
    external = sorted(token for token in token_set if any(token.startswith(marker[:5]) for marker in EXTERNAL_MARKERS))
    proof = sorted(token for token in token_set if any(token.startswith(marker[:5]) for marker in PROOF_MARKERS))
    process = sorted(token for token in token_set if token in PROCESS_MARKERS or token.endswith(("ть", "ться", "ете", "ает", "яют")))
    emotions = sorted(token for token in token_set if any(token.startswith(marker[:5]) for marker in EMOTION_MARKERS))
    concreteness = min(1.0, 0.18 + len(objects) * 0.18 + len(external) * 0.12 + (0.12 if has_number else 0.0))
    visualizability = min(1.0, concreteness + len(process) * 0.08 + len(proof) * 0.16)
    return {
        "visualizability": round(visualizability, 3), "concreteness": round(concreteness, 3),
        "entity_or_object_mentions": objects, "action_or_process": process,
        "proof_or_example": proof, "external_context": external,
        "emotional_function": emotions, "has_number": has_number,
    }


def _semantic_role(text: str | None, start: float, duration: float) -> str:
    lower = (text or "").casefold()
    if start < 3.5:
        return "HOOK"
    if any(marker in lower for marker in ("например", "к примеру", "история")):
        return "EXAMPLE"
    if any(marker in lower for marker in ("потому что", "доказ", "результат")):
        return "PROOF"
    if any(char.isdigit() for char in lower):
        return "NUMBER_EVIDENCE"
    if any(marker in lower for marker in ("но ", "однако", "вместо")):
        return "CONTRAST"
    if start > duration - 5 and any(marker in lower for marker in ("напиши", "ссылка", "подпис", "комментар")):
        return "CTA"
    return "EXPLANATION"


def visual_behavior_profile(
    reference_id: str, reference_type: str, weak_label: str,
    analysis: dict[str, Any], transcript: Transcript | None = None,
) -> dict[str, Any]:
    duration = float(analysis.get("duration", 0))
    scenes = copy.deepcopy(list(analysis.get("typography", {}).get("scenes", [])))
    if transcript is not None:
        for scene in scenes:
            spoken = scene.get("actual_text") or _spoken_text(transcript, float(scene.get("start", 0)), float(scene.get("end", 0)))
            scene["actual_text"] = spoken
            if scene.get("word_count") is None and spoken:
                scene["word_count"] = len(_tokens(spoken))
    rhythm = list(analysis.get("composition_rhythm", []))
    normal = [item for item in scenes if str(item.get("role", "")).upper() == "BODY"]
    strong = [item for item in scenes if str(item.get("role", "")).upper() in {"HERO", "DISPLAY", "NUMBER"}]
    text_intervals = [(item["start"], item["end"]) for item in scenes]
    normal_duration = _duration((item["start"], item["end"]) for item in normal)
    strong_duration = _duration((item["start"], item["end"]) for item in strong)
    text_runs = _collapse_states([{"start": item["start"], "end": item["end"], "state": "TEXT"} for item in scenes])
    speaker_only = [item for item in rhythm if item.get("state") == "SPEAKER_ONLY"]
    text_free_visual = [item for item in rhythm if item.get("state") in {"BROLL", "VISUAL_EVENT"}]
    strong_rest = []
    ordered_scenes = sorted(scenes, key=lambda item: item["start"])
    for scene in strong:
        next_scene = next((item for item in ordered_scenes if item["start"] >= scene["end"]), None)
        strong_rest.append(max(0.0, (next_scene["start"] if next_scene else duration) - scene["end"]))
    transition = composition_transition_analysis(analysis)
    text_words = [float(item["word_count"]) for item in scenes if item.get("word_count") is not None]
    broll_events = []
    for item in analysis.get("broll", {}).get("events", []):
        text = item.get("illustrated_thought") or _spoken_text(transcript, float(item["start"]), float(item["end"]))
        before = _spoken_text(transcript, max(0.0, float(item["start"]) - 2.0), float(item["start"]))
        after = _spoken_text(transcript, float(item["end"]), min(duration, float(item["end"]) + 2.0))
        broll_events.append({
            **copy.deepcopy(item), "spoken_phrase": text, "before_context": before, "after_context": after,
            "semantic_role": _semantic_role(text, float(item["start"]), duration),
            "semantic_features": _semantic_features(text),
            "relation_to_spoken_phrase": "TIME_ALIGNED_OBSERVATION" if text else "UNKNOWN_NO_TRANSCRIPT",
        })
    broll_durations = [float(item.get("duration", 0)) for item in broll_events]
    broll_gaps = [float(broll_events[index]["start"]) - float(broll_events[index - 1]["end"]) for index in range(1, len(broll_events))]
    camera = _camera_profile(list(analysis.get("camera", {}).get("events", [])), duration, analysis.get("camera", {}).get("summary", {}).get("calm_coverage"))
    detected = str(analysis.get("style", {}).get("detected_style", "unknown"))
    detector_confidence = float(analysis.get("style", {}).get("style_confidence", 0.0))
    normalized_label = weak_label.casefold().replace("-", "_")
    recognized_labels = {"aggressive_social", "clean_expert", "storytelling", "podcast"}
    label_agrees = normalized_label in {detected.casefold(), "paired"}
    style_confidence = min(0.85, detector_confidence + (0.12 if label_agrees else -0.04))
    style_cluster = detected if label_agrees or normalized_label not in recognized_labels or detector_confidence >= 0.65 else normalized_label
    role_counts = Counter(str(item.get("role", "UNKNOWN")).upper() for item in scenes)
    strong_gaps = [strong[index]["start"] - strong[index - 1]["end"] for index in range(1, len(strong))]
    return {
        "version": 1, "reference_id": reference_id, "reference_type": reference_type,
        "editorial_evidence_allowed": reference_type == "RAW_TO_FINAL",
        "duration": round(duration, 3), "weak_human_label": weak_label,
        "detected_style": detected, "style_cluster": style_cluster,
        "style_cluster_basis": "detector" if style_cluster == detected else "weak_label_assisted_low_confidence_detector",
        "style_confidence": round(max(0.0, style_confidence), 3),
        "text": {
            "coverage": round(_duration(text_intervals) / max(duration, 0.001), 4),
            "text_free_coverage": round(max(0.0, 1 - _duration(text_intervals) / max(duration, 0.001)), 4),
            "normal_text_coverage": round(normal_duration / max(duration, 0.001), 4),
            "strong_typography_coverage": round(strong_duration / max(duration, 0.001), 4),
            "words_per_scene": _median(text_words),
            "median_scene_duration": _median([float(item.get("duration", 0)) for item in scenes]),
            "average_uninterrupted_text_run": _mean([item["end"] - item["start"] for item in text_runs]),
            "average_visual_rest_after_strong": _mean(strong_rest),
            "word_measurement_available": bool(text_words),
        },
        "composition": {
            **transition, "role_counts": dict(role_counts),
            "hero_count": role_counts.get("HERO", 0), "hero_rate_per_minute": round(role_counts.get("HERO", 0) * 60 / max(duration, 0.001), 3),
            "number_count": None if transcript is None else sum(bool(item.get("actual_text")) and any(char.isdigit() for char in str(item["actual_text"])) for item in scenes),
            "number_rate_per_minute": None if transcript is None else round(sum(bool(item.get("actual_text")) and any(char.isdigit() for char in str(item["actual_text"])) for item in scenes) * 60 / max(duration, 0.001), 3),
            "accent_count": role_counts.get("DISPLAY", 0), "accent_rate_per_minute": round(role_counts.get("DISPLAY", 0) * 60 / max(duration, 0.001), 3),
            "strong_event_ratio": round(len(strong) / max(1, len(scenes)), 4),
            "strong_event_cooldown": _median(strong_gaps),
            "semantic_layout_match": None if transcript is None else round(sum(0.7 if item.get("actual_text") else 0.35 for item in scenes) / max(1, len(scenes)), 3),
            "semantic_layout_match_method": "weak_phrase_role_heuristic" if transcript else "UNAVAILABLE_WITHOUT_TRANSCRIPT",
        },
        "broll": {
            "count": len(broll_events), "coverage": analysis.get("broll", {}).get("summary", {}).get("coverage", 0.0),
            "median_duration": _median(broll_durations), "median_gap": _median(broll_gaps),
            "burst_count": sum(bool(item.get("burst")) for item in broll_events),
            "burst_rate": round(sum(bool(item.get("burst")) for item in broll_events) / max(1, len(broll_events)), 3),
            "events": broll_events,
        },
        "speaker_only_coverage": round(_duration((item["start"], item["end"]) for item in speaker_only) / max(duration, 0.001), 4),
        "text_free_visual_or_broll_coverage": round(_duration((item["start"], item["end"]) for item in text_free_visual) / max(duration, 0.001), 4),
        "camera": camera,
        "strong_effect_count": len(analysis.get("motion", {}).get("events", [])),
        "strong_effect_rate_per_minute": round(len(analysis.get("motion", {}).get("events", [])) * 60 / max(duration, 0.001), 3),
        "visual_rest": {"coverage": analysis.get("visual_rest", {}).get("summary", {}).get("coverage", 0.0), "median_duration": analysis.get("visual_rest", {}).get("summary", {}).get("median_duration")},
        "approximate_sfx_density": analysis.get("sfx", {}).get("summary", {}).get("event_density", 0.0),
        "measurement_limits": list(analysis.get("limitations", [])),
    }


def aggregate_reference_priors(profiles: list[dict[str, Any]], *, raw_pair_count: int) -> dict[str, Any]:
    metric_paths = {
        "text.coverage": lambda p: p["text"]["coverage"],
        "text.normal_coverage": lambda p: p["text"]["normal_text_coverage"],
        "text.strong_coverage": lambda p: p["text"]["strong_typography_coverage"],
        "text.speaker_only_coverage": lambda p: p["speaker_only_coverage"],
        "text.average_run": lambda p: p["text"]["average_uninterrupted_text_run"],
        "text.rest_after_strong": lambda p: p["text"]["average_visual_rest_after_strong"],
        "composition.strong_event_ratio": lambda p: p["composition"]["strong_event_ratio"],
        "composition.normal_run_median": lambda p: p["composition"]["normal_run_length"].get("median"),
        "composition.strong_run_median": lambda p: p["composition"]["strong_scene_run_length"].get("median"),
        "composition.same_layout_strong_repeat": lambda p: p["composition"]["same_layout_strong_repeat"],
        "composition.entropy": lambda p: p["composition"]["composition_entropy"],
        "composition.pattern_repetition": lambda p: p["composition"]["visual_pattern_repetition"],
        "camera.event_rate": lambda p: p["camera"]["event_rate_per_minute"],
        "camera.subtle_strength": lambda p: p["camera"]["by_type"]["SUBTLE_PUSH"]["strength_median"],
        "camera.punch_strength": lambda p: p["camera"]["by_type"]["PUNCH_LIKE"]["strength_median"],
        "camera.recovery_per_push": lambda p: p["camera"]["recovery_behavior"]["recovery_per_push"],
        "camera.baseline_hold": lambda p: p["camera"]["baseline_hold_median"],
        "broll.coverage": lambda p: p["broll"]["coverage"],
        "broll.median_duration": lambda p: p["broll"]["median_duration"],
        "broll.median_gap": lambda p: p["broll"]["median_gap"],
        "visual_rest.coverage": lambda p: p["visual_rest"]["coverage"],
        "effects.rate": lambda p: p["strong_effect_rate_per_minute"],
        "sfx.density": lambda p: p["approximate_sfx_density"],
    }
    clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for profile in profiles:
        clusters[profile["style_cluster"]].append(profile)
    clusters["GLOBAL"] = profiles
    priors = []
    for cluster, members in sorted(clusters.items()):
        for parameter, getter in metric_paths.items():
            values, ids = [], []
            for member in members:
                value = getter(member)
                if value is not None:
                    values.append(float(value)); ids.append(member["reference_id"])
            observed = observed_distribution(values, ids)
            candidate_allowed = observed["confidence_level"] in {"MEDIUM", "HIGH"}
            priors.append({
                "parameter": parameter, "style_cluster": cluster, "observed": observed,
                "source_reference_ids": sorted(set(ids)), "sample_count": observed["reference_count"],
                "confidence": observed["confidence"], "confidence_level": observed["confidence_level"],
                "applicability": "OBSERVABLE_VISUAL_BEHAVIOR_ONLY",
                "candidate_usage_allowed": candidate_allowed,
                "production_usage_allowed": candidate_allowed and raw_pair_count >= 3 and observed["confidence_level"] == "HIGH",
            })
    return {
        "version": 1, "principle": "evidence_distributions_not_single_reference_targets",
        "raw_to_final_pairs": raw_pair_count, "visual_reference_count": len(profiles),
        "confidence_policy": {"LOW": "suggestion only", "MEDIUM": "isolated candidate allowed", "HIGH": "promotion review only after holdout and >=3 RAW pairs"},
        "production_promotion_allowed": False if raw_pair_count < 3 else "REQUIRES_HOLDOUT",
        "style_clusters": {key: [item["reference_id"] for item in value] for key, value in sorted(clusters.items()) if key != "GLOBAL"},
        "priors": priors,
    }


def _prior(priors: dict[str, Any], parameter: str, cluster: str = "GLOBAL") -> dict[str, Any] | None:
    return next((item for item in priors.get("priors", []) if item["parameter"] == parameter and item["style_cluster"] == cluster), None)


def evaluate_hypotheses(profiles: list[dict[str, Any]], before: dict[str, Any]) -> dict[str, Any]:
    definitions = [
        ("shortsai_text_density_too_high", lambda p: p["text"]["coverage"], float(before.get("text_coverage", 0)), -0.10, -0.03),
        ("shortsai_strong_hierarchy_too_weak", lambda p: p["composition"]["strong_event_ratio"], float(before.get("strong_typography_rate", 0)), 0.05, 0.015),
        ("shortsai_camera_punch_too_strong", lambda p: p["camera"]["by_type"]["PUNCH_LIKE"]["strength_median"], float(before.get("camera_punch_strength", before.get("camera_strength", 0))), -0.08, -0.02),
        ("shortsai_visual_rest_pattern_differs", lambda p: p["visual_rest"]["coverage"], float(before.get("visual_rest", 0)), None, None),
        ("shortsai_may_underuse_semantic_broll", lambda p: p["broll"]["coverage"], float(before.get("broll_coverage", 0)), 0.05, 0.01),
    ]
    findings = []
    for name, getter, current, strong_delta, weak_delta in definitions:
        supporting, contradicting, neutral = [], [], []
        for profile in profiles:
            value = getter(profile)
            if value is None:
                continue
            delta = float(value) - current
            if strong_delta is None:
                bucket = supporting if abs(delta) >= 0.10 else contradicting if abs(delta) <= 0.03 else neutral
            elif strong_delta < 0:
                bucket = supporting if delta <= strong_delta else contradicting if delta >= weak_delta else neutral
            else:
                bucket = supporting if delta >= strong_delta else contradicting if delta <= weak_delta else neutral
            bucket.append(profile["reference_id"])
        eligible = len(supporting) + len(contradicting) + len(neutral)
        consistency = len(supporting) / max(1, len(supporting) + len(contradicting))
        confidence = min(0.88, 0.2 + 0.11 * eligible + 0.2 * consistency)
        level = "HIGH" if eligible >= 5 and consistency >= 0.8 else "MEDIUM" if eligible >= 3 and consistency >= 0.67 else "LOW"
        clusters = {profile["style_cluster"] for profile in profiles if profile["reference_id"] in supporting}
        findings.append({
            "hypothesis": name, "supporting_reference_ids": supporting, "supporting_reference_count": len(supporting),
            "contradicting_reference_ids": contradicting, "contradicting_reference_count": len(contradicting),
            "neutral_reference_ids": neutral, "eligible_reference_count": eligible,
            "scope": "GLOBAL" if len(clusters) > 1 else "STYLE_SPECIFIC" if clusters else "UNRESOLVED",
            "supporting_styles": sorted(clusters), "confidence": round(confidence, 3), "confidence_level": level,
            "candidate_usage_allowed": level in {"MEDIUM", "HIGH"},
        })
    return {"version": 1, "hypotheses": findings}


def load_broll_assets(index_path: Path) -> list[dict[str, Any]]:
    if not index_path.is_file():
        return []
    return [item for item in json.loads(index_path.read_text(encoding="utf-8")).get("assets", []) if item.get("usable", True)]


def _asset_matches(text: str, assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tokens = set(_tokens(text))
    matches = []
    for asset in assets:
        tags = set(_tokens(" ".join(asset.get("tags", [])) + " " + asset.get("description", "")))
        overlap = sorted(tokens & tags)
        score = len(overlap) / max(2, min(8, len(tokens)))
        if score >= 0.16:
            matches.append({"asset_id": asset.get("id"), "file": asset.get("file"), "score": round(score, 3), "overlap": overlap})
    return sorted(matches, key=lambda item: item["score"], reverse=True)


def build_broll_evidence(profiles: list[dict[str, Any]], assets: list[dict[str, Any]]) -> dict[str, Any]:
    observations = []
    rule_refs: dict[str, set[str]] = defaultdict(set)
    rule_durations: dict[str, list[float]] = defaultdict(list)
    for profile in profiles:
        for event in profile["broll"]["events"]:
            features = event["semantic_features"]
            rules = []
            if features["visualizability"] >= 0.55: rules.append("visualizable_concrete_thought")
            if features["entity_or_object_mentions"]: rules.append("concrete_object_or_entity")
            if features["action_or_process"]: rules.append("process_or_action")
            if features["proof_or_example"]: rules.append("proof_or_example")
            if features["external_context"]: rules.append("external_context")
            matches = _asset_matches(event.get("spoken_phrase") or "", assets)
            for rule in rules:
                rule_refs[rule].add(profile["reference_id"]); rule_durations[rule].append(float(event.get("duration", 0)))
            observations.append({
                "reference_id": profile["reference_id"], "reference_type": profile["reference_type"],
                "start": event.get("start"), "end": event.get("end"), "spoken_phrase": event.get("spoken_phrase"),
                "semantic_role": event.get("semantic_role"), "features": features, "rules": rules,
                "presentation": event.get("presentation"), "burst": event.get("burst"),
                "asset_matches": matches, "asset_status": "MATCH_AVAILABLE" if matches else "BROLL_WANTED_BUT_ASSET_MISSING",
                "editorial_claim_allowed": profile["editorial_evidence_allowed"],
            })
    rules = []
    for rule, references in sorted(rule_refs.items()):
        count = len(references)
        level = "HIGH" if count >= 5 else "MEDIUM" if count >= 3 else "LOW"
        rules.append({
            "signal": rule, "supporting_reference_ids": sorted(references), "reference_count": count,
            "observed_broll_duration": observed_distribution(rule_durations[rule], [item["reference_id"] for item in observations if rule in item["rules"]]),
            "confidence_level": level, "candidate_usage_allowed": level in {"MEDIUM", "HIGH"},
            "principle": "signal contributes to a score; it is never sufficient alone",
        })
    concept_rules = {
        "bank_credit_debt": (("банк", "кредит", "ставк", "процент", "платеж", "долг", "банкрот"), "credit card, bank statement, minimum payment, interest and debt visuals"),
        "social_media_analytics": (("просмотр", "смотренн", "статист", "охват"), "phone analytics, views, retention graph and reach dashboard"),
        "content_creation_process": (("снима", "нареза", "монтаж", "кадр", "контент"), "camera setup, recording, editing timeline and clip selection"),
        "community_chat": (("чат", "комментар", "сообщ", "комьюн"), "messenger conversation, community feed and comment CTA"),
        "documents_and_proof": (("документ", "скрин", "доказ", "результ"), "document close-up, screenshot, result and proof card"),
        "money_usage": (("деньг", "оплат", "доход", "цена"), "payment, money transfer and practical spending context"),
    }
    missing: dict[str, dict[str, Any]] = {}
    for item in observations:
        if item["asset_status"] != "BROLL_WANTED_BUT_ASSET_MISSING":
            continue
        phrase = (item.get("spoken_phrase") or "").casefold().replace("ё", "е")
        for concept, (markers, desired_visual) in concept_rules.items():
            if not any(marker in phrase for marker in markers):
                continue
            row = missing.setdefault(concept, {"concept": concept, "observations": 0, "example_phrases": [], "desired_visual": desired_visual})
            row["observations"] += 1
            if item.get("spoken_phrase") and len(row["example_phrases"]) < 3:
                row["example_phrases"].append(item["spoken_phrase"])
    return {
        "version": 1, "principle": "semantic necessity + reference support + local asset + cadence",
        "rules": rules, "observations": observations,
        "asset_library": {"count": len(assets), "files": [item.get("file") for item in assets]},
        "recommended_missing_asset_concepts": sorted(missing.values(), key=lambda item: item["observations"], reverse=True),
    }


def assess_plan_broll(plan: dict[str, Any], evidence: dict[str, Any], assets: list[dict[str, Any]]) -> dict[str, Any]:
    rules = {item["signal"]: item for item in evidence.get("rules", [])}
    assessments = []
    for request in plan.get("brollRequests", []):
        text = str(request.get("text", ""))
        features = _semantic_features(text)
        signals = []
        if features["visualizability"] >= 0.55: signals.append("visualizable_concrete_thought")
        if features["entity_or_object_mentions"]: signals.append("concrete_object_or_entity")
        if features["action_or_process"]: signals.append("process_or_action")
        if features["proof_or_example"]: signals.append("proof_or_example")
        if features["external_context"]: signals.append("external_context")
        supported = [rules[item] for item in signals if item in rules]
        level_rank = max(({"LOW": 1, "MEDIUM": 2, "HIGH": 3}[item["confidence_level"]] for item in supported), default=0)
        support_level = {0: "LOW", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}[level_rank]
        matches = _asset_matches(text, assets)
        necessity = float(request.get("brollNecessity", {}).get("final_score", request.get("brollValue", 0.0)))
        if support_level == "LOW":
            status = "CANDIDATE_REJECTED_LOW_CONFIDENCE"
        elif necessity < 0.45:
            status = "DIRECTOR_MISSED_BROLL" if features["visualizability"] >= 0.7 else "CANDIDATE_REJECTED_LOW_NECESSITY"
        elif not matches:
            status = "BROLL_WANTED_BUT_ASSET_MISSING"
        else:
            status = "BROLL_CANDIDATE_SUPPORTED"
        assessments.append({
            "segment_id": request.get("segmentId"), "time": request.get("time"), "text": text,
            "semantic_necessity": round(necessity, 3), "features": features,
            "supporting_signals": signals, "reference_support_level": support_level,
            "supporting_reference_ids": sorted({ref for item in supported for ref in item["supporting_reference_ids"]}),
            "asset_matches": matches, "status": status,
        })
    return {
        "version": 1, "assessments": assessments,
        "summary": dict(Counter(item["status"] for item in assessments)),
    }


def plan_behavior_profile(plan: dict[str, Any], duration: float) -> dict[str, Any]:
    scenes = [item for item in plan.get("scenes", []) if item.get("enabled", True)]
    roles = [str(item.get("semanticRole", item.get("type", "NORMAL"))).upper() for item in scenes]
    normal = [item for item, role in zip(scenes, roles) if role == "NORMAL"]
    strong = [item for item, role in zip(scenes, roles) if role in STRONG_ROLES]
    camera = [item for item in plan.get("execution", {}).get("camera_actions", plan.get("camera", [])) if item.get("enabled", True)]
    templates = [str(item.get("template", item.get("type", "NORMAL"))).upper() for item in scenes]
    transitions = Counter(f"{a}->{b}" for a, b in zip(templates, templates[1:]))
    strong_repeats = sum(a == b and roles[index] in STRONG_ROLES for index, (a, b) in enumerate(zip(templates, templates[1:]), 1))
    text_coverage = _duration((item.get("start", 0), item.get("end", 0)) for item in scenes) / max(duration, 0.001)
    return {
        "text_coverage": round(text_coverage, 4),
        "body_text_coverage": round(_duration((item.get("start", 0), item.get("end", 0)) for item in normal) / max(duration, 0.001), 4),
        "strong_text_coverage": round(_duration((item.get("start", 0), item.get("end", 0)) for item in strong) / max(duration, 0.001), 4),
        "strong_typography_rate": round(len(strong) / max(1, len(scenes)), 4),
        "speaker_only_text_free": round(max(0.0, 1 - text_coverage), 4),
        "composition_transition_counts": dict(transitions),
        "same_layout_strong_repeat": strong_repeats,
        "camera": _camera_profile(camera, duration),
    }


def build_candidate_v2(
    priors: dict[str, Any], hypotheses: dict[str, Any], before_metrics: dict[str, Any],
    before_behavior: dict[str, Any], broll_assessment: dict[str, Any], *, raw_pair_count: int,
) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    evidence_log = []
    text_hypothesis = next((item for item in hypotheses["hypotheses"] if item["hypothesis"] == "shortsai_text_density_too_high"), None)
    text_prior = _prior(priors, "text.coverage")
    if text_hypothesis and text_hypothesis["candidate_usage_allowed"] and text_prior and text_prior["candidate_usage_allowed"]:
        upper = text_prior["observed"].get("q3")
        current = before_behavior["text_coverage"]
        if upper is not None and current > upper:
            parameters["target_text_coverage"] = round(max(float(upper), current - min(0.12, (current - float(upper)) * 0.45)), 4)
            parameters["rest_opportunity_threshold"] = 0.66
            evidence_log.append({"parameter": "target_text_coverage", "prior": text_prior, "hypothesis": text_hypothesis})
    for camera_type, prior_name in (("SUBTLE_PUSH", "camera.subtle_strength"), ("PUNCH_LIKE", "camera.punch_strength")):
        prior = _prior(priors, prior_name)
        observed = before_behavior["camera"]["by_type"][camera_type].get("strength_median")
        if prior and prior["candidate_usage_allowed"] and observed is not None and prior["observed"].get("q3") is not None and observed > prior["observed"]["q3"]:
            parameters.setdefault("camera_strength_by_type", {})[camera_type] = round(max(prior["observed"]["q3"], observed * 0.88), 4)
            evidence_log.append({"parameter": f"camera_strength_by_type.{camera_type}", "prior": prior})
    hierarchy_hypothesis = next((item for item in hypotheses["hypotheses"] if item["hypothesis"] == "shortsai_strong_hierarchy_too_weak"), None)
    suggestions = []
    if hierarchy_hypothesis and hierarchy_hypothesis["candidate_usage_allowed"]:
        suggestions.append({
            "parameter": "strong_moment_hierarchy", "confidence_level": hierarchy_hypothesis["confidence_level"],
            "supporting_references": hierarchy_hypothesis["supporting_reference_ids"],
            "status": "DIRECTOR_REEVALUATION_ONLY",
            "reason": "Evidence supports rarer stronger hierarchy, but semantic roles must not be invented by calibration.",
        })
    candidate = {
        "version": 2, "mode": "ISOLATED_EVIDENCE_AWARE_CANDIDATE", "production_applied": False,
        "application_policy_version": "semantic_rest_v2",
        "objective": {"semantic_correctness": 1.0, "readability": 1.0, "editorial_correctness": 1.0, "visual_hierarchy": 0.85, "style_consistency": 0.8, "reference_supported_rhythm": 0.75, "controlled_stimulation": 0.8, "visual_rest": 0.75, "asset_relevance": 1.0, "reference_similarity": 0.35},
        "parameters": parameters, "evidence_log": evidence_log, "suggestions": suggestions, "broll_assessment": broll_assessment,
        "promotion_guard": {"minimum_raw_pairs": 3, "current_raw_pairs": raw_pair_count, "allowed": False, "reason": "Candidate v2 requires >=3 RAW→FINAL pairs and holdout validation"},
        "low_evidence_policy": "LOW evidence is suggestion-only and cannot alter candidate behavior",
    }
    candidate["candidate_id"] = sha256(json.dumps({"policy": candidate["application_policy_version"], "parameters": parameters, "broll": broll_assessment.get("summary", {})}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return candidate


def _rest_opportunity(scene: dict[str, Any], previous: dict[str, Any] | None, following: dict[str, Any] | None) -> tuple[float, list[str]]:
    role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
    text = str(scene.get("text", ""))
    importance = float(scene.get("importance", scene.get("executionAction", {}).get("importance", 0.5)))
    score, reasons = 0.0, []
    if role == "NORMAL": score += 0.34; reasons.append("normal typography")
    score += max(0.0, 0.62 - importance) * 0.72
    if importance < 0.42: reasons.append("low semantic importance")
    if previous and str(previous.get("semanticRole", previous.get("type", ""))).upper() in STRONG_ROLES:
        score += 0.18; reasons.append("rest after strong typography")
    if following and str(following.get("semanticRole", following.get("type", ""))).upper() in STRONG_ROLES:
        score += 0.1; reasons.append("breath before strong moment")
    semantic_protection = ("проблем", "долг", "кредит", "ставк", "процент", "потер", "провал", "опас", "нищ", "никогда", "важн", "результ", "повис")
    if any(marker in text.casefold() for marker in semantic_protection):
        score -= 0.34; reasons.append("protected semantic conflict/information")
    if following and not re.search(r"[.!?…:]\s*$", text) and float(following.get("start", 0)) - float(scene.get("end", 0)) <= 0.32:
        score -= 0.42; reasons.append("protected incomplete phrase")
    if "?" in text or any(char.isdigit() for char in text) or len(text.split()) >= 5:
        score -= 0.28; reasons.append("protected readability/information")
    if importance >= 0.68:
        score -= 0.35; reasons.append("protected important phrase")
    return round(max(0.0, min(1.0, score)), 3), reasons


def apply_candidate_v2(plan: dict[str, Any], candidate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    result = copy.deepcopy(plan)
    params = candidate.get("parameters", {})
    changes = []
    scenes = result.get("scenes", [])
    duration = float(result.get("output", {}).get("duration", 0))
    current = _duration((item.get("start", 0), item.get("end", 0)) for item in scenes if item.get("enabled", True)) / max(duration, 0.001)
    target = float(params.get("target_text_coverage", current))
    threshold = float(params.get("rest_opportunity_threshold", 1.1))
    opportunities = []
    for index, scene in enumerate(scenes):
        score, reasons = _rest_opportunity(scene, scenes[index - 1] if index else None, scenes[index + 1] if index + 1 < len(scenes) else None)
        opportunities.append({"index": index, "score": score, "reasons": reasons})
        scene.setdefault("referenceEvidence", {})["rest_opportunity_score"] = score
    removed = 0.0
    need = max(0.0, (current - target) * duration)
    for item in sorted(opportunities, key=lambda value: value["score"], reverse=True):
        if removed >= need or item["score"] < threshold:
            break
        scene = scenes[item["index"]]
        if not scene.get("enabled", True):
            continue
        before = True
        scene["enabled"] = False
        span = max(0.0, float(scene.get("end", 0)) - float(scene.get("start", 0)))
        removed += span
        changes.append({
            "parameter": "scene.enabled", "before": before, "after": False,
            "scene_start": scene.get("start"), "text": scene.get("text"),
            "reference_evidence": {"rest_opportunity_score": item["score"]},
            "supporting_references": next((log["prior"]["source_reference_ids"] for log in candidate.get("evidence_log", []) if log["parameter"] == "target_text_coverage"), []),
            "confidence": next((log["prior"]["confidence_level"] for log in candidate.get("evidence_log", []) if log["parameter"] == "target_text_coverage"), "LOW"),
            "expected_reason": "; ".join(item["reasons"]), "actual_measured_effect": None,
        })
    camera_targets = params.get("camera_strength_by_type", {})
    camera = result.get("execution", {}).get("camera_actions", result.get("camera", []))
    for event in camera:
        camera_type = _camera_class(event)
        target_strength = camera_targets.get(camera_type)
        current_strength = float(event.get("strength", event.get("intensity", 0.0)))
        if target_strength is None or current_strength <= target_strength:
            continue
        ratio = max(0.8, float(target_strength) / max(current_strength, 0.001))
        before = current_strength
        if "strength" in event: event["strength"] = round(current_strength * ratio, 3)
        if "intensity" in event: event["intensity"] = round(float(event["intensity"]) * ratio, 3)
        if "scale" in event: event["scale"] = round(1 + (float(event["scale"]) - 1) * ratio, 4)
        changes.append({
            "parameter": f"camera.{camera_type}.strength", "before": round(before, 3), "after": event.get("strength", event.get("intensity")),
            "reference_evidence": {"target": target_strength}, "supporting_references": next((log["prior"]["source_reference_ids"] for log in candidate.get("evidence_log", []) if log["parameter"] == f"camera_strength_by_type.{camera_type}"), []),
            "confidence": next((log["prior"]["confidence_level"] for log in candidate.get("evidence_log", []) if log["parameter"] == f"camera_strength_by_type.{camera_type}"), "LOW"),
            "expected_reason": "type-specific camera calibration", "actual_measured_effect": None,
        })
    assessments = {item.get("segment_id"): item for item in candidate.get("broll_assessment", {}).get("assessments", [])}
    for request in result.get("brollRequests", []):
        assessment = assessments.get(request.get("segmentId"))
        if assessment:
            request["referenceEvidence"] = assessment
            request["candidateV2Status"] = assessment["status"]
    result["referenceCalibrationV2"] = {"candidate": candidate, "candidate_change_log": changes, "production_applied": False}
    return result, {"version": 2, "candidate_id": candidate["candidate_id"], "changes": changes, "rest_opportunities": opportunities, "broll": candidate.get("broll_assessment", {}), "summary": {"count": len(changes)}}
