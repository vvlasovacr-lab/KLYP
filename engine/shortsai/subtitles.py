from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Sequence

from .config import SubtitleConfig
from .fonts import resolve_font_family
from .semantic_analysis import AnalyzedWord, CompositionStep, EditingPlan, MotionPreset, SceneType, TextScene


PLAY_RES_X = 1080
PLAY_RES_Y = 1920
BODY_Y = 1330
HERO_Y = 1120


def _timestamp(seconds: float) -> str:
    value = max(0, round(seconds * 100))
    hours, remainder = divmod(value, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def _escape(text: str) -> str:
    return text.replace("\\", r"\e").replace("{", r"\{").replace("}", r"\}")


def _balanced_indices(words: Sequence[AnalyzedWord], max_lines: int) -> list[list[int]]:
    count = len(words)
    if count <= 3 or max_lines == 1:
        return [list(range(count))]
    lines = min(max_lines, 2 if count <= 6 else 3)
    if lines == 2:
        split = min(range(1, count), key=lambda index: abs(
            sum(len(word.text) + 1 for word in words[:index]) -
            sum(len(word.text) + 1 for word in words[index:])
        ))
        return [list(range(split)), list(range(split, count))]
    first = max(1, round(count / 3))
    second = max(first + 1, round(count * 2 / 3))
    return [list(range(0, first)), list(range(first, second)), list(range(second, count))]


def _accent_color(word: AnalyzedWord) -> str:
    # Red is restricted to explicit danger/failure/problem semantics.
    return "&H003C3CFF&" if word.category == "problem" else "&H0000D7FF&"


def _line_text(
    scene: TextScene,
    indices: Sequence[int],
    base_size: int,
    accent_size: int,
    all_large: bool = False,
) -> str:
    motion_by_word = {event.element_index: event for event in scene.motion_events if event.ass_supported}
    chunks: list[str] = []
    for index in indices:
        word = scene.words[index]
        value = _escape(word.text.upper() if all_large else word.text)
        size = accent_size if index in scene.emphasis_words else base_size
        color = _accent_color(word) if index in scene.emphasis_words else "&H00FFFFFF&"
        motion = motion_by_word.get(index)
        motion_tags = ""
        if motion is not None:
            start_ms = max(0, round((motion.motion_start - scene.start) * 1000))
            end_ms = start_ms + round(motion.motion_duration * 1000)
            peak_ms = start_ms + max(50, round(motion.motion_duration * 480))
            start_scale = round(motion.start_scale * 100)
            peak_scale = round(motion.peak_scale * 100)
            motion_tags = (
                rf"\fscx100\fscy100"
                rf"\t({start_ms},{start_ms + 18},\fscx{start_scale}\fscy{start_scale})"
                rf"\t({start_ms + 18},{peak_ms},\fscx{peak_scale}\fscy{peak_scale})"
                rf"\t({peak_ms},{end_ms},\fscx100\fscy100)"
            )
            if motion.motion_preset is MotionPreset.BOUNCE:
                motion_tags += rf"\t({peak_ms},{end_ms},\fscx97\fscy97)\t({end_ms},{end_ms + 35},\fscx100\fscy100)"
            elif motion.motion_preset is MotionPreset.MICRO_SHAKE:
                third = max(25, round(motion.motion_duration * 250))
                motion_tags += (
                    rf"\t({start_ms},{start_ms + third},\frz-1.5)"
                    rf"\t({start_ms + third},{start_ms + third * 2},\frz1.5)"
                    rf"\t({start_ms + third * 2},{end_ms},\frz0)"
                )
        if index in scene.emphasis_words:
            chunks.append(rf"{{\c{color}\fs{size}\b1{motion_tags}}}{value}")
        else:
            chunks.append(rf"{{\c&H00FFFFFF&\fs{size}\b1{motion_tags}}}{value}")
    return " ".join(chunks)


def _scene_lines(scene: TextScene, config: SubtitleConfig) -> list[tuple[list[int], int, int, bool]]:
    base = config.font_size
    accent = round(base * config.accent_scale)
    if scene.scene_type is SceneType.HERO:
        hero_size = config.hero_font_size if len(scene.words) <= 3 else round(config.hero_font_size * 0.84)
        return [(line, hero_size, hero_size, True) for line in _balanced_indices(scene.words, 3)]
    if scene.scene_type is SceneType.PUNCH:
        return [(list(range(len(scene.words))), config.hero_font_size, config.hero_font_size, True)]
    if scene.scene_type is SceneType.NUMBER:
        lead: list[int] = []
        for index, word in enumerate(scene.words):
            if index == len(lead) and word.category == "number":
                lead.append(index)
            else:
                break
        lead = lead or list(range(min(1, len(scene.words))))
        explanation = [index for index in range(len(scene.words)) if index not in lead]
        lines = [(lead, config.hero_font_size, config.hero_font_size, True)]
        if explanation:
            for line in _balanced_indices([scene.words[index] for index in explanation], 2):
                mapped = [explanation[index] for index in line]
                lines.append((mapped, round(base * 0.92), accent, False))
        return lines[:3]
    if scene.scene_type is SceneType.CONTRAST:
        connector = next(
            (index for index, word in enumerate(scene.words) if word.text.lower().strip(".,!") in {"но", "либо", "или", "наоборот", "зато"}),
            max(1, len(scene.words) // 2),
        )
        split = max(1, min(len(scene.words) - 1, connector))
        return [
            (list(range(0, split)), base, accent, False),
            (list(range(split, len(scene.words))), base, accent, False),
        ]
    return [(line, base, accent, False) for line in _balanced_indices(scene.words, 2)]


def _animation(scene: TextScene) -> str:
    if scene.scene_type is SceneType.HERO:
        return r"\fad(20,65)\fscx70\fscy70\t(0,90,\fscx112\fscy112)\t(90,170,\fscx100\fscy100)"
    if scene.scene_type is SceneType.PUNCH:
        return r"\fad(10,45)\fscx55\fscy55\t(0,55,\fscx118\fscy118)\t(55,115,\fscx100\fscy100)"
    if scene.scene_type is SceneType.NUMBER:
        return r"\fad(20,60)\fscx72\fscy72\t(0,75,\fscx108\fscy108)\t(75,145,\fscx100\fscy100)"
    if scene.scene_type is SceneType.ACCENT:
        return r"\fad(25,55)\fscx88\fscy88\t(0,70,\fscx104\fscy104)\t(70,130,\fscx100\fscy100)"
    if scene.scene_type is SceneType.CONTRAST:
        return r"\fad(25,65)\fscx92\fscy92\t(0,80,\fscx100\fscy100)"
    return r"\fad(30,60)\fscx94\fscy94\t(0,85,\fscx100\fscy100)"


def _step_scene(scene: TextScene, step: CompositionStep) -> TextScene:
    mapping = {original: new for new, original in enumerate(step.visible_word_indices)}
    emphasis = tuple(mapping[index] for index in scene.emphasis_words if index in mapping)
    motions = tuple(
        replace(event, element_index=mapping[event.element_index], active_element=mapping[event.active_element])
        for event in scene.motion_events
        if event.element_index in mapping
        and step.start <= event.motion_start < step.end
        and event.active_element in mapping
    )
    return replace(
        scene,
        start=step.start,
        end=step.end,
        words=tuple(scene.words[index] for index in step.visible_word_indices),
        emphasis_words=emphasis,
        composition_steps=(),
        motion_events=motions,
    )


def _document(plan: EditingPlan, config: SubtitleConfig) -> str:
    body_font = resolve_font_family(config.font_families, config.font_name)
    hero_font = resolve_font_family(config.hero_font_families, body_font)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {PLAY_RES_X}
PlayResY: {PLAY_RES_Y}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Body,{body_font},{config.font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,{config.outline},{config.shadow},2,70,70,{config.margin_vertical},1
Style: Display,{hero_font},{config.hero_font_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,1,{config.outline},{config.shadow},2,55,55,{config.margin_vertical},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for source_scene in plan.scenes:
      for scene in (_step_scene(source_scene, step) for step in source_scene.composition_steps or (CompositionStep(source_scene.start, source_scene.end, tuple(range(len(source_scene.words))), None),)):
        raw_lines = _scene_lines(scene, config)
        display = scene.scene_type in {SceneType.HERO, SceneType.PUNCH, SceneType.NUMBER}
        lines: list[tuple[list[int], int, int, bool]] = []
        for indices, base_size, accent_size, all_large in raw_lines:
            character_count = sum(len(scene.words[index].text) for index in indices) + max(0, len(indices) - 1)
            width_factor = 0.57 if display else 0.54
            fitted = round(900 / max(1.0, character_count * width_factor))
            minimum = 60 if display and all_large else 46
            fitted_base = min(base_size, max(minimum, fitted))
            fitted_accent = min(accent_size, round(fitted_base * config.accent_scale))
            lines.append((indices, fitted_base, fitted_accent, all_large))
        center_y = HERO_Y if display else BODY_Y
        heights = [base_size for _, base_size, _, _ in lines]
        total_height = sum(heights) + config.line_spacing * max(0, len(lines) - 1)
        y = center_y - total_height // 2
        for line_number, (indices, base_size, accent_size, all_large) in enumerate(lines):
            line_y = y + base_size // 2
            y += base_size + config.line_spacing
            style = "Display" if display else "Body"
            override = (
                rf"{{\an5\pos({PLAY_RES_X // 2},{line_y}){_animation(scene)}"
                rf"\fn{hero_font if display else body_font}\bord{config.outline}\shad{config.shadow}}}"
            )
            events.append(
                f"Dialogue: {1 if display else 0},{_timestamp(scene.start)},{_timestamp(scene.end)},"
                f"{style},,0,0,0,,{override}{_line_text(scene, indices, base_size, accent_size, all_large)}"
            )
    return header + "\n".join(events) + "\n"


def write_srt(plan: EditingPlan, destination: Path, config: SubtitleConfig | int) -> Path:
    """Render text-scene templates to ASS; legacy integer config remains accepted."""
    if isinstance(config, int):
        config = SubtitleConfig(max_chars_per_line=config)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = _document(plan, config)
    destination.write_text(document, encoding="utf-8-sig")
    if destination.suffix.lower() != ".ass":
        destination.with_suffix(".ass").write_text(document, encoding="utf-8-sig")
    return destination
