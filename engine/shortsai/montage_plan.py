from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .media import MediaInfo
from .number_formatting import format_numeric_words
from .semantic_analysis import EditingPlan
from .text_composition import validate_text_compositions
from .caption_engine import build_caption_plan


CONTRACT_VERSION = 4
MOTION_NAMES = {
    "micro_shake": "SHAKE", "pop": "POP", "bounce": "BOUNCE", "punch": "PUNCH",
    "slide_up": "SLIDE_UP", "slide_left": "SLIDE_LEFT", "scale_in": "SCALE_IN",
    "flash": "FLASH", "rotate": "ROTATE",
}
SCENE_ANIMATION = {
    "NORMAL": "SLIDE_UP", "ACCENT": "SCALE_IN", "HERO": "BOUNCE", "PUNCH": "PUNCH",
    "NUMBER": "SCALE_IN", "CONTRAST": "SLIDE_LEFT", "TITLE": "BOUNCE",
}
NUMBER_UNIT_TOKENS = {
    "тысяча", "тысячи", "тысяч", "миллион", "миллиона", "миллионов",
    "миллиард", "миллиарда", "миллиардов", "рубль", "рубля", "рублей",
    "доллар", "доллара", "долларов", "евро", "процент", "процента", "процентов",
    "ноль", "нуля", "нулей", "%", "₽", "$", "€",
}
WEAK_NUMBER_LABELS = {"был", "была", "было", "были", "будет", "стало", "это", "составляет"}


def _number_parts(words: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Keep a number and its magnitude/currency unit as one visual object."""
    indices = [index for index, word in enumerate(words) if word.get("category") == "number"]
    if not indices:
        return None, None
    start = indices[0]
    end = start + 1
    while end < len(words):
        token = str(words[end].get("word", "")).lower().strip(".,;:!?")
        category = str(words[end].get("category") or "").lower()
        if token in NUMBER_UNIT_TOKENS or category == "money" and token in NUMBER_UNIT_TOKENS:
            end += 1
            continue
        break
    hero = " ".join(str(word.get("word", "")) for word in words[start:end]).strip()
    remaining = [str(word.get("word", "")) for index, word in enumerate(words) if not start <= index < end]
    normalized_remaining = [value.lower().strip(".,;:!?") for value in remaining if value]
    label = " ".join(remaining).strip()
    if normalized_remaining and all(value in WEAK_NUMBER_LABELS for value in normalized_remaining):
        label = ""
    return hero or None, label or None


def _word_color(category: str | None, role: str, profile: dict[str, Any]) -> str | None:
    if role == "ordinary":
        return None
    colors = profile.get("colors", {})
    return colors.get("danger", "#FF3B30") if category == "problem" else colors.get("accent", "#FFD000")


def _contrast_parts(words: list[dict[str, Any]]) -> dict[str, str] | None:
    markers = {"но", "зато", "вместо", "наоборот", "или", "либо"}
    split = next((index for index, word in enumerate(words) if word["word"].lower().strip(".,!?—–-") in markers), None)
    if split is None or split == 0 or split >= len(words) - 1:
        return None
    return {
        "left": " ".join(word["word"] for word in words[:split]),
        "marker": words[split]["word"],
        "right": " ".join(word["word"] for word in words[split + 1:]),
    }


def _phrase_build_steps(words: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    count = len(words)
    if count <= 1:
        return [{"start": start, "end": end, "visibleWords": list(range(count)), "activeElement": 0 if count else None}]
    steps: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        step_start = start if index == 0 else max(start, float(word["start"]))
        step_end = end if index == count - 1 else max(step_start + 0.03, float(words[index + 1]["start"]))
        steps.append({
            "start": round(step_start, 3), "end": round(min(end, step_end), 3),
            "visibleWords": list(range(index + 1)), "activeElement": index,
        })
    return steps


def _base_scene(scene: Any, profile: dict[str, Any]) -> dict[str, Any]:
    scene_type = scene.scene_type.value.upper()
    motion_by_index = {event.element_index: event for event in scene.motion_events}
    words: list[dict[str, Any]] = []
    for index, word in enumerate(scene.words):
        role = scene.word_roles[index] if index < len(scene.word_roles) else "ordinary"
        item: dict[str, Any] = {
            "word": word.text, "start": round(word.start, 3), "end": round(word.end, 3), "role": role,
            "category": word.category,
        }
        motion = motion_by_index.get(index)
        if motion is not None:
            item.update({
                "effect": MOTION_NAMES.get(motion.motion_preset.value, motion.motion_preset.value.upper()),
                "scale": round(motion.peak_scale, 3), "intensity": round(motion.motion_intensity, 3),
                "duration": round(motion.motion_duration, 3),
            })
        color = _word_color(word.category, role, profile)
        if color:
            item["color"] = color
        words.append(item)
    words, mapped_emphasis = format_numeric_words(words, scene.emphasis_words)
    text = " ".join(word["word"] for word in words)
    result: dict[str, Any] = {
        "start": round(scene.start, 3), "end": round(scene.end, 3), "type": scene_type,
        "text": text.upper() if scene_type in {"HERO", "PUNCH", "TITLE"} else text,
        "importance": round(scene.importance_score, 3), "emotion": round(scene.emotion_score, 3),
        "speechEnergy": round(scene.speech_energy, 3), "motionIntensity": round(scene.motion_intensity, 3),
        "animation": SCENE_ANIMATION[scene_type], "emphasis": mapped_emphasis, "words": words,
        "layout": {"maxLines": 3 if scene_type in {"HERO", "TITLE"} else 2, "maxWords": 2 if scene_type == "PUNCH" else 6 if scene_type in {"HERO", "TITLE"} else 5},
    }
    if scene_type == "NUMBER":
        number, label = _number_parts(words)
        if number:
            result["number"] = number
            # Empty string is an explicit instruction to render no secondary
            # label.  It must not be confused with an absent legacy field.
            result["label"] = label or ""
    if scene_type == "CONTRAST":
        contrast = _contrast_parts(words)
        if contrast:
            result["contrast"] = contrast
        else:
            fallback = "ACCENT" if scene.emphasis_words else "NORMAL"
            result.update({"type": fallback, "animation": SCENE_ANIMATION[fallback]})
    return result


def _apply_profile_types(scenes: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    rules = profile.get("scene", {})
    accent_min = float(rules.get("accent_min_importance", 0.0))
    hero_min = float(rules.get("hero_min_importance", 0.78))
    punch_min = float(rules.get("punch_min_importance", 0.88))
    hero_cooldown = float(rules.get("hero_cooldown", 14.0))
    punch_cooldown = float(rules.get("punch_cooldown", 8.0))
    last_hero = -100.0
    last_punch = -100.0
    for scene in scenes:
        current = scene["type"]
        importance = float(scene["importance"])
        word_count = len(scene.get("words", []))
        if current == "HERO":
            if word_count > 3 or importance < hero_min or float(scene["start"]) - last_hero < hero_cooldown:
                current = "ACCENT"
            else:
                last_hero = float(scene["start"])
        elif current == "PUNCH":
            if importance < punch_min or float(scene["start"]) - last_punch < punch_cooldown:
                current = "ACCENT"
            else:
                last_punch = float(scene["start"])
        elif current == "ACCENT" and importance < accent_min:
            current = "NORMAL"
        elif current == "ACCENT" and importance >= punch_min and word_count <= 2 and float(scene["start"]) - last_punch >= punch_cooldown:
            current = "PUNCH"
            last_punch = float(scene["start"])
        elif current == "ACCENT" and importance >= hero_min and word_count <= 3 and float(scene["start"]) - last_hero >= hero_cooldown:
            current = "HERO"
            last_hero = float(scene["start"])
        scene["type"] = current
        scene["animation"] = SCENE_ANIMATION[current]


def _apply_text_density(scenes: list[dict[str, Any]], profile: dict[str, Any]) -> None:
    density = max(0.45, min(1.0, float(profile.get("text", {}).get("normal_visibility", 1.0))))
    normal_index = 0
    for scene in scenes:
        scene["enabled"] = True
        if scene["type"] != "NORMAL" or float(scene["start"]) < 3.0 or float(scene.get("importance", 0.0)) >= 0.45:
            continue
        normal_index += 1
        scene["enabled"] = ((normal_index * 37) % 100) < density * 100


def _apply_director_text(scenes: list[dict[str, Any]], director_plan: dict[str, Any] | None) -> None:
    if not director_plan:
        return
    events = director_plan.get("text_events", [])
    for scene in scenes:
        event = next((
            item for item in events
            if abs(float(item.get("start", -100)) - float(scene["start"])) <= 0.04
        ), None)
        if event is None:
            continue
        scene_type = str(event.get("scene_type", scene["type"])).upper()
        if scene_type in SCENE_ANIMATION:
            scene["type"] = scene_type
            scene["animation"] = SCENE_ANIMATION[scene_type]
        scene["directorTemplate"] = str(event.get("template", "")).upper() or None
        scene["directorDecision"] = {
            "segmentId": event.get("segment_id"),
            "reason": event.get("reason"),
            "colorRole": event.get("color_role"),
        }


def _apply_execution_text(scenes: list[dict[str, Any]], execution_plan: dict[str, Any] | None) -> None:
    if not execution_plan:
        return
    for scene in scenes:
        action = next((
            item for item in execution_plan.get("text_actions", [])
            if abs(float(item.get("start", -100)) - float(scene["start"])) <= 0.04
        ), None)
        if action is None:
            scene["enabled"] = False
            continue
        semantic_role = str(action.get("scene_type", scene["type"])).upper()
        render_type = "HERO" if semantic_role == "HOOK" else semantic_role
        if render_type in SCENE_ANIMATION:
            scene["type"] = render_type
        scene["semanticRole"] = semantic_role
        scene["enabled"] = bool(action.get("enabled", True))
        scene["captionState"] = str(action.get("caption_state", "BODY_CAPTION"))
        scene["actionType"] = "text_action"
        scene["actionId"] = action.get("id")
        scene["animation"] = str(action.get("animation", SCENE_ANIMATION.get(render_type, "SLIDE_UP"))).upper()
        scene["motionIntensity"] = float(action.get("motion", {}).get("intensity", scene.get("motionIntensity", 0)))
        scene["directorTemplate"] = str(action.get("template", "")).upper() or None
        scene["executionLayout"] = action.get("layout", {})
        scene["executionAction"] = action
        emphasis = scene.get("emphasis", [])
        if emphasis and action.get("highlight", {}).get("enabled"):
            target = int(emphasis[0])
            if 0 <= target < len(scene.get("words", [])):
                motion = action.get("motion", {})
                scene["words"][target].update({
                    "effect": str(motion.get("preset", "POP")).upper(),
                    "scale": round(float(motion.get("accent_scale", 1.08)), 3),
                    "intensity": round(float(motion.get("intensity", 0.6)), 3),
                    "duration": round(float(motion.get("duration", 0.25)), 3),
                    "color": action.get("color"),
                })


def _face_sample(face: dict[str, Any], timestamp: float) -> dict[str, Any] | None:
    samples = face.get("samples", []) if face.get("detected") else []
    return min(samples, key=lambda item: abs(float(item.get("time", 0)) - timestamp)) if samples else None


def _layout_position(kind: str, index: int, face: dict[str, Any], sample: dict[str, Any] | None, text_rules: dict[str, Any]) -> str:
    if kind in {"HERO", "PUNCH", "TITLE"}:
        return "center_lower"
    if kind in {"NUMBER", "CONTRAST"}:
        return "lower"
    if sample:
        face_x = float(sample.get("x", 0.5))
        face_y = float(sample.get("y", 0.4))
        face_w = float(sample.get("w", 0.2))
        face_h = float(sample.get("h", 0.2))
        left_space = face_x - face_w / 2
        right_space = 1.0 - face_x - face_w / 2
        top_space = face_y - face_h / 2
        if kind == "ACCENT" and text_rules.get("side_text", "auto") is not False and face_x > 0.60 and left_space >= 0.34 and index % 4 == 2:
            return "side_left"
        if kind == "ACCENT" and text_rules.get("allow_right_side", False) and face_x < 0.36 and right_space >= 0.40 and index % 4 == 2:
            return "side_right"
        if kind == "NORMAL" and top_space >= 0.29 and index % 11 == 7:
            return "top"
    return "lower"


def _assign_templates(scenes: list[dict[str, Any]], profile: dict[str, Any], face: dict[str, Any]) -> None:
    text_rules = profile.get("text", {})
    top_rate = max(0.0, min(0.5, float(text_rules.get("top_caption_rate", 0.12))))
    top_every = max(4, round(1 / top_rate)) if top_rate else 10_000
    for index, scene in enumerate(scenes):
        kind = scene["type"]
        words = scene.get("words", [])
        midpoint = (float(scene["start"]) + float(scene["end"])) / 2
        sample = _face_sample(face, midpoint)
        position = _layout_position(kind, index, face, sample, text_rules)
        if scene.get("directorTemplate"):
            template = scene["directorTemplate"]
        elif kind == "NUMBER":
            template = "NUMBER_HERO"
        elif kind == "CONTRAST":
            template = "CONTRAST_SPLIT"
        elif kind == "PUNCH" or (kind == "HERO" and len(words) <= 2):
            template = "KEYWORD_HERO"
            emphasis = scene.get("emphasis", [])
            hero_index = emphasis[0] if emphasis else 0
            scene["heroWord"] = words[hero_index]["word"] if words else scene["text"]
        elif kind in {"HERO", "TITLE"}:
            template = "STACKED_TEXT"
        elif any(symbol in scene["text"] for symbol in ('«', '»', '"')) and len(words) >= 4:
            template = "QUOTE_CARD"
        elif position == "top" or top_rate and kind == "NORMAL" and index % top_every == 0:
            template = "TOP_CAPTION"
        elif position in {"side_left", "side_right"}:
            template = "SIDE_TEXT"
        elif text_rules.get("phrase_build", True) and len(words) >= 3:
            template = "PHRASE_BUILD"
        else:
            template = "PHRASE_BUILD"
        scene["template"] = template
        scene["layout"].update({
            "position": position,
            "faceAvoidance": bool(sample),
            "faceBox": ({key: sample[key] for key in ("x", "y", "w", "h")} if sample else None),
        })
        if scene.get("executionLayout"):
            execution_layout = scene["executionLayout"]
            scene["layout"].update({
                "position": execution_layout.get("position", scene["layout"]["position"]),
                "faceAvoidance": execution_layout.get("face_avoidance", scene["layout"]["faceAvoidance"]),
                "faceBox": execution_layout.get("face_box", scene["layout"]["faceBox"]),
                "safeZone": execution_layout.get("safe_zone"),
                "maxLines": execution_layout.get("max_lines", scene["layout"].get("maxLines")),
                "sideLayout": execution_layout.get("side_layout"),
            })
        scene["compositionSteps"] = _phrase_build_steps(words, float(scene["start"]), float(scene["end"])) if template == "PHRASE_BUILD" else [{"start": scene["start"], "end": scene["end"], "visibleWords": list(range(len(words))), "activeElement": scene.get("emphasis", [None])[0] if scene.get("emphasis") else None}]


def _apply_composition_rhythm(scenes: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
    """Choose a semantically valid calm/build variant without random layout."""
    polish = profile.get("visual_polish", {})
    maximum_run = max(2, int(polish.get("composition_cooldown", 4)))
    rest_seconds = max(0.8, float(polish.get("strong_rest_seconds", 1.8)))
    last_strong_end = -100.0
    run_template = None
    run_length = 0
    switches = 0
    for index, scene in enumerate(scenes):
        alternative_applied = False
        role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
        template = str(scene.get("template", "PHRASE_BUILD")).upper()
        protected = template in {"SIDE_TEXT", "TOP_CAPTION", "QUOTE_CARD", "CONTRAST_SPLIT", "NUMBER_HERO", "KEYWORD_HERO", "STACKED_TEXT"}
        words = scene.get("words", [])
        after_strong = float(scene.get("start", 0)) - last_strong_end <= rest_seconds
        sentence_start = index == 0 or str(scenes[index - 1].get("text", "")).rstrip().endswith((".", "!", "?", ";"))
        if role in {"HOOK", "HERO", "PUNCH", "NUMBER"}:
            last_strong_end = float(scene.get("end", scene.get("start", 0)))
        elif not protected and role == "ACCENT":
            template = "ACCENT_WORD"
        elif not protected and role == "NORMAL":
            template = "NORMAL" if after_strong or sentence_start or len(words) <= 2 else "PHRASE_BUILD"

        if template == run_template:
            run_length += 1
        else:
            run_template, run_length = template, 1
        if run_length > maximum_run and role == "NORMAL" and template in {"NORMAL", "PHRASE_BUILD"}:
            alternative = "PHRASE_BUILD" if template == "NORMAL" and len(words) >= 3 else "NORMAL"
            if alternative != template:
                template = alternative
                run_template, run_length = template, 1
                switches += 1
                alternative_applied = True
        scene["template"] = template
        scene["compositionRhythm"] = {
            "afterStrongRest": after_strong, "sentenceStart": sentence_start,
            "maximumIdenticalRun": maximum_run, "semanticAlternativeApplied": alternative_applied,
        }
        scene["compositionSteps"] = (
            _phrase_build_steps(words, float(scene["start"]), float(scene["end"]))
            if template == "PHRASE_BUILD" else [{
                "start": scene["start"], "end": scene["end"],
                "visibleWords": list(range(len(words))),
                "activeElement": scene.get("emphasis", [None])[0] if scene.get("emphasis") else None,
            }]
        )
    return {"maximum_identical_run": maximum_run, "semantic_alternative_switches": switches}


def _retention_phases(scenes: list[dict[str, Any]]) -> None:
    hit_indices = {index for index, scene in enumerate(scenes) if scene["type"] in {"HERO", "PUNCH", "NUMBER"} or float(scene["importance"]) >= 0.82}
    for index, scene in enumerate(scenes):
        if index in hit_indices:
            phase = "HIT"
        elif index + 1 in hit_indices:
            phase = "BUILD"
        elif index - 1 in hit_indices:
            phase = "REST"
        else:
            phase = "CALM"
        scene["retentionPhase"] = phase


def _director_camera_events(events: list[dict[str, Any]], rules: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    min_gap = float(rules.get("min_gap", 3.0))
    for source in sorted(events, key=lambda item: float(item.get("time", 0))):
        kind = str(source.get("type", "ACCENT_ZOOM")).upper()
        strong = kind in {"HERO_ZOOM", "PUNCH_ZOOM"}
        timestamp = float(source.get("time", 0))
        if result and timestamp - float(result[-1]["time"]) < min_gap:
            if strong and result[-1]["effect"] == "SUBTLE_ZOOM":
                result.pop()
            else:
                continue
        scale = float(source.get("scale", rules.get("hero" if strong else "subtle", 1.04)))
        result.append({
            "time": round(timestamp, 3),
            "duration": round(float(source.get("duration", 0.82 if strong else 1.2)), 3),
            "effect": "PUNCH_ZOOM" if strong else "SUBTLE_ZOOM",
            "scale": round(scale, 3),
            "strength": round(float(source.get("strength", min(1.0, (scale - 1.0) / 0.14))), 3),
            "reason": source.get("reason", kind),
            "directorType": kind,
            "segmentId": source.get("segment_id"),
            "retentionPhase": "HIT" if strong else "BUILD",
            "enabled": True,
        })
    return result


def build_montage_plan(
    source: Path,
    media: MediaInfo,
    editing_plan: EditingPlan,
    *,
    speech_edit: dict[str, Any],
    style_profile: dict[str, Any],
    face_plan: dict[str, Any],
    audio_plan: dict[str, Any],
    director_plan: dict[str, Any] | None = None,
    director_execution_plan: dict[str, Any] | None = None,
    broll: list[dict[str, Any]] | None = None,
    output_width: int = 1080,
    output_height: int = 1920,
    output_fps: int = 30,
    camera_drift: float = 0.008,
    editorial_quality: dict[str, Any] | None = None,
    timeline_plan: dict[str, Any] | None = None,
    text_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenes = [_base_scene(scene, style_profile) for scene in editing_plan.scenes]
    _apply_profile_types(scenes, style_profile)
    _apply_director_text(scenes, director_plan)
    _apply_execution_text(scenes, director_execution_plan)
    if not director_execution_plan:
        _apply_text_density(scenes, style_profile)
    _assign_templates(scenes, style_profile, face_plan)
    composition_rhythm = _apply_composition_rhythm(scenes, style_profile)
    composition_safety = validate_text_compositions(
        scenes, style_profile, face_plan, output_width, output_height, text_metrics,
    )
    caption_plan = build_caption_plan(
        scenes, composition_safety, width=output_width, height=output_height,
    )
    _retention_phases(scenes)
    camera: list[dict[str, Any]] = []
    visual: list[dict[str, Any]] = []
    sfx: list[dict[str, Any]] = []
    camera_rules = style_profile.get("camera", {})
    for event in ([] if director_execution_plan else editing_plan.visual_events):
        kind = event.event_type.lower()
        event_duration = round(max(0.0, event.end - event.start), 3)
        if kind == "camera_punch":
            # Semantic analysis decides *where* a camera beat is meaningful.
            # The final cadence is built from the completed text scenes below so
            # a nearby weak beat cannot suppress a HERO/NUMBER punch.
            continue
        elif kind == "sfx":
            if director_plan:
                continue
            cue = str(event.payload.get("cue", "impact")).upper()
            sfx.append({"time": round(event.start, 3), "type": cue, "file": event.payload.get("file"), "intensity": round(event.intensity, 3), "enabled": event.enabled})
        elif kind not in {"broll", "image", "icon"}:
            visual.append({"time": round(event.start, 3), "duration": event_duration, "type": kind.upper(), "intensity": round(event.intensity, 3), "enabled": event.enabled, **event.payload})

    if director_execution_plan:
        camera = [dict(event) for event in director_execution_plan.get("camera_actions", [])]
        visual = [dict(event) for event in director_execution_plan.get("visual_actions", [])]
        sfx = [dict(event) for event in director_execution_plan.get("audio_actions", [])]
    elif director_plan and director_plan.get("camera_events"):
        camera = _director_camera_events(director_plan["camera_events"], camera_rules)
    min_gap = float(camera_rules.get("min_gap", 3.0))
    quiet_gap = max(2.6, min_gap + 0.7)
    for scene in ([] if camera else scenes):
        scene_type = str(scene.get("type", "NORMAL")).upper()
        strong = scene_type in {"HERO", "PUNCH", "NUMBER"}
        emphasis = set(scene.get("emphasis", []))
        emphasized_word = next((word for word in scene.get("words", []) if word.get("word") in emphasis), None)
        event_time = float(emphasized_word.get("start", scene["start"]) if emphasized_word else scene["start"])
        since_last = event_time - float(camera[-1]["time"]) if camera else 100.0

        if strong:
            if camera and since_last < 1.75 and camera[-1]["effect"] == "SUBTLE_ZOOM":
                camera.pop()
                since_last = event_time - float(camera[-1]["time"]) if camera else 100.0
            if since_last < max(1.8, min_gap * 0.72):
                continue
            scale_key = "hero" if scene_type == "HERO" else "strong"
            scale = float(camera_rules.get(scale_key, 1.1))
            duration = 0.62 if scene_type == "PUNCH" else 0.82
            camera.append({
                "time": round(event_time, 3), "duration": duration,
                "effect": "PUNCH_ZOOM", "scale": round(scale, 3),
                "strength": round(min(1.0, (scale - 1.0) / 0.14), 3),
                "reason": scene_type, "retentionPhase": "HIT", "enabled": True,
            })
        elif since_last >= quiet_gap and (float(scene.get("importance", 0.0)) >= 0.45 or not camera):
            scale = float(camera_rules.get("subtle", 1.04))
            camera.append({
                "time": round(float(scene["start"]), 3), "duration": 1.35,
                "effect": "SUBTLE_ZOOM", "scale": round(scale, 3),
                "strength": round(min(0.55, (scale - 1.0) / 0.12), 3),
                "reason": scene_type, "retentionPhase": "BUILD", "enabled": True,
            })

    if director_plan and not director_execution_plan:
        sfx.extend({
            "time": round(float(event.get("time", 0)), 3),
            "type": str(event.get("type", "IMPACT")).upper(),
            "file": event.get("file"),
            "intensity": round(float(event.get("intensity", 0.6)), 3),
            "segmentId": event.get("segment_id"),
            "reason": event.get("reason"),
            "enabled": event.get("enabled", True),
        } for event in director_plan.get("sfx_events", []))

    effects = style_profile.get("effects", {})
    last_effect = -100.0
    for scene in ([] if director_execution_plan else scenes):
        if scene["retentionPhase"] != "HIT" or float(scene["start"]) - last_effect < 7.0:
            continue
        if effects.get("flash") and float(scene["importance"]) >= 0.84:
            visual.append({"time": scene["start"], "duration": 0.12, "type": "FLASH", "intensity": 0.34, "enabled": True})
        if effects.get("glitch") and scene["type"] in {"HERO", "PUNCH"} and float(scene["importance"]) >= 0.9:
            visual.append({"time": scene["start"], "duration": 0.18, "type": "GLITCH", "intensity": 0.55, "enabled": True})
        if effects.get("monochrome") and scene["type"] == "HERO":
            visual.append({"time": scene["start"], "duration": min(2.5, scene["end"] - scene["start"]), "type": "MONOCHROME", "intensity": 1.0, "enabled": True})
        last_effect = float(scene["start"])

    output_duration = float(speech_edit.get("output_duration", media.duration))
    return {
        "version": CONTRACT_VERSION,
        "source": {"file": str(source.resolve()), "duration": media.duration, "width": media.width, "height": media.height, "fps": media.fps, "hasAudio": media.has_audio},
        "output": {"duration": round(output_duration, 3), "width": output_width, "height": output_height, "fps": output_fps},
        "styleProfile": style_profile,
        "speechEdit": speech_edit,
        "editorialQuality": editorial_quality or {},
        "timelinePlan": timeline_plan or {},
        "captionPlan": caption_plan,
        "compositionSafety": composition_safety,
        "compositionRhythm": composition_rhythm,
        "face": face_plan,
        "audio": audio_plan,
        "director": director_plan or {},
        "execution": director_execution_plan or {},
        "scenes": scenes, "camera": camera, "visual": visual, "sfx": sfx,
        "broll": ([dict(event) for event in director_execution_plan.get("broll_actions", [])] if director_execution_plan else broll or []),
        "brollRequests": (director_execution_plan.get("broll_requests", []) if director_execution_plan else []),
        "config": {
            "cameraDrift": round(camera_drift * float(camera_rules.get("drift_multiplier", 1.0)), 5),
            "baseCameraScale": round(float(camera_rules.get("base_scale", 1.0)), 4),
        },
    }


def create_preview_events(plan: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for removal in plan.get("speechEdit", {}).get("removals", []):
        events.append({"time": removal["start"], "type": "SPEECH_REMOVE", "word": removal.get("text", ""), "effect": removal["reason"], "enabled": True})
    for phrase in plan.get("speechEdit", {}).get("weak_phrases", []):
        events.append({"time": phrase["start"], "type": "WEAK_PHRASE", "word": phrase.get("text", ""), "effect": phrase.get("decision", "KEEP"), "enabled": True})
    for segment in plan.get("speechEdit", {}).get("timeline", []):
        if segment.get("transition") == "JUMP_CUT":
            events.append({"time": segment["output_start"], "type": "JUMP_CUT", "word": "", "effect": "JUMP_CUT", "enabled": True})
        elif segment.get("transition") == "SPEED_CHANGE":
            events.append({"time": segment["output_start"], "type": "SPEED_CHANGE", "word": "", "effect": f"{segment.get('speed', 1)}x", "enabled": True})
    for segment in plan.get("director", {}).get("segments", []):
        events.append({
            "time": segment.get("start", 0), "type": "DIRECTOR_DECISION",
            "word": segment.get("text", ""), "effect": "+".join(segment.get("recommended_action", [])),
            "contentType": segment.get("type"), "retentionScore": segment.get("retention_score"),
            "enabled": True,
        })
    execution = plan.get("execution", {})
    for section, event_type in (
        ("text_actions", "EXEC_TEXT"), ("camera_actions", "EXEC_CAMERA"),
        ("visual_actions", "EXEC_VISUAL"), ("audio_actions", "EXEC_AUDIO"),
        ("broll_actions", "EXEC_BROLL"),
    ):
        for action in execution.get(section, []):
            events.append({
                "time": action.get("start", action.get("time", action.get("from", 0))),
                "type": event_type, "actionId": action.get("id"),
                "sceneType": action.get("scene_type", action.get("semantic_type")),
                "word": action.get("text", action.get("reason", "")),
                "effect": action.get("animation", action.get("effect", action.get("type", section.upper()))),
                "reason": action.get("reason"), "enabled": action.get("enabled", True),
            })
    for scene in plan.get("scenes", []):
        events.append({"time": scene["start"], "type": "TEXT_SCENE", "sceneType": scene["type"], "template": scene.get("template"), "phase": scene.get("retentionPhase"), "word": scene["text"], "effect": scene.get("animation")})
        for word in scene.get("words", []):
            if word.get("effect"):
                events.append({"time": word["start"], "type": "WORD_MOTION", "sceneType": scene["type"], "word": word["word"], "effect": word["effect"], "intensity": word.get("intensity")})
    for section, event_type in (("camera", "CAMERA"), ("visual", "VISUAL"), ("sfx", "SFX"), ("broll", "BROLL")):
        for event in plan.get(section, []):
            events.append({"time": event.get("time", event.get("from", 0)), "type": event_type, "word": event.get("word", event.get("text", event.get("reason", ""))), "effect": event.get("effect", event.get("type", section.upper())), "enabled": event.get("enabled", True)})
    for request in plan.get("brollRequests", []):
        events.append({
            "time": request.get("time", 0), "type": "BROLL_REQUEST",
            "word": request.get("text", ""), "effect": request.get("status", "UNRESOLVED"),
            "query": request.get("query", []), "enabled": request.get("status") == "MATCHED",
        })
    return sorted(events, key=lambda event: (float(event["time"]), event["type"]))


def plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(scene["type"] for scene in plan.get("scenes", []))
    templates = Counter(scene.get("template", "UNKNOWN") for scene in plan.get("scenes", []))
    speech = plan.get("speechEdit", {})
    enabled_broll = [event for event in plan.get("broll", []) if event.get("enabled", True)]
    broll_duration = sum(max(0.0, float(event.get("to", 0)) - float(event.get("from", 0))) for event in enabled_broll)
    output_duration = max(0.001, float(plan.get("output", {}).get("duration", 0.001)))
    unique_broll_assets = {
        str(shot.get("assetId", shot.get("file", "")))
        for event in enabled_broll for shot in event.get("shots", [event])
        if shot.get("assetId") or shot.get("file")
    }
    return {
        **{name: counts.get(name, 0) for name in ("NORMAL", "ACCENT", "HERO", "PUNCH", "NUMBER", "CONTRAST", "TITLE")},
        "templates": dict(templates),
        "camera_events": sum(event.get("enabled", True) for event in plan.get("camera", [])),
        "motion_events": sum(bool(word.get("effect")) for scene in plan.get("scenes", []) for word in scene.get("words", [])),
        "visible_text_scenes": sum(scene.get("enabled", True) for scene in plan.get("scenes", [])),
        "visual_events": sum(event.get("enabled", True) for event in plan.get("visual", [])),
        "broll_bursts": sum(event.get("enabled", True) for event in plan.get("broll", [])),
        "broll_duration": round(broll_duration, 3),
        "broll_coverage": round(broll_duration / output_duration, 4),
        "broll_unique_assets": len(unique_broll_assets),
        "broll_requests": len(plan.get("brollRequests", [])),
        "broll_unresolved": sum(request.get("status") != "MATCHED" for request in plan.get("brollRequests", [])),
        "jump_cuts": sum(segment.get("transition") == "JUMP_CUT" for segment in speech.get("timeline", [])),
        "removed_fillers": len(speech.get("removed_fillers", [])),
        "weak_phrases": len(speech.get("weak_phrases", [])),
        "removed_duration": float(speech.get("removed_duration", 0.0)),
        "removed_silence": float(speech.get("statistics", {}).get("removedSilence", 0.0)),
        "compression_saved": float(speech.get("statistics", {}).get("savedByCompression", 0.0)),
        "speed_changes": int(speech.get("statistics", {}).get("speedChanges", 0)),
        "hook_score": float(speech.get("hook", {}).get("score", 0.0)),
        "director_profile": plan.get("director", {}).get("profile"),
        "director_retention": float(plan.get("director", {}).get("retention_score", 0.0)),
        "director_segments": len(plan.get("director", {}).get("segments", [])),
        "execution_version": plan.get("execution", {}).get("version"),
        "execution_text_actions": len(plan.get("execution", {}).get("text_actions", [])),
        "execution_camera_actions": len(plan.get("execution", {}).get("camera_actions", [])),
        "execution_visual_actions": len(plan.get("execution", {}).get("visual_actions", [])),
        "execution_audio_actions": len(plan.get("execution", {}).get("audio_actions", [])),
        "execution_broll_actions": len(plan.get("execution", {}).get("broll_actions", [])),
    }
