from __future__ import annotations

from dataclasses import asdict
from html import escape
import json
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterable

from .automated_pipeline import AutomatedPipeline, AutomatedResult
from .discovery import discover_videos


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _avg(values: Iterable[float | int | None]) -> float | None:
    actual = [float(value) for value in values if value is not None]
    return round(mean(actual), 4) if actual else None


def evaluation_summary(result: AutomatedResult) -> dict[str, Any]:
    workspace = Path(result.workspace) if result.workspace else None
    execution = _read(workspace / "artifacts" / "director_execution_plan.json") if workspace else {}
    director = _read(workspace / "artifacts" / "director_plan.json") if workspace else {}
    quality = _read(workspace / "artifacts" / "quality_report.json") if workspace else {}
    style = _read(workspace / "artifacts" / "director_style.json") if workspace else {}
    speech = _read(workspace / "artifacts" / "speech_edit_plan.json") if workspace else {}
    scenes = execution.get("text_actions", [])
    distribution: dict[str, int] = {}
    for scene in scenes:
        role = str(scene.get("scene_type", scene.get("semantic_type", "NORMAL"))).upper()
        distribution[role] = distribution.get(role, 0) + 1
    broll = [item for item in execution.get("broll_actions", []) if item.get("enabled", True)]
    broll_duration = sum(max(0.0, float(item.get("to", 0)) - float(item.get("from", 0))) for item in broll)
    assets = {
        shot.get("file") for event in broll for shot in event.get("shots", [event]) if shot.get("file")
    }
    metrics = quality.get("metrics", {})
    penalties = metrics.get("visual_penalties", {})
    source_duration = result.source_duration
    output_duration = result.duration if result.duration else speech.get("output_duration")
    return {
        "input": result.input, "job_id": result.job_id, "status": result.status,
        "error": result.error, "workspace": result.workspace, "output": result.output,
        "source_duration": source_duration, "output_duration": output_duration,
        "style_profile": style.get("profile", director.get("profile")),
        "style_confidence": style.get("confidence"),
        "hook_score": quality.get("hook_score", director.get("hook", {}).get("score")),
        "semantic_segments": len(director.get("segments", [])) if director else None,
        "scene_distribution": distribution or None,
        "text_actions": len(execution.get("text_actions", [])) if execution else None,
        "camera_actions": len(execution.get("camera_actions", [])) if execution else None,
        "visual_actions": len(execution.get("visual_actions", [])) if execution else None,
        "sfx_actions": len(execution.get("audio_actions", [])) if execution else None,
        "broll_candidates": len(execution.get("broll_requests", [])) if execution else None,
        "broll_used": len(broll) if execution else None,
        "broll_duration": round(broll_duration, 3) if execution else None,
        "broll_coverage": metrics.get("broll_coverage"),
        "unique_assets": len(assets) if execution else None,
        "speaker_only_coverage": metrics.get("speaker_only_coverage"),
        "face_safety": quality.get("face_safety_score"),
        "repeated_composition": penalties.get("repeated_composition"),
        "broll_text_mismatch": penalties.get("broll_text_mismatch"),
        "end_zone_broll": penalties.get("end_zone_broll"),
        "awkward_side_layout": penalties.get("awkward_side_layout"),
        "vertical_text_stack": penalties.get("vertical_text_stack"),
        "effect_overdensity": penalties.get("effect_overdensity"),
        "quality_score": quality.get("final_score"),
        "quality_metrics": metrics or None,
    }


def aggregate_report(rows: list[dict[str, Any]], input_dir: Path) -> dict[str, Any]:
    warning_fields = (
        "repeated_composition", "broll_text_mismatch", "end_zone_broll",
        "awkward_side_layout", "vertical_text_stack", "effect_overdensity",
    )
    warnings = [
        {"job_id": row.get("job_id"), "input": row.get("input"),
         "metrics": {key: row.get(key) for key in warning_fields if row.get(key)}}
        for row in rows if any(row.get(key) for key in warning_fields)
    ]
    return {
        "version": 1, "input_dir": str(input_dir.resolve()), "concurrency": 1,
        "processed": len(rows), "completed": sum(row.get("status") in {"success", "skipped"} for row in rows),
        "failed": sum(row.get("status") == "failed" for row in rows),
        "averages": {
            "quality_score": _avg(row.get("quality_score") for row in rows),
            "broll_coverage": _avg(row.get("broll_coverage") for row in rows),
            "camera_actions": _avg(row.get("camera_actions") for row in rows),
            "repeated_composition": _avg(row.get("repeated_composition") for row in rows),
        },
        "warnings": warnings, "results": rows,
    }


def write_batch_report(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, html_path = output_dir / "batch_report.json", output_dir / "batch_report.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = ("status", "input", "job_id", "style_profile", "style_confidence", "quality_score", "hook_score", "camera_actions", "broll_used", "broll_coverage", "repeated_composition", "face_safety", "effect_overdensity", "error")
    body = "".join("<tr>" + "".join(f"<td>{escape(str(row.get(key, 'N/A') if row.get(key) is not None else 'N/A'))}</td>" for key in columns) + "</tr>" for row in report["results"])
    headers = "".join(f"<th>{escape(key)}</th>" for key in columns)
    html_path.write_text(f"""<!doctype html><html><head><meta charset="utf-8"><title>ShortsAI Batch Report</title><style>body{{font:14px Segoe UI,sans-serif;margin:22px;background:#111;color:#eee}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #444;padding:7px}}th{{background:#292929;position:sticky;top:0}}.ok{{color:#7ee787}}</style></head><body><h1>ShortsAI Batch Evaluation</h1><p>Processed: {report['processed']}; completed: {report['completed']}; failed: {report['failed']}; averages: {escape(str(report['averages']))}</p><table><thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></body></html>""", encoding="utf-8")
    return json_path, html_path


def run_batch_evaluation(
    pipeline: AutomatedPipeline, input_dir: Path, *, force: bool = False,
    style_name: str | None = None, renderer_mode: str | None = None,
    debug: bool = False, processor: Callable[[Path], AutomatedResult] | None = None,
) -> tuple[list[AutomatedResult], dict[str, Any]]:
    videos = discover_videos(input_dir, pipeline.config.video_extensions)
    results: list[AutomatedResult] = []
    for video in videos:
        try:
            if processor is not None:
                result = processor(video)
            else:
                result = pipeline.process_one(
                    video, force=force, style_name=style_name, renderer_mode=renderer_mode,
                    debug=debug, batch=True,
                )
        except Exception as error:
            result = AutomatedResult(
                input=str(video), video_id=video.stem, status="failed", success=False,
                output=None, duration=0.0, retimed_blocks=0, summary={}, render_time=0.0,
                error=f"{type(error).__name__}: {error}",
            )
        results.append(result)
    summaries: list[dict[str, Any]] = []
    for result in results:
        summary = evaluation_summary(result)
        summaries.append(summary)
        if result.workspace:
            path = Path(result.workspace) / "artifacts" / "evaluation_summary.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            if result.manifest and Path(result.manifest).is_file():
                manifest = _read(Path(result.manifest))
                manifest.setdefault("artifacts", {})["evaluation_summary"] = str(path.resolve())
                Path(result.manifest).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return results, aggregate_report(summaries, input_dir)
