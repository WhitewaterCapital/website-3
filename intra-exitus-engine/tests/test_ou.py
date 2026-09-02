"""Tests for the Ornstein-Uhlenbeck estimator.

The headline is parameter recovery: simulate an OU path with KNOWN mu, theta,
sigma, fit it, and require the estimator to recover them. If it can't recover
truth from data it generated itself, it can't be trusted on real prices. A random
walk must be flagged non-reverting rather than handed a fake band.
"""

from __future__ import annotations

import numpy as np
import pytest

from ie.levels.ou import fit_ou, simulate_ou


def test_recovers_known_parameters():
    mu, theta, sigma = 4.0, 0.05, 0.2
    x = simulate_ou(40_000, mu=mu, theta=theta, sigma=sigma, dt=1.0, seed=1)
    p = fit_ou(x, dt=1.0)
    assert p.reverts
    assert p.mu == pytest.approx(mu, abs=0.05)
    assert p.theta == pytest.approx(theta, rel=0.10)
    # Equilibrium std = sigma / sqrt(2 theta).
    assert p.sigma_eq == pytest.approx(sigma / np.sqrt(2 * theta), rel=0.10)
    # Half-life = ln(2)/theta.
    assert p.half_life == pytest.approx(np.log(2) / theta, rel=0.10)


def test_faster_reversion_shorter_half_life():
    slow = fit_ou(simulate_ou(40_000, 0.0, 0.02, 0.2, seed=2))
    fast = fit_ou(simulate_ou(40_000, 0.0, 0.20, 0.2, seed=3))
    assert fast.half_life < slow.half_life
    assert fast.theta > slow.theta


def test_random_walk_low_false_positive_rate():
    # A true random walk over a ~120-bar window (the engine's OU window) must be
    # flagged reverting only RARELY. The old point-estimate (b < 1) fired ~60% of
    # the time; the Dickey-Fuller gate controls this near ~5%.
    n_seeds = 200
    fp = sum(
        fit_ou(np.cumsum(np.random.default_rng(1000 + s).normal(0, 1.0, 120))).reverts
        for s in range(n_seeds)
    )
    rate = fp / n_seeds
    assert rate < 0.15, f"random-walk false-positive rate too high: {rate}"


def test_strong_reverter_is_accepted():
    # Power check: a genuinely mean-reverting OU over a realistic window is accepted
    # the large majority of the time (the DF gate rejects noise, not real signal).
    n_seeds = 50
    hits = sum(
        fit_ou(simulate_ou(250, mu=0.0, theta=0.10, sigma=0.2, seed=2000 + s)).reverts
        for s in range(n_seeds)
    )
    assert hits / n_seeds > 0.8, f"true reverter accepted too rarely: {hits}/{n_seeds}"


def test_df_stat_exposed():
    p = fit_ou(simulate_ou(5000, mu=0.0, theta=0.08, sigma=0.2, seed=42))
    assert np.isfinite(p.se_b) and p.se_b > 0
    assert p.df_stat < 0  # a reverter has b < 1 -> negative DF statistic


def test_recovers_mean_offset():
    p = fit_ou(simulate_ou(40_000, mu=123.0, theta=0.08, sigma=1.0, seed=5))
    assert p.reverts
    assert p.mu == pytest.approx(123.0, abs=0.3)


def test_r2_tracks_persistence_not_reversion():
    # Level-on-level R^2 tracks persistence: a SLOW reverter (near random walk) has
    # HIGHER R^2 than a fast reverter. This documents the diagnostic's true meaning.
    slow = fit_ou(simulate_ou(20_000, 0.0, 0.01, 0.2, seed=6))
    fast = fit_ou(simulate_ou(20_000, 0.0, 0.30, 0.2, seed=7))
    assert slow.r2 > fast.r2
    assert slow.half_life > fast.half_life


def test_too_short_raises():
    with pytest.raises(ValueError):
        fit_ou(np.arange(5.0))
