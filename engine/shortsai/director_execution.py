from __future__ import annotations

from collections import Counter
from pathlib import Path
import re
from typing import Any

from .broll_planner import build_broll_plan
from .sfx_library import resolve_sfx_actions


EXECUTION_PLAN_VERSION = 2
ROLE_PRIORITY = {"NORMAL": 0, "ACCENT": 1, "CONTRAST": 2, "HERO": 3, "NUMBER": 4, "PUNCH": 5, "HOOK": 6}


def validate_director_execution_plan(plan: dict[str, Any]) -> None:
    if plan.get("version") != EXECUTION_PLAN_VERSION:
        raise ValueError(f"director_execution_plan version must be {EXECUTION_PLAN_VERSION}")
    duration = float(plan.get("output_duration", 0))
    if duration <= 0:
        raise ValueError("director_execution_plan output duration must be positive")
    identifiers: set[str] = set()
    for section in ("text_actions", "camera_actions", "visual_actions", "audio_actions", "broll_actions"):
        for action in plan.get(section, []):
            identifier = str(action.get("id", ""))
            if not identifier or identifier in identifiers:
                raise ValueError(f"Invalid or duplicate execution action id: {identifier!r}")
            identifiers.add(identifier)
            start = float(action.get("start", action.get("time", action.get("from", 0))))
            if start < 0 or start > duration + 0.05:
                raise ValueError(f"Execution action is outside timeline: {identifier}")
            if section == "text_actions":
                end = float(action.get("end", start))
                if end <= start or end > duration + 0.05:
                    raise ValueError(f"Invalid text action interval: {identifier}")
            if section == "camera_actions":
                scale = float(action.get("scale", 1))
                if not 1.0 <= scale <= 1.2:
                    raise ValueError(f"Invalid semantic camera scale: {identifier}")
            if section == "broll_actions":
                end = float(action.get("to", start))
                if end <= start or end > duration + 0.05:
                    raise ValueError(f"Invalid B-roll execution interval: {identifier}")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _nearest_face(face_plan: dict[str, Any], timestamp: float) -> dict[str, Any] | None:
    samples = face_plan.get("samples", []) if face_plan.get("detected") else []
    if not samples:
        return None
    return min(samples, key=lambda item: abs(float(item.get("time", 0)) - timestamp))


def _side_line_count(text: str, available_width: float) -> int:
    """Estimate greedy line wrapping in normalized 1080px-wide coordinates."""
    words = [word for word in str(text).split() if word]
    if not words or available_width <= 0:
        return 99
    lines, occupied = 1, 0.0
    for word in words:
        width = max(0.065, len(word.strip(".,!?;:—-")) * 0.033 + 0.026)
        if occupied and occupied + width > available_width:
            lines += 1
            occupied = width
        else:
            occupied += width
    return lines


def _layout_for(
    role: str, face_plan: dict[str, Any], timestamp: float, text: str,
    style_profile: dict[str, Any],
) -> dict[str, Any]:
    sample = _nearest_face(face_plan, timestamp)
    face_box = None
    if sample:
        face_box = {key: round(float(sample[key]), 4) for key in ("x", "y", "w", "h")}
    text_rules = style_profile.get("text", {})
    proposed_side: str | None = None
    if role in {"HOOK", "HERO", "PUNCH", "NUMBER"}:
        position = "center_lower"
    elif sample and float(sample["y"]) > 0.58:
        position = "top"
    elif role == "ACCENT" and sample and float(sample["x"]) < 0.42 and text_rules.get("allow_right_side", False):
        proposed_side = "side_right"
        position = proposed_side
    elif role == "ACCENT" and sample and float(sample["x"]) > 0.58 and text_rules.get("side_text", "auto") is not False:
        proposed_side = "side_left"
        position = proposed_side
    else:
        position = "lower"

    available_width = 0.0
    estimated_lines = 0
    side_layout_valid = False
    fallback_reason = None
    if proposed_side and sample:
        face_x, face_w = float(sample["x"]), float(sample["w"])
        free_space = face_x - face_w / 2 if proposed_side == "side_left" else 1.0 - face_x - face_w / 2
        available_width = max(0.0, min(0.38, free_space - 0.07))
        estimated_lines = _side_line_count(text, available_width)
        word_count = len(str(text).split())
        side_layout_valid = available_width >= 0.31 and word_count <= 4 and estimated_lines <= 2
        if not side_layout_valid:
            position = "center_lower" if role == "ACCENT" else "lower"
            fallback_reason = "insufficient horizontal area or vertical text stack"
    result = {
        "position": position,
        "face_avoidance": True,
        "safe_zone": "lower_third" if position in {"lower", "center_lower"} else position,
        "face_box": face_box,
        "max_lines": 3 if role in {"HOOK", "HERO"} else 2,
        "side_layout": {
            "proposed": proposed_side,
            "valid": side_layout_valid,
            "available_width": round(available_width, 3),
            "estimated_lines": estimated_lines,
            "fallback_reason": fallback_reason,
        },
    }
    return result


def _decision_scores(segment: dict[str, Any]) -> dict[str, float]:
    importance = float(segment.get("importance", 0))
    retention = float(segment.get("retention_score", importance))
    values = segment.get("retention_scores", {})
    semantic = str(segment.get("type", "NORMAL")).upper()
    return {
        "hook_strength": float(values.get("hook_strength", segment.get("hook_strength", retention if semantic == "HOOK" else 0.0))),
        "emotional_intensity": float(values.get("emotional_intensity", segment.get("emotional_intensity", segment.get("emotion_score", 0.0)))),
        "information_value": float(values.get("information_value", segment.get("information_value", retention))),
        "visual_importance": float(values.get("visual_importance", segment.get("visual_importance", retention))),
        "assertion_strength": float(values.get("assertion_strength", segment.get("assertion_strength", importance))),
        "semantic_change": float(values.get("semantic_change", segment.get("semantic_change", 0.5))),
        "retention": retention,
        "decision_strength": float(segment.get("decision_strength", importance * 0.45 + retention * 0.55)),
    }


def _text_motion(role: str, semantic_type: str, importance: float, scores: dict[str, float]) -> dict[str, Any]:
    visual = scores["visual_importance"]
    energy = _clamp(visual * 0.58 + scores["emotional_intensity"] * 0.24 + scores["assertion_strength"] * 0.18, 0.0, 1.0)
    if role == "HOOK":
        intensity = _clamp(scores["hook_strength"] * 0.62 + visual * 0.38, 0.72, 0.96)
        return {"preset": "IMPACT_SCALE", "duration": 0.24, "intensity": round(intensity, 3), "font_scale": round(1.08 + intensity * 0.06, 3), "accent_scale": 1.10}
    if role == "PUNCH":
        return {"preset": "HARD_POP", "duration": 0.22, "intensity": round(_clamp(energy, 0.78, 0.94), 3), "font_scale": 1.14, "accent_scale": 1.08}
    if role == "NUMBER":
        return {"preset": "SPRING_IN", "duration": 0.26, "intensity": round(_clamp(energy, 0.68, 0.90), 3), "font_scale": 1.10, "accent_scale": 1.06}
    if role == "HERO":
        preset = "HARD_POP" if semantic_type in {"RESULT", "MONEY", "SOLUTION"} else "SPRING_IN"
        return {"preset": preset, "duration": 0.26, "intensity": round(_clamp(energy, 0.64, 0.88), 3), "font_scale": 1.10, "accent_scale": 1.07}
    if role == "ACCENT":
        preset = "SOFT_POP" if semantic_type not in {"EMOTION", "CONFLICT", "PROBLEM"} else "HARD_POP"
        return {"preset": preset, "duration": 0.20, "intensity": round(_clamp(energy, 0.46, 0.72), 3), "font_scale": 1.02, "accent_scale": 1.09}
    if role == "CONTRAST":
        return {"preset": "SLIDE_SIDE", "duration": 0.24, "intensity": round(_clamp(energy, 0.50, 0.70), 3), "font_scale": 1.0, "accent_scale": 1.05}
    return {"preset": "CALM_REVEAL", "duration": 0.18, "intensity": 0.18, "font_scale": 1.0, "accent_scale": 1.0}


def _template(role: str, requested: str) -> str:
    requested = requested.upper()
    if role == "NUMBER":
        return "NUMBER_HERO"
    if role == "PUNCH":
        return "KEYWORD_HERO"
    if role == "CONTRAST":
        return "CONTRAST_SPLIT"
    if role in {"HOOK", "HERO"}:
        return requested if requested in {"KEYWORD_HERO", "STACKED_TEXT"} else "STACKED_TEXT"
    return requested if requested else "PHRASE_BUILD"


def _segment_role(segment: dict[str, Any], text_events: list[dict[str, Any]]) -> str:
    semantic = str(segment.get("type", "NORMAL")).upper()
    if semantic == "HOOK":
        return "HOOK"
    candidates = [
        str(event.get("scene_type", "NORMAL")).upper()
        for event in text_events
        if event.get("segment_id") == segment.get("id")
    ]
    return max(candidates or ["NORMAL"], key=lambda value: ROLE_PRIORITY.get(value, 0))


def _apply_caption_states(actions: list[dict[str, Any]], face_plan: dict[str, Any]) -> None:
    """Create semantic visual rest without changing transcript or spoken audio.

    Only clearly low-information, low-energy groups can become reduced. One
    representative phrase remains visible; neighbouring service fragments are
    speaker-only. Strong typography is never hidden by this pass.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for action in actions:
        grouped.setdefault(str(action.get("segment_id") or action["id"]), []).append(action)
    for group in grouped.values():
        for action in group:
            action["caption_state"] = (
                "STRONG_TYPOGRAPHY"
                if str(action.get("scene_type", "NORMAL")).upper() in {"HOOK", "HERO", "NUMBER", "PUNCH", "CONTRAST"}
                else "BODY_CAPTION"
            )
        if not face_plan.get("detected") or float(group[0].get("start", 0)) < 3.0:
            continue
        if any(action["caption_state"] == "STRONG_TYPOGRAPHY" for action in group):
            continue
        scores = group[0].get("decision_scores", {})
        low_information = (
            float(scores.get("information_value", 1.0)) < 0.34
            and float(scores.get("visual_importance", 1.0)) < 0.36
            and float(scores.get("decision_strength", 1.0)) < 0.38
        )
        if not low_information or len(group) < 2:
            continue
        anchor = max(
            group,
            key=lambda item: (
                float(item.get("importance", 0)),
                float(item.get("end", 0)) - float(item.get("start", 0)),
                len(str(item.get("text", ""))),
            ),
        )
        for action in group:
            if action is anchor:
                action["caption_state"] = "REDUCED_CAPTION"
                action["reason"] = f"{action.get('reason') or 'normal phrase'}; representative caption retained"
            else:
                action["caption_state"] = "SPEAKER_ONLY"
                action["enabled"] = False
                action["reason"] = "low-information service fragment; speaker expression provides visual rest"

    # A large NUMBER composition already communicates the numeric object.
    # When the immediately following short bridge repeats that same value,
    # keep the spoken audio but give the viewer a visual recovery beat.  This
    # is semantic de-duplication, not a coverage target: non-numeric words,
    # different values, and strong scene types remain visible.
    numeric = re.compile(r"\d+(?:[.,]\d+)?")
    ordered = sorted(actions, key=lambda item: (float(item.get("start", 0)), float(item.get("end", 0))))
    for previous, current in zip(ordered, ordered[1:]):
        if str(previous.get("scene_type", "")).upper() != "NUMBER":
            continue
        repeated = set(numeric.findall(str(previous.get("text", "")))) & set(numeric.findall(str(current.get("text", ""))))
        duration = float(current.get("end", 0)) - float(current.get("start", 0))
        if (
            repeated and current.get("enabled", True)
            and str(current.get("caption_state", "BODY_CAPTION")) == "BODY_CAPTION"
            and str(current.get("scene_type", "NORMAL")).upper() in {"NORMAL", "ACCENT"}
            and duration <= 1.4
            and float(current.get("start", 0)) - float(previous.get("end", 0)) <= 0.12
        ):
            current["caption_state"] = "SPEAKER_ONLY"
            current["enabled"] = False
            current["reason"] = "repeated numeric bridge after NUMBER composition; visual recovery beat"


def _camera_action(
    segment: dict[str, Any], role: str, profile: dict[str, Any], face_plan: dict[str, Any],
    camera_profiles: dict[str, Any],
) -> dict[str, Any] | None:
    rules = profile.get("camera", {})
    importance = float(segment.get("importance", 0))
    scores = _decision_scores(segment)
    retention = scores["retention"]
    visual = scores["visual_importance"]
    emotion = scores["emotional_intensity"]
    hook = scores["hook_strength"]
    decision = scores["decision_strength"]
    if role == "HOOK" and hook >= 0.64:
        effect = "PUNCH_ZOOM"
        scale = _clamp(max(float(rules.get("hero", 1.14)), 1.12 + visual * 0.06), 1.14, 1.18)
        duration, strength = 1.0, _clamp(hook * 0.62 + visual * 0.38, 0.74, 0.98)
    elif role in {"HERO", "PUNCH"} and visual >= 0.60 and decision >= 0.58:
        effect = "PUNCH_ZOOM"
        maximum = 1.18 if role == "PUNCH" else 1.16
        scale = _clamp(float(rules.get("hero", 1.14)) + emotion * 0.015, 1.10, maximum)
        duration, strength = (0.58, _clamp(decision, 0.72, 0.94)) if role == "PUNCH" else (0.86, _clamp(decision, 0.62, 0.88))
    elif role == "NUMBER" and scores["information_value"] >= 0.60 and visual >= 0.52:
        effect = "PUNCH_ZOOM"
        scale = _clamp(max(float(rules.get("strong", 1.10)), 1.10), 1.10, 1.14)
        duration, strength = 0.66, _clamp(decision, 0.64, 0.88)
    elif role in {"ACCENT", "CONTRAST"} and visual >= 0.50 and decision >= 0.50:
        effect = "SUBTLE_ZOOM"
        scale = _clamp(float(rules.get("subtle", 1.055)), 1.035, 1.075)
        duration, strength = 1.08, _clamp(decision, 0.46, 0.72)
    else:
        return None
    camera_profile = camera_profiles.get(role, {})
    modifier = float(camera_profiles.get("style_modifiers", {}).get(profile.get("name"), 1.0))
    if camera_profile:
        configured_scale = 1.0 + (float(camera_profile.get("zoom", scale)) - 1.0) * modifier
        scale = _clamp((scale + configured_scale) / 2, 1.01, 1.19)
        duration = float(camera_profile.get("duration", duration))
    sample = _nearest_face(face_plan, float(segment.get("start", 0)))
    anchor = (
        {"x": round(float(sample["x"]), 4), "y": round(float(sample["y"]), 4)}
        if sample else face_plan.get("cropAnchor", {"x": 0.5, "y": 0.42})
    )
    result = {
        "id": f"camera-{segment['id']}", "action_type": "camera_action",
        "time": round(float(segment["start"]), 3), "duration": duration,
        "effect": effect, "scale": round(scale, 3), "strength": round(float(strength), 3),
        "motion_class": "PUNCH" if effect == "PUNCH_ZOOM" else "PUSH_IN",
        "attack_duration": round(min(duration * 0.34, 0.30 if effect == "PUNCH_ZOOM" else 0.42), 3),
        "hold_duration": round(max(0.12, duration * 0.34), 3),
        "return_scale": 1.0, "settle_duration": round(max(0.34, duration * 0.42), 3),
        "anchor": anchor,
        "easing": str(camera_profile.get("ease", "semantic_spring" if effect == "PUNCH_ZOOM" else "ease_in_out")),
        "movement": round(float(camera_profile.get("movement", 0.3)) * modifier, 3),
        "segment_id": segment["id"], "semantic_type": segment.get("type"),
        "decision_score": round(decision, 3), "visual_importance": round(visual, 3),
        "reason": f"{role.lower()} semantic beat; smooth return to rest", "enabled": True,
    }
    return result


def _append_camera(actions: list[dict[str, Any]], candidate: dict[str, Any], min_gap: float) -> None:
    if not actions:
        actions.append(candidate)
        return
    gap = float(candidate["time"]) - float(actions[-1]["time"])
    if gap >= min_gap:
        actions.append(candidate)
    elif (
        gap >= 1.25
        and float(candidate.get("decision_score", 0)) >= float(actions[-1].get("decision_score", 0)) + 0.10
    ):
        actions[-1] = candidate


def build_director_execution_plan(
    director_plan: dict[str, Any],
    style_profile: dict[str, Any],
    speech_edit_plan: dict[str, Any],
    face_plan: dict[str, Any],
    assets_dir: Path,
    ffprobe: Path,
    camera_profiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    camera_profiles = camera_profiles or {}
    segments = list(director_plan.get("segments", []))
    director_text = list(director_plan.get("text_events", []))
    segment_by_id = {segment["id"]: segment for segment in segments}
    text_actions: list[dict[str, Any]] = []
    for index, event in enumerate(director_text):
        segment = segment_by_id.get(event.get("segment_id"), {})
        semantic_type = str(segment.get("type", "NORMAL")).upper()
        event_role = str(event.get("scene_type", "NORMAL")).upper()
        role = "HOOK" if semantic_type == "HOOK" and index == 0 else event_role
        importance = float(event.get("importance", segment.get("importance", 0)))
        decision_scores = _decision_scores(segment)
        layout = _layout_for(
            role, face_plan, float(event.get("start", 0)), str(event.get("text", "")), style_profile,
        )
        motion = _text_motion(role, semantic_type, importance, decision_scores)
        template = _template(role, str(event.get("template", "")))
        if semantic_type == "QUOTE":
            template = "QUOTE_CARD"
        elif layout["position"] in {"side_left", "side_right"} and role in {"NORMAL", "ACCENT"}:
            template = "SIDE_TEXT"
        elif layout["position"] == "top" and role == "NORMAL":
            template = "TOP_CAPTION"
        color_role = str(event.get("color_role", "text"))
        colors = style_profile.get("colors", {})
        action = {
            "id": f"text-{index + 1:03d}", "action_type": "text_action",
            "start": round(float(event["start"]), 3), "end": round(float(event["end"]), 3),
            "text": event.get("text", ""), "scene_type": role,
            "semantic_type": semantic_type, "segment_id": event.get("segment_id"),
            "template": template,
            "animation": motion["preset"], "motion": motion, "layout": layout,
            "color_role": color_role,
            "color": colors.get("danger" if color_role == "danger" else "accent" if color_role == "accent" else "text"),
            "highlight": {"enabled": role in {"ACCENT", "HOOK", "HERO", "PUNCH", "NUMBER"}, "duration": 0.18, "intensity": round(motion["intensity"], 3)},
            "importance": round(importance, 3),
            "decision_scores": {key: round(value, 3) for key, value in decision_scores.items()},
            "reason": event.get("reason"), "enabled": True,
        }
        text_actions.append(action)

    _apply_caption_states(text_actions, face_plan)

    camera_actions: list[dict[str, Any]] = []
    min_gap = max(1.8, float(style_profile.get("camera", {}).get("min_gap", 3.0)))
    for segment in segments:
        role = _segment_role(segment, director_text)
        candidate = _camera_action(segment, role, style_profile, face_plan, camera_profiles)
        if candidate:
            _append_camera(camera_actions, candidate, min_gap)

    effects = style_profile.get("effects", {})
    polish = style_profile.get("visual_polish", {})
    effect_cooldown = max(3.0, float(polish.get("effect_cooldown", 6.0)))
    sfx_cooldown = max(1.2, float(polish.get("sfx_cooldown", 2.0)))
    same_sfx_cooldown = max(sfx_cooldown, float(polish.get("same_sfx_cooldown", 7.0)))
    visual_actions: list[dict[str, Any]] = []
    audio_actions: list[dict[str, Any]] = []
    last_visual = -100.0
    last_audio = -100.0
    for segment in segments:
        role = _segment_role(segment, director_text)
        timestamp = float(segment.get("start", 0))
        scores = _decision_scores(segment)
        retention = scores["retention"]
        visual_importance = scores["visual_importance"]
        decision_strength = scores["decision_strength"]
        importance = float(segment.get("importance", 0))
        if role == "HOOK" and scores["hook_strength"] >= 0.64:
            visual_actions.append({
                "id": f"visual-{segment['id']}-hook", "action_type": "visual_action",
                "time": timestamp, "duration": 0.30, "type": "GLEAM", "intensity": 0.48,
                "segment_id": segment["id"], "reason": "focus opening hook", "enabled": True,
            })
            last_visual = timestamp
        elif role in {"HERO", "PUNCH"} and visual_importance >= 0.70 and decision_strength >= 0.66 and timestamp - last_visual >= effect_cooldown:
            if effects.get("flash", False):
                visual_actions.append({
                    "id": f"visual-{segment['id']}-flash", "action_type": "visual_action",
                    "time": timestamp, "duration": 0.12, "type": "FLASH", "intensity": 0.28,
                    "segment_id": segment["id"], "reason": "strong semantic transition", "enabled": True,
                })
                last_visual = timestamp
            elif polish.get("allow_blur_impact", False):
                visual_actions.append({
                    "id": f"visual-{segment['id']}-blur", "action_type": "visual_action",
                    "time": timestamp, "duration": 0.16, "type": "BLUR_IMPACT", "intensity": 0.32,
                    "segment_id": segment["id"], "reason": "controlled semantic blur impact", "enabled": True,
                })
                last_visual = timestamp
            if role == "PUNCH" and effects.get("shake") not in {False, "never"} and scores["emotional_intensity"] >= 0.70:
                visual_actions.append({
                    "id": f"visual-{segment['id']}-shake", "action_type": "visual_action",
                    "time": timestamp, "duration": 0.18, "type": "SHAKE", "intensity": 0.42,
                    "segment_id": segment["id"], "reason": "rare punch emphasis", "enabled": True,
                })

        cue: str | None = None
        if role == "HOOK" and scores["hook_strength"] >= 0.64:
            cue = "IMPACT"
        elif role == "HERO" and visual_importance >= 0.66:
            cue = "IMPACT" if decision_strength >= 0.78 else "WHOOSH"
        elif role == "PUNCH" and visual_importance >= 0.72:
            cue = "BASS_HIT"
        elif role == "NUMBER" and scores["information_value"] >= 0.62:
            cue = "CLICK" if decision_strength < 0.78 else "POP"
        elif role == "ACCENT" and visual_importance >= 0.68 and decision_strength >= 0.68:
            cue = "POP"
        audio_rules = style_profile.get("audio", {})
        if cue and audio_rules and audio_rules.get(cue.lower(), True) is False:
            cue = None
        previous_same = max((float(item["time"]) for item in audio_actions if item.get("type") == cue), default=-100.0)
        if cue and timestamp - last_audio >= sfx_cooldown and timestamp - previous_same >= same_sfx_cooldown:
            audio_actions.append({
                "id": f"audio-{segment['id']}-{cue.lower()}", "action_type": "audio_action",
                "time": round(timestamp, 3), "duration": 0.0, "type": cue,
                "file": None, "intensity": round(_clamp(decision_strength, 0.38, 0.88), 3),
                "segment_id": segment["id"], "reason": f"{role.lower()} audio reinforcement", "enabled": True,
            })
            last_audio = timestamp

    last_whoosh = -100.0
    for camera in camera_actions:
        timestamp = float(camera["time"])
        if camera["effect"] != "SUBTLE_ZOOM" or float(camera.get("strength", 0)) < 0.60:
            continue
        if timestamp - last_whoosh < same_sfx_cooldown or timestamp - last_audio < sfx_cooldown or any(abs(float(item["time"]) - timestamp) < 0.35 for item in audio_actions):
            continue
        audio_actions.append({
            "id": f"audio-{camera['segment_id']}-whoosh", "action_type": "audio_action",
            "time": round(timestamp, 3), "duration": 0.0, "type": "WHOOSH",
            "file": None, "intensity": 0.46,
            "segment_id": camera["segment_id"], "reason": "semantic camera transition", "enabled": True,
        })
        last_whoosh = timestamp
    audio_actions.sort(key=lambda item: (float(item["time"]), item["id"]))
    sfx_plan = resolve_sfx_actions(audio_actions, assets_dir / "sfx", ffprobe)
    audio_actions = sfx_plan["actions"]

    synthetic_scenes = [
        {
            "start": float(event.get("start", 0)), "end": float(event.get("end", 0)),
            "text": event.get("text", ""), "importance": event.get("importance", 0),
            "type": event.get("scene_type", "NORMAL"),
        }
        for event in director_text
    ]
    broll_plan = build_broll_plan(
        synthetic_scenes, assets_dir, style_profile, ffprobe,
        director_events=director_plan.get("broll_events", []),
        camera_actions=camera_actions,
    )
    broll_actions: list[dict[str, Any]] = []
    for index, event in enumerate(broll_plan.get("events", [])):
        shots = [dict(shot) for shot in event.get("shots", [])]
        if shots:
            shots[-1]["transition"] = "FADE"
        broll_actions.append({
            **event, "id": f"broll-{index + 1:02d}", "action_type": "broll_action",
            "return_transition": "FADE_TO_SPEAKER", "reason": event.get("reason") or "semantic explanation",
        })

    # Speaker-camera motion is invisible under full-screen B-roll and can create
    # a discontinuity when the edit returns to the face. Remove every overlap.
    camera_actions = [
        camera for camera in camera_actions
        if not any(
            float(camera.get("time", 0)) < float(event.get("to", 0))
            and float(camera.get("time", 0)) + float(camera.get("duration", 0)) > float(event.get("from", 0))
            for event in broll_actions
        )
    ]
    visible_camera_segments = {str(item.get("segment_id")) for item in camera_actions}
    audio_actions = [
        item for item in audio_actions
        if item.get("reason") != "semantic camera transition"
        or str(item.get("segment_id")) in visible_camera_segments
    ]

    action_timeline: list[dict[str, Any]] = []
    for segment in segments:
        segment_id = segment["id"]
        action_timeline.append({
            "segment_id": segment_id, "start": segment["start"], "end": segment["end"],
            "semantic_type": segment.get("type"), "retention_score": segment.get("retention_score"),
            "retention_scores": segment.get("retention_scores", _decision_scores(segment)),
            "decision_strength": segment.get("decision_strength", _decision_scores(segment)["decision_strength"]),
            "reason": segment.get("retention_reason"),
            "text_action_ids": [item["id"] for item in text_actions if item.get("segment_id") == segment_id],
            "camera_action_ids": [item["id"] for item in camera_actions if item.get("segment_id") == segment_id],
            "visual_action_ids": [item["id"] for item in visual_actions if item.get("segment_id") == segment_id],
            "audio_action_ids": [item["id"] for item in audio_actions if item.get("segment_id") == segment_id],
            "broll_action_ids": [item["id"] for item in broll_actions if item.get("segmentId") == segment_id],
        })

    roles = Counter(item["scene_type"] for item in text_actions)
    result = {
        "version": EXECUTION_PLAN_VERSION,
        "profile": style_profile.get("name"),
        "camera_profile_version": 1,
        "source_director_version": director_plan.get("version"),
        "output_duration": speech_edit_plan.get("output_duration"),
        "policy": {
            "semantic_events_only": True, "renderer_makes_decisions": False,
            "face_avoidance": True, "missing_assets": "SKIP",
            "decision_scoring": "retention_v2", "camera_returns_to_rest": True,
            "broll_scope": "semantic_block",
            "camera_modes": ["CALM", "SUBTLE_PUSH", "PUNCH", "RETURN"],
            "camera_under_fullscreen_broll": False,
        },
        "actions": action_timeline,
        "text_actions": text_actions,
        "camera_actions": camera_actions,
        "visual_actions": visual_actions,
        "audio_actions": audio_actions,
        "broll_actions": broll_actions,
        "broll_requests": broll_plan.get("requests", []),
        "broll_policy": broll_plan.get("policy", {}),
        "asset_summary": {
            "broll_available": len(broll_plan.get("library", {}).get("assets", [])),
            "broll_errors": len(broll_plan.get("library", {}).get("errors", [])),
            "sfx_available": len(sfx_plan.get("library", {}).get("assets", [])),
            "sfx_resolved": sum(bool(item.get("resolved")) for item in audio_actions),
            "sfx_errors": len(sfx_plan.get("library", {}).get("errors", [])),
        },
        "summary": {
            "segments": len(segments), "text_actions": len(text_actions),
            "camera_actions": len(camera_actions), "visual_actions": len(visual_actions),
            "audio_actions": len(audio_actions), "broll_actions": len(broll_actions),
            "strong_text_actions": sum(roles[name] for name in ("HOOK", "HERO", "PUNCH", "NUMBER")),
            "calm_segments": sum(_decision_scores(item)["visual_importance"] < 0.45 for item in segments),
            "average_visual_importance": round(sum(_decision_scores(item)["visual_importance"] for item in segments) / max(1, len(segments)), 3),
            "roles": dict(roles),
            "caption_states": dict(Counter(str(item.get("caption_state", "BODY_CAPTION")) for item in text_actions)),
        },
    }
    validate_director_execution_plan(result)
    return result
