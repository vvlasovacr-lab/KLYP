from __future__ import annotations

import copy
import unittest

from shortsai.reference_calibration import apply_candidate
from shortsai.reference_evidence import (
    aggregate_reference_priors, apply_candidate_v2, assess_plan_broll,
    build_broll_evidence, build_candidate_v2, composition_transition_analysis,
    evaluate_hypotheses, plan_behavior_profile, visual_behavior_profile,
)


def analysis(sequence=("NORMAL_TEXT", "NORMAL_TEXT", "ACCENT", "SPEAKER_ONLY"), *, text_coverage=.5, broll=False):
    duration = 8.0
    rhythm = []
    for index, role in enumerate(sequence):
        rhythm.append({"start": index * 2.0, "end": (index + 1) * 2.0, "state": role})
    scenes = [
        {"start": 0, "end": 2, "duration": 2, "role": "BODY", "position": "lower", "word_count": 3, "actual_text": "обычная фраза"},
        {"start": 2, "end": 4, "duration": 2, "role": "BODY", "position": "lower", "word_count": 3, "actual_text": "ещё одна фраза"},
        {"start": 4, "end": 5, "duration": 1, "role": "DISPLAY", "position": "center", "word_count": 1, "actual_text": "ВАЖНО"},
    ]
    inserts = [{"start": 5, "end": 6.5, "duration": 1.5, "presentation": "FULL_SCREEN", "burst": False}] if broll else []
    return {
        "version": 3, "duration": duration, "limitations": [],
        "typography": {"scenes": scenes, "summary": {"text_coverage": text_coverage}},
        "composition_rhythm": rhythm,
        "camera": {"events": [{"time": 3, "effect": "SUBTLE_PUSH", "scale_delta": .05, "duration": .3}, {"time": 4, "effect": "RECOVERY", "scale_delta": -.05, "duration": .3}], "summary": {"calm_coverage": .92}},
        "broll": {"events": inserts, "summary": {"coverage": .1875 if broll else 0}},
        "motion": {"events": [], "summary": {}}, "visual_rest": {"summary": {"coverage": .5, "median_duration": 2}},
        "sfx": {"summary": {"event_density": 0}}, "style": {"detected_style": "clean_expert", "style_confidence": .6},
    }


def plan():
    return {
        "output": {"duration": 8},
        "scenes": [
            {"start": 0, "end": 2, "type": "NORMAL", "semanticRole": "NORMAL", "text": "простая мысль", "importance": .2, "enabled": True},
            {"start": 2, "end": 4, "type": "HERO", "semanticRole": "HERO", "text": "ВАЖНО", "importance": .9, "enabled": True},
        ],
        "camera": [{"time": 2, "effect": "PUNCH_ZOOM", "strength": .8, "scale": 1.12, "enabled": True}],
        "execution": {"camera_actions": [{"time": 2, "effect": "PUNCH_ZOOM", "strength": .8, "scale": 1.12, "enabled": True}], "broll_actions": []},
        "brollRequests": [{"segmentId": "s1", "time": 1, "text": "покажу документ банка", "brollValue": .8, "brollNecessity": {"final_score": .8}}],
    }


class ReferenceEvidenceTests(unittest.TestCase):
    def test_composition_transition_analysis_preserves_normal_runs(self):
        result = composition_transition_analysis(analysis())
        self.assertIn("NORMAL", result["transition_matrix"])
        self.assertIn("NORMAL", result["transition_matrix"]["NORMAL"])
        self.assertEqual(result["normal_run_length"]["maximum"], 2)
        self.assertEqual(result["same_layout_strong_repeat"], 0)
        self.assertIn("neither is minimized", result["interpretation"])

    def test_visual_behavior_profile_contains_unified_density_camera_and_runs(self):
        profile = visual_behavior_profile("final/a", "FINAL_ONLY", "expert", analysis(), None)
        self.assertIn("normal_text_coverage", profile["text"])
        self.assertIn("transition_matrix", profile["composition"])
        self.assertIn("SUBTLE_PUSH", profile["camera"]["by_type"])
        self.assertFalse(profile["editorial_evidence_allowed"])
        self.assertIsNone(profile["composition"]["number_count"])

    def test_style_relative_statistics_have_iqr_and_reference_count(self):
        profiles = [visual_behavior_profile(f"r{i}", "FINAL_ONLY", "expert", analysis(text_coverage=.4 + i * .1), None) for i in range(3)]
        priors = aggregate_reference_priors(profiles, raw_pair_count=1)
        prior = next(item for item in priors["priors"] if item["style_cluster"] == "GLOBAL" and item["parameter"] == "text.coverage")
        self.assertEqual(prior["sample_count"], 3)
        self.assertIsNotNone(prior["observed"]["q1"])
        self.assertEqual(prior["confidence_level"], "MEDIUM")
        self.assertTrue(prior["candidate_usage_allowed"])
        self.assertFalse(prior["production_usage_allowed"])

    def test_low_evidence_prior_cannot_change_candidate(self):
        profile = visual_behavior_profile("only", "RAW_TO_FINAL", "paired", analysis(), None)
        priors = aggregate_reference_priors([profile], raw_pair_count=1)
        hypotheses = {"hypotheses": [{"hypothesis": "shortsai_text_density_too_high", "candidate_usage_allowed": True}]}
        base = plan(); behavior = plan_behavior_profile(base, 8)
        candidate = build_candidate_v2(priors, hypotheses, {"text_coverage": .9}, behavior, {"assessments": [], "summary": {}}, raw_pair_count=1)
        self.assertNotIn("target_text_coverage", candidate["parameters"])
        self.assertFalse(candidate["promotion_guard"]["allowed"])

    def test_final_only_never_creates_editorial_permission(self):
        profile = visual_behavior_profile("final/a", "FINAL_ONLY", "expert", analysis(), None)
        priors = aggregate_reference_priors([profile, copy.deepcopy(profile), copy.deepcopy(profile)], raw_pair_count=0)
        self.assertFalse(profile["editorial_evidence_allowed"])
        self.assertTrue(all(item["applicability"] == "OBSERVABLE_VISUAL_BEHAVIOR_ONLY" for item in priors["priors"]))

    def test_broll_asset_missing_is_distinct_from_low_confidence(self):
        profiles = [visual_behavior_profile(f"r{i}", "FINAL_ONLY", "expert", analysis(broll=True), None) for i in range(3)]
        for profile in profiles:
            event = profile["broll"]["events"][0]
            event["spoken_phrase"] = "покажу документ банка"
            event["semantic_features"] = {"visualizability": .9, "concreteness": .8, "entity_or_object_mentions": ["документ", "банк"], "action_or_process": ["покажу"], "proof_or_example": ["покажу"], "external_context": ["банк"], "emotional_function": [], "has_number": False}
        evidence = build_broll_evidence(profiles, [])
        assessed = assess_plan_broll(plan(), evidence, [])
        self.assertEqual(assessed["assessments"][0]["status"], "BROLL_WANTED_BUT_ASSET_MISSING")

    def test_candidate_v1_and_v2_are_isolated_from_before(self):
        before = plan(); original = copy.deepcopy(before)
        v1, _ = apply_candidate(before, {"parameters": {"target_text_coverage": .2}})
        v2_candidate = {"candidate_id": "v2", "parameters": {"target_text_coverage": .2, "rest_opportunity_threshold": .2}, "evidence_log": [{"parameter": "target_text_coverage", "prior": {"source_reference_ids": ["r1", "r2", "r3"], "confidence_level": "MEDIUM"}}], "broll_assessment": {"assessments": [], "summary": {}}}
        v2, log = apply_candidate_v2(before, v2_candidate)
        self.assertEqual(before, original)
        self.assertIsNot(v1, before); self.assertIsNot(v2, before)
        self.assertFalse(v2["referenceCalibrationV2"]["production_applied"])
        self.assertGreaterEqual(log["summary"]["count"], 1)

    def test_hypothesis_confidence_uses_support_and_contradiction(self):
        profiles = [visual_behavior_profile(f"r{i}", "FINAL_ONLY", "expert", analysis(), None) for i in range(4)]
        findings = evaluate_hypotheses(profiles, {"text_coverage": .95, "strong_typography_rate": 0, "camera_strength": .8, "visual_rest": .5, "broll_coverage": 0})
        text = next(item for item in findings["hypotheses"] if item["hypothesis"] == "shortsai_text_density_too_high")
        self.assertEqual(text["supporting_reference_count"], 4)
        self.assertEqual(text["confidence_level"], "MEDIUM")


if __name__ == "__main__":
    unittest.main()
