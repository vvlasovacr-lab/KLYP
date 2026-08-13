from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any


ASSET_INDEX_VERSION = 1
VIDEO = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})
IMAGE = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
AUDIO = frozenset({".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"})


def _sidecar(path: Path) -> dict[str, Any]:
    candidates = (path.with_suffix(path.suffix + ".json"), path.with_suffix(".json"))
    source = next((item for item in candidates if item.is_file()), None)
    if source is None:
        return {}
    value = json.loads(source.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _asset_type(relative: Path) -> str:
    first = relative.parts[0].lower() if relative.parts else "other"
    suffix = relative.suffix.lower()
    if first == "broll" and suffix in VIDEO: return "broll_video"
    if first == "sfx" and suffix in AUDIO: return "sfx"
    if first == "music" and suffix in AUDIO: return "music"
    if first in {"overlays", "effects"}: return "overlay"
    if first in {"particles", "light_leaks", "glitch", "film_grain", "motion_graphics"}: return first
    if suffix in IMAGE: return "image"
    if suffix in VIDEO: return "video"
    if suffix in AUDIO: return "audio"
    return "other"


def build_asset_catalog(root: Path, *, write_index: bool = True) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in VIDEO | IMAGE | AUDIO:
            continue
        relative = path.relative_to(root)
        metadata = _sidecar(path)
        tags = metadata.get("keywords", metadata.get("tags", []))
        if isinstance(tags, str): tags = [tags]
        inferred = re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", " ".join(relative.with_suffix("").parts))
        styles = metadata.get("styles", metadata.get("suitableStyles", []))
        if isinstance(styles, str): styles = [styles]
        stat = path.stat()
        category = str(metadata.get("category") or (relative.parts[1] if len(relative.parts) > 2 else relative.parts[0]))
        assets.append({
            "id": hashlib.sha1(relative.as_posix().lower().encode("utf-8")).hexdigest()[:12],
            "file": relative.as_posix(), "assetType": _asset_type(relative),
            "category": category, "topic": str(metadata.get("topic", category)),
            "emotion": str(metadata.get("emotion", "neutral")),
            "keywords": sorted({str(value).lower() for value in [*tags, *inferred]}),
            "suitableStyles": [str(value).upper() for value in styles],
            "importance": round(min(1.0, max(0.0, float(metadata.get("importance", 0.5)))), 3),
            "description": str(metadata.get("description", path.stem.replace("_", " "))),
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
        })
    types = Counter(asset["assetType"] for asset in assets)
    catalog = {"version": ASSET_INDEX_VERSION, "root": str(root.resolve()), "assets": assets, "summary": {"total": len(assets), "types": dict(types)}}
    if write_index:
        (root / "asset_index.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    return catalog
