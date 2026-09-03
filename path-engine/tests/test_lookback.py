"""PATH-03: lookback payoffs -- structural bounds and a GBM Monte Carlo
sanity check (lookbacks have known closed forms too, but this package does
not implement the Goldman-Sosin-Gatto formula; the check here is a
model-free bound plus a floating-vs-fixed consistency check instead)."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.payoffs.lookback import lookback_payoff

S0, r, q, sigma, T = 100.0, 0.02, 0.0, 0.30, 1.0


def _paths():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=60, n_paths=20_000, seed=40, antithetic=True)
    return paths


def test_floating_lookback_call_is_always_nonnegative_and_at_least_vanilla_call_at_S0():
    paths = _paths()
    payoff = lookback_payoff(paths, "call", "floating")
    assert np.all(payoff >= 0.0)
    # S_T - running_min >= S_T - S0 (since S0 is itself a candidate for the
    # running min, running_min <= S0), so this floating lookback call
    # dominates a vanilla call struck at S0 path-by-path.
    vanilla_at_S0 = np.maximum(paths[:, -1] - S0, 0.0)
    assert np.all(payoff >= vanilla_at_S0 - 1e-9)


def test_floating_lookback_put_is_always_nonnegative_and_at_least_vanilla_put_at_S0():
    paths = _paths()
    payoff = lookback_payoff(paths, "put", "floating")
    assert np.all(payoff >= 0.0)
    vanilla_at_S0 = np.maximum(S0 - paths[:, -1], 0.0)
    assert np.all(payoff >= vanilla_at_S0 - 1e-9)


def test_fixed_strike_lookback_matches_running_extremum_definition():
    paths = _paths()
    K = 105.0
    call = lookback_payoff(paths, "call", "fixed", K=K)
    put = lookback_payoff(paths, "put", "fixed", K=K)
    np.testing.assert_allclose(call, np.maximum(paths.max(axis=1) - K, 0.0))
    np.testing.assert_allclose(put, np.maximum(K - paths.min(axis=1), 0.0))


def test_floating_lookback_rejects_a_strike():
    try:
        lookback_payoff(_paths(), "call", "floating", K=100.0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_fixed_lookback_requires_a_strike():
    try:
        lookback_payoff(_paths(), "call", "fixed", K=None)
        assert False, "expected ValueError"
    except ValueError:
        pass
