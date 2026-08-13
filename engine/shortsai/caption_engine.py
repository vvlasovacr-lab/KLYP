from __future__ import annotations

from typing import Any, Sequence


def build_caption_plan(
    scenes: Sequence[dict[str, Any]], composition_safety: dict[str, Any],
    *, width: int, height: int,
) -> dict[str, Any]:
    """Freeze readable caption geometry before visual polish is executed."""
    captions: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for scene in scenes:
        safety = scene.get("layout", {}).get("compositionSafety", {})
        item = {
            "start": scene.get("start"), "end": scene.get("end"), "text": scene.get("text", ""),
            "semantic_role": scene.get("semanticRole", scene.get("type", "NORMAL")),
            "position": scene.get("layout", {}).get("position"),
            "bounding_box": safety.get("bounding_box"),
            "bounding_box_px": safety.get("bounding_box_px"),
            "platform_safe_zone_px": safety.get("platform_safe_zone_px"),
            "font_size_px": safety.get("font_size"), "line_count": safety.get("line_count"),
            "font_scale": safety.get("font_scale"), "fallback_applied": safety.get("fallback_applied", False),
            "validation": "PASS" if not safety.get("violations_after") else "FAIL",
            "violations": list(safety.get("violations_after", [])),
        }
        captions.append(item)
        if item["validation"] == "FAIL": invalid.append(item)
    return {
        "version": 1, "layer": "CAPTION_ENGINE",
        "principle": "normalized text + measured bounding boxes + platform safe zones; no visual effect decisions",
        "canvas": {"width": width, "height": height},
        "number_style": "conversational_magnitude_words",
        "captions": captions, "composition_summary": composition_safety,
        "summary": {
            "captions": len(captions), "valid": len(captions) - len(invalid),
            "invalid": len(invalid), "fallbacks": composition_safety.get("fallbacks", 0),
        },
    }
