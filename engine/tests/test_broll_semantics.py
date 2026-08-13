from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shortsai.broll_library import build_broll_library
from shortsai.broll_planner import build_broll_plan
from shortsai.media import MediaInfo


def _profile() -> dict:
    return {
        "name": "AGGRESSIVE_RED",
        "broll": {
            "enabled": True, "min_importance": 0.56, "min_gap": 5.5,
            "max_bursts": 6, "max_coverage": 0.30, "burst_duration": 1.8,
        },
    }


def _credit_assets() -> dict:
    common = {
        "usable": True, "tags": ["кредит", "долг", "ставка", "проценты", "bank", "credit"],
        "semanticGroups": ["bank_credit_debt"], "orientation": "vertical", "height": 1920,
        "duration": 8.0, "importance": 0.9, "suitableStyles": [],
        "focalPoint": {"x": 0.5, "y": 0.5}, "technicalValidity": {"valid": True},
    }
    return {"assets": [
        {**common, "id": "credit-1", "file": "money/bank_credit_debt/banking_stress_01.mp4"},
        {**common, "id": "credit-2", "file": "money/bank_credit_debt/credit_statement_01.mp4"},
    ], "errors": []}


class BrollSemanticTests(unittest.TestCase):
    @patch("shortsai.broll_library.probe_media")
    def test_recursive_manifest_contains_enriched_machine_metadata(self, probe_mock) -> None:
        probe_mock.return_value = MediaInfo(
            file="clip.mp4", duration=4.0, width=1080, height=1920, fps=30.0,
            has_audio=False, video_codec="h264", audio_codec=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clip = root / "money" / "bank_credit_debt" / "banking_stress_01.mp4"
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"probe-is-mocked")
            manifest = build_broll_library(root, Path("ffprobe"))
            asset = manifest["assets"][0]
            self.assertEqual("money", asset["category"])
            self.assertEqual("bank_credit_debt", asset["subcategory"])
            self.assertIn("bank_credit_debt", asset["semanticGroups"])
            self.assertIn("person", asset["presence"])
            self.assertTrue(asset["technicalValidity"]["valid"])
            self.assertTrue((root / "broll_manifest.json").is_file())

    @patch("shortsai.broll_planner.build_broll_library")
    def test_local_credit_meaning_selects_real_asset_and_explains_decision(self, library_mock) -> None:
        library_mock.return_value = _credit_assets()
        scenes = [
            {"start": 5.0, "end": 7.0, "text": "кредитная ставка восемьдесят процентов", "type": "NORMAL", "importance": 0.95},
            {"start": 29.0, "end": 30.0, "text": "конец", "type": "NORMAL", "importance": 0.2},
        ]
        director = [{
            "start": 5.0, "duration": 1.8, "text": scenes[0]["text"], "importance": 0.95,
            "visual_importance": 0.90, "broll_value": 0.96, "content_format": "talking_head",
            "search_terms": ["кредит", "ставка", "долг"], "topic": "bank_credit_debt",
            "segment_id": "credit", "broll_necessity": {"visualizability": 0.9},
        }]
        plan = build_broll_plan(scenes, Path("assets"), _profile(), Path("ffprobe"), director_events=director)
        self.assertEqual(1, len(plan["events"]))
        self.assertEqual("MATCHED", plan["requests"][0]["status"])
        self.assertGreaterEqual(plan["events"][0]["selectionDiagnostics"]["localRelevance"], 0.45)
        self.assertIn("bank_credit_debt", plan["events"][0]["shots"][0]["file"])

    @patch("shortsai.broll_planner.build_broll_library")
    def test_camera_conflict_and_density_are_rejected_after_semantic_match(self, library_mock) -> None:
        library_mock.return_value = _credit_assets()
        scenes = [
            {"start": 5.0, "end": 6.8, "text": "кредитная ставка и долг", "type": "NORMAL", "importance": 0.95},
            {"start": 14.0, "end": 15.8, "text": "проценты по кредиту", "type": "NORMAL", "importance": 0.95},
            {"start": 29.0, "end": 30.0, "text": "конец", "type": "NORMAL", "importance": 0.2},
        ]
        director = [
            {"start": 5.0, "duration": 1.8, "text": scenes[0]["text"], "importance": 0.95, "visual_importance": 0.9, "broll_value": 0.95, "content_format": "talking_head", "search_terms": ["кредит"], "topic": "bank_credit_debt", "broll_necessity": {"visualizability": 0.9}},
            {"start": 14.0, "duration": 1.8, "text": scenes[1]["text"], "importance": 0.95, "visual_importance": 0.9, "broll_value": 0.95, "content_format": "talking_head", "search_terms": ["кредит"], "topic": "bank_credit_debt", "broll_necessity": {"visualizability": 0.9}},
        ]
        plan = build_broll_plan(
            scenes, Path("assets"), _profile(), Path("ffprobe"), director_events=director,
            camera_actions=[{"time": 5.0, "duration": 0.8, "effect": "PUNCH_ZOOM", "strength": 0.8}],
        )
        self.assertEqual("SKIPPED_CAMERA_CONFLICT", plan["requests"][0]["status"])
        self.assertEqual("PASSED", plan["requests"][0]["decisionStages"]["local_asset_match"])
        self.assertLessEqual(plan["policy"]["max_coverage"], 0.14)


if __name__ == "__main__":
    unittest.main()
