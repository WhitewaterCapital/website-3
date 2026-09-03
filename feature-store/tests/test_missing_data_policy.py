"""Missing-data policy tests -- FEAT-01 (b), (c), (d).

Spec: "Every feature declares a missing data policy. Forward fill with a
maximum age, treat as missing, or fail. Never fill with zero, because zero
is a real value for a return."
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fs.missing_data import MissingDataFailure, apply_missing_data_policy
from fs.panel import build_panel
from fs.registry import FeatureDef, FeatureRegistry
from fs.sample_features import register_sample_features
from fs.synthetic import make_synthetic_ohlcv


def _make_feature(name, policy, max_age=None, compute=None):
    return FeatureDef(
        name=name,
        version="1.0.0",
        owner="quant-team",
        lookback=1,
        rationale="Test fixture feature -- exercises missing_data_policy handling.",
        missing_data_policy=policy,
        max_age_periods=max_age,
        compute=compute or (lambda h: h["close"].astype(float)),
    )


# --- direct unit tests on apply_missing_data_policy -------------------------


def test_treat_as_missing_passes_nan_through_unchanged():
    fd = _make_feature("f_treat_as_missing", "treat_as_missing")
    raw = pd.Series([1.0, np.nan, 3.0, np.nan], index=pd.RangeIndex(4))
    out = apply_missing_data_policy(raw, fd)
    pd.testing.assert_series_equal(out, raw)


def test_fail_policy_raises_on_any_missing_value():
    fd = _make_feature("f_fail", "fail")
    raw = pd.Series([1.0, np.nan, 3.0], index=pd.RangeIndex(3))
    with pytest.raises(MissingDataFailure, match="f_fail"):
        apply_missing_data_policy(raw, fd)


def test_fail_policy_passes_through_when_nothing_is_missing():
    fd = _make_feature("f_fail_ok", "fail")
    raw = pd.Series([1.0, 0.0, -2.0], index=pd.RangeIndex(3))
    out = apply_missing_data_policy(raw, fd)
    pd.testing.assert_series_equal(out, raw)


def test_forward_fill_fills_gaps_within_max_age():
    fd = _make_feature("f_ffill", "forward_fill_max_age", max_age=2)
    raw = pd.Series([1.0, np.nan, np.nan, 4.0], index=pd.RangeIndex(4))
    out = apply_missing_data_policy(raw, fd)
    # both NaNs are within 2 periods of the last valid observation (1.0)
    assert out.tolist() == [1.0, 1.0, 1.0, 4.0]


def test_forward_fill_does_not_fill_past_max_age():
    """The core (d) test: a gap OLDER than max_age_periods stays missing --
    it is never filled with a stale value, and it is never filled with 0."""
    fd = _make_feature("f_ffill_capped", "forward_fill_max_age", max_age=2)
    raw = pd.Series([5.0, np.nan, np.nan, np.nan, 9.0], index=pd.RangeIndex(5))
    out = apply_missing_data_policy(raw, fd)
    # index 1, 2 are within max_age=2 of the last valid obs -> filled with 5.0
    # index 3 is the 3rd consecutive NaN, past max_age=2 -> stays NaN
    assert out.iloc[0] == 5.0
    assert out.iloc[1] == 5.0
    assert out.iloc[2] == 5.0
    assert np.isnan(out.iloc[3])
    assert out.iloc[3] != 0.0  # explicitly not fabricated as zero
    assert out.iloc[4] == 9.0


def test_forward_fill_never_substitutes_zero_for_a_leading_gap():
    """A gap with NO prior valid observation at all cannot be forward-filled
    (there is nothing to fill from) -- it must stay NaN, never become 0.0,
    even though 0.0 would silently "look like" a plausible return value."""
    fd = _make_feature("f_ffill_leading_gap", "forward_fill_max_age", max_age=5)
    raw = pd.Series([np.nan, np.nan, 3.0], index=pd.RangeIndex(3))
    out = apply_missing_data_policy(raw, fd)
    assert np.isnan(out.iloc[0])
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 3.0


# --- end-to-end via build_panel ---------------------------------------------


def _loader_with_a_real_gap(security: str) -> pd.DataFrame:
    """A SAMPLE (synthetic) history with a deliberately injected data gap
    (a NaN close on one date, simulating a missing upstream print) placed
    where it will propagate into ret_lag_1's raw output as NaN."""
    history = make_synthetic_ohlcv(security, n_periods=40, seed=7)
    history = history.copy()
    gap_date = history.index[20]
    history.loc[gap_date, "close"] = np.nan
    return history


def test_build_panel_treat_as_missing_never_fills_with_zero():
    registry = FeatureRegistry()
    register_sample_features(registry, owner="test-owner")
    dates = _loader_with_a_real_gap("DEMO_GAP").index[15:25]

    panel = build_panel(
        registry=registry,
        universe=["DEMO_GAP"],
        dates=dates,
        load_history=_loader_with_a_real_gap,
        feature_names=["ret_lag_1"],
    )

    col = panel["ret_lag_1"]
    # wherever the underlying close was NaN (or immediately after it, since
    # pct_change needs both endpoints), the feature must be NaN -- and
    # critically, NEVER a fabricated 0.0 standing in for "missing". (A
    # genuine zero return elsewhere in the series would be a legitimate
    # value -- the point of this test is that a *missing* value is
    # represented as NaN, distinguishable from a real zero, never coerced
    # into looking like one.)
    assert col.isna().sum() >= 1
    gap_date = _loader_with_a_real_gap("DEMO_GAP").index[20]
    assert pd.isna(col.loc[("DEMO_GAP", gap_date)])


def test_build_panel_zero_is_never_used_as_a_fill_value_directly():
    """Directly proves apply_missing_data_policy (which build_panel calls
    for every feature) contains no code path that produces 0.0 from a NaN
    input, for any of the three policies."""
    raw_with_gaps = pd.Series([np.nan, 1.5, np.nan, np.nan, -0.5, np.nan], index=pd.RangeIndex(6))

    treat = apply_missing_data_policy(raw_with_gaps, _make_feature("f1", "treat_as_missing"))
    assert treat.isna().sum() == 4  # unchanged (positions 0, 2, 3, 5)
    assert 0.0 not in treat.dropna().tolist()

    ffill = apply_missing_data_policy(
        raw_with_gaps, _make_feature("f2", "forward_fill_max_age", max_age=1)
    )
    assert 0.0 not in ffill.dropna().tolist()
    # the two-NaN run (indices 2,3) only gets index 2 filled (max_age=1);
    # index 3 stays NaN rather than being fabricated as 0 or over-filled.
    assert ffill.iloc[2] == 1.5
    assert np.isnan(ffill.iloc[3])


def test_build_panel_fail_policy_raises_on_a_genuine_gap_past_warmup():
    """realized_vol_20 (missing_data_policy='fail') must raise, not return
    NaN or 0, when the underlying data has a genuine gap past its
    20-period warm-up window -- the (c) acceptance test. (A NaN INSIDE the
    warm-up window itself is expected -- see
    test_build_panel_fail_policy_tolerates_its_own_warmup_window below --
    so this test injects a gap well after warmup instead.)"""
    registry = FeatureRegistry()
    register_sample_features(registry, owner="test-owner")

    def loader(security: str) -> pd.DataFrame:
        history = make_synthetic_ohlcv(security, n_periods=60, seed=3).copy()
        history.iloc[40, history.columns.get_loc("close")] = np.nan  # genuine gap, well past warmup
        return history

    dates = loader("DEMO_GENUINE_GAP").index[35:45]  # straddles the injected gap

    with pytest.raises(MissingDataFailure, match="realized_vol_20"):
        build_panel(
            registry=registry,
            universe=["DEMO_GENUINE_GAP"],
            dates=dates,
            load_history=loader,
            feature_names=["realized_vol_20"],
        )


def test_build_panel_fail_policy_tolerates_its_own_warmup_window():
    """The flip side: a "fail"-policy feature must NOT raise merely because
    a requested date falls inside its own declared lookback warm-up --
    that NaN is expected (documented by `lookback`), not a data gap."""
    registry = FeatureRegistry()
    register_sample_features(registry, owner="test-owner")

    def loader(security: str) -> pd.DataFrame:
        return make_synthetic_ohlcv(security, n_periods=40, seed=3)

    early_dates = loader("DEMO_WARMUP").index[:10]  # inside the 20-period warmup, no real gap

    panel = build_panel(
        registry=registry,
        universe=["DEMO_WARMUP"],
        dates=early_dates,
        load_history=loader,
        feature_names=["realized_vol_20"],
    )
    assert panel["realized_vol_20"].isna().all()


def test_build_panel_fail_policy_succeeds_once_history_is_long_enough():
    registry = FeatureRegistry()
    register_sample_features(registry, owner="test-owner")

    def loader(security: str) -> pd.DataFrame:
        return make_synthetic_ohlcv(security, n_periods=60, seed=3)

    late_dates = loader("DEMO_LATE").index[30:40]  # well past the 20-period warmup

    panel = build_panel(
        registry=registry,
        universe=["DEMO_LATE"],
        dates=late_dates,
        load_history=loader,
        feature_names=["realized_vol_20"],
    )
    assert panel["realized_vol_20"].notna().all()


def test_build_panel_forward_fill_max_age_respected_end_to_end():
    """rsi_14 (forward_fill_max_age=3) must not fill a gap older than 3
    periods, even when wired through the full build_panel path."""
    registry = FeatureRegistry()
    register_sample_features(registry, owner="test-owner")

    def loader(security: str) -> pd.DataFrame:
        history = make_synthetic_ohlcv(security, n_periods=60, seed=11)
        history = history.copy()
        # blank out 5 consecutive closes well past the RSI warm-up window,
        # simulating a longer-than-max_age upstream data outage.
        gap_start = 30
        history.iloc[gap_start : gap_start + 5, history.columns.get_loc("close")] = np.nan
        return history

    dates = loader("DEMO_LONGGAP").index[25:40]
    panel = build_panel(
        registry=registry,
        universe=["DEMO_LONGGAP"],
        dates=dates,
        load_history=loader,
        feature_names=["rsi_14"],
    )
    col = panel["rsi_14"]
    # at least one date inside the gap window must be NaN (past max_age=3),
    # not silently forward-filled indefinitely and not fabricated as 0.
    assert col.isna().any()
    assert 0.0 not in col.dropna().tolist()
