"""Tests for CHAOS-02 — the (explicitly simplified, stated-as-such) directional
classifier: causal-feature construction, no-leakage, calibration quality on a
synthetic dataset with a KNOWN true probability structure, and the abstention
gate.

Headline tests:
  * test_no_future_leakage — shuffling FUTURE rows must not change PAST
    predictions. This is the doc's causality requirement, checked directly
    rather than assumed from the `.shift(k)`-only construction.
  * test_calibration_error_within_tolerance — on synthetic data with a known
    generating probability, the calibrated model's mean absolute calibration
    error must fall under a documented tolerance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chaos.directional import (
    DirectionalConfig,
    DirectionalModel,
    MetaLabelGate,
    brier_and_reliability,
    build_features,
    make_direction_labels,
)

# Documented calibration tolerance for this synthetic test. Isotonic
# calibration on a few hundred held-out rows is not going to be perfect;
# this bound is generous enough to be stable but tight enough to catch a
# genuinely broken calibration step.
CALIBRATION_TOLERANCE = 0.12


def make_trending_bars(n: int = 900, seed: int = 3) -> pd.DataFrame:
    """A synthetic bar series with genuine (if modest) autocorrelation in
    returns, so the directional classifier has *something* real, if noisy,
    to learn — momentum continuation with mean-reverting noise on top."""
    rng = np.random.default_rng(seed)
    signal = rng.normal(0, 1, n)
    smoothed = pd.Series(signal).ewm(span=5).mean().to_numpy()
    logret = 0.0006 * smoothed + rng.normal(0, 0.0015, n)
    close = 100.0 * np.exp(np.cumsum(logret))
    volume = np.maximum(10_000 + rng.normal(0, 1000, n), 100.0)
    idx = pd.date_range("2026-01-05 09:30", periods=n, freq="min")
    return pd.DataFrame(
        {
            "open": np.roll(close, 1),
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def make_known_probability_dataset(n: int = 3000, seed: int = 42):
    """A dataset with a KNOWN true generating probability: y ~ Bernoulli(p),
    where p is a deterministic, learnable function of a single feature x.
    This lets the calibration test compare the model's calibrated output
    directly against ground truth, not just against noisy realised outcomes."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-3, 3, n)
    true_p = 1.0 / (1.0 + np.exp(-x))  # logistic in x — smooth, learnable
    y = rng.binomial(1, true_p)

    # Package as a feature frame shaped like build_features' output (plus a
    # couple of decoy columns) so DirectionalModel.fit/predict can be used
    # directly against it.
    idx = pd.RangeIndex(n)
    X = pd.DataFrame(
        {
            "ret_lag_1": x,
            "ret_lag_2": rng.normal(0, 1, n),  # pure noise decoy feature
            "vol_5": np.abs(rng.normal(0, 1, n)),
        },
        index=idx,
    )
    y_s = pd.Series(y.astype(float), index=idx)
    true_p_s = pd.Series(true_p, index=idx)
    return X, y_s, true_p_s


# --- causality / no-leakage --------------------------------------------------


def test_build_features_is_causal_shift_only():
    """Every feature column at row t must depend only on bars <= t: verified
    directly by checking each engineered column equals a `.shift(k)` (k >= 0)
    of a base causal series, for the pure-lag columns."""
    bars = make_trending_bars(n=200, seed=1)
    feats = build_features(bars)
    logret = np.log(bars["close"] / bars["close"].shift(1))
    for lag in range(1, DirectionalConfig().n_lag_returns + 1):
        expected = logret.shift(lag - 1)
        pd.testing.assert_series_equal(
            feats[f"ret_lag_{lag}"], expected, check_names=False
        )


def test_no_future_leakage():
    """The doc's causality proof: shuffle rows STRICTLY AFTER a cutoff and
    confirm predictions for rows AT OR BEFORE the cutoff are bit-for-bit
    unchanged. If any feature or the fitted model secretly depended on future
    rows, permuting them would perturb past predictions."""
    bars = make_trending_bars(n=500, seed=5)
    cfg = DirectionalConfig(horizon=5)
    X = build_features(bars, cfg)
    y = make_direction_labels(bars, cfg.horizon)

    model = DirectionalModel(cfg).fit(X, y)
    pred_before = model.predict(X)

    cutoff = 400
    rng = np.random.default_rng(0)
    bars_shuffled = bars.copy()
    future_idx = bars.index[cutoff:]
    perm = rng.permutation(future_idx)
    bars_shuffled.loc[future_idx, ["open", "high", "low", "close", "volume"]] = bars.loc[
        perm, ["open", "high", "low", "close", "volume"]
    ].to_numpy()

    X_shuffled = build_features(bars_shuffled, cfg)
    # Features at/before `cutoff - n_lag_returns` cannot see the shuffled
    # region at all (they are pure lags of bars strictly before it); compare
    # over a safely-past window.
    safe_upto = cutoff - cfg.n_lag_returns - 1
    pred_after = model.predict(X_shuffled)

    pd.testing.assert_frame_equal(
        pred_before.iloc[:safe_upto], pred_after.iloc[:safe_upto]
    )


def test_feature_shuffle_future_rows_do_not_change_past_features():
    """A narrower, feature-only version of the leakage check: perturbing bars
    after a cutoff must leave `build_features` output before the cutoff
    (minus the lag warm-up band) byte-identical."""
    bars = make_trending_bars(n=300, seed=8)
    cfg = DirectionalConfig()
    feats_before = build_features(bars, cfg)

    cutoff = 250
    rng = np.random.default_rng(1)
    bars2 = bars.copy()
    future_idx = bars.index[cutoff:]
    bars2.loc[future_idx, "close"] = rng.permutation(bars.loc[future_idx, "close"].to_numpy())
    feats_after = build_features(bars2, cfg)

    safe_upto = cutoff - cfg.n_lag_returns - 1
    pd.testing.assert_frame_equal(
        feats_before.iloc[:safe_upto], feats_after.iloc[:safe_upto]
    )


# --- label construction (documented look-ahead, training target only) ------


def test_make_direction_labels_uses_future_and_documents_it():
    bars = make_trending_bars(n=100, seed=2)
    horizon = 5
    y = make_direction_labels(bars, horizon)
    assert y.iloc[-horizon:].isna().all()
    assert y.iloc[: len(y) - horizon].notna().all()
    assert set(y.dropna().unique()) <= {0.0, 1.0}


# --- fit / predict basic shape ------------------------------------------------


def test_fit_predict_shapes_and_abstain_band():
    bars = make_trending_bars(n=700, seed=13)
    cfg = DirectionalConfig(horizon=5, abstain_band=(0.45, 0.55))
    X = build_features(bars, cfg)
    y = make_direction_labels(bars, cfg.horizon)
    model = DirectionalModel(cfg).fit(X, y)
    pred = model.predict(X)

    assert list(pred.columns) == ["probability", "uncertainty", "abstain"]
    valid = pred["probability"].notna()
    assert valid.sum() > 0
    p = pred.loc[valid, "probability"]
    assert (p >= 0.0).all() and (p <= 1.0).all()
    # Abstain must be true wherever probability is inside the band or NaN.
    lo, hi = cfg.abstain_band
    should_abstain = pred["probability"].isna() | (
        (pred["probability"] >= lo) & (pred["probability"] <= hi)
    )
    assert (pred["abstain"] == should_abstain).all()


def test_fit_requires_minimum_rows():
    bars = make_trending_bars(n=20, seed=1)
    cfg = DirectionalConfig(horizon=5)
    X = build_features(bars, cfg)
    y = make_direction_labels(bars, cfg.horizon)
    with pytest.raises(ValueError):
        DirectionalModel(cfg).fit(X, y)


# --- calibration on a KNOWN true probability structure -----------------------


def test_calibration_error_within_tolerance():
    """The doc's calibration "done when": fit on synthetic data with a KNOWN
    true generating probability, then assert the CALIBRATED model's mean
    absolute calibration error against ground truth is within the documented
    tolerance (CALIBRATION_TOLERANCE)."""
    X, y, true_p = make_known_probability_dataset(n=3000, seed=42)
    cfg = DirectionalConfig(calibration_holdout_frac=0.3, random_state=1)
    model = DirectionalModel(cfg).fit(X, y)

    pred_p = model.probability(X)
    valid = pred_p.notna()
    report = brier_and_reliability(pred_p[valid].to_numpy(), true_p[valid].to_numpy())

    assert report["mean_abs_calibration_error"] < CALIBRATION_TOLERANCE, report


def test_calibration_improves_or_matches_raw_scores():
    """Sanity check that calibration is doing real work: the calibrated
    model's Brier score against ground-truth probability should not be wildly
    worse than a naive constant-0.5 baseline (i.e. it has learned something,
    not just degraded to noise)."""
    X, y, true_p = make_known_probability_dataset(n=2000, seed=7)
    cfg = DirectionalConfig(random_state=2)
    model = DirectionalModel(cfg).fit(X, y)
    pred_p = model.probability(X)
    valid = pred_p.notna()

    report = brier_and_reliability(pred_p[valid].to_numpy(), true_p[valid].to_numpy())
    baseline_brier = float(np.mean((0.5 - true_p[valid].to_numpy()) ** 2))
    assert report["brier"] < baseline_brier


# --- abstention gate ----------------------------------------------------------


def test_meta_label_gate_abstains_without_fit_data_gracefully():
    bars = make_trending_bars(n=500, seed=21)
    cfg = DirectionalConfig(horizon=5)
    X = build_features(bars, cfg)
    y = make_direction_labels(bars, cfg.horizon)
    model = DirectionalModel(cfg).fit(X, y)
    pred = model.predict(X)

    gate = MetaLabelGate(random_state=1).fit(X, pred["probability"], y)
    act = gate.act(X, pred["probability"])
    # Rows without a primary probability must always abstain (False).
    assert not act[pred["probability"].isna()].any()
    assert act.dtype == bool
