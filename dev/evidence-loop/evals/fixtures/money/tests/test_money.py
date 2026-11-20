import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from ledger import total  # noqa: E402
from money import format_cents, round_cents  # noqa: E402


class RoundCentsTest(unittest.TestCase):
    def test_positive_half_rounds_up(self):
        self.assertEqual(round_cents(1125), 113)
        self.assertEqual(round_cents(125), 13)

    def test_negative_half_rounds_away_from_zero(self):
        self.assertEqual(round_cents(-1125), -113)
        self.assertEqual(round_cents(-125), -13)

    def test_format(self):
        self.assertEqual(format_cents(-113), "-1.13")
        self.assertEqual(total([100, -13]), 87)


if __name__ == "__main__":
    unittest.main()
