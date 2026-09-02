"""Pipeline integration tests (offline, synthetic).

Covers the warm-up gate (fix #5): plan_for_ticker must abstain — not crash on a
short OU fit or classify on an under-warmed row — when history is too short.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ie.pipeline import PipelineConfig, plan_for_ticker
from ie.regime.classifier import RegimeModel, build_dataset


def _ohlc(n, seed):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, n)))
    idx = pd.date_range("2013-01-02", periods=n, freq="B", name="date")
    span = np.abs(rng.normal(0, 0.6, n)) + 0.2
    return pd.DataFrame(
        {"open": close + rng.normal(0, 0.3, n), "high": close + span,
         "low": close - span, "close": close, "volume": 1e6},
        index=idx,
    )


def _trained_model():
    # calibrate=False here for speed — calibration is exercised in test_classifier.
    prices = {"AAA": _ohlc(1000, 1), "BBB": _ohlc(1000, 2)}
    X, y, times, groups, cols = build_dataset(prices)
    return RegimeModel(max_iter=60, calibrate=False).fit(X, y), cols


def test_pipeline_abstains_when_underwarmed():
    model, cols = _trained_model()
    short = _ohlc(100, 9)  # < the 252-bar warm-up
    plan = plan_for_ticker("AAA", short, model, cols, PipelineConfig())
    assert plan.confidence == "insufficient"
    assert "history" in plan.rationale.lower()


def test_pipeline_tiny_frame_does_not_crash():
    model, cols = _trained_model()
    tiny = _ohlc(15, 10)  # would break fit_ou (<20 points) if it reached it
    plan = plan_for_ticker("AAA", tiny, model, cols, PipelineConfig())
    assert plan.confidence == "insufficient"


def test_pipeline_full_history_produces_valid_plan():
    model, cols = _trained_model()
    prices = _ohlc(600, 11)
    plan = plan_for_ticker("AAA", prices, model, cols, PipelineConfig())
    assert plan.regime in ("trend", "mean-revert", "high-vol")
    assert plan.confidence in ("actionable", "watch", "insufficient")
    d = plan.as_dict()
    assert "sizingPct" in d and "regime" in d
