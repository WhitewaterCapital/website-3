"""Residual computation: diffusion-implied gap, cross-sectional z-score,
sector neutrality."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ge.config import DiffusionConfig
from ge.residual import compute_residuals


def _star_graph_weights(n: int, hub: int = 0) -> np.ndarray:
    """Every non-hub node connects only to the hub (weight 1); the hub
    connects to everyone. Simple, hand-checkable topology."""
    w = np.zeros((n, n))
    for i in range(n):
        if i != hub:
            w[i, hub] = w[hub, i] = 1.0
    return w


def test_residual_definition_actual_minus_diffused():
    n = 5
    tickers = [f"T{i}" for i in range(n)]
    sector_of = {t: "SECTOR" for t in tickers}
    w = _star_graph_weights(n)
    signal = pd.Series([10.0, 1.0, 1.0, 1.0, 1.0], index=tickers)
    rf = compute_residuals(signal, w, sector_of, DiffusionConfig(alpha=0.0, n_iters=1))
    np.testing.assert_allclose(rf.residual, rf.signal - rf.diffused)


def test_residual_z_has_zero_mean_unit_std_when_nondegenerate():
    rng = np.random.default_rng(0)
    n = 30
    tickers = [f"T{i}" for i in range(n)]
    sector_of = {t: f"S{i % 3}" for i, t in enumerate(tickers)}
    w = rng.random((n, n))
    w = (w + w.T) / 2
    np.fill_diagonal(w, 0.0)
    signal = pd.Series(rng.normal(size=n), index=tickers)
    rf = compute_residuals(signal, w, sector_of, DiffusionConfig())
    assert rf.residual_z.mean() == pytest.approx(0.0, abs=1e-9)
    assert rf.residual_z.std(ddof=0) == pytest.approx(1.0, abs=1e-9)


def test_sector_neutral_zeros_out_each_sector_mean():
    rng = np.random.default_rng(1)
    n = 24
    tickers = [f"T{i}" for i in range(n)]
    sector_of = {t: f"S{i % 4}" for i, t in enumerate(tickers)}
    w = rng.random((n, n))
    w = (w + w.T) / 2
    np.fill_diagonal(w, 0.0)
    signal = pd.Series(rng.normal(size=n), index=tickers)
    rf = compute_residuals(signal, w, sector_of, DiffusionConfig())
    df = rf.as_frame()
    df["sector"] = [sector_of[t] for t in df["ticker"]]
    sector_means = df.groupby("sector")["residual_z_sector_neutral"].mean()
    np.testing.assert_allclose(sector_means.to_numpy(), 0.0, atol=1e-9)


def test_a_diverging_name_gets_large_positive_residual():
    # One name runs away from an otherwise flat, tightly-connected group.
    n = 6
    tickers = [f"T{i}" for i in range(n)]
    sector_of = {t: "SECTOR" for t in tickers}
    rng = np.random.default_rng(2)
    w = rng.random((n, n)) * 0.5 + 0.5
    w = (w + w.T) / 2
    np.fill_diagonal(w, 0.0)
    signal = pd.Series([5.0, 0.0, 0.1, -0.1, 0.05, -0.05], index=tickers)
    rf = compute_residuals(signal, w, sector_of, DiffusionConfig())
    df = rf.as_frame().set_index("ticker")
    assert df.loc["T0", "residual_z"] == df["residual_z"].max()
    assert df.loc["T0", "residual"] > 0


def test_compute_residuals_rejects_non_finite_signal():
    n = 4
    tickers = [f"T{i}" for i in range(n)]
    sector_of = {t: "SECTOR" for t in tickers}
    w = np.ones((n, n)) - np.eye(n)
    signal = pd.Series([1.0, np.nan, 2.0, 3.0], index=tickers)
    with pytest.raises(ValueError):
        compute_residuals(signal, w, sector_of, DiffusionConfig())
