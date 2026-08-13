from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .discovery import discover_videos
from .render import render_with_subtitles
from .semantic_analysis import analyze_transcript
from .subtitles import write_srt
from .text_correction import correct_transcript
from .transcription import Transcriber


@dataclass(frozen=True)
class ProcessingResult:
    source: Path
    output: Path | None
    success: bool
    error: str | None = None


def _job_name(video_path: Path, input_dir: Path) -> str:
    relative = video_path.relative_to(input_dir).with_suffix("")
    raw_name = "__".join(relative.parts)
    cleaned = re.sub(r"[^\w.-]+", "_", raw_name, flags=re.UNICODE).strip("._")
    return cleaned or "video"


class Pipeline:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.transcriber = Transcriber(config.whisper)

    def discover(self) -> list[Path]:
        return discover_videos(self.config.input_dir, self.config.video_extensions)

    def process_one(self, video_path: Path) -> ProcessingResult:
        name = _job_name(video_path, self.config.input_dir)
        subtitle_path = self.config.output_dir / f"{name}.srt"
        transcript_path = self.config.output_dir / f"{name}.transcript.json"
        analysis_path = self.config.output_dir / f"{name}.analysis.json"
        output_path = self.config.output_dir / f"{name}.mp4"
        try:
            raw_transcript = self.transcriber.transcribe(video_path)
            transcript = correct_transcript(
                raw_transcript,
                self.config.project_root / "corrections.json",
            )
            editing_plan = analyze_transcript(transcript)
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
            transcript_path.write_text(
                json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            analysis_path.write_text(
                json.dumps(editing_plan.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            write_srt(
                editing_plan,
                subtitle_path,
                self.config.subtitles,
            )
            render_with_subtitles(
                video_path,
                subtitle_path,
                output_path,
                self.config.render,
                self.config.subtitles,
                editing_plan.camera_events(),
            )
            return ProcessingResult(video_path, output_path, True)
        except Exception as error:
            return ProcessingResult(video_path, None, False, str(error))

    def run(self) -> list[ProcessingResult]:
        return [self.process_one(video) for video in self.discover()]
