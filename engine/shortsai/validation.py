from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable

from .media import MediaInfo, probe_media


def validate_source(info: MediaInfo) -> None:
    if info.duration <= 0 or not math.isfinite(info.duration):
        raise ValueError("Source duration must be finite and greater than zero")
    if info.width <= 0 or info.height <= 0:
        raise ValueError("Source has invalid video dimensions")
    if info.fps <= 0 or not math.isfinite(info.fps):
        raise ValueError("Source has invalid FPS")


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not numeric: {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} is not finite")
    return number


def _interval(start: Any, end: Any, duration: float, label: str) -> None:
    start_value = _finite(start, f"{label}.start")
    end_value = _finite(end, f"{label}.end")
    if start_value < 0 or end_value > duration + 0.05 or start_value >= end_value:
        raise ValueError(f"Impossible interval for {label}: {start_value}..{end_value}, duration={duration}")


def validate_montage_plan(plan: dict[str, Any], duration: float) -> None:
    if plan.get("version") != 4:
        raise ValueError("montage_plan version must be 4")
    output_duration = _finite(plan.get("output", {}).get("duration", duration), "output.duration")
    if abs(output_duration - duration) > 0.1:
        raise ValueError("montage_plan output duration does not match edited timeline")
    caption_summary = plan.get("captionPlan", {}).get("summary", {})
    if int(caption_summary.get("invalid", 0)) > 0:
        raise ValueError("Caption Engine rejected one or more visual compositions before render")
    previous_output_end = 0.0
    for index, segment in enumerate(plan.get("speechEdit", {}).get("timeline", [])):
        source_start = _finite(segment.get("source_start"), f"timeline[{index}].source_start")
        source_end = _finite(segment.get("source_end"), f"timeline[{index}].source_end")
        output_start = _finite(segment.get("output_start"), f"timeline[{index}].output_start")
        output_end = _finite(segment.get("output_end"), f"timeline[{index}].output_end")
        speed = _finite(segment.get("speed", 1), f"timeline[{index}].speed")
        if source_start < 0 or source_end <= source_start or output_start < previous_output_end - 0.02 or output_end <= output_start:
            raise ValueError(f"Impossible speech timeline segment {index}")
        if not 0.8 <= speed <= 1.5:
            raise ValueError(f"Speech speed out of range: {speed}")
        previous_output_end = output_end
    for index, scene in enumerate(plan.get("scenes", [])):
        _interval(scene.get("start"), scene.get("end"), duration, f"scenes[{index}]")
        for word_index, word in enumerate(scene.get("words", [])):
            _interval(word.get("start"), word.get("end"), duration, f"scenes[{index}].words[{word_index}]")
            if word.get("scale") is not None:
                scale = _finite(word["scale"], f"scenes[{index}].words[{word_index}].scale")
                if not 0.5 <= scale <= 2.0:
                    raise ValueError(f"Word scale out of range: {scale}")
    for section in ("camera", "visual", "sfx"):
        for index, event in enumerate(plan.get(section, [])):
            time = _finite(event.get("time", 0), f"{section}[{index}].time")
            event_duration = _finite(event.get("duration", 0), f"{section}[{index}].duration")
            if time < 0 or time > duration + 0.05 or event_duration < 0 or time + event_duration > duration + 0.1:
                raise ValueError(f"Impossible event interval: {section}[{index}]")
            if event.get("scale") is not None:
                scale = _finite(event["scale"], f"{section}[{index}].scale")
                if not 0.9 <= scale <= 1.2:
                    raise ValueError(f"Camera scale out of range: {scale}")
    for index, event in enumerate(plan.get("broll", [])):
        _interval(event.get("from"), event.get("to"), duration, f"broll[{index}]")
        shot_total = 0.0
        for shot_index, shot in enumerate(event.get("shots", [event])):
            start_from = _finite(shot.get("startFrom", 0), f"broll[{index}].shots[{shot_index}].startFrom")
            shot_duration = _finite(shot.get("duration", event.get("to", 0) - event.get("from", 0)), f"broll[{index}].shots[{shot_index}].duration")
            if start_from < 0 or shot_duration <= 0:
                raise ValueError("B-roll shot has invalid timing")
            if shot.get("fit", "cover") not in {"cover", "contain"}:
                raise ValueError("B-roll shot has an invalid fit mode")
            shot_total += shot_duration
        event_duration = _finite(event.get("to"), f"broll[{index}].to") - _finite(event.get("from"), f"broll[{index}].from")
        if shot_total > event_duration + 0.1:
            raise ValueError("B-roll shots exceed their event duration")


def validate_output(
    output: Path,
    source: MediaInfo,
    ffprobe: Path,
    ffmpeg: Path,
    *,
    expected_duration: float | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> MediaInfo:
    if not output.is_file() or output.stat().st_size <= 0:
        raise ValueError(f"Rendered output is missing or empty: {output}")
    rendered = probe_media(output, ffprobe)
    target_duration = source.duration if expected_duration is None else expected_duration
    tolerance = max(0.75, target_duration * 0.02)
    if abs(rendered.duration - target_duration) > tolerance:
        raise ValueError(f"Output duration mismatch: {rendered.duration} vs {target_duration}")
    if (rendered.width, rendered.height) != (width, height):
        raise ValueError(f"Output resolution is {rendered.width}x{rendered.height}, expected {width}x{height}")
    if abs(rendered.fps - fps) > 0.1:
        raise ValueError(f"Output FPS is {rendered.fps}, expected {fps}")
    if source.has_audio and not rendered.has_audio:
        raise ValueError("Source has audio but rendered output does not")
    with open(os.devnull, "wb") as sink:
        result = subprocess.run(
            [str(ffmpeg), "-v", "error", "-i", str(output), "-f", "null", "-"],
            stdout=sink,
            stderr=subprocess.PIPE,
        )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Full output decode failed: {message}")
    return rendered
