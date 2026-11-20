import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from lease import LeaseService, Store  # noqa: E402


class FenceTest(unittest.TestCase):
    def test_fresh_holder_can_write(self):
        svc, store = LeaseService(), Store()
        t = svc.acquire("a")
        self.assertTrue(store.write(t, "x"))
        self.assertEqual((store.value, store.token), ("x", t))

    def test_stale_holder_is_fenced_after_expire(self):
        svc, store = LeaseService(), Store()
        old = svc.acquire("a")
        svc.expire()
        new = svc.acquire("b")
        self.assertTrue(store.write(new, "fresh"))
        self.assertFalse(store.write(old, "stale"))
        self.assertEqual((store.value, store.token), ("fresh", new))

    def test_same_token_may_rewrite(self):
        svc, store = LeaseService(), Store()
        t = svc.acquire("a")
        store.write(t, "x")
        self.assertTrue(store.write(t, "y"))
        self.assertEqual(store.value, "y")


if __name__ == "__main__":
    unittest.main()
