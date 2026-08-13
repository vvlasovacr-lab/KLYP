from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import WhisperConfig
from .speech_api import resolve_settings, transcribe_via_api


@dataclass(frozen=True)
class TranscriptWord:
    start: float
    end: float
    text: str
    probability: float


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...] = ()


@dataclass(frozen=True)
class Transcript:
    language: str
    language_probability: float
    duration: float
    segments: tuple[TranscriptSegment, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        return cls(
            language=str(data.get("language", "unknown")),
            language_probability=float(data.get("language_probability", 0.0)),
            duration=float(data.get("duration", 0.0)),
            segments=tuple(
                TranscriptSegment(
                    start=float(segment["start"]),
                    end=float(segment["end"]),
                    text=str(segment.get("text", "")),
                    words=tuple(
                        TranscriptWord(
                            start=float(word["start"]),
                            end=float(word["end"]),
                            text=str(word.get("text", word.get("word", ""))),
                            probability=float(word.get("probability", 0.0)),
                        )
                        for word in segment.get("words", [])
                    ),
                )
                for segment in data.get("segments", [])
            ),
        )


class Transcriber:
    """Распознавание речи: через API, если задан ключ, иначе локальной моделью.

    Оба пути возвращают один и тот же Transcript, поэтому остальной пайплайн
    не знает, откуда пришёл текст.
    """

    def __init__(self, config: WhisperConfig) -> None:
        self.config = config
        self._model: Any = None
        self._api = resolve_settings()
        self.provider = self._api["provider"] if self._api else f"faster-whisper/{config.model}"

    def _get_model(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as error:
                raise RuntimeError(
                    "Распознавать речь нечем: ключ SPEECH_API_KEY не задан, "
                    "а локальная модель faster-whisper не установлена. "
                    "Впиши ключ (console.groq.com/keys) — это и быстрее, и дешевле, "
                    "либо поставь пакет: pip install faster-whisper"
                ) from error
            self._model = WhisperModel(
                self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        return self._model

    def transcribe(self, video_path: Path) -> Transcript:
        if self._api is not None:
            try:
                return Transcript.from_dict(transcribe_via_api(video_path, self._api))
            except Exception as error:  # noqa: BLE001 — ролик важнее текста
                # Сеть отвалилась или ключ протух: ролик всё равно нужно
                # собрать, поэтому молча уходим на локальную модель.
                print(f"  распознавание через {self._api['provider']} не сработало: {error}")
                print("  перехожу на локальную модель")

        return self._by_local_model(video_path)

    def _by_local_model(self, video_path: Path) -> Transcript:
        segments, info = self._get_model().transcribe(
            str(video_path),
            language=self.config.language,
            beam_size=self.config.beam_size,
            word_timestamps=True,
        )
        materialized = tuple(
            TranscriptSegment(
                start=float(segment.start),
                end=float(segment.end),
                text=segment.text.strip(),
                words=tuple(
                    TranscriptWord(
                        start=float(word.start),
                        end=float(word.end),
                        text=word.word.strip(),
                        probability=float(word.probability),
                    )
                    for word in (segment.words or ())
                    if word.start is not None and word.end is not None and word.word.strip()
                ),
            )
            for segment in segments
            if segment.text.strip()
        )
        return Transcript(
            language=str(info.language),
            language_probability=float(info.language_probability),
            duration=float(info.duration),
            segments=materialized,
        )
