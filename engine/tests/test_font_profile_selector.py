from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from shortsai.automated_pipeline import AutomatedPipeline
from shortsai.config import load_config
from shortsai.font_profile_selector import (
    load_font_library, resolve_profile_variant, select_font_profile,
)
from shortsai.jobs import JobContext
from shortsai.quality_report import build_quality_report
from shortsai.remotion_runner import RemotionRenderer
from shortsai.style_profiles import get_style_profile, merge_render_style
from shortsai.text_composition import validate_text_compositions


ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "assets" / "fonts"
PROFILES = ROOT / "font_profiles.json"


def decision(*, topic="money", format_name="talking_head", pace="fast", density=0.88, energy=0.75):
    return {
        "confidence": 0.84,
        "editParameters": {"textDensity": density},
        "contentAnalysis": {
            "topic": topic, "format": format_name,
            "delivery": {"pace": pace, "energyScore": energy},
        },
    }


class FontProfileSelectorTests(unittest.TestCase):
    def test_library_has_four_distinct_production_profiles(self) -> None:
        library = load_font_library(PROFILES)
        self.assertEqual({"SOCIAL_AGGRESSIVE", "SOCIAL_CLEAN", "PODCAST_PREMIUM", "MODERN_TECH"}, set(library))
        signatures = set()
        for profile_id, profile in library.items():
            variant = resolve_profile_variant(PROFILES, FONTS, profile_id, profile["default_variant"])
            signatures.add(tuple(variant["font_assets"][role]["relativePath"] for role in ("body", "display", "hero")))
        self.assertEqual(4, len(signatures))

    def test_style_and_content_mapping(self) -> None:
        aggressive = select_font_profile(PROFILES, FONTS, "AGGRESSIVE_SOCIAL", decision(), {"file": "a"})
        podcast = select_font_profile(PROFILES, FONTS, "PODCAST_PREMIUM", decision(format_name="podcast", pace="calm"), {"file": "b"})
        tech = select_font_profile(PROFILES, FONTS, "CLEAN_EXPERT", decision(topic="technology", format_name="education"), {"file": "c"})
        self.assertEqual("SOCIAL_AGGRESSIVE", aggressive["font_profile_id"])
        self.assertEqual("PODCAST_PREMIUM", podcast["font_profile_id"])
        self.assertEqual("MODERN_TECH", tech["font_profile_id"])

    def test_selection_and_variant_are_deterministic(self) -> None:
        value = decision(topic="expert", pace="calm", density=0.60, energy=0.3)
        first = select_font_profile(PROFILES, FONTS, "CLEAN_EXPERT", value, {"file": "same", "size": 10})
        second = select_font_profile(PROFILES, FONTS, "CLEAN_EXPERT", copy.deepcopy(value), {"size": 10, "file": "same"})
        self.assertEqual(first["seed"], second["seed"])
        self.assertEqual(first["variant_id"], second["variant_id"])
        self.assertEqual("MANROPE", first["variant_id"])

    def test_persisted_selection_wins_on_repeat_render(self) -> None:
        first = select_font_profile(PROFILES, FONTS, "CLEAN_EXPERT", decision(topic="expert"), {"file": "x"})
        persisted = {key: first[key] for key in ("font_profile_id", "variant_id", "seed")}
        repeated = select_font_profile(PROFILES, FONTS, "AGGRESSIVE_SOCIAL", decision(topic="money"), {"file": "changed"}, persisted)
        self.assertEqual(first["font_profile_id"], repeated["font_profile_id"])
        self.assertEqual(first["variant_id"], repeated["variant_id"])
        self.assertIn("persisted", repeated["selection_reason"])

    def test_job_manifest_persists_font_contract(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root / "video.mp4"; source.touch()
            job = JobContext.create(root / "work", source, mode="production", requested_profile="AUTO")
            selection = select_font_profile(PROFILES, FONTS, "AGGRESSIVE_SOCIAL", decision(), {"file": "video"})
            job.transition(
                "SPEECH_EDIT", style_profile="AGGRESSIVE_SOCIAL", style_confidence=0.84,
                font_profile=selection["font_profile_id"], font_variant=selection["variant_id"],
                body_font_file=selection["body_font_file"], display_font_file=selection["display_font_file"],
                hero_font_file=selection["hero_font_file"], font_fallbacks=0,
            )
            manifest = json.loads(job.paths.manifest.read_text(encoding="utf-8"))
            for key in ("style_profile", "style_confidence", "font_profile", "font_variant", "body_font_file", "display_font_file", "hero_font_file", "font_fallbacks"):
                self.assertIn(key, manifest)

    def test_role_mapping_is_fixed_for_entire_job(self) -> None:
        profile = resolve_profile_variant(PROFILES, FONTS, "SOCIAL_AGGRESSIVE", "PROVEN")
        role_map = profile["role_map"]
        self.assertEqual("body", role_map["NORMAL"])
        self.assertEqual("display", role_map["ACCENT"])
        self.assertEqual("display", role_map["CONTRAST"])
        self.assertTrue(all(role_map[role] == "hero" for role in ("HOOK", "HERO", "NUMBER", "PUNCH")))
        self.assertEqual(3, len({profile["font_assets"][role]["relativePath"] for role in ("body", "display", "hero")}))

    def test_unsupported_cyrillic_is_rejected(self) -> None:
        data = json.loads(PROFILES.read_text(encoding="utf-8"))
        data["BROKEN"] = copy.deepcopy(data["SOCIAL_AGGRESSIVE"])
        data["BROKEN"]["variants"]["PROVEN"]["font_assets"]["hero"]["relativePath"] = "hero/Anton/Anton-Regular.ttf"
        with TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rejected"):
                resolve_profile_variant(path, FONTS, "BROKEN", "PROVEN")

    def test_emergency_system_fallback_is_reported(self) -> None:
        config = load_config(ROOT / "config.json")
        renderer = RemotionRenderer(config)
        with TemporaryDirectory() as directory:
            runtime = renderer._stage_font_assets({"profileName": "BROKEN", "font": {}}, Path(directory), "jobs/test")
        self.assertEqual(1, runtime["fallback_count"])
        self.assertGreater(runtime["typography_qc_penalty"], 0)
        self.assertEqual("EMERGENCY_SYSTEM_FONT_FALLBACK", runtime["warnings"][0]["code"])

    def test_long_word_geometry_for_every_profile(self) -> None:
        config = load_config(ROOT / "config.json")
        pipeline = AutomatedPipeline(config)
        cases = [
            ("NORMAL", "NORMAL", "ПРЕДПРИНИМАТЕЛЬ"),
            ("ACCENT", "ACCENT_WORD", "ЭФФЕКТИВНОСТЬ"),
            ("HERO", "KEYWORD_HERO", "ДИСЦИПЛИНА"),
            ("NUMBER", "NUMBER_HERO", "70 ТЫСЯЧ ₽"),
        ]
        for profile_id, definition in load_font_library(PROFILES).items():
            for variant_id in definition["variants"]:
                font_profile = resolve_profile_variant(PROFILES, FONTS, profile_id, variant_id)
                style = {"name": "TEST", "fontProfile": font_profile, "fontSelection": {"font_profile_id": profile_id, "variant_id": variant_id, "font_fallbacks": 0}}
                metrics = pipeline._text_metrics(style)
                for role, template, text in cases:
                    scene = {"start": 0, "end": 2, "type": role, "semanticRole": role, "text": text, "words": [{"word": text, "role": "ordinary", "start": 0, "end": 1}], "emphasis": [], "template": template, "layout": {"position": "center_lower"}}
                    result = validate_text_compositions([scene], style, {"detected": False}, 1080, 1920, metrics)
                    self.assertEqual(0, result["violations_after"], f"{profile_id}/{variant_id}/{text}")
                    safety = scene["layout"]["compositionSafety"]
                    self.assertGreaterEqual(safety["edge_proximity"], 0)
                    self.assertGreaterEqual(safety["font_size"], 47 if role == "NORMAL" else 38)

    def test_quality_report_penalizes_declared_font_fallback(self) -> None:
        base = {
            "output": {"duration": 5, "width": 1080, "height": 1920, "fps": 30},
            "styleProfile": {"name": "TEST", "fontSelection": {"font_profile_id": "X", "variant_id": "Y", "font_fallbacks": 0}},
            "scenes": [], "camera": [], "visual": [], "sfx": [], "broll": [], "brollRequests": [],
        }
        clean = build_quality_report(base, finalized=False)
        broken = copy.deepcopy(base); broken["styleProfile"]["fontSelection"]["font_fallbacks"] = 1
        report = build_quality_report(broken, finalized=False)
        self.assertLess(report["final_score"], clean["final_score"])
        self.assertIn("font_role_fallback", report["warnings"])


if __name__ == "__main__":
    unittest.main()
