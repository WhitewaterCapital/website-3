"""Tests for loop/champion_challenger.py."""

from __future__ import annotations

import numpy as np
import pytest

from champion_challenger import (
    ModelMetrics,
    NoiseEstimate,
    calibration_error,
    deflated_sharpe_ratio,
    promote,
    rank_ic,
    turnover,
)


# --- vendored metrics smoke tests ---------------------------------------------

def test_rank_ic_perfect_positive():
    pred = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    actual = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    assert rank_ic(pred, actual) == pytest.approx(1.0)


def test_rank_ic_too_few_points_is_nan():
    assert np.isnan(rank_ic([1.0, 2.0], [1.0, 2.0]))


def test_deflated_sharpe_single_trial_matches_psr_fallback():
    dsr = deflated_sharpe_ratio(sr=0.1, n_obs=252, n_trials=1, sr_variance_across_trials=0.0)
    assert 0.0 <= dsr <= 1.0


def test_calibration_error_perfect_calibration_is_zero():
    rng = np.random.default_rng(0)
    probs = rng.uniform(0, 1, 5000)
    outcomes = (rng.uniform(0, 1, 5000) < probs).astype(float)
    ce = calibration_error(probs, outcomes, n_bins=10)
    assert ce < 0.03


def test_calibration_error_badly_miscalibrated_is_large():
    probs = np.full(1000, 0.9)
    outcomes = np.zeros(1000)  # always predicts 90% but never happens
    ce = calibration_error(probs, outcomes)
    assert ce == pytest.approx(0.9, abs=1e-6)


def test_calibration_error_empty_is_nan():
    assert np.isnan(calibration_error([], []))


def test_turnover_basic():
    w = np.array([[0.1, 0.1], [0.2, 0.0], [0.2, 0.0]])
    # period1->2: |0.1|+|0.1| = 0.2 ; period2->3: 0
    assert turnover(w) == pytest.approx(0.1)


def test_turnover_single_period_is_nan():
    assert np.isnan(turnover(np.array([[0.1, 0.2]])))


def test_turnover_requires_2d():
    with pytest.raises(ValueError):
        turnover(np.array([0.1, 0.2, 0.3]))


# --- promote() -----------------------------------------------------------------

def _metrics(rank_ic_=0.05, dsr=0.5, calib=0.05, turn=0.2):
    return ModelMetrics(rank_ic=rank_ic_, deflated_sharpe=dsr, calibration_error=calib, turnover=turn)


def _noise(ric_margin=0.01, dsr_margin=0.05, calib_tol=0.02, turn_tol=0.05):
    return NoiseEstimate(
        rank_ic_margin=ric_margin, deflated_sharpe_margin=dsr_margin,
        calibration_error_tolerance=calib_tol, turnover_tolerance=turn_tol,
    )


def test_clearly_better_challenger_is_promoted():
    champion = _metrics(rank_ic_=0.02, dsr=0.3, calib=0.05, turn=0.2)
    challenger = _metrics(rank_ic_=0.08, dsr=0.6, calib=0.04, turn=0.18)
    decision = promote(champion, challenger, _noise())
    assert decision.promote is True
    assert decision.primary_improvement["rank_ic"] == pytest.approx(0.06)
    assert decision.secondary_checks["calibration_error"] is True
    assert decision.secondary_checks["turnover"] is True


def test_marginally_better_challenger_is_not_promoted():
    """The doc's explicit requirement: a near-tie keeps the champion."""
    champion = _metrics(rank_ic_=0.050, dsr=0.500, calib=0.05, turn=0.2)
    # improvement smaller than the noise margins on both primaries
    challenger = _metrics(rank_ic_=0.053, dsr=0.510, calib=0.05, turn=0.2)
    noise = _noise(ric_margin=0.01, dsr_margin=0.05)
    decision = promote(champion, challenger, noise)
    assert decision.promote is False
    assert "noise margin" in decision.reason


def test_primary_gain_but_secondary_regression_blocks_promotion():
    champion = _metrics(rank_ic_=0.02, dsr=0.3, calib=0.05, turn=0.2)
    challenger = _metrics(rank_ic_=0.10, dsr=0.6, calib=0.20, turn=0.2)  # calibration got much worse
    decision = promote(champion, challenger, _noise(calib_tol=0.02))
    assert decision.promote is False
    assert decision.secondary_checks["calibration_error"] is False
    assert "guardrail" in decision.reason


def test_one_primary_metric_failing_blocks_promotion():
    champion = _metrics(rank_ic_=0.02, dsr=0.3)
    # rank_ic improves a lot, deflated_sharpe barely moves -> should not promote
    challenger = _metrics(rank_ic_=0.20, dsr=0.31)
    decision = promote(champion, challenger, _noise(dsr_margin=0.05))
    assert decision.promote is False


def test_worse_challenger_is_never_promoted():
    champion = _metrics(rank_ic_=0.10, dsr=0.8)
    challenger = _metrics(rank_ic_=0.02, dsr=0.1)
    decision = promote(champion, challenger, _noise())
    assert decision.promote is False


def test_nan_metric_never_promotes():
    champion = _metrics()
    challenger = ModelMetrics(rank_ic=float("nan"), deflated_sharpe=1.0, calibration_error=0.01, turnover=0.1)
    decision = promote(champion, challenger, _noise())
    assert decision.promote is False
    assert "NaN" in decision.reason


def test_negative_noise_margin_raises():
    champion = _metrics()
    challenger = _metrics(rank_ic_=0.5, dsr=2.0)
    with pytest.raises(ValueError):
        promote(champion, challenger, _noise(ric_margin=-0.01))


def test_exact_tie_is_not_promoted():
    champion = _metrics()
    challenger = _metrics()
    decision = promote(champion, challenger, _noise())
    assert decision.promote is False
