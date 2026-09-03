"""PIT correctness of the signal layer, and the cross-sectional z-score."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ge.features.signal import (
    cross_sectional_zscore,
    returns,
    rolling_return,
    signal_frame,
)
from ge.synthetic import make_synthetic_panel


def test_rolling_return_is_point_in_time():
    prices, _ = make_synthetic_panel(n_sectors=2, per_sector=3, n_days=120, seed=1)
    window = 5
    sig_before = signal_frame(prices, window).iloc[:80].copy()

    mutated = prices.copy()
    mutated.iloc[90:] = mutated.iloc[90:] * 5.0  # blow up the future
    sig_after = signal_frame(mutated, window).iloc[:80]

    pd.testing.assert_frame_equal(sig_before, sig_after)


def test_rolling_return_matches_pct_change():
    prices, _ = make_synthetic_panel(n_sectors=2, per_sector=2, n_days=30, seed=2)
    rr = rolling_return(prices, 3)
    expected = prices.pct_change(3)
    pd.testing.assert_frame_equal(rr, expected)


def test_cross_sectional_zscore_mean_zero_std_one():
    row = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = cross_sectional_zscore(row)
    assert z.mean() == pytest.approx(0.0, abs=1e-9)
    assert z.std(ddof=0) == pytest.approx(1.0, abs=1e-9)


def test_cross_sectional_zscore_constant_row_is_zero():
    row = pd.Series([2.0, 2.0, 2.0, 2.0])
    z = cross_sectional_zscore(row)
    assert (z == 0.0).all()


def test_cross_sectional_zscore_too_few_finite_returns_nan():
    row = pd.Series([1.0, np.nan, np.nan])
    z = cross_sectional_zscore(row)
    assert z.isna().all()


def test_returns_first_row_nan():
    prices, _ = make_synthetic_panel(n_sectors=1, per_sector=3, n_days=10, seed=3)
    r = returns(prices)
    assert r.iloc[0].isna().all()
    assert r.iloc[1:].notna().all().all()
