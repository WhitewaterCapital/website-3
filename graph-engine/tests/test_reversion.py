"""Tests for ge.reversion — mirrors intra-exitus-engine/tests/test_ou.py
almost verbatim, since the math (and its honesty gate) is duplicated on
purpose from ie/levels/ou.py. If this suite passes, the estimator this engine
relies on for its half-life claim behaves exactly like the one already proven
out in Intra/Exitus."""

from __future__ import annotations

import numpy as np
import pytest

from ge.reversion import DF_CRIT_5PCT, fit_ou, simulate_ou


def test_recovers_known_parameters():
    mu, theta, sigma = 4.0, 0.05, 0.2
    x = simulate_ou(40_000, mu=mu, theta=theta, sigma=sigma, dt=1.0, seed=1)
    p = fit_ou(x, dt=1.0)
    assert p.reverts
    assert p.mu == pytest.approx(mu, abs=0.05)
    assert p.theta == pytest.approx(theta, rel=0.10)
    assert p.sigma_eq == pytest.approx(sigma / np.sqrt(2 * theta), rel=0.10)
    assert p.half_life == pytest.approx(np.log(2) / theta, rel=0.10)


def test_faster_reversion_shorter_half_life():
    slow = fit_ou(simulate_ou(40_000, 0.0, 0.02, 0.2, seed=2))
    fast = fit_ou(simulate_ou(40_000, 0.0, 0.20, 0.2, seed=3))
    assert fast.half_life < slow.half_life
    assert fast.theta > slow.theta


def test_random_walk_low_false_positive_rate():
    n_seeds = 200
    fp = sum(
        fit_ou(np.cumsum(np.random.default_rng(1000 + s).normal(0, 1.0, 120))).reverts
        for s in range(n_seeds)
    )
    rate = fp / n_seeds
    assert rate < 0.15, f"random-walk false-positive rate too high: {rate}"


def test_strong_reverter_is_accepted():
    n_seeds = 50
    hits = sum(
        fit_ou(simulate_ou(250, mu=0.0, theta=0.10, sigma=0.2, seed=2000 + s)).reverts
        for s in range(n_seeds)
    )
    assert hits / n_seeds > 0.8, f"true reverter accepted too rarely: {hits}/{n_seeds}"


def test_df_stat_exposed():
    p = fit_ou(simulate_ou(5000, mu=0.0, theta=0.08, sigma=0.2, seed=42))
    assert np.isfinite(p.se_b) and p.se_b > 0
    assert p.df_stat < 0


def test_recovers_mean_offset():
    p = fit_ou(simulate_ou(40_000, mu=123.0, theta=0.08, sigma=1.0, seed=5))
    assert p.reverts
    assert p.mu == pytest.approx(123.0, abs=0.3)


def test_r2_tracks_persistence_not_reversion():
    slow = fit_ou(simulate_ou(20_000, 0.0, 0.01, 0.2, seed=6))
    fast = fit_ou(simulate_ou(20_000, 0.0, 0.30, 0.2, seed=7))
    assert slow.r2 > fast.r2
    assert slow.half_life > fast.half_life


def test_too_short_raises():
    with pytest.raises(ValueError):
        fit_ou(np.arange(5.0))


def test_degenerate_series_raises():
    with pytest.raises(ValueError):
        fit_ou(np.ones(30))


def test_df_crit_matches_intra_exitus_constant():
    # Same duplicated constant, same value -- not re-derived independently.
    assert DF_CRIT_5PCT == pytest.approx(-2.86)
