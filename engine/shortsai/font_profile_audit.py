from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .automated_pipeline import AutomatedPipeline
from .config import load_config
from .font_profile_selector import select_font_profile
from .style_profiles import get_style_profile
from .text_composition import validate_text_compositions


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _candidates(work: Path) -> list[Path]:
    rows, seen = [], set()
    for path in sorted(work.glob("jobs/*/artifacts/style_intelligence.json"), key=lambda item: item.stat().st_mtime_ns, reverse=True):
        data = _read(path)
        if not data.get("automatic"):
            continue
        content = data.get("contentAnalysis", {})
        key = (data.get("profile"), content.get("topic"), content.get("format"))
        if key in seen or not (path.parent / "montage_plan.json").is_file():
            continue
        seen.add(key); rows.append(path)
    return rows


def audit(config_path: Path, output: Path, limit: int = 3) -> dict[str, Any]:
    config = load_config(config_path)
    pipeline = AutomatedPipeline(config)
    report = {"version": 1, "principle": "AUTO style then one deterministic job-level font profile", "jobs": []}
    candidates = _candidates(config.work_dir)
    if len(candidates) < limit:
        raise RuntimeError(f"Need {limit} distinct AUTO artifacts, found {len(candidates)}")
    for style_path in candidates[:limit]:
        artifacts = style_path.parent
        style_decision = _read(style_path)
        source_meta = _read(artifacts / "source.json") if (artifacts / "source.json").is_file() else {}
        source_identity = source_meta.get("source_fingerprint") or {"job": artifacts.parent.name}
        style_profile = get_style_profile(config.project_root / "style_profiles.json", style_decision["profile"])
        selection = select_font_profile(
            config.project_root / "font_profiles.json", config.assets_dir / "fonts",
            style_profile["name"], style_decision, source_identity,
        )
        style_profile.update({
            "font_profile": selection["font_profile_id"], "fontProfile": selection["profile"],
            "fontSelection": {key: value for key, value in selection.items() if key != "profile"},
        })
        plan = _read(artifacts / "montage_plan.json")
        scenes = copy.deepcopy(plan.get("scenes", []))
        face = _read(artifacts / "face_plan.json") if (artifacts / "face_plan.json").is_file() else {"detected": False}
        geometry = validate_text_compositions(scenes, style_profile, face, 1080, 1920, pipeline._text_metrics(style_profile))
        safeties = [scene.get("layout", {}).get("compositionSafety", {}) for scene in scenes]
        invalid_scenes = [{
            "start": scene.get("start"), "role": scene.get("semanticRole", scene.get("type")),
            "template": scene.get("template"), "text": scene.get("text"),
            "reasons": scene.get("layout", {}).get("compositionSafety", {}).get("violations_after", []),
            "font_size": scene.get("layout", {}).get("compositionSafety", {}).get("font_size"),
        } for scene in scenes if scene.get("layout", {}).get("compositionSafety", {}).get("valid") is False]
        fallback_count = sum(bool(item.get("font_role_fallback")) for item in safeties)
        tiny = sum(float(item.get("font_size", 999)) < 38 for item in safeties)
        qc = max(0.0, 1.0 - geometry["violations_after"] * 0.12 - tiny * 0.08 - fallback_count * 0.10)
        content = style_decision.get("contentAnalysis", {})
        report["jobs"].append({
            "job_id": artifacts.parent.name, "content_style_profile": style_profile["name"],
            "style_confidence": style_decision.get("confidence"), "topic": content.get("topic"),
            "content_format": content.get("format"), "pace": content.get("delivery", {}).get("pace"),
            "font_profile": selection["font_profile_id"], "variant": selection["variant_id"],
            "seed": selection["seed"], "selection_reason": selection["selection_reason"],
            "body": selection["body_font_file"], "display": selection["display_font_file"], "hero": selection["hero_font_file"],
            "fallback_count": fallback_count, "typography_qc": round(qc, 3),
            "geometry": {"scenes": len(scenes), "violations_before": geometry["violations_before"], "violations_after": geometry["violations_after"], "tiny_auto_fit": tiny, "invalid_scenes": invalid_scenes},
            "semantic_artifact_hashes": {name: _hash(artifacts / filename) for name, filename in {
                "content_map": "content_map.json", "normalized_transcript": "transcript.normalized.json",
                "speech_edit": "speech_edit_plan.json", "timeline": "timeline_plan.json",
            }.items()},
        })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, default=Path("output/production_font_library_gallery/auto_selection_diversity.json"))
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    result = audit(args.config.resolve(), args.output.resolve(), args.limit)
    print(json.dumps({"jobs": len(result["jobs"]), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
