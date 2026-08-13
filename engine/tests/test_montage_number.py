from __future__ import annotations

import unittest

from shortsai.montage_plan import _number_parts


class MontageNumberCompositionTests(unittest.TestCase):
    def test_magnitude_stays_with_number_and_weak_auxiliary_is_removed(self) -> None:
        number, label = _number_parts([
            {"word": "было", "category": None},
            {"word": "70", "category": "number"},
            {"word": "тысяч", "category": "number"},
        ])
        self.assertEqual("70 тысяч", number)
        self.assertIsNone(label)

    def test_explanation_remains_secondary(self) -> None:
        number, label = _number_parts([
            {"word": "10", "category": "number"},
            {"word": "тысяч", "category": "number"},
            {"word": "это", "category": None},
            {"word": "4", "category": "number"},
            {"word": "нуля", "category": "number"},
        ])
        self.assertEqual("10 тысяч", number)
        self.assertEqual("это 4 нуля", label)


if __name__ == "__main__":
    unittest.main()
