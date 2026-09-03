"""PATH-03: cliquet / forward-starting payoffs."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.payoffs.cliquet import cliquet_payoff, forward_start_payoff

S0, r, q, sigma, T = 100.0, 0.02, 0.0, 0.25, 1.0


def _paths():
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=252, n_paths=20_000, seed=50, antithetic=True)
    return paths


def test_forward_start_payoff_is_nonnegative():
    paths = _paths()
    payoff = forward_start_payoff(paths, start_index=63, option_type="call", moneyness=1.0)
    assert np.all(payoff >= 0.0)
    # ATM forward-start: payoff = max(S_T - S_63, 0)
    expected = np.maximum(paths[:, -1] - paths[:, 63], 0.0)
    np.testing.assert_allclose(payoff, expected)


def test_cliquet_globally_floored_locally_uncapped_is_never_negative():
    paths = _paths()
    reset_idx = [0, 63, 126, 189, 252]
    payoff = cliquet_payoff(paths, reset_idx, global_floor=0.0)
    assert np.all(payoff >= 0.0)


def test_cliquet_local_cap_reduces_payoff_relative_to_uncapped():
    paths = _paths()
    reset_idx = [0, 63, 126, 189, 252]
    uncapped = cliquet_payoff(paths, reset_idx, global_floor=0.0, local_cap=np.inf)
    capped = cliquet_payoff(paths, reset_idx, global_floor=0.0, local_cap=0.03)
    assert np.all(capped <= uncapped + 1e-12)
    assert np.mean(capped) < np.mean(uncapped)  # the cap must bind somewhere across 20k paths


def test_cliquet_local_floor_raises_payoff_relative_to_unfloored_on_the_downside():
    """A local floor at -0.02 (never worse than -2% per period) can only
    help (or leave unchanged) a path relative to no local floor, since it
    clips only the downside of each local return."""
    paths = _paths()
    reset_idx = [0, 63, 126, 189, 252]
    unfloored = cliquet_payoff(paths, reset_idx, global_floor=-np.inf, local_floor=-np.inf)
    floored = cliquet_payoff(paths, reset_idx, global_floor=-np.inf, local_floor=-0.02)
    assert np.all(floored >= unfloored - 1e-12)


def test_cliquet_rejects_non_increasing_reset_indices():
    paths = _paths()
    try:
        cliquet_payoff(paths, [0, 100, 50, 252])
        assert False, "expected ValueError"
    except ValueError:
        pass
