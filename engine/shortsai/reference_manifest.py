from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .media import probe_media, source_fingerprint


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


def _videos(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root.resolve()] if root.suffix.lower() in VIDEO_EXTENSIONS else []
    return sorted(
        (item.resolve() for item in root.rglob("*") if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS),
        key=lambda item: item.as_posix().casefold(),
    )


def _designated(example: Path, name: str) -> tuple[Path | None, list[str]]:
    target = example / name
    candidates = _videos(target)
    if not candidates and target.suffix.lower() in VIDEO_EXTENSIONS:
        candidates = [item for item in _videos(example) if item.name.casefold() == name.casefold()]
    return (candidates[0] if len(candidates) == 1 else None), [str(item) for item in candidates]


def _orientation(width: int, height: int) -> str:
    if height > width:
        return "vertical"
    if width > height:
        return "horizontal"
    return "square"


def _media(path: Path | None, ffprobe: Path) -> dict[str, Any] | None:
    if path is None:
        return None
    info = probe_media(path, ffprobe)
    width, height = info.display_width or info.width, info.display_height or info.height
    return {
        **info.to_dict(),
        "resolution": {"width": width, "height": height},
        "orientation": _orientation(width, height),
        "container": path.suffix.lower().lstrip("."),
        "fingerprint": source_fingerprint(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def discover_reference_dataset(dataset: Path, ffprobe: Path) -> dict[str, Any]:
    """Build a stable manifest without touching reference media.

    A path such as ``source.mp4`` may be either a file or a directory containing
    the actual user video. Missing and ambiguous examples stay visible in the
    manifest instead of being silently ignored.
    """
    dataset = dataset.resolve()
    entries: list[dict[str, Any]] = []
    raw_root = dataset / "raw_to_final"
    if raw_root.is_dir():
        for example in sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
            source, source_candidates = _designated(example, "source.mp4")
            final, final_candidates = _designated(example, "reference_final.mp4")
            if source and final:
                status = "READY"
            elif len(source_candidates) > 1 or len(final_candidates) > 1:
                status = "AMBIGUOUS_MEDIA"
            else:
                status = "MISSING_SOURCE" if not source else "MISSING_FINAL"
            entries.append({
                "reference_id": f"raw_to_final/{example.name}",
                "reference_type": "RAW_TO_FINAL",
                "category": "paired",
                "source_path": str(source) if source else None,
                "final_path": str(final) if final else None,
                "has_raw_source": source is not None,
                "source_candidates": source_candidates,
                "final_candidates": final_candidates,
                "source_media": _media(source, ffprobe),
                "final_media": _media(final, ffprobe),
                "analysis_status": status,
            })
    final_root = dataset / "final_only"
    if final_root.is_dir():
        for category in sorted((p for p in final_root.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
            for final in _videos(category):
                relative = final.relative_to(category).with_suffix("").as_posix()
                entries.append({
                    "reference_id": f"final_only/{category.name}/{relative}",
                    "reference_type": "FINAL_ONLY",
                    "category": category.name,
                    "source_path": None,
                    "final_path": str(final),
                    "has_raw_source": False,
                    "source_media": None,
                    "final_media": _media(final, ffprobe),
                    "analysis_status": "READY",
                })
    return {
        "version": 1,
        "dataset_root": str(dataset),
        "policy": "read_only_media_offline_developer_analysis",
        "entries": entries,
        "summary": {
            "objects": len(entries),
            "ready": sum(item["analysis_status"] == "READY" for item in entries),
            "raw_to_final_pairs": sum(item["reference_type"] == "RAW_TO_FINAL" and item["analysis_status"] == "READY" for item in entries),
            "final_only": sum(item["reference_type"] == "FINAL_ONLY" for item in entries),
            "incomplete": sum(item["analysis_status"] != "READY" for item in entries),
        },
    }


def write_reference_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def reference_media_paths(manifest: dict[str, Any]) -> Iterable[Path]:
    for item in manifest.get("entries", []):
        for key in ("source_path", "final_path"):
            if item.get(key):
                yield Path(item[key])
