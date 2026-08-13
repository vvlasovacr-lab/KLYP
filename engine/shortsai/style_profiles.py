from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


PROFILE_ALIASES = {
    "MONEY": "CLEAN_YELLOW",
    "AGGRESSIVE": "AGGRESSIVE_RED",
    "PODCAST_NOIR": "PODCAST",
}


def load_style_profiles(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("style_profiles.json must contain at least one profile")
    return {str(name).upper(): dict(value) for name, value in data.items()}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key == "extends":
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def get_style_profile(path: Path, name: str) -> dict[str, Any]:
    profiles = load_style_profiles(path)
    requested = name.upper()
    key = PROFILE_ALIASES.get(requested, requested)
    if key not in profiles:
        raise ValueError(f"Unknown style profile {name!r}. Available: {', '.join(sorted(profiles))}")
    raw = copy.deepcopy(profiles[key])
    parent_name = str(raw.get("extends", "")).upper()
    if parent_name:
        if parent_name not in profiles or parent_name == key:
            raise ValueError(f"Invalid style profile inheritance: {key} -> {parent_name}")
        raw = _deep_merge(profiles[parent_name], raw)
    profile = {"name": key, "requestedAs": requested, **raw}
    resources = (
        ("font_profile", "fontProfile", "font_profiles.json"),
        ("visual_profile", "visualProfile", "visual_profiles.json"),
    )
    for reference_key, output_key, filename in resources:
        resource_path = path.parent / filename
        reference = str(profile.get(reference_key, "")).upper()
        if reference and resource_path.is_file():
            values = json.loads(resource_path.read_text(encoding="utf-8"))
            if reference in values:
                selected = copy.deepcopy(values[reference])
                if reference_key == "font_profile" and selected.get("variants"):
                    variant_id = str(selected.get("default_variant") or sorted(selected["variants"])[0]).upper()
                    selected = copy.deepcopy(selected["variants"][variant_id])
                    selected.update({"id": reference, "variant_id": variant_id})
                profile[output_key] = selected
    motion_path = path.parent / "motion_profiles.json"
    if motion_path.is_file():
        profile["motionPresets"] = json.loads(motion_path.read_text(encoding="utf-8")).get("presets", {})
    return profile


def merge_render_style(base: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    result.setdefault("colors", {}).update(profile.get("colors", {}))
    result["animationSpeed"] = float(profile.get("text", {}).get("animation_speed", result.get("animationSpeed", 1.0)))
    result["profileName"] = profile["name"]
    result["effects"] = copy.deepcopy(profile.get("effects", {}))
    result["motionPresets"] = copy.deepcopy(profile.get("motionPresets", {}))
    result["visualProfile"] = copy.deepcopy(profile.get("visualProfile", {}))
    font_profile = profile.get("fontProfile", {})
    if font_profile:
        result.setdefault("font", {})["families"] = {
            role: list(font_profile.get(role, result.get("font", {}).get("families", {}).get(role, [])))
            for role in ("body", "display", "hero", "punch")
        }
        result["font"]["weight"] = int(font_profile.get("weight", result["font"].get("weight", 800)))
        for source_key, target_key in (("body_profile", "body"), ("display_profile", "display"), ("hero_profile", "hero")):
            if font_profile.get(source_key):
                result.setdefault("typographyProfiles", {}).setdefault(target_key, {}).update(
                    copy.deepcopy(font_profile[source_key])
                )
        result["font"]["assets"] = copy.deepcopy(font_profile.get("font_assets", {}))
        result["font"]["roleMap"] = copy.deepcopy(font_profile.get("role_map", {}))
        for scene_role, font_role in result["font"]["roleMap"].items():
            result.setdefault("typographyProfiles", {}).setdefault("roles", {}).setdefault(scene_role, {})["fontProfile"] = font_role
        result["fontSelection"] = copy.deepcopy(profile.get("fontSelection", {}))
    typography = profile.get("typography", {})
    scale = float(typography.get("scale", 1.0))
    for key, value in list(result.get("fontSize", {}).items()):
        role_scale = (
            float(typography.get("hero_scale", 1.0)) if key in {"hero", "punch"}
            else float(typography.get("accent_scale", 1.0)) if key == "accent"
            else 1.0
        )
        result["fontSize"][key] = round(float(value) * scale * role_scale)
    result["outline"] = round(float(result.get("outline", 4)) * float(typography.get("outline_scale", 1.0)), 2)
    if "line_height" in typography:
        result["lineHeight"] = float(typography["line_height"])
    result["visualPolish"] = copy.deepcopy(profile.get("visual_polish", {
        "composition_cooldown": 4, "strong_rest_seconds": 2.0,
        "effect_cooldown": 7.0, "sfx_cooldown": 2.5,
        "same_sfx_cooldown": 8.0, "camera_dead_zone": 0.016,
        "camera_smoothing_window": 5, "allow_blur_impact": False,
        "max_strong_events_2s": 2,
    }))
    return result
