from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
import re
from typing import Any, Sequence

from .transcription import Transcript, TranscriptWord


class SceneType(str, Enum):
    NORMAL = "normal"
    ACCENT = "accent"
    HERO = "hero"
    PUNCH = "punch"
    NUMBER = "number"
    CONTRAST = "contrast"


SUPPORTED_VISUAL_EVENTS = (
    "broll", "image", "icon", "sfx", "flash", "gleam", "camera_punch", "text_card"
)


@dataclass(frozen=True)
class AnalyzedWord:
    start: float
    end: float
    text: str
    category: str | None
    score: int


class MotionPreset(str, Enum):
    POP = "pop"
    BOUNCE = "bounce"
    PUNCH = "punch"
    SLIDE_UP = "slide_up"
    SLIDE_LEFT = "slide_left"
    SCALE_IN = "scale_in"
    MICRO_SHAKE = "micro_shake"


@dataclass(frozen=True)
class CompositionStep:
    start: float
    end: float
    visible_word_indices: tuple[int, ...]
    active_element: int | None


@dataclass(frozen=True)
class TextMotionEvent:
    text: str
    element_index: int
    element_role: str
    motion_preset: MotionPreset
    motion_start: float
    motion_duration: float
    motion_intensity: float
    active_element: int
    start_scale: float
    peak_scale: float
    end_scale: float
    position_offset: tuple[int, int]
    ass_supported: bool = True


@dataclass(frozen=True)
class TextScene:
    start: float
    end: float
    scene_type: SceneType
    text_template: str
    words: tuple[AnalyzedWord, ...]
    emphasis_words: tuple[int, ...]
    importance_score: float
    emotion_score: float
    recommended_zoom: float
    context_before: str = ""
    context_after: str = ""
    motion_intensity: float = 0.0
    speech_energy: float = 0.0
    word_roles: tuple[str, ...] = ()
    composition_steps: tuple[CompositionStep, ...] = ()
    motion_events: tuple[TextMotionEvent, ...] = ()


@dataclass(frozen=True)
class VisualEvent:
    event_type: str
    start: float
    end: float
    intensity: float
    enabled: bool
    payload: dict[str, Any]


@dataclass(frozen=True)
class EditingPlan:
    scenes: tuple[TextScene, ...]
    visual_events: tuple[VisualEvent, ...]

    def camera_events(self) -> tuple[tuple[float, float, float], ...]:
        return tuple(
            (event.start, event.end, float(event.payload["zoom"]))
            for event in self.visual_events
            if event.event_type == "camera_punch" and event.enabled
        )

    # Compatibility for older callers; the renderer now consumes camera_events().
    def hook_intervals(self) -> tuple[tuple[float, float], ...]:
        return tuple(
            (scene.start, scene.end)
            for scene in self.scenes
            if scene.scene_type in {SceneType.HERO, SceneType.PUNCH}
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 3,
            "supported_visual_event_types": list(SUPPORTED_VISUAL_EVENTS),
            "scenes": [asdict(scene) for scene in self.scenes],
            "visual_events": [asdict(event) for event in self.visual_events],
        }


STOP_WORDS = frozenset(
    "а без бы в вам вас ведь во вот все вы где да даже для до его ее если есть "
    "же за и из или к как когда ли мы на над не ну о об от по под при про с так "
    "там то ты у уже что чтобы это я".split()
)

STEMS: dict[str, tuple[str, ...]] = {
    "conflict": ("но", "никогда", "всегда", "однако", "зато", "вместо", "против", "наоборот", "либо"),
    "problem": ("проблем", "потер", "ошиб", "бедн", "долг", "провал", "риск", "неудач", "опас", "дешев"),
    "emotion": ("страх", "шок", "ужас", "боль", "счаст", "люб", "ненав", "стыд", "мечт"),
    "money": ("деньг", "богат", "миллион", "миллиард", "доход", "заработ", "прибыл", "рубл", "доллар", "цен"),
    "result": ("результ", "получ", "рост", "успех", "свобод", "выигр", "эконом", "лучш", "решен", "измен"),
    "principle": ("дисциплин", "качест", "гарантир", "важн", "мышлен"),
}

NUMBER_WORDS = frozenset(
    "ноль один одна два две три четыре пять шесть семь восемь девять десять "
    "сто тысяча тысячи тысяч миллион миллиона миллионов миллиард процента процентов".split()
)
HOOK_STEMS = ("миллионер", "банкрот", "секрет", "главн", "катастроф")
CONTRAST_TOKENS = frozenset(("но", "либо", "или", "наоборот", "зато", "вместо"))


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё-]", "", text).lower()


def _classify(words: Sequence[TranscriptWord]) -> tuple[AnalyzedWord, ...]:
    tokens = [_normalize(word.text) for word in words]
    result: list[AnalyzedWord] = []
    weights = {"money": 6, "problem": 5, "conflict": 4, "emotion": 5, "result": 5, "principle": 5}
    for index, (word, token) in enumerate(zip(words, tokens)):
        category: str | None = None
        score = 0
        for candidate, stems in STEMS.items():
            if token and any(token.startswith(stem) for stem in stems):
                category, score = candidate, weights[candidate]
                break
        if token in NUMBER_WORDS or any(character.isdigit() for character in token):
            category, score = "number", 7
        neighbors = tokens[max(0, index - 2):index] + tokens[index + 1:index + 3]
        if category == "money" and any(
            any(stem in neighbor for stem in STEMS["problem"] + STEMS["conflict"])
            for neighbor in neighbors
        ):
            score += 1
        if token in STOP_WORDS and category is None:
            score = 0
        result.append(AnalyzedWord(word.start, word.end, word.text, category, score))
    return tuple(result)


def _phrases(transcript: Transcript) -> list[tuple[TranscriptWord, ...]]:
    phrases: list[tuple[TranscriptWord, ...]] = []
    current: list[TranscriptWord] = []
    for segment in transcript.segments:
        for word in segment.words:
            if current and word.start - current[-1].end >= 0.38:
                phrases.append(tuple(current)); current = []
            current.append(word)
            if word.text.rstrip().endswith((".", "!", "?", ":", ";")) or len(current) >= 12:
                phrases.append(tuple(current)); current = []
    if current:
        phrases.append(tuple(current))
    return phrases


def _scores(words: Sequence[AnalyzedWord], previous: Sequence[AnalyzedWord], following: Sequence[AnalyzedWord]) -> tuple[float, float]:
    strong = [word for word in words if word.score >= 4]
    density = len(strong) / max(1, len(words))
    peak = max((word.score for word in words), default=0) / 7
    question = any(word.text.rstrip().endswith(("?", "!")) for word in words)
    context_categories = {word.category for word in previous[-4:]} | {word.category for word in following[:4]}
    continuity = 0.08 if any(word.category in context_categories and word.category for word in strong) else 0
    importance = min(1.0, 0.18 + peak * 0.52 + density * 0.22 + continuity + (0.12 if question else 0))
    emotional = sum(word.category in {"emotion", "problem", "conflict"} for word in words)
    emotion = min(1.0, emotional / max(1, len(words)) * 1.8 + (0.2 if question else 0))
    return round(importance, 3), round(emotion, 3)


def _choose_phrase_type(words: Sequence[AnalyzedWord], importance: float, phrase_index: int) -> SceneType | None:
    tokens = [_normalize(word.text) for word in words]
    number_count = sum(word.category == "number" for word in words)
    contrast_count = sum(token in CONTRAST_TOKENS for token in tokens)
    strong_count = sum(word.score >= 5 for word in words)
    hook = any(any(stem in token for stem in HOOK_STEMS) for token in tokens)
    if number_count >= 2 or number_count and any(word.category == "money" for word in words):
        return SceneType.NUMBER
    if contrast_count >= 2 or "наоборот" in tokens or ("не" in tokens and "но" in tokens):
        return SceneType.CONTRAST
    if len(words) <= 6 and (phrase_index == 0 and words[-1].text.rstrip().endswith("?") or hook and importance >= 0.72):
        return SceneType.HERO
    if len(words) <= 2 and importance >= 0.72 and strong_count:
        return SceneType.PUNCH
    return None


def _scene(words: Sequence[AnalyzedWord], kind: SceneType, importance: float, emotion: float, before: str, after: str) -> TextScene:
    ranked = sorted(range(len(words)), key=lambda index: words[index].score, reverse=True)
    emphasis_limit = 2 if kind in {SceneType.HERO, SceneType.CONTRAST} else 1
    emphasis = tuple(sorted(index for index in ranked[:emphasis_limit] if words[index].score >= 5))
    zoom = {
        SceneType.NORMAL: 1.0, SceneType.ACCENT: 1.055, SceneType.HERO: 1.12,
        SceneType.PUNCH: 1.11, SceneType.NUMBER: 1.10, SceneType.CONTRAST: 1.065,
    }[kind]
    return TextScene(
        words[0].start, words[-1].end, kind, kind.value, tuple(words), emphasis,
        importance, emotion, zoom, before, after,
    )


def _chunk_phrase(words: Sequence[AnalyzedWord], importance: float, emotion: float, before: str, after: str, rhythm: int) -> list[TextScene]:
    scenes: list[TextScene] = []
    cursor = 0
    while cursor < len(words):
        remaining = len(words) - cursor
        local = words[cursor:cursor + 5]
        peak = max((word.score for word in local), default=0)
        size = min(5 if peak < 4 and rhythm % 3 == 0 else 3 if peak >= 4 else 4, remaining)
        if remaining - size == 1:
            size = size - 1 if size > 2 else size + 1
        chunk = tuple(words[cursor:cursor + size])
        chunk_peak = max((word.score for word in chunk), default=0)
        chunk_strong = sum(word.score >= 5 for word in chunk)
        if len(chunk) <= 2 and chunk_peak >= 6 and importance >= 0.68:
            kind = SceneType.PUNCH
        elif chunk_strong:
            kind = SceneType.ACCENT
        else:
            kind = SceneType.NORMAL
        scenes.append(_scene(chunk, kind, importance, emotion, before, after))
        cursor += size; rhythm += 1
    return scenes


def _composition_steps(scene: TextScene) -> tuple[CompositionStep, ...]:
    all_indices = tuple(range(len(scene.words)))
    if scene.scene_type is SceneType.NUMBER and len(scene.words) >= 4:
        tokens = [_normalize(word.text) for word in scene.words]
        second_anchor = next(
            (index for index, token in enumerate(tokens[2:], start=2) if "миллион" in token or "миллиард" in token),
            None,
        )
        steps: list[CompositionStep] = []
        first_pair_end = min(2, len(scene.words))
        if first_pair_end > 1:
            steps.append(CompositionStep(scene.words[0].start, scene.words[1].start, (0,), 0))
        first_end = second_anchor if second_anchor is not None else len(scene.words)
        phrase_build_start = scene.words[min(2, len(scene.words) - 1)].start
        steps.append(CompositionStep(scene.words[1].start, phrase_build_start, tuple(range(first_pair_end)), 1))
        steps.append(CompositionStep(
            phrase_build_start,
            scene.words[first_end].start if first_end < len(scene.words) else scene.end,
            tuple(range(first_end)),
            min(first_end - 1, len(scene.words) - 1),
        ))
        if second_anchor is not None:
            next_start = scene.words[second_anchor + 1].start if second_anchor + 1 < len(scene.words) else scene.end
            steps.append(CompositionStep(scene.words[second_anchor].start, next_start, (second_anchor,), second_anchor))
            steps.append(CompositionStep(next_start, scene.end, tuple(range(second_anchor, len(scene.words))), min(second_anchor + 1, len(scene.words) - 1)))
        return tuple(step for step in steps if step.end - step.start >= 0.04)
    if scene.scene_type is SceneType.HERO and len(scene.words) >= 5:
        split = min(3, len(scene.words) - 1)
        return (
            CompositionStep(scene.start, scene.words[split].start, tuple(range(split)), split - 1),
            CompositionStep(scene.words[split].start, scene.end, all_indices, len(scene.words) - 1),
        )
    return (CompositionStep(scene.start, scene.end, all_indices, scene.emphasis_words[0] if scene.emphasis_words else None),)


def _speech_energy(scene: TextScene) -> float:
    duration = max(0.25, scene.end - scene.start)
    word_rate = len(scene.words) / duration
    punctuation = 0.12 if any(word.text.rstrip().endswith(("!", "?")) for word in scene.words) else 0.0
    return round(min(1.0, word_rate / 5.0 * 0.65 + scene.emotion_score * 0.25 + punctuation), 3)


def _motion_strength(scene: TextScene, energy: float) -> float:
    base = {
        SceneType.NORMAL: 0.16,
        SceneType.ACCENT: 0.48,
        SceneType.HERO: 0.76,
        SceneType.PUNCH: 0.88,
        SceneType.NUMBER: 0.80,
        SceneType.CONTRAST: 0.58,
    }[scene.scene_type]
    return round(min(1.0, base + scene.importance_score * 0.12 + energy * 0.10), 3)


def _motion_events(scene: TextScene, scene_index: int, last_motion: float) -> tuple[tuple[TextMotionEvent, ...], float]:
    energy = _speech_energy(scene)
    intensity = _motion_strength(scene, energy)
    limits = {
        SceneType.NORMAL: 1,
        SceneType.ACCENT: 1,
        SceneType.HERO: 2,
        SceneType.PUNCH: 1,
        SceneType.NUMBER: 1,
        SceneType.CONTRAST: 1,
    }
    candidates = list(scene.emphasis_words)
    if scene.scene_type is SceneType.CONTRAST:
        negative = [index for index in candidates if scene.words[index].category == "problem"]
        candidates = negative + [index for index in candidates if index not in negative]
    if not candidates and scene.scene_type in {SceneType.HERO, SceneType.PUNCH, SceneType.NUMBER}:
        candidates = [max(range(len(scene.words)), key=lambda index: scene.words[index].score)]
    if scene.scene_type is SceneType.NORMAL and scene.importance_score < 0.7:
        candidates = []
    candidates = sorted(candidates, key=lambda index: scene.words[index].score, reverse=True)[:limits[scene.scene_type]]
    presets = (MotionPreset.POP, MotionPreset.SCALE_IN, MotionPreset.SLIDE_UP)
    events: list[TextMotionEvent] = []
    for ordinal, word_index in enumerate(sorted(candidates, key=lambda index: scene.words[index].start)):
        word = scene.words[word_index]
        if word.start - last_motion < 0.48:
            continue
        strong = scene.scene_type in {SceneType.HERO, SceneType.PUNCH, SceneType.NUMBER} or intensity >= 0.72
        if scene.scene_type is SceneType.PUNCH:
            preset = MotionPreset.PUNCH
        elif word.category == "problem" and scene.emotion_score >= 0.28:
            preset = MotionPreset.POP
        elif scene.scene_type is SceneType.NUMBER:
            preset = MotionPreset.SCALE_IN
        else:
            preset = presets[(scene_index + ordinal) % len(presets)]
        duration = round(min(0.25, max(0.12, 0.12 + intensity * 0.13)), 3)
        start_scale = round(0.80 + (1.0 - intensity) * 0.12, 3) if strong else 1.0
        peak_scale = round(1.08 + intensity * (0.10 if strong else 0.04), 3)
        offset = {
            MotionPreset.BOUNCE: (0, 14),
            MotionPreset.PUNCH: (0, 10),
            MotionPreset.MICRO_SHAKE: (4, 0),
        }.get(preset, (0, 0))
        role = "punch_word" if scene.scene_type is SceneType.PUNCH else "strong_emphasis" if strong else "emphasis"
        events.append(TextMotionEvent(
            word.text, word_index, role, preset, word.start, duration, intensity,
            word_index, start_scale, peak_scale, 1.0, offset,
            preset not in {MotionPreset.SLIDE_LEFT, MotionPreset.SLIDE_UP},
        ))
        last_motion = word.start
    return tuple(events), last_motion


def _enrich_motion(scenes: Sequence[TextScene]) -> tuple[TextScene, ...]:
    enriched: list[TextScene] = []
    last_motion = -10.0
    for index, scene in enumerate(scenes):
        energy = _speech_energy(scene)
        intensity = _motion_strength(scene, energy)
        events, last_motion = _motion_events(scene, index, last_motion)
        roles = ["ordinary"] * len(scene.words)
        for word_index in scene.emphasis_words:
            roles[word_index] = (
                "punch_word" if scene.scene_type is SceneType.PUNCH
                else "strong_emphasis" if scene.scene_type in {SceneType.HERO, SceneType.NUMBER}
                else "emphasis"
            )
        enriched.append(replace(
            scene,
            motion_intensity=intensity,
            speech_energy=energy,
            word_roles=tuple(roles),
            composition_steps=_composition_steps(scene),
            motion_events=events,
        ))
    return tuple(enriched)


def _visual_events(scenes: Sequence[TextScene]) -> tuple[VisualEvent, ...]:
    events: list[VisualEvent] = []
    last_camera = -10.0
    last_gleam = -10.0
    timeline_end = scenes[-1].end if scenes else 0.0
    for index, scene in enumerate(scenes):
        gap = scene.start - last_camera
        strong = scene.scene_type in {SceneType.HERO, SceneType.PUNCH, SceneType.NUMBER, SceneType.CONTRAST}
        should_move = gap >= 2.0 and (strong or scene.importance_score >= 0.7 or gap >= 4.8)
        if should_move:
            end = min(timeline_end, scene.end + 0.25, scene.start + 1.8)
            event_zoom = 1.04 if scene.recommended_zoom == 1.0 else scene.recommended_zoom
            events.append(VisualEvent("camera_punch", scene.start, end, event_zoom - 1, True, {
                "zoom": event_zoom,
                "transition_in": 0.18,
                "transition_out": 0.24,
                "reason": scene.scene_type.value,
            }))
            last_camera = scene.start
        if scene.scene_type in {SceneType.HERO, SceneType.NUMBER}:
            events.append(VisualEvent("text_card", scene.start, scene.end, scene.importance_score, False, {"template": scene.text_template}))
            events.append(VisualEvent("sfx", scene.start, min(scene.end, scene.start + 0.3), 0.6, False, {"cue": "impact"}))
        if scene.scene_type is SceneType.CONTRAST:
            events.append(VisualEvent("flash", scene.start, min(scene.end, scene.start + 0.12), 0.35, False, {"color": "white"}))
        transition_markers = (
            "во-первых", "во-вторых", "в-третьих", "далее", "теперь", "итак",
            "кстати", "главное", "наконец", "следующее", "с другой стороны",
        )
        scene_text = " ".join(word.text for word in scene.words).lower().replace(" -", "-")
        logical_shift = (
            scene.scene_type in {SceneType.HERO, SceneType.NUMBER, SceneType.CONTRAST}
            or any(scene_text.startswith(marker) for marker in transition_markers)
        )
        if index > 0 and scene.start >= 4.0 and logical_shift and scene.start - last_gleam >= 5.5:
            events.append(VisualEvent(
                "gleam", scene.start, min(scene.end, scene.start + 0.46), 0.32, True,
                {"direction": "left_to_right", "reason": "logical_transition"},
            ))
            last_gleam = scene.start
        if scene.importance_score >= 0.78:
            events.append(VisualEvent("broll", scene.start, scene.end, scene.importance_score, False, {"query": " ".join(word.text for word in scene.words)}))
        if any(word.category == "number" for word in scene.words):
            events.append(VisualEvent("icon", scene.start, scene.end, 0.5, False, {"concept": "number"}))
    # Schema-ready placeholders document that these event types can be scheduled later.
    events.append(VisualEvent("image", 0, 0, 0, False, {"status": "available"}))
    return tuple(events)


def _phrases_from_retimed(blocks: Sequence[dict[str, Any]]) -> list[tuple[TranscriptWord, ...]]:
    phrases: list[tuple[TranscriptWord, ...]] = []
    for block in blocks:
        words = tuple(
            TranscriptWord(
                float(word["start"]),
                float(word["end"]),
                str(word["word"]),
                float(word.get("probability", 0.0)),
            )
            for word in block.get("words", [])
            if word.get("word") and word.get("start") is not None and word.get("end") is not None
        )
        if words:
            phrases.append(words)
    return phrases


def analyze_transcript(
    transcript: Transcript,
    retimed_blocks: Sequence[dict[str, Any]] | None = None,
) -> EditingPlan:
    raw_phrases = _phrases_from_retimed(retimed_blocks) if retimed_blocks is not None else _phrases(transcript)
    analyzed = [_classify(phrase) for phrase in raw_phrases]
    scenes: list[TextScene] = []
    rhythm = 0
    for index, phrase in enumerate(analyzed):
        previous = analyzed[index - 1] if index else ()
        following = analyzed[index + 1] if index + 1 < len(analyzed) else ()
        importance, emotion = _scores(phrase, previous, following)
        before = " ".join(word.text for word in previous[-4:])
        after = " ".join(word.text for word in following[:4])
        special = _choose_phrase_type(phrase, importance, index)
        if special:
            # HERO is capped at six words; other scene compositions at eight.
            cap = 6 if special is SceneType.HERO else 8
            for start in range(0, len(phrase), cap):
                part = phrase[start:start + cap]
                part_type = special if start == 0 else SceneType.ACCENT
                scenes.append(_scene(part, part_type, importance, emotion, before, after))
        elif retimed_blocks is not None:
            peak = max((word.score for word in phrase), default=0)
            strong_count = sum(word.score >= 5 for word in phrase)
            if len(phrase) <= 2 and peak >= 6 and importance >= 0.68:
                kind = SceneType.PUNCH
            elif strong_count:
                kind = SceneType.ACCENT
            else:
                kind = SceneType.NORMAL
            scenes.append(_scene(phrase, kind, importance, emotion, before, after))
        else:
            scenes.extend(_chunk_phrase(phrase, importance, emotion, before, after, rhythm))
        rhythm += 1
    scenes.sort(key=lambda scene: scene.start)
    enriched = _enrich_motion(scenes)
    return EditingPlan(enriched, _visual_events(enriched))
