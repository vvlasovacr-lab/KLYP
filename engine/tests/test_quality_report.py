from __future__ import annotations

import unittest

from shortsai.quality_report import build_quality_report


class QualityReportTests(unittest.TestCase):
    def test_overanimated_plan_scores_worse_than_controlled_retention_plan(self) -> None:
        base = {
            "output": {"duration": 30.0}, "styleProfile": {"name": "HIGH_RETENTION"},
            "speechEdit": {"hook": {"score": 0.85}}, "audio": {"enabled": True},
            "scenes": [
                {"start": 0.0, "end": 1.5, "type": "HERO", "semanticRole": "HOOK", "template": "STACKED_TEXT", "enabled": True},
                {"start": 14.0, "end": 15.0, "type": "NUMBER", "template": "NUMBER_HERO", "enabled": True},
            ],
            "camera": [{"time": 0.0, "duration": 1.0, "enabled": True}, {"time": 14.0, "duration": 0.7, "enabled": True}],
            "visual": [], "broll": [{"from": 7.0, "to": 10.0, "enabled": True}],
        }
        controlled = build_quality_report(base, {"integratedLufs": -14.0, "truePeak": -1.2}, finalized=True)
        overloaded_plan = dict(base)
        overloaded_plan["camera"] = [{"time": index * 0.5, "duration": 0.4, "enabled": True} for index in range(60)]
        overloaded = build_quality_report(overloaded_plan, {"integratedLufs": -14.0, "truePeak": -1.2}, finalized=True)
        self.assertGreater(controlled["effect_balance_score"], overloaded["effect_balance_score"])

    def test_balanced_plan_with_mastered_audio_scores_well(self) -> None:
        plan = {
            "output": {"duration": 20.0},
            "styleProfile": {"name": "VIRAL_SHORTS"},
            "speechEdit": {"hook": {"score": 0.9}},
            "audio": {"enabled": True},
            "scenes": [
                {"start": 0.0, "type": "HERO", "semanticRole": "HOOK", "template": "STACKED_TEXT", "enabled": True},
                {"start": 6.0, "type": "HERO", "template": "KEYWORD_HERO", "enabled": True},
                {"start": 12.0, "type": "NUMBER", "template": "NUMBER_HERO", "enabled": True},
                {"start": 17.0, "type": "ACCENT", "template": "PHRASE_BUILD", "enabled": True},
            ],
            "camera": [{"time": value, "enabled": True} for value in (0.0, 4.0, 8.0, 12.0, 16.0)],
            "visual": [{"time": 6.0, "enabled": True}],
            "broll": [{"from": 8.0, "to": 11.0, "enabled": True}],
        }
        report = build_quality_report(
            plan, {"integratedLufs": -14.1, "truePeak": -1.2}, finalized=True,
        )
        self.assertEqual("FINAL", report["status"])
        self.assertGreater(report["audio_score"], 0.95)
        self.assertGreater(report["final_score"], 0.75)
        self.assertEqual(
            {"CONTENT", "EDITORIAL", "TYPOGRAPHY", "VISUAL", "BROLL", "CAMERA", "AUDIO", "TECHNICAL"},
            set(report["quality_dimensions"]),
        )

    def test_visual_mismatch_and_bad_side_layout_reduce_quality(self) -> None:
        base = {
            "output": {"duration": 20.0}, "styleProfile": {"name": "PODCAST"},
            "speechEdit": {"hook": {"score": 0.8}}, "audio": {"enabled": True},
            "scenes": [
                {"start": 0.0, "end": 1.2, "type": "HERO", "semanticRole": "HOOK", "template": "STACKED_TEXT", "enabled": True},
                {"start": 4.0, "end": 5.2, "type": "ACCENT", "template": "SIDE_TEXT", "layout": {"position": "side_right", "sideLayout": {"valid": True, "estimatedLines": 2, "availableWidth": 0.36}}, "enabled": True},
            ],
            "camera": [{"time": 0.0, "duration": 1.0, "enabled": True}], "visual": [],
            "broll": [{"from": 8.0, "to": 9.6, "enabled": True, "brollNecessity": {"local_semantic_relevance": 0.9}}],
        }
        clean = build_quality_report(base, {"integratedLufs": -14.0, "truePeak": -1.2}, finalized=True)
        broken = {**base, "scenes": [*base["scenes"], {
            "start": 10.0, "end": 11.2, "type": "NORMAL", "template": "SIDE_TEXT",
            "layout": {"position": "side_right", "sideLayout": {"valid": False, "estimatedLines": 4, "availableWidth": 0.22}},
            "words": [{"word": value} for value in ("one", "two", "three", "four", "five")], "enabled": True,
        }], "broll": [{
            "from": 18.0, "to": 19.5, "enabled": True,
            "brollNecessity": {"local_semantic_relevance": 0.1},
        }]}
        report = build_quality_report(broken, {"integratedLufs": -14.0, "truePeak": -1.2}, finalized=True)
        penalties = report["metrics"]["visual_penalties"]
        self.assertEqual(1, penalties["broll_text_mismatch"])
        self.assertEqual(1, penalties["end_zone_broll"])
        self.assertEqual(1, penalties["awkward_side_layout"])
        self.assertEqual(1, penalties["vertical_text_stack"])
        self.assertGreater(clean["visual_polish_score"], report["visual_polish_score"])
        self.assertGreater(clean["final_score"], report["final_score"])


if __name__ == "__main__":
    unittest.main()
