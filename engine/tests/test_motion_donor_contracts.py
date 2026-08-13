from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MotionDonorContractsTest(unittest.TestCase):
    def test_production_does_not_import_research_sources(self) -> None:
        for path in (ROOT / "remotion" / "src").rglob("*.js*"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("research/motion_donors/sources", text)
            self.assertNotIn("degueba/onda", text)
            self.assertNotIn("reactvideoeditor/remotion-templates", text)

    def test_micro_shake_is_seeded_and_decays(self) -> None:
        motion = (ROOT / "remotion" / "src" / "effects" / "motion.js").read_text(encoding="utf-8")
        camera = (ROOT / "remotion" / "src" / "Camera.jsx").read_text(encoding="utf-8")
        self.assertIn("random(`shortsai-shake-x-", motion)
        self.assertIn("safeIntensity * settle", motion)
        self.assertIn("const decay = 1 - local / duration", camera)
        self.assertIn("random(`${seed}-x-${local}`)", camera)

    def test_controlled_blur_has_symmetric_settle(self) -> None:
        camera = (ROOT / "remotion" / "src" / "Camera.jsx").read_text(encoding="utf-8")
        self.assertIn("Math.sin(Math.PI * progress)", camera)


if __name__ == "__main__":
    unittest.main()
