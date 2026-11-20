import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from export import store  # noqa: E402


class StoreTest(unittest.TestCase):
    def test_page(self):
        self.assertEqual([o["id"] for o in store.page(0, 3)], [1, 2, 3])
        self.assertEqual(len(store.page(20, 10)), 5)


if __name__ == "__main__":
    unittest.main()
