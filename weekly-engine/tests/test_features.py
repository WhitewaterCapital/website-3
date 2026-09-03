"""Feature-layer tests: registry integrity, point-in-time discipline, and a
handful of known-answer checks on the technical features.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wf.features.panel import build_feature_panel, prepare_base
from wf.features.registry import FEATURE_REGISTRY, base_manifest, manifest_hash
from wf.features.returns import RET_LAG_COLUMNS
from wf.features.technical import TECHNICAL_COLUMNS, _wilder_rsi
from wf.synthetic import default_sector_map, generate_synthetic_weekly_prices


def test_registry_has_every_documented_feature_family():
    names = {s.name for s in FEATURE_REGISTRY}
    assert set(RET_LAG_COLUMNS).issubset(names)
    assert {"rsi_5", "rsi_9", "rsi_14"}.issubset(names)
    for w in (4, 8, 12, 26, 52):
        assert f"mom_{w}" in names
        assert f"mom_{w}_skip" in names
    assert {"vol_10", "vol_26", "vol_ratio_10_26", "dist_52w_high", "vol_trend_4_26"}.issubset(names)


def test_every_feature_has_a_rationale_and_version():
    for spec in FEATURE_REGISTRY:
        assert spec.rationale and len(spec.rationale) > 10
        assert spec.version
        assert spec.lookback_weeks >= 0


def test_manifest_hash_is_stable_and_changes_with_content():
    m1 = base_manifest()
    m2 = base_manifest()
    assert manifest_hash(m1) == manifest_hash(m2)
    mutated = m1 + [{"name": "fake_feature", "version": "9.9"}]
    assert manifest_hash(mutated) != manifest_hash(m1)


def test_point_in_time_appending_future_bars_does_not_change_past_rows():
    """The core anti-look-ahead guarantee: every feature's value at week t
    must be identical whether or not later weeks exist in the input at all.
    """
    tickers = ["X"]
    prices = generate_synthetic_weekly_prices(tickers, n_weeks=120, seed=5, signal_strength=0.3)
    full = prices["X"]
    truncated = full.iloc[:-20]  # drop the most recent 20 weeks

    base_full = prepare_base(full)
    base_trunc = prepare_base(truncated)

    for spec in FEATURE_REGISTRY:
        full_vals = spec.fn(base_full)
        trunc_vals = spec.fn(base_trunc)
        common_idx = trunc_vals.index
        pd.testing.assert_series_equal(
            full_vals.loc[common_idx], trunc_vals, check_names=False, obj=spec.name, rtol=1e-9, atol=1e-12
        )


def test_rsi_bounds_and_flat_series_is_nan():
    close = pd.Series(np.linspace(10, 20, 40))  # monotonic increase -> all gains
    rsi_up = _wilder_rsi(close, 14)
    assert np.nanmax(rsi_up.to_numpy()) <= 100.0 + 1e-9
    assert np.nanmin(rsi_up.dropna().to_numpy()) >= 0.0
    # a perfectly flat window (no movement at all) is genuinely undefined
    flat = pd.Series([5.0] * 40)
    rsi_flat = _wilder_rsi(flat, 14)
    assert rsi_flat.iloc[-1] != rsi_flat.iloc[-1]  # NaN


def test_momentum_skip_excludes_most_recent_week():
    close = pd.Series([100.0, 110.0, 90.0, 90.0, 90.0, 90.0, 90.0])
    # last-week jump/drop should NOT affect the skip variant's most recent value
    from wf.features.technical import _momentum, _momentum_skip

    raw = _momentum(close, 2)
    skip = _momentum_skip(close, 2)
    # raw at the last index uses close[-1] and close[-3]; skip uses close[-2] and close[-4]
    assert raw.iloc[-1] == pytest.approx(close.iloc[-1] / close.iloc[-3] - 1.0)
    assert skip.iloc[-1] == pytest.approx(close.iloc[-2] / close.iloc[-4] - 1.0)


def test_ranked_lag_returns_are_bounded_0_1_within_each_week():
    tickers = [f"T{i}" for i in range(10)]
    prices = generate_synthetic_weekly_prices(tickers, n_weeks=80, seed=2, signal_strength=0.2)
    sectors = default_sector_map(tickers)
    panel, feature_cols, manifest = build_feature_panel(prices, sectors)
    for k in (1, 5, 10):
        col = f"ret_lag_{k}_xrank"
        vals = panel[col].dropna()
        assert (vals >= 0.0).all() and (vals <= 1.0).all()
        assert col in feature_cols


def test_sector_relative_zscore_columns_present_and_finite_where_expected():
    tickers = [f"T{i}" for i in range(12)]
    prices = generate_synthetic_weekly_prices(tickers, n_weeks=90, seed=3, signal_strength=0.2)
    sectors = default_sector_map(tickers, n_sectors=3)
    panel, feature_cols, manifest = build_feature_panel(prices, sectors)
    for base_col in TECHNICAL_COLUMNS:
        z_col = f"{base_col}_sector_z"
        assert z_col in feature_cols
        # once warm-up has passed there should be some finite values
        assert panel[z_col].notna().sum() > 0
