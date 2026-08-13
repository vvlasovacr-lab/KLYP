from __future__ import annotations

from typing import Any


HYBRID_MODES = {"hybrid", "clip_hybrid"}


def normalize_renderer_mode(value: str | None) -> str:
    mode = str(value or "legacy").strip().lower()
    if mode == "clip_hybrid":
        return "hybrid"
    if mode not in {"legacy", "hybrid"}:
        raise ValueError(f"Unknown renderer mode: {value}. Expected legacy or hybrid")
    return mode


def _transition(
    *, timestamp: float, source_id: str, kind: str, intensity: float,
    flash_enabled: bool, reason: str,
) -> dict[str, Any]:
    strength = max(0.0, min(1.0, float(intensity)))
    return {
        "time": round(max(0.0, float(timestamp)), 3),
        "duration": round(0.18 + 0.10 * strength, 3),
        "type": kind,
        "sourceActionId": source_id,
        "punch": round(0.012 + 0.022 * strength, 4),
        "blur": round(3.0 + 8.0 * strength, 2),
        "flash": round((0.04 + 0.11 * strength) if flash_enabled else 0.0, 3),
        "reason": reason,
    }


def build_clip_visual_plan(
    execution_plan: dict[str, Any],
    style_profile: dict[str, Any],
    face_plan: dict[str, Any] | None = None,
    resolved_scenes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Translate ShortsAI decisions into Clip-inspired visual parameters.

    This layer deliberately does not infer semantics. Every time and intensity is
    inherited from an existing Director Execution action.
    """
    text_actions = [item for item in execution_plan.get("text_actions", []) if item.get("enabled", True)]
    broll_actions = [item for item in execution_plan.get("broll_actions", []) if item.get("enabled", True)]
    effects = style_profile.get("effects", {})
    colors = style_profile.get("colors", {})
    animation_speed = float(style_profile.get("text", {}).get("animation_speed", 1.0))

    scene_styles: dict[str, dict[str, Any]] = {}
    scene_by_action = {str(item.get("actionId", "")): item for item in (resolved_scenes or [])}
    strong_actions: list[dict[str, Any]] = []
    for action in text_actions:
        action_id = str(action.get("id", ""))
        resolved = scene_by_action.get(action_id, {})
        scene_type = str(resolved.get("semanticRole", action.get("scene_type", "NORMAL"))).upper()
        requested_template = str(resolved.get("template", action.get("template", ""))).upper()
        intensity = max(0.0, min(1.0, float(action.get("motion", {}).get("intensity", action.get("importance", 0.4)))))
        component = (
            "DIRECTOR_TEMPLATE" if requested_template in {"SIDE_TEXT", "TOP_CAPTION", "QUOTE_CARD", "CONTRAST_SPLIT"}
            else
            "TITLE_COMPOSITION" if scene_type in {"HOOK", "HERO", "TITLE"}
            else "SHOUT" if scene_type == "PUNCH"
            else "NUMBER_STAMP" if scene_type == "NUMBER"
            else "ACCENT_WORD" if scene_type == "ACCENT"
            else "NORMAL" if requested_template == "NORMAL"
            else "PHRASE_BUILD"
        )
        scene_styles[action_id] = {
            "component": component,
            "entrySpring": "strong" if scene_type in {"HOOK", "HERO", "PUNCH", "NUMBER"} else "base",
            "stableWordSlots": True,
            "fitToWidth": True,
            "gradientAccent": scene_type in {"HOOK", "HERO", "PUNCH", "NUMBER", "ACCENT"},
            "intensity": round(intensity, 3),
            "motionPreset": str(action.get("motion", {}).get("preset", "CALM_REVEAL")).upper(),
        }
        decision_scores = action.get("decision_scores", {})
        visual_importance = float(decision_scores.get("visual_importance", intensity))
        hook_strength = float(decision_scores.get("hook_strength", intensity if scene_type == "HOOK" else 0.0))
        qualifies_for_transition = (
            scene_type == "HOOK" and hook_strength >= 0.64
            or scene_type in {"HERO", "PUNCH"} and visual_importance >= 0.66
            or scene_type == "NUMBER" and visual_importance >= 0.58
        )
        if qualifies_for_transition:
            strong_actions.append(action)

    transitions: list[dict[str, Any]] = []
    last_semantic = -100.0
    transition_cooldown = max(2.4, float(style_profile.get("visual_polish", {}).get("effect_cooldown", 5.5)) * 0.55)
    for action in strong_actions:
        timestamp = float(action.get("start", 0.0))
        if timestamp - last_semantic < transition_cooldown:
            continue
        intensity = float(action.get("motion", {}).get("intensity", action.get("importance", 0.7)))
        transitions.append(_transition(
            timestamp=timestamp,
            source_id=str(action.get("id", "")),
            kind="SEMANTIC_FOCUS",
            intensity=intensity,
            flash_enabled=bool(effects.get("flash", False)),
            reason=f"execution {str(action.get('scene_type', 'strong')).lower()} beat",
        ))
        last_semantic = timestamp

    transitions.sort(key=lambda item: (item["time"], item["type"]))
    face = face_plan or {}
    return {
        "version": 1,
        "mode": "hybrid",
        "source": "director_execution_plan",
        "principle": "visual execution only; no semantic inference",
        "typography": {
            "stableWordSlots": True,
            "fitToWidth": True,
            "maxWidth": 0.76,
            "safeCenterX": 0.46,
            "accentMaxScale": 1.18,
            "animationSpeed": round(animation_speed, 3),
            "colors": {
                "text": colors.get("text", "#F5F5F5"),
                "accent": colors.get("accent", "#EFCB45"),
                "danger": colors.get("danger", "#E53935"),
            },
            "motionAuthority": "styleConfig.motionPresets + execution motionPreset",
        },
        "safeLayout": {
            "faceDetected": bool(face.get("detected")),
            "avoidRightUi": True,
            "allowRightText": False,
            "lowerThirdTop": 0.54,
            "lowerThirdBottom": 0.81,
        },
        "sceneStyles": scene_styles,
        "transitions": transitions,
        "brollPresentation": {
            "timingAuthority": "director_execution_plan",
            "extendsEvent": False,
            "fadeSeconds": 0.12,
            "entryBlur": 14,
            "exitBlur": 8,
            "baseScale": 1.025,
            "zoomScale": 1.052,
        },
        "summary": {
            "styledScenes": len(scene_styles),
            "strongCompositions": len(strong_actions),
            "semanticTransitions": sum(1 for item in transitions if item["type"] == "SEMANTIC_FOCUS"),
            "brollTransitions": 0,
            "brollEventsExecutedWithoutRetime": len(broll_actions),
        },
    }
