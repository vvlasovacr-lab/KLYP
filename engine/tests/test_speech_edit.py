from __future__ import annotations

import unittest

from shortsai.config import SpeechEditConfig
from shortsai.speech_edit import apply_speech_edit, build_speech_edit_plan


def word(text: str, start: float, end: float) -> dict[str, object]:
    return {"word": text, "start": start, "end": end}


class SpeechEditPlanTests(unittest.TestCase):
    def test_long_pause_keeps_natural_breath(self) -> None:
        plan = build_speech_edit_plan(
            [word("Это", 0.0, 0.2), word("важно.", 0.2, 0.5), word("Дальше", 1.5, 1.8)],
            1.9,
            SpeechEditConfig(preserve_speech_rate=True),
        ).to_dict()
        self.assertEqual(plan["cuts"][0]["type"], "REMOVE_SILENCE")
        self.assertAlmostEqual(plan["statistics"]["removedSilence"], 0.58, places=2)
        self.assertEqual(plan["statistics"]["jumpCuts"], 1)

    def test_connected_discourse_marker_is_not_removed(self) -> None:
        plan = build_speech_edit_plan(
            [word("Мы", 0.0, 0.2), word("короче", 0.24, 0.48), word("продолжаем", 0.52, 0.9)],
            1.0,
            SpeechEditConfig(preserve_speech_rate=True),
        ).to_dict()
        self.assertFalse(any(cut["type"] == "REMOVE_FILLER" for cut in plan["cuts"]))
        self.assertEqual(plan["contextual_keeps"][0]["reason"], "connected_to_sentence")

    def test_question_money_hook_scores_high(self) -> None:
        plan = build_speech_edit_plan(
            [
                word("Почему", 0.0, 0.2), word("ты", 0.2, 0.3), word("не", 0.3, 0.4),
                word("миллионер?", 0.4, 0.8),
            ],
            0.9,
            SpeechEditConfig(preserve_speech_rate=True),
        ).to_dict()
        self.assertEqual(plan["hook"]["level"], "HIGH")
        self.assertGreaterEqual(plan["hook"]["score"], 0.8)

    def test_zero_length_whisper_word_gets_renderable_interval(self) -> None:
        words = [word("И", 0.2, 0.2), word("вот", 0.2, 0.4)]
        plan = build_speech_edit_plan(words, 0.5, SpeechEditConfig(preserve_speech_rate=True))
        edited = apply_speech_edit(words, plan)
        self.assertGreater(edited[0]["end"], edited[0]["start"])
        self.assertAlmostEqual(edited[0]["source_start"], 0.2, places=3)


if __name__ == "__main__":
    unittest.main()
