from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from shortsai.config import EditorialQualityConfig
from shortsai.editorial_quality import _internal_editorial_pass, _semantic_coverage, _word_boundary_alternatives, build_editorial_quality_plan
from shortsai.transcription import Transcript, TranscriptSegment, TranscriptWord


def source() -> Transcript:
    words = (
        TranscriptWord(0.0, 0.3, "Ну", 0.9), TranscriptWord(0.3, 0.8, "начнем.", 0.9),
        TranscriptWord(1.0, 1.35, "Почему", 0.95), TranscriptWord(1.35, 1.75, "это", 0.95),
        TranscriptWord(1.75, 2.2, "важно?", 0.95), TranscriptWord(3.0, 3.5, "Потому", 0.95),
        TranscriptWord(3.5, 4.0, "что", 0.95), TranscriptWord(4.0, 4.6, "работает.", 0.95),
    )
    return Transcript("ru", 0.99, 5.0, (TranscriptSegment(0.0, 4.6, " ".join(word.text for word in words), words),))


class FakeProbe:
    def __init__(self, *args, **kwargs) -> None: pass
    def close(self) -> None: pass
    def window(self, timestamp, config, before=False):
        readiness = 0.40 if timestamp < 0.9 else 0.82
        return {"available": True, "face_presence": 1.0, "visual_readiness": readiness, "first_frame_readiness": readiness, "gaze_readiness": readiness, "pose_stability": readiness, "frame_usability": readiness, "samples": []}


class PerformanceProbe:
    def __init__(self, short_glance: bool = False) -> None:
        self.short_glance = short_glance

    def frame(self, timestamp):
        weak = (0.8 <= timestamp <= 1.1) if self.short_glance else timestamp < 3.0
        quality = 0.05 if weak else 0.92
        return {
            "time": timestamp, "available": True, "face": True,
            "x": 0.5, "y": 0.35, "w": 0.2, "h": 0.2,
            "gaze_readiness": quality, "head_pose_readiness": quality,
            "downward_gaze_probability": 0.0, "eye_confidence": 0.9,
            "frame_usability": quality, "blur_score": 0.9,
        }


class EditorialQualityTests(unittest.TestCase):
    def test_internal_pass_prefers_equivalent_better_take(self) -> None:
        words = (
            TranscriptWord(0.0, 0.5, "Почему", 0.95), TranscriptWord(0.5, 1.0, "это", 0.95),
            TranscriptWord(1.0, 1.8, "важно?", 0.95), TranscriptWord(4.0, 4.5, "Почему", 0.95),
            TranscriptWord(4.5, 5.0, "это", 0.95), TranscriptWord(5.0, 5.8, "важно?", 0.95),
        )
        transcript = Transcript("ru", 0.99, 6.0, (TranscriptSegment(0, 5.8, "", words),))
        config = EditorialQualityConfig(
            internal_sample_step=0.3, sustained_bad_min_seconds=0.6,
            min_internal_performance=0.65, min_take_performance_gain=0.08,
        )
        result = _internal_editorial_pass(
            PerformanceProbe(), transcript,
            [{"source_start": 0.0, "source_end": 1.8}],
            [{"source_start": 0.0, "source_end": 1.8}], config,
        )
        self.assertEqual(result["summary"]["take_replacements"], 1)
        self.assertEqual(result["actions"][0]["type"], "REPLACE_TAKE")
        self.assertEqual(result["ranges"], [{"source_start": 4.0, "source_end": 5.8}])

    def test_short_natural_glance_does_not_create_cut(self) -> None:
        transcript = source()
        config = EditorialQualityConfig(
            internal_sample_step=0.3, sustained_bad_min_seconds=1.0,
            min_internal_performance=0.8,
        )
        result = _internal_editorial_pass(
            PerformanceProbe(short_glance=True), transcript,
            [{"source_start": 1.0, "source_end": 4.6}],
            [{"source_start": 1.0, "source_end": 4.6}], config,
        )
        self.assertFalse(any(item["type"] != "KEEP" for item in result["actions"]))

    def test_stable_intentional_off_camera_delivery_is_kept(self) -> None:
        transcript = source()
        metrics = {
            "performance_quality": 0.49, "sustained_off_camera": [{"start": 1.0, "end": 3.2, "duration": 2.2}],
            "sustained_downward_gaze": [], "speech_quality": 0.80, "semantic_completeness": 1.0,
            "delivery_confidence": 0.84, "pose_stability": 0.93, "frame_usability": 0.68,
            "motion_blur_quality": 0.92, "transition_risk": 0.20, "camera_engagement": 0.0,
            "head_pose_quality": 0.0, "gaze_quality": 0.0, "frame_stability": 0.93,
            "face_presence": 1.0, "sample_count": 5, "samples": [],
        }
        with patch("shortsai.editorial_quality._performance_quality", return_value=metrics):
            result = _internal_editorial_pass(
                PerformanceProbe(), transcript,
                [{"source_start": 1.0, "source_end": 4.6}],
                [{"source_start": 1.0, "source_end": 4.6}], EditorialQualityConfig(),
            )
        self.assertTrue(all(item["type"] == "KEEP" for item in result["actions"]))
        self.assertFalse(result["warnings"])
        self.assertIn("intentional visual/prop delivery", result["actions"][0]["reason"])

    def test_truncated_retake_has_lower_semantic_coverage(self) -> None:
        reference = "всего три причины почему реклама не приносит клиентов"
        complete = "три причины почему реклама не приносит клиентов"
        truncated = "три причины почему реклама не приносит"
        self.assertGreater(_semantic_coverage(reference, complete), _semantic_coverage(reference, truncated))

    def test_visual_word_trim_only_removes_low_value_opener(self) -> None:
        config = EditorialQualityConfig()
        words = [
            TranscriptWord(0.0, 2.4, "есть", 0.9), TranscriptWord(2.4, 2.8, "всего", 0.9),
            TranscriptWord(2.8, 3.2, "три", 0.9), TranscriptWord(3.2, 4.0, "причины.", 0.9),
        ]
        phrase = {"start": 0.0, "end": 4.0, "text": "есть всего три причины."}
        alternatives = _word_boundary_alternatives(phrase, words, config)
        self.assertEqual(len(alternatives), 1)
        self.assertEqual(alternatives[0]["start"], 2.4)
        self.assertEqual(alternatives[0]["removed_lead_words"], ["есть"])

        meaningful = {**phrase, "text": "почему всего три причины."}
        meaningful_words = [TranscriptWord(0.0, 2.4, "почему", 0.9), *words[1:]]
        self.assertFalse(_word_boundary_alternatives(meaningful, meaningful_words, config))

    def test_visual_lead_in_moves_only_to_complete_phrase_boundary(self) -> None:
        transcript = source()
        episode = {"episode_id": "episode-001", "selected_ranges": [{"source_start": 0.0, "source_end": 4.6}]}
        with patch("shortsai.editorial_quality._VisualProbe", FakeProbe):
            plan = build_editorial_quality_plan(Path("source.mp4"), transcript, episode, 5.0, EditorialQualityConfig())
        self.assertEqual(plan["editorial_boundary"]["in"], 1.0)
        self.assertEqual(plan["start"]["reason"], "VISUAL_NOT_READY")
        self.assertGreater(plan["start"]["after"]["start_readiness"], plan["start"]["before"]["start_readiness"])

    def test_single_ready_clip_is_conservative_for_visual_only_change(self) -> None:
        original = source()
        words = list(original.segments[0].words)
        words[0] = TranscriptWord(words[0].start, words[0].end, "Сегодня", words[0].probability)
        transcript = Transcript("ru", 0.99, 5.0, (TranscriptSegment(0.0, 4.6, " ".join(word.text for word in words), tuple(words)),))
        episode = {"episode_id": "episode-001", "selected_ranges": [{"source_start": 0.0, "source_end": 4.6}]}
        with patch("shortsai.editorial_quality._VisualProbe", FakeProbe):
            plan = build_editorial_quality_plan(Path("source.mp4"), transcript, episode, 5.0, EditorialQualityConfig(), conservative=True)
        self.assertEqual(plan["editorial_boundary"]["in"], 0.0)
        self.assertIn("START_QUALITY_WARNING", plan["warnings"])


if __name__ == "__main__":
    unittest.main()
