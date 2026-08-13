from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import RenderConfig, SubtitleConfig


def _filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    return value.replace("'", r"\'").replace(":", r"\:")


def render_with_subtitles(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    render_config: RenderConfig,
    subtitle_config: SubtitleConfig,
    camera_events: tuple[tuple[float, float, float], ...] = (),
) -> Path:
    ffmpeg = shutil.which(render_config.ffmpeg)
    if ffmpeg is None:
        candidate = Path(render_config.ffmpeg)
        if not candidate.is_file():
            raise RuntimeError(
                f"FFmpeg not found: {render_config.ffmpeg}. Add it to PATH or set render.ffmpeg."
            )
        ffmpeg = str(candidate)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subtitle_filter = f"subtitles='{_filter_path(subtitle_path)}'"
    filters: list[str] = []
    if render_config.zoom_enabled:
        fps = render_config.output_fps
        zoom_expression = "1.0"
        for start, end, zoom in reversed(camera_events):
            start_frame = max(0, round(start * fps))
            end_frame = max(start_frame + 1, round(end * fps))
            ramp_in_end = min(end_frame, start_frame + max(1, round(0.18 * fps)))
            ramp_out_start = max(ramp_in_end, end_frame - max(1, round(0.24 * fps)))
            delta = zoom - 1.0
            zoom_expression = (
                f"if(between(on,{start_frame},{ramp_in_end}),"
                f"1+{delta:.6f}*(on-{start_frame})/{max(1, ramp_in_end-start_frame)},"
                f"if(between(on,{ramp_in_end},{ramp_out_start}),{zoom:.4f},"
                f"if(between(on,{ramp_out_start},{end_frame}),"
                f"1+{delta:.6f}*({end_frame}-on)/{max(1, end_frame-ramp_out_start)},"
                f"{zoom_expression})))"
            )
        filters.append(
            f"zoompan=z='{zoom_expression}':d=1:s=1080x1920:fps={fps}"
        )
    filters.append(subtitle_filter)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        ",".join(filters),
        "-c:v",
        render_config.video_codec,
        "-preset",
        render_config.preset,
        "-crf",
        str(render_config.crf),
        "-c:a",
        render_config.audio_codec,
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(f"FFmpeg failed for {video_path.name}") from error
    return output_path
