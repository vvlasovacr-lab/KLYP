from __future__ import annotations

import unittest

from shortsai.raw_session import analyze_raw_session, build_episode_transcript
from shortsai.transcription import Transcript, TranscriptSegment, TranscriptWord


def transcript(parts: list[tuple[float, float, str]]) -> Transcript:
    segments = []
    for start, end, text in parts:
        values = text.split()
        step = (end - start) / max(1, len(values))
        words = tuple(
            TranscriptWord(start + index * step, start + (index + 1) * step, value, 0.94)
            for index, value in enumerate(values)
        )
        segments.append(TranscriptSegment(start, end, text, words))
    return Transcript("ru", 0.99, max((end for _, end, _ in parts), default=0), tuple(segments))


class RawSessionTests(unittest.TestCase):
    def test_short_ready_clip_is_not_split(self) -> None:
        value = transcript([(0.2, 4.0, "Почему важно работать над одной сильной идеей?"), (4.3, 9.5, "Так появляется настоящий результат.")])
        plan = analyze_raw_session(value, 10.0)
        self.assertEqual(plan["classification"], "SINGLE_READY_CLIP")
        self.assertEqual(len(plan["episodes"]), 1)
        self.assertEqual(plan["episodes"][0]["selected_ranges"], [{"source_start": 0.0, "source_end": 10.0}])

    def test_raw_session_uses_format_boundary_but_keeps_topic_continuity(self) -> None:
        value = transcript([
            (5.0, 7.0, "проверяем звук и настройка камеры."),
            (12.0, 22.0, "Почему люди не умеют откладывать деньги?"),
            (31.0, 42.0, "Зарплата растет, но расходы растут еще быстрее."),
            (49.0, 51.0, "Следующий вариант podcast."),
            (57.0, 70.0, "Нужно работать не больше, а точнее выбирать задачи."),
            (82.0, 96.0, "Тогда результат появляется без постоянной усталости."),
        ])
        plan = analyze_raw_session(value, 210.0)
        self.assertEqual(plan["classification"], "RAW_MULTI_TAKE_SESSION")
        self.assertEqual(len(plan["episodes"]), 2)
        self.assertTrue(any(item["classification"] == "NON_CONTENT" for item in plan["ranges"]))

    def test_episode_transcript_preserves_source_mapping(self) -> None:
        value = transcript([(10.0, 12.0, "первая мысль."), (20.0, 22.0, "вторая мысль.")])
        child, mapping, words = build_episode_transcript(value, [
            {"source_start": 10.0, "source_end": 12.0},
            {"source_start": 20.0, "source_end": 22.0},
        ])
        self.assertAlmostEqual(child.duration, 4.0)
        self.assertEqual(mapping[1]["episode_start"], 2.0)
        self.assertEqual(words[-1]["original_source_end"], 22.0)
        self.assertLessEqual(words[-1]["end"], 4.0)


if __name__ == "__main__":
    unittest.main()
