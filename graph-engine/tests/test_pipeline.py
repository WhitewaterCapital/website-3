"""Orchestration: run_as_of / run_history. PIT correctness and basic shape
checks -- the reversion-honesty integration test lives in its own file."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ge.config import GraphConfig
from ge.pipeline import PipelineConfig, run_as_of, run_history
from ge.synthetic import make_synthetic_panel, make_universe, returns_to_prices, simulate_returns


def test_run_as_of_returns_one_row_per_ticker():
    prices, sector_of = make_synthetic_panel(n_sectors=4, per_sector=5, n_days=150, seed=1)
    cfg = PipelineConfig(graph=GraphConfig(top_k=6))
    rf, graph = run_as_of(prices, sector_of, cfg)
    assert set(rf.tickers) == set(prices.columns)
    assert len(rf.tickers) == len(prices.columns)
    assert graph.sparse_weights.shape == (len(prices.columns),) * 2


def test_run_as_of_is_point_in_time():
    prices, sector_of = make_synthetic_panel(n_sectors=3, per_sector=4, n_days=150, seed=2)
    cfg = PipelineConfig(graph=GraphConfig(top_k=5))
    as_of_idx = 120
    rf1, _ = run_as_of(prices.iloc[: as_of_idx + 1], sector_of, cfg)

    mutated = prices.copy()
    mutated.iloc[as_of_idx + 1 :] *= 3.0  # rewrite the (unseen) future
    rf2, _ = run_as_of(mutated.iloc[: as_of_idx + 1], sector_of, cfg)

    np.testing.assert_allclose(rf1.residual_z_sector_neutral, rf2.residual_z_sector_neutral)


def test_run_as_of_raises_on_short_history():
    prices, sector_of = make_synthetic_panel(n_sectors=2, per_sector=3, n_days=3, seed=3)
    with pytest.raises(ValueError):
        run_as_of(prices, sector_of, PipelineConfig())


def test_run_history_produces_tidy_long_panel():
    prices, sector_of = make_synthetic_panel(n_sectors=3, per_sector=4, n_days=140, seed=4)
    cfg = PipelineConfig(graph=GraphConfig(top_k=5, corr_window=40), signal_window=5, refresh_every=5)
    hist = run_history(prices, sector_of, cfg)
    assert set(hist.columns) >= {
        "date", "ticker", "signal", "diffused", "residual",
        "residual_z", "residual_z_sector_neutral",
    }
    # every date present has exactly one row per ticker
    counts = hist.groupby("date")["ticker"].nunique()
    assert (counts == len(prices.columns)).all()
    assert hist["date"].is_monotonic_increasing or hist.sort_values("date")["date"].is_monotonic_increasing


def test_run_history_never_uses_future_prices():
    prices, sector_of = make_synthetic_panel(n_sectors=2, per_sector=4, n_days=140, seed=5)
    cfg = PipelineConfig(graph=GraphConfig(top_k=4, corr_window=40), signal_window=5, refresh_every=5)
    hist_full = run_history(prices, sector_of, cfg)

    truncate_at = 110
    truncated_prices = prices.iloc[:truncate_at]
    hist_truncated = run_history(truncated_prices, sector_of, cfg)

    common_dates = set(hist_full["date"]) & set(hist_truncated["date"])
    assert common_dates  # sanity: some overlap exists
    a = hist_full[hist_full["date"].isin(common_dates)].sort_values(["date", "ticker"]).reset_index(drop=True)
    b = hist_truncated[hist_truncated["date"].isin(common_dates)].sort_values(["date", "ticker"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(
        a[["date", "ticker", "residual_z_sector_neutral"]],
        b[["date", "ticker", "residual_z_sector_neutral"]],
    )


def test_run_history_raises_when_no_history_fits():
    prices, sector_of = make_synthetic_panel(n_sectors=2, per_sector=3, n_days=10, seed=6)
    with pytest.raises(ValueError):
        run_history(prices, sector_of, PipelineConfig())
