"""Tests for kf/cointegration.py — the required synthetic known-relationship
recovery check (mirrors quant-infra/cascade/tests/test_transmission.py's
"recovers known coefficient" pattern), plus the honest-abstention check on
genuinely non-cointegrated series."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kf.cointegration import engle_granger_test, ols_regress, adf_test_statistic

TRUE_INTERCEPT = 0.35
TRUE_HEDGE_RATIO = 0.72


def _cointegrated_pair(n=300, phi=0.8, spread_sigma=0.01, seed=7):
    """y2 a random walk (I(1)); y1 = a + b*y2 + stationary AR(1) spread —
    genuinely cointegrated by construction with a KNOWN hedge ratio."""
    rng = np.random.default_rng(seed)
    y2 = np.cumsum(rng.normal(0.0002, 0.015, n))
    spread = np.empty(n)
    spread[0] = rng.normal(0, spread_sigma / np.sqrt(1 - phi ** 2))
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + rng.normal(0, spread_sigma)
    y1 = TRUE_INTERCEPT + TRUE_HEDGE_RATIO * y2 + spread
    return y1, y2


def _independent_walks(n=300, seed=11):
    rng = np.random.default_rng(seed)
    y1 = np.cumsum(rng.normal(0.0003, 0.02, n))
    y2 = np.cumsum(rng.normal(-0.0001, 0.018, n))
    return y1, y2


class TestOLSRecoversKnownHedgeRatio(unittest.TestCase):
    def test_recovers_known_coefficient_within_tolerance(self):
        y1, y2 = _cointegrated_pair()
        result = ols_regress(y1, y2)
        # documented tolerance: within 5% relative or 0.03 absolute, whichever looser
        self.assertAlmostEqual(result.slope, TRUE_HEDGE_RATIO, delta=max(0.05 * TRUE_HEDGE_RATIO, 0.03))
        self.assertAlmostEqual(result.intercept, TRUE_INTERCEPT, delta=0.1)
        self.assertGreater(result.r_squared, 0.9)
        self.assertEqual(result.n_obs, 300)


class TestADFRejectsUnitRootOnStationarySeries(unittest.TestCase):
    def test_ar1_series_rejects_unit_root(self):
        rng = np.random.default_rng(3)
        n = 300
        phi = 0.7
        x = np.empty(n)
        x[0] = 0.0
        for t in range(1, n):
            x[t] = phi * x[t - 1] + rng.normal(0, 0.5)
        adf = adf_test_statistic(x, max_lag=6)
        # A genuinely stationary AR(1) with phi=0.7 should give a strongly
        # negative ADF statistic -- well past even the 1% critical value.
        self.assertLess(adf.t_stat, -3.9)

    def test_pure_random_walk_does_not_reject_unit_root(self):
        rng = np.random.default_rng(4)
        n = 300
        x = np.cumsum(rng.normal(0, 0.5, n))
        adf = adf_test_statistic(x, max_lag=6)
        # A genuine unit-root series should NOT produce a t-stat past the 5%
        # critical value -- this is a probabilistic claim (Type I error rate
        # is 5% by construction), so this uses a fixed seed known to pass,
        # same discipline as this repo's other seeded statistical tests.
        self.assertGreater(adf.t_stat, -3.3377)


class TestEngleGrangerDetectsKnownCointegration(unittest.TestCase):
    def test_detects_cointegration_and_recovers_hedge_ratio(self):
        y1, y2 = _cointegrated_pair()
        result = engle_granger_test("Y1", "Y2", y1, y2, significance=0.05, max_lag=8)
        self.assertTrue(result.is_cointegrated, msg=result.reason)
        self.assertAlmostEqual(result.hedge_ratio, TRUE_HEDGE_RATIO, delta=0.1)
        self.assertLess(result.adf_t_stat, result.critical_value_used)

    def test_stronger_mean_reversion_gives_more_negative_adf_stat(self):
        # A lower phi (faster mean reversion in the spread) should be an
        # EASIER cointegration case to detect -- sanity-checks the test's
        # own directional logic, not just a single pass/fail.
        y1_slow, y2_slow = _cointegrated_pair(phi=0.95, seed=21)
        y1_fast, y2_fast = _cointegrated_pair(phi=0.5, seed=21)
        slow = engle_granger_test("A", "B", y1_slow, y2_slow)
        fast = engle_granger_test("A", "B", y1_fast, y2_fast)
        self.assertLess(fast.adf_t_stat, slow.adf_t_stat)


class TestEngleGrangerAbstainsOnNonCointegratedSeries(unittest.TestCase):
    def test_independent_random_walks_are_not_cointegrated(self):
        y1, y2 = _independent_walks()
        result = engle_granger_test("Y1", "Y2", y1, y2, significance=0.05, max_lag=8)
        self.assertFalse(result.is_cointegrated)
        self.assertIn("not rejected", result.reason.lower())
        self.assertGreater(result.adf_t_stat, result.critical_value_used)

    def test_abstention_reason_is_stated_not_silent(self):
        y1, y2 = _independent_walks(seed=99)
        result = engle_granger_test("Y1", "Y2", y1, y2)
        self.assertFalse(result.is_cointegrated)
        self.assertTrue(len(result.reason) > 20)  # a real explanation, not a blank/placeholder


class TestShapeAndEdgeCases(unittest.TestCase):
    def test_too_short_series_does_not_crash_and_abstains(self):
        rng = np.random.default_rng(1)
        y1 = rng.normal(0, 1, 5)
        y2 = rng.normal(0, 1, 5)
        result = engle_granger_test("A", "B", y1, y2, max_lag=8)
        self.assertFalse(result.is_cointegrated)


if __name__ == "__main__":
    unittest.main()
