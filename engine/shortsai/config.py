from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_VIDEO_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
)


@dataclass(frozen=True)
class WhisperConfig:
    model: str = "medium"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str | None = "ru"
    beam_size: int = 5


@dataclass(frozen=True)
class SpeechEditConfig:
    enabled: bool = True
    min_silence_remove_ms: int = 650
    max_allowed_pause_ms: int = 420
    silence_threshold: float = 0.58
    retained_pause: float = 0.30
    thought_pause_threshold: float = 0.62
    retained_thought_pause: float = 0.42
    remove_fillers: bool = True
    filler_words: tuple[str, ...] = ("ээ", "эм", "ну", "короче", "как бы", "вот", "типа")
    filler_min_gap: float = 0.18
    preserve_speech_rate: bool = False
    speech_compression: bool = True
    compression_speed: float = 1.035
    min_compress_segment_ms: int = 900
    max_speed: float = 1.06
    calm_speed: float = 1.035
    hook_window_ms: int = 3000


@dataclass(frozen=True)
class FaceTrackingConfig:
    enabled: bool = True
    sample_interval: float = 0.5
    min_confidence: float = 0.5


@dataclass(frozen=True)
class EditorialQualityConfig:
    enabled: bool = True
    analyze_single_ready_clip: bool = True
    sample_step: float = 0.24
    sample_window: float = 1.2
    max_start_search_seconds: float = 14.0
    alternate_take_search_seconds: float = 10.0
    max_auto_lead_trim_seconds: float = 1.5
    max_visual_lead_trim_seconds: float = 3.2
    min_start_readiness: float = 0.62
    min_readiness_improvement: float = 0.12
    min_editorial_confidence: float = 0.66
    tail_padding_seconds: float = 0.14
    max_end_trim_seconds: float = 1.6
    detector_max_width: int = 720
    internal_enabled: bool = True
    internal_sample_step: float = 0.42
    sustained_bad_min_seconds: float = 1.25
    sustained_downward_min_seconds: float = 1.10
    internal_gaze_threshold: float = 0.24
    downward_gaze_threshold: float = 0.58
    min_internal_performance: float = 0.52
    min_take_similarity: float = 0.74
    min_take_performance_gain: float = 0.14
    min_replacement_confidence: float = 0.72
    min_safe_internal_cut_seconds: float = 0.70
    min_kept_shot_seconds: float = 0.85
    min_jump_cut_gap_seconds: float = 0.65
    max_internal_actions: int = 8
    semantic_duplicate_enabled: bool = True
    semantic_duplicate_threshold: float = 0.80
    semantic_duplicate_review_threshold: float = 0.68
    semantic_duplicate_min_keep_seconds: float = 0.85


@dataclass(frozen=True)
class TextCompositionConfig:
    horizontal_margin: int = 92
    left_margin: int = 104
    right_margin: int = 150
    top_margin: int = 96
    bottom_margin: int = 300
    animation_padding: int = 34
    minimum_side_width: int = 330
    minimum_font_scale: float = 0.78
    minimum_display_font_scale: float = 0.50
    face_safety_padding: int = 44
    camera_safety_padding: int = 24
    maximum_side_lines: int = 2
    maximum_normal_lines: int = 2
    maximum_hero_lines: int = 3
    minimum_body_font_px: int = 48
    minimum_display_font_px: int = 62
    body_stroke_ratio: float = 0.050
    display_stroke_ratio: float = 0.044
    minimum_stroke_px: float = 2.0
    maximum_stroke_px: float = 6.0
    maximum_body_overshoot: float = 1.04
    maximum_accent_overshoot: float = 1.18
    maximum_display_overshoot: float = 1.16
    minimum_readability_score: float = 0.70


@dataclass(frozen=True)
class AudioMasteringConfig:
    enabled: bool = True
    target_lufs: float = -14.0
    true_peak: float = -1.4
    loudness_range: float = 7.0
    noise_reduction: float = 0.15
    voice_gain: float = 1.0
    noise_reduction_strength: float = 0.15
    compression_ratio: float = 3.0
    limiter_threshold: float = -1.5
    music_volume: float = 0.18
    ducking_amount: float = 0.65
    compressor: bool = True
    music_ducking: bool = True


@dataclass(frozen=True)
class SubtitleConfig:
    max_chars_per_line: int = 42
    font_name: str = "Arial"
    font_families: tuple[str, ...] = ("Bahnschrift Condensed", "Montserrat ExtraBold", "Montserrat Black", "Bahnschrift", "Arial")
    hero_font_families: tuple[str, ...] = ("Anton", "Impact", "Arial Black", "Arial")
    font_size: int = 64
    hero_font_size: int = 112
    accent_scale: float = 1.25
    outline: float = 4.0
    shadow: float = 4.0
    line_spacing: int = 6
    margin_vertical: int = 60


@dataclass(frozen=True)
class RenderConfig:
    ffmpeg: str = "ffmpeg"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    preset: str = "medium"
    crf: int = 20
    zoom_enabled: bool = True
    output_fps: int = 30


@dataclass(frozen=True)
class RemotionConfig:
    project_dir: str = "remotion"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    codec: str = "h264"
    crf: int = 18
    sfx_min_gap: float = 0.35
    camera_drift: float = 0.004
    renderer_mode: str = "legacy"


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    input_dir: Path
    output_dir: Path
    work_dir: Path
    logs_dir: Path
    assets_dir: Path
    style_profile: str = "AUTO"
    video_extensions: tuple[str, ...] = DEFAULT_VIDEO_EXTENSIONS
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    speech_edit: SpeechEditConfig = field(default_factory=SpeechEditConfig)
    face_tracking: FaceTrackingConfig = field(default_factory=FaceTrackingConfig)
    editorial_quality: EditorialQualityConfig = field(default_factory=EditorialQualityConfig)
    text_composition: TextCompositionConfig = field(default_factory=TextCompositionConfig)
    audio_mastering: AudioMasteringConfig = field(default_factory=AudioMasteringConfig)
    subtitles: SubtitleConfig = field(default_factory=SubtitleConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    remotion: RemotionConfig = field(default_factory=RemotionConfig)


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def load_config(config_path: Path | None = None) -> AppConfig:
    project_root = Path.cwd().resolve()
    path = (config_path or project_root / "config.json").resolve()
    data: dict[str, Any] = {}

    if path.exists():
        with path.open("r", encoding="utf-8") as config_file:
            data = json.load(config_file)
        project_root = path.parent
    elif config_path is not None:
        raise FileNotFoundError(f"Configuration file not found: {path}")

    extensions = tuple(
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in data.get("video_extensions", DEFAULT_VIDEO_EXTENSIONS)
    )

    speech_data = dict(data.get("speech_edit", {}))
    if "filler_words" in speech_data:
        speech_data["filler_words"] = tuple(str(value) for value in speech_data["filler_words"])

    return AppConfig(
        project_root=project_root,
        input_dir=_resolve_path(project_root, data.get("input_dir", "input")),
        output_dir=_resolve_path(project_root, data.get("output_dir", "output")),
        work_dir=_resolve_path(project_root, data.get("work_dir", "work")),
        logs_dir=_resolve_path(project_root, data.get("logs_dir", "logs")),
        assets_dir=_resolve_path(project_root, data.get("assets_dir", "assets")),
        style_profile=str(data.get("profile", data.get("style_profile", "AUTO"))).upper(),
        video_extensions=extensions,
        whisper=WhisperConfig(**data.get("whisper", {})),
        speech_edit=SpeechEditConfig(**speech_data),
        face_tracking=FaceTrackingConfig(**data.get("face_tracking", {})),
        editorial_quality=EditorialQualityConfig(**data.get("editorial_quality", {})),
        text_composition=TextCompositionConfig(**data.get("text_composition", {})),
        audio_mastering=AudioMasteringConfig(**data.get("audio_mastering", {})),
        subtitles=SubtitleConfig(**data.get("subtitles", {})),
        render=RenderConfig(**data.get("render", {})),
        remotion=RemotionConfig(**data.get("remotion", {})),
    )
