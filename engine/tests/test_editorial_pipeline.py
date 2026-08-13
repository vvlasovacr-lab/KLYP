from __future__ import annotations

import unittest

from shortsai.content_map import build_content_map
from shortsai.number_formatting import format_numeric_words
from shortsai.timeline_builder import build_timeline_plan
from shortsai.transcript_normalizer import normalize_transcript
from shortsai.transcription import Transcript, TranscriptSegment, TranscriptWord


def transcript_from_words(values: list[str]) -> Transcript:
    words = tuple(
        TranscriptWord(index * 0.4, (index + 1) * 0.4, value, 0.95)
        for index, value in enumerate(values)
    )
    return Transcript("ru", 1.0, len(values) * 0.4, (
        TranscriptSegment(0.0, len(values) * 0.4, " ".join(values), words),
    ))


class EditorialPipelineTests(unittest.TestCase):
    def test_transcript_normalizer_preserves_conversational_magnitude(self) -> None:
        source = transcript_from_words(["семьдесят", "тысяч", "рублей", "и", "один", "миллион"])
        result = normalize_transcript(source)
        words = [word.text for segment in result.transcript.segments for word in segment.words]
        self.assertEqual(["70", "тысяч", "рублей", "и", "1", "миллион"], words)
        self.assertNotIn("70 000", result.transcript.segments[0].text)

    def test_display_formatter_never_turns_magnitude_into_1000(self) -> None:
        words, _ = format_numeric_words([
            {"word": "70", "start": 0.0, "end": 0.2, "role": "ordinary"},
            {"word": "тысяч", "start": 0.2, "end": 0.5, "role": "ordinary"},
            {"word": "рублей", "start": 0.5, "end": 0.8, "role": "ordinary"},
        ], [])
        self.assertEqual("70 тысяч рублей", " ".join(item["word"] for item in words))

    def test_content_map_detects_paraphrased_argument_episode_wide(self) -> None:
        values = [
            "Чтобы", "заработать", "деньги,", "нужно", "научиться", "продавать.",
            "Главное", "в", "заработке", "—", "умение", "продавать,", "без", "продаж", "денег", "не", "будет.",
            "Поэтому", "начните", "практиковаться", "сегодня.",
        ]
        transcript = transcript_from_words(values)
        result = build_content_map(transcript, [{"source_start": 0.0, "source_end": transcript.duration}])
        decisions = [unit["decision"] for unit in result["units"]]
        self.assertTrue("TRIM" in decisions or "REPLACE_TAKE" in decisions)
        self.assertTrue(set(result["structure"]["functions"]) & {"CONCLUSION", "CTA"})

    def test_timeline_builder_contains_no_visual_decisions(self) -> None:
        content = {"units": [{
            "id": "content-001", "text": "Главная мысль", "narrative_function": "POINT",
            "decision": "KEEP", "editorial_output_coordinates": {"start": 0.0, "end": 1.0},
        }]}
        speech = {"output_duration": 1.0, "timeline": [{
            "source_start": 0.0, "source_end": 1.0, "output_start": 0.0, "output_end": 1.0,
            "speed": 1.0,
        }]}
        plan = build_timeline_plan(speech, content)
        self.assertEqual("TIMELINE_CONSTRUCTION", plan["layer"])
        self.assertNotIn("animation", plan["sequence"][0])
        self.assertNotIn("camera", plan)


if __name__ == "__main__":
    unittest.main()
