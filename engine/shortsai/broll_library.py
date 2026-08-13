from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from .media import probe_media


SUPPORTED_BROLL = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})
INDEX_VERSION = 3


SEMANTIC_ONTOLOGY: dict[str, tuple[str, ...]] = {
    "bank_credit_debt": ("bank", "banking", "credit", "debt", "loan", "statement", "minimum_payment", "банк", "кредит", "долг", "займ", "ставка", "процент", "платеж"),
    "payment": ("payment", "contactless", "transfer", "invoice", "salary", "charges", "card", "оплата", "платеж", "перевод", "счет", "карта"),
    "money_loss": ("financial_problem", "budget", "expense", "stress", "burnout", "loss", "убыток", "потеря", "расход", "финансовая_проблема", "стресс"),
    "analytics": ("analytics", "metrics", "stats", "graph", "growth", "retention", "followers", "dashboard", "аналитика", "метрики", "статистика", "график", "рост", "удержание", "охват", "просмотры"),
    "content_creation": ("editing", "timeline", "camera", "recording", "script", "thumbnail", "content", "editor", "монтаж", "таймлайн", "камера", "съемка", "сценарий", "контент", "редактор"),
    "social_media": ("social", "scroll", "comments", "feed", "followers", "engagement", "соцсети", "скролл", "комментарии", "лента", "подписчики", "вовлеченность"),
    "community_chat": ("chat", "message", "reply", "reactions", "notifications", "community", "чат", "сообщение", "ответ", "реакции", "уведомления", "сообщество"),
    "business_work": ("business", "client", "customer", "sales", "team", "meeting", "presentation", "crm", "work", "бизнес", "клиент", "продажи", "команда", "встреча", "презентация", "работа"),
    "planning": ("planning", "planner", "calendar", "schedule", "notes", "whiteboard", "план", "календарь", "расписание", "заметки", "доска"),
    "success_growth": ("success", "growth", "revenue", "celebration", "positive", "handshake", "успех", "рост", "выручка", "победа", "результат"),
    "luxury": ("luxury", "premium", "watch", "business_class", "office", "wealth", "люкс", "премиум", "часы", "богатство"),
}

PRESENCE_TERMS: dict[str, tuple[str, ...]] = {
    "person": ("person", "people", "team", "client", "customer", "handshake", "discussion", "meeting", "stress", "frustrated", "человек", "люди", "команда"),
    "hands": ("hands", "handshake", "typing", "keyboard", "payment", "card", "phone", "mouse", "notes", "counting", "руки", "клавиатура"),
    "screen": ("screen", "dashboard", "timeline", "analytics", "metrics", "graph", "scroll", "crm", "editor", "экран", "график", "аналитика"),
    "phone": ("phone", "mobile", "contactless", "notifications", "телефон", "смартфон"),
    "laptop": ("laptop", "keyboard", "editor", "timeline", "ноутбук", "клавиатура"),
    "money": ("money", "cash", "salary", "revenue", "budget", "expense", "деньги", "наличные", "доход", "расход"),
    "charts": ("chart", "graph", "analytics", "metrics", "stats", "growth", "график", "аналитика", "метрики"),
    "chat": ("chat", "message", "reply", "comments", "reactions", "чат", "сообщение", "комментарии"),
    "payment": ("payment", "transfer", "invoice", "contactless", "card", "charges", "оплата", "перевод", "карта"),
}


def normalize_token(value: str) -> str:
    return value.lower().replace("ё", "е").strip()


def tokens(value: str | Iterable[str]) -> set[str]:
    text = value if isinstance(value, str) else " ".join(str(item) for item in value)
    return {
        normalize_token(token)
        for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё]+", text)
        if len(token) >= 2
    }


def _sidecar(path: Path) -> Path | None:
    candidates = (path.with_suffix(path.suffix + ".json"), path.with_suffix(".json"))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _metadata(path: Path) -> dict[str, Any]:
    sidecar = _sidecar(path)
    if sidecar is None:
        return {}
    value = json.loads(sidecar.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("B-roll sidecar must contain a JSON object")
    return value


def _contains(text: str, terms: Iterable[str]) -> bool:
    normalized = normalize_token(text).replace("-", "_")
    return any(normalize_token(term).replace("-", "_") in normalized for term in terms)


def _semantic_metadata(relative: str, metadata: dict[str, Any]) -> dict[str, Any]:
    path = Path(relative)
    parts = list(path.parts)
    category = parts[0] if len(parts) > 1 else str(metadata.get("category") or "general")
    subcategory = parts[1] if len(parts) > 2 else str(metadata.get("subcategory") or "general")
    source_text = " ".join((relative, path.stem.replace("_", " "), str(metadata.get("description", ""))))
    semantic_groups = [name for name, vocabulary in SEMANTIC_ONTOLOGY.items() if _contains(source_text, vocabulary) or name in relative.casefold()]
    expanded_tags = set(tokens(source_text))
    for group in semantic_groups:
        expanded_tags.add(group)
        expanded_tags.update(SEMANTIC_ONTOLOGY[group])
    presence = {
        name: {"present": _contains(source_text, vocabulary), "confidence": 0.78 if _contains(source_text, vocabulary) else 0.18, "source": "path_and_filename_prior"}
        for name, vocabulary in PRESENCE_TERMS.items()
    }
    stem = path.stem.casefold()
    frame_type = (
        "SCREEN_CLOSEUP" if any(term in stem for term in ("screen", "dashboard", "timeline", "scroll", "graph", "crm"))
        else "TOP_VIEW" if any(term in stem for term in ("topview", "desk", "notes", "keyboard"))
        else "PEOPLE_MEDIUM" if presence["person"]["present"]
        else "OBJECT_CLOSEUP" if any(value["present"] for key, value in presence.items() if key != "person")
        else "GENERAL_BROLL"
    )
    presumed_meaning = str(metadata.get("description") or " / ".join(semantic_groups) or path.stem.replace("_", " "))
    return {
        "category": category, "subcategory": subcategory,
        "presumedMeaning": presumed_meaning, "frameType": frame_type,
        "semanticGroups": semantic_groups, "semanticTags": sorted(expanded_tags),
        "presence": presence, "taggingMethod": "folder_prior+filename_ontology+sidecar",
    }


def library_signature(root: Path) -> list[dict[str, Any]]:
    """Stable cache fingerprint for clips and their optional sidecars."""
    if not root.is_dir():
        return []
    values: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or (path.suffix.lower() not in SUPPORTED_BROLL and not path.name.lower().endswith(".json")):
            continue
        if path.name.lower() in {"index.json", "broll_index.json", "broll_manifest.json"}:
            continue
        stat = path.stat()
        values.append({
            "file": path.relative_to(root).as_posix(),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        })
    return values


def build_broll_library(root: Path, ffprobe: Path, *, write_index: bool = True) -> dict[str, Any]:
    """Probe local B-roll files and create a deterministic searchable index."""
    root.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_BROLL),
        key=lambda item: item.as_posix().lower(),
    )
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            metadata = _metadata(path)
            media = probe_media(path, ffprobe)
            supplied_tags = metadata.get("tags", metadata.get("keywords", []))
            if isinstance(supplied_tags, str):
                supplied_tags = [supplied_tags]
            semantic = _semantic_metadata(relative, metadata)
            searchable = " ".join((relative, str(metadata.get("description", "")), str(metadata.get("category", ""))))
            asset_tags = sorted(tokens(searchable) | tokens(supplied_tags) | set(semantic["semanticTags"]))
            focal = metadata.get("focalPoint", metadata.get("focal_point", {"x": 0.5, "y": 0.5}))
            if not isinstance(focal, dict):
                focal = {"x": 0.5, "y": 0.5}
            x = min(1.0, max(0.0, float(focal.get("x", 0.5))))
            y = min(1.0, max(0.0, float(focal.get("y", 0.5))))
            orientation = "vertical" if media.height > media.width else "square" if media.height == media.width else "horizontal"
            stat = path.stat()
            category = str(metadata.get("category") or semantic["category"]).strip("./")
            subcategory = str(metadata.get("subcategory") or semantic["subcategory"]).strip("./")
            topic = str(metadata.get("topic") or (semantic["semanticGroups"][0] if semantic["semanticGroups"] else subcategory) or category or "general")
            emotion = str(metadata.get("emotion", "neutral"))
            suitable_styles = metadata.get("styles", metadata.get("suitableStyles", []))
            if isinstance(suitable_styles, str):
                suitable_styles = [suitable_styles]
            assets.append({
                "id": hashlib.sha1(relative.lower().encode("utf-8")).hexdigest()[:12],
                "file": relative, "absolutePath": str(path.resolve()), "filename": path.name,
                "duration": media.duration,
                "width": media.width,
                "height": media.height,
                "fps": media.fps,
                "orientation": orientation,
                "hasAudio": media.has_audio,
                "tags": asset_tags,
                "assetType": "broll_video",
                "description": str(metadata.get("description", semantic["presumedMeaning"])),
                "presumedMeaning": semantic["presumedMeaning"],
                "category": category, "subcategory": subcategory,
                "topic": topic,
                "frameType": semantic["frameType"],
                "semanticGroups": semantic["semanticGroups"],
                "semanticTags": semantic["semanticTags"],
                "presence": semantic["presence"],
                "taggingMethod": semantic["taggingMethod"],
                "emotion": emotion,
                "keywords": asset_tags,
                "suitableStyles": [str(value).upper() for value in suitable_styles],
                "importance": round(min(1.0, max(0.0, float(metadata.get("importance", 0.6)))), 3),
                "focalPoint": {"x": round(x, 3), "y": round(y, 3)},
                "usable": media.duration >= 0.5 and media.width >= 320 and media.height >= 320,
                "technicalValidity": {
                    "valid": media.duration >= 0.5 and media.width >= 320 and media.height >= 320,
                    "reason": "OK" if media.duration >= 0.5 and media.width >= 320 and media.height >= 320 else "duration_or_resolution_below_minimum",
                    "codec": media.video_codec, "hasAudio": media.has_audio,
                },
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            })
        except Exception as error:
            errors.append({"file": relative, "error": f"{type(error).__name__}: {error}"})
    index = {
        "version": INDEX_VERSION, "root": str(root.resolve()), "scanMethod": "recursive_filesystem_truth",
        "summary": {"files": len(paths), "validAssets": sum(item["usable"] for item in assets), "invalidAssets": sum(not item["usable"] for item in assets), "errors": len(errors), "categories": sorted({item["category"] for item in assets}), "subcategories": sorted({item["subcategory"] for item in assets})},
        "assets": assets, "errors": errors,
    }
    if write_index:
        (root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "broll_index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "broll_manifest.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index
