from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import traceback
from typing import Any, Iterable

from .config import AppConfig
from .audio_mastering import create_audio_plan, master_rendered_audio, measure_loudness
from .ai_director import build_director_plan
from .asset_library import build_asset_catalog
from .director_execution import build_director_execution_plan
from .clip_visual_adapter import build_clip_visual_plan, normalize_renderer_mode
from .broll_library import library_signature
from .broll_planner import build_broll_plan
from .broll_report import write_broll_inspector
from .face_tracking import analyze_faces
from .fonts import resolve_font_family, resolve_font_file
from .font_inventory import build_font_manifest, resolve_manifest_font
from .font_profile_selector import select_font_profile
from .director_profile_selector import select_director_profile
from .media import MediaInfo, probe_media, resolve_ffmpeg, resolve_ffprobe, source_fingerprint
from .montage_plan import build_montage_plan, create_preview_events, plan_summary
from .quality_report import build_quality_report, build_rendered_frame_qc
from .remotion_runner import RemotionRenderer
from .retime import retime_words
from .semantic_analysis import analyze_transcript
from .speech_edit import apply_speech_edit, build_speech_edit_plan, transcript_from_edited_words
from .style_profiles import get_style_profile, merge_render_style
from .text_correction import correct_transcript
from .transcript_normalizer import chunks_from_normalized, normalize_transcript
from .transcription import Transcript, Transcriber
from .validation import validate_montage_plan, validate_output, validate_source
from .debug_inspector import build_director_debug, write_debug_inspector
from .jobs import JobContext, publish_output
from .raw_session import analyze_raw_session, build_episode_transcript, extract_episode_source, write_session_preview
from .editorial_quality import build_editorial_quality_plan
from .timeline_builder import build_timeline_plan


PIPELINE_VERSION = 23
RELEASE_CANDIDATE = "TALKING_HEAD_V1_RC"


@dataclass
class AutomatedResult:
    input: str
    video_id: str
    status: str
    success: bool
    output: str | None
    duration: float
    retimed_blocks: int
    summary: dict[str, Any]
    render_time: float
    error: str | None = None
    job_id: str | None = None
    workspace: str | None = None
    manifest: str | None = None
    source_duration: float | None = None
    children: list[dict[str, Any]] | None = None


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned or "video"


def _video_id(video: Path, input_dir: Path) -> str:
    try:
        relative = video.resolve().relative_to(input_dir.resolve()).with_suffix("")
        return _safe_name("__".join(relative.parts))
    except ValueError:
        return _safe_name(video.stem)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _corrections_signature(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"file": str(path.resolve()), "size": 0, "mtime_ns": 0}
    stat = path.stat()
    return {"file": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _directory_signature(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    result: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower()):
        if path.name.lower() in {"index.json", "broll_index.json", "broll_manifest.json", "asset_index.json"}:
            continue
        stat = path.stat()
        result.append({"file": path.relative_to(root).as_posix(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return result


def _json_value(value: Any) -> Any:
    """Normalize tuples and other JSON-compatible values before fingerprint comparison."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _chunks_from_transcripts(raw: Transcript, corrected: Transcript) -> list[dict[str, Any]]:
    raw_words = [word for segment in raw.segments for word in segment.words]
    corrected_words = [word for segment in corrected.segments for word in segment.words]
    chunks: list[dict[str, Any]] = []
    previous_end = -1.0
    for word in corrected_words:
        if word.start < previous_end - 0.001 or word.end < word.start:
            raise ValueError("Text correction produced non-monotonic word timestamps")
        sources = [
            source for source in raw_words
            if source.end > word.start + 0.001 and source.start < word.end - 0.001
        ]
        if not sources:
            sources = [
                source for source in raw_words
                if abs(source.start - word.start) <= 0.001 or abs(source.end - word.end) <= 0.001
            ]
        chunks.append({
            "source_word": " ".join(source.text for source in sources).strip() or word.text,
            "word": word.text,
            "start": round(word.start, 3),
            "end": round(word.end, 3),
            "probability": round(word.probability, 4),
        })
        previous_end = word.end
    return chunks


def _map_time_through_timeline(timestamp: float, timeline: list[dict[str, Any]]) -> float | None:
    for item in timeline:
        source_start, source_end = float(item["source_start"]), float(item["source_end"])
        if source_start - 0.01 <= timestamp <= source_end + 0.01:
            speed = max(0.001, float(item.get("speed", 1.0)))
            return round(float(item["output_start"]) + max(0.0, timestamp - source_start) / speed, 3)
    return None


def _retime_editorial_actions(editorial: dict[str, Any], speech_plan: dict[str, Any]) -> None:
    timeline = list(speech_plan.get("timeline", []))
    for action in editorial.get("editorial_internal_actions", []):
        coordinates = action.get("output_coordinates") or {}
        start = _map_time_through_timeline(float(coordinates.get("start", 0.0)), timeline)
        end = _map_time_through_timeline(float(coordinates.get("end", coordinates.get("start", 0.0))), timeline)
        action["final_output_coordinates"] = (
            {"start": start, "end": end} if start is not None and end is not None else None
        )


class AutomatedPipeline:
    """Primary Whisper -> retime -> montage plan -> Remotion batch pipeline."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.transcriber = Transcriber(config.whisper)
        self.renderer = RemotionRenderer(config)
        self.ffmpeg = resolve_ffmpeg(config.render.ffmpeg)
        self.ffprobe = resolve_ffprobe(self.ffmpeg)
        self.corrections = config.project_root / "corrections.json"

    def _fingerprint(self, source: Path, style_name: str, renderer_mode: str) -> dict[str, Any]:
        return {
            "pipeline_version": PIPELINE_VERSION,
            "release_candidate": RELEASE_CANDIDATE,
            "release_config": _corrections_signature(self.config.project_root / "talking_head_v1_rc.json"),
            "source": source_fingerprint(source),
            "corrections": _corrections_signature(self.corrections),
            "style_profiles": _corrections_signature(self.config.project_root / "style_profiles.json"),
            "camera_profiles": _corrections_signature(self.config.project_root / "camera_profiles.json"),
            "font_profiles": _corrections_signature(self.config.project_root / "font_profiles.json"),
            "motion_profiles": _corrections_signature(self.config.project_root / "motion_profiles.json"),
            "visual_profiles": _corrections_signature(self.config.project_root / "visual_profiles.json"),
            "background_music": _corrections_signature(self.config.project_root / "background_music.json"),
            "style": style_name.upper(),
            "renderer_mode": renderer_mode,
            "speech_edit": _json_value(asdict(self.config.speech_edit)),
            "face_tracking": _json_value(asdict(self.config.face_tracking)),
            "editorial_quality": _json_value(asdict(self.config.editorial_quality)),
            "text_composition": _json_value(asdict(self.config.text_composition)),
            "audio_mastering": _json_value(asdict(self.config.audio_mastering)),
            "broll_library": library_signature(self.config.assets_dir / "broll"),
            "sfx_library": _directory_signature(self.config.assets_dir / "sfx"),
            "music_library": _directory_signature(self.config.assets_dir / "music"),
            "asset_library": _directory_signature(self.config.assets_dir),
        }

    def _text_metrics(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        subtitles = self.config.subtitles
        style_config = _read_json(self.config.project_root / "remotion" / "src" / "styles" / "config.json")
        if profile:
            style_config = merge_render_style(style_config, profile)
        families = style_config.get("font", {}).get("families", {})
        body_families = tuple(families.get("body", subtitles.font_families))
        display_families = tuple(families.get("display", subtitles.hero_font_families))
        hero_families = tuple(families.get("hero", display_families))
        body_font_file = resolve_font_file(body_families)
        display_font_file = resolve_font_file(display_families)
        hero_font_file = resolve_font_file(hero_families)
        resolved_families = {
            "body": resolve_font_family(body_families, subtitles.font_name),
            "display": resolve_font_family(display_families, subtitles.font_name),
            "hero": resolve_font_family(hero_families, subtitles.font_name),
        }
        local_assets = style_config.get("font", {}).get("assets", {})
        if local_assets:
            fonts_root = self.config.assets_dir / "fonts"
            manifest = build_font_manifest(fonts_root, fonts_root / "font_manifest.json")
            resolved_files = {"body": body_font_file, "display": display_font_file, "hero": hero_font_file}
            for role in ("body", "display", "hero"):
                asset = local_assets.get(role, {})
                local_file, record = resolve_manifest_font(fonts_root, manifest, str(asset.get("relativePath", "")))
                if local_file and record:
                    resolved_files[role] = local_file
                    resolved_families[role] = str(asset.get("alias") or record.get("family"))
            body_font_file, display_font_file, hero_font_file = (
                resolved_files["body"], resolved_files["display"], resolved_files["hero"]
            )
        sizes = style_config.get("fontSize", {})
        profiles = style_config.get("typographyProfiles", {})
        return {
            "font_size": float(sizes.get("normal", subtitles.font_size)),
            "accent_font_size": float(sizes.get("accent", round(subtitles.font_size * subtitles.accent_scale))),
            "hero_font_size": float(sizes.get("hero", subtitles.hero_font_size)),
            "punch_font_size": float(sizes.get("punch", round(subtitles.hero_font_size * 1.18))),
            "outline": style_config.get("outline", subtitles.outline), "shadow": subtitles.shadow,
            "body_font_family": resolved_families["body"],
            "display_font_family": resolved_families["display"],
            "hero_font_family": resolved_families["hero"],
            "body_font_file": str(body_font_file) if body_font_file else None,
            "display_font_file": str(display_font_file) if display_font_file else None,
            "hero_font_file": str(hero_font_file) if hero_font_file else None,
            "font_weight": style_config.get("font", {}).get("weight", 800),
            "font_role_map": style_config.get("font", {}).get("roleMap", {}),
            "typography_profiles": profiles,
            "visual_polish": style_config.get("visualPolish", {}),
            **asdict(self.config.text_composition),
        }

    def _output_path(self, source: Path) -> Path:
        stem = _safe_name(source.stem)
        candidate = self.config.output_dir / f"{stem}_final.mp4"
        counter = 2
        while candidate.exists():
            candidate = self.config.output_dir / f"{stem}_final_{counter}.mp4"
            counter += 1
        return candidate

    def _reusable_transcript(self, source_fingerprint_value: dict[str, Any]) -> Transcript | None:
        jobs_root = self.config.work_dir / "jobs"
        if not jobs_root.is_dir():
            return None
        for artifacts in sorted(jobs_root.glob("*/artifacts"), key=lambda path: path.stat().st_mtime_ns, reverse=True):
            source_meta, raw_path = artifacts / "source.json", artifacts / "transcript.raw.json"
            if not (source_meta.is_file() and raw_path.is_file()):
                continue
            try:
                prior = _read_json(source_meta)
                prior_source = prior.get("source_fingerprint") or prior.get("fingerprint", {}).get("source")
                if prior_source == source_fingerprint_value:
                    return Transcript.from_dict(_read_json(raw_path))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    def _reusable_artifact(self, fingerprint: dict[str, Any], filename: str) -> dict[str, Any] | None:
        jobs_root = self.config.work_dir / "jobs"
        if not jobs_root.is_dir():
            return None
        for artifacts in sorted(jobs_root.glob("*/artifacts"), key=lambda path: path.stat().st_mtime_ns, reverse=True):
            source_meta, artifact = artifacts / "source.json", artifacts / filename
            if not (source_meta.is_file() and artifact.is_file()):
                continue
            try:
                prior = _read_json(source_meta)
                if prior.get("pipeline_fingerprint") == fingerprint:
                    return _read_json(artifact)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    def _reusable_episode_proxy(self, source: Path, selected_ranges: list[dict[str, Any]]) -> Path | None:
        jobs_root = self.config.work_dir / "jobs"
        if not jobs_root.is_dir():
            return None
        expected_ranges = _json_value(selected_ranges)
        for source_map in sorted(jobs_root.glob("*/artifacts/source_map.json"), key=lambda path: path.stat().st_mtime_ns, reverse=True):
            try:
                mapping = _read_json(source_map)
                if Path(mapping.get("source_file", "")).resolve() != source.resolve():
                    continue
                mapped_ranges = [
                    {"source_start": item["source_start"], "source_end": item["source_end"]}
                    for item in mapping.get("ranges", [])
                ]
                if _json_value(mapped_ranges) != expected_ranges:
                    continue
                manifest = _read_json(source_map.parent.parent / "job_manifest.json")
                proxy = Path(manifest.get("source", {}).get("path", ""))
                if proxy.is_file():
                    return proxy.resolve()
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return None

    def _cached_result(
        self,
        source: Path,
        media: MediaInfo,
        workspace: Path,
        fingerprint: dict[str, Any],
    ) -> AutomatedResult | None:
        job_path = workspace / "job.json"
        plan_path = workspace / "montage_plan.json"
        if not (job_path.exists() and plan_path.exists()):
            return None
        job = _read_json(job_path)
        if job.get("fingerprint") != fingerprint or job.get("status") != "success":
            return None
        output_value = job.get("output")
        if not output_value:
            return None
        output = Path(output_value)
        plan = _read_json(plan_path)
        try:
            expected_duration = float(plan.get("output", {}).get("duration", media.duration))
            validate_output(
                output, media, self.ffprobe, self.ffmpeg,
                expected_duration=expected_duration,
                width=self.config.remotion.width, height=self.config.remotion.height, fps=self.config.remotion.fps,
            )
        except (OSError, ValueError):
            return None
        retimed = json.loads((workspace / "retimed.json").read_text(encoding="utf-8"))
        return AutomatedResult(
            str(source), workspace.name, "skipped", True, str(output), expected_duration,
            len(retimed), plan_summary(plan), float(job.get("render_time", 0.0)), None,
        )

    def _process_raw_session(
        self, source: Path, media: MediaInfo, raw_transcript: Transcript,
        analysis: dict[str, Any], job_context: JobContext, *, preview: bool,
        force: bool, style_name: str | None, renderer_mode: str | None,
        debug: bool, batch: bool,
        episode_ids: set[str] | None,
    ) -> AutomatedResult:
        job_context.transition(
            "EPISODE_EXTRACTION", episodes=len(analysis.get("episodes", [])),
            requested_episodes=sorted(episode_ids or []),
        )
        preview_path = job_context.paths.previews / "raw_session_timeline.html"
        write_session_preview(analysis, preview_path)
        children: list[dict[str, Any]] = []
        editorial_plans: list[dict[str, Any]] = []
        for episode in analysis.get("episodes", []):
            episode_id = str(episode["episode_id"])
            if episode_ids and episode_id not in episode_ids:
                continue
            editorial_plan = build_editorial_quality_plan(
                source, raw_transcript, episode, media.duration, self.config.editorial_quality,
                rotation=media.rotation,
            )
            editorial_plans.append(editorial_plan)
            ranges = editorial_plan["editorial_boundary"]["ranges"]
            proxy = self._reusable_episode_proxy(source, ranges)
            if proxy is None:
                proxy = job_context.paths.temp / "episodes" / f"{_safe_name(source.stem)}__{episode_id}.mp4"
            try:
                episode_transcript, source_mapping, word_mapping = build_episode_transcript(raw_transcript, ranges)
                if not proxy.is_file():
                    extract_episode_source(source, ranges, proxy, self.ffmpeg, has_audio=media.has_audio)
                context = {
                    "parent_job_id": job_context.job_id,
                    "source_file": str(source),
                    "episode": episode,
                    "source_mapping": source_mapping,
                    "word_mapping": word_mapping,
                    "editorial_quality": editorial_plan,
                }
                result = self.process_one(
                    proxy, preview=preview, force=force, style_name=style_name,
                    renderer_mode=renderer_mode, debug=debug, batch=batch,
                    _raw_transcript=episode_transcript, _raw_session_context=context,
                    _skip_raw_session=True,
                )
                children.append({
                    "episode_id": episode_id, "job_id": result.job_id,
                    "status": result.status, "success": result.success,
                    "output": result.output, "workspace": result.workspace,
                    "source_start": episode.get("source_start"),
                    "source_end": episode.get("source_end"),
                    "selected_duration": episode.get("episode_duration"),
                    "editorial_duration": round(sum(float(item["source_end"]) - float(item["source_start"]) for item in ranges), 3),
                    "editorial_trimmed": editorial_plan.get("trimmed_seconds"),
                    "editorial_reasons": editorial_plan.get("decisions", []),
                    "editorial_warnings": editorial_plan.get("warnings", []),
                    "internal_trims": editorial_plan.get("performance_quality", {}).get("internal_trims", 0),
                    "take_replacements": editorial_plan.get("performance_quality", {}).get("take_replacements", 0),
                    "internal_review_required": editorial_plan.get("performance_quality", {}).get("review_required", 0),
                    "sustained_off_camera": editorial_plan.get("performance_quality", {}).get("sustained_off_camera", 0),
                    "sustained_downward_gaze": editorial_plan.get("performance_quality", {}).get("sustained_downward_gaze", 0),
                    "start_readiness_before": editorial_plan.get("start", {}).get("before", {}).get("start_readiness"),
                    "start_readiness_after": editorial_plan.get("start", {}).get("after", {}).get("start_readiness"),
                    "final_duration": result.duration, "profile": result.summary.get("style_profile"),
                    "quality_score": result.summary.get("quality_score"),
                    "review_required": (
                        not result.success or float(result.summary.get("quality_score") or 0) < 0.58
                        or int(editorial_plan.get("performance_quality", {}).get("review_required", 0)) > 0
                    ),
                    "error": result.error,
                })
            except Exception as error:
                children.append({
                    "episode_id": episode_id, "job_id": None, "status": "failed",
                    "success": False, "output": None, "workspace": None,
                    "source_start": episode.get("source_start"), "source_end": episode.get("source_end"),
                    "selected_duration": episode.get("episode_duration"), "final_duration": 0.0,
                    "profile": None, "quality_score": None, "review_required": True,
                    "error": f"{type(error).__name__}: {error}",
                })
        _write_json(job_context.paths.artifacts / "editorial_quality_plans.json", {"version": 1, "plans": editorial_plans})
        succeeded = sum(bool(child["success"]) for child in children)
        status = "COMPLETED" if succeeded == len(children) and children else "PARTIAL_SUCCESS" if succeeded else "FAILED"
        parent_summary = {
            "version": 1, "parent_job_id": job_context.job_id,
            "classification": analysis.get("classification"),
            "classification_confidence": analysis.get("confidence"),
            "source_file": str(source), "source_duration": media.duration,
            "episodes_detected": len(analysis.get("episodes", [])),
            "episodes_processed": len(children),
            "requested_episodes": sorted(episode_ids or []),
            "selected_before_speech_edit": round(sum(float(child.get("selected_duration") or 0) for child in children), 3),
            "selected_after_editorial_gate": round(sum(float(child.get("editorial_duration") or 0) for child in children), 3),
            "editorial_trimmed_total": round(sum(float(child.get("editorial_trimmed") or 0) for child in children), 3),
            "internal_trims_total": sum(int(child.get("internal_trims") or 0) for child in children),
            "take_replacements_total": sum(int(child.get("take_replacements") or 0) for child in children),
            "internal_review_required_total": sum(int(child.get("internal_review_required") or 0) for child in children),
            "final_total_duration": round(sum(float(child.get("final_duration") or 0) for child in children), 3),
            "excluded_source_duration": round(media.duration - sum(float(child.get("selected_duration") or 0) for child in children), 3),
            "children_succeeded": succeeded, "children_failed": len(children) - succeeded,
            "review_required": [child["episode_id"] for child in children if child.get("review_required")],
            "children": children,
        }
        summary_path = job_context.paths.artifacts / "raw_session_summary.json"
        _write_json(summary_path, parent_summary)
        job_context.manifest_data["child_jobs"] = children
        job_context.artifact("raw_session_preview", preview_path)
        job_context.artifact("raw_session_summary", summary_path)
        job_context.register_existing_artifacts()
        job_context.transition(status, output_duration=round(sum(float(child.get("final_duration") or 0) for child in children), 3))
        return AutomatedResult(
            input=str(source), video_id=_video_id(source, self.config.input_dir),
            status=status.lower(), success=bool(succeeded), output=None,
            duration=sum(float(child.get("final_duration") or 0) for child in children),
            retimed_blocks=0, summary=parent_summary, render_time=0.0,
            error=None if succeeded else "No episode child job completed",
            job_id=job_context.job_id, workspace=str(job_context.paths.root),
            manifest=str(job_context.paths.manifest), source_duration=media.duration,
            children=children,
        )

    def process_one(
        self, source: Path, *, preview: bool = False, force: bool = False,
        style_name: str | None = None, renderer_mode: str | None = None,
        debug: bool = False, batch: bool = False,
        _raw_transcript: Transcript | None = None,
        _raw_session_context: dict[str, Any] | None = None,
        _skip_raw_session: bool = False,
        episode_ids: set[str] | None = None,
    ) -> AutomatedResult:
        source = source.resolve()
        video_id = _video_id(source, self.config.input_dir)
        requested_style = (style_name or self.config.style_profile).upper()
        mode = "batch" if batch else "preview" if preview else "production"
        job_context = JobContext.create(
            self.config.work_dir, source, mode=mode,
            requested_profile=requested_style, debug=debug,
            parent_job_id=(_raw_session_context or {}).get("parent_job_id"),
            job_type="EPISODE" if _raw_session_context else "VIDEO",
            source_file=Path((_raw_session_context or {}).get("source_file", source)),
        )
        workspace = job_context.paths.artifacts
        media = MediaInfo(str(source), 0, 0, 0, 0, False, "unknown", None)
        render_time = 0.0
        try:
            media = probe_media(source, self.ffprobe)
            validate_source(media)
            job_context.transition(
                "ANALYZING", source_duration=round(media.duration, 3),
                release_candidate=RELEASE_CANDIDATE, pipeline_version=PIPELINE_VERSION,
            )
            requested_renderer = normalize_renderer_mode(renderer_mode or self.config.remotion.renderer_mode)
            fingerprint = self._fingerprint(source, requested_style, requested_renderer)

            source_meta = workspace / "source.json"
            previous_meta = _read_json(source_meta) if source_meta.exists() else {}
            previous_source = previous_meta.get("source_fingerprint") or previous_meta.get("fingerprint", {}).get("source")
            raw_path = workspace / "transcript.raw.json"
            transcript_path = workspace / "transcript.json"
            if _raw_transcript is not None:
                raw_transcript = _raw_transcript
                _write_json(raw_path, raw_transcript.to_dict())
            elif previous_source == fingerprint["source"] and raw_path.exists():
                raw_transcript = Transcript.from_dict(_read_json(raw_path))
            else:
                raw_transcript = self._reusable_transcript(fingerprint["source"])
                if raw_transcript is None:
                    raw_transcript = self.transcriber.transcribe(source)
                _write_json(raw_path, raw_transcript.to_dict())
            corrected_transcript = correct_transcript(raw_transcript, self.corrections)
            normalization = normalize_transcript(corrected_transcript)
            transcript = normalization.transcript
            _write_json(workspace / "transcript.corrected.json", corrected_transcript.to_dict())
            _write_json(workspace / "transcript.normalization.json", normalization.report)
            _write_json(workspace / "transcript.normalized.json", transcript.to_dict())
            _write_json(transcript_path, transcript.to_dict())
            _write_json(source_meta, {
                "source_fingerprint": fingerprint["source"],
                "pipeline_fingerprint": fingerprint,
                "media": media.to_dict(),
                "raw_session": _raw_session_context,
            })

            corrected_chunks = _chunks_from_transcripts(raw_transcript, corrected_transcript)
            original_chunks = chunks_from_normalized(corrected_chunks, transcript)
            _write_json(workspace / "chunks.original.json", original_chunks)
            if _raw_session_context:
                _write_json(workspace / "editorial_quality_plan.json", _raw_session_context["editorial_quality"])
                _write_json(workspace / "source_map.json", {
                    "version": 1,
                    "parent_job_id": _raw_session_context["parent_job_id"],
                    "source_file": _raw_session_context["source_file"],
                    "episode": _raw_session_context["episode"],
                    "semantic_ranges": _raw_session_context["editorial_quality"]["semantic_boundary"]["ranges"],
                    "editorial_ranges": _raw_session_context["editorial_quality"]["editorial_boundary"]["ranges"],
                    "ranges": _raw_session_context["source_mapping"],
                    "words": _raw_session_context["word_mapping"],
                })
            raw_analysis = analyze_raw_session(transcript, media.duration)
            _write_json(workspace / "raw_session_analysis.json", raw_analysis)
            if not _skip_raw_session and raw_analysis["classification"] == "RAW_MULTI_TAKE_SESSION":
                return self._process_raw_session(
                    source, media, raw_transcript, raw_analysis, job_context,
                    preview=preview, force=force, style_name=style_name,
                    renderer_mode=renderer_mode, debug=debug, batch=batch,
                    episode_ids=episode_ids,
                )
            editorial_quality = (
                _raw_session_context.get("editorial_quality") if _raw_session_context
                else build_editorial_quality_plan(
                    source, transcript, raw_analysis["episodes"][0], media.duration,
                    self.config.editorial_quality, rotation=media.rotation, conservative=True,
                )
            )
            _write_json(workspace / "editorial_quality_plan.json", editorial_quality)
            preliminary_retimed = retime_words(original_chunks)
            preliminary_analysis = analyze_transcript(transcript, preliminary_retimed)
            face_plan = self._reusable_artifact(fingerprint, "face_plan.json")
            if face_plan is None:
                face_plan = analyze_faces(source, media.duration, self.config.face_tracking, rotation=media.rotation)
            _write_json(workspace / "face_plan.json", face_plan)
            style_decision = select_director_profile(
                preliminary_analysis, original_chunks, media.duration, requested_style, face_plan,
                editorial_quality,
            )
            _write_json(workspace / "content_analysis.json", style_decision["contentAnalysis"])
            _write_json(workspace / "style_intelligence.json", style_decision)
            profile = get_style_profile(
                self.config.project_root / "style_profiles.json", style_decision["profile"],
            )
            style_decision["profile"] = profile["name"]
            font_selection = select_font_profile(
                self.config.project_root / "font_profiles.json",
                self.config.assets_dir / "fonts",
                profile["name"], style_decision, fingerprint["source"],
            )
            profile["font_profile"] = font_selection["font_profile_id"]
            profile["fontProfile"] = font_selection["profile"]
            profile["fontSelection"] = {
                key: value for key, value in font_selection.items() if key != "profile"
            }
            style_decision["fontSelection"] = profile["fontSelection"]
            _write_json(workspace / "font_style_selection.json", font_selection)
            _write_json(workspace / "director_style.json", style_decision)
            job_context.transition(
                "SPEECH_EDIT", profile=profile["name"], style_profile=profile["name"],
                style_confidence=style_decision.get("confidence"),
                font_profile=font_selection["font_profile_id"],
                font_variant=font_selection["variant_id"],
                font_selection_seed=font_selection["seed"],
                font_selection_reason=font_selection["selection_reason"],
                body_font_file=font_selection["body_font_file"],
                display_font_file=font_selection["display_font_file"],
                hero_font_file=font_selection["hero_font_file"],
                font_fallbacks=0,
            )
            speech_plan = build_speech_edit_plan(
                # Visual AI Director must not decide what the timeline keeps or
                # speeds up. Speech Edit operates only on transcript/pause
                # evidence; the final visual Director runs after this boundary.
                original_chunks, media.duration, self.config.speech_edit, None,
            )
            speech_plan_data = speech_plan.to_dict()
            _retime_editorial_actions(editorial_quality, speech_plan_data)
            _write_json(workspace / "editorial_quality_plan.json", editorial_quality)
            _write_json(workspace / "speech_edit_plan.json", speech_plan_data)
            timeline_plan = build_timeline_plan(
                speech_plan_data, editorial_quality.get("content_map", {}),
            )
            _write_json(workspace / "content_map.json", editorial_quality.get("content_map", {}))
            _write_json(workspace / "timeline_plan.json", timeline_plan)
            if _raw_session_context:
                source_map_path = workspace / "source_map.json"
                source_map_data = _read_json(source_map_path)
                source_map_data["chain"] = {
                    "raw_source_to_semantic_episode": _raw_session_context["editorial_quality"]["semantic_boundary"],
                    "semantic_episode_to_editorial_episode": _raw_session_context["editorial_quality"]["editorial_boundary"],
                    "editorial_episode_to_proxy_timeline": _raw_session_context["source_mapping"],
                    "proxy_timeline_to_speech_edited_timeline": speech_plan_data.get("timeline", []),
                    "speech_edited_timeline_to_final_timeline": {"start": 0.0, "end": speech_plan.output_duration, "mapping": "identity_until_renderer"},
                }
                _write_json(source_map_path, source_map_data)
            chunks = apply_speech_edit(original_chunks, speech_plan)
            _write_json(workspace / "chunks.json", chunks)
            edited_transcript = transcript_from_edited_words(transcript, chunks, speech_plan.output_duration)
            _write_json(workspace / "transcript.edited.json", edited_transcript.to_dict())
            retimed = retime_words(chunks)
            _write_json(workspace / "retimed.json", retimed)
            editing_plan = analyze_transcript(edited_transcript, retimed)
            job_context.transition("DIRECTING", output_duration=round(speech_plan.output_duration, 3))
            director_plan = build_director_plan(
                editing_plan, profile, style_decision, speech_edit=speech_plan.to_dict(),
            )
            _write_json(workspace / "director_plan.json", director_plan)
            asset_catalog = build_asset_catalog(self.config.assets_dir)
            _write_json(workspace / "asset_catalog.json", asset_catalog)
            job_context.transition("EXECUTING")
            execution_plan = build_director_execution_plan(
                director_plan, profile, speech_plan.to_dict(), face_plan,
                self.config.assets_dir, self.ffprobe,
                _read_json(self.config.project_root / "camera_profiles.json"),
            )
            execution_plan.setdefault("asset_summary", {}).update({
                "catalog_total": asset_catalog["summary"]["total"],
                "catalog_types": asset_catalog["summary"]["types"],
            })
            _write_json(workspace / "director_execution_plan.json", execution_plan)
            audio_plan = create_audio_plan(
                self.config.audio_mastering, media.has_audio, source=source, ffmpeg=self.ffmpeg,
                music_config=self.config.project_root / "background_music.json",
            )
            _write_json(workspace / "audio_mastering.json", audio_plan)
            baseline_plan = None
            if preview:
                baseline_plan = build_montage_plan(
                    source, media, editing_plan,
                    speech_edit=speech_plan.to_dict(), style_profile=profile, face_plan=face_plan,
                    audio_plan=audio_plan, director_plan=director_plan,
                    editorial_quality=editorial_quality,
                    timeline_plan=timeline_plan,
                    text_metrics=self._text_metrics(profile),
                    output_width=self.config.remotion.width,
                    output_height=self.config.remotion.height,
                    output_fps=self.config.remotion.fps,
                    camera_drift=self.config.remotion.camera_drift,
                )
                baseline_broll = build_broll_plan(
                    baseline_plan["scenes"], self.config.assets_dir, profile, self.ffprobe,
                    director_events=director_plan.get("broll_events", []),
                )
                baseline_plan["broll"] = baseline_broll["events"]
                baseline_plan["brollRequests"] = baseline_broll["requests"]
                _write_json(workspace / "montage_plan.before_execution.json", baseline_plan)
                _write_json(workspace / "preview_events.before_execution.json", create_preview_events(baseline_plan))
            montage_plan = build_montage_plan(
                source, media, editing_plan,
                speech_edit=speech_plan.to_dict(), style_profile=profile, face_plan=face_plan,
                audio_plan=audio_plan, director_plan=director_plan,
                director_execution_plan=execution_plan,
                editorial_quality=editorial_quality,
                timeline_plan=timeline_plan,
                text_metrics=self._text_metrics(profile),
                output_width=self.config.remotion.width,
                output_height=self.config.remotion.height,
                output_fps=self.config.remotion.fps,
                camera_drift=self.config.remotion.camera_drift,
            )
            montage_plan["rendererMode"] = requested_renderer
            _write_json(workspace / "caption_plan.json", montage_plan.get("captionPlan", {}))
            if requested_renderer == "hybrid":
                visual_adapter = build_clip_visual_plan(
                    execution_plan, profile, face_plan, montage_plan.get("scenes", []),
                )
            else:
                visual_adapter = {
                    "version": 1, "mode": "legacy", "source": "feature_flag",
                    "principle": "existing ShortsAI Remotion components", "summary": {},
                }
            montage_plan["visualAdapter"] = visual_adapter
            _write_json(workspace / "clip_visual_plan.json", visual_adapter)
            _write_json(workspace / "broll_plan.json", {
                "version": 3, "source": "director_execution_plan",
                "requests": execution_plan.get("broll_requests", []),
                "events": execution_plan.get("broll_actions", []),
                "policy": execution_plan.get("broll_policy", {}),
                "assetSummary": execution_plan.get("asset_summary", {}),
            })
            validate_montage_plan(montage_plan, speech_plan.output_duration)
            _write_json(workspace / "montage_plan.json", montage_plan)
            preview_events = create_preview_events(montage_plan)
            _write_json(workspace / "preview_events.json", preview_events)
            summary = plan_summary(montage_plan)
            summary["style_profile"] = profile["name"]
            summary["style_confidence"] = style_decision.get("confidence")
            summary["font_profile"] = font_selection["font_profile_id"]
            summary["font_variant"] = font_selection["variant_id"]
            summary["font_selection_reason"] = font_selection["selection_reason"]
            summary["font_fallbacks"] = 0
            summary["renderer_mode"] = requested_renderer
            summary["visual_adapter"] = visual_adapter.get("summary", {})
            quality_report = build_quality_report(
                montage_plan, audio_plan.get("sourceAnalysis"), finalized=False,
            )
            _write_json(workspace / "quality_report.json", quality_report)
            _write_json(workspace / f"quality_report.{profile['name']}.json", quality_report)
            summary["quality_score"] = quality_report["final_score"]
            if preview and baseline_plan is not None:
                _write_json(workspace / "preview_comparison.json", {
                    "before": {"label": "Director decisions without Execution v2", "summary": plan_summary(baseline_plan)},
                    "after": {"label": "AI Director Execution v2", "summary": summary},
                    "execution": execution_plan.get("summary", {}),
                })

            if preview:
                if debug:
                    debug_data = build_director_debug(workspace, job_id=job_context.job_id)
                    write_debug_inspector(
                        debug_data, workspace / "director_debug.json",
                        job_context.paths.previews / "director_inspector.html",
                    )
                job_context.register_existing_artifacts()
                job_context.transition("COMPLETED", output_duration=round(speech_plan.output_duration, 3))
                return AutomatedResult(
                    input=str(source), video_id=video_id, status="preview", success=True,
                    output=None, duration=speech_plan.output_duration, retimed_blocks=len(retimed),
                    summary=summary, render_time=0.0, error=None, job_id=job_context.job_id,
                    workspace=str(job_context.paths.root), manifest=str(job_context.paths.manifest),
                    source_duration=media.duration,
                )

            job_context.transition("RENDERING")
            job_output = job_context.paths.output / f"{_safe_name(source.stem)}_final.mp4"
            render_time = self.renderer.render(
                source, media, chunks, montage_plan, job_context.paths.root,
                job_output, job_context.job_id,
            )
            master_rendered_audio(job_output, job_output, self.ffmpeg, audio_plan)
            font_runtime_path = workspace / "font_runtime_manifest.json"
            if font_runtime_path.is_file():
                font_runtime = _read_json(font_runtime_path)
                runtime_fallbacks = int(font_runtime.get("fallback_count", 0))
                summary["font_fallbacks"] = runtime_fallbacks
                job_context.manifest_data["font_fallbacks"] = runtime_fallbacks
            job_context.transition("QUALITY_CHECK")
            final_audio = measure_loudness(job_output, self.ffmpeg)
            rendered_frame_qc = build_rendered_frame_qc(
                job_output, montage_plan, job_context.paths.previews / "rendered_frame_qc",
            )
            _write_json(workspace / "rendered_frame_qc.json", rendered_frame_qc)
            quality_report = build_quality_report(
                montage_plan, final_audio, finalized=True, rendered_frame_qc=rendered_frame_qc,
            )
            _write_json(workspace / "quality_report.json", quality_report)
            _write_json(workspace / f"quality_report.{profile['name']}.json", quality_report)
            _write_json(job_output.with_suffix(".quality.json"), quality_report)
            write_broll_inspector(
                montage_plan, quality_report, rendered_frame_qc,
                job_context.paths.previews / "broll_inspector.html",
            )
            summary["quality_score"] = quality_report["final_score"]
            validate_output(
                job_output, media, self.ffprobe, self.ffmpeg,
                expected_duration=speech_plan.output_duration,
                width=self.config.remotion.width, height=self.config.remotion.height, fps=self.config.remotion.fps,
            )
            published_output = publish_output(source, job_context.job_id, job_output, self.config.output_dir)
            job = {
                "status": "success", "fingerprint": fingerprint, "output": str(published_output),
                "render_time": round(render_time, 3), "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            _write_json(workspace / "job.json", job)
            if debug:
                debug_data = build_director_debug(
                    workspace, job_id=job_context.job_id, final_video=published_output,
                )
                write_debug_inspector(
                    debug_data, workspace / "director_debug.json",
                    job_context.paths.previews / "director_inspector.html",
                )
            job_context.register_existing_artifacts()
            job_context.artifact("job_output", job_output)
            job_context.transition(
                "COMPLETED", output_duration=round(speech_plan.output_duration, 3),
                final_mp4=str(job_output.resolve()), published_output=str(published_output),
                font_fallbacks=summary.get("font_fallbacks", 0),
            )
            return AutomatedResult(
                input=str(source), video_id=video_id, status="success", success=True,
                output=str(published_output), duration=speech_plan.output_duration,
                retimed_blocks=len(retimed), summary=summary, render_time=render_time, error=None,
                job_id=job_context.job_id, workspace=str(job_context.paths.root),
                manifest=str(job_context.paths.manifest), source_duration=media.duration,
            )
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            error_path = job_context.paths.logs / "error.txt"
            error_path.write_text(f"{message}\n\n{traceback.format_exc()}", encoding="utf-8")
            job_context.register_existing_artifacts()
            job_context.artifact("error", error_path)
            job_context.transition("FAILED", error=message)
            return AutomatedResult(
                input=str(source), video_id=video_id, status="failed", success=False,
                output=None, duration=media.duration, retimed_blocks=0, summary={},
                render_time=render_time, error=message, job_id=job_context.job_id,
                workspace=str(job_context.paths.root), manifest=str(job_context.paths.manifest),
                source_duration=media.duration or None,
            )

    def run(
        self, videos: Iterable[Path], *, preview: bool = False, force: bool = False,
        style_name: str | None = None, renderer_mode: str | None = None,
        debug: bool = False, batch: bool = False,
        episode_ids: set[str] | None = None,
    ) -> list[AutomatedResult]:
        return [
            self.process_one(
                video, preview=preview, force=force, style_name=style_name, renderer_mode=renderer_mode,
                debug=debug, batch=batch,
                episode_ids=episode_ids,
            )
            for video in videos
        ]

    def write_manifest(self, results: list[AutomatedResult], *, preview: bool) -> Path:
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "preview" if preview else "render",
            "processed": len(results),
            "success": sum(result.success for result in results),
            "failed": sum(not result.success for result in results),
            "skipped": sum(result.status == "skipped" for result in results),
            "results": [asdict(result) for result in results],
        }
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = self.config.logs_dir / f"run_manifest_{stamp}.json"
        _write_json(path, manifest)
        return path
