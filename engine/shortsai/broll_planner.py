from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

from .broll_library import build_broll_library, normalize_token, tokens


STOPWORDS = frozenset(
    "а и но или либо в во на к ко с со у о об от до за из по под при про для не ни это тот эта эти "
    "как что чтобы когда где кто мы вы они он она я ты мой твой свой наш ваш уже еще сейчас просто "
    "будет будут был была были есть number principle ordinary very with from into this that the and for are was were".split()
)

CONCEPTS: dict[str, frozenset[str]] = {
    "money": frozenset("деньги денежный сумма суммы миллион миллионы богатый богатство доход цена прибыль cash money finance dollar ruble".split()),
    "bank_credit_debt": frozenset("банк банковский кредит кредитка долг ставка проценты процент платеж займ bank banking credit debt loan statement minimum payment interest".split()),
    "payment": frozenset("оплата оплатить перевод счет карта терминал бесконтактный payment transfer invoice card contactless salary charges".split()),
    "analytics": frozenset("аналитика статистика метрика график просмотры охват удержание подписчики рост analytics metrics stats graph views reach retention followers growth dashboard".split()),
    "content_creation": frozenset("контент монтаж таймлайн редактор съемка камера сценарий ролик нарезка editing timeline editor camera recording script video content thumbnail".split()),
    "social_media": frozenset("соцсети комментарии лента скролл вовлеченность блог social comments feed scroll engagement blogger".split()),
    "community_chat": frozenset("чат сообщение ответ уведомление сообщество реакция chat message reply notification community reactions".split()),
    "business": frozenset("бизнес предприниматель услуга услуги продавать продажа клиент работа реклама маркетинг company business entrepreneur service client sales advertising marketing crm".split()),
    "discipline": frozenset("дисциплина привычка режим каждый ежедневно календарь тренировка discipline habit routine calendar training".split()),
    "failure": frozenset("провал провалились ошибка проблема потеря яма риск failure mistake problem loss risk".split()),
    "success": frozenset("успех результат получилось победа рост развитие success result win growth achievement".split()),
    "family": frozenset("родители семья наследство отец мать family parents inheritance".split()),
    "lottery": frozenset("лотерея выигрыш билет jackpot lottery ticket prize".split()),
    "mindset": frozenset("мышление мысль решение выбор идея mindset thought decision idea".split()),
}

CTA_MARKERS = frozenset({
    "подписывайся", "подпишись", "подписывайтесь", "подписаться", "подписка",
    "лайк", "лайкни", "комментарий", "комментариях", "сохрани", "репост",
    "канал", "профиль", "ссылка", "follow", "subscribe", "comment", "like",
})


def _bounded_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def _related(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < 5:
        return False
    # Conservative prefix comparison covers common Russian case endings while
    # avoiding broad substring matches.
    return left[:5] == right[:5]


def _has_related(source: set[str], vocabulary: set[str] | frozenset[str]) -> bool:
    return any(_related(left, right) for left in source for right in vocabulary)


def _query(scene: dict[str, Any]) -> tuple[list[str], set[str]]:
    source = tokens(scene.get("text", "")) | tokens(scene.get("directorQuery", []))
    for word in scene.get("words", []):
        category = word.get("category")
        if category:
            source.add(normalize_token(str(category)))
    meaningful = {token for token in source if token not in STOPWORDS and len(token) >= 3}
    concepts = {
        name for name, vocabulary in CONCEPTS.items()
        if _has_related(meaningful, vocabulary)
    }
    director_topic = normalize_token(str(scene.get("directorTopic", "")))
    if director_topic in CONCEPTS:
        concepts.add(director_topic)
    ranked = sorted(meaningful, key=lambda value: (-len(value), value))[:8]
    return ranked, concepts


def _local_query(scene: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Return only the words spoken in this segment, without global Director hints."""
    source = tokens(scene.get("text", ""))
    meaningful = {token for token in source if token not in STOPWORDS and len(token) >= 3}
    concepts = {
        name for name, vocabulary in CONCEPTS.items()
        if _has_related(meaningful, vocabulary)
    }
    return meaningful, concepts


def _is_cta(scene: dict[str, Any]) -> bool:
    local, _ = _local_query(scene)
    return _has_related(local, CTA_MARKERS)


def _local_asset_relevance(
    asset: dict[str, Any], local_tokens: set[str], local_concepts: set[str],
) -> float:
    """Measure asset relevance to the current phrase, not to the video topic."""
    if not local_tokens:
        return 0.0
    asset_tokens = set(asset.get("tags", []))
    direct_hits = sum(any(_related(token, tag) for tag in asset_tokens) for token in local_tokens)
    direct = direct_hits / max(2, min(6, len(local_tokens)))
    asset_concepts = _asset_concepts(asset)
    concept = len(local_concepts & asset_concepts) / max(1, len(local_concepts)) if local_concepts else 0.0
    return _bounded_score(direct * 0.68 + concept * 0.32)


def _asset_concepts(asset: dict[str, Any]) -> set[str]:
    asset_tokens = set(asset.get("tags", []))
    declared = {str(value) for value in asset.get("semanticGroups", [])}
    return declared | {name for name, vocabulary in CONCEPTS.items() if _has_related(asset_tokens, vocabulary) or name in asset_tokens}


def _score(
    asset: dict[str, Any], query_tokens: set[str], query_concepts: set[str], used: set[str],
    profile_name: str, *, allow_reuse: bool, use_counts: dict[str, int],
) -> float:
    asset_id = str(asset.get("id", ""))
    if not asset.get("usable", False) or (asset_id in used and not allow_reuse):
        return -1.0
    asset_tokens = set(asset.get("tags", []))
    direct = sum(any(_related(query, tag) for tag in asset_tokens) for query in query_tokens)
    concept = len(query_concepts & _asset_concepts(asset))
    if direct == 0 and concept == 0:
        return -1.0
    orientation_bonus = 0.9 if asset.get("orientation") == "vertical" else 0.45 if asset.get("orientation") == "square" else 0.0
    resolution_bonus = 0.35 if int(asset.get("height", 0)) >= 1080 else 0.15
    duration_bonus = min(0.4, float(asset.get("duration", 0)) / 20.0)
    suitable = {str(value).upper() for value in asset.get("suitableStyles", [])}
    style_bonus = 0.55 if not suitable or profile_name.upper() in suitable else -0.35
    importance_bonus = float(asset.get("importance", 0.6)) * 0.4
    reuse_penalty = use_counts.get(asset_id, 0) * 4.5
    return round(direct * 3.0 + concept * 2.25 + orientation_bonus + resolution_bonus + duration_bonus + style_bonus + importance_bonus - reuse_penalty, 3)


def _start_from(asset: dict[str, Any], shot_duration: float, seed: str) -> float:
    available = max(0.0, float(asset["duration"]) - shot_duration - 0.08)
    if available <= 0.0:
        return 0.0
    ratio = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    return round(min(available, available * (0.15 + ratio * 0.7)), 3)


def build_broll_plan(
    scenes: list[dict[str, Any]],
    assets_dir: Path,
    profile: dict[str, Any],
    ffprobe: Path,
    director_events: Sequence[dict[str, Any]] | None = None,
    camera_actions: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rules = profile.get("broll", {})
    library = build_broll_library(assets_dir / "broll", ffprobe)
    if not rules.get("enabled", False):
        return {"version": 1, "library": library, "requests": [], "events": []}

    timeline_end = max((float(scene["end"]) for scene in scenes), default=0.0)
    min_importance = float(rules.get("min_importance", 0.8))
    content_format = next((
        str(event.get("content_format", "")).lower()
        for event in (director_events or []) if event.get("content_format")
    ), "unknown")
    talking_head = content_format == "talking_head"
    end_zone_seconds = max(3.5, min(6.0, timeline_end * 0.10)) if talking_head else max(2.5, min(4.5, timeline_end * 0.07))
    end_zone_start = max(0.0, timeline_end - end_zone_seconds)
    configured_gap = float(rules.get("min_gap", 14.0))
    aggressive_profile = profile.get("name") in {"AGGRESSIVE_SOCIAL", "AGGRESSIVE_RED", "HIGH_RETENTION"}
    talking_head_floor = 6.5 if aggressive_profile else 8.0
    min_gap = (
        max(talking_head_floor, min(configured_gap, 9.5))
        if talking_head
        else max(configured_gap, 5.5 if 30 <= timeline_end <= 60 else 4.0)
    )
    configured_max = int(rules.get("max_bursts", 4))
    duration_max = (
        max(1, round(timeline_end / 12)) if timeline_end < 30
        else max(3, min(6, round(timeline_end / 11))) if timeline_end <= 60
        else max(4, min(8, round(timeline_end / 12)))
    )
    max_bursts = min(configured_max, duration_max, 3 if talking_head and timeline_end >= 45 else configured_max)
    target_coverage = {"min": 0.06, "max": 0.14} if talking_head else {"min": 0.10, "max": 0.35}
    max_coverage = min(target_coverage["max"], max(0.0, float(rules.get("max_coverage", 0.22))))
    shot_target = min(1.8, max(0.6, float(rules.get("shot_duration", 1.0))))
    burst_target = min(2.0 if talking_head else 5.0, max(1.2 if talking_head else 1.0, float(rules.get("burst_duration", 3.5))))
    min_score = float(rules.get("min_score", 2.5))
    allow_reuse = bool(rules.get("allow_reuse", False))
    profile_name = str(profile.get("name", ""))

    requests: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    used: set[str] = set()
    use_counts: dict[str, int] = {}
    last_topic_time: dict[str, float] = {}
    last_end = -100.0
    covered = 0.0
    planning_items: list[dict[str, Any]] = []
    if director_events:
        for event in director_events:
            timestamp = float(event.get("start", 0))
            nearest = min(scenes, key=lambda item: abs(float(item["start"]) - timestamp)) if scenes else {}
            planning_items.append({
                **nearest,
                "start": timestamp,
                "end": timestamp + float(event.get("duration", 2.5)),
                "text": event.get("text", nearest.get("text", "")),
                "importance": event.get("importance", nearest.get("importance", 0.0)),
                "visualImportance": event.get("visual_importance", nearest.get("visualImportance", 0.0)),
                "brollValue": event.get("broll_value", nearest.get("brollValue", 0.0)),
                "brollNecessity": event.get("broll_necessity", {}),
                "contentFormat": event.get("content_format", content_format),
                "directorQuery": event.get("search_terms", []),
                "directorTopic": event.get("topic", ""),
                "directorDuration": event.get("duration"),
                "directorSegmentId": event.get("segment_id"),
                "directorReason": event.get("reason"),
            })
    else:
        planning_items = list(scenes)
    for scene in sorted(planning_items, key=lambda item: float(item["start"])):
        if timeline_end <= 0:
            break
        raw_importance = float(scene.get("importance", 0))
        visual_importance = float(scene.get("visualImportance", scene.get("visual_importance", 0)))
        broll_value = float(scene.get("brollValue", scene.get("broll_value", 0)))
        importance = max(raw_importance, visual_importance * 0.9, broll_value)
        scene_type = str(scene.get("type", "NORMAL")).upper()
        start = float(scene["start"])
        query, concepts = _query(scene)
        local_tokens, local_concepts = _local_query(scene)
        in_end_zone = start >= end_zone_start
        cta_segment = _is_cta(scene)
        available = max(0.0, timeline_end - start)
        requested_duration = min(
            burst_target,
            max(1.0, float(scene.get("directorDuration") or (float(scene["end"]) - start + 1.8))),
            available,
        )
        necessity = dict(scene.get("brollNecessity", {}))
        pre_asset_necessity = float(scene.get("brollValue", scene.get("broll_value", 0.0)))
        topic = str(scene.get("directorTopic", scene_type)).lower()
        category_penalty = 0.14 if start - last_topic_time.get(topic, -100.0) < 14.0 else 0.0
        request: dict[str, Any] = {
            "time": round(start, 3), "end": round(start + requested_duration, 3),
            "sceneType": scene_type, "importance": round(importance, 3),
            "sourceImportance": round(raw_importance, 3),
            "visualImportance": round(visual_importance, 3),
            "brollValue": round(broll_value, 3),
            "text": scene.get("text", ""), "query": query, "concepts": sorted(concepts),
            "fallback": "CAMERA_PUNCH", "status": "UNRESOLVED", "matches": [],
            "segmentId": scene.get("directorSegmentId"),
            "directorReason": scene.get("directorReason"),
            "brollNecessity": necessity,
            "endZone": in_end_zone,
            "ctaSegment": cta_segment,
            "localQuery": sorted(local_tokens),
            "decisionStages": {
                "semantic_necessity": "PENDING", "local_asset_match": "PENDING",
                "editorial_suitability": "PENDING", "rhythm_and_density": "PENDING",
                "execution": "PENDING",
            },
        }
        if not query and not concepts:
            request["status"] = "SKIPPED_NO_SEMANTIC_QUERY"
            request["decisionStages"]["semantic_necessity"] = "REJECTED_NO_LOCAL_MEANING"
            requests.append(request)
            continue
        if importance < min_importance:
            request["status"] = "SKIPPED_LOW_IMPORTANCE"; request["decisionStages"]["semantic_necessity"] = "REJECTED"; requests.append(request); continue
        request["decisionStages"]["semantic_necessity"] = "PASSED"
        candidates = sorted(
            ((_score(
                asset, set(query), concepts, used, profile_name,
                allow_reuse=allow_reuse, use_counts=use_counts,
            ), asset) for asset in library["assets"]),
            key=lambda item: (-item[0], str(item[1].get("file", "")).lower()),
        )
        best_asset_score = max(0.0, candidates[0][0]) if candidates else 0.0
        asset_match = _bounded_score(best_asset_score / 9.0)
        best_asset = candidates[0][1] if candidates and candidates[0][0] >= 0 else None
        local_relevance = _local_asset_relevance(best_asset, local_tokens, local_concepts) if best_asset else 0.0
        final_necessity = _bounded_score(
            pre_asset_necessity * 0.62 + asset_match * 0.20 + local_relevance * 0.18 - category_penalty
        )
        visualizability = _bounded_score(float(necessity.get("visualizability", scene.get("visualImportance", 0.0))))
        # An insert must add local explanatory value, not merely have a file
        # whose tags resemble the global topic. Strong talking-head moments
        # carry a small replacement cost because the speaker remains primary.
        speaker_replacement_cost = 0.10 if talking_head and scene_type in {"HOOK", "HERO", "PUNCH"} else 0.04 if talking_head else 0.0
        insert_value = _bounded_score(
            final_necessity * 0.30 + local_relevance * 0.34
            + asset_match * 0.22 + visualizability * 0.14
            - category_penalty - speaker_replacement_cost
        )
        necessity.update({
            "asset_match": round(asset_match, 3), "category_repetition_penalty": round(category_penalty, 3),
            "local_semantic_relevance": round(local_relevance, 3),
            "visualizability": round(visualizability, 3),
            "speaker_replacement_cost": round(speaker_replacement_cost, 3),
            "insert_value": round(insert_value, 3),
            "insert_type": "semantic_broll",
            "end_zone": in_end_zone, "cta_segment": cta_segment,
            "final_score": round(final_necessity, 3),
        })
        request["brollNecessity"] = necessity
        request["assetCandidate"] = None if best_asset is None else {"id": best_asset.get("id"), "file": best_asset.get("file"), "score": round(best_asset_score, 3), "semanticGroups": best_asset.get("semanticGroups", []), "technicalValidity": best_asset.get("technicalValidity", {})}
        minimum_necessity = 0.72 if talking_head else 0.66
        if local_relevance < (0.45 if talking_head else 0.30):
            request["status"] = "SKIPPED_END_ZONE_CTA" if in_end_zone and cta_segment else "SKIPPED_LOCAL_MISMATCH"
            request["decisionStages"]["local_asset_match"] = "REJECTED_LOCAL_RELEVANCE"
            requests.append(request)
            continue
        request["decisionStages"]["local_asset_match"] = "PASSED"
        if insert_value < (0.70 if talking_head else 0.62):
            request["status"] = "SKIPPED_LOW_INSERT_VALUE"
            request["decisionStages"]["semantic_necessity"] = "REJECTED_INSERT_VALUE"
            requests.append(request)
            continue
        if final_necessity < minimum_necessity or asset_match < 0.58:
            request["status"] = "SKIPPED_LOW_NECESSITY" if asset_match >= 0.58 else "SKIPPED_NO_STRONG_ASSET"
            request["decisionStages"]["local_asset_match"] = "REJECTED_ASSET_OR_NECESSITY"
            requests.append(request)
            continue
        if in_end_zone:
            required_local = 0.84 if cta_segment else 0.72
            required_final = 0.90 if cta_segment else 0.86
            if local_relevance < required_local or asset_match < 0.82 or final_necessity < required_final:
                request["status"] = "SKIPPED_END_ZONE_CTA" if cta_segment else "SKIPPED_END_ZONE_LOW_RELEVANCE"
                request["decisionStages"]["editorial_suitability"] = "REJECTED_END_ZONE_THRESHOLD"
                requests.append(request)
                continue
        if scene_type in {"HOOK", "NUMBER", "HERO", "PUNCH", "CONTRAST"}:
            request["status"] = "SKIPPED_STRONG_TEXT_CONFLICT"; request["decisionStages"]["editorial_suitability"] = f"REJECTED_{scene_type}"; requests.append(request); continue
        if start < 3.0:
            request["status"] = "SKIPPED_HOOK_ZONE"; request["decisionStages"]["editorial_suitability"] = "REJECTED_HOOK_ZONE"; requests.append(request); continue
        nearby_strong = next((item for item in scenes if str(item.get("semanticRole", item.get("type", "NORMAL"))).upper() in {"HOOK", "HERO", "NUMBER", "PUNCH"} and float(item.get("start", 0)) - 0.45 < start + requested_duration and float(item.get("end", item.get("start", 0))) + 0.45 > start), None)
        if nearby_strong:
            request["status"] = "SKIPPED_NEAR_STRONG_TEXT"; request["decisionStages"]["editorial_suitability"] = "REJECTED_STRONG_NEIGHBOR"; requests.append(request); continue
        camera_conflict = next((item for item in (camera_actions or []) if float(item.get("time", 0)) < start + requested_duration and float(item.get("time", 0)) + max(0.25, float(item.get("duration", 0))) > start), None)
        if camera_conflict and (float(camera_conflict.get("strength", 0)) >= 0.62 or str(camera_conflict.get("effect", "")).upper() == "PUNCH_ZOOM"):
            request["status"] = "SKIPPED_CAMERA_CONFLICT"; request["decisionStages"]["editorial_suitability"] = "REJECTED_CAMERA_PUNCH"; requests.append(request); continue
        request["decisionStages"]["editorial_suitability"] = "PASSED"
        if len(events) >= max_bursts:
            request["status"] = "SKIPPED_EVENT_CAP"; request["decisionStages"]["rhythm_and_density"] = "REJECTED_MAX_EVENTS"; requests.append(request); continue
        if start - last_end < min_gap:
            request["status"] = "SKIPPED_BROLL_COOLDOWN"; request["decisionStages"]["rhythm_and_density"] = "REJECTED_MIN_GAP"; request["secondsSincePreviousBroll"] = round(start - last_end, 3); requests.append(request); continue
        request["decisionStages"]["rhythm_and_density"] = "PASSED"
        relative_min_score = max(min_score, candidates[0][0] * 0.65) if candidates else min_score
        shots: list[dict[str, Any]] = []
        cursor = 0.0
        for score, asset in candidates:
            if score < relative_min_score or cursor >= requested_duration - 0.1:
                continue
            target_shot = requested_duration if talking_head and not shots else shot_target
            duration = round(min(target_shot, float(asset["duration"]), requested_duration - cursor), 3)
            if duration < 0.5:
                continue
            focal = asset.get("focalPoint", {"x": 0.5, "y": 0.5})
            shots.append({
                "assetId": asset["id"], "file": asset["file"],
                "startFrom": _start_from(asset, duration, f"{scene.get('text', '')}|{asset['file']}"),
                "duration": duration, "score": score,
                "fit": "cover", "objectPosition": f"{float(focal.get('x', 0.5)) * 100:.1f}% {float(focal.get('y', 0.5)) * 100:.1f}%",
                "transition": "CUT", "motion": "SUBTLE_ZOOM",
            })
            cursor += duration
            if talking_head:
                break
        # When the library has one excellent semantic match, build a real burst
        # from different non-overlapping sections of that clip. This is preferable
        # to filling the block with unrelated assets merely to increase shot count.
        if not talking_head and len(shots) == 1 and requested_duration >= 2.4:
            primary = next((asset for score, asset in candidates if score >= relative_min_score), None)
            if primary is not None and float(primary["duration"]) >= 2.4:
                burst_available = min(requested_duration, float(primary["duration"]) - 0.05)
                rebuilt: list[dict[str, Any]] = []
                rebuilt_cursor = 0.0
                shot_index = 0
                while rebuilt_cursor < burst_available - 0.45 and shot_index < 4:
                    duration = round(min(shot_target, burst_available - rebuilt_cursor), 3)
                    if duration < 0.5:
                        break
                    focal = primary.get("focalPoint", {"x": 0.5, "y": 0.5})
                    rebuilt.append({
                        "assetId": primary["id"], "file": primary["file"],
                        "startFrom": round(rebuilt_cursor, 3), "duration": duration,
                        "score": candidates[0][0], "fit": "cover",
                        "objectPosition": f"{float(focal.get('x', 0.5)) * 100:.1f}% {float(focal.get('y', 0.5)) * 100:.1f}%",
                        "transition": "CUT",
                        "motion": ("SUBTLE_ZOOM", "PAN_LEFT", "PAN_RIGHT")[shot_index % 3],
                    })
                    rebuilt_cursor += duration
                    shot_index += 1
                if len(rebuilt) >= 3:
                    shots = rebuilt
                    cursor = round(rebuilt_cursor, 3)
        request["matches"] = [shot["assetId"] for shot in shots]
        if shots and covered + cursor <= timeline_end * max_coverage + 0.01:
            request["status"] = "MATCHED"
            request["decisionStages"]["execution"] = "MATCHED"
            event = {
                "type": "BROLL_BURST", "from": round(start, 3), "to": round(start + cursor, 3),
                "reason": scene.get("directorReason") or scene.get("text", ""), "query": query, "importance": round(importance, 3),
                "brollNecessity": necessity,
                "selectionDiagnostics": {
                    "localRelevance": round(local_relevance, 3), "assetMatch": round(asset_match, 3),
                    "insertValue": round(insert_value, 3), "semanticNecessity": round(final_necessity, 3),
                    "profile": profile_name, "minGap": round(min_gap, 3),
                    "reason": "local semantic explanation with validated asset and available rhythm budget",
                },
                "insertValue": round(insert_value, 3), "insertType": "SEMANTIC_BROLL",
                "audio": "KEEP_ORIGINAL", "fallback": "CAMERA_PUNCH", "shots": shots, "enabled": True,
                "segmentId": scene.get("directorSegmentId"), "topic": scene.get("directorTopic"),
            }
            events.append(event)
            covered += cursor
            last_end = start + cursor
            last_topic_time[topic] = start
            for asset_id in {str(shot["assetId"]) for shot in shots}:
                if not allow_reuse:
                    used.add(asset_id)
                use_counts[asset_id] = use_counts.get(asset_id, 0) + 1
        elif shots:
            request["status"] = "SKIPPED_COVERAGE_BUDGET"
            request["decisionStages"]["execution"] = "REJECTED_MAX_COVERAGE"
        else:
            request["status"] = "SKIPPED_NO_USABLE_SHOT"
            request["decisionStages"]["execution"] = "REJECTED_NO_USABLE_SHOT"
        requests.append(request)
    return {
        "version": 3, "library": library, "requests": requests, "events": events,
        "policy": {
            "scope": "semantic_block", "min_gap": round(min_gap, 3),
            "max_bursts": max_bursts, "duration_limit": duration_max,
            "content_format": content_format, "max_coverage": round(max_coverage, 3),
            "target_coverage": target_coverage,
            "actual_coverage": round(covered / max(0.1, timeline_end), 4),
            "end_zone_start": round(end_zone_start, 3),
            "end_zone_seconds": round(end_zone_seconds, 3),
            "end_zone_broll": "requires exceptional local semantic relevance",
            "automatic_insert_types": ["SEMANTIC_BROLL"],
            "editorial_cover": "requires explicit cut-cover request and strong local asset match",
            "decorative_insert": "disabled",
            "timing_authority": "director_execution_plan",
        },
    }


def plan_broll_bursts(
    scenes: list[dict[str, Any]], assets_dir: Path, profile: dict[str, Any], ffprobe: Path,
) -> list[dict[str, Any]]:
    """Compatibility wrapper for older integrations."""
    return build_broll_plan(scenes, assets_dir, profile, ffprobe)["events"]
