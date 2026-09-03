"""PATH-02b: Dupire local vol reprices its OWN calibration surface within
Monte Carlo tolerance -- the only "calibration" here is the closed-form
Dupire identity (see `pe/engine/localvol.py`), so this is really a test
that the Euler-discretized simulation of that identity doesn't drift away
from it."""
from __future__ import annotations

import numpy as np

from pe.engine.localvol import LocalVolParams, simulate_local_vol_paths
from pe.engine.mc import mc_stats_antithetic
from pe.payoffs.closed_form import bs_price
from pe.surface.svi import SVIParams, svi_term_structure_surface

S0, r, q = 100.0, 0.02, 0.0


def _surface():
    k_grid = np.linspace(-0.8, 0.8, 61)
    T_grid = np.array([0.25, 0.5, 1.0])
    base = SVIParams(a=0.015, b=0.12, rho=-0.35, m=0.0, sigma=0.30)
    atm_w = np.array([0.22**2 * T for T in T_grid])
    return svi_term_structure_surface(k_grid, T_grid, base, atm_w)


def _bs_reference_from_surface(surface, T, K):
    k = np.log(K / (S0 * np.exp((r - q) * T)))
    iv = surface.implied_vol(k, T)
    return bs_price(S0, K, r, q, iv, T, "call")


def test_local_vol_reprices_atm_vanilla_at_calibration_maturity():
    surface = _surface()
    T = 0.5
    K = S0  # ATM
    params = LocalVolParams(surface=surface, S0=S0, r=r, q=q)
    _, paths, _ = simulate_local_vol_paths(params, T, n_steps=100, n_paths=200_000, seed=30, antithetic=True)

    payoff = np.maximum(paths[:, -1] - K, 0.0)
    disc = np.exp(-r * T) * payoff
    result = mc_stats_antithetic(disc)
    reference = _bs_reference_from_surface(surface, T, K)
    assert result.within(reference, n_sigma=4.0), (
        f"local-vol MC {result.price:.5f} +/- {result.std_error:.5f} vs surface-implied BS {reference:.5f}"
    )


def test_local_vol_reprices_otm_and_itm_strikes():
    surface = _surface()
    T = 1.0
    params = LocalVolParams(surface=surface, S0=S0, r=r, q=q)
    _, paths, _ = simulate_local_vol_paths(params, T, n_steps=100, n_paths=200_000, seed=31, antithetic=True)
    S_T = paths[:, -1]
    disc = np.exp(-r * T)

    for K in (80.0, 100.0, 125.0):
        payoff = np.maximum(S_T - K, 0.0)
        result = mc_stats_antithetic(disc * payoff)
        reference = _bs_reference_from_surface(surface, T, K)
        assert result.within(reference, n_sigma=4.5), (
            f"K={K}: local-vol MC {result.price:.5f} +/- {result.std_error:.5f} vs {reference:.5f}"
        )


def test_local_variance_is_nonnegative_on_the_calibration_grid():
    from pe.engine.localvol import local_variance

    surface = _surface()
    for T in surface.T_grid:
        var = local_variance(surface, surface.k_grid, float(T))
        assert np.all(var >= 0.0)
        assert np.all(np.isfinite(var))
