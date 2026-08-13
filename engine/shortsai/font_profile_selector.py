from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .font_inventory import build_font_manifest, resolve_manifest_font


FONT_SELECTION_VERSION = 1


def load_font_library(path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError("font_profiles.json must contain production profiles")
    return {str(key).upper(): dict(value) for key, value in data.items()}


def _stable_seed(source_identity: Any, style_profile: str, content: dict[str, Any]) -> str:
    payload = {
        "source": source_identity,
        "style": style_profile,
        "topic": content.get("topic"),
        "format": content.get("format"),
        "pace": content.get("delivery", {}).get("pace"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _preferred_profile(style_name: str, content: dict[str, Any]) -> tuple[str, str]:
    style = style_name.upper()
    topic = str(content.get("topic", "general")).lower()
    format_name = str(content.get("format", "talking_head")).lower()
    pace = str(content.get("delivery", {}).get("pace", "medium")).lower()
    if style in {"AGGRESSIVE_SOCIAL", "HIGH_RETENTION", "AGGRESSIVE_RED", "VIRAL_SHORTS", "BROLL_BURST"}:
        return "SOCIAL_AGGRESSIVE", "high-retention/aggressive style compatibility"
    if style in {"PODCAST_PREMIUM", "PODCAST", "CINEMATIC_STORY", "CINEMATIC"} or format_name == "podcast":
        return "PODCAST_PREMIUM", "podcast/story format prioritizes calm BODY typography"
    if topic == "technology" or (format_name == "education" and pace in {"medium", "fast"}):
        return "MODERN_TECH", "technology/education geometry and information density"
    return "SOCIAL_CLEAN", "clean general/expert social typography"


def _variant(profile_id: str, profile: dict[str, Any], content: dict[str, Any], seed: str) -> tuple[str, str]:
    variants = profile.get("variants", {})
    if not variants:
        raise ValueError(f"Font profile {profile_id} has no variants")
    default = str(profile.get("default_variant") or sorted(variants)[0]).upper()
    # Controlled variants are content rules, never a per-scene random choice.
    if profile_id == "SOCIAL_CLEAN" and "MANROPE" in variants:
        density = float(content.get("editParameters", {}).get("textDensity", 0.65))
        energy = float(content.get("contentAnalysis", content).get("delivery", {}).get("energyScore", 0.4))
        if density <= 0.68 and energy <= 0.55:
            return "MANROPE", "calmer delivery and lower caption density"
    if default not in variants:
        raise ValueError(f"Default variant {default} not found in {profile_id}")
    return default, f"deterministic default for {profile_id}; seed={seed}"


def _validate_assets(fonts_root: Path, profile_id: str, variant_id: str, value: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = build_font_manifest(fonts_root, fonts_root / "font_manifest.json")
    assets = value.get("font_assets", {})
    required = {"body", "display", "hero"}
    if not required.issubset(assets):
        raise ValueError(f"{profile_id}/{variant_id} is missing font roles: {sorted(required - set(assets))}")
    resolved = []
    for role in ("body", "display", "hero"):
        asset = assets[role]
        path, record = resolve_manifest_font(fonts_root, manifest, str(asset.get("relativePath", "")))
        if path is None or record is None:
            status = record.get("validation_status") if record else "NOT_FOUND"
            raise ValueError(f"{profile_id}/{variant_id}/{role} rejected by font manifest: {status}")
        resolved.append({
            "role": role, "family": asset.get("alias") or record["family"],
            "file": record["relative_path"], "weight": int(asset.get("weight", record.get("weight") or 400)),
            "validation_status": record["validation_status"],
        })
    return resolved


def resolve_profile_variant(
    font_profiles_path: Path, fonts_root: Path, profile_id: str, variant_id: str | None = None,
) -> dict[str, Any]:
    library = load_font_library(font_profiles_path)
    key = profile_id.upper()
    if key not in library:
        raise ValueError(f"Unknown font profile {profile_id!r}")
    definition = library[key]
    chosen = (variant_id or definition.get("default_variant") or "DEFAULT").upper()
    variants = definition.get("variants", {})
    if chosen not in variants:
        raise ValueError(f"Unknown font variant {key}/{chosen}")
    profile = copy.deepcopy(variants[chosen])
    profile["id"] = key
    profile["variant_id"] = chosen
    profile["description"] = definition.get("description", "")
    _validate_assets(fonts_root, key, chosen, profile)
    return profile


def select_font_profile(
    font_profiles_path: Path,
    fonts_root: Path,
    style_profile: str,
    style_decision: dict[str, Any],
    source_identity: Any,
    persisted: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content = style_decision.get("contentAnalysis", style_decision)
    if persisted:
        profile_id = str(persisted["font_profile_id"]).upper()
        variant_id = str(persisted["variant_id"]).upper()
        seed = str(persisted.get("seed") or _stable_seed(source_identity, style_profile, content))
        reason = "reused persisted job font selection"
    else:
        profile_id, profile_reason = _preferred_profile(style_profile, content)
        seed = _stable_seed(source_identity, style_profile, content)
        definition = load_font_library(font_profiles_path)[profile_id]
        variant_id, variant_reason = _variant(profile_id, definition, style_decision, seed)
        reason = f"{profile_reason}; {variant_reason}"
    profile = resolve_profile_variant(font_profiles_path, fonts_root, profile_id, variant_id)
    files = {
        role: profile["font_assets"][role]["relativePath"]
        for role in ("body", "display", "hero")
    }
    return {
        "version": FONT_SELECTION_VERSION,
        "font_profile_id": profile_id,
        "variant_id": variant_id,
        "seed": seed,
        "selection_reason": reason,
        "style_profile": style_profile,
        "style_confidence": style_decision.get("confidence"),
        "content_format": content.get("format"),
        "topic": content.get("topic"),
        "pace": content.get("delivery", {}).get("pace"),
        "caption_density": style_decision.get("editParameters", {}).get("textDensity"),
        "body_font_file": files["body"],
        "display_font_file": files["display"],
        "hero_font_file": files["hero"],
        "font_fallbacks": 0,
        "font_role_fallbacks": [],
        "profile": profile,
    }
