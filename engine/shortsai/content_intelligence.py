from __future__ import annotations

from collections import Counter
import re
from typing import Any, Sequence

from .semantic_analysis import EditingPlan


CONTENT_ANALYSIS_VERSION = 1
STYLE_INTELLIGENCE_VERSION = 1
TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё%]+")
STOPWORDS = frozenset(
    "и в во на к ко с со у о об от до за из по под при про для не ни это тот та те "
    "как что чтобы когда где кто мы вы они он она я ты мой твой свой наш ваш уже ещё "
    "будет будут был была были есть просто очень также либо или а но же".split()
)
TOPICS: dict[str, frozenset[str]] = {
    "money": frozenset("деньги доход прибыль миллион миллионы миллиард сумма цена рубль рубли доллар доллары богатство капитал инвестиции бизнес продажа клиент услуга".split()),
    "expert": frozenset("правило способ метод причина ошибка совет важно нужно результат пример объясню почему как обучение система анализ".split()),
    "motivation": frozenset("успех цель победа рост развитие дисциплина действие никогда всегда сможешь станешь добьёшься".split()),
    "story": frozenset("однажды история случилось помню тогда потом сначала внезапно чувствовал оказалось решил".split()),
    "technology": frozenset("технология искусственный интеллект нейросеть программа приложение данные алгоритм автоматизация ai".split()),
    "relationships": frozenset("отношения мужчина женщина семья любовь партнёр доверие чувства".split()),
}
EMOTION_WORDS = frozenset("страх боль шок ненавижу люблю ужас провал потеря опасность счастье радость злость никогда невозможно".split())
CONFLICT_WORDS = frozenset("но однако против проблема ошибка провал потеря риск опасность вместо хотя никогда неправильно".split())
ASSERTION_WORDS = frozenset("главное факт правда всегда никогда точно обязан должен нужно нельзя гарантированно".split())
PODCAST_WORDS = frozenset("подкаст интервью ведущий гость разговор спросил ответил студия микрофон".split())
EDUCATION_WORDS = frozenset("объясню пример шаг правило метод способ разберём запомни во-первых во-вторых".split())


def _tokens(words: Sequence[dict[str, Any]]) -> list[str]:
    return [match.group(0).lower().replace("ё", "е") for word in words for match in TOKEN_RE.finditer(str(word.get("word", "")))]


def _related(token: str, vocabulary: frozenset[str]) -> bool:
    return any(token == item or (len(token) >= 5 and len(item) >= 5 and token[:5] == item[:5]) for item in vocabulary)


def _topic_scores(tokens: list[str]) -> dict[str, float]:
    counts = Counter(tokens)
    denominator = max(4.0, len(tokens) ** 0.55)
    return {
        topic: round(min(1.0, sum(count for token, count in counts.items() if _related(token, vocabulary)) / denominator), 3)
        for topic, vocabulary in TOPICS.items()
    }


def _keywords(tokens: list[str], editing_plan: EditingPlan) -> list[dict[str, Any]]:
    category_bonus: Counter[str] = Counter()
    for scene in editing_plan.scenes:
        for word in scene.words:
            matches = TOKEN_RE.findall(word.text.lower().replace("ё", "е"))
            if matches and word.category:
                category_bonus[matches[0]] += 2 + int(word.score >= 4)
    frequencies = Counter(token for token in tokens if len(token) >= 3 and token not in STOPWORDS and not token.isdigit())
    ranked = sorted(frequencies, key=lambda token: (-(frequencies[token] + category_bonus[token]), -len(token), token))
    return [{"word": token, "frequency": frequencies[token], "semanticWeight": min(10, frequencies[token] + category_bonus[token])} for token in ranked[:16]]


def analyze_content(
    editing_plan: EditingPlan,
    words: Sequence[dict[str, Any]],
    duration: float,
    face_plan: dict[str, Any] | None = None,
    editorial_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tokens = _tokens(words)
    scene_count = max(1, len(editing_plan.scenes))
    words_per_second = len(tokens) / max(1.0, duration)
    emotion = sum(float(scene.emotion_score) for scene in editing_plan.scenes) / scene_count
    importance = sum(float(scene.importance_score) for scene in editing_plan.scenes) / scene_count
    punctuation = " ".join(str(word.get("word", "")) for word in words)
    question_count = punctuation.count("?") + sum(token in {"почему", "зачем", "как", "что"} for token in tokens[:30])
    number_count = sum(bool(re.search(r"\d", str(word.get("word", "")))) for word in words)
    semantic_categories = Counter(word.category for scene in editing_plan.scenes for word in scene.words if word.category)
    semantic_money = semantic_categories["money"] + semantic_categories["number"]
    semantic_conflict = semantic_categories["conflict"] + semantic_categories["problem"]
    conflict_count = sum(_related(token, CONFLICT_WORDS) for token in tokens) + semantic_conflict
    assertion_count = sum(_related(token, ASSERTION_WORDS) for token in tokens)
    emotion_count = sum(_related(token, EMOTION_WORDS) for token in tokens)
    topic_scores = _topic_scores(tokens)
    topic_scores["money"] = round(max(topic_scores["money"], min(1.0, semantic_money / 4.0)), 3)
    topic = max(topic_scores, key=topic_scores.get) if max(topic_scores.values(), default=0.0) >= 0.12 else "general"
    first_words = [word for word in words if float(word.get("start", 0)) < 3.0]
    first_tokens = _tokens(first_words)
    hook_question = bool(set(first_tokens) & {"почему", "зачем", "как", "что"}) or any("?" in str(word.get("word", "")) for word in first_words)
    first_end = max((float(word.get("end", 0)) for word in first_words), default=3.0)
    hook_number = any(re.search(r"\d", str(word.get("word", ""))) for word in first_words) or any(word.category in {"money", "number"} and word.start < first_end for scene in editing_plan.scenes for word in scene.words)
    hook_conflict = any(_related(token, CONFLICT_WORDS) for token in first_tokens)
    hook_assertion = any(_related(token, ASSERTION_WORDS) for token in first_tokens)
    text_hook_score = min(1.0, 0.28 + 0.22 * hook_question + 0.18 * hook_number + 0.20 * hook_conflict + 0.16 * hook_assertion)
    editorial = editorial_quality or {}
    opening = float(editorial.get("start", {}).get("strong_opening", 0.72))
    hook_score = min(1.0, text_hook_score * 0.72 + opening * 0.28)
    if "START_QUALITY_WARNING" in editorial.get("warnings", []):
        hook_score = min(hook_score, 0.62)
    podcast_signals = sum(_related(token, PODCAST_WORDS) for token in tokens)
    education_signals = sum(_related(token, EDUCATION_WORDS) for token in tokens)
    face = face_plan or {}
    face_detected = bool(face.get("detected"))
    format_name = "podcast" if podcast_signals >= 2 else "education" if education_signals >= 2 else "talking_head" if face_detected else "voice_over"
    audience = "entrepreneurs_and_finance" if topic == "money" else "professionals_and_learners" if topic in {"expert", "technology"} else "broad_lifestyle" if topic == "relationships" else "broad_social"
    energy = min(1.0, emotion * 1.35 + min(0.42, words_per_second / 7.0) + min(0.22, (conflict_count + assertion_count) / 18.0))
    return {
        "version": CONTENT_ANALYSIS_VERSION, "topic": topic, "topicScores": topic_scores,
        "keywords": _keywords(tokens, editing_plan), "audience": audience, "format": format_name,
        "delivery": {"wordsPerSecond": round(words_per_second, 3), "pace": "fast" if words_per_second >= 2.8 else "medium" if words_per_second >= 2.0 else "calm", "emotionScore": round(emotion, 3), "energyScore": round(energy, 3), "averageImportance": round(importance, 3)},
        "signals": {"questions": int(question_count), "numbers": int(max(number_count, semantic_categories["number"])), "money": int(semantic_money), "conflicts": int(conflict_count), "strongAssertions": int(assertion_count), "emotionalWords": int(emotion_count), "podcast": int(podcast_signals), "education": int(education_signals)},
        "hook": {"score": round(hook_score, 3), "textScore": round(text_hook_score, 3), "visualReadiness": round(opening, 3), "strongOpening": opening >= 0.64, "question": hook_question, "number": hook_number, "conflict": hook_conflict, "strongAssertion": hook_assertion, "text": " ".join(str(word.get("word", "")) for word in first_words).strip()},
        "visual": {"faceDetected": face_detected, "facePosition": face.get("dominantPosition", "unknown"), "textSide": face.get("textSide", "bottom"), "freeZones": face.get("freeZones", [])},
    }


def select_style(content: dict[str, Any], requested_profile: str = "AUTO") -> dict[str, Any]:
    requested = requested_profile.upper()
    delivery, signals, topics = content["delivery"], content["signals"], content["topicScores"]
    hook = float(content["hook"]["score"])
    fast = 1.0 if delivery["pace"] == "fast" else 0.45 if delivery["pace"] == "medium" else 0.0
    energy = float(delivery["energyScore"])
    expert = float(topics.get("expert", 0)) + float(topics.get("technology", 0)) * 0.55
    story = float(topics.get("story", 0))
    podcast = min(1.0, signals["podcast"] / 2.0 + (0.35 if content["format"] == "podcast" else 0.0))
    conflict = min(1.0, signals["conflicts"] / 5.0)
    money = float(topics.get("money", 0))
    scores = {
        "AGGRESSIVE_SOCIAL": 0.16 + money * 0.40 + conflict * 0.20 + fast * 0.18 + energy * 0.17 + hook * 0.08,
        "CLEAN_EXPERT": 0.24 + expert * 0.30 + (1.0 - energy) * 0.12 + (0.12 if content["format"] == "education" else 0.0),
        "PODCAST_PREMIUM": 0.16 + podcast * 0.52 + (1.0 - fast) * 0.12 + (0.08 if content["visual"]["faceDetected"] else 0.0),
        "CINEMATIC_STORY": 0.15 + story * 0.42 + min(1.0, signals["emotionalWords"] / 4.0) * 0.18 + (1.0 - fast) * 0.10,
        "HIGH_RETENTION": 0.20 + hook * 0.22 + fast * 0.16 + energy * 0.17 + conflict * 0.11 + min(1.0, signals["numbers"] / 3.0) * 0.08,
    }
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    automatic = requested == "AUTO"
    profile = ranked[0][0] if automatic else requested
    margin = ranked[0][1] - ranked[1][1]
    confidence = min(0.97, max(0.56, 0.64 + margin * 0.8)) if automatic else 1.0
    reasons: list[str] = []
    if automatic:
        if money >= 0.12: reasons.append("money/business semantics")
        if conflict >= 0.2: reasons.append("conflict-driven statements")
        if fast >= 1.0: reasons.append("fast speech pace")
        if expert >= 0.18: reasons.append("expert/educational structure")
        if podcast >= 0.5: reasons.append("podcast conversation signals")
        if story >= 0.15: reasons.append("storytelling structure")
        if hook >= 0.65: reasons.append("strong first-three-second hook")
    else: reasons.append("manual profile override")
    intensity = 0.45 + energy * 0.35 + hook * 0.20
    return {
        "version": STYLE_INTELLIGENCE_VERSION, "profile": profile, "selectedStyle": profile,
        "confidence": round(confidence, 3), "reason": reasons or ["best weighted content match"],
        "reasoning": reasons or ["best weighted content match"], "automatic": automatic,
        "scores": {name: round(score, 3) for name, score in scores.items()},
        "metrics": {"topic": content["topic"], "audience": content["audience"], "format": content["format"], "tempo": delivery["pace"], "wordsPerSecond": delivery["wordsPerSecond"], "emotion": "high" if delivery["emotionScore"] >= 0.32 else "medium" if delivery["emotionScore"] >= 0.16 else "low", "emotionScore": delivery["emotionScore"], "averageImportance": delivery["averageImportance"], "moneySignals": signals["numbers"] if content["topic"] == "money" else 0, "conflictSignals": signals["conflicts"], "expertSignals": signals["education"], "podcastSignals": signals["podcast"]},
        "editParameters": {"overallIntensity": round(min(1.0, intensity), 3), "textDensity": round(0.55 + fast * 0.22 + hook * 0.12, 3), "cameraIntensity": round(0.38 + energy * 0.40 + conflict * 0.12, 3), "brollPriority": round(0.42 + expert * 0.16 + story * 0.22, 3), "effectIntensity": round(0.30 + energy * 0.42 + hook * 0.16, 3), "hookPriority": round(hook, 3)},
        "contentAnalysis": content,
    }
