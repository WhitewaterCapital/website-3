"""PATH-06: Monte Carlo convergence rate (~1/sqrt(N)), checked empirically
via a log-log fit rather than eyeballing one or two path counts."""
from __future__ import annotations

import functools

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.engine.pricer import price_from_paths
from pe.validation.convergence import fit_convergence_rate, measure_convergence

S0, r, q, sigma, T, K = 100.0, 0.02, 0.0, 0.25, 1.0, 100.0


def _price_at(n_paths: int, antithetic: bool, seed: int = 500):
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=20, n_paths=n_paths, seed=seed, antithetic=antithetic)

    def payoff(p):
        return np.maximum(p[:, -1] - K, 0.0)

    return price_from_paths(paths, payoff, r, T, antithetic=antithetic)


def test_plain_mc_standard_error_converges_at_one_over_sqrt_n():
    n_list = [2_000, 8_000, 32_000, 128_000]
    pricer = functools.partial(_price_at, antithetic=False)
    _, ses, slope = measure_convergence(pricer, n_list)
    assert -0.65 < slope < -0.35, f"convergence slope {slope} far from the expected -0.5"


def test_antithetic_mc_standard_error_also_converges_at_one_over_sqrt_n():
    """Antithetic pairing changes the constant in front (usually shrinking
    it), not the exponent -- SE should still scale like N^-0.5 in the raw
    path count."""
    n_list = [2_000, 8_000, 32_000, 128_000]
    pricer = functools.partial(_price_at, antithetic=True)
    _, ses, slope = measure_convergence(pricer, n_list)
    assert -0.65 < slope < -0.35, f"convergence slope {slope} far from the expected -0.5"


def test_fit_convergence_rate_on_synthetic_exact_half_power_data():
    """Sanity check on the fitting utility itself: feed it data that is
    EXACTLY se = C / sqrt(n) and confirm it recovers slope = -0.5 to high
    precision (isolates the curve-fit machinery from any Monte Carlo
    noise)."""
    n_list = [100, 1_000, 10_000, 100_000]
    C = 2.5
    se_list = [C / np.sqrt(n) for n in n_list]
    slope = fit_convergence_rate(n_list, se_list)
    assert abs(slope - (-0.5)) < 1e-9
