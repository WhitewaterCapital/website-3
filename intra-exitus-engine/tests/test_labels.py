"""Tests for the regime labeler.

These are *falsifiability* tests: a synthetic series with a known character must
receive the label that character implies. A noisy uptrend must label trend-up; a
mean-reverting (AR-1) series must label mean-revert; a volatility burst must label
high-vol. If the labeler can't tell these apart on data we constructed, it can't
be trusted on real data.

Note the labeler flags the top (1 - vol_pct) fraction of forward-vol as high-vol
by construction, so even a clean trend has a ~15% high-vol floor — the trend
fractions below are set with that ceiling in mind.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ie.regime.labels import REGIMES, LabelConfig, make_labels


def _series(vals) -> pd.Series:
    idx = pd.date_range("2016-01-04", periods=len(vals), freq="B", name="date")
    return pd.Series(np.asarray(vals, dtype=float), index=idx)


def _noisy_trend(n, drift, seed, noise=0.003):
    rng = np.random.default_rng(seed)
    steps = drift + rng.normal(0, noise, n)
    return _series(100.0 * np.exp(np.cumsum(steps)))


def _ar1(n, phi, seed, scale=3.0):
    """Mean-reverting AR(1) around 0 -> realistic choppy series (what OU models)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, 1)
    return _series(100.0 + scale * x)


def test_clean_uptrend_is_trend_with_up_direction():
    res = make_labels(_noisy_trend(320, drift=0.005, seed=0), LabelConfig())
    lab = res["label"].dropna()
    assert (lab == "trend").mean() > 0.7, lab.value_counts().to_dict()
    assert lab.value_counts().idxmax() == "trend"
    # The direction diagnostic reads "up" on the trend rows (not a training target).
    d = res.loc[lab[lab == "trend"].index, "direction"]
    assert (d == "up").mean() > 0.9


def test_clean_downtrend_is_trend_with_down_direction():
    res = make_labels(_noisy_trend(320, drift=-0.005, seed=1), LabelConfig())
    lab = res["label"].dropna()
    assert (lab == "trend").mean() > 0.7, lab.value_counts().to_dict()
    d = res.loc[lab[lab == "trend"].index, "direction"]
    assert (d == "down").mean() > 0.9


def test_oscillation_is_mean_revert():
    lab = make_labels(_ar1(500, phi=0.8, seed=2), LabelConfig())["label"].dropna()
    vc = lab.value_counts()
    assert (lab == "mean-revert").mean() > 0.55, vc.to_dict()
    assert vc.idxmax() == "mean-revert"


def test_vol_burst_is_high_vol():
    # Long calm (so the causal threshold from fix #3 is warmed up), then a burst.
    # Forward vol in the burst dwarfs the expanding threshold -> high-vol dominates
    # there, and is far rarer in the calm stretch. (Note: a within-name relative
    # threshold still flags the calm period's OWN top band, so "calm" isn't zero.)
    rng = np.random.default_rng(1)
    calm = np.cumsum(rng.normal(0, 0.1, 400)) + 100
    burst = calm[-1] + np.cumsum(rng.normal(0, 3.0, 120))
    close = _series(np.concatenate([calm, burst]))
    lab = make_labels(close, LabelConfig())["label"]
    in_burst = lab.iloc[400:480].dropna()   # burst, past the 252-bar warm-up
    in_calm = lab.iloc[300:390].dropna()    # calm, past warm-up
    assert in_burst.value_counts().idxmax() == "high-vol", in_burst.value_counts().to_dict()
    assert (in_burst == "high-vol").mean() > 0.6, in_burst.value_counts().to_dict()
    assert (in_calm == "high-vol").mean() < (in_burst == "high-vol").mean()


def test_high_vol_is_a_bounded_minority_class():
    # With the causal (expanding) threshold from fix #3, high-vol is no longer an
    # exact (1 - vol_pct) slice — early rows have no threshold yet — but it must
    # stay a clear minority and never dominate.
    close = _noisy_trend(1200, drift=0.001, seed=4, noise=0.01)
    lab = make_labels(close, LabelConfig(vol_pct=0.85))["label"].dropna()
    frac = (lab == "high-vol").mean()
    assert 0.03 < frac < 0.20, frac
    assert (lab == "high-vol").sum() < (lab == "mean-revert").sum()


def test_label_threshold_is_causal_stable():
    # Fix #3: labels for early rows must NOT change when future bars are appended.
    # The high-vol threshold is now an expanding (causal) quantile, so appending a
    # later vol regime cannot retroactively flip earlier labels.
    base = _ar1(700, phi=0.85, seed=11)
    # Append a violent high-vol tail (would have lifted a global quantile).
    rng = np.random.default_rng(12)
    tail = base.iloc[-1] + np.cumsum(rng.normal(0, 4.0, 300))
    extended = pd.concat([base, _series(tail)], ignore_index=False)
    extended.index = pd.date_range("2016-01-04", periods=len(extended), freq="B", name="date")

    cfg = LabelConfig(vol_min_periods=252)
    lab_base = make_labels(base, cfg)["label"]
    lab_ext = make_labels(extended, cfg)["label"]

    # Compare the first 400 labelled positions — they must be identical.
    n = 400
    a = lab_base.iloc[:n].reset_index(drop=True)
    b = lab_ext.iloc[:n].reset_index(drop=True)
    both = a.notna() & b.notna()
    assert (a[both] == b[both]).all(), "early labels changed when future was appended"
    assert (a.isna() == b.isna()).all()


def test_last_horizon_rows_unlabelled():
    cfg = LabelConfig(horizon=10)
    close = _noisy_trend(160, drift=0.003, seed=6)
    lab = make_labels(close, cfg)["label"]
    # The final H rows can't see the future -> must be NaN.
    assert lab.iloc[-cfg.horizon:].isna().all()
    assert lab.iloc[-(cfg.horizon + 1)] in REGIMES


def test_labels_are_deterministic_and_in_vocab():
    close = _ar1(300, phi=0.85, seed=3)
    a = make_labels(close)["label"]
    b = make_labels(close)["label"]
    pd.testing.assert_series_equal(a, b)
    assert set(a.dropna().unique()).issubset(set(REGIMES))


def test_efficiency_bounds():
    er = make_labels(_ar1(300, phi=0.85, seed=5))["efficiency"].dropna()
    assert ((er >= -1e-9) & (er <= 1 + 1e-9)).all()


def test_threshold_shifts_class_mix():
    # Raising the efficiency cutoff converts some trend labels to mean-revert
    # (harder to qualify as "directional"), among the calm (non-high-vol) rows.
    close = _noisy_trend(500, drift=0.002, seed=9, noise=0.006)
    loose = make_labels(close, LabelConfig(er_trend=0.2))["label"].dropna()
    strict = make_labels(close, LabelConfig(er_trend=0.8))["label"].dropna()
    assert (strict == "trend").mean() <= (loose == "trend").mean()
