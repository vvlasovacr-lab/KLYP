from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shortsai.reference_alignment import align_transcripts
from shortsai.reference_calibration import (
    aggregate_style_statistics, apply_candidate, build_calibration_candidate,
)
from shortsai.reference_manifest import discover_reference_dataset
from shortsai.transcription import Transcript, TranscriptSegment, TranscriptWord


def transcript(values):
    words = tuple(TranscriptWord(start, end, text, 0.95) for text, start, end in values)
    return Transcript("ru", 0.99, words[-1].end if words else 0, (TranscriptSegment(0, words[-1].end if words else 0, " ".join(item.text for item in words), words),))


def visual(value: float = 0.5):
    return {
        "typography": {"summary": {"text_coverage": value, "text_free_coverage": 1-value, "median_scene_duration": 1.0, "median_words_per_scene": 3, "hero_count": 2, "accent_count": 4}},
        "camera": {"summary": {"count": 5, "calm_coverage": 0.8}},
        "broll": {"summary": {"count": 2, "coverage": 0.1, "median_duration": 1.2}},
        "visual_rest": {"summary": {"coverage": 0.3}},
        "motion": {"summary": {"event_density": 0.08}},
        "sfx": {"summary": {"event_density": 0.04}},
    }


class ReferenceLayerTests(unittest.TestCase):
    def test_dataset_discovery_pairs_nested_media_and_final_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw_to_final/example_001/source.mp4/source-real.mp4"
            final = root / "raw_to_final/example_001/reference_final.mp4/final-real.mp4"
            final_only = root / "final_only/podcast/example.mp4"
            for path in (source, final, final_only):
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"media")
            fake = lambda path, ffprobe: {"file": str(path), "duration": 1, "resolution": {"width": 1080, "height": 1920}, "orientation": "vertical", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            with patch("shortsai.reference_manifest._media", side_effect=fake):
                manifest = discover_reference_dataset(root, Path("ffprobe"))
            self.assertEqual(manifest["summary"]["raw_to_final_pairs"], 1)
            self.assertEqual(manifest["summary"]["final_only"], 1)
            self.assertTrue(next(item for item in manifest["entries"] if item["reference_type"] == "RAW_TO_FINAL")["has_raw_source"])

    def test_missing_source_and_final_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "raw_to_final/example_002").mkdir(parents=True)
            manifest = discover_reference_dataset(root, Path("ffprobe"))
            self.assertEqual(manifest["entries"][0]["analysis_status"], "MISSING_SOURCE")

    def test_reference_discovery_never_modifies_source_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "raw_to_final/example_001/source.mp4"
            final = root / "raw_to_final/example_001/reference_final.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"immutable raw bytes")
            final.write_bytes(b"immutable final bytes")
            before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (source, final)}
            fake = lambda path, ffprobe: {"file": str(path), "duration": 1, "resolution": {"width": 1080, "height": 1920}, "orientation": "vertical", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            with patch("shortsai.reference_manifest._media", side_effect=fake):
                discover_reference_dataset(root, Path("ffprobe"))
            self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (source, final)})

    def test_semantic_alignment_reports_removed_words_without_invented_coordinates(self):
        raw = transcript([("мы", 0, .2), ("ну", .3, .5), ("делаем", .6, 1), ("монтаж", 1.1, 1.5)])
        final = transcript([("мы", 0, .2), ("делаем", .25, .6), ("монтаж", .65, 1)])
        result = align_transcripts(raw, final)
        removed = [item for item in result["segments"] if item["transformation_type"] == "FILLER_REMOVED"]
        self.assertEqual(len(removed), 1)
        self.assertIsNone(removed[0]["reference_start"])
        self.assertGreater(result["summary"]["reference_word_coverage"], .9)

    def test_final_only_statistics_keep_real_sample_count(self):
        report = aggregate_style_statistics([visual(.4), visual(.6), visual(.8)])
        self.assertEqual(report["sample_count"], 3)
        self.assertEqual(report["metrics"]["text_coverage"]["sample_count"], 3)
        self.assertEqual(report["metrics"]["text_coverage"]["median"], .6)

    def test_candidate_is_isolated_and_does_not_mutate_production_plan(self):
        plan = {"output": {"duration": 4}, "scenes": [{"start": 0, "end": 2, "type": "NORMAL", "text": "обычная фраза"}, {"start": 2, "end": 4, "type": "HERO", "text": "важно"}], "execution": {"camera_actions": [], "broll_actions": []}}
        original = copy.deepcopy(plan)
        candidate = {"parameters": {"target_text_coverage": .55}, "production_applied": False}
        after, changes = apply_candidate(plan, candidate)
        self.assertEqual(plan, original)
        self.assertFalse(after["calibration"]["production_applied"])
        self.assertGreater(changes["summary"]["count"], 0)

    def test_candidate_merges_only_adjacent_normal_text_in_same_semantic_segment(self):
        plan = {
            "output": {"duration": 5},
            "scenes": [
                {"start": 0, "end": 1, "type": "NORMAL", "semanticRole": "NORMAL", "text": "мы не", "words": [{"word": "мы"}, {"word": "не"}], "executionAction": {"segment_id": "a"}},
                {"start": 1.05, "end": 2, "type": "NORMAL", "semanticRole": "NORMAL", "text": "будем спешить", "words": [{"word": "будем"}, {"word": "спешить"}], "executionAction": {"segment_id": "a"}},
                {"start": 2.05, "end": 3, "type": "NORMAL", "semanticRole": "NORMAL", "text": "другая мысль", "words": [{"word": "другая"}, {"word": "мысль"}], "executionAction": {"segment_id": "b"}},
            ],
            "execution": {"camera_actions": [], "broll_actions": []},
        }
        after, _ = apply_candidate(plan, {"parameters": {"target_words_per_scene": 4.5}})
        self.assertEqual(len(after["scenes"]), 2)
        self.assertEqual(after["scenes"][0]["text"], "мы не будем спешить")
        self.assertEqual(after["scenes"][1]["text"], "другая мысль")

    def test_promotion_guard_requires_three_real_pairs(self):
        candidate = build_calibration_candidate([], {}, {}, raw_pair_count=1, visual_reference_count=4)
        self.assertFalse(candidate["promotion_guard"]["allowed"])
        self.assertFalse(candidate["production_applied"])

    def test_candidate_is_reproducible(self):
        comparisons = [{"metric": "text_coverage", "reference": .5, "shortsai_before": .9, "classification": "LIKELY_IMPROVEMENT", "confidence": .72, "significant": True}]
        first = build_calibration_candidate(comparisons, {}, {}, raw_pair_count=1, visual_reference_count=4)
        second = build_calibration_candidate(comparisons, {}, {}, raw_pair_count=1, visual_reference_count=4)
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(first["parameters"], second["parameters"])


if __name__ == "__main__":
    unittest.main()
