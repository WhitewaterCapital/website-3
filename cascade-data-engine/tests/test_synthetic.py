import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cde.config import FUNDS, SYNTHETIC_CONSTITUENTS
from cde.synthetic import synthetic_snapshots


class TestSyntheticSnapshots(unittest.TestCase):
    def test_shape(self):
        holdings_df, flows, snapshots, typical_volume = synthetic_snapshots(date(2026, 9, 14))
        self.assertEqual(len(holdings_df), len(FUNDS) * len(SYNTHETIC_CONSTITUENTS))
        self.assertEqual(len(flows), len(FUNDS))
        self.assertEqual(len(snapshots), len(FUNDS))
        self.assertEqual(set(typical_volume), set(SYNTHETIC_CONSTITUENTS))

    def test_weights_sum_to_one_per_fund(self):
        holdings_df, *_ = synthetic_snapshots(date(2026, 9, 14))
        for ticker in (f.ticker for f in FUNDS):
            total = holdings_df[holdings_df["product"] == ticker]["weight"].sum()
            self.assertAlmostEqual(total, 1.0, places=9)

    def test_flows_are_nonzero_and_finite(self):
        import math

        _, flows, _, _ = synthetic_snapshots(date(2026, 9, 14))
        for f in flows:
            self.assertFalse(math.isnan(f.flow_dollars))
            self.assertNotEqual(f.flow_dollars, 0.0)

    def test_deterministic_on_fixed_seed(self):
        a = synthetic_snapshots(date(2026, 9, 14))
        b = synthetic_snapshots(date(2026, 9, 14))
        self.assertTrue(a[0].equals(b[0]))
        self.assertEqual([f.flow_dollars for f in a[1]], [f.flow_dollars for f in b[1]])
        self.assertEqual(a[3], b[3])


if __name__ == "__main__":
    unittest.main()
