"""Cost-aware backtest mechanics, and the residual-as-signal backtest applied
to the pipeline's own output."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ge.backtest import BacktestConfig, backtest_residual
from ge.config import GraphConfig
from ge.pipeline import PipelineConfig, run_history
from ge.synthetic import make_synthetic_panel


def _predictive_panel(n_dates=60, n_names=20, noise=0.3, seed=0) -> pd.DataFrame:
    """A synthetic panel where `score` genuinely predicts `fwd_ret` (positive
    relationship, plus noise) -- the backtest MUST find a positive edge here."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        score = rng.normal(size=n_names)
        fwd = 0.01 * score + rng.normal(scale=noise, size=n_names) * 0.01
        for i in range(n_names):
            rows.append({"date": d, "ticker": f"T{i}", "score": score[i], "fwd_ret": fwd[i]})
    return pd.DataFrame(rows)


def _random_panel(n_dates=60, n_names=20, seed=0) -> pd.DataFrame:
    """No true relationship between score and fwd_ret."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        score = rng.normal(size=n_names)
        fwd = rng.normal(scale=0.01, size=n_names)
        for i in range(n_names):
            rows.append({"date": d, "ticker": f"T{i}", "score": score[i], "fwd_ret": fwd[i]})
    return pd.DataFrame(rows)


def test_first_rebalance_has_full_turnover():
    panel = _predictive_panel(n_dates=3, n_names=10, seed=1)
    res = backtest_residual(panel, BacktestConfig(quantile=0.2, cost_bps=0.0))
    assert res.turnover_series[0] == pytest.approx(1.0)


def test_cost_reduces_net_return_relative_to_gross():
    panel = _predictive_panel(n_dates=40, n_names=20, seed=2)
    free = backtest_residual(panel, BacktestConfig(quantile=0.2, cost_bps=0.0))
    costly = backtest_residual(panel, BacktestConfig(quantile=0.2, cost_bps=200.0))
    assert costly.cum_return < free.cum_return
    np.testing.assert_allclose(free.gross_returns, costly.gross_returns)


def test_predictive_score_yields_positive_rank_ic():
    panel = _predictive_panel(n_dates=60, n_names=25, seed=3)
    res = backtest_residual(panel, BacktestConfig(quantile=0.2, cost_bps=10.0))
    assert res.mean_rank_ic > 0.3
    assert res.net_sharpe > 0


def test_random_score_yields_near_zero_rank_ic():
    panel = _random_panel(n_dates=60, n_names=25, seed=4)
    res = backtest_residual(panel, BacktestConfig(quantile=0.2, cost_bps=10.0))
    assert abs(res.mean_rank_ic) < 0.15


def test_too_few_names_per_date_is_skipped_not_crashed():
    # A single name per date can't form a long leg AND a short leg
    # (n_leg=1 needs at least 2 names) -- must be skipped, not crash.
    panel = pd.DataFrame({"date": [1], "ticker": ["A"], "score": [1.0], "fwd_ret": [0.01]})
    res = backtest_residual(panel, BacktestConfig(quantile=0.4))
    assert res.n_rebalances == 0
    assert res.summary()["net_sharpe"] is None


@pytest.mark.parametrize("horizon", [1, 3, 5, 10])
def test_residual_backtest_across_1_to_10_day_horizons(horizon):
    # Full pipeline: build residuals, then a forward return over `horizon`
    # trading days computed AFTER each date (point-in-time), fade the
    # residual (score = -residual_z), and backtest with realistic costs.
    prices, sector_of = make_synthetic_panel(n_sectors=4, per_sector=6, n_days=220, seed=5)
    cfg = PipelineConfig(graph=GraphConfig(top_k=6, corr_window=40), signal_window=5, refresh_every=5)
    hist = run_history(prices, sector_of, cfg)

    fwd_ret = prices.pct_change(horizon).shift(-horizon)  # starts AFTER `date`, PIT-safe
    fwd_long = fwd_ret.stack().rename("fwd_ret").reset_index()
    fwd_long.columns = ["date", "ticker", "fwd_ret"]

    panel = hist.merge(fwd_long, on=["date", "ticker"], how="inner").dropna(subset=["fwd_ret"])
    panel = panel.assign(score=-panel["residual_z_sector_neutral"])

    res = backtest_residual(panel, BacktestConfig(horizon=horizon, cost_bps=10.0))
    # Just needs to run cleanly end-to-end and produce finite, well-formed output.
    assert res.n_rebalances > 0
    assert np.isfinite(res.avg_turnover)
    summary = res.summary()
    assert "net_sharpe" in summary and "cum_return" in summary
