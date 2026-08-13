"""Распознавание речи через внешний сервис вместо локальной модели.

Локальный faster-whisper бесплатен по деньгам, но держит полтора гигабайта
памяти и добавляет полторы минуты процессорного времени на каждый ролик.
На сервере, где рендер и так занимает все ядра, это дороже, чем запрос
к API за пару копеек.

Провайдер выбирается теми же переменными, что и в основном сервисе,
поэтому ключ вписывается один раз и работает в обеих половинах системы:

    SPEECH_PROVIDER=groq|openai|custom   (пусто или silence — локальная модель)
    SPEECH_API_KEY=...
    SPEECH_MODEL=...      необязательно, есть пресеты
    SPEECH_URL=...        необязательно, для своего сервиса
    SPEECH_LANG=ru

Ответ приводится к тому же Transcript, что отдаёт локальная модель,
поэтому дальше по пайплайну разницы нет.
"""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any
import urllib.error
import urllib.request
import uuid


PRESETS = {
    "openai": {
        "url": "https://api.openai.com/v1/audio/transcriptions",
        "model": "whisper-1",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/audio/transcriptions",
        "model": "whisper-large-v3-turbo",
    },
    "custom": {
        "url": "",
        "model": "whisper-1",
    },
}


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if isinstance(value, str) else ""
    return value or None


def resolve_settings() -> dict[str, Any] | None:
    """Настройки провайдера или None, если работаем локальной моделью."""
    provider = (_env("SPEECH_PROVIDER") or "").lower()
    api_key = _env("SPEECH_API_KEY")

    # auto: есть ключ — идём в сеть, нет — остаёмся на локальной модели
    if provider in ("", "auto"):
        provider = "openai" if api_key else "silence"
    if provider in ("silence", "local", "faster-whisper"):
        return None
    if not api_key:
        return None

    preset = PRESETS.get(provider, PRESETS["custom"])
    url = _env("SPEECH_URL") or preset["url"]
    if not url:
        return None

    return {
        "provider": provider,
        "url": url,
        "model": _env("SPEECH_MODEL") or preset["model"],
        "language": _env("SPEECH_LANG") or "ru",
        "api_key": api_key,
        "max_audio_mb": float(_env("SPEECH_MAX_AUDIO_MB") or 24),
    }


def _extract_audio(video: Path, ffmpeg: str = "ffmpeg") -> Path:
    """Моно-mp3 16 кГц: у распознавания лимит на размер запроса."""
    out = Path(tempfile.gettempdir()) / f"shortsai-speech-{uuid.uuid4().hex}.mp3"
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(video),
         "-vn", "-ac", "1", "-ar", "16000", "-b:a", "64k", str(out)],
        check=True,
    )
    return out


def _multipart(fields: list[tuple[str, str]], file_path: Path) -> tuple[bytes, str]:
    """Тело multipart/form-data вручную: сторонних библиотек в движке нет.

    Поля идут списком пар, а не словарём: timestamp_granularities[]
    передаётся дважды, и словарь второе значение потерял бы.
    """
    boundary = f"----shortsai{uuid.uuid4().hex}"
    line_break = b"\r\n"
    body = bytearray()

    for name, value in fields:
        body += f"--{boundary}".encode() + line_break
        body += f'Content-Disposition: form-data; name="{name}"'.encode() + line_break
        body += line_break
        body += str(value).encode() + line_break

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    body += f"--{boundary}".encode() + line_break
    body += (
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"'.encode()
        + line_break
    )
    body += f"Content-Type: {mime}".encode() + line_break + line_break
    body += file_path.read_bytes() + line_break
    body += f"--{boundary}--".encode() + line_break

    return bytes(body), f"multipart/form-data; boundary={boundary}"


def _request(settings: dict[str, Any], audio: Path) -> dict[str, Any]:
    fields = [
        ("model", settings["model"]),
        ("response_format", "verbose_json"),
        # Оба уровня: слова держат тайминги подсветки, сегменты — границы
        # фраз. Без второго сервис вернёт один кусок на весь ролик.
        ("timestamp_granularities[]", "word"),
        ("timestamp_granularities[]", "segment"),
    ]
    if settings["language"]:
        fields.append(("language", settings["language"]))

    body, content_type = _multipart(fields, audio)
    request = urllib.request.Request(
        settings["url"],
        data=body,
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": content_type,
            # Без своего User-Agent Cloudflare у Groq отвечает 403 (код 1010):
            # заголовок urllib по умолчанию попадает под фильтр ботов.
            "User-Agent": "ShortsAI/1.0",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"{settings['provider']} ответил {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"{settings['provider']} недоступен: {error.reason}") from error


def _words_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
    words = []
    for item in payload.get("words") or ():
        text = str(item.get("word") or item.get("text") or "").strip()
        start, end = item.get("start"), item.get("end")
        if text and start is not None and end is not None:
            words.append({"text": text, "start": float(start), "end": float(end),
                          "probability": float(item.get("probability", 1.0))})
    return _monotonic(_glue_hyphens(words))


def _glue_hyphens(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Склеивает слова, разорванные по дефису.

    Распознавание иногда отдаёт «кто» и «-нибудь» двумя кусками, и на экране
    они оказываются на разных кадрах: «Вот хоть кто» / «-нибудь, будете».
    Склеиваем обратно, время берём от первой части до последней.
    """
    glued: list[dict[str, Any]] = []

    for word in words:
        text = word["text"]
        previous = glued[-1] if glued else None
        # Склеиваем только настоящие половинки слова. Одиночное тире —
        # это знак препинания («было — стало»), а «-30%» — отрицательное
        # число; ни то, ни другое приклеивать к соседу нельзя.
        joins_back = (
            text.startswith("-")
            and len(text) > 1
            and not text[1:2].isdigit()
        )
        hangs_forward = (
            bool(previous)
            and previous["text"].endswith("-")
            and len(previous["text"].rstrip("-")) > 0
        )

        if previous and (joins_back or hangs_forward):
            previous["text"] = previous["text"].rstrip("-") + "-" + text.lstrip("-")
            previous["end"] = max(previous["end"], word["end"])
            continue

        glued.append(dict(word))

    return glued


def _monotonic(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Убирает наложения соседних слов.

    Распознавание отдаёт последнее слово фразы с хвостом, который залезает
    на первое слово следующей — обычно на пять сотых секунды. Дальше по
    пайплайну тайминги обязаны идти строго вперёд, иначе монтаж не соберётся.
    Подрезаем хвост предыдущего слова, а не сдвигаем следующее: сдвиг увёл бы
    подсветку с того момента, когда слово реально звучит.
    """
    for current, following in zip(words, words[1:]):
        if following["start"] < current["end"]:
            current["end"] = following["start"]
        # слово не может кончаться раньше, чем началось
        if current["end"] < current["start"]:
            current["end"] = current["start"]
    return words


def transcribe_via_api(video: Path, settings: dict[str, Any], ffmpeg: str = "ffmpeg") -> dict[str, Any]:
    """Возвращает словарь в формате Transcript.to_dict()."""
    audio = _extract_audio(video, ffmpeg)
    try:
        size_mb = audio.stat().st_size / 1048576
        if size_mb > settings["max_audio_mb"]:
            raise RuntimeError(
                f"Дорожка {size_mb:.1f} МБ больше лимита {settings['max_audio_mb']:.0f} МБ "
                f"у провайдера {settings['provider']}"
            )

        payload = _request(settings, audio)
        words = _words_from(payload)
        if not words:
            raise RuntimeError(f"{settings['provider']} не вернул ни одного слова")

        # Сегменты: берём готовые, если пришли, иначе режем по паузам —
        # дальше по пайплайну фразы всё равно пересобираются заново.
        raw_segments = payload.get("segments") or []
        segments: list[dict[str, Any]] = []

        if raw_segments:
            # Слово относим к сегменту по своей середине, а не по строгому
            # вхождению целиком: на стыках фраз слово выходит за границу,
            # и при строгой проверке терялось каждое шестое.
            bounds = [(float(s.get("start", 0)), float(s.get("end", 0))) for s in raw_segments]
            buckets: list[list[dict[str, Any]]] = [[] for _ in bounds]

            for word in words:
                middle = (word["start"] + word["end"]) / 2
                index = next(
                    (i for i, (start, end) in enumerate(bounds) if start <= middle <= end),
                    None,
                )
                if index is None:
                    # Слово в зазоре между сегментами — отдаём ближайшему.
                    index = min(
                        range(len(bounds)),
                        key=lambda i: min(abs(middle - bounds[i][0]), abs(middle - bounds[i][1])),
                    )
                buckets[index].append(word)

            for (start, end), segment, inside in zip(bounds, raw_segments, buckets):
                if not inside:
                    continue
                segments.append({
                    # Границы берём по словам: они точнее, чем у сегмента,
                    # и по ним потом режутся реплики на экране.
                    "start": min(start, inside[0]["start"]),
                    "end": max(end, inside[-1]["end"]),
                    "text": str(segment.get("text", "")).strip(),
                    "words": inside,
                })

            # Расширение по словам может наложить соседей друг на друга,
            # а дальше по пайплайну тайминги обязаны идти строго вперёд.
            # Подрезаем стык по границе первого слова следующей фразы.
            for current, following in zip(segments, segments[1:]):
                if current["end"] > following["start"]:
                    current["end"] = following["start"]
        else:
            current: list[dict[str, Any]] = []
            for word in words:
                if current and word["start"] - current[-1]["end"] > 0.45:
                    segments.append({
                        "start": current[0]["start"], "end": current[-1]["end"],
                        "text": " ".join(w["text"] for w in current), "words": list(current),
                    })
                    current = []
                current.append(word)
            if current:
                segments.append({
                    "start": current[0]["start"], "end": current[-1]["end"],
                    "text": " ".join(w["text"] for w in current), "words": list(current),
                })

        return {
            "language": str(payload.get("language") or settings["language"] or "ru"),
            "language_probability": 1.0,
            "duration": float(payload.get("duration") or (words[-1]["end"] if words else 0.0)),
            "segments": segments,
        }
    finally:
        audio.unlink(missing_ok=True)
