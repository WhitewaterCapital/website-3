"""PATH-06: point-in-time determinism -- the same seed and inputs must
reproduce byte-identical paths and prices, across every engine in this
package. This is what makes a reported price auditable rather than "roughly
reproducible.\""""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.engine.heston import HestonParams, simulate_heston_qe_paths, simulate_qe_variance
from pe.engine.localvol import LocalVolParams, simulate_local_vol_paths
from pe.engine.bootstrap import historical_bootstrap_paths, synthetic_historical_returns
from pe.surface.svi import SVIParams, svi_term_structure_surface

S0, r, q, sigma, T = 100.0, 0.02, 0.0, 0.22, 1.0


def test_gbm_paths_are_deterministic_given_the_same_seed():
    _, paths_a, info_a = simulate_gbm_paths(S0, r, q, sigma, T, 50, 1000, seed=999, antithetic=True)
    _, paths_b, info_b = simulate_gbm_paths(S0, r, q, sigma, T, 50, 1000, seed=999, antithetic=True)
    np.testing.assert_array_equal(paths_a, paths_b)
    assert info_a == info_b


def test_gbm_paths_differ_across_seeds():
    _, paths_a, _ = simulate_gbm_paths(S0, r, q, sigma, T, 50, 1000, seed=1, antithetic=True)
    _, paths_b, _ = simulate_gbm_paths(S0, r, q, sigma, T, 50, 1000, seed=2, antithetic=True)
    assert not np.allclose(paths_a, paths_b)


def test_heston_qe_paths_are_deterministic_given_the_same_seed():
    params = HestonParams(v0=0.04, kappa=1.5, theta=0.04, xi=0.5, rho=-0.6)
    _, Sa, va, _ = simulate_heston_qe_paths(S0, r, q, params, T, 50, 1000, seed=1234)
    _, Sb, vb, _ = simulate_heston_qe_paths(S0, r, q, params, T, 50, 1000, seed=1234)
    np.testing.assert_array_equal(Sa, Sb)
    np.testing.assert_array_equal(va, vb)


def test_qe_variance_alone_is_deterministic():
    params = HestonParams(v0=0.04, kappa=1.5, theta=0.04, xi=0.5, rho=-0.6)
    _, va = simulate_qe_variance(params, T, 50, 1000, seed=55)
    _, vb = simulate_qe_variance(params, T, 50, 1000, seed=55)
    np.testing.assert_array_equal(va, vb)


def test_local_vol_paths_are_deterministic_given_the_same_seed():
    k_grid = np.linspace(-0.6, 0.6, 41)
    T_grid = np.array([0.25, 0.5, 1.0])
    base = SVIParams(a=0.02, b=0.15, rho=-0.4, m=0.0, sigma=0.25)
    atm_w = np.array([0.22**2 * t for t in T_grid])
    surface = svi_term_structure_surface(k_grid, T_grid, base, atm_w)
    params = LocalVolParams(surface=surface, S0=S0, r=r, q=q)

    _, paths_a, _ = simulate_local_vol_paths(params, T, 50, 1000, seed=321)
    _, paths_b, _ = simulate_local_vol_paths(params, T, 50, 1000, seed=321)
    np.testing.assert_array_equal(paths_a, paths_b)


def test_bootstrap_paths_are_deterministic_given_the_same_seed():
    returns = synthetic_historical_returns(1000, seed=1)
    _, paths_a, _ = historical_bootstrap_paths(returns, S0, 60, 500, seed=77)
    _, paths_b, _ = historical_bootstrap_paths(returns, S0, 60, 500, seed=77)
    np.testing.assert_array_equal(paths_a, paths_b)


def test_synthetic_historical_returns_are_deterministic_given_the_same_seed():
    a = synthetic_historical_returns(500, seed=44)
    b = synthetic_historical_returns(500, seed=44)
    np.testing.assert_array_equal(a, b)
