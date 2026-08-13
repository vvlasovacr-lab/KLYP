from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


SUPPORTED_SFX = frozenset({".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"})
SFX_CATEGORIES = frozenset({"impact", "whoosh", "pop", "click", "bass_hit", "transition"})


def _duration(path: Path, ffprobe: Path) -> float:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return max(0.0, float(result.stdout.strip() or 0))


def build_sfx_library(root: Path, ffprobe: Path, *, write_index: bool = True) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SFX:
            continue
        relative = path.relative_to(root).as_posix()
        category = path.parent.name.lower()
        if category not in SFX_CATEGORIES:
            category = path.stem.lower().split("_")[0]
        try:
            duration = _duration(path, ffprobe)
            assets.append({
                "id": hashlib.sha1(relative.lower().encode("utf-8")).hexdigest()[:12],
                "file": relative, "category": category, "duration": round(duration, 4),
                "tags": sorted(set(path.stem.lower().replace("-", "_").split("_")) | {category}),
                "usable": 0.03 <= duration <= 5.0,
            })
        except Exception as error:
            errors.append({"file": relative, "error": f"{type(error).__name__}: {error}"})
    result = {"version": 1, "root": str(root.resolve()), "assets": assets, "errors": errors}
    if write_index:
        (root / "index.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def resolve_sfx_actions(actions: list[dict[str, Any]], root: Path, ffprobe: Path) -> dict[str, Any]:
    library = build_sfx_library(root, ffprobe)
    by_category: dict[str, list[dict[str, Any]]] = {}
    for asset in library["assets"]:
        if asset.get("usable"):
            by_category.setdefault(str(asset["category"]), []).append(asset)
    resolved: list[dict[str, Any]] = []
    for action in actions:
        item = dict(action)
        category = str(item.get("type", "")).lower()
        candidates = by_category.get(category, [])
        if not candidates and category == "bass_hit":
            candidates = by_category.get("impact", [])
        if not candidates and category == "whoosh":
            candidates = by_category.get("transition", [])
        if not candidates:
            item.update({"file": None, "resolved": False, "enabled": False})
            resolved.append(item)
            continue
        intensity = max(0.0, min(1.0, float(item.get("intensity", 0.6))))
        ordered = sorted(candidates, key=lambda asset: (float(asset["duration"]), asset["file"]))
        selected = ordered[min(len(ordered) - 1, round(intensity * (len(ordered) - 1)))]
        duration = float(selected["duration"])
        item.update({
            "file": selected["file"], "asset_id": selected["id"], "resolved": True, "enabled": True,
            "duration": round(duration, 4), "volume": round(0.28 + intensity * 0.52, 3),
            "fade_in": round(min(0.018, duration * 0.12), 4),
            "fade_out": round(min(0.10, duration * 0.28), 4),
        })
        resolved.append(item)
    return {"version": 1, "library": library, "actions": resolved}
