from __future__ import annotations

import unittest

from shortsai.text_composition import validate_text_compositions


METRICS = {
    "font_size": 64, "accent_font_size": 80, "hero_font_size": 112, "punch_font_size": 132,
    "outline": 4, "shadow": 4, "horizontal_margin": 92, "top_margin": 96,
    "bottom_margin": 280, "animation_padding": 34, "minimum_side_width": 330,
    "minimum_font_scale": 0.78, "minimum_display_font_scale": 0.66, "maximum_side_lines": 2,
    "maximum_normal_lines": 2, "maximum_hero_lines": 3,
}


def scene(position: str, text: str) -> dict:
    words = [{"word": value, "role": "ordinary"} for value in text.split()]
    return {"start": 0.0, "end": 2.0, "type": "ACCENT", "semanticRole": "ACCENT", "text": text, "words": words, "emphasis": [0], "template": "SIDE_TEXT", "layout": {"position": position}}


class TextCompositionTests(unittest.TestCase):
    def test_long_word_reserves_motion_envelope_inside_safe_zone(self) -> None:
        value = {
            "start": 0.0, "end": 1.5, "type": "NORMAL", "semanticRole": "NORMAL",
            "text": "сверхпроизводительность",
            "words": [{"word": "сверхпроизводительность", "role": "ordinary"}],
            "emphasis": [], "template": "NORMAL", "layout": {"position": "center_lower"},
        }
        result = validate_text_compositions(
            [value], {"text": {}}, {"detected": False}, 1080, 1920, METRICS,
        )
        safety = value["layout"]["compositionSafety"]
        self.assertEqual(0, result["violations_after"])
        self.assertGreaterEqual(safety["edge_proximity"], 0)
        self.assertNotIn("animation_edge_violation", safety["violations_after"])

    def test_narrow_left_side_falls_back_as_complete_block(self) -> None:
        value = scene("side_left", "важная мысль без лесенки")
        face = {"detected": True, "samples": [{"time": 1.0, "x": 0.33, "y": 0.38, "w": 0.25, "h": 0.22}]}
        validate_text_compositions([value], {"text": {"allow_right_side": False}}, face, 1080, 1920, METRICS)
        safety = value["layout"]["compositionSafety"]
        self.assertNotEqual(value["layout"]["position"], "side_left")
        self.assertTrue(safety["fallback_applied"])
        self.assertFalse(safety["violations_after"])

    def test_right_and_left_edges_use_same_safe_margin(self) -> None:
        left = scene("side_left", "сильный акцент")
        right = scene("side_right", "сильный акцент")
        face_left = {"detected": True, "samples": [{"time": 1.0, "x": 0.25, "y": 0.38, "w": 0.18, "h": 0.20}]}
        face_right = {"detected": True, "samples": [{"time": 1.0, "x": 0.75, "y": 0.38, "w": 0.18, "h": 0.20}]}
        validate_text_compositions([right], {"text": {"allow_right_side": True}}, face_left, 1080, 1920, METRICS)
        validate_text_compositions([left], {"text": {"allow_right_side": True}}, face_right, 1080, 1920, METRICS)
        self.assertGreaterEqual(right["layout"]["compositionSafety"]["edge_proximity"], 0)
        self.assertGreaterEqual(left["layout"]["compositionSafety"]["edge_proximity"], 0)

    def test_three_word_hook_auto_fits_out_of_vertical_ladder(self) -> None:
        value = {
            "start": 0.0, "end": 1.8, "type": "HOOK", "semanticRole": "HOOK",
            "text": "почему большинство людей",
            "words": [{"word": word, "role": "ordinary"} for word in "почему большинство людей".split()],
            "emphasis": [1], "template": "STACKED_TEXT", "layout": {"position": "center_lower"},
        }
        result = validate_text_compositions([value], {"text": {}}, {"detected": False}, 1080, 1920, METRICS)
        safety = value["layout"]["compositionSafety"]
        self.assertEqual(result["violations_after"], 0)
        self.assertLessEqual(safety["line_count"], 2)
        self.assertLess(safety["font_scale"], 1.0)

    def test_four_word_hero_keeps_browser_headroom(self) -> None:
        value = {
            "start": 0.0, "end": 2.0, "type": "HERO", "semanticRole": "HERO",
            "text": "всего три причины почему",
            "words": [{"word": word, "role": "ordinary"} for word in "всего три причины почему".split()],
            "emphasis": [2], "template": "STACKED_TEXT", "layout": {"position": "center_lower"},
        }
        validate_text_compositions([value], {"text": {}}, {"detected": False}, 1080, 1920, METRICS)
        safety = value["layout"]["compositionSafety"]
        self.assertFalse(safety["violations_after"])
        self.assertLessEqual(safety["line_count"], 2)
        self.assertLess(safety["font_scale"], 1.0)

    def test_four_word_hook_uses_job_display_face_instead_of_vertical_ladder(self) -> None:
        value = {
            "start": 0.0, "end": 1.6, "type": "HOOK", "semanticRole": "HOOK",
            "text": "как кредит калифобанка год",
            "words": [{"word": word, "role": "ordinary"} for word in "как кредит калифобанка год".split()],
            "emphasis": [], "template": "STACKED_TEXT", "layout": {"position": "lower"},
        }
        metrics = {**METRICS, "typography_profiles": {
            "roles": {"HOOK": {"fontProfile": "hero", "maxLines": 2, "maxWidth": 0.8}},
            "display": {"minSize": 52, "maxSize": 104, "maxWidth": 0.8, "maxOvershoot": 1.12},
            "hero": {"minSize": 52, "maxSize": 126, "maxWidth": 0.8, "maxOvershoot": 1.12},
        }}
        result = validate_text_compositions([value], {"text": {}}, {"detected": False}, 1080, 1920, metrics)
        safety = value["layout"]["compositionSafety"]
        self.assertEqual(0, result["violations_after"])
        self.assertEqual("display", safety["font_profile"])
        self.assertLessEqual(safety["line_count"], 2)

    def test_temporal_face_envelope_moves_text_before_head_crossing(self) -> None:
        value = scene("center_lower", "важная мысль")
        face = {
            "detected": True,
            "samples": [
                {"time": 0.0, "x": 0.50, "y": 0.42, "w": 0.28, "h": 0.20},
                {"time": 1.0, "x": 0.46, "y": 0.57, "w": 0.36, "h": 0.25},
                {"time": 2.0, "x": 0.42, "y": 0.61, "w": 0.36, "h": 0.25},
            ],
        }
        result = validate_text_compositions([value], {"text": {}}, face, 1080, 1920, METRICS)
        safety = value["layout"]["compositionSafety"]
        self.assertEqual(result["violations_after"], 0)
        self.assertNotEqual(value["layout"]["position"], "center_lower")
        self.assertEqual(safety["face_overlap"], 0)
        self.assertEqual(value["layout"]["faceBox"]["method"], "temporal_face_envelope")


if __name__ == "__main__":
    unittest.main()
