from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shortsai.automated_pipeline import AutomatedResult
from shortsai.debug_inspector import build_director_debug, write_debug_inspector
from shortsai.discovery import discover_videos
from shortsai.evaluation import aggregate_report, run_batch_evaluation, write_batch_report
from shortsai.jobs import JobContext


class _Config:
    video_extensions = (".mp4", ".mov")


class _Pipeline:
    config = _Config()


class JobInfrastructureTests(unittest.TestCase):
    def test_job_paths_are_unique_and_unicode_safe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "исходник с пробелами.mp4"
            source.touch()
            first = JobContext.create(root / "work", source, mode="production", requested_profile="AUTO")
            second = JobContext.create(root / "work", source, mode="production", requested_profile="AUTO")
            self.assertNotEqual(first.job_id, second.job_id)
            self.assertNotEqual(first.paths.artifacts, second.paths.artifacts)
            self.assertTrue(first.paths.manifest.is_file())
            self.assertEqual(json.loads(first.paths.manifest.read_text(encoding="utf-8"))["status"], "CREATED")

    def test_batch_discovery_is_recursive_and_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z.mov").touch()
            (root / "nested").mkdir()
            (root / "nested" / "а video.MP4").touch()
            (root / "ignore.txt").touch()
            found = discover_videos(root, (".mp4", ".mov"))
            self.assertEqual(2, len(found))
            self.assertEqual(found, sorted(found, key=lambda path: str(path).lower()))

    def test_batch_continues_after_processor_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bad, good = root / "01_bad.mp4", root / "02_good.mp4"
            bad.touch(); good.touch()
            called: list[str] = []

            def processor(path: Path) -> AutomatedResult:
                called.append(path.name)
                if "bad" in path.name:
                    raise RuntimeError("forced safe failure")
                return AutomatedResult(str(path), path.stem, "success", True, "out.mp4", 1.0, 1, {}, 0.0)

            results, report = run_batch_evaluation(_Pipeline(), root, processor=processor)
            self.assertEqual(["01_bad.mp4", "02_good.mp4"], called)
            self.assertEqual(["failed", "success"], [item.status for item in results])
            self.assertEqual(1, report["failed"])
            self.assertEqual(1, report["completed"])

    def test_report_aggregation_and_html(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {"status": "success", "quality_score": 0.8, "broll_coverage": 0.1, "camera_actions": 4, "repeated_composition": 2},
                {"status": "failed", "quality_score": None, "broll_coverage": None, "camera_actions": None, "repeated_composition": None},
            ]
            report = aggregate_report(rows, root)
            json_path, html_path = write_batch_report(report, root / "report")
            self.assertEqual(0.8, report["averages"]["quality_score"])
            self.assertTrue(json_path.is_file())
            self.assertIn("ShortsAI Batch Evaluation", html_path.read_text(encoding="utf-8"))

    def test_debug_serialization_uses_real_actions_and_none(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "director_plan.json").write_text(json.dumps({
                "segments": [{"id": "s1", "start": 0, "end": 2, "text": "Сильная мысль", "type": "HERO", "decision_strength": 0.9}]
            }), encoding="utf-8")
            (root / "director_execution_plan.json").write_text(json.dumps({
                "text_actions": [{"segment_id": "s1", "start": 0, "end": 2, "template": "HERO", "scene_type": "HERO"}],
                "camera_actions": [], "broll_actions": [], "broll_requests": [], "visual_actions": [], "audio_actions": [],
            }), encoding="utf-8")
            debug = build_director_debug(root, job_id="job-1")
            self.assertEqual("SKIPPED", debug["timeline"][0]["broll_decision"])
            self.assertEqual("NONE", debug["timeline"][0]["camera_decision"])
            json_path, html_path = root / "director_debug.json", root / "debug.html"
            write_debug_inspector(debug, json_path, html_path)
            self.assertEqual("job-1", json.loads(json_path.read_text(encoding="utf-8"))["job_id"])
            self.assertTrue(html_path.is_file())


if __name__ == "__main__":
    unittest.main()
