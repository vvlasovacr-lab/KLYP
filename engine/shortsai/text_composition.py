from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


_FONT_CACHE: dict[tuple[str, int], Any] = {}
_SFNT_CACHE: dict[str, Any] = {}


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _face_sample(face_plan: dict[str, Any], timestamp: float) -> dict[str, Any] | None:
    samples = face_plan.get("samples", []) if face_plan.get("detected") else []
    return min(samples, key=lambda item: abs(float(item.get("time", 0)) - timestamp)) if samples else None


def _face_envelope(
    face_plan: dict[str, Any], start: float, end: float, width: int, height: int,
    metrics: dict[str, Any],
) -> dict[str, Any] | None:
    samples = face_plan.get("samples", []) if face_plan.get("detected") else []
    if not samples:
        return None
    selected = [item for item in samples if start - 0.15 <= float(item.get("time", 0)) <= end + 0.15]
    if not selected:
        nearest = _face_sample(face_plan, (start + end) / 2)
        selected = [nearest] if nearest else []
    selected = [item for item in selected if item and all(key in item for key in ("x", "y", "w", "h"))]
    if not selected:
        return None
    pad_x = (float(metrics.get("face_safety_padding", 44)) + float(metrics.get("camera_safety_padding", 24))) / width
    pad_y = (float(metrics.get("face_safety_padding", 44)) + float(metrics.get("camera_safety_padding", 24))) / height
    left = min(float(item["x"]) - float(item["w"]) / 2 for item in selected) - pad_x
    right = max(float(item["x"]) + float(item["w"]) / 2 for item in selected) + pad_x
    top = min(float(item["y"]) - float(item["h"]) / 2 for item in selected) - pad_y
    bottom = max(float(item["y"]) + float(item["h"]) / 2 for item in selected) + pad_y
    left, right = _clamp(left), _clamp(right)
    top, bottom = _clamp(top), _clamp(bottom)
    return {
        "x": round((left + right) / 2, 4), "y": round((top + bottom) / 2, 4),
        "w": round(right - left, 4), "h": round(bottom - top, 4),
        "sample_count": len(selected), "method": "temporal_face_envelope",
    }


def _overlap(left: dict[str, float], right: dict[str, float]) -> float:
    x1, y1 = max(left["x"], right["x"]), max(left["y"], right["y"])
    x2, y2 = min(left["x"] + left["w"], right["x"] + right["w"]), min(left["y"] + left["h"], right["y"] + right["h"])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    return (x2 - x1) * (y2 - y1) / max(1.0, min(left["w"] * left["h"], right["w"] * right["h"]))


def _role_profile(scene: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
    profile = dict(metrics.get("typography_profiles", {}).get("roles", {}).get(role, {}))
    # A multi-word HOOK/HERO is still a display composition, but a very wide
    # HERO face can force four readable words into a three-row ladder. Use the
    # job's validated DISPLAY face for the whole composition in that case.
    # The semantic role and hierarchy remain HOOK/HERO; supporting words never
    # become a separate tiny caption and no scene-specific font is introduced.
    if (
        role in {"HOOK", "HERO", "TITLE"}
        and len(scene.get("words", [])) >= 3
        and metrics.get("typography_profiles", {}).get("display")
    ):
        profile["fontProfile"] = "display"
    return profile


def _font_profile_name(role: str, metrics: dict[str, Any], role_profile: dict[str, Any] | None = None) -> str:
    configured = (role_profile or {}).get("fontProfile") or metrics.get("font_role_map", {}).get(role)
    if configured in {"body", "display", "hero"}:
        return str(configured)
    return "hero" if role in {"HOOK", "HERO", "TITLE", "PUNCH", "NUMBER"} else "body"


def _font_size(scene: dict[str, Any], metrics: dict[str, Any]) -> float:
    role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
    if role in {"NUMBER", "PUNCH"}:
        value = metrics.get("punch_font_size", 132)
    elif role in {"HOOK", "HERO", "TITLE"}:
        value = metrics.get("hero_font_size", 112)
    else:
        value = metrics.get("font_size", 64)
    profile = _role_profile(scene, metrics)
    execution_scale = float(scene.get("executionAction", {}).get("motion", {}).get("font_scale", 1.0))
    requested = float(value) * float(profile.get("scale", 1.0)) * execution_scale
    profile_name = _font_profile_name(role, metrics, profile)
    font_profile = metrics.get("typography_profiles", {}).get(profile_name, {})
    return _clamp(
        requested,
        float(font_profile.get("minSize", 1.0)),
        float(font_profile.get("maxSize", max(requested, 200.0))),
    )


def _word_width(
    word: str, font_size: float, emphasized: bool, metrics: dict[str, Any], role: str,
    role_profile: dict[str, Any] | None = None,
) -> float:
    clean = str(word).strip()
    role_profile = role_profile or metrics.get("typography_profiles", {}).get("roles", {}).get(role, {})
    profile_name = _font_profile_name(role, metrics, role_profile)
    font_file = metrics.get(f"{profile_name}_font_file")
    tracking = float(role_profile.get("tracking", 0.0))
    # Display compositions keep supporting words at the same readable tier;
    # the renderer emphasizes them through entry motion/composition. Applying
    # the body accent ratio here would falsely turn a balanced two-line HOOK
    # into a three-line ladder.
    accent_scale = (
        float(role_profile.get("accentScale", 1.18))
        if emphasized and profile_name == "body" else 1.0
    )
    measured_size = font_size * accent_scale
    if font_file and Path(str(font_file)).is_file():
        try:
            from PIL import ImageFont  # type: ignore
            key = (str(font_file), max(1, round(measured_size)))
            font = _FONT_CACHE.get(key)
            if font is None:
                font = ImageFont.truetype(str(font_file), key[1])
                _FONT_CACHE[key] = font
            left, _, right, _ = font.getbbox(clean or " ")
            return max(measured_size * 0.45, float(right - left) + max(0, len(clean) - 1) * tracking)
        except (ImportError, OSError, ValueError):
            pass
        try:
            from .font_inventory import SfntFont
            path_key = str(Path(str(font_file)).resolve())
            sfnt = _SFNT_CACHE.get(path_key)
            if sfnt is None:
                sfnt = SfntFont.open(Path(path_key))
                _SFNT_CACHE[path_key] = sfnt
            return max(measured_size * 0.45, sfnt.text_advance(clean or " ", measured_size, tracking))
        except (OSError, ValueError, KeyError):
            pass
    wide = sum(character.upper() in "ЖШЩМWQЮФ" for character in clean)
    narrow = sum(character.lower() in "il1тг" for character in clean)
    factor = 0.59 + wide * 0.025 / max(1, len(clean)) - narrow * 0.04 / max(1, len(clean))
    return max(measured_size * 0.55, len(clean) * measured_size * factor)


def _wrap_layout(
    words: Sequence[dict[str, Any]], font_size: float, available_width: float,
    emphasis: set[int], metrics: dict[str, Any], role: str, gap: float = 12.0,
    role_profile: dict[str, Any] | None = None,
) -> tuple[list[float], list[list[int]]]:
    lines: list[float] = []
    indices: list[list[int]] = []
    occupied = 0.0
    current: list[int] = []
    for index, word in enumerate(words):
        width = _word_width(
            str(word.get("word", "")), font_size,
            index in emphasis or word.get("role") != "ordinary", metrics, role, role_profile,
        )
        proposed = width if occupied == 0 else occupied + gap + width
        if occupied and proposed > available_width:
            lines.append(occupied); indices.append(current)
            occupied = width; current = [index]
        else:
            occupied = proposed
            current.append(index)
    if occupied or not lines:
        lines.append(occupied); indices.append(current)
    return lines, indices


def _wrap(
    words: Sequence[dict[str, Any]], font_size: float, available_width: float,
    emphasis: set[int], metrics: dict[str, Any], role: str, gap: float = 12.0,
    role_profile: dict[str, Any] | None = None,
) -> list[float]:
    return _wrap_layout(words, font_size, available_width, emphasis, metrics, role, gap, role_profile)[0]


def _container(
    position: str, width: int, height: int, metrics: dict[str, Any], face: dict[str, Any] | None,
) -> dict[str, float]:
    horizontal = float(metrics.get("horizontal_margin", 92))
    left_margin = float(metrics.get("left_margin", horizontal))
    right_margin = float(metrics.get("right_margin", horizontal))
    top_margin = float(metrics.get("top_margin", 96))
    bottom = float(metrics.get("bottom_margin", 300))
    animation = float(metrics.get("animation_padding", 34))
    safe_left, safe_right = left_margin + animation, width - right_margin - animation
    safe_top, safe_bottom = top_margin + animation, height - bottom - animation
    if position in {"side_left", "side_right"} and face:
        face_left = (float(face["x"]) - float(face["w"]) / 2) * width
        face_right = (float(face["x"]) + float(face["w"]) / 2) * width
        if position == "side_left":
            x, right = safe_left, min(safe_right, face_left - 34)
        else:
            x, right = max(safe_left, face_right + 34), safe_right
        return {"x": x, "y": max(safe_top, height * 0.34), "w": max(0.0, right - x), "h": min(height * 0.34, safe_bottom - height * 0.34)}
    top = {
        "top": max(safe_top, height * 0.08), "center": height * 0.43,
        "center_lower": height * 0.54, "lower": height * 0.61,
    }.get(position, height * 0.61)
    target_height = {"top": height * 0.22, "center": height * 0.25, "center_lower": height * 0.24, "lower": height * 0.21}.get(position, height * 0.21)
    return {"x": safe_left, "y": max(safe_top, top), "w": max(0.0, safe_right - safe_left), "h": max(0.0, min(target_height, safe_bottom - max(safe_top, top)))}


def _evaluate(
    scene: dict[str, Any], position: str, width: int, height: int,
    metrics: dict[str, Any], face: dict[str, Any] | None,
) -> dict[str, Any]:
    container = _container(position, width, height, metrics, face)
    words = scene.get("words", [])
    emphasis = set(int(value) for value in scene.get("emphasis", []))
    requested = _font_size(scene, metrics)
    role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
    role_profile = _role_profile(scene, metrics)
    profile_name = _font_profile_name(role, metrics, role_profile)
    font_profile = dict(metrics.get("typography_profiles", {}).get(profile_name, {}))
    maximum_width = float(role_profile.get("maxWidth", font_profile.get("maxWidth", 0.82 if profile_name == "display" else 0.74))) * width
    if not position.startswith("side_") and container["w"] > maximum_width:
        original_width = container["w"]
        container["x"] += (original_width - maximum_width) / 2
        container["w"] = maximum_width
    maximum_lines = int(role_profile.get("maxLines", font_profile.get("maxLines", metrics.get("maximum_hero_lines" if role in {"HOOK", "HERO", "TITLE"} else "maximum_normal_lines", 3 if role in {"HOOK", "HERO", "TITLE"} else 2))))
    if position.startswith("side_"):
        maximum_lines = int(metrics.get("maximum_side_lines", 2))
    minimum_scale = float(metrics.get(
        "minimum_display_font_scale" if role in {"HOOK", "HERO", "TITLE"} else "minimum_font_scale",
        0.66 if role in {"HOOK", "HERO", "TITLE"} else 0.78,
    ))
    minimum_px = float(font_profile.get(
        "minSize", metrics.get("minimum_display_font_px" if role in {"HOOK", "HERO", "TITLE", "PUNCH", "NUMBER"} else "minimum_body_font_px", 62 if role in {"HOOK", "HERO", "TITLE", "PUNCH", "NUMBER"} else 48),
    ))
    if role in {"HOOK", "HERO", "TITLE"} and len(words) >= 3 and profile_name == "display":
        # The condensed DISPLAY face remains readable at the HERO library's
        # 52px floor and can keep a four-word thought in two balanced rows.
        # This is safer than accepting a one-word-per-line ladder.
        minimum_px = min(minimum_px, 52.0)
    # A large execution scale can make the configured relative floor stricter
    # than the profile's absolute readable minimum. Prefer the explicit pixel
    # minimum: it lets a three-word display thought become two balanced lines
    # instead of accepting a vertical ladder at a larger nominal scale.
    fit_floor = min(1.0, max(0.38, minimum_px / max(1.0, requested)))
    display = profile_name in {"display", "hero"}
    animation = float(metrics.get("animation_padding", 34))
    overshoot = min(float(font_profile.get("maxOvershoot", 1.20)), float(metrics.get(
        "maximum_display_overshoot" if display else "maximum_accent_overshoot" if role == "ACCENT" else "maximum_body_overshoot",
        1.16 if display else 1.18 if role == "ACCENT" else 1.04,
    )))
    # Wrapping must reserve the complete animated envelope.  Previously the
    # static glyphs were fitted first and padding/overshoot was added later,
    # which allowed a visually valid phrase to cross the platform safe edge
    # during its entrance animation.
    wrap_width = max(1.0, (container["w"] - animation * 2) / max(1.0, overshoot) - 18.0)
    scale = 1.0
    lines = _wrap(words, requested, wrap_width, emphasis, metrics, role, role_profile=role_profile)

    # Three large words in a HOOK/HERO can technically fit the configured
    # maximum while still producing the undesirable one-word-per-line
    # "ladder".  Auto-fit for the *composition*, not only the line limit.
    # This keeps the whole thought visually dominant without shrinking the
    # supporting words into a separate micro-caption.
    def needs_fit(candidate: list[float]) -> bool:
        too_many_lines = len(candidate) > maximum_lines
        too_wide = max(candidate, default=0) > wrap_width
        compact_display = role in {"HOOK", "HERO", "TITLE"} and len(words) <= 4
        # The renderer now consumes these exact planned line groups, so a short
        # display phrase may use two balanced rows. Three one-word rows remain
        # a vertical ladder and must be fitted down or moved.
        excessive_stack = (compact_display and len(candidate) > 2) or (len(words) >= 3 and len(candidate) > 2)
        return too_many_lines or too_wide or excessive_stack

    while needs_fit(lines) and scale > fit_floor + 0.001:
        scale = max(fit_floor, scale - 0.04)
        lines = _wrap(words, requested * scale, wrap_width, emphasis, metrics, role, role_profile=role_profile)
    line_height_ratio = float(role_profile.get("lineHeight", 0.90 if display else 1.0))
    line_height = requested * scale * line_height_ratio
    stroke_ratio = float(font_profile.get("strokeRatio", metrics.get("display_stroke_ratio" if display else "body_stroke_ratio", 0.044 if display else 0.05)))
    stroke = _clamp(
        requested * scale * stroke_ratio,
        float(font_profile.get("strokeMin", metrics.get("minimum_stroke_px", 2.0))),
        float(font_profile.get("strokeMax", metrics.get("maximum_stroke_px", 6.0))),
    )
    shadow_profile = font_profile.get("shadow", {})
    shadow = _clamp(float(shadow_profile.get("blur", metrics.get("shadow", 4))) * (requested * scale / 64.0), 2.0, 14.0)
    static_width = max(lines, default=0) + stroke * 2 + shadow
    static_height = len(lines) * line_height + stroke * 2 + shadow
    # Never clamp the measured envelope to the container. Clamping hid real
    # long-word overflow from preflight while the browser still rendered it.
    block_width = static_width * overshoot + animation * 2
    block_height = static_height * overshoot + animation * 2
    x = container["x"] + (container["w"] - block_width) / 2
    if position == "side_left": x = container["x"]
    if position == "side_right": x = container["x"] + container["w"] - block_width
    y = container["y"] + max(0.0, (container["h"] - block_height) / 2)
    bbox = {"x": x, "y": y, "w": block_width, "h": block_height}
    horizontal = float(metrics.get("horizontal_margin", 92))
    safe_left = float(metrics.get("left_margin", horizontal))
    safe_right = width - float(metrics.get("right_margin", horizontal))
    safe_top = float(metrics.get("top_margin", 96))
    safe_bottom = height - float(metrics.get("bottom_margin", 300))
    edge_proximity = min(x - safe_left, safe_right - (x + block_width), y - safe_top, safe_bottom - (y + block_height))
    violations: list[str] = []
    if edge_proximity < 0: violations.extend(["safe_area_violation", "text_edge_violation"])
    static_edge_proximity = edge_proximity + max(static_width, static_height) * max(0.0, overshoot - 1.0) / 2
    if edge_proximity < 0 <= static_edge_proximity: violations.append("animation_edge_violation")
    if len(lines) > maximum_lines: violations.extend(["line_count", "excessive_line_count"])
    if scale <= fit_floor + 0.001 and (
        len(lines) > maximum_lines or (len(words) > 1 and max(lines, default=0) > wrap_width)
    ):
        violations.append("auto_fit_limit")
    aspect = block_width / max(1.0, block_height)
    narrow = position.startswith("side_") and container["w"] < float(metrics.get("minimum_side_width", 330))
    # Two balanced rows are a valid HOOK/HERO composition.  The former 1.12
    # aspect threshold incorrectly rejected legitimate three-word hooks such
    # as "почему большинство людей" even after they were fitted to two rows.
    # Reserve vertical-stack failure for a real ladder (3+ rows) or an
    # exceptionally narrow two-row block.
    vertical_stack = len(lines) > 2 or (len(lines) == 2 and len(words) >= 3 and aspect < 0.82)
    if narrow: violations.append("narrow_text_column")
    if vertical_stack: violations.append("vertical_text_stack")
    face_overlap = 0.0
    if face:
        face_rect = {"x": (float(face["x"]) - float(face["w"]) / 2) * width, "y": (float(face["y"]) - float(face["h"]) / 2) * height, "w": float(face["w"]) * width, "h": float(face["h"]) * height}
        face_overlap = _overlap(bbox, face_rect)
        if face_overlap > 0.10: violations.append("face_text_collision")
    balance = 1.0 - abs((x + block_width / 2) - width / 2) / (width / 2)
    if requested * scale < minimum_px:
        violations.append("body_text_too_small" if not display else "display_text_too_small")
    stroke_ratio_actual = stroke / max(1.0, requested * scale)
    if stroke_ratio_actual > (0.075 if display else 0.07):
        violations.append("stroke_too_heavy")
    readability = _clamp(
        1.0
        - max(0.0, minimum_px - requested * scale) / minimum_px * 0.46
        - max(0, len(lines) - maximum_lines) * 0.22
        - max(0.0, 0.95 - aspect) * 0.18
        - min(0.38, face_overlap * 1.4)
        - (0.20 if edge_proximity < 12 else 0.0)
    )
    if readability < float(metrics.get("minimum_readability_score", 0.70)):
        violations.append("body_text_unreadable")
    side_confidence = _clamp(container["w"] / max(1.0, float(metrics.get("minimum_side_width", 330))) * 0.42 + (1.0 - min(1.0, len(lines) / 3.0)) * 0.28 + (1.0 - face_overlap) * 0.30) if position.startswith("side_") else 1.0
    _, line_word_indices = _wrap_layout(words, requested * scale, wrap_width, emphasis, metrics, role, role_profile=role_profile)
    return {
        "position": position, "valid": not violations, "violations": violations,
        "bounding_box_px": {key: round(value, 2) for key, value in bbox.items()},
        "bounding_box": {"x": round(x / width, 4), "y": round(y / height, 4), "w": round(block_width / width, 4), "h": round(block_height / height, 4)},
        "platform_safe_zone_px": {
            "left": round(safe_left, 2), "right": round(width - safe_right, 2),
            "top": round(safe_top, 2), "bottom": round(height - safe_bottom, 2),
        },
        "container_width": round(container["w"], 2), "font_scale": round(scale, 3),
        "font_size": round(requested * scale, 2), "line_count": len(lines),
        "line_word_indices": line_word_indices,
        "font_family": metrics.get(f"{profile_name}_font_family"),
        "font_profile": profile_name,
        "font_weight": font_profile.get("weight", metrics.get("font_weight", 800)),
        "tracking": role_profile.get("tracking", 0), "line_height": round(line_height_ratio, 3),
        "stroke_px": round(stroke, 2), "stroke_ratio": round(stroke_ratio_actual, 4),
        "shadow_px": round(shadow, 2), "animation_overshoot": round(overshoot, 3),
        "static_bounding_box_px": {"w": round(static_width, 2), "h": round(static_height, 2)},
        "readability_score": round(readability, 3),
        "longest_line_width": round(max(lines, default=0), 2),
        "edge_proximity": round(edge_proximity, 2), "layout_balance": round(_clamp(balance), 3),
        "text_block_aspect_ratio": round(aspect, 3), "face_overlap": round(face_overlap, 3),
        "safe_area_violation": "safe_area_violation" in violations,
        "side_layout_confidence": round(side_confidence, 3),
    }


def validate_text_compositions(
    scenes: list[dict[str, Any]], style_profile: dict[str, Any], face_plan: dict[str, Any],
    width: int, height: int, metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Style profiles may override the global safety geometry, but semantic
    # decisions remain upstream.  The renderer receives only the resolved,
    # validated composition.
    style_safety = style_profile.get("text", {}).get("safe_area", {})
    metrics = {**(metrics or {}), **style_safety}
    fallbacks = 0
    violations_before = 0
    for scene in scenes:
        midpoint = (float(scene.get("start", 0)) + float(scene.get("end", 0))) / 2
        face = _face_envelope(
            face_plan, float(scene.get("start", midpoint)), float(scene.get("end", midpoint)),
            width, height, metrics,
        )
        if face:
            scene.setdefault("layout", {})["faceBox"] = face
        requested_position = str(scene.get("layout", {}).get("position", "lower"))
        requested_template = str(scene.get("template", "PHRASE_BUILD"))
        before = _evaluate(scene, requested_position, width, height, metrics, face)
        violations_before += len(before["violations"])
        allow_right = bool(style_profile.get("text", {}).get("allow_right_side", False))
        positions = [requested_position]
        if requested_position == "side_left" and allow_right: positions.append("side_right")
        if requested_position == "side_right": positions.append("side_left")
        positions.extend(["center_lower", "center", "top", "lower"])
        unique_positions = list(dict.fromkeys(positions))
        evaluations = [_evaluate(scene, position, width, height, metrics, face) for position in unique_positions]
        selected = next((item for item in evaluations if item["valid"]), evaluations[-1])
        fallback = selected["position"] != requested_position
        if fallback:
            fallbacks += 1
            scene["layout"]["position"] = selected["position"]
            if requested_template == "SIDE_TEXT":
                scene["template"] = "TOP_CAPTION" if selected["position"] == "top" else "PHRASE_BUILD"
        scene["layout"]["compositionSafety"] = {
            **selected, "requested_position": requested_position,
            "requested_template": requested_template, "fallback_applied": fallback,
            "fallback_chain": unique_positions,
            "fallback_reason": ", ".join(before["violations"]) if fallback else None,
            "violations_before": before["violations"], "violations_after": selected["violations"],
            "before": before,
        }
        side = scene["layout"].get("sideLayout") or scene["layout"].get("side_layout") or {}
        if selected["position"].startswith("side_"):
            side.update({"valid": selected["valid"], "estimated_lines": selected["line_count"], "available_width": round(selected["container_width"] / width, 3), "confidence": selected["side_layout_confidence"]})
        scene["layout"]["sideLayout"] = side
    return {"scenes": len(scenes), "fallbacks": fallbacks, "violations_before": violations_before, "violations_after": sum(len(scene.get("layout", {}).get("compositionSafety", {}).get("violations_after", [])) for scene in scenes)}
