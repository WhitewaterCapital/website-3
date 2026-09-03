"""Known-answer tests for validation/metrics.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wf.validation.metrics import (
    decile_spread,
    deflated_sharpe_ratio,
    hit_rate,
    probabilistic_sharpe_ratio,
    rank_ic,
    sharpe_of_returns,
    turnover,
)


def test_rank_ic_perfect_positive_and_negative():
    pred = np.arange(20)
    assert rank_ic(pred, pred) == pytest.approx(1.0)
    assert rank_ic(pred, -pred) == pytest.approx(-1.0)


def test_rank_ic_nan_with_too_few_points():
    result = rank_ic([1, 2], [1, 2])  # fewer than 3 points -> undefined by construction
    assert result != result  # NaN != NaN


def test_hit_rate_perfect_and_worst():
    pred = np.array([1.0, 2.0, -1.0, -2.0])
    actual = np.array([0.5, 0.9, -0.2, -0.3])
    assert hit_rate(pred, actual) == pytest.approx(1.0)
    assert hit_rate(pred, -actual) == pytest.approx(0.0)


def test_decile_spread_monotonic_relationship_gives_positive_spread():
    rng = np.random.default_rng(0)
    pred = rng.normal(size=200)
    actual = pred + rng.normal(scale=0.1, size=200)  # pred strongly predicts actual
    spread = decile_spread(pred, actual)
    assert spread > 0.5  # top decile should clearly beat bottom decile here


def test_decile_spread_nan_on_too_few_points():
    assert decile_spread([1, 2, 3], [1, 2, 3], n_deciles=10) != decile_spread([1, 2, 3], [1, 2, 3], n_deciles=10)


def test_turnover_zero_for_identical_rankings():
    ranks = pd.Series([0.1, 0.5, 0.9], index=["A", "B", "C"])
    assert turnover(ranks, ranks) == pytest.approx(0.0)


def test_turnover_positive_for_shuffled_rankings():
    prev = pd.Series([0.1, 0.5, 0.9], index=["A", "B", "C"])
    curr = pd.Series([0.9, 0.5, 0.1], index=["A", "B", "C"])
    assert turnover(prev, curr) > 0.5


def test_turnover_nan_with_no_common_names():
    a = pd.Series([0.5], index=["A"])
    b = pd.Series([0.5], index=["B"])
    result = turnover(a, b)
    assert result != result  # NaN


def test_probabilistic_sharpe_ratio_higher_sr_gives_higher_psr():
    low = probabilistic_sharpe_ratio(sr=0.01, n_obs=100)
    high = probabilistic_sharpe_ratio(sr=0.1, n_obs=100)
    assert high > low


def test_deflated_sharpe_ratio_falls_back_to_psr_with_one_trial():
    sr, n = 0.05, 80
    dsr = deflated_sharpe_ratio(sr, n, n_trials=1, sr_variance_across_trials=0.0)
    psr = probabilistic_sharpe_ratio(sr, n)
    assert dsr == pytest.approx(psr)


def test_deflated_sharpe_ratio_penalizes_more_trials():
    sr, n = 0.15, 100
    dsr_few = deflated_sharpe_ratio(sr, n, n_trials=2, sr_variance_across_trials=0.01)
    dsr_many = deflated_sharpe_ratio(sr, n, n_trials=100, sr_variance_across_trials=0.01)
    assert dsr_many < dsr_few  # more trials tried -> harder to call it skill


def test_sharpe_of_returns_zero_for_zero_mean():
    r = np.array([0.01, -0.01, 0.01, -0.01])
    assert sharpe_of_returns(r) == pytest.approx(0.0, abs=1e-9)
