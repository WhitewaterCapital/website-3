import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ee.sue import (
    compute_sue,
    estimate_stdev_from_surprises,
    MIN_SURPRISE_QUARTERS_FOR_STDEV,
    MIN_USABLE_STDEV,
)


class TestEstimateStdevFromSurprises(unittest.TestCase):
    def test_abstains_below_minimum_quarters(self):
        surprises = [0.02, -0.01, 0.03][: MIN_SURPRISE_QUARTERS_FOR_STDEV - 1]
        sd, reason = estimate_stdev_from_surprises(surprises)
        self.assertIsNone(sd)
        self.assertIn("trailing quarter", reason)

    def test_abstains_on_degenerate_near_zero_stdev(self):
        # Four (>= minimum) essentially-identical surprises -> stdev below
        # MIN_USABLE_STDEV -> must abstain rather than divide by it later.
        surprises = [0.10, 0.10, 0.10, 0.1001]
        sd, reason = estimate_stdev_from_surprises(surprises)
        self.assertIsNone(sd)
        self.assertIn("numerical-stability floor", reason)

    def test_computes_real_stdev_with_enough_dispersed_history(self):
        surprises = [0.10, -0.05, 0.20, -0.15, 0.08]
        sd, reason = estimate_stdev_from_surprises(surprises)
        self.assertIsNone(reason)
        self.assertIsNotNone(sd)
        self.assertGreater(sd, MIN_USABLE_STDEV)


class TestComputeSue(unittest.TestCase):
    def test_abstains_when_actual_missing_pre_print(self):
        # The dominant real-world case for this engine: every event it
        # exports is pre-print, so eps_actual is always None.
        sue, reason = compute_sue(eps_actual=None, eps_estimate=1.50, eps_estimate_stdev=0.10)
        self.assertIsNone(sue)
        self.assertIn("not yet reported", reason)

    def test_abstains_when_estimate_missing(self):
        sue, reason = compute_sue(eps_actual=1.60, eps_estimate=None, eps_estimate_stdev=0.10)
        self.assertIsNone(sue)
        self.assertIn("no consensus EPS estimate", reason)

    def test_abstains_when_stdev_missing(self):
        sue, reason = compute_sue(eps_actual=1.60, eps_estimate=1.50, eps_estimate_stdev=None)
        self.assertIsNone(sue)
        self.assertIn("stdev", reason)

    def test_computes_real_sue_when_all_inputs_present(self):
        sue, reason = compute_sue(eps_actual=1.60, eps_estimate=1.50, eps_estimate_stdev=0.10)
        self.assertIsNone(reason)
        self.assertAlmostEqual(sue, 1.0)

    def test_sign_reflects_beat_vs_miss(self):
        beat, _ = compute_sue(eps_actual=1.70, eps_estimate=1.50, eps_estimate_stdev=0.10)
        miss, _ = compute_sue(eps_actual=1.30, eps_estimate=1.50, eps_estimate_stdev=0.10)
        self.assertGreater(beat, 0)
        self.assertLess(miss, 0)


if __name__ == "__main__":
    unittest.main()
