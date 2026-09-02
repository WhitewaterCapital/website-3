"""Fast, offline sanity tests for the classifier plumbing (no network).

Real out-of-sample skill is measured against the live universe in the evaluation
script, not here — these just prove the dataset assembly, fit/predict, and
walk-forward reporting are wired correctly and leakage-safe end to end.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier

from ie.regime.classifier import RegimeModel, build_dataset, walk_forward_report
from ie.regime.labels import REGIMES
from ie.validation.splits import PurgedWalkForwardCV


def _ohlc(n, seed):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0003, 0.012, n)
    close = 100 * np.exp(np.cumsum(steps))
    idx = pd.date_range("2013-01-02", periods=n, freq="B", name="date")
    span = np.abs(rng.normal(0, 0.6, n)) + 0.2
    return pd.DataFrame(
        {
            "open": close + rng.normal(0, 0.3, n),
            "high": close + span,
            "low": close - span,
            "close": close,
            "volume": 1e6,
        },
        index=idx,
    )


def test_build_dataset_shapes_and_alignment():
    prices = {"AAA": _ohlc(900, 1), "BBB": _ohlc(900, 2)}
    X, y, times, groups, cols = build_dataset(prices)
    n = len(X)
    assert len(y) == n == len(times) == len(groups)
    assert set(y.unique()).issubset(set(REGIMES))
    assert "mom_252" in cols and "rsi_14" in cols
    # No all-NaN rows survived the warm-up filter.
    assert not X["mom_252"].isna().any()


def test_fit_predict_proba_valid():
    prices = {"AAA": _ohlc(1000, 3), "BBB": _ohlc(1000, 4)}
    X, y, times, groups, cols = build_dataset(prices)
    model = RegimeModel(max_iter=60, calibrate=False).fit(X, y)
    proba = model.predict_proba(X)
    # Probabilities sum to 1 per row and columns are a subset of the vocabulary.
    assert np.allclose(proba.sum(axis=1).to_numpy(), 1.0, atol=1e-6)
    assert set(proba.columns).issubset(set(REGIMES))
    assert set(model.predict(X)).issubset(set(REGIMES))


def test_calibration_is_wrapped_and_probabilities_valid():
    # Fix #2: calibrate=True wraps the base in CalibratedClassifierCV (fit only ever
    # sees the data passed to it => fold-internal in walk-forward). calibrate=False
    # leaves the bare estimator.
    prices = {"AAA": _ohlc(1000, 7), "BBB": _ohlc(1000, 8)}
    X, y, times, groups, cols = build_dataset(prices)
    cal = RegimeModel(max_iter=50, calibrate=True).fit(X, y)
    raw = RegimeModel(max_iter=50, calibrate=False).fit(X, y)
    assert isinstance(cal.clf, CalibratedClassifierCV)
    assert isinstance(raw.clf, HistGradientBoostingClassifier)
    p = cal.predict_proba(X)
    assert np.allclose(p.sum(axis=1).to_numpy(), 1.0, atol=1e-6)


def test_walk_forward_report_runs_and_reports_brier():
    prices = {"AAA": _ohlc(1400, 5), "BBB": _ohlc(1400, 6)}
    X, y, times, groups, cols = build_dataset(prices)
    cv = PurgedWalkForwardCV(n_splits=3, horizon=10, embargo=5, min_train=252)
    rep = walk_forward_report(X, y, times, cv, RegimeModel(max_iter=60, calibrate=False))
    assert -1.0 <= rep["kappa"] <= 1.0
    assert 0.0 <= rep["balanced_accuracy"] <= 1.0
    assert rep["confusion"].to_numpy().sum() == rep["n_oos"]
    assert len(rep["fold_kappa"]) >= 2
    # Fix #2: Brier + reliability are reported.
    assert 0.0 <= rep["brier"] <= 2.0
    assert isinstance(rep["reliability_high_vol"], list)


def test_walk_forward_report_calibrated_reports_brier():
    # Same, but through the calibrated path (smaller/faster), proving the report
    # runs end-to-end with fold-internal calibration.
    prices = {"AAA": _ohlc(1100, 15), "BBB": _ohlc(1100, 16)}
    X, y, times, groups, cols = build_dataset(prices)
    cv = PurgedWalkForwardCV(n_splits=2, horizon=10, embargo=5, min_train=252)
    rep = walk_forward_report(X, y, times, cv, RegimeModel(max_iter=40, calibrate=True))
    assert 0.0 <= rep["brier"] <= 2.0


def test_build_dataset_ragged_columns_raise(monkeypatch):
    # Fix #5: a column mismatch across tickers must fail loudly, not silently
    # overwrite the column list and misalign the pooled matrix.
    import ie.regime.classifier as C
    real = C.compute_features
    calls = {"n": 0}

    def fake(df, cfg=None):
        out = real(df, cfg)
        calls["n"] += 1
        if calls["n"] == 2:  # make the 2nd ticker ragged
            out = out.drop(columns=[out.columns[0]])
        return out

    monkeypatch.setattr(C, "compute_features", fake)
    with pytest.raises(ValueError):
        build_dataset({"AAA": _ohlc(400, 1), "BBB": _ohlc(400, 2)})
