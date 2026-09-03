"""PATH-06: geometric Asian MC vs the Kemna-Vorst closed form, and the
geometric-Asian control variate reducing arithmetic-Asian standard error."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.engine.mc import mc_stats_antithetic, control_variate_adjust
from pe.payoffs.asian import arithmetic_asian_payoff, geometric_asian_payoff
from pe.payoffs.closed_form import geometric_asian_price_bs

S0, r, q, sigma, T = 100.0, 0.02, 0.0, 0.30, 1.0
K = 100.0
N_STEPS = 52  # weekly fixings


def test_geometric_asian_mc_matches_closed_form():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=N_STEPS, n_paths=200_000, seed=10, antithetic=True)
    payoff = geometric_asian_payoff(paths, K, option_type="call", strike_type="fixed")
    disc = np.exp(-r * T) * payoff
    result = mc_stats_antithetic(disc)
    reference = geometric_asian_price_bs(S0, K, r, q, sigma, T, n_fixings=N_STEPS, option_type="call")
    assert result.within(reference, n_sigma=4.0), f"MC {result.price} +/- {result.std_error} vs {reference}"


def test_geometric_asian_put_matches_closed_form():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=N_STEPS, n_paths=200_000, seed=11, antithetic=True)
    payoff = geometric_asian_payoff(paths, K, option_type="put", strike_type="fixed")
    disc = np.exp(-r * T) * payoff
    result = mc_stats_antithetic(disc)
    reference = geometric_asian_price_bs(S0, K, r, q, sigma, T, n_fixings=N_STEPS, option_type="put")
    assert result.within(reference, n_sigma=4.0)


def test_geometric_asian_control_variate_reduces_variance_for_arithmetic_asian():
    """The whole point of using the geometric Asian as a control variate:
    the arithmetic Asian's Monte Carlo standard error with the control
    applied should be materially smaller than without it, on the identical
    simulated paths (so the comparison isn't contaminated by different
    random draws)."""
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=N_STEPS, n_paths=100_000, seed=12, antithetic=True)
    arith_payoff = arithmetic_asian_payoff(paths, K, option_type="call", strike_type="fixed")
    geo_payoff = geometric_asian_payoff(paths, K, option_type="call", strike_type="fixed")
    disc = np.exp(-r * T)

    plain = mc_stats_antithetic(disc * arith_payoff)

    # the control's true mean must be supplied in the SAME (discounted)
    # units as the discounted control cashflow passed below
    control_true_mean_discounted = geometric_asian_price_bs(S0, K, r, q, sigma, T, n_fixings=N_STEPS, option_type="call")

    cv_result = control_variate_adjust(
        disc * arith_payoff, disc * geo_payoff, control_true_mean_discounted, antithetic=True
    )

    assert cv_result.std_error < plain.std_error, (
        f"control variate should reduce SE: plain={plain.std_error:.6f} cv={cv_result.std_error:.6f}"
    )
    # prices should agree closely (both unbiased estimators of the same quantity)
    assert abs(cv_result.price - plain.price) < 5.0 * max(plain.std_error, cv_result.std_error)
    assert cv_result.meta["control_variate"] is True
    assert cv_result.meta["beta"] > 0.0  # arithmetic and geometric Asian payoffs are positively correlated
