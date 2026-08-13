from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shortsai.automated_pipeline import AutomatedPipeline
from shortsai.config import load_config
from shortsai.font_inventory import LONG_WORDS, NUMBER_CASES, SfntFont, build_font_manifest, resolve_manifest_font
from shortsai.remotion_runner import RemotionRenderer
from shortsai.font_profile_selector import resolve_profile_variant
from shortsai.style_profiles import merge_render_style
from shortsai.text_composition import validate_text_compositions


ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"


class FontInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = build_font_manifest(FONTS)
        font_profile = resolve_profile_variant(
            ROOT / "font_profiles.json", FONTS, "SOCIAL_AGGRESSIVE", "PROVEN",
        )
        cls.profile = {
            "name": "AGGRESSIVE_SOCIAL", "font_profile": "SOCIAL_AGGRESSIVE",
            "fontProfile": font_profile, "fontSelection": {
                "font_profile_id": "SOCIAL_AGGRESSIVE", "variant_id": "PROVEN", "font_fallbacks": 0,
            },
        }

    def test_inventory_finds_real_files_and_rejects_incomplete_cyrillic(self) -> None:
        self.assertEqual(53, self.manifest["summary"]["total"])
        self.assertEqual(49, self.manifest["summary"]["cyrillic_supported"])
        records = {item["relative_path"]: item for item in self.manifest["fonts"]}
        self.assertEqual("CYRILLIC_UNSUPPORTED", records["hero/Anton/Anton-Regular.ttf"]["validation_status"])
        self.assertIn("₽", records["display/Russo One/RussoOne-Regular.ttf"]["missing_required_characters"])

    def test_selected_body_display_and_hero_files_are_valid(self) -> None:
        for role, asset in self.profile["fontProfile"]["font_assets"].items():
            path, record = resolve_manifest_font(FONTS, self.manifest, asset["relativePath"])
            self.assertIsNotNone(path, role)
            self.assertEqual("VALID_CYRILLIC", record["validation_status"])
            self.assertTrue(record["cyrillic_support"])

    def test_long_words_and_number_cases_have_real_glyph_advances(self) -> None:
        for asset in self.profile["fontProfile"]["font_assets"].values():
            font = SfntFont.open(FONTS / asset["relativePath"])
            for text in (*LONG_WORDS, *NUMBER_CASES):
                self.assertTrue(all(font.glyph_index(ord(character)) for character in text if character != " "))
                self.assertGreater(font.text_advance(text, 64), 20)

    def test_staging_uses_project_assets_without_windows_install(self) -> None:
        config = load_config(ROOT / "config.json")
        renderer = RemotionRenderer(config)
        base = json.loads((ROOT / "remotion/src/styles/config.json").read_text(encoding="utf-8"))
        style = merge_render_style(base, self.profile)
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            runtime = renderer._stage_font_assets(style, stage, "jobs/font-test")
            self.assertTrue(runtime["fonts"])
            self.assertTrue(all(not item["fallback_used"] for item in runtime["fonts"]))
            self.assertTrue(all((stage / "fonts" / Path(item["staged_src"]).name).is_file() for item in runtime["fonts"]))

    def test_actual_local_metrics_keep_regressions_inside_safe_area(self) -> None:
        config = load_config(ROOT / "config.json")
        metrics = AutomatedPipeline(config)._text_metrics(self.profile)
        cases = [
            ("NORMAL", "NORMAL", LONG_WORDS[0]),
            ("ACCENT", "ACCENT_WORD", LONG_WORDS[1]),
            ("HERO", "KEYWORD_HERO", LONG_WORDS[2]),
            ("HOOK", "STACKED_TEXT", f"{LONG_WORDS[3]} ДЛЯ КАЖДОГО"),
            *(("NUMBER", "NUMBER_HERO", value) for value in NUMBER_CASES),
        ]
        for role, template, text in cases:
            words = [
                {"word": word, "role": "strong_emphasis" if index == 0 and role != "NORMAL" else "ordinary", "start": index * 0.2, "end": (index + 1) * 0.2}
                for index, word in enumerate(text.split())
            ]
            scene = {
                "start": 0.0, "end": 2.0, "type": role, "semanticRole": role,
                "text": text, "words": words, "emphasis": [0] if role != "NORMAL" else [],
                "template": template, "layout": {"position": "center_lower"},
            }
            result = validate_text_compositions([scene], self.profile, {"detected": False}, 1080, 1920, metrics)
            safety = scene["layout"]["compositionSafety"]
            self.assertEqual(0, result["violations_after"], text)
            self.assertGreaterEqual(safety["edge_proximity"], 0, text)
            self.assertLessEqual(safety["line_count"], 2, text)


if __name__ == "__main__":
    unittest.main()
