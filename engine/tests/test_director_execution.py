from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shortsai.broll_planner import build_broll_plan
from shortsai.director_execution import build_director_execution_plan


def profile() -> dict:
    return {
        "name": "AGGRESSIVE_RED",
        "colors": {"text": "#FFFFFF", "accent": "#FF3434", "danger": "#FF1F1F"},
        "camera": {"subtle": 1.055, "strong": 1.11, "hero": 1.14, "min_gap": 2.2},
        "broll": {"enabled": True, "min_importance": 0.56, "min_gap": 5.5},
        "effects": {"flash": True, "shake": "strong_only"},
        "text": {"side_text": "auto", "allow_right_side": True},
    }


class DirectorExecutionTests(unittest.TestCase):
    def build(self, face_x: float = 0.5) -> dict:
        director = {
            "version": 1,
            "segments": [
                {"id": "segment-01", "start": 0.0, "end": 1.5, "type": "HOOK", "importance": 0.9, "retention_score": 0.94, "retention_reason": "strong hook"},
                {"id": "segment-02", "start": 3.0, "end": 4.2, "type": "RESULT", "importance": 0.7, "retention_score": 0.78, "retention_reason": "result"},
                {"id": "segment-03", "start": 6.0, "end": 7.2, "type": "NUMBER", "importance": 0.9, "retention_score": 0.9, "retention_reason": "number"},
            ],
            "text_events": [
                {"start": 0.0, "end": 1.5, "text": "Почему не ты?", "scene_type": "HERO", "template": "STACKED_TEXT", "segment_id": "segment-01", "importance": 0.9, "color_role": "accent", "reason": "hook"},
                {"start": 3.0, "end": 4.2, "text": "Главный результат", "scene_type": "ACCENT", "template": "PHRASE_BUILD", "segment_id": "segment-02", "importance": 0.7, "color_role": "accent", "reason": "result"},
                {"start": 6.0, "end": 7.2, "text": "1 000 000", "scene_type": "NUMBER", "template": "NUMBER_HERO", "segment_id": "segment-03", "importance": 0.9, "color_role": "accent", "reason": "number"},
            ],
            "broll_events": [],
        }
        face = {
            "detected": True,
            "cropAnchor": {"x": face_x, "y": 0.36},
            "samples": [{"time": 3.0, "x": face_x, "y": 0.36, "w": 0.22, "h": 0.16}],
        }
        with tempfile.TemporaryDirectory() as directory:
            return build_director_execution_plan(
                director, profile(), {"output_duration": 8.0}, face,
                Path(directory), Path("ffprobe"),
            )

    def test_hook_number_and_semantic_camera_become_actions(self) -> None:
        execution = self.build()
        self.assertEqual(2, execution["version"])
        self.assertEqual("HOOK", execution["text_actions"][0]["scene_type"])
        self.assertEqual("NUMBER_HERO", execution["text_actions"][2]["template"])
        self.assertGreaterEqual(execution["camera_actions"][0]["scale"], 1.16)
        self.assertGreaterEqual(execution["summary"]["strong_text_actions"], 2)

    def test_face_on_left_places_accent_on_right(self) -> None:
        execution = self.build(face_x=0.30)
        accent = execution["text_actions"][1]
        self.assertEqual("side_right", accent["layout"]["position"])
        self.assertTrue(accent["layout"]["face_avoidance"])

    def test_side_text_falls_back_when_words_form_vertical_stack(self) -> None:
        execution = self.build(face_x=0.30)
        action = execution["text_actions"][1]
        action["text"] = "extraordinary transformation architecture"
        director = {
            "version": 2,
            "segments": [{"id": "segment-long", "start": 1.0, "end": 2.5, "type": "RESULT", "importance": 0.72, "retention_score": 0.76}],
            "text_events": [{"start": 1.0, "end": 2.5, "text": action["text"], "scene_type": "ACCENT", "segment_id": "segment-long", "importance": 0.72}],
            "broll_events": [],
        }
        face = {"detected": True, "samples": [{"time": 1.0, "x": 0.30, "y": 0.36, "w": 0.22, "h": 0.16}]}
        with tempfile.TemporaryDirectory() as directory:
            result = build_director_execution_plan(
                director, profile(), {"output_duration": 3.0}, face, Path(directory), Path("ffprobe"),
            )
        layout = result["text_actions"][0]["layout"]
        self.assertEqual("center_lower", layout["position"])
        self.assertFalse(layout["side_layout"]["valid"])
        self.assertGreater(layout["side_layout"]["estimated_lines"], 2)

    @patch("shortsai.broll_planner.build_broll_library")
    def test_final_cta_rejects_global_topic_broll(self, library_mock) -> None:
        library_mock.return_value = {"assets": [{
            "id": "money", "file": "money.mp4", "usable": True, "tags": ["money", "service", "value"],
            "orientation": "vertical", "height": 1920, "duration": 8.0, "importance": 0.9,
            "suitableStyles": [], "focalPoint": {"x": 0.5, "y": 0.5},
        }], "errors": []}
        scenes = [{"start": 18.0, "end": 20.0, "text": "subscribe to my channel", "type": "NORMAL", "importance": 0.9}]
        events = [{
            "start": 18.0, "duration": 2.0, "text": "subscribe to my channel", "importance": 0.9,
            "visual_importance": 0.9, "broll_value": 0.9, "content_format": "talking_head",
            "search_terms": ["money", "business"], "topic": "money", "segment_id": "cta",
            "broll_necessity": {"visualizability": 0.8},
        }]
        plan = build_broll_plan(scenes, Path("assets"), profile(), Path("ffprobe"), director_events=events)
        self.assertEqual([], plan["events"])
        self.assertEqual("SKIPPED_END_ZONE_CTA", plan["requests"][0]["status"])
        self.assertTrue(plan["requests"][0]["brollNecessity"]["end_zone"])

    def test_missing_sfx_library_disables_audio_without_failure(self) -> None:
        execution = self.build()
        self.assertTrue(execution["audio_actions"])
        self.assertTrue(all(not action["enabled"] for action in execution["audio_actions"]))
        self.assertEqual(0, execution["asset_summary"]["sfx_resolved"])

    def test_calm_segment_has_no_mechanical_camera_action(self) -> None:
        execution = self.build()
        calm_director = {
            "version": 2,
            "segments": [{
                "id": "segment-calm", "start": 0.0, "end": 4.0, "type": "NORMAL",
                "importance": 0.3, "retention_score": 0.28, "decision_strength": 0.27,
                "retention_scores": {
                    "hook_strength": 0.0, "emotional_intensity": 0.05, "information_value": 0.28,
                    "visual_importance": 0.24, "assertion_strength": 0.3, "semantic_change": 0.34,
                    "retention": 0.28,
                },
            }],
            "text_events": [{
                "start": 0.0, "end": 4.0, "text": "calm explanation", "scene_type": "NORMAL",
                "template": "PHRASE_BUILD", "segment_id": "segment-calm", "importance": 0.3,
                "color_role": "text", "reason": "supporting explanation",
            }],
            "broll_events": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            calm = build_director_execution_plan(
                calm_director, profile(), {"output_duration": 4.0}, {"detected": False},
                Path(directory), Path("ffprobe"),
            )
        self.assertEqual([], calm["camera_actions"])
        self.assertEqual(1, calm["summary"]["calm_segments"])

    def test_low_information_group_creates_semantic_speaker_rest(self) -> None:
        director = {
            "version": 2,
            "segments": [{
                "id": "segment-rest", "start": 6.0, "end": 9.0, "type": "NORMAL",
                "importance": 0.2, "retention_score": 0.2, "decision_strength": 0.2,
                "retention_scores": {"information_value": 0.2, "visual_importance": 0.22, "emotional_intensity": 0.1},
            }],
            "text_events": [
                {"start": 6.0, "end": 6.7, "text": "и вообще", "scene_type": "NORMAL", "segment_id": "segment-rest", "importance": 0.18},
                {"start": 6.7, "end": 8.1, "text": "основная спокойная мысль", "scene_type": "NORMAL", "segment_id": "segment-rest", "importance": 0.2},
                {"start": 8.1, "end": 9.0, "text": "вот так", "scene_type": "NORMAL", "segment_id": "segment-rest", "importance": 0.18},
            ],
            "broll_events": [],
        }
        face = {"detected": True, "samples": [{"time": 7.0, "x": 0.5, "y": 0.35, "w": 0.2, "h": 0.16}]}
        with tempfile.TemporaryDirectory() as directory:
            result = build_director_execution_plan(director, profile(), {"output_duration": 10.0}, face, Path(directory), Path("ffprobe"))
        states = [item["caption_state"] for item in result["text_actions"]]
        self.assertEqual(1, states.count("REDUCED_CAPTION"))
        self.assertEqual(2, states.count("SPEAKER_ONLY"))
        self.assertEqual(2, sum(not item["enabled"] for item in result["text_actions"]))

    def test_repeated_numeric_bridge_after_number_becomes_visual_rest(self) -> None:
        director = {
            "version": 2,
            "segments": [{
                "id": "segment-number", "start": 6.0, "end": 9.0, "type": "NUMBER",
                "importance": 0.8, "retention_score": 0.75, "decision_strength": 0.72,
                "retention_scores": {"information_value": 0.85, "visual_importance": 0.7},
            }],
            "text_events": [
                {"start": 6.0, "end": 7.1, "text": "70 тысяч", "scene_type": "NUMBER", "segment_id": "segment-number", "importance": 0.8},
                {"start": 7.1, "end": 8.2, "text": "жил на 70", "scene_type": "ACCENT", "segment_id": "segment-number", "importance": 0.7},
                {"start": 8.2, "end": 9.0, "text": "стало 100", "scene_type": "ACCENT", "segment_id": "segment-number", "importance": 0.75},
            ],
            "broll_events": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            result = build_director_execution_plan(
                director, profile(), {"output_duration": 10.0}, {"detected": True, "samples": []},
                Path(directory), Path("ffprobe"),
            )
        actions = result["text_actions"]
        self.assertEqual("STRONG_TYPOGRAPHY", actions[0]["caption_state"])
        self.assertEqual("SPEAKER_ONLY", actions[1]["caption_state"])
        self.assertFalse(actions[1]["enabled"])
        self.assertTrue(actions[2]["enabled"])

    def test_every_semantic_camera_action_has_a_baseline_return(self) -> None:
        execution = self.build()
        self.assertTrue(execution["camera_actions"])
        for action in execution["camera_actions"]:
            self.assertEqual(1.0, action["return_scale"])
            self.assertGreater(action["settle_duration"], 0)
            self.assertIn(action["motion_class"], {"CALM", "PUSH_IN", "PUNCH"})

    def test_visual_and_audio_actions_respect_global_cooldowns(self) -> None:
        tuned = profile()
        tuned["visual_polish"] = {
            "effect_cooldown": 5.5, "sfx_cooldown": 1.8,
            "same_sfx_cooldown": 6.0,
        }
        with patch("test_director_execution.profile", return_value=tuned):
            execution = self.build()
        visual_times = [float(item["time"]) for item in execution["visual_actions"]]
        audio_times = [float(item["time"]) for item in execution["audio_actions"]]
        self.assertTrue(all(right - left >= 5.5 for left, right in zip(visual_times, visual_times[1:])))
        self.assertTrue(all(right - left >= 1.8 for left, right in zip(audio_times, audio_times[1:])))


if __name__ == "__main__":
    unittest.main()
