"""Stress suite: hard safety guarantees plus pinned expected outcomes."""
import collections
import unittest

from stress.cases import CASES
from stress.runner import outcome, violations


class StressSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {c["name"]: outcome(c) for c in CASES}

    def test_cases_are_well_formed(self):
        names = [c["name"] for c in CASES]
        self.assertEqual(len(names), len(set(names)))
        self.assertGreaterEqual(len(CASES), 80)
        for c in CASES:
            self.assertIn(c["truth"], ("stale", "ok"))
            self.assertIn(c["expect"], ("fixed", "review", "quiet"))
            self.assertEqual(c["gold"] is not None, c["expect"] == "fixed", c["name"])
            self.assertFalse(c["truth"] == "ok" and c["expect"] == "fixed", c["name"])

    def test_hard_guarantees(self):
        # Never edit or flag a correct doc as stale, never miss a stale doc,
        # and every fix must equal the hand-written correct text.
        failures = {n: v for c in CASES if (n := c["name"]) and (v := violations(c, self.results[n]))}
        self.assertEqual(failures, {})

    def test_pinned_outcomes(self):
        # Changing behaviour (even improving it) must update cases.py on purpose.
        drift = {c["name"]: (c["expect"], self.results[c["name"]]["status"]) for c in CASES if self.results[c["name"]]["status"] != c["expect"]}
        self.assertEqual(drift, {})

    def test_scorecard(self):
        counts = collections.Counter((c["truth"], self.results[c["name"]]["status"]) for c in CASES)
        self.assertEqual(counts[("ok", "fixed")], 0)
        self.assertEqual(counts[("stale", "quiet")], 0)


if __name__ == "__main__":
    unittest.main()
