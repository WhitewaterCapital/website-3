"""PATH-03 + PATH-06: Longstaff-Schwartz American/Bermudan pricing.

Checks: (1) American put >= European put (early exercise is an option, so
it cannot be worth less); (2) with only ONE exercise date (maturity), LSM
must reduce exactly to the European price; (3) the well-known in-sample
regression bias runs upward and grows with the basis's degree, checked
directly rather than assumed."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.payoffs.american import american_option_lsm
from pe.payoffs.closed_form import bs_price
from pe.engine.mc import mc_stats

S0, r, q, sigma, T = 100.0, 0.04, 0.0, 0.35, 1.0
K = 105.0
N_STEPS = 50


def _paths(seed):
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, N_STEPS, 100_000, seed, antithetic=True)
    times = np.linspace(0.0, T, N_STEPS + 1)
    return paths, times


def test_american_put_is_at_least_the_european_put():
    paths, times = _paths(70)
    american = american_option_lsm(paths, times, K, r, option_type="put", basis_degree=3)
    european_ref = bs_price(S0, K, r, q, sigma, T, "put")
    # allow a little slack for MC noise on the American estimate; the
    # inequality itself should hold well outside that noise for a put this
    # deep in early-exercise territory (positive rate, no dividend: an
    # American put's early-exercise premium is real and not a rounding effect)
    assert american.price > european_ref - 3.0 * american.std_error


def test_single_exercise_date_reduces_to_european():
    """With exercise_idx = [n_steps] only (exercise permitted solely at
    maturity), LSM has no continuation decision to make at all -- it must
    reduce exactly to the discounted terminal payoff, i.e. the plain
    European Monte Carlo price."""
    paths, times = _paths(71)
    result = american_option_lsm(paths, times, K, r, option_type="put", basis_degree=3, exercise_idx=np.array([N_STEPS]))
    disc_terminal = np.exp(-r * T) * np.maximum(K - paths[:, -1], 0.0)
    plain = mc_stats(disc_terminal)
    assert abs(result.price - plain.price) < 1e-9
    assert abs(result.std_error - plain.std_error) < 1e-9


def test_lsm_upward_bias_grows_with_basis_degree():
    """The documented bias (see `pe/payoffs/american.py`): on the SAME
    simulated paths, a higher-degree polynomial basis has more freedom to
    overfit the in-sample continuation-value regression, which can only
    push the estimated price up (or leave it unchanged), never down, on
    average across independent path sets. Check this directly by averaging
    over several independent path sets rather than trusting a single draw."""
    low_prices = []
    high_prices = []
    for seed in range(60, 65):
        paths, times = _paths(seed)
        low = american_option_lsm(paths, times, K, r, option_type="put", basis_degree=1)
        high = american_option_lsm(paths, times, K, r, option_type="put", basis_degree=9)
        low_prices.append(low.price)
        high_prices.append(high.price)
    assert np.mean(high_prices) >= np.mean(low_prices), (
        f"expected higher-degree basis to be biased upward on average: "
        f"degree1={np.mean(low_prices):.5f} degree9={np.mean(high_prices):.5f}"
    )


def test_lsm_reports_a_standard_error():
    paths, times = _paths(72)
    result = american_option_lsm(paths, times, K, r, option_type="put", basis_degree=3)
    assert result.std_error > 0.0
    assert not np.isnan(result.std_error)
