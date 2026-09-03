"""PATH-03: basic autocallable payoff -- structural/mechanical checks
(this is a simplified structure by design, see `pe/payoffs/autocallable.py`
docstring, so the tests check the mechanics rather than an external
closed-form reference, which does not exist for even a "basic" autocall)."""
from __future__ import annotations

import numpy as np

from pe.engine.gbm import simulate_gbm_paths
from pe.payoffs.autocallable import autocallable_payoff, discount_autocallable

S0, r, q, sigma, T = 100.0, 0.02, 0.0, 0.30, 2.0
OBS = [63, 126, 189, 252, 315, 378, 441, 504]  # ~8 quarterly observations over 2y


def _paths(seed=60, n_paths=20_000):
    _, paths, _ = simulate_gbm_paths(S0, r, q, sigma, T, n_steps=OBS[-1], n_paths=n_paths, seed=seed, antithetic=True)
    times = np.linspace(0.0, T, OBS[-1] + 1)
    return paths, times


def test_every_path_redeems_exactly_once_and_payoff_is_nonnegative():
    paths, times = _paths()
    result = autocallable_payoff(
        paths, OBS, S0, autocall_barrier=1.0, coupon_barrier=0.8, coupon_rate=0.02, knock_in_barrier=0.65
    )
    assert not np.any(np.isnan(result.payoff))
    assert np.all(result.payoff >= 0.0)
    assert np.all(np.isin(result.redemption_index, OBS))


def test_autocalled_paths_are_exactly_those_above_barrier_at_first_opportunity():
    paths, times = _paths()
    result = autocallable_payoff(
        paths, OBS, S0, autocall_barrier=1.0, coupon_barrier=0.8, coupon_rate=0.05, knock_in_barrier=0.65
    )
    called_at_first = paths[:, OBS[0]] >= 1.0 * S0
    assert np.all(result.redemption_index[called_at_first] == OBS[0])
    assert np.all(result.payoff[called_at_first] == 1.0 * (1.0 + 0.05))


def test_knocked_in_paths_get_downside_participation_not_full_principal():
    """A path that survives to maturity, finishes below the coupon barrier,
    AND breached the knock-in barrier at some point must be paid
    notional * S_T / S0 -- strictly less than full principal whenever it
    finished below S0."""
    paths, times = _paths(seed=61, n_paths=50_000)
    result = autocallable_payoff(
        paths, OBS, S0, autocall_barrier=1.05, coupon_barrier=0.90, coupon_rate=0.03, knock_in_barrier=0.60
    )
    maturity = OBS[-1]
    survived_to_maturity = result.redemption_index == maturity
    S_T = paths[survived_to_maturity, maturity]
    ever_breached = np.any(paths[survived_to_maturity][:, : maturity + 1] <= 0.60 * S0, axis=1)
    below_coupon = S_T < 0.90 * S0
    knocked_in = ever_breached & below_coupon
    assert np.any(knocked_in), "test setup should produce at least one knocked-in path at 50k paths"
    notional = 1.0  # autocallable_payoff's default
    expected = notional * S_T[knocked_in] / S0
    got = result.payoff[survived_to_maturity][knocked_in]
    np.testing.assert_allclose(got, expected)
    assert np.all(got < notional)


def test_discounting_uses_each_paths_own_redemption_time():
    paths, times = _paths()
    result = autocallable_payoff(
        paths, OBS, S0, autocall_barrier=1.0, coupon_barrier=0.8, coupon_rate=0.02, knock_in_barrier=0.65
    )
    discounted = discount_autocallable(result, times, r)
    expected = np.exp(-r * times[result.redemption_index]) * result.payoff
    np.testing.assert_allclose(discounted, expected)
    assert np.all(discounted <= result.payoff)  # positive rate, so discounting only shrinks value
