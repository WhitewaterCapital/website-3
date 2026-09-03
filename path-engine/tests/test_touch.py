"""PATH-03/PATH-06: first-passage / touch payoffs. Down/up-touch
probability under GBM has a known closed form (reflection principle) used
here as an independent reference."""
from __future__ import annotations

import numpy as np
from scipy.stats import norm

from pe.engine.gbm import simulate_gbm_paths
from pe.payoffs.touch import expected_time_to_touch, touch_probability, touch_then_recover_probability

S0, r, q, sigma, T = 100.0, 0.03, 0.0, 0.30, 1.0


def _closed_form_touch_probability(S0, H, mu, sigma, T, direction):
    """P(continuous GBM path with drift `mu` (i.e. d ln S = (mu - .5 sigma^2)dt + sigma dW)
    ever hits level H by time T) -- standard reflection-principle result
    (e.g. Shreve, "Stochastic Calculus for Finance II", Ch. 7). Writing
    X_t = ln(S_t/S0) (drift nu = mu - 0.5 sigma^2) and b = ln(H/S0):

        P(min X <= b) = N(d) + (H/S0)^(2 nu/sigma^2) N(d2),   b <= 0 (down)
        P(max X >= b) = N(-d) + (H/S0)^(2 nu/sigma^2) N(-d2), b >= 0 (up)

    with d = (b - nu*T)/(sigma*sqrt(T)), d2 = (b + nu*T)/(sigma*sqrt(T)) in
    both cases (the up-barrier result follows from applying the down-barrier
    reflection identity to the mirrored process -X, drift -nu, level -b).
    """
    nu = mu - 0.5 * sigma * sigma
    sT = sigma * np.sqrt(T)
    b = np.log(H / S0)
    d = (b - nu * T) / sT
    d2 = (b + nu * T) / sT
    coeff = (H / S0) ** (2 * nu / sigma**2)
    if direction == "down":
        return norm.cdf(d) + coeff * norm.cdf(d2)
    return norm.cdf(-d) + coeff * norm.cdf(-d2)


def test_bridge_corrected_down_touch_probability_matches_reflection_principle():
    H = 80.0
    reference = _closed_form_touch_probability(S0, H, r - q, sigma, T, "down")
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 100, 200_000, seed=80, antithetic=True, use_sobol=False)
    times = np.linspace(0.0, T, 101)
    corrected = touch_probability(paths, H, "down", times=times, sigma_path=sigma)
    assert corrected.within(reference, n_sigma=4.5), (
        f"corrected {corrected.price:.5f} +/- {corrected.std_error:.5f} vs {reference:.5f}"
    )


def test_bridge_corrected_up_touch_probability_matches_reflection_principle():
    H = 120.0
    reference = _closed_form_touch_probability(S0, H, r - q, sigma, T, "up")
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 100, 200_000, seed=85, antithetic=True, use_sobol=False)
    times = np.linspace(0.0, T, 101)
    corrected = touch_probability(paths, H, "up", times=times, sigma_path=sigma)
    assert corrected.within(reference, n_sigma=4.5)


def test_bridge_correction_shrinks_discrete_monitoring_gap_for_touch_probability():
    """Same demonstration as the barrier test: discrete monitoring must
    UNDERSTATE touch probability relative to continuous monitoring, and the
    bridge correction must shrink that gap on the same paths."""
    H = 80.0
    reference = _closed_form_touch_probability(S0, H, r - q, sigma, T, "down")
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 100, 200_000, seed=86, antithetic=True, use_sobol=False)
    times = np.linspace(0.0, T, 101)

    naive = touch_probability(paths, H, "down")
    corrected = touch_probability(paths, H, "down", times=times, sigma_path=sigma)

    assert naive.price < reference, "naive discrete monitoring should understate touch probability"
    naive_gap = abs(naive.price - reference)
    corrected_gap = abs(corrected.price - reference)
    assert corrected_gap < naive_gap
    assert naive_gap > 3.0 * naive.std_error


def test_touch_probability_reports_binomial_style_standard_error():
    """`touch_probability` routes a 0/1 indicator through the generic
    `mc_stats` (ddof=1 sample std / sqrt(n)) rather than a hand-rolled
    binomial formula -- check it against that exact same ddof=1
    computation on the underlying indicator array, not the (very slightly
    different, ddof=0) textbook p(1-p)/n formula."""
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 100, 50_000, seed=81, antithetic=False)
    result = touch_probability(paths, 80.0, "down")
    hit = paths <= 80.0
    touched = np.any(hit, axis=1).astype(float)
    expected_se = float(np.std(touched, ddof=1) / np.sqrt(touched.shape[0]))
    assert abs(result.std_error - expected_se) < 1e-9
    assert abs(result.price - float(np.mean(touched))) < 1e-12


def test_expected_time_to_touch_is_conditional_and_reports_touch_count():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 100, 50_000, seed=82, antithetic=False)
    times = np.linspace(0.0, T, 101)
    result = expected_time_to_touch(paths, times, 80.0, "down")
    assert 0.0 < result.price <= T
    assert 0 < result.meta["n_touched"] <= paths.shape[0]
    assert 0.0 < result.meta["touch_probability"] <= 1.0


def test_expected_time_to_touch_raises_when_nothing_touches():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 20, 500, seed=83, antithetic=False)
    times = np.linspace(0.0, T, 21)
    try:
        expected_time_to_touch(paths, times, 1.0, "down")  # essentially unreachable level
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_touch_then_recover_probability_is_bounded_by_touch_probability():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, 200, 100_000, seed=84, antithetic=False)
    touch_result = touch_probability(paths, 85.0, "down")
    recover_result = touch_then_recover_probability(paths, 85.0, "down", 95.0)
    assert recover_result.price <= touch_result.price + 3 * recover_result.std_error
    assert recover_result.price >= 0.0
