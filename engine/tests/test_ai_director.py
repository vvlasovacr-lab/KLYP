from __future__ import annotations

import unittest

from shortsai.ai_director import build_director_plan
from shortsai.director_profile_selector import select_director_profile
from shortsai.semantic_analysis import AnalyzedWord, EditingPlan, SceneType, TextScene


def scene(start: float, end: float, words: list[AnalyzedWord], importance: float) -> TextScene:
    return TextScene(
        start=start,
        end=end,
        scene_type=SceneType.NORMAL,
        text_template="PHRASE_BUILD",
        words=tuple(words),
        emphasis_words=(),
        importance_score=importance,
        emotion_score=0.24,
        recommended_zoom=1.0,
    )


class AIDirectorTests(unittest.TestCase):
    def test_retention_scores_and_broll_are_segment_scoped_and_limited(self) -> None:
        scenes = []
        for index in range(12):
            start = index * 3.0
            category = "money" if index % 2 == 0 else "result"
            word = "money." if category == "money" else "result."
            scenes.append(scene(
                start, start + 3.0,
                [AnalyzedWord(start, start + 3.0, word, category, 6)], 0.82,
            ))
        profile = {
            "name": "TEST",
            "scene": {"hero_min_importance": 0.72, "punch_min_importance": 0.9, "hero_cooldown": 7.0},
            "camera": {"subtle": 1.04, "strong": 1.1, "hero": 1.12},
            "broll": {"enabled": True, "min_importance": 0.56, "min_gap": 5.5, "max_bursts": 7, "shot_duration": 1.0},
        }
        director = build_director_plan(
            EditingPlan(tuple(scenes), ()), profile, {"profile": "TEST", "confidence": 1.0},
        )
        first_scores = director["segments"][0]["retention_scores"]
        self.assertEqual(
            {"hook_strength", "emotional_intensity", "information_value", "visual_importance", "assertion_strength", "semantic_change", "retention"},
            set(first_scores),
        )
        self.assertLessEqual(len(director["broll_events"]), 3)
        self.assertTrue(all(len(event["search_terms"]) <= 4 for event in director["broll_events"]))
        self.assertTrue(all("broll_necessity" in event for event in director["broll_events"]))
        self.assertTrue(all(event["broll_necessity"]["asset_match"] is None for event in director["broll_events"]))
        for previous, current in zip(director["broll_events"], director["broll_events"][1:]):
            previous_end = previous["start"] + previous["duration"]
            self.assertGreaterEqual(current["start"] - previous_end, director["decision_policy"]["broll_min_gap"])

    def test_auto_selects_aggressive_for_fast_money_conflict(self) -> None:
        words = (
            AnalyzedWord(0.0, 0.3, "Почему", None, 0),
            AnalyzedWord(0.3, 0.6, "теряешь", "problem", 5),
            AnalyzedWord(0.6, 0.9, "деньги", "money", 6),
            AnalyzedWord(0.9, 1.2, "миллион", "number", 7),
        )
        plan = EditingPlan((scene(0.0, 1.2, list(words), 0.9),), ())
        chunks = [
            {"word": word.text, "start": word.start, "end": word.end}
            for word in words
        ]
        decision = select_director_profile(plan, chunks, 1.2, "AUTO")
        self.assertEqual("AGGRESSIVE_SOCIAL", decision["profile"])
        self.assertTrue(decision["automatic"])
        self.assertGreaterEqual(decision["confidence"], 0.56)

    def test_number_requires_meaningful_numeric_context(self) -> None:
        weak_number = scene(
            4.0,
            5.0,
            [
                AnalyzedWord(4.0, 4.3, "два", "number", 7),
                AnalyzedWord(4.3, 5.0, "качества", "principle", 5),
            ],
            0.8,
        )
        plan = EditingPlan((
            scene(0.0, 1.0, [AnalyzedWord(0.0, 1.0, "Начало.", None, 0)], 0.7),
            weak_number,
        ), ())
        profile = {
            "name": "CLEAN_YELLOW",
            "scene": {"hero_min_importance": 0.9, "punch_min_importance": 0.95},
            "camera": {"subtle": 1.04, "strong": 1.1, "hero": 1.12},
            "broll": {"min_importance": 0.65, "shot_duration": 1.0},
        }
        director = build_director_plan(
            plan,
            profile,
            {"profile": "CLEAN_YELLOW", "confidence": 1.0},
        )
        self.assertNotEqual("NUMBER", director["segments"][1]["type"])
        self.assertNotEqual("NUMBER", director["text_events"][1]["scene_type"])

    def test_director_emits_renderer_independent_decisions(self) -> None:
        words = [
            AnalyzedWord(0.0, 0.4, "Почему", None, 0),
            AnalyzedWord(0.4, 0.8, "теряешь", "problem", 5),
            AnalyzedWord(0.8, 1.2, "деньги?", "money", 6),
        ]
        plan = EditingPlan((scene(0.0, 1.2, words, 0.92),), ())
        profile = {
            "name": "AGGRESSIVE_RED",
            "scene": {"hero_min_importance": 0.68, "punch_min_importance": 0.74},
            "camera": {"subtle": 1.05, "strong": 1.11, "hero": 1.14},
            "broll": {"min_importance": 0.56, "shot_duration": 0.8},
        }
        director = build_director_plan(
            plan,
            profile,
            {"profile": "AGGRESSIVE_RED", "confidence": 0.9},
        )
        self.assertEqual("HOOK", director["segments"][0]["type"])
        self.assertIn(director["text_events"][0]["scene_type"], {"HERO", "PUNCH"})
        self.assertTrue(director["camera_events"])
        self.assertIn("retention_reason", director["segments"][0])
        self.assertIn("visual_importance", director["segments"][0])


if __name__ == "__main__":
    unittest.main()
