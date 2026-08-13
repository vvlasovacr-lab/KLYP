from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import uuid
from typing import Any


JOB_STATES = (
    "CREATED", "ANALYZING", "EPISODE_EXTRACTION", "SPEECH_EDIT", "DIRECTING", "EXECUTING",
    "RENDERING", "QUALITY_CHECK", "COMPLETED", "PARTIAL_SUCCESS", "FAILED",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_stem(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return value[:64] or "video"


def create_job_id(source: Path) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}_{_safe_stem(source.stem)}_{uuid.uuid4().hex[:8]}"


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


@dataclass(frozen=True)
class JobPaths:
    root: Path
    input: Path
    artifacts: Path
    previews: Path
    logs: Path
    output: Path
    temp: Path
    manifest: Path

    @classmethod
    def create(cls, work_dir: Path, job_id: str) -> "JobPaths":
        root = (work_dir / "jobs" / job_id).resolve()
        jobs_root = (work_dir / "jobs").resolve()
        root.relative_to(jobs_root)
        paths = cls(
            root=root,
            input=root / "input",
            artifacts=root / "artifacts",
            previews=root / "previews",
            logs=root / "logs",
            output=root / "output",
            temp=root / "temp",
            manifest=root / "job_manifest.json",
        )
        for directory in (paths.input, paths.artifacts, paths.previews, paths.logs, paths.output, paths.temp):
            directory.mkdir(parents=True, exist_ok=False)
        return paths


class JobContext:
    """Small persistent job envelope around the existing production pipeline."""

    def __init__(self, job_id: str, paths: JobPaths, manifest: dict[str, Any]) -> None:
        self.job_id = job_id
        self.paths = paths
        self.manifest_data = manifest

    @classmethod
    def create(
        cls, work_dir: Path, source: Path, *, mode: str, requested_profile: str,
        debug: bool = False, parent_job_id: str | None = None,
        job_type: str = "VIDEO", source_file: Path | None = None,
    ) -> "JobContext":
        source = source.resolve()
        job_id = create_job_id(source)
        paths = JobPaths.create(work_dir, job_id)
        manifest = {
            "version": 1,
            "job_id": job_id,
            "source": {"name": source.name, "path": str(source), "staging": "REFERENCE"},
            "source_file": str((source_file or source).resolve()),
            "job_type": job_type,
            "parent_job_id": parent_job_id,
            "child_jobs": [],
            "mode": mode,
            "debug": debug,
            "status": "CREATED",
            "current_stage": "CREATED",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "completed_at": None,
            "source_duration": None,
            "output_duration": None,
            "profile": requested_profile,
            "artifacts": {},
            "final_mp4": None,
            "published_output": None,
            "error": None,
        }
        context = cls(job_id, paths, manifest)
        _write_json_atomic(paths.input / "source_reference.json", manifest["source"])
        context._save()
        context.log("CREATED", f"source={source}")
        return context

    def _save(self) -> None:
        self.manifest_data["updated_at"] = _utc_now()
        _write_json_atomic(self.paths.manifest, self.manifest_data)

    def log(self, stage: str, message: str) -> None:
        line = f"{_utc_now()} [{self.job_id}] [{stage}] {message}\n"
        with (self.paths.logs / "job.log").open("a", encoding="utf-8") as stream:
            stream.write(line)

    def transition(self, stage: str, **values: Any) -> None:
        if stage not in JOB_STATES:
            raise ValueError(f"Unsupported job stage: {stage}")
        self.manifest_data["status"] = stage
        self.manifest_data["current_stage"] = stage
        self.manifest_data.update(values)
        if stage in {"COMPLETED", "PARTIAL_SUCCESS", "FAILED"}:
            self.manifest_data["completed_at"] = _utc_now()
        self._save()
        self.log(stage, values.get("message", stage))

    def artifact(self, name: str, path: Path | None) -> None:
        if path is None:
            return
        self.manifest_data.setdefault("artifacts", {})[name] = str(path.resolve())
        self._save()

    def register_existing_artifacts(self) -> None:
        names = {
            "raw_session_analysis": "raw_session_analysis.json",
            "editorial_quality_plan": "editorial_quality_plan.json",
            "editorial_quality_plans": "editorial_quality_plans.json",
            "source_map": "source_map.json",
            "transcript": "transcript.json",
            "retimed_transcript": "retimed.json",
            "speech_edit_plan": "speech_edit_plan.json",
            "director_style": "director_style.json",
            "font_style_selection": "font_style_selection.json",
            "font_runtime_manifest": "font_runtime_manifest.json",
            "director_plan": "director_plan.json",
            "director_execution_plan": "director_execution_plan.json",
            "clip_visual_plan": "clip_visual_plan.json",
            "montage_plan": "montage_plan.json",
            "quality_report": "quality_report.json",
            "director_debug": "director_debug.json",
        }
        for key, filename in names.items():
            path = self.paths.artifacts / filename
            if path.exists():
                self.manifest_data.setdefault("artifacts", {})[key] = str(path.resolve())
        self._save()


def publish_output(source: Path, job_id: str, job_output: Path, public_output_dir: Path) -> Path:
    public_output_dir.mkdir(parents=True, exist_ok=True)
    suffix = job_id.rsplit("_", 1)[-1]
    destination = public_output_dir / f"{_safe_stem(source.stem)}_{suffix}_final.mp4"
    try:
        os.link(job_output, destination)
    except OSError:
        shutil.copy2(job_output, destination)
    return destination.resolve()
