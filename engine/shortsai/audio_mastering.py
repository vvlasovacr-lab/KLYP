from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
from typing import Any

from .config import AudioMasteringConfig


def measure_loudness(source: Path, ffmpeg: Path) -> dict[str, float | None]:
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "info", "-i", str(source), "-vn",
        "-af", "loudnorm=I=-14:TP=-1:LRA=7:print_format=json", "-f", "null", "-",
    ]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=True)
    matches = re.findall(r"\{\s*\"input_i\".*?\}", result.stderr, flags=re.DOTALL)
    if not matches:
        return {"integratedLufs": None, "truePeak": None, "loudnessRange": None}
    measured = json.loads(matches[-1])

    def number(key: str) -> float | None:
        try:
            value = float(measured[key])
            return value if value not in {float("inf"), float("-inf")} else None
        except (KeyError, TypeError, ValueError):
            return None

    return {
        "integratedLufs": number("input_i"),
        "truePeak": number("input_tp"),
        "loudnessRange": number("input_lra"),
    }


def _music_plan(path: Path | None, config: AudioMasteringConfig) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    track = value.get("track")
    if not track or value.get("enabled", True) is False:
        return None
    return {
        "track": str(track),
        "volume": float(value.get("volume", config.music_volume)),
        "ducking": float(value.get("ducking", config.ducking_amount)),
        "fadeIn": float(value.get("fade_in", 0.8)),
        "fadeOut": float(value.get("fade_out", 1.0)),
        "enabled": True,
    }


def create_audio_plan(
    config: AudioMasteringConfig,
    has_audio: bool,
    *,
    source: Path | None = None,
    ffmpeg: Path | None = None,
    music_config: Path | None = None,
) -> dict[str, Any]:
    source_analysis = (
        measure_loudness(source, ffmpeg)
        if has_audio and source is not None and ffmpeg is not None else
        {"integratedLufs": None, "truePeak": None, "loudnessRange": None}
    )
    source_lufs = source_analysis.get("integratedLufs")
    automatic_gain_db = 0.0 if source_lufs is None else max(-2.5, min(2.5, (config.target_lufs - float(source_lufs)) * 0.22))
    voice_gain = config.voice_gain * (10 ** (automatic_gain_db / 20))
    source_lra = source_analysis.get("loudnessRange")
    ratio = max(config.compression_ratio, 3.6) if source_lra is not None and float(source_lra) > 9 else config.compression_ratio
    return {
        "enabled": bool(config.enabled and has_audio),
        "targetLufs": config.target_lufs,
        "truePeak": config.true_peak,
        "loudnessRange": config.loudness_range,
        "voiceGain": round(voice_gain, 4),
        "voiceGainDb": round(automatic_gain_db, 3),
        "noiseReduction": config.noise_reduction_strength if config.noise_reduction_strength is not None else config.noise_reduction,
        "compressionRatio": round(float(ratio), 3),
        "limiterThreshold": config.limiter_threshold,
        "compressor": config.compressor,
        "musicDucking": config.music_ducking,
        "musicVolume": config.music_volume,
        "duckingAmount": config.ducking_amount,
        "music": _music_plan(music_config, config),
        "sourceAnalysis": source_analysis,
    }


def master_rendered_audio(source: Path, destination: Path, ffmpeg: Path, plan: dict[str, Any]) -> Path:
    if not plan.get("enabled", False):
        return source
    temporary = destination.with_name(f"{destination.stem}.mastering{destination.suffix}")
    filters: list[str] = ["highpass=f=70", "equalizer=f=3000:t=q:w=1:g=1.4"]
    if float(plan.get("noiseReduction", 0)) > 0:
        noise = 6 + float(plan["noiseReduction"]) * 14
        filters.append(f"afftdn=nr={noise:.2f}:nf=-35")
    if plan.get("compressor", True):
        ratio = max(1.0, min(8.0, float(plan.get("compressionRatio", 3.0))))
        filters.append(f"acompressor=threshold=0.125:ratio={ratio:.2f}:attack=12:release=140:makeup=1.28")
    limiter_db = float(plan.get("limiterThreshold", plan.get("truePeak", -1.0)))
    limiter_linear = 10 ** (limiter_db / 20)
    filters.append(f"alimiter=limit={limiter_linear:.5f}:attack=5:release=60")
    target_i = float(plan.get("targetLufs", -14))
    target_tp = min(float(plan.get("truePeak", -1)), float(plan.get("limiterThreshold", -1.1)))
    target_lra = float(plan.get("loudnessRange", 7))
    prefilters = ",".join(filters)
    analysis_filter = (
        f"{prefilters},loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:print_format=json"
    )
    analysis = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-loglevel", "info", "-i", str(source), "-vn", "-af", analysis_filter, "-f", "null", "-"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=True,
    )
    matches = re.findall(r"\{\s*\"input_i\".*?\}", analysis.stderr, flags=re.DOTALL)
    if not matches:
        raise RuntimeError("FFmpeg loudnorm analysis did not return measurement JSON")
    measured = json.loads(matches[-1])
    loudnorm = (
        f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=summary"
    )
    command = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy", "-af", f"{prefilters},{loudnorm}",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(temporary),
    ]
    try:
        subprocess.run(command, check=True)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
