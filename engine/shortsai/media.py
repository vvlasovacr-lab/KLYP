from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any


@dataclass(frozen=True)
class MediaInfo:
    file: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    audio_codec: str | None
    rotation: int = 0
    display_width: int | None = None
    display_height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_ffmpeg(configured: str = "ffmpeg") -> Path:
    found = shutil.which(configured)
    if found:
        return Path(found).resolve()
    candidate = Path(configured)
    if candidate.is_file():
        return candidate.resolve()
    windows_candidate = Path("C:/ffmpeg/bin/ffmpeg.exe")
    if windows_candidate.is_file():
        return windows_candidate.resolve()
    raise RuntimeError(f"FFmpeg not found: {configured}")


def resolve_ffprobe(ffmpeg: Path) -> Path:
    name = "ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe"
    sibling = ffmpeg.with_name(name)
    if sibling.is_file():
        return sibling
    found = shutil.which("ffprobe")
    if found:
        return Path(found).resolve()
    raise RuntimeError("ffprobe was not found next to FFmpeg or in PATH")


def _fps(value: str | None) -> float:
    if not value:
        return 0.0
    numerator, separator, denominator = value.partition("/")
    try:
        result = float(numerator) / float(denominator) if separator else float(numerator)
    except (ValueError, ZeroDivisionError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def probe_media(path: Path, ffprobe: Path) -> MediaInfo:
    command = [
        str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if video is None:
        raise ValueError(f"No video stream: {path}")
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    rotation = int(float(video.get("tags", {}).get("rotate") or 0))
    for side_data in video.get("side_data_list", []):
        if side_data.get("rotation") is not None:
            rotation = int(float(side_data["rotation"]))
            break
    coded_width, coded_height = int(video.get("width") or 0), int(video.get("height") or 0)
    display_width, display_height = (coded_height, coded_width) if abs(rotation) % 180 == 90 else (coded_width, coded_height)
    return MediaInfo(
        file=str(path.resolve()),
        duration=round(duration, 6),
        width=coded_width,
        height=coded_height,
        fps=round(fps, 6),
        has_audio=audio is not None,
        video_codec=str(video.get("codec_name") or "unknown"),
        audio_codec=str(audio.get("codec_name")) if audio else None,
        rotation=rotation,
        display_width=display_width,
        display_height=display_height,
    )


def source_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "file": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
