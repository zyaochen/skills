import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from kvparse import parse, parse_line  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_line(self):
        self.assertEqual(parse_line("a=1; b = two ;c="), {"a": "1", "b": "two", "c": ""})

    def test_value_may_contain_equals(self):
        self.assertEqual(parse_line("expr=x=y"), {"expr": "x=y"})

    def test_text(self):
        self.assertEqual(parse("a=1\n\nb=2\n"), [{"a": "1"}, {"b": "2"}])


if __name__ == "__main__":
    unittest.main()
