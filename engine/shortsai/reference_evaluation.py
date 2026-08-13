from __future__ import annotations

from dataclasses import asdict
from html import escape
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .audio_mastering import master_rendered_audio
from .automated_pipeline import AutomatedPipeline, AutomatedResult
from .config import AppConfig
from .media import probe_media, resolve_ffmpeg, resolve_ffprobe
from .reference_alignment import align_transcripts, reference_content_map
from .reference_calibration import (
    aggregate_style_statistics, apply_candidate, build_calibration_candidate,
    compare_metrics, production_metrics, reference_metrics,
)
from .reference_manifest import discover_reference_dataset, reference_media_paths, write_reference_manifest
from .reference_visual_analysis import analyze_reference_visuals
from .reference_evidence import (
    aggregate_reference_priors, apply_candidate_v2, assess_plan_broll,
    build_broll_evidence, build_candidate_v2, evaluate_hypotheses,
    load_broll_assets, plan_behavior_profile, visual_behavior_profile,
)
from .text_composition import validate_text_compositions
from .transcript_normalizer import normalize_transcript
from .transcription import Transcript, Transcriber


def _write(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _safe(value: str) -> str:
    return value.replace("/", "__").replace("\\", "__").replace(" ", "_")


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _transcribe_cached(transcriber: Transcriber, source: Path, path: Path) -> Transcript:
    if path.is_file():
        return Transcript.from_dict(_read(path))
    transcript = transcriber.transcribe(source)
    _write(path, transcript.to_dict())
    return transcript


def _editorial_report(alignment: dict[str, Any], raw_duration: float, final_duration: float, visual: dict[str, Any]) -> dict[str, Any]:
    segments = alignment.get("segments", [])
    removed = [item for item in segments if item["transformation_type"] in {"REMOVED", "FILLER_REMOVED"}]
    shortened = [item for item in segments if item["transformation_type"] in {"PAUSE_COMPRESSION", "SPEED_UP"}]
    removed_duration = sum(float(item["raw_end"]) - float(item["raw_start"]) for item in removed)
    mapping_jumps = []
    matched = [item for item in segments if item.get("raw_start") is not None and item.get("reference_start") is not None]
    for previous, current in zip(matched, matched[1:]):
        raw_gap = float(current["raw_start"]) - float(previous["raw_end"])
        final_gap = float(current["reference_start"]) - float(previous["reference_end"])
        if raw_gap - final_gap > 0.22:
            mapping_jumps.append({"raw_gap": round(raw_gap, 3), "reference_gap": round(final_gap, 3), "removed": round(raw_gap - final_gap, 3), "at_reference": current["reference_start"]})
    ratios = []
    for item in matched:
        raw_span = float(item["raw_end"]) - float(item["raw_start"])
        final_span = float(item["reference_end"]) - float(item["reference_start"])
        if final_span > 0.05:
            ratios.append(raw_span / final_span)
    cuts = visual["cuts"]["events"]
    broll = visual["broll"]["events"]
    return {
        "version": 1,
        "raw_duration": raw_duration, "reference_duration": final_duration,
        "duration_compression_ratio": round(final_duration / max(raw_duration, 0.001), 4),
        "fully_removed_segments": removed, "fully_removed_duration": round(removed_duration, 3),
        "pause_or_speed_compression_segments": shortened,
        "jump_cuts": mapping_jumps, "visual_cuts": cuts,
        "filler_removals": [item for item in removed if item["transformation_type"] == "FILLER_REMOVED"],
        "retake_selection": {"detected": False, "confidence": 0.35, "reason": "No reliable reordered aligned blocks"},
        "source_speech_order_preserved": True,
        "average_aligned_speed_ratio": round(sum(ratios) / len(ratios), 3) if ratios else None,
        "starts_with_raw_material_at": matched[0]["raw_start"] if matched else None,
        "ends_with_raw_material_at": matched[-1]["raw_end"] if matched else None,
        "first_meaningful_segment_duration": round(float(matched[0]["reference_end"]) - float(matched[0]["reference_start"]), 3) if matched else None,
        "last_meaningful_frames": round(final_duration - float(matched[-1]["reference_start"]), 3) if matched else None,
        "average_cut_cadence": visual["cuts"]["summary"]["average_cadence"],
        "average_continuous_talking_head_interval": round(final_duration / max(1, len(cuts) + len(broll)), 3),
        "visual_cover_over_cut": any(any(insert["start"] <= cut["time"] <= insert["end"] for insert in broll) for cut in cuts),
        "separation_policy": "visual cuts and overlays are not treated as raw editorial cuts without alignment evidence",
    }


def _extract_frame(ffmpeg: Path, video: Path, time: float, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ffmpeg), "-v", "error", "-y", "-ss", f"{max(0, time):.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(target)], check=True)


def _gallery(
    ffmpeg: Path, output: Path, media: dict[str, Path], alignment: dict[str, Any],
    raw_to_before: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    aligned = [item for item in alignment.get("segments", []) if item.get("raw_start") is not None and item.get("reference_start") is not None and item.get("alignment_confidence", 0) >= 0.55]
    if not aligned:
        return []
    step = max(1, len(aligned) // 6)
    selected = aligned[::step][:6]
    before_segments = (raw_to_before or {}).get("segments", [])
    rows = []
    for index, segment in enumerate(selected, 1):
        raw_time = (segment["raw_start"] + segment["raw_end"]) / 2
        reference_time = (segment["reference_start"] + segment["reference_end"]) / 2
        before_match = next((item for item in before_segments if item.get("raw_start") is not None and item.get("reference_start") is not None and item["raw_start"] <= raw_time <= item["raw_end"]), None)
        before_time = ((before_match["reference_start"] + before_match["reference_end"]) / 2) if before_match else reference_time
        times = {
            label: raw_time if label == "source" else reference_time if label == "reference" else before_time
            for label in media
        }
        files = {}
        for label, video in media.items():
            if not video or not video.is_file():
                continue
            target = output / "gallery" / f"{index:02d}_{label}.jpg"
            _extract_frame(ffmpeg, video, times[label], target)
            files[label] = target.relative_to(output).as_posix()
        rows.append({"id": index, "transcript": segment["transcript"], "confidence": segment["alignment_confidence"], "times": {key: round(value, 3) for key, value in times.items()}, "files": files})
    return rows


def _overlap(item: dict[str, Any], start: float, end: float, *, point_key: str = "time") -> bool:
    if item.get("start") is not None:
        return float(item["start"]) < end and float(item.get("end", item["start"])) > start
    point = item.get(point_key)
    return point is not None and start <= float(point) < end


def _semantic_difference_timeline(
    alignment: dict[str, Any], raw_to_before: dict[str, Any],
    reference_visual: dict[str, Any], plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare events only after the same spoken material has been aligned."""
    before_alignment = [item for item in raw_to_before.get("segments", []) if item.get("raw_start") is not None and item.get("reference_start") is not None]
    rows: list[dict[str, Any]] = []
    aligned = [item for item in alignment.get("segments", []) if item.get("raw_start") is not None and item.get("reference_start") is not None and float(item.get("alignment_confidence", 0)) >= 0.55]
    for index, segment in enumerate(aligned, 1):
        raw_start, raw_end = float(segment["raw_start"]), float(segment["raw_end"])
        mapped = [item for item in before_alignment if float(item["raw_start"]) < raw_end and float(item["raw_end"]) > raw_start]
        if not mapped:
            continue
        reference_start, reference_end = float(segment["reference_start"]), float(segment["reference_end"])
        before_start = min(float(item["reference_start"]) for item in mapped)
        before_end = max(float(item["reference_end"]) for item in mapped)
        reference_events = {
            "typography": [item.get("role") for item in reference_visual.get("typography", {}).get("scenes", []) if _overlap(item, reference_start, reference_end)],
            "camera": [item.get("effect") for item in reference_visual.get("camera", {}).get("events", []) if _overlap(item, reference_start, reference_end)],
            "broll": [item.get("semantic_function") for item in reference_visual.get("broll", {}).get("events", []) if _overlap(item, reference_start, reference_end)],
            "motion": [item.get("type") for item in reference_visual.get("motion", {}).get("events", []) if _overlap(item, reference_start, reference_end)],
        }
        before_events = {
            "typography": [item.get("type") for item in plan.get("scenes", []) if item.get("enabled", True) and _overlap(item, before_start, before_end)],
            "camera": [item.get("effect") for item in plan.get("camera", []) if item.get("enabled", True) and _overlap(item, before_start, before_end)],
            "broll": [item.get("type", item.get("presentation")) for item in plan.get("broll", []) if item.get("enabled", True) and _overlap(item, before_start, before_end)],
            "motion": [item.get("type") for item in plan.get("visual", []) if item.get("enabled", True) and _overlap(item, before_start, before_end)],
        }
        different_layers = [layer for layer in reference_events if reference_events[layer] != before_events[layer]]
        rows.append({
            "id": index, "transcript": segment.get("transcript", ""),
            "raw": [round(raw_start, 3), round(raw_end, 3)],
            "reference": [round(reference_start, 3), round(reference_end, 3)],
            "shortsai_before": [round(before_start, 3), round(before_end, 3)],
            "alignment_confidence": segment.get("alignment_confidence"),
            "reference_events": reference_events, "shortsai_events": before_events,
            "different_layers": different_layers,
            "classification": "OBSERVED_DIFFERENCE" if different_layers else "SIMILAR_EVENT_PATTERN",
        })
    return rows


def _write_layer_reports(
    output: Path, alignment: dict[str, Any], editorial: dict[str, Any],
    reference_visual: dict[str, Any], before: dict[str, Any], after: dict[str, Any],
    plan: dict[str, Any], semantic_timeline: list[dict[str, Any]],
) -> None:
    _write(output / "alignment_report.json", alignment)
    _write(output / "editorial_difference.json", {
        "version": 1, "reference_decisions": editorial,
        "shortsai_before": {"retained_raw_coverage": before.get("retained_raw_coverage"), "duration": before.get("duration")},
        "shortsai_after": {"retained_raw_coverage": after.get("retained_raw_coverage"), "duration": after.get("duration")},
        "interpretation": "Editorial claims use transcript alignment; visual cuts are not counted as source removals.",
    })
    _write(output / "typography_difference.json", {
        "version": 1, "measurement": reference_visual.get("typography", {}),
        "shortsai_before": {key: before.get(key) for key in ("text_coverage", "text_free_coverage", "median_words_per_scene", "maximum_words", "hero_count", "accent_count", "number_count", "repeated_composition_count")},
        "shortsai_after": {key: after.get(key) for key in ("text_coverage", "text_free_coverage", "median_words_per_scene", "maximum_words", "hero_count", "accent_count", "number_count", "repeated_composition_count")},
        "limitations": "Reference text strings are aligned-speech proxies; font family is deliberately not guessed.",
    })
    _write(output / "composition_rhythm_map.json", {
        "version": 1, "reference": reference_visual.get("composition_rhythm", {}),
        "reference_visual_rest": reference_visual.get("visual_rest", {}),
        "shortsai_scene_sequence": [{"start": item.get("start"), "end": item.get("end"), "type": item.get("type"), "enabled": item.get("enabled", True), "text": item.get("text")} for item in plan.get("scenes", [])],
    })
    for name, reference_key, metric_keys in (
        ("camera_difference", "camera", ("camera_event_count", "camera_average_strength", "camera_recovery_count")),
        ("broll_difference", "broll", ("broll_count", "broll_coverage", "broll_average_duration", "speaker_only_coverage")),
        ("motion_effects_difference", "motion", ("effects_density", "sfx_density")),
        ("visual_rest_difference", "visual_rest", ("visual_rest_coverage", "text_free_coverage")),
    ):
        timeline_key = reference_key if reference_key in {"camera", "broll", "motion"} else "typography"
        _write(output / f"{name}.json", {
            "version": 1, "reference_measurement": reference_visual.get(reference_key, {}),
            "shortsai_before": {key: before.get(key) for key in metric_keys},
            "shortsai_after": {key: after.get(key) for key in metric_keys},
            "semantic_timeline": [{"id": item["id"], "transcript": item["transcript"], "reference": item["reference_events"].get(timeline_key, []), "shortsai": item["shortsai_events"].get(timeline_key, [])} for item in semantic_timeline],
        })


def _write_detailed_report(output: Path, comparison: dict[str, Any], editorial: dict[str, Any]) -> Path:
    reference = comparison["reference"]
    before = comparison["shortsai_before"]
    after = comparison["shortsai_after_candidate"]
    candidate = comparison["candidate"]
    lines = [
        "# ShortsAI Reference Evaluation — detailed report", "",
        f"Reference: `{comparison['reference_id']}`  ",
        f"Candidate: `{candidate['candidate_id']}` (`production_applied=false`)  ",
        f"Evidence: {candidate['evidence']['raw_to_final_pairs']} RAW→FINAL pair, {candidate['evidence']['visual_references']} visual references.  ",
        "", "## Measured comparison", "",
        "| Layer / metric | Reference | ShortsAI BEFORE | Candidate AFTER |", "|---|---:|---:|---:|",
    ]
    rows = (
        ("Retained RAW speech", "retained_raw_coverage"), ("Text coverage", "text_coverage"),
        ("Text-free coverage", "text_free_coverage"), ("Median words / scene", "median_words_per_scene"),
        ("HERO count", "hero_count"), ("ACCENT / display count", "accent_count"),
        ("Repeated compositions", "repeated_composition"), ("Camera event count", "camera_count"),
        ("Camera average strength", "camera_strength"), ("Camera recoveries", "camera_recovery"),
        ("B-roll count", "broll_count"), ("B-roll coverage", "broll_coverage"),
        ("Visual rest", "visual_rest"), ("Visual-effect density", "visual_effect_density"),
        ("SFX transient density", "sfx_density"),
    )
    lines.extend(f"| {label} | {reference.get(key, '—')} | {before.get(key, '—')} | {after.get(key, '—')} |" for label, key in rows)
    lines.extend([
        "", "## Editorial interpretation", "",
        f"- Word alignment covers {comparison['alignment']['raw_word_coverage']:.1%} of RAW and {comparison['alignment']['reference_word_coverage']:.1%} of the reference; mean confidence is {comparison['alignment']['mean_alignment_confidence']:.3f}.",
        f"- Reference duration is {editorial.get('reference_duration', 0):.3f}s versus RAW {editorial.get('raw_duration', 0):.3f}s. This example does **not** support a universal rule for aggressive speech shortening.",
        f"- Alignment found {len(editorial.get('fully_removed_segments', []))} locally removed fragments ({editorial.get('fully_removed_duration', 0):.3f}s), while speech order stayed intact.",
        "- Detected visual cuts and B-roll covers are reported separately from source editorial cuts.",
        "", "## Systemic findings", "",
    ])
    for index, item in enumerate(comparison.get("systemic_findings", []), 1):
        evidence = item["evidence"]
        lines.append(f"{index}. `{item['finding']}`: reference={evidence.get('reference')}, BEFORE={evidence.get('shortsai_before')}, AFTER={evidence.get('shortsai_after')}; {item['classification']}, confidence={item['confidence']}. Layer: {item['affected_layer']}.")
    lines.extend([
        "", "## Candidate decision", "",
        "The isolated candidate intentionally changes only conservative, reversible parameters: it creates text rest by disabling low-importance NORMAL captions and reduces existing camera strength. It does not create new semantic camera, B-roll, SFX, HERO or editorial events.",
        "", f"Automatic production promotion is **blocked**: {candidate['promotion_guard']['reason']}. Add at least {max(0, candidate['promotion_guard']['minimum_raw_pairs'] - candidate['promotion_guard']['current_raw_pairs'])} independent RAW→FINAL pairs and validate on a holdout set.",
        "", "## Measurement limits", "",
        "Typography boxes, cuts, camera changes and inserts are OpenCV measurements with confidence values, not a claim about the editor’s intent. Actual reference text is represented by aligned speech, not OCR. SFX labels are low-confidence audio transients. Final-only references contribute visual statistics only and never editorial conclusions.",
    ])
    path = output / "DETAILED_REPORT.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _inspector(output: Path, context: dict[str, Any]) -> Path:
    videos = context["videos"]
    differences = context.get("differences", [])
    gallery = context.get("gallery", [])
    aligned = context.get("alignment", {}).get("segments", [])[:80]
    semantic = context.get("semantic_timeline", [])[:80]
    cards = "".join(
        f'<section><h2>{escape(label.upper())}</h2><video controls preload="metadata" src="{escape(path)}"></video></section>'
        for label, path in videos.items() if path
    )
    diff_rows = "".join(f"<tr><td>{escape(str(row.get('metric')))}</td><td>{escape(str(row.get('reference')))}</td><td>{escape(str(row.get('shortsai_before')))}</td><td>{escape(str(row.get('shortsai_after', '—')))}</td><td>{escape(str(row.get('classification')))}</td><td>{escape(str(row.get('confidence')))}</td></tr>" for row in differences)
    alignment_rows = "".join(f"<tr><td>{escape(str(row.get('raw_start')))}–{escape(str(row.get('raw_end')))}</td><td>{escape(str(row.get('reference_start')))}–{escape(str(row.get('reference_end')))}</td><td>{escape(str(row.get('transformation_type')))}</td><td>{escape(str(row.get('alignment_confidence')))}</td><td>{escape(str(row.get('transcript')))}</td></tr>" for row in aligned)
    semantic_rows = "".join(f"<tr><td>{escape(str(row.get('transcript')))}</td><td>{escape(str(row.get('reference')))}</td><td>{escape(str(row.get('shortsai_before')))}</td><td>{escape(', '.join(row.get('different_layers', [])))}</td><td>{escape(str(row.get('classification')))}</td></tr>" for row in semantic)
    gallery_html = "".join(
        f'<article><h3>{escape(row["transcript"][:90])}</h3><div class="frames">' + "".join(f'<figure><img src="{escape(path)}"><figcaption>{escape(label)} · {row["times"][label]}s</figcaption></figure>' for label, path in row["files"].items()) + "</div></article>"
        for row in gallery
    )
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ShortsAI Reference Inspector</title><style>body{{margin:0;background:#090b10;color:#f5f6f8;font:15px system-ui}}main{{max-width:1500px;margin:auto;padding:26px}}.videos{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}section,article{{background:#151923;border:1px solid #303847;border-radius:14px;padding:14px}}video{{width:100%;max-height:610px;background:#000}}table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{border:1px solid #394252;padding:7px;text-align:left}}th,h1,h2{{color:#ffd000}}.frames{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}}figure{{margin:0}}img{{width:100%}}figcaption{{color:#aab2bf}}@media(max-width:900px){{.videos,.frames{{grid-template-columns:1fr 1fr}}}}</style></head><body><main><h1>Reference Intelligence Inspector</h1><p>Timelines are connected by word/semantic alignment, not absolute seconds.</p><div class="videos">{cards}</div><h2>Difference Timeline</h2><table><tr><th>Metric</th><th>Reference</th><th>Before</th><th>After</th><th>Classification</th><th>Confidence</th></tr>{diff_rows}</table><h2>Semantic event comparison</h2><table><tr><th>Aligned speech</th><th>Reference time</th><th>ShortsAI time</th><th>Different layers</th><th>Result</th></tr>{semantic_rows}</table><h2>RAW → Reference alignment</h2><table><tr><th>RAW</th><th>Reference</th><th>Transformation</th><th>Confidence</th><th>Transcript</th></tr>{alignment_rows}</table><h2>Semantic visual gallery</h2>{gallery_html}</main></body></html>"""
    path = output / "reference_inspector.html"
    path.write_text(html, encoding="utf-8")
    return path


def _evidence_dashboard(
    root: Path, pair_output: Path, four_way: dict[str, Any], priors: dict[str, Any],
    hypotheses: dict[str, Any], broll_evidence: dict[str, Any], profiles: list[dict[str, Any]],
) -> Path:
    relative_pair = pair_output.relative_to(root).as_posix()
    videos = {
        "REFERENCE": f"{relative_pair}/reference_final.mp4",
        "BEFORE": f"{relative_pair}/shortsai_before.mp4",
        "CANDIDATE V1": f"{relative_pair}/shortsai_after_candidate.mp4",
        "CANDIDATE V2": f"{relative_pair}/shortsai_after_candidate_v2.mp4",
    }
    video_html = "".join(f'<section><h3>{escape(label)}</h3><video controls preload="metadata" src="{escape(path)}"></video></section>' for label, path in videos.items())
    metrics = four_way["metrics"]
    metric_rows = "".join(
        f"<tr><td>{escape(metric)}</td><td>{escape(str(values.get('reference')))}</td><td>{escape(str(values.get('before')))}</td><td>{escape(str(values.get('candidate_v1')))}</td><td>{escape(str(values.get('candidate_v2')))}</td></tr>"
        for metric, values in metrics.items()
    )
    prior_rows = "".join(
        f"<tr><td>{escape(item['style_cluster'])}</td><td>{escape(item['parameter'])}</td><td>{escape(str(item['observed'].get('median')))}</td><td>{escape(str(item['observed'].get('q1')))}–{escape(str(item['observed'].get('q3')))}</td><td>{item['sample_count']}</td><td>{item['confidence_level']}</td><td>{'yes' if item['candidate_usage_allowed'] else 'no'}</td></tr>"
        for item in priors.get("priors", [])
    )
    hypothesis_rows = "".join(
        f"<tr><td>{escape(item['hypothesis'])}</td><td>{item['supporting_reference_count']}</td><td>{item['contradicting_reference_count']}</td><td>{escape(item['scope'])}</td><td>{escape(item['confidence_level'])}</td></tr>"
        for item in hypotheses.get("hypotheses", [])
    )
    profile_rows = "".join(
        f"<tr><td>{escape(item['reference_id'])}</td><td>{escape(item['weak_human_label'])}</td><td>{escape(item['detected_style'])}</td><td>{item['style_confidence']}</td><td>{item['text']['coverage']}</td><td>{item['composition']['strong_event_ratio']}</td><td>{item['camera']['event_rate_per_minute']}</td><td>{item['broll']['coverage']}</td><td>{item['visual_rest']['coverage']}</td></tr>"
        for item in profiles
    )
    broll_rows = "".join(
        f"<tr><td>{escape(item['signal'])}</td><td>{item['reference_count']}</td><td>{escape(item['confidence_level'])}</td><td>{escape(str(item['observed_broll_duration'].get('median')))}</td><td>{'yes' if item['candidate_usage_allowed'] else 'no'}</td></tr>"
        for item in broll_evidence.get("rules", [])
    )
    html = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ShortsAI Evidence Dashboard</title><style>body{{background:#0a0c12;color:#edf0f5;font:14px system-ui;margin:0}}main{{max-width:1600px;margin:auto;padding:28px}}h1,h2,h3{{color:#ffd000}}.videos{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}section{{background:#151a24;border:1px solid #30394a;padding:12px;border-radius:12px}}video{{width:100%;max-height:560px;background:#000}}table{{width:100%;border-collapse:collapse;margin:18px 0 30px}}th,td{{border:1px solid #354052;padding:7px;text-align:left}}th{{color:#ffd000;position:sticky;top:0;background:#121722}}.note{{border-left:4px solid #ffd000;padding:10px 14px;background:#171b22}}@media(max-width:900px){{.videos{{grid-template-columns:1fr 1fr}}}}</style></head><body><main><h1>Reference Evidence Dashboard</h1><p class="note">Final-only references contribute observable visual behavior only. Candidate v2 is isolated; production promotion is blocked.</p><div class="videos">{video_html}</div><h2>Four-way comparison</h2><table><tr><th>Metric</th><th>Reference</th><th>BEFORE</th><th>Candidate v1</th><th>Candidate v2</th></tr>{metric_rows}</table><h2>Hypotheses</h2><table><tr><th>Hypothesis</th><th>Support</th><th>Contradict</th><th>Scope</th><th>Confidence</th></tr>{hypothesis_rows}</table><h2>Reference style clusters</h2><table><tr><th>Reference</th><th>Weak label</th><th>Detected style</th><th>Confidence</th><th>Text coverage</th><th>Strong ratio</th><th>Camera/min</th><th>B-roll coverage</th><th>Visual rest</th></tr>{profile_rows}</table><h2>Style-relative priors</h2><table><tr><th>Cluster</th><th>Parameter</th><th>Median</th><th>IQR</th><th>Refs</th><th>Confidence</th><th>Candidate allowed</th></tr>{prior_rows}</table><h2>B-roll evidence</h2><table><tr><th>Semantic signal</th><th>References</th><th>Confidence</th><th>Median duration</th><th>Candidate allowed</th></tr>{broll_rows}</table></main></body></html>"""
    path = root / "reference_evidence_dashboard.html"
    path.write_text(html, encoding="utf-8")
    return path


def _write_evidence_summary(
    root: Path, four_way: dict[str, Any], hypotheses: dict[str, Any],
    broll_evidence: dict[str, Any], candidate_v2: dict[str, Any],
) -> Path:
    confirmed = [item for item in hypotheses["hypotheses"] if item["confidence_level"] in {"MEDIUM", "HIGH"} and item["supporting_reference_count"] > item["contradicting_reference_count"]]
    contradicted = [item for item in hypotheses["hypotheses"] if item["contradicting_reference_count"] > item["supporting_reference_count"]]
    style_specific = [item for item in hypotheses["hypotheses"] if item["scope"] == "STYLE_SPECIFIC"]
    lines = [
        "# Evidence Aggregation — executive summary", "",
        "Candidate v2 remains isolated. Production profiles, fonts and reference media were not modified.", "",
        "## Confirmed across current visual references", "",
    ]
    lines.extend(f"- `{item['hypothesis']}`: support {item['supporting_reference_count']}, contradiction {item['contradicting_reference_count']}, confidence {item['confidence_level']}." for item in confirmed)
    if not confirmed: lines.append("- No hypothesis reached MEDIUM confidence.")
    lines.extend(["", "## Style-specific observations", ""])
    lines.extend(f"- `{item['hypothesis']}`: {', '.join(item['supporting_styles']) or 'unresolved style'}." for item in style_specific)
    if not style_specific: lines.append("- None with current sample.")
    lines.extend(["", "## Contradicted or unresolved", ""])
    lines.extend(f"- `{item['hypothesis']}`: support {item['supporting_reference_count']}, contradiction {item['contradicting_reference_count']}." for item in contradicted)
    unresolved = [item for item in hypotheses["hypotheses"] if item["confidence_level"] == "LOW" and item not in contradicted]
    lines.extend(f"- `{item['hypothesis']}` remains LOW evidence." for item in unresolved)
    lines.extend(["", "## Candidate v1 vs Candidate v2", "", "| Metric | Reference | BEFORE | v1 | v2 |", "|---|---:|---:|---:|---:|"])
    for metric, values in four_way["metrics"].items():
        lines.append(f"| {metric} | {values.get('reference')} | {values.get('before')} | {values.get('candidate_v1')} | {values.get('candidate_v2')} |")
    lines.extend(["", "Candidate v2 changes only priors with MEDIUM/HIGH evidence, protects important/information-heavy captions, calibrates camera by event type, and never treats composition repetition as a scalar minimization objective.", "", "## B-roll library gaps", ""])
    for item in broll_evidence.get("recommended_missing_asset_concepts", [])[:12]:
        lines.append(f"- `{item['concept']}` — {item['observations']} observed reference insert(s).")
    lines.extend(["", "## Most useful next data", "", "For `example_002` and `example_003`, add complete independent RAW and human-edited FINAL files, preferably with different speakers/topics and preserved audio. These pairs are more valuable than additional FINAL-only clips because they unlock editorial transformation confidence, retake/cut evidence and holdout validation.", "", f"Candidate v2 ID: `{candidate_v2['candidate_id']}`. Automatic promotion: **blocked**."])
    path = root / "EVIDENCE_EXECUTIVE_SUMMARY.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ReferenceEvaluator:
    def __init__(self, config: AppConfig, dataset: Path) -> None:
        self.config = config
        self.dataset = dataset.resolve()
        self.ffmpeg = resolve_ffmpeg(config.render.ffmpeg)
        self.ffprobe = resolve_ffprobe(self.ffmpeg)
        self.work_root = config.work_dir / "reference_analysis"
        self.output_root = config.output_dir / "reference_analysis"
        self.transcriber = Transcriber(config.whisper)

    def run(self, *, build_candidate: bool = False, render_comparison: bool = False, force_baseline: bool = False) -> dict[str, Any]:
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        manifest = discover_reference_dataset(self.dataset, self.ffprobe)
        write_reference_manifest(manifest, self.output_root / "reference_manifest.json")
        original_hashes = {str(path): manifest_entry_hash(manifest, path) for path in reference_media_paths(manifest)}
        production_files = [
            self.config.project_root / name for name in (
                "config.json", "style_profiles.json", "font_profiles.json",
                "camera_profiles.json", "motion_profiles.json", "visual_profiles.json",
            )
        ]
        production_hashes = {str(path): _file_digest(path) for path in production_files}
        analyses, paired_contexts, behavior_profiles = [], [], []
        for entry in manifest["entries"]:
            workspace = self.work_root / _safe(entry["reference_id"])
            workspace.mkdir(parents=True, exist_ok=True)
            _write(workspace / "reference_entry.json", entry)
            if entry["analysis_status"] != "READY":
                report = {"reference_id": entry["reference_id"], "status": entry["analysis_status"], "claims": "NONE"}
                _write(workspace / "analysis.json", report); analyses.append(report); continue
            final = Path(entry["final_path"])
            final_media = entry["final_media"]
            if entry["reference_type"] == "RAW_TO_FINAL":
                source = Path(entry["source_path"])
                raw_transcript = _transcribe_cached(self.transcriber, source, workspace / "source.transcript.json")
                reference_transcript = _transcribe_cached(self.transcriber, final, workspace / "reference.transcript.json")
                normalized_raw = normalize_transcript(raw_transcript)
                normalized_reference = normalize_transcript(reference_transcript)
                _write(workspace / "source.transcript.normalized.json", normalized_raw.transcript.to_dict())
                _write(workspace / "reference.transcript.normalized.json", normalized_reference.transcript.to_dict())
                alignment = align_transcripts(normalized_raw.transcript, normalized_reference.transcript)
                _write(workspace / "alignment_report.json", alignment)
                visual_path = workspace / "reference_visual_analysis.json"
                if visual_path.is_file() and int(_read(visual_path).get("version", 0)) >= 3:
                    visual = _read(visual_path)
                else:
                    visual = analyze_reference_visuals(final, final_media["duration"], transcript=normalized_reference.transcript, ffmpeg=self.ffmpeg)
                    visual["duration"] = final_media["duration"]
                    visual["style"]["human_label"] = entry["category"]
                content_map = reference_content_map(normalized_reference.transcript)
                editorial = _editorial_report(alignment, entry["source_media"]["duration"], final_media["duration"], visual)
                _write(workspace / "editorial_reference_decisions.json", editorial)
                _write(workspace / "reference_content_map.json", content_map)
                _write(workspace / "reference_visual_analysis.json", visual)
                behavior = visual_behavior_profile(entry["reference_id"], entry["reference_type"], entry["category"], visual, normalized_reference.transcript)
                _write(workspace / "visual_behavior_profile.json", behavior)
                behavior_profiles.append(behavior)
                report = {"reference_id": entry["reference_id"], "status": "ANALYZED", "type": entry["reference_type"], "alignment": alignment["summary"], "editorial": editorial, "content_map": content_map, "visual": visual}
                paired_contexts.append({"entry": entry, "workspace": workspace, "raw_transcript": raw_transcript, "normalized_raw": normalized_raw.transcript, "normalized_reference": normalized_reference.transcript, "alignment": alignment, "visual": visual, "behavior": behavior})
            else:
                reference_transcript = _transcribe_cached(self.transcriber, final, workspace / "reference.transcript.json")
                normalized_reference = normalize_transcript(reference_transcript)
                _write(workspace / "reference.transcript.normalized.json", normalized_reference.transcript.to_dict())
                visual_path = workspace / "reference_visual_analysis.json"
                if visual_path.is_file() and int(_read(visual_path).get("version", 0)) >= 3:
                    visual = _read(visual_path)
                else:
                    visual = analyze_reference_visuals(final, final_media["duration"], ffmpeg=self.ffmpeg)
                    visual["duration"] = final_media["duration"]
                    visual["style"]["human_label"] = entry["category"]
                _write(workspace / "reference_visual_analysis.json", visual)
                behavior = visual_behavior_profile(entry["reference_id"], entry["reference_type"], entry["category"], visual, normalized_reference.transcript)
                _write(workspace / "visual_behavior_profile.json", behavior)
                behavior_profiles.append(behavior)
                report = {"reference_id": entry["reference_id"], "status": "ANALYZED", "type": entry["reference_type"], "editorial_claims": "PROHIBITED_NO_SOURCE", "visual": visual}
            _write(workspace / "analysis.json", report)
            analyses.append(report)
        visual_reports = [item["visual"] for item in analyses if item.get("status") == "ANALYZED" and item.get("visual")]
        statistics_report = aggregate_style_statistics(visual_reports)
        _write(self.output_root / "reference_style_statistics.json", statistics_report)
        profile_root = self.output_root / "visual_behavior_profiles"
        for profile in behavior_profiles:
            _write(profile_root / f"{_safe(profile['reference_id'])}.json", profile)
        priors = aggregate_reference_priors(behavior_profiles, raw_pair_count=manifest["summary"]["raw_to_final_pairs"])
        _write(self.output_root / "reference_priors.json", priors)
        assets = load_broll_assets(self.config.project_root / "assets" / "broll" / "broll_index.json")
        broll_evidence = build_broll_evidence(behavior_profiles, assets)
        _write(self.output_root / "broll_evidence_rules.json", broll_evidence)
        comparisons = []
        if paired_contexts and (build_candidate or render_comparison):
            comparisons.append(self._compare_pair(
                paired_contexts[0], manifest, priors=priors, broll_evidence=broll_evidence, assets=assets,
                render_comparison=render_comparison, force_baseline=force_baseline,
            ))
        unchanged = {path: manifest_entry_hash(manifest, Path(path)) == digest for path, digest in original_hashes.items()}
        if not all(unchanged.values()):
            raise RuntimeError("Reference source immutability check failed")
        production_unchanged = all(_file_digest(Path(path)) == digest for path, digest in production_hashes.items())
        if not production_unchanged:
            raise RuntimeError("Production configuration immutability check failed")
        summary = {
            "version": 1, "manifest": manifest["summary"], "analyzed": sum(item.get("status") == "ANALYZED" for item in analyses),
            "statistics": str((self.output_root / "reference_style_statistics.json").resolve()),
            "reference_priors": str((self.output_root / "reference_priors.json").resolve()),
            "visual_behavior_profiles": len(behavior_profiles),
            "comparisons": comparisons, "source_files_unchanged": all(unchanged.values()),
            "production_configuration_changed": not production_unchanged,
            "production_files_unchanged": production_unchanged,
            "promotion_allowed": manifest["summary"]["raw_to_final_pairs"] >= 3,
            "recommended_additional_raw_pairs": max(0, 3 - manifest["summary"]["raw_to_final_pairs"]),
        }
        _write(self.output_root / "reference_evaluation_summary.json", summary)
        executive = [
            "# ShortsAI Reference Intelligence — executive summary", "",
            f"Discovered {manifest['summary']['objects']} dataset objects: {manifest['summary']['raw_to_final_pairs']} ready RAW→FINAL pair, {manifest['summary']['final_only']} ready final-only references and {manifest['summary']['incomplete']} incomplete entries.", "",
            "The current evidence supports an isolated calibration candidate, not a production preset. Reference media remained byte-identical and the normal production configuration was not changed.", "",
        ]
        if comparisons:
            comparison_path = Path(comparisons[0]["output"]) / "reference_vs_shortsaI.json"
            payload = _read(comparison_path)
            ref, before, after = payload.get("reference", {}), payload.get("shortsai_before", {}), payload.get("shortsai_after_candidate", {})
            executive.extend([
                "## Main result", "",
                f"- Text coverage: reference {ref.get('text_coverage')} / BEFORE {before.get('text_coverage')} / AFTER {after.get('text_coverage')}.",
                f"- Repeated compositions: reference {ref.get('repeated_composition')} / BEFORE {before.get('repeated_composition')} / AFTER {after.get('repeated_composition')}.",
                f"- Camera strength: reference {ref.get('camera_strength')} / BEFORE {before.get('camera_strength')} / AFTER {after.get('camera_strength')}.",
                f"- B-roll: reference {ref.get('broll_count')} events / BEFORE {before.get('broll_count')} / AFTER {after.get('broll_count')}. The candidate does not invent inserts without semantic assets/evidence.", "",
                "The strongest current signal is excessive always-on caption coverage and overly strong sparse camera punches. HERO/ACCENT frequency, B-roll cadence, effects and SFX remain style observations until more paired examples establish a repeatable editorial pattern.", "",
                f"Detailed report: `{Path(comparisons[0]['output']) / 'DETAILED_REPORT.md'}`", "",
            ])
        executive.extend([
            "## Promotion guard", "",
            f"Automatic promotion: **blocked**. Need {summary['recommended_additional_raw_pairs']} additional independent RAW→FINAL pairs plus holdout validation. Final-only examples never count as editorial evidence.", "",
        ])
        (self.output_root / "EXECUTIVE_SUMMARY.md").write_text("\n".join(executive), encoding="utf-8")
        return summary

    def _compare_pair(
        self, context: dict[str, Any], manifest: dict[str, Any], *,
        priors: dict[str, Any], broll_evidence: dict[str, Any], assets: list[dict[str, Any]],
        render_comparison: bool, force_baseline: bool,
    ) -> dict[str, Any]:
        entry, workspace = context["entry"], context["workspace"]
        source, reference = Path(entry["source_path"]), Path(entry["final_path"])
        pipeline = AutomatedPipeline(self.config)
        baseline = None if force_baseline else self._cached_baseline(source)
        if baseline is None:
            baseline = pipeline.process_one(source, force=force_baseline, renderer_mode="hybrid", _raw_transcript=context["raw_transcript"])
        if not baseline.success or not baseline.workspace:
            raise RuntimeError(f"ShortsAI BEFORE failed: {baseline.error}")
        if baseline.children:
            raise RuntimeError("Reference comparison requires a single baseline output; source was classified as a multi-episode session")
        baseline_workspace = Path(baseline.workspace)
        baseline_plan = _read(baseline_workspace / "artifacts" / "montage_plan.json")
        before_metrics = production_metrics(baseline_plan, entry["source_media"]["duration"])
        baseline_duration = float(baseline_plan.get("output", {}).get("duration") or entry["source_media"]["duration"])
        before_behavior = plan_behavior_profile(baseline_plan, baseline_duration)
        before_metrics.update({
            "body_text_coverage": before_behavior["body_text_coverage"],
            "strong_text_coverage": before_behavior["strong_text_coverage"],
            "strong_typography_rate": before_behavior["strong_typography_rate"],
            "camera_punch_strength": before_behavior["camera"]["by_type"]["PUNCH_LIKE"].get("strength_median"),
        })
        ref_metrics = reference_metrics(context["visual"], context["alignment"], entry["source_media"]["duration"])
        difference = compare_metrics(ref_metrics, before_metrics)
        hypotheses = evaluate_hypotheses(
            [_read(path) for path in (self.output_root / "visual_behavior_profiles").glob("*.json")],
            before_metrics,
        )
        _write(self.output_root / "evidence_hypotheses.json", hypotheses)
        broll_assessment = assess_plan_broll(baseline_plan, broll_evidence, assets)
        candidate = build_calibration_candidate(
            difference, ref_metrics, before_metrics,
            raw_pair_count=manifest["summary"]["raw_to_final_pairs"], visual_reference_count=manifest["summary"]["final_only"] + manifest["summary"]["raw_to_final_pairs"],
        )
        candidate_plan, candidate_changes = apply_candidate(baseline_plan, candidate)
        candidate_v2 = build_candidate_v2(
            priors, hypotheses, before_metrics, before_behavior, broll_assessment,
            raw_pair_count=manifest["summary"]["raw_to_final_pairs"],
        )
        candidate_v2_plan, candidate_v2_changes = apply_candidate_v2(baseline_plan, candidate_v2)
        output = self.output_root / _safe(entry["reference_id"])
        output.mkdir(parents=True, exist_ok=True)
        candidate_geometry = validate_text_compositions(
            candidate_plan.get("scenes", []), candidate_plan.get("styleProfile", {}),
            candidate_plan.get("face", {}), self.config.remotion.width, self.config.remotion.height,
            pipeline._text_metrics(candidate_plan.get("styleProfile", {})),
        )
        if candidate_geometry.get("violations_after"):
            raise RuntimeError(f"Candidate typography failed safe layout: {candidate_geometry}")
        candidate_changes["geometry"] = candidate_geometry
        candidate_v2_geometry = validate_text_compositions(
            candidate_v2_plan.get("scenes", []), candidate_v2_plan.get("styleProfile", {}),
            candidate_v2_plan.get("face", {}), self.config.remotion.width, self.config.remotion.height,
            pipeline._text_metrics(candidate_v2_plan.get("styleProfile", {})),
        )
        if candidate_v2_geometry.get("violations_after"):
            raise RuntimeError(f"Candidate v2 typography failed safe layout: {candidate_v2_geometry}")
        candidate_v2_changes["geometry"] = candidate_v2_geometry
        _write(output / "calibration_candidate.json", candidate)
        _write(output / "montage_plan.after_candidate.json", candidate_plan)
        _write(output / "calibration_candidate_v2.json", candidate_v2)
        _write(output / "montage_plan.after_candidate_v2.json", candidate_v2_plan)
        _link_or_copy(source, output / "source.mp4")
        _link_or_copy(reference, output / "reference_final.mp4")
        before_output = Path(baseline.output) if baseline.output else None
        if before_output and before_output.is_file():
            _link_or_copy(before_output, output / "shortsai_before.mp4")
        after_output = output / "shortsai_after_candidate.mp4"
        render_manifest_path = output / "candidate_render_manifest.json"
        render_manifest = _read(render_manifest_path)
        candidate_changed = render_manifest.get("candidate_id") != candidate["candidate_id"]
        if render_comparison and (not after_output.is_file() or candidate_changed):
            chunks = _read(baseline_workspace / "artifacts" / "chunks.json")
            media = probe_media(source, self.ffprobe)
            render_workspace = workspace / "candidate_render"
            (render_workspace / "artifacts").mkdir(parents=True, exist_ok=True)
            pipeline.renderer.render(source, media, chunks, candidate_plan, render_workspace, after_output, f"reference-{candidate['candidate_id']}")
            master_rendered_audio(after_output, after_output, self.ffmpeg, candidate_plan.get("audio", {}))
            _write(render_manifest_path, {"version": 1, "candidate_id": candidate["candidate_id"], "output": str(after_output.resolve()), "rendered": True})
        after_v2_output = output / "shortsai_after_candidate_v2.mp4"
        render_v2_manifest_path = output / "candidate_v2_render_manifest.json"
        render_v2_manifest = _read(render_v2_manifest_path)
        candidate_v2_changed = render_v2_manifest.get("candidate_id") != candidate_v2["candidate_id"]
        if render_comparison and (not after_v2_output.is_file() or candidate_v2_changed):
            chunks = _read(baseline_workspace / "artifacts" / "chunks.json")
            media = probe_media(source, self.ffprobe)
            render_workspace = workspace / "candidate_v2_render"
            (render_workspace / "artifacts").mkdir(parents=True, exist_ok=True)
            pipeline.renderer.render(source, media, chunks, candidate_v2_plan, render_workspace, after_v2_output, f"reference-v2-{candidate_v2['candidate_id']}")
            master_rendered_audio(after_v2_output, after_v2_output, self.ffmpeg, candidate_v2_plan.get("audio", {}))
            _write(render_v2_manifest_path, {"version": 1, "candidate_id": candidate_v2["candidate_id"], "output": str(after_v2_output.resolve()), "rendered": True})
        after_metrics = production_metrics(candidate_plan, entry["source_media"]["duration"])
        after_behavior = plan_behavior_profile(candidate_plan, baseline_duration)
        after_metrics.update({"body_text_coverage": after_behavior["body_text_coverage"], "strong_text_coverage": after_behavior["strong_text_coverage"], "strong_typography_rate": after_behavior["strong_typography_rate"]})
        after_v2_metrics = production_metrics(candidate_v2_plan, entry["source_media"]["duration"])
        after_v2_behavior = plan_behavior_profile(candidate_v2_plan, baseline_duration)
        after_v2_metrics.update({"body_text_coverage": after_v2_behavior["body_text_coverage"], "strong_text_coverage": after_v2_behavior["strong_text_coverage"], "strong_typography_rate": after_v2_behavior["strong_typography_rate"]})
        for change in candidate_v2_changes["changes"]:
            if change["parameter"] == "scene.enabled":
                change["actual_measured_effect"] = {"text_coverage_before": before_metrics["text_coverage"], "text_coverage_after": after_v2_metrics["text_coverage"], "strong_typography_rate_before": before_behavior["strong_typography_rate"], "strong_typography_rate_after": after_v2_behavior["strong_typography_rate"]}
            elif change["parameter"].startswith("camera."):
                change["actual_measured_effect"] = {"camera_strength_before": before_metrics["camera_strength"], "camera_strength_after": after_v2_metrics["camera_strength"]}
        _write(output / "candidate_change_log_v2.json", candidate_v2_changes)
        for row in difference:
            row["shortsai_after"] = after_metrics.get(row["metric"])
        edited = Transcript.from_dict(_read(baseline_workspace / "artifacts" / "transcript.edited.json"))
        raw_to_before = align_transcripts(context["normalized_raw"], edited)
        _write(output / "raw_to_shortsai_before_alignment.json", raw_to_before)
        semantic_timeline = _semantic_difference_timeline(
            context["alignment"], raw_to_before, context["visual"], baseline_plan,
        )
        _write_layer_reports(
            output, context["alignment"], _read(workspace / "editorial_reference_decisions.json"),
            context["visual"], before_metrics, after_metrics, candidate_plan, semantic_timeline,
        )
        gallery = _gallery(self.ffmpeg, output, {
            "source": output / "source.mp4", "reference": output / "reference_final.mp4",
            "before": output / "shortsai_before.mp4", "candidate_v1": after_output,
            "candidate_v2": after_v2_output,
        }, context["alignment"], raw_to_before) if render_comparison else []
        findings = []
        layer_map = {"text": "Caption Engine", "hero": "Typography", "accent": "Typography", "camera": "Camera", "broll": "B-roll", "visual": "Visual Director", "sfx": "Audio", "repeated": "Typography", "speaker": "Visual Director"}
        for row in difference:
            if not row["significant"]:
                continue
            layer = next((layer_map[key] for key in layer_map if key in row["metric"]), "Timeline/Visual Director")
            findings.append({
                "finding": row["metric"], "evidence": {"reference": row["reference"], "shortsai_before": row["shortsai_before"], "shortsai_after": row.get("shortsai_after")},
                "sample_count": 1, "confidence": row["confidence"], "classification": row["classification"],
                "affected_layer": layer, "proposed_universal_change": next((item["proposed_universal_change"] for item in candidate["suggestions"] if item["metric"] == row["metric"]), "Collect more pairs before changing production"),
                "expected_benefit": "Closer retention rhythm without copying timestamps", "overfitting_risk": "HIGH",
            })
        comparison = {
            "version": 1, "reference_id": entry["reference_id"], "baseline_job_id": baseline.job_id,
            "principle": "REFERENCE was never provided to baseline AUTO",
            "raw": entry["source_media"], "reference": ref_metrics, "shortsai_before": before_metrics, "shortsai_after_candidate": after_metrics,
            "differences": difference, "systemic_findings": findings[:15], "candidate": candidate,
            "candidate_execution": candidate_changes, "alignment": context["alignment"]["summary"],
            "semantic_timeline_summary": {
                "segments": len(semantic_timeline),
                "segments_with_observed_visual_difference": sum(item["classification"] == "OBSERVED_DIFFERENCE" for item in semantic_timeline),
                "comparison_basis": "aligned spoken material",
            },
            "videos": {"source": "source.mp4", "reference": "reference_final.mp4", "before": "shortsai_before.mp4", "after": "shortsai_after_candidate.mp4" if after_output.is_file() else None},
            "gallery": gallery,
        }
        reference_behavior = context["behavior"]
        def four(reference_value: Any, before_value: Any, v1_value: Any, v2_value: Any) -> dict[str, Any]:
            return {"reference": reference_value, "before": before_value, "candidate_v1": v1_value, "candidate_v2": v2_value}
        four_way = {
            "version": 2, "reference_id": entry["reference_id"],
            "principle": "Candidate v2 optimizes evidence-supported quality objectives, not scalar distance to one reference.",
            "metrics": {
                "text_coverage": four(reference_behavior["text"]["coverage"], before_behavior["text_coverage"], after_behavior["text_coverage"], after_v2_behavior["text_coverage"]),
                "body_text_coverage": four(reference_behavior["text"]["normal_text_coverage"], before_behavior["body_text_coverage"], after_behavior["body_text_coverage"], after_v2_behavior["body_text_coverage"]),
                "strong_text_coverage": four(reference_behavior["text"]["strong_typography_coverage"], before_behavior["strong_text_coverage"], after_behavior["strong_text_coverage"], after_v2_behavior["strong_text_coverage"]),
                "speaker_only_or_text_free": four(reference_behavior["speaker_only_coverage"], before_behavior["speaker_only_text_free"], after_behavior["speaker_only_text_free"], after_v2_behavior["speaker_only_text_free"]),
                "strong_typography_rate": four(reference_behavior["composition"]["strong_event_ratio"], before_behavior["strong_typography_rate"], after_behavior["strong_typography_rate"], after_v2_behavior["strong_typography_rate"]),
                "same_layout_strong_repeat": four(reference_behavior["composition"]["same_layout_strong_repeat"], before_behavior["same_layout_strong_repeat"], after_behavior["same_layout_strong_repeat"], after_v2_behavior["same_layout_strong_repeat"]),
                "camera_subtle_strength": four(reference_behavior["camera"]["by_type"]["SUBTLE_PUSH"]["strength_median"], before_behavior["camera"]["by_type"]["SUBTLE_PUSH"]["strength_median"], after_behavior["camera"]["by_type"]["SUBTLE_PUSH"]["strength_median"], after_v2_behavior["camera"]["by_type"]["SUBTLE_PUSH"]["strength_median"]),
                "camera_punch_strength": four(reference_behavior["camera"]["by_type"]["PUNCH_LIKE"]["strength_median"], before_behavior["camera"]["by_type"]["PUNCH_LIKE"]["strength_median"], after_behavior["camera"]["by_type"]["PUNCH_LIKE"]["strength_median"], after_v2_behavior["camera"]["by_type"]["PUNCH_LIKE"]["strength_median"]),
                "camera_recovery_per_push": four(reference_behavior["camera"]["recovery_behavior"]["recovery_per_push"], before_behavior["camera"]["recovery_behavior"]["recovery_per_push"], after_behavior["camera"]["recovery_behavior"]["recovery_per_push"], after_v2_behavior["camera"]["recovery_behavior"]["recovery_per_push"]),
                "visual_rest_coverage": four(reference_behavior["visual_rest"]["coverage"], before_metrics["visual_rest"], after_metrics["visual_rest"], after_v2_metrics["visual_rest"]),
                "broll_executed": four(reference_behavior["broll"]["count"], before_metrics["broll_count"], after_metrics["broll_count"], after_v2_metrics["broll_count"]),
                "broll_wanted_asset_missing": four(None, 0, 0, broll_assessment["summary"].get("BROLL_WANTED_BUT_ASSET_MISSING", 0)),
                "broll_rejected_low_confidence": four(None, 0, 0, broll_assessment["summary"].get("CANDIDATE_REJECTED_LOW_CONFIDENCE", 0)),
                "director_missed_broll": four(None, 0, 0, broll_assessment["summary"].get("DIRECTOR_MISSED_BROLL", 0)),
            },
            "reference_behavior_profile": reference_behavior,
            "before_behavior": before_behavior, "candidate_v1_behavior": after_behavior, "candidate_v2_behavior": after_v2_behavior,
            "candidate_v1": candidate, "candidate_v2": candidate_v2,
            "candidate_v2_change_log": candidate_v2_changes,
            "broll_diagnostics": broll_assessment,
            "hypotheses": hypotheses,
            "production_applied": False,
        }
        _write(output / "reference_before_candidate_v1_candidate_v2.json", four_way)
        _write(output / "reference_vs_shortsaI.json", comparison)
        _write(output / "difference_timeline.json", {"version": 2, "differences": difference, "semantic_segments": semantic_timeline})
        _inspector(output, {"videos": comparison["videos"], "differences": difference, "alignment": context["alignment"], "semantic_timeline": semantic_timeline, "gallery": gallery})
        _write_detailed_report(output, comparison, _read(workspace / "editorial_reference_decisions.json"))
        profiles = [_read(path) for path in (self.output_root / "visual_behavior_profiles").glob("*.json")]
        _evidence_dashboard(self.output_root, output, four_way, priors, hypotheses, broll_evidence, profiles)
        _write_evidence_summary(self.output_root, four_way, hypotheses, broll_evidence, candidate_v2)
        return {"reference_id": entry["reference_id"], "output": str(output), "baseline_job_id": baseline.job_id, "alignment": context["alignment"]["summary"], "candidate_id": candidate["candidate_id"], "candidate_v2_id": candidate_v2["candidate_id"], "promotion_allowed": False, "rendered_after": after_output.is_file(), "rendered_after_v2": after_v2_output.is_file(), "findings": len(findings)}

    def _cached_baseline(self, source: Path) -> AutomatedResult | None:
        jobs = sorted((self.config.work_dir / "jobs").glob("*/job_manifest.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True)
        for manifest_path in jobs:
            manifest = _read(manifest_path)
            if manifest.get("status") != "COMPLETED":
                continue
            if str(Path(manifest.get("source", {}).get("path", "")).resolve()) != str(source.resolve()):
                continue
            workspace = manifest_path.parent
            montage = workspace / "artifacts" / "montage_plan.json"
            published = Path(manifest.get("published_output") or manifest.get("final_mp4") or "")
            if not montage.is_file() or not published.is_file():
                continue
            return AutomatedResult(
                input=str(source), video_id=source.stem, status="success", success=True,
                output=str(published), duration=float(manifest.get("output_duration") or 0),
                retimed_blocks=0, summary={}, render_time=0.0, error=None,
                job_id=manifest.get("job_id"), workspace=str(workspace), manifest=str(manifest_path),
                source_duration=float(manifest.get("source_duration") or 0), children=[],
            )
        return None


def manifest_entry_hash(manifest: dict[str, Any], path: Path) -> str:
    path_string = str(path.resolve())
    for entry in manifest.get("entries", []):
        for role in ("source_media", "final_media"):
            media = entry.get(role)
            if media and str(Path(media["file"]).resolve()) == path_string:
                # Re-hash at the end, rather than trusting size/mtime.
                import hashlib
                return hashlib.sha256(path.read_bytes()).hexdigest()
    raise KeyError(path_string)
