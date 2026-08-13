from __future__ import annotations

import unittest

from shortsai.clip_visual_adapter import build_clip_visual_plan, normalize_renderer_mode


class ClipVisualAdapterTests(unittest.TestCase):
    def test_times_and_components_are_derived_from_execution_actions(self) -> None:
        execution = {
            "text_actions": [
                {"id": "text-a", "start": 1.25, "end": 2.0, "scene_type": "HERO", "motion": {"intensity": 0.9}},
                {"id": "text-b", "start": 4.75, "end": 5.4, "scene_type": "NUMBER", "motion": {"intensity": 0.8}},
            ],
            "broll_actions": [
                {"id": "broll-a", "from": 8.2, "to": 9.8, "importance": 0.7, "enabled": True},
            ],
        }
        profile = {
            "colors": {"text": "#fff", "accent": "#ffd000", "danger": "#f00"},
            "text": {"animation_speed": 1.1}, "effects": {"flash": True},
        }
        plan = build_clip_visual_plan(execution, profile, {"detected": True})
        self.assertEqual("TITLE_COMPOSITION", plan["sceneStyles"]["text-a"]["component"])
        self.assertEqual("NUMBER_STAMP", plan["sceneStyles"]["text-b"]["component"])
        self.assertEqual([1.25, 4.75], [item["time"] for item in plan["transitions"]])
        self.assertEqual(0, plan["summary"]["brollTransitions"])
        self.assertFalse(plan["brollPresentation"]["extendsEvent"])
        self.assertEqual("director_execution_plan", plan["brollPresentation"]["timingAuthority"])
        self.assertEqual("director_execution_plan", plan["source"])

    def test_disabled_broll_does_not_create_visual_transition(self) -> None:
        plan = build_clip_visual_plan(
            {"text_actions": [], "broll_actions": [{"id": "missing", "from": 3, "to": 4, "enabled": False}]},
            {}, {},
        )
        self.assertEqual([], plan["transitions"])

    def test_renderer_mode_is_strict_and_backward_compatible(self) -> None:
        self.assertEqual("legacy", normalize_renderer_mode(None))
        self.assertEqual("hybrid", normalize_renderer_mode("CLIP_HYBRID"))
        with self.assertRaises(ValueError):
            normalize_renderer_mode("experimental")

    def test_weak_hero_does_not_create_adapter_transition(self) -> None:
        plan = build_clip_visual_plan({
            "text_actions": [{
                "id": "weak-hero", "start": 4.0, "end": 5.0, "scene_type": "HERO",
                "motion": {"intensity": 0.8},
                "decision_scores": {"visual_importance": 0.42, "hook_strength": 0.0},
            }],
            "broll_actions": [],
        }, {}, {})
        self.assertEqual([], plan["transitions"])


if __name__ == "__main__":
    unittest.main()
