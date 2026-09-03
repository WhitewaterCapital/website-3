"""PATH-06 + PATH-04: continuous-monitoring barrier MC vs the analytic
Reiner-Rubinstein closed form, and a direct demonstration that the
Brownian-bridge correction removes the discrete-monitoring bias a raw
endpoint check leaves behind."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.payoffs.barrier import barrier_payoff
from pe.payoffs.closed_form import barrier_price_bs

S0, r, q, sigma, T = 100.0, 0.02, 0.0, 0.25, 1.0
K = 100.0
H_down = 85.0
H_up = 120.0
N_STEPS = 20  # deliberately coarse, so the discrete-monitoring bias is visible
N_PATHS = 300_000


def _mc_result(payoff, r, T):
    from pe.engine.mc import mc_stats_antithetic

    disc = np.exp(-r * T) * payoff
    return mc_stats_antithetic(disc)


def test_bridge_corrected_down_and_out_call_matches_analytic():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, N_STEPS, N_PATHS, seed=20, antithetic=True)
    times = np.linspace(0.0, T, N_STEPS + 1)
    payoff = barrier_payoff(
        paths, K, H_down, "call", "down", "out", times=times, sigma_path=sigma
    )
    result = _mc_result(payoff, r, T)
    reference = barrier_price_bs(S0, K, H_down, r, q, sigma, T, "call", "down", "out")
    assert result.within(reference, n_sigma=4.0), f"MC {result.price:.5f}+/-{result.std_error:.5f} vs {reference:.5f}"


def test_bridge_corrected_up_and_out_put_matches_analytic():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, N_STEPS, N_PATHS, seed=21, antithetic=True)
    times = np.linspace(0.0, T, N_STEPS + 1)
    payoff = barrier_payoff(paths, K, H_up, "put", "up", "out", times=times, sigma_path=sigma)
    result = _mc_result(payoff, r, T)
    reference = barrier_price_bs(S0, K, H_up, r, q, sigma, T, "put", "up", "out")
    assert result.within(reference, n_sigma=4.0)


def test_bridge_correction_reduces_discrete_monitoring_bias():
    """The whole reason this correction exists: a raw discrete-endpoint
    check systematically overprices a down-and-out (understates knockout
    frequency) relative to continuous monitoring, and the bridge-corrected
    estimator should sit materially closer to the continuous analytic
    value than the naive discrete estimator does, on the SAME paths."""
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, N_STEPS, N_PATHS, seed=22, antithetic=True)
    times = np.linspace(0.0, T, N_STEPS + 1)

    naive_payoff = barrier_payoff(paths, K, H_down, "call", "down", "out")  # no times/sigma -> discrete only
    corrected_payoff = barrier_payoff(paths, K, H_down, "call", "down", "out", times=times, sigma_path=sigma)

    naive_result = _mc_result(naive_payoff, r, T)
    corrected_result = _mc_result(corrected_payoff, r, T)
    reference = barrier_price_bs(S0, K, H_down, r, q, sigma, T, "call", "down", "out")

    naive_gap = abs(naive_result.price - reference)
    corrected_gap = abs(corrected_result.price - reference)

    # naive discrete monitoring should overprice a down-and-out relative to
    # continuous monitoring (it under-detects knockouts) -- confirm the
    # DIRECTION of the bias, not just its existence.
    assert naive_result.price > reference, (
        f"expected naive discrete monitoring to overprice the down-and-out: "
        f"naive={naive_result.price:.5f} reference={reference:.5f}"
    )
    assert corrected_gap < naive_gap, (
        f"bridge correction should shrink the gap to the continuous reference: "
        f"naive_gap={naive_gap:.5f} corrected_gap={corrected_gap:.5f}"
    )
    # the naive bias should be well outside its own MC noise -- otherwise
    # this "bias" would just be sampling error, not a real discretization effect
    assert naive_gap > 3.0 * naive_result.std_error


def test_knock_in_plus_knock_out_equals_vanilla_on_same_paths():
    """Model-free identity (zero rebate): in + out = vanilla. Check it
    holds on simulated paths using the SAME bridge-corrected payoff
    machinery, as an internal consistency check independent of the
    analytic reference."""
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, N_STEPS, N_PATHS, seed=23, antithetic=True)
    times = np.linspace(0.0, T, N_STEPS + 1)

    out_payoff = barrier_payoff(paths, K, H_down, "call", "down", "out", times=times, sigma_path=sigma)
    in_payoff = barrier_payoff(paths, K, H_down, "call", "down", "in", times=times, sigma_path=sigma)
    vanilla_payoff = np.maximum(paths[:, -1] - K, 0.0)

    np.testing.assert_allclose(out_payoff + in_payoff, vanilla_payoff, atol=1e-8)


def test_all_eight_barrier_combinations_are_nonnegative_and_bounded_by_vanilla():
    """Sanity sweep over all up/down x in/out x call/put combinations: every
    combination must produce a nonnegative payoff no larger than the
    corresponding vanilla (a barrier restricts payoff, it never enhances
    it, since there's no rebate)."""
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, N_STEPS, 20_000, seed=24, antithetic=True)
    times = np.linspace(0.0, T, N_STEPS + 1)

    for option_type in ("call", "put"):
        vanilla = np.maximum((1.0 if option_type == "call" else -1.0) * (paths[:, -1] - K), 0.0)
        for direction, H in (("down", H_down), ("up", H_up)):
            for kind in ("in", "out"):
                payoff = barrier_payoff(paths, K, H, option_type, direction, kind, times=times, sigma_path=sigma)
                assert np.all(payoff >= -1e-9), (option_type, direction, kind)
                assert np.all(payoff <= vanilla + 1e-9), (option_type, direction, kind)
