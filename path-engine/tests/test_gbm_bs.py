"""PATH-06: GBM Monte Carlo European call vs Black-Scholes closed form, and
put-call parity within Monte Carlo error."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.engine.pricer import price_from_paths
from pe.payoffs.closed_form import bs_price

S0, r, q, sigma, T = 100.0, 0.03, 0.01, 0.22, 0.75
K = 105.0


def _vanilla(option_type):
    def payoff(paths):
        S_T = paths[:, -1]
        phi = 1.0 if option_type == "call" else -1.0
        return np.maximum(phi * (S_T - K), 0.0)

    return payoff


def test_gbm_european_call_matches_black_scholes():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=50, n_paths=200_000, seed=1, antithetic=True)
    result = price_from_paths(paths, _vanilla("call"), r, T, antithetic=True)
    reference = bs_price(S0, K, r, q, sigma, T, "call")
    assert result.within(reference, n_sigma=4.0), (
        f"MC {result.price:.6f} +/- {result.std_error:.6f} vs BS {reference:.6f}"
    )
    # tolerance is tied to the reported SE, not a fixed magic number
    assert abs(result.price - reference) < 4.0 * result.std_error


def test_gbm_european_put_matches_black_scholes():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=50, n_paths=200_000, seed=2, antithetic=True)
    result = price_from_paths(paths, _vanilla("put"), r, T, antithetic=True)
    reference = bs_price(S0, K, r, q, sigma, T, "put")
    assert result.within(reference, n_sigma=4.0)


def test_put_call_parity_within_mc_error():
    """C - P = S0*exp(-qT) - K*exp(-rT), a model-free identity -- check it
    holds on the SAME simulated paths (common random numbers) within a
    combined standard error, which is a much tighter test than checking
    each leg against Black-Scholes separately."""
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=50, n_paths=200_000, seed=3, antithetic=True)
    call_result = price_from_paths(paths, _vanilla("call"), r, T, antithetic=True)
    put_result = price_from_paths(paths, _vanilla("put"), r, T, antithetic=True)

    lhs = call_result.price - put_result.price
    rhs = S0 * np.exp(-q * T) - K * np.exp(-r * T)
    combined_se = np.sqrt(call_result.std_error**2 + put_result.std_error**2)
    assert abs(lhs - rhs) < 4.0 * combined_se, f"parity gap {lhs - rhs:.6f} vs combined SE {combined_se:.6f}"


def test_mc_result_never_lacks_a_standard_error():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=10, n_paths=1000, seed=4, antithetic=False)
    result = price_from_paths(paths, _vanilla("call"), r, T, antithetic=False)
    assert result.std_error > 0.0
    assert not np.isnan(result.std_error)
    lo, hi = result.ci95()
    assert lo < result.price < hi
