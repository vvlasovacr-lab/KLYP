from __future__ import annotations

from pathlib import Path
import unittest

from shortsai.style_profiles import get_style_profile, merge_render_style
from shortsai.montage_plan import _apply_composition_rhythm


ROOT = Path(__file__).resolve().parent.parent


class StyleProfileTests(unittest.TestCase):
    def test_legacy_aliases_resolve_to_canonical_profiles(self) -> None:
        path = ROOT / "style_profiles.json"
        self.assertEqual(get_style_profile(path, "MONEY")["name"], "CLEAN_YELLOW")
        self.assertEqual(get_style_profile(path, "AGGRESSIVE")["name"], "AGGRESSIVE_RED")

    def test_aggressive_profile_changes_typography(self) -> None:
        profile = get_style_profile(ROOT / "style_profiles.json", "AGGRESSIVE_RED")
        result = merge_render_style(
            {"fontSize": {"normal": 64, "accent": 80, "hero": 112, "punch": 132}, "outline": 4},
            profile,
        )
        self.assertEqual(result["colors"]["accent"], "#FF3434")
        self.assertGreater(result["fontSize"]["hero"], 112)
        self.assertGreater(result["animationSpeed"], 1.0)

    def test_new_retention_profiles_are_available(self) -> None:
        path = ROOT / "style_profiles.json"
        viral = get_style_profile(path, "VIRAL_SHORTS")
        cinematic = get_style_profile(path, "CINEMATIC")
        self.assertLess(viral["camera"]["min_gap"], cinematic["camera"]["min_gap"])
        self.assertGreater(cinematic["broll"]["burst_duration"], viral["broll"]["burst_duration"])

    def test_professional_profiles_resolve_external_resources(self) -> None:
        profile = get_style_profile(ROOT / "style_profiles.json", "HIGH_RETENTION")
        self.assertEqual(profile["font_profile"], "SOCIAL_AGGRESSIVE")
        self.assertIn("body", profile["fontProfile"])
        self.assertIn("POP", profile["motionPresets"])
        self.assertGreater(profile["visualProfile"]["contrast"], 1.0)

    def test_body_and_display_profiles_are_merged_independently(self) -> None:
        profile = get_style_profile(ROOT / "style_profiles.json", "HIGH_RETENTION")
        result = merge_render_style({"typographyProfiles": {}}, profile)
        body = result["typographyProfiles"]["body"]
        display = result["typographyProfiles"]["display"]
        self.assertLess(body["weight"], display["weight"])
        self.assertGreater(body["lineHeight"], display["lineHeight"])
        self.assertLess(body["maxSize"], display["maxSize"])

    def test_composition_cooldown_breaks_long_mechanical_runs(self) -> None:
        scenes = [{
            "start": float(index), "end": float(index + 1), "type": "NORMAL",
            "semanticRole": "NORMAL", "template": "PHRASE_BUILD", "text": "обычная мысль продолжается",
            "words": [
                {"word": word, "start": float(index) + word_index * 0.22, "end": float(index) + (word_index + 1) * 0.22}
                for word_index, word in enumerate("обычная мысль продолжается".split())
            ], "emphasis": [],
        } for index in range(10)]
        summary = _apply_composition_rhythm(scenes, {"visual_polish": {"composition_cooldown": 3}})
        maximum_run = 1
        current_run = 1
        for previous, current in zip(scenes, scenes[1:]):
            current_run = current_run + 1 if current["template"] == previous["template"] else 1
            maximum_run = max(maximum_run, current_run)
        self.assertLessEqual(maximum_run, 3)
        self.assertGreater(summary["semantic_alternative_switches"], 0)



if __name__ == "__main__":
    unittest.main()
