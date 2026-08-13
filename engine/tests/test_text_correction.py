from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from shortsai.text_correction import correct_transcript
from shortsai.transcription import Transcript, TranscriptSegment, TranscriptWord


class TextCorrectionTests(unittest.TestCase):
    def test_phrase_replacement_updates_timestamped_words(self) -> None:
        transcript = Transcript("ru", 1.0, 1.0, (
            TranscriptSegment(0.0, 1.0, "кредит калифобанка", (
                TranscriptWord(0.0, 0.4, "кредит", 0.8),
                TranscriptWord(0.4, 1.0, "калифобанка", 0.9),
            )),
        ))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrections.json"
            path.write_text(json.dumps({
                "words": {},
                "phrases": {"кредит калифобанка": "кредитка Альфа-Банка"},
            }, ensure_ascii=False), encoding="utf-8")
            corrected = correct_transcript(transcript, path)

        words = corrected.segments[0].words
        self.assertEqual([word.text for word in words], ["кредитка", "Альфа-Банка"])
        self.assertEqual(corrected.segments[0].text, "кредитка Альфа-Банка")
        self.assertEqual(words[0].start, 0.0)
        self.assertEqual(words[-1].end, 1.0)
        self.assertLess(words[0].end, words[1].end)


if __name__ == "__main__":
    unittest.main()
