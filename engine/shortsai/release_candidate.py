from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable


RC_ID = "TALKING_HEAD_V1_RC"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _hash(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {"path": str(path.resolve()), "exists": path.is_file(), "sha256": digest, "size": path.stat().st_size if path.is_file() else None}


def build_config_snapshot(project_root: Path) -> dict[str, Any]:
    files = [
        "config.json", "talking_head_v1_rc.json", "style_profiles.json", "font_profiles.json",
        "camera_profiles.json", "motion_profiles.json", "visual_profiles.json", "background_music.json",
        "remotion/package.json", "remotion/src/styles/config.json", "assets/fonts/font_manifest.json",
        "assets/broll/broll_manifest.json", "assets/sfx/index.json",
    ]
    rc = _read(project_root / "talking_head_v1_rc.json")
    return {
        "release_candidate": RC_ID, "created_at": datetime.now(timezone.utc).isoformat(),
        "contracts": rc.get("contracts", {}), "policy": rc,
        "files": {name: _hash(project_root / name) for name in files},
    }


def _merged_duration(intervals: Iterable[tuple[float, float]], duration: float) -> float:
    values = sorted((max(0.0, start), min(duration, end)) for start, end in intervals if end > start)
    merged: list[tuple[float, float]] = []
    for start, end in values:
        if merged and start <= merged[-1][1] + 0.02:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def _longest_layout_run(scenes: list[dict[str, Any]]) -> tuple[int, int]:
    last = None
    run = maximum = transitions = 0
    for scene in sorted((item for item in scenes if item.get("enabled", True)), key=lambda item: float(item.get("start", 0))):
        signature = (scene.get("template"), scene.get("layout", {}).get("position"))
        if last is not None and signature != last:
            transitions += 1
        run = run + 1 if signature == last else 1
        maximum = max(maximum, run)
        last = signature
    return transitions, maximum


def _job_metrics(job: Path) -> dict[str, Any]:
    artifacts = job / "artifacts"
    plan = _read(artifacts / "montage_plan.json")
    quality = _read(artifacts / "quality_report.json")
    execution = _read(artifacts / "director_execution_plan.json")
    manifest = _read(job / "job_manifest.json")
    scenes = list(plan.get("scenes", []))
    enabled = [item for item in scenes if item.get("enabled", True)]
    duration = max(0.1, float(plan.get("output", {}).get("duration", 0.0)))
    role_counts = Counter(str(item.get("semanticRole", item.get("type", "NORMAL"))).upper() for item in enabled)
    state_counts = Counter(str(item.get("captionState", "BODY_CAPTION")) for item in scenes)
    broll = [item for item in plan.get("broll", []) if item.get("enabled", True)]
    requests = list(plan.get("brollRequests", []))
    camera = [item for item in plan.get("camera", []) if item.get("enabled", True)]
    visual = [item for item in plan.get("visual", []) if item.get("enabled", True)]
    sfx = [item for item in plan.get("sfx", []) if item.get("enabled", True)]
    transitions, longest_run = _longest_layout_run(scenes)
    metrics = quality.get("metrics", {})
    penalties = metrics.get("visual_penalties", {})
    text_duration = _merged_duration(((float(item.get("start", 0)), float(item.get("end", 0))) for item in enabled), duration)
    strong_duration = _merged_duration(((float(item.get("start", 0)), float(item.get("end", 0))) for item in enabled if str(item.get("captionState", "")) == "STRONG_TYPOGRAPHY"), duration)
    body_duration = _merged_duration(((float(item.get("start", 0)), float(item.get("end", 0))) for item in enabled if str(item.get("captionState", "BODY_CAPTION")) in {"BODY_CAPTION", "REDUCED_CAPTION"}), duration)
    relevances = [float(item.get("brollNecessity", {}).get("local_semantic_relevance", 0)) for item in broll]
    broll_duration = sum(max(0.0, float(item.get("to", 0)) - float(item.get("from", 0))) for item in broll)
    return {
        "job_id": manifest.get("job_id", job.name), "job": str(job.resolve()),
        "source": plan.get("source", {}).get("file", manifest.get("source_file")),
        "output": manifest.get("published_output") or manifest.get("final_mp4"),
        "style_profile": quality.get("profile") or manifest.get("profile"),
        "font_profile": metrics.get("font_profile") or manifest.get("font_profile"),
        "font_variant": metrics.get("font_variant") or manifest.get("font_variant"),
        "font_seed": manifest.get("font_selection_seed"), "duration": round(duration, 3),
        "text_coverage": round(text_duration / duration, 4),
        "body_coverage": round(body_duration / duration, 4),
        "strong_typography_coverage": round(strong_duration / duration, 4),
        "speaker_only_text_coverage": round(max(0.0, 1.0 - text_duration / duration), 4),
        "visual_rest_coverage": metrics.get("visual_rest_coverage"),
        "caption_states": dict(state_counts), "roles": dict(role_counts),
        "layout_transitions": transitions, "longest_same_layout_run": longest_run,
        "broll_candidates": len(requests), "broll_executed": len(broll),
        "broll_coverage": round(broll_duration / duration, 4),
        "broll_local_relevance": round(sum(relevances) / len(relevances), 3) if relevances else None,
        "broll_mismatch": penalties.get("broll_mismatch", penalties.get("broll_text_mismatch", 0)),
        "broll_repetition": penalties.get("broll_repetition", 0),
        "average_insert_duration": round(broll_duration / len(broll), 3) if broll else 0.0,
        "broll_assets": [shot.get("file") for item in broll for shot in item.get("shots", [])],
        "broll_rejections": dict(Counter(str(item.get("status", "UNKNOWN")) for item in requests if item.get("status") != "MATCHED")),
        "camera_events": len(camera), "camera_punches": sum(str(item.get("effect", "")).upper() == "PUNCH_ZOOM" for item in camera),
        "camera_under_broll": metrics.get("camera_under_broll", 0),
        "unreturned_camera": metrics.get("unreturned_camera_events", 0),
        "effects": len(visual), "effect_cooldown_violations": penalties.get("effect_overdensity", 0),
        "sfx": len(sfx), "face_collisions": penalties.get("face_text_collision", 0),
        "safe_area_violations": penalties.get("safe_area_violation", 0),
        "text_overflow": penalties.get("text_edge_violation", 0),
        "motion_overshoot_violations": penalties.get("animation_edge_violation", 0),
        "end_zone_violations": penalties.get("broll_in_cta_zone", penalties.get("end_zone_broll", 0)),
        "audio_lufs": metrics.get("integrated_lufs"), "audio_peak": metrics.get("true_peak_dbtp"),
        "decode_rate": metrics.get("technical_contract", {}).get("decode_rate"),
        "quality_dimensions": quality.get("quality_dimensions", {}), "quality_score": quality.get("final_score"),
        "quality_warnings": quality.get("warnings", []), "rendered_qc": quality.get("rendered_frame_qc", {}),
        "plan": plan, "quality": quality, "execution": execution, "manifest": manifest,
    }


def _number_error(scenes: list[dict[str, Any]]) -> bool:
    return any(re.search(r"\b\d+(?:[.,]\d+)?\s+1000\b", str(item.get("text", ""))) for item in scenes)


def _classify(metrics: dict[str, Any]) -> dict[str, Any]:
    plan, warnings = metrics["plan"], set(metrics.get("quality_warnings", []))
    penalties = metrics.get("quality", {}).get("metrics", {}).get("visual_penalties", {})
    blockers: list[str] = []
    output = Path(metrics.get("output") or "")
    if not output.is_file() or float(metrics.get("decode_rate") or 0) < 1.0: blockers.append("broken_mp4_or_incomplete_decode")
    for name, value in (
        ("text_outside_safe_area", metrics["safe_area_violations"]), ("critical_face_overlap", metrics["face_collisions"]),
        ("text_overflow", metrics["text_overflow"]), ("motion_overshoot_unsafe", metrics["motion_overshoot_violations"]),
        ("irrelevant_broll", metrics["broll_mismatch"]), ("repeated_broll", metrics["broll_repetition"]),
        ("broll_in_cta", metrics["end_zone_violations"]), ("camera_under_broll", metrics["camera_under_broll"]),
        ("unreturned_camera_punch", metrics["unreturned_camera"]),
    ):
        if value: blockers.append(name)
    if penalties.get("vertical_text_stack"): blockers.append("text_ladder")
    if penalties.get("body_text_unreadable"): blockers.append("unreadable_caption")
    if int(metrics.get("manifest", {}).get("font_fallbacks", 0) or 0): blockers.append("random_font_fallback")
    if _number_error(plan.get("scenes", [])): blockers.append("wrong_number_formatting")
    if penalties.get("effect_overdensity", 0) > 1 or penalties.get("effect_overactivity", 0) > 2: blockers.append("strong_effects_spam")
    if metrics.get("audio_peak") is not None and float(metrics["audio_peak"]) >= -0.1: blockers.append("audio_clipping_risk")
    for name in ("subject_not_ready_at_start", "excessive_off_camera_start", "transition_frame_retained", "weak_episode_tail", "content_structure_missing_close"):
        if name in warnings: blockers.append(name)
    review: list[str] = []
    if metrics["text_coverage"] > 0.93: review.append("moderately_high_text_density")
    if penalties.get("repeated_composition"): review.append("minor_visual_repetition")
    if penalties.get("camera_overactivity"): review.append("camera_could_be_calmer")
    if metrics.get("broll_executed") and (metrics.get("broll_local_relevance") or 0) < 0.55: review.append("broll_could_be_more_specific")
    cosmetics: list[str] = []
    if not blockers and float(metrics.get("quality_dimensions", {}).get("TYPOGRAPHY", 1.0)) < 0.95:
        cosmetics.append("minor_typography_preference")
    verdict = "NOT_SHOWCASE_READY" if blockers else "SHOWCASE_READY_WITH_COSMETIC_WARNINGS" if review or cosmetics else "SHOWCASE_READY"
    return {"blockers": sorted(set(blockers)), "warnings": sorted(set(review)), "cosmetic": sorted(set(cosmetics)), "verdict": verdict}


def _active_metadata(metrics: dict[str, Any], timestamp: float, label: str) -> dict[str, Any]:
    plan = metrics["plan"]
    scenes = [item for item in plan.get("scenes", []) if float(item.get("start", 0)) <= timestamp <= float(item.get("end", 0))]
    scene = next((item for item in scenes if item.get("enabled", True)), scenes[0] if scenes else {})
    safety = scene.get("layout", {}).get("compositionSafety", {})
    face_samples = plan.get("face", {}).get("samples", [])
    face = min(face_samples, key=lambda item: abs(float(item.get("time", 0)) - timestamp)) if face_samples else None
    camera = next((item for item in plan.get("camera", []) if float(item.get("time", 0)) <= timestamp <= float(item.get("time", 0)) + float(item.get("duration", 0))), None)
    broll = next((item for item in plan.get("broll", []) if float(item.get("from", 0)) <= timestamp <= float(item.get("to", 0))), None)
    effect = next((item for item in plan.get("visual", []) if float(item.get("time", 0)) <= timestamp <= float(item.get("time", 0)) + float(item.get("duration", 0))), None)
    sfx = min(plan.get("sfx", []), key=lambda item: abs(float(item.get("time", 0)) - timestamp), default=None)
    return {
        "label": label, "timestamp": round(timestamp, 3),
        "scene_role": scene.get("semanticRole", scene.get("type", "SPEAKER_ONLY") if scene else "SPEAKER_ONLY"),
        "caption_state": scene.get("captionState", "SPEAKER_ONLY") if scene else "SPEAKER_ONLY",
        "text": scene.get("text", "") if scene.get("enabled", True) else "",
        "font": safety.get("font_family"), "font_size": safety.get("font_size"),
        "text_bounding_box": safety.get("bounding_box_px"), "face_bounding_box": face,
        "safe_area": safety.get("platform_safe_zone_px"), "camera_scale": (camera or {}).get("scale", 1.0),
        "broll_asset": ((broll or {}).get("shots") or [{}])[0].get("file"),
        "broll_relevance": (broll or {}).get("brollNecessity", {}).get("local_semantic_relevance"),
        "effect": (effect or {}).get("type"), "sfx": (sfx or {}).get("type") if sfx and abs(float(sfx.get("time", 0)) - timestamp) < 0.35 else None,
        "director_reason": scene.get("executionAction", {}).get("reason") or scene.get("directorDecision", {}).get("reason"),
    }


def _targets(metrics: dict[str, Any]) -> list[tuple[str, float]]:
    plan, duration = metrics["plan"], float(metrics["duration"])
    scenes = list(plan.get("scenes", []))
    values: list[tuple[str, float]] = [("OPENING", min(0.35, duration - 0.02)), ("END_ZONE", max(0.0, duration - 0.75))]
    def add_scene(label: str, predicate) -> None:
        scene = next((item for item in scenes if predicate(item)), None)
        if scene: values.append((label, (float(scene.get("start", 0)) + float(scene.get("end", 0))) / 2))
    add_scene("HOOK", lambda item: str(item.get("semanticRole", "")).upper() == "HOOK")
    add_scene("BODY", lambda item: item.get("enabled", True) and str(item.get("captionState", "BODY_CAPTION")) == "BODY_CAPTION" and float(item.get("start", 0)) > 3)
    add_scene("SPEAKER_ONLY", lambda item: not item.get("enabled", True))
    for role in ("ACCENT", "HERO", "NUMBER"):
        add_scene(role, lambda item, role=role: item.get("enabled", True) and str(item.get("semanticRole", item.get("type", ""))).upper() == role)
    broll = next(iter(plan.get("broll", [])), None)
    if broll:
        values.extend([("BROLL", (float(broll["from"]) + float(broll["to"])) / 2), ("RETURN_FROM_BROLL", min(duration - 0.02, float(broll["to"]) + 0.12))])
    punch = next((item for item in plan.get("camera", []) if str(item.get("effect", "")).upper() == "PUNCH_ZOOM"), None)
    if punch: values.append(("CAMERA_PUNCH", float(punch.get("time", 0)) + min(0.25, float(punch.get("duration", 0)) * 0.3)))
    result: list[tuple[str, float]] = []
    for label, timestamp in values:
        if label not in {item[0] for item in result}:
            result.append((label, max(0.0, min(duration - 0.02, timestamp))))
    return result


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-1200:])


def _extract_frame(ffmpeg: Path, video: Path, timestamp: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    _run([str(ffmpeg), "-y", "-v", "error", "-ss", f"{timestamp:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(output)])


def _extract_motion(ffmpeg: Path, video: Path, timestamp: float, duration: float, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, timestamp - 0.35)
    _run([str(ffmpeg), "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(video),
          "-map", "0:v:0", "-map", "0:a?", "-vf", "scale=405:720:force_original_aspect_ratio=increase,crop=405:720",
          "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(output)])


def _comparison(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "text_coverage", "body_coverage", "strong_typography_coverage", "speaker_only_text_coverage", "visual_rest_coverage",
        "roles", "caption_states", "layout_transitions", "longest_same_layout_run", "broll_candidates", "broll_executed",
        "broll_coverage", "broll_local_relevance", "broll_mismatch", "broll_repetition", "average_insert_duration",
        "camera_events", "camera_punches", "camera_under_broll", "unreturned_camera", "effects", "effect_cooldown_violations",
        "sfx", "face_collisions", "safe_area_violations", "text_overflow", "motion_overshoot_violations", "end_zone_violations",
        "audio_lufs", "audio_peak", "decode_rate", "quality_dimensions", "quality_score",
    ]
    return {key: {"before": before.get(key) if before else None, "after": after.get(key)} for key in keys}


@dataclass(frozen=True)
class ReleaseCase:
    label: str
    after_job: Path
    before_job: Path | None = None


def build_showcase(project_root: Path, cases: list[ReleaseCase], ffmpeg: Path) -> dict[str, Any]:
    output = project_root / "output" / "showcase_v1"
    if output.exists():
        shutil.rmtree(output)
    (output / "frames").mkdir(parents=True)
    (output / "motion").mkdir(parents=True)
    results: list[dict[str, Any]] = []
    motion_candidates: list[tuple[str, Path, float]] = []
    for case in cases:
        after = _job_metrics(case.after_job)
        before = _job_metrics(case.before_job) if case.before_job else None
        assessment = _classify(after)
        source_video = Path(after["output"])
        showcase_video = output / f"{case.label}_final.mp4"
        shutil.copy2(source_video, showcase_video)
        frames: list[dict[str, Any]] = []
        for index, (label, timestamp) in enumerate(_targets(after), 1):
            frame = output / "frames" / case.label / f"{index:02d}_{label.lower()}_{timestamp:07.3f}.jpg"
            _extract_frame(ffmpeg, source_video, timestamp, frame)
            metadata = _active_metadata(after, timestamp, label)
            metadata["frame"] = str(frame.resolve())
            frames.append(metadata)
            if label in {"HOOK", "HERO", "NUMBER", "ACCENT", "BROLL", "CAMERA_PUNCH", "END_ZONE"}:
                motion_candidates.append((f"{case.label}_{label}", source_video, timestamp))
        public_after = {key: value for key, value in after.items() if key not in {"plan", "quality", "execution", "manifest", "rendered_qc"}}
        public_before = ({key: value for key, value in before.items() if key not in {"plan", "quality", "execution", "manifest", "rendered_qc"}} if before else None)
        results.append({"label": case.label, "before": public_before, "after": public_after, "comparison": _comparison(before, after), "assessment": assessment, "frames": frames, "showcase_video": str(showcase_video.resolve())})
    motions: list[dict[str, Any]] = []
    seen_types: Counter[str] = Counter()
    for name, video, timestamp in motion_candidates:
        event_type = name.rsplit("_", 1)[-1]
        if len(motions) >= 10 or seen_types[event_type] >= 2:
            continue
        path = output / "motion" / f"{len(motions) + 1:02d}_{name.lower()}.mp4"
        _extract_motion(ffmpeg, video, timestamp, 1.8 if event_type != "BROLL" else 2.4, path)
        motions.append({"name": name, "type": event_type, "timestamp": round(timestamp, 3), "file": str(path.resolve())})
        seen_types[event_type] += 1
    blockers = sum(len(item["assessment"]["blockers"]) for item in results)
    warnings = sum(len(item["assessment"]["warnings"]) for item in results)
    cosmetics = sum(len(item["assessment"]["cosmetic"]) for item in results)
    verdict = "NOT_SHOWCASE_READY" if blockers else "SHOWCASE_READY_WITH_COSMETIC_WARNINGS" if warnings or cosmetics else "SHOWCASE_READY"
    report = {
        "version": 1, "release_candidate": RC_ID, "created_at": datetime.now(timezone.utc).isoformat(),
        "real_sources": len(results), "verdict": verdict,
        "release_issues": {"blockers": blockers, "warnings": warnings, "cosmetic": cosmetics},
        "cases": results, "motion_previews": motions,
    }
    _write(output / "release_report.json", report)
    _write(output / "config_snapshot.json", build_config_snapshot(project_root))
    _write(output / "before_after_comparison.json", {item["label"]: item["comparison"] for item in results})
    _write(output / "broll_usage_report.json", {item["label"]: {key: item["after"].get(key) for key in ("broll_candidates", "broll_executed", "broll_coverage", "broll_local_relevance", "broll_mismatch", "broll_repetition", "broll_assets", "broll_rejections")} for item in results})
    _write(output / "visual_qc_report.json", {item["label"]: {"assessment": item["assessment"], "dimensions": item["after"].get("quality_dimensions"), "frames": item["frames"]} for item in results})
    _write_markdown(report, output / "release_report.md")
    _write_html(report, output / "showcase_inspector.html")
    return report


def _write_markdown(report: dict[str, Any], output: Path) -> None:
    lines = [f"# {RC_ID}", "", f"Verdict: **{report['verdict']}**", "", f"Real AUTO sources: {report['real_sources']}", ""]
    for item in report["cases"]:
        after = item["after"]
        lines.extend([
            f"## {item['label']}", "", f"- Style: {after.get('style_profile')}", f"- Font: {after.get('font_profile')} / {after.get('font_variant')}",
            f"- B-roll: {after.get('broll_executed')} executed from {after.get('broll_candidates')} candidates; assets: {after.get('broll_assets')}",
            f"- Text/body/strong/speaker-only: {after.get('text_coverage')} / {after.get('body_coverage')} / {after.get('strong_typography_coverage')} / {after.get('speaker_only_text_coverage')}",
            f"- Roles: {after.get('roles')}", f"- Camera: {after.get('camera_events')} events, {after.get('camera_punches')} punches, under B-roll={after.get('camera_under_broll')}, unreturned={after.get('unreturned_camera')}",
            f"- Blockers: {item['assessment']['blockers']}", f"- Warnings: {item['assessment']['warnings']}", f"- Cosmetic: {item['assessment']['cosmetic']}", "",
        ])
    output.write_text("\n".join(lines), encoding="utf-8")


def _write_html(report: dict[str, Any], output: Path) -> None:
    sections: list[str] = []
    for item in report["cases"]:
        cards = []
        for frame in item["frames"]:
            image = Path(frame["frame"]).resolve().as_uri()
            details = escape(json.dumps({key: value for key, value in frame.items() if key != "frame"}, ensure_ascii=False, indent=2))
            cards.append(f'<article><img src="{image}"><h3>{escape(frame["label"])} · {frame["timestamp"]:.3f}s</h3><pre>{details}</pre></article>')
        video = Path(item["showcase_video"]).resolve().as_uri()
        sections.append(f'<section><h2>{escape(item["label"])} · {escape(item["assessment"]["verdict"])}</h2><video controls src="{video}"></video><div class="grid">{"".join(cards)}</div></section>')
    motions = "".join(f'<article><video controls src="{Path(item["file"]).resolve().as_uri()}"></video><h3>{escape(item["name"])}</h3></article>' for item in report["motion_previews"])
    output.write_text(f'''<!doctype html><html lang="ru"><meta charset="utf-8"><title>{RC_ID}</title><style>body{{font:14px system-ui;background:#0e0e10;color:#eee;margin:24px}}h1{{color:#ffd54a}}section{{margin:32px 0}}video{{width:min(320px,100%);max-height:570px;background:#000}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}article{{background:#19191d;border:1px solid #333;border-radius:14px;padding:12px}}img{{width:100%;aspect-ratio:9/16;object-fit:cover;border-radius:8px}}pre{{font-size:11px;white-space:pre-wrap;max-height:280px;overflow:auto}}</style><body><h1>{RC_ID}</h1><p>Verdict: <b>{escape(report["verdict"])}</b> · real AUTO sources: {report["real_sources"]}</p>{"".join(sections)}<h2>Motion previews</h2><div class="grid">{motions}</div></body></html>''', encoding="utf-8")
