"""Tests for the 'truth machine': leakage-safe splits, metrics, and that the
backtest recovers signal when it exists and finds none when it doesn't."""

import numpy as np
import pandas as pd

from incepta.validation.splits import purged_walk_forward, purged_kfold
from incepta.validation.metrics import (
    information_coefficient, rank_ic, deflated_sharpe_ratio,
    probabilistic_sharpe_ratio, sharpe, sortino,
    historical_var, expected_shortfall,
)
from incepta.backtest.engine import cross_sectional_backtest


# ---- splits: prove no leakage --------------------------------------------
def test_walk_forward_train_is_past_and_purged():
    horizon = 5
    for train, test in purged_walk_forward(200, n_splits=4, label_horizon=horizon):
        assert train.max() < test.min()                 # train strictly before test
        assert test.min() - train.max() >= horizon      # purge gap respected


def test_kfold_purge_and_embargo_no_overlap():
    horizon, embargo = 3, 2
    for train, test in purged_kfold(100, n_splits=5, label_horizon=horizon, embargo=embargo):
        assert len(set(train) & set(test)) == 0         # never overlap
        lo, hi = test.min() - horizon, test.max() + embargo
        assert not any(lo <= i <= hi for i in train)     # purge+embargo band excluded


# ---- metrics -------------------------------------------------------------
def test_ic_perfect_and_rank_ic_monotonic():
    x = np.arange(50).astype(float)
    assert abs(information_coefficient(x, x) - 1.0) < 1e-9
    assert abs(rank_ic(x, np.exp(x / 50)) - 1.0) < 1e-9   # monotone transform → rank IC 1


def test_deflated_sharpe_penalises_more_trials():
    # same observed SR, more trials searched → lower confidence it's real
    common = dict(sr=0.12, n_obs=1000, sr_variance_across_trials=0.01,
                  skew=0.0, kurt=3.0)
    dsr_few = deflated_sharpe_ratio(n_trials=5, **common)
    dsr_many = deflated_sharpe_ratio(n_trials=500, **common)
    assert 0.0 <= dsr_many <= dsr_few <= 1.0
    assert dsr_few > dsr_many


def test_psr_bounds():
    p = probabilistic_sharpe_ratio(sr=0.1, n_obs=500)
    assert 0.0 <= p <= 1.0


def test_dsr_single_trial_does_not_crash():
    # n_trials=1 must NOT hit inv_cdf(0); it falls back to PSR vs 0.
    d = deflated_sharpe_ratio(sr=0.1, n_obs=500, n_trials=1,
                             sr_variance_across_trials=0.01)
    assert 0.0 <= d <= 1.0
    assert abs(d - probabilistic_sharpe_ratio(0.1, 500)) < 1e-12


def test_sortino_known_answer():
    r = [0.02, -0.01, 0.03, -0.02]           # mean 0.005
    # downside = [0,-0.01,0,-0.02]; mean(sq)=0.000125; dd=0.0111803
    assert abs(sortino(r, periods_per_year=1) - 0.005 / (0.000125 ** 0.5)) < 1e-9


def test_var_and_es_relationship():
    r = [-0.10] + [0.01] * 9                  # one -10% tail, rest +1%
    var = historical_var(r, alpha=0.9)
    es = expected_shortfall(r, alpha=0.9)
    assert es >= var                          # ES is always >= VaR
    assert abs(es - 0.10) < 1e-9              # the tail loss averages -10%


# ---- backtest: signal vs no-signal ---------------------------------------
def _panel(seed, signal_strength):
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(60):                      # 60 monthly rebalances
        for i in range(60):                  # 60 names
            score = rng.normal()
            fwd = signal_strength * score + rng.normal(0, 1.0)
            rows.append({"date": t, "id": i, "score": score, "fwd_ret": fwd / 100.0})
    return pd.DataFrame(rows)


def test_backtest_recovers_positive_signal():
    res = cross_sectional_backtest(_panel(0, signal_strength=1.5), long_short=True)
    assert res.mean_rank_ic > 0.05
    assert res.cum_return > 0


def test_backtest_finds_no_edge_in_noise():
    res = cross_sectional_backtest(_panel(1, signal_strength=0.0), long_short=True)
    assert abs(res.mean_rank_ic) < 0.05      # honest: no signal → ~zero IC
