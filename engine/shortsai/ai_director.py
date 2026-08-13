from __future__ import annotations

from collections import Counter
import re
from typing import Any, Sequence

from .semantic_analysis import EditingPlan, TextScene


DIRECTOR_PLAN_VERSION = 2


def _normalize(value: str) -> str:
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё-]", "", value).lower()


def _scene_text(scene: TextScene) -> str:
    return " ".join(word.text for word in scene.words)


def _group_scenes(scenes: Sequence[TextScene]) -> list[list[TextScene]]:
    groups: list[list[TextScene]] = []
    current: list[TextScene] = []
    for scene in scenes:
        current.append(scene)
        duration = current[-1].end - current[0].start
        sentence_end = _scene_text(scene).rstrip().endswith((".", "!", "?", ":", ";"))
        if (sentence_end and duration >= 1.0) or duration >= 4.2:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _content_type(group: Sequence[TextScene], index: int) -> str:
    categories = Counter(word.category for scene in group for word in scene.words if word.category)
    tokens = {_normalize(word.text) for scene in group for word in scene.words}
    text = " ".join(_scene_text(scene) for scene in group)
    if index == 0:
        return "HOOK"
    large_number = any(
        re.search(r"\d{3,}", token)
        or token.startswith(("тысяч", "миллион", "миллиард", "процент", "рубл", "доллар"))
        for token in tokens
    )
    if categories["number"] and (large_number or categories["money"] or categories["number"] >= 2):
        return "NUMBER"
    if categories["money"]:
        return "MONEY"
    if categories["problem"] and categories["conflict"]:
        return "CONFLICT"
    if categories["problem"]:
        return "PROBLEM"
    if tokens.intersection({"решение", "нужно", "надо", "сделай", "используй", "добавь"}):
        return "SOLUTION"
    if categories["result"]:
        return "RESULT"
    if categories["emotion"]:
        return "EMOTION"
    if "«" in text or "»" in text or '"' in text:
        return "QUOTE"
    return "NORMAL"


def _segment_scores(
    group: Sequence[TextScene], content_type: str, index: int, previous_type: str | None,
) -> dict[str, float]:
    importance = max(scene.importance_score for scene in group)
    raw_emotion = max(scene.emotion_score for scene in group)
    text = " ".join(_scene_text(scene) for scene in group)
    words = [word for scene in group for word in scene.words]
    categories = {word.category for word in words if word.category}
    key_density = min(1.0, sum(word.score >= 4 for word in words) / max(2, len(words)) * 2.2)
    question = "?" in text
    exclamation = "!" in text
    semantic_change = 1.0 if index == 0 or (previous_type and previous_type != content_type) else 0.34

    hook_strength = 0.0
    if index == 0:
        hook_strength = 0.38 + importance * 0.24
        hook_strength += 0.22 if question else 0.08 if exclamation else 0.0
        hook_strength += 0.12 if content_type in {"HOOK", "CONFLICT", "PROBLEM", "NUMBER", "MONEY"} else 0.0
    elif question and content_type in {"CONFLICT", "PROBLEM"}:
        hook_strength = 0.24 + importance * 0.18

    emotion_bonus = 0.16 if content_type in {"CONFLICT", "PROBLEM", "EMOTION"} else 0.08 if content_type == "HOOK" else 0.0
    emotional_intensity = raw_emotion * 0.72 + emotion_bonus + (0.10 if exclamation else 0.0)

    information_bonus = {
        "NUMBER": 0.18, "SOLUTION": 0.15, "RESULT": 0.13, "MONEY": 0.12,
        "CONFLICT": 0.10, "PROBLEM": 0.09, "HOOK": 0.08, "QUOTE": 0.07,
        "EMOTION": 0.05, "NORMAL": 0.0,
    }[content_type]
    information_value = importance * 0.54 + key_density * 0.20 + information_bonus
    assertion_strength = importance * 0.68 + (0.10 if content_type not in {"NORMAL", "QUOTE"} else 0.0)
    assertion_strength += 0.08 if question or exclamation else 0.0
    if "conflict" in categories or "result" in categories or "principle" in categories:
        assertion_strength += 0.06

    hook_strength = _bounded(hook_strength)
    emotional_intensity = _bounded(emotional_intensity)
    information_value = _bounded(information_value)
    assertion_strength = _bounded(assertion_strength)
    visual_importance = _bounded(
        information_value * 0.32 + emotional_intensity * 0.22 + semantic_change * 0.20
        + hook_strength * 0.16 + assertion_strength * 0.10
    )
    retention = _bounded(
        hook_strength * 0.24 + emotional_intensity * 0.20 + information_value * 0.30
        + assertion_strength * 0.16 + semantic_change * 0.10
    )
    return {
        "hook_strength": round(hook_strength, 3),
        "emotional_intensity": round(emotional_intensity, 3),
        "information_value": round(information_value, 3),
        "visual_importance": round(visual_importance, 3),
        "assertion_strength": round(assertion_strength, 3),
        "semantic_change": round(semantic_change, 3),
        "retention": round(retention, 3),
    }


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, value))


def _clamped_duration(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _broll_limit(duration: float, configured: int) -> int:
    if duration < 30:
        duration_limit = max(1, round(duration / 12))
    elif duration <= 60:
        duration_limit = max(3, min(6, round(duration / 11)))
    else:
        duration_limit = max(4, min(8, round(duration / 12)))
    return max(0, min(configured, duration_limit))


def _key_terms(group: Sequence[TextScene]) -> list[str]:
    ranked = sorted(
        (word for scene in group for word in scene.words if word.category or word.score >= 4),
        key=lambda word: (-word.score, word.start),
    )
    values: list[str] = []
    for word in ranked:
        token = _normalize(word.text)
        if token and token not in values:
            values.append(token)
    return values[:6]


def build_director_plan(
    editing_plan: EditingPlan,
    profile: dict[str, Any],
    style_decision: dict[str, Any],
    *,
    speech_edit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_name = profile["name"]
    scene_rules = profile.get("scene", {})
    camera_rules = profile.get("camera", {})
    hero_min = float(scene_rules.get("hero_min_importance", 0.8))
    punch_min = float(scene_rules.get("punch_min_importance", 0.9))
    hero_cooldown = float(scene_rules.get("hero_cooldown", 12.0))
    punch_cooldown = float(scene_rules.get("punch_cooldown", 8.0))
    groups = _group_scenes(editing_plan.scenes)
    segments: list[dict[str, Any]] = []
    text_events: list[dict[str, Any]] = []
    camera_events: list[dict[str, Any]] = []
    broll_events: list[dict[str, Any]] = []
    broll_candidates: list[dict[str, Any]] = []
    sfx_events: list[dict[str, Any]] = []
    last_hero = -100.0
    last_punch = -100.0
    previous_type: str | None = None
    seen_visual_terms: set[str] = set()
    last_broll_topic: str | None = None
    content_format = str(style_decision.get("metrics", {}).get("format", "unknown")).lower()

    for index, group in enumerate(groups):
        start, end = group[0].start, group[-1].end
        content_type = _content_type(group, index)
        importance = round(max(scene.importance_score for scene in group), 3)
        emotion_score = round(max(scene.emotion_score for scene in group), 3)
        keys = _key_terms(group)
        scores = _segment_scores(group, content_type, index, previous_type)
        if index == 0:
            opening = style_decision.get("contentAnalysis", {}).get("hook", {})
            visual_opening = float(opening.get("visualReadiness", 0.72))
            scores["hook_strength"] = round(_bounded(scores["hook_strength"] * 0.68 + visual_opening * 0.32), 3)
            if opening.get("strongOpening") is False:
                scores["hook_strength"] = min(scores["hook_strength"], 0.62)
            scores["retention"] = round(_bounded(
                scores["hook_strength"] * 0.24 + scores["emotional_intensity"] * 0.20
                + scores["information_value"] * 0.30 + scores["visual_importance"] * 0.26
            ), 3)
        retention = scores["retention"]
        visual_importance = scores["visual_importance"]
        decision_strength = round(_bounded(
            importance * 0.34 + visual_importance * 0.30
            + scores["emotional_intensity"] * 0.16
            + scores["information_value"] * 0.12
            + scores["assertion_strength"] * 0.08
        ), 3)
        strongest = max(group, key=lambda scene: (scene.importance_score, max((word.score for word in scene.words), default=0)))
        actions: list[str] = []
        visual_role = "NORMAL"
        template = "PHRASE_BUILD"
        danger = content_type in {"CONFLICT", "PROBLEM"}
        strong_content = content_type in {"HOOK", "CONFLICT", "PROBLEM", "RESULT", "NUMBER", "MONEY", "EMOTION", "SOLUTION"}

        if content_type == "HOOK" and scores["hook_strength"] >= 0.68:
            visual_role, template = "HERO", "STACKED_TEXT"
            actions.extend(["HERO", "HERO_ZOOM", "SFX_IMPACT"])
            last_hero = start
        elif content_type == "NUMBER" and scores["information_value"] >= 0.62 and visual_importance >= 0.52:
            visual_role, template = "NUMBER", "NUMBER_HERO"
            actions.extend(["NUMBER_HERO", "HERO_ZOOM", "SFX_IMPACT"])
        elif content_type == "CONFLICT" and visual_importance >= 0.55 and decision_strength >= 0.56:
            visual_role, template = "CONTRAST", "CONTRAST_SPLIT"
            actions.extend(["CONTRAST", "SEMANTIC_ACCENT", "RED_ACCENT"])
        elif strong_content and decision_strength >= punch_min and visual_importance >= 0.70 and len(strongest.words) <= 2 and start - last_punch >= punch_cooldown:
            visual_role, template = "PUNCH", "KEYWORD_HERO"
            actions.extend(["PUNCH", "PUNCH_ZOOM", "SFX_IMPACT"])
            last_punch = start
        elif strong_content and decision_strength >= hero_min and visual_importance >= 0.61 and start - last_hero >= hero_cooldown:
            visual_role = "HERO"
            template = "KEYWORD_HERO" if len(strongest.words) <= 2 else "STACKED_TEXT"
            actions.extend(["HERO", "HERO_ZOOM", "RED_ACCENT" if danger else "SEMANTIC_ACCENT", "SFX_IMPACT"])
            last_hero = start
        elif visual_importance >= 0.50 and decision_strength >= 0.50:
            visual_role = "ACCENT"
            actions.extend(["ACCENT", "ACCENT_ZOOM", "RED_ACCENT" if danger else "SEMANTIC_ACCENT"])
        else:
            actions.append("REST")
            if (
                content_type == "NORMAL"
                and scores["information_value"] < 0.30
                and scores["emotional_intensity"] < 0.18
                and end - start >= 3.0
            ):
                actions.append("SPEED_UP")

        reason = (
            "strong hook with immediate viewer promise" if scores["hook_strength"] >= 0.68 else
            "high-value semantic transition" if visual_importance >= 0.65 else
            "meaningful supporting point" if decision_strength >= 0.50 else
            "low information density" if "SPEED_UP" in actions else
            "supporting explanation"
        )
        segment_id = f"segment-{index + 1:02d}"
        segment = {
            "id": segment_id, "start": round(start, 3), "end": round(end, 3),
            "text": " ".join(_scene_text(scene) for scene in group),
            "type": content_type, "importance": importance,
            "emotion": "high" if emotion_score >= 0.34 else "medium" if emotion_score >= 0.18 else "low",
            "emotion_score": emotion_score, "retention_score": retention,
            "retention_scores": scores,
            "hook_strength": scores["hook_strength"],
            "emotional_intensity": scores["emotional_intensity"],
            "information_value": scores["information_value"],
            "visual_importance": visual_importance,
            "assertion_strength": scores["assertion_strength"],
            "semantic_change": scores["semantic_change"],
            "decision_strength": decision_strength,
            "retention_reason": reason, "key_terms": keys,
            "recommended_action": actions,
            "speech_action": "COMPRESS" if "SPEED_UP" in actions else "KEEP",
        }
        segments.append(segment)

        for scene in group:
            primary = scene is strongest
            event_role = visual_role if primary else "ACCENT" if visual_role in {"HERO", "PUNCH", "NUMBER"} and scene.importance_score >= 0.6 else "NORMAL"
            event_template = template if primary else "PHRASE_BUILD"
            text_events.append({
                "start": round(scene.start, 3), "end": round(scene.end, 3),
                "text": _scene_text(scene), "scene_type": event_role,
                "template": event_template, "segment_id": segment_id,
                "importance": round(scene.importance_score, 3),
                "visual_importance": visual_importance,
                "decision_strength": decision_strength,
                "color_role": "danger" if danger and primary else "accent" if event_role != "NORMAL" else "text",
                "reason": reason,
            })

        if visual_role in {"HERO", "PUNCH", "NUMBER"}:
            camera_type = "HERO_ZOOM" if visual_role in {"HERO", "NUMBER"} else "PUNCH_ZOOM"
            scale_key = "hero" if visual_role in {"HERO", "NUMBER"} else "strong"
            camera_events.append({
                "time": round(strongest.start, 3), "duration": 0.82 if visual_role != "PUNCH" else 0.58,
                "type": camera_type, "strength": round(retention, 3),
                "scale": round(float(camera_rules.get(scale_key, 1.12)), 3),
                "segment_id": segment_id, "reason": content_type,
            })
            sfx_events.append({
                "time": round(strongest.start, 3), "type": "IMPACT", "intensity": round(retention, 3),
                "segment_id": segment_id, "reason": content_type, "enabled": True,
            })
        elif visual_role == "ACCENT":
            camera_events.append({
                "time": round(strongest.start, 3), "duration": 1.1,
                "type": "ACCENT_ZOOM", "strength": round(min(0.7, retention), 3),
                "scale": round(float(camera_rules.get("subtle", 1.04)), 3),
                "segment_id": segment_id, "reason": content_type,
            })

        visualizability = {
            "NUMBER": 0.86, "MONEY": 0.76, "SOLUTION": 0.72, "PROBLEM": 0.60,
            "RESULT": 0.58, "CONFLICT": 0.56, "EMOTION": 0.48,
        }.get(content_type, 0.28)
        visualizability = _bounded(visualizability + min(0.08, len(keys) * 0.02))
        explanatory_value = _bounded(
            scores["information_value"] * 0.58 + scores["assertion_strength"] * 0.27
            + (0.10 if content_type in {"NUMBER", "SOLUTION", "PROBLEM"} else 0.05)
        )
        new_terms = [term for term in keys if term not in seen_visual_terms]
        term_novelty = len(new_terms) / max(1, len(keys))
        topic_novelty = 1.0 if last_broll_topic != content_type else 0.25
        novelty = _bounded(term_novelty * 0.58 + topic_novelty * 0.42)
        pre_asset_necessity = round(_bounded(
            visualizability * 0.38 + explanatory_value * 0.30
            + scores["semantic_change"] * 0.14 + novelty * 0.18
        ), 3)
        broll_helpful = content_type in {"MONEY", "RESULT", "SOLUTION", "EMOTION", "PROBLEM", "CONFLICT", "NUMBER"}
        min_broll_value = max(0.64, float(profile.get("broll", {}).get("min_importance", 0.65)))
        if broll_helpful and keys and pre_asset_necessity >= min_broll_value and scores["information_value"] >= 0.48:
            shot_duration = float(profile.get("broll", {}).get("shot_duration", 1.0))
            target_duration = (
                _clamped_duration(end - start, 1.4, 2.0)
                if content_format == "talking_head" else _clamped_duration(end - start, 1.6, 3.2)
            )
            broll_candidates.append({
                "type": "BROLL_BURST", "topic": content_type.lower(),
                "start": round(start, 3), "duration": round(target_duration, 3),
                "text": segment["text"], "importance": importance,
                "visual_importance": visual_importance, "broll_value": pre_asset_necessity,
                "broll_necessity": {
                    "visualizability": round(visualizability, 3),
                    "semantic_change": scores["semantic_change"],
                    "explanatory_value": round(explanatory_value, 3),
                    "novelty": round(novelty, 3),
                    "asset_match": None, "final_score": None,
                },
                "content_format": content_format,
                "segment_id": segment_id, "reason": "visual replacement can explain this semantic block better than speaker alone",
                "search_terms": keys[:4],
                "shots": [
                    {"search": term, "duration": round(shot_duration, 2)}
                    for term in (keys[:3] or [content_type.lower()])
                ],
            })
            seen_visual_terms.update(keys)
            last_broll_topic = content_type
        previous_type = content_type

    timeline_end = max((float(item["end"]) for item in segments), default=0.0)
    broll_rules = profile.get("broll", {})
    broll_gap = max(
        8.0 if content_format == "talking_head" else 5.5 if timeline_end >= 30 else 4.0,
        float(broll_rules.get("min_gap", 8.0)),
    )
    broll_cap = _broll_limit(timeline_end, int(broll_rules.get("max_bursts", 4)))
    selected_broll: list[dict[str, Any]] = []
    for candidate in sorted(broll_candidates, key=lambda item: float(item["start"])):
        if float(candidate["start"]) < 2.0:
            continue
        if selected_broll and float(candidate["start"]) - (
            float(selected_broll[-1]["start"]) + float(selected_broll[-1]["duration"])
        ) < broll_gap:
            previous = selected_broll[-1]
            before_previous_end = (
                float(selected_broll[-2]["start"]) + float(selected_broll[-2]["duration"])
                if len(selected_broll) > 1 else -100.0
            )
            if (
                float(candidate["broll_value"]) >= float(previous["broll_value"]) + 0.08
                and float(candidate["start"]) - before_previous_end >= broll_gap
            ):
                selected_broll[-1] = candidate
            continue
        selected_broll.append(candidate)
    if len(selected_broll) > broll_cap:
        selected_broll = sorted(
            sorted(selected_broll, key=lambda item: (-float(item["broll_value"]), float(item["start"])))[:broll_cap],
            key=lambda item: float(item["start"]),
        )
    broll_events.extend(selected_broll)

    duration_total = sum(max(0.01, item["end"] - item["start"]) for item in segments)
    retention_score = round(sum(
        item["retention_score"] * max(0.01, item["end"] - item["start"]) for item in segments
    ) / max(0.01, duration_total), 3)
    hook = next((item for item in segments if item["type"] == "HOOK"), {})
    return {
        "version": DIRECTOR_PLAN_VERSION,
        "profile": profile_name,
        "profile_decision": style_decision,
        "hook": hook,
        "segments": segments,
        "text_events": text_events,
        "camera_events": camera_events,
        "broll_events": broll_events,
        "sfx_events": sfx_events,
        "retention_score": retention_score,
        "decision_policy": {
            "segment_scoring": "retention_v2", "broll_scope": "semantic_block",
            "broll_min_gap": round(broll_gap, 3), "broll_max_events": broll_cap,
            "effects_require_visual_importance": True,
            "broll_requires_asset_match": True, "content_format": content_format,
        },
        "speech_edit": speech_edit or {},
    }
