"""PATH-06: the three-model spread (local vol / Heston / historical
bootstrap) -- structural checks and, most importantly, that the P-measure
bootstrap number is labeled distinctly from the two Q-measure prices and
never silently blended into the "spread" statistic."""
from __future__ import annotations

import numpy as np

from pe.engine.heston import HestonParams
from pe.surface.svi import SVIParams, svi_term_structure_surface
from pe.validation.model_comparison import three_model_spread

S0, r, q, T = 100.0, 0.02, 0.0, 0.5
K = 100.0


def _vanilla_call(paths):
    return np.maximum(paths[:, -1] - K, 0.0)


def _surface():
    k_grid = np.linspace(-0.6, 0.6, 41)
    T_grid = np.array([0.25, 0.5, 1.0])
    base = SVIParams(a=0.02, b=0.15, rho=-0.4, m=0.0, sigma=0.25)
    atm_w = np.array([0.22**2 * t for t in T_grid])
    return svi_term_structure_surface(k_grid, T_grid, base, atm_w)


def test_three_model_spread_reports_all_three_with_standard_errors():
    heston = HestonParams(v0=0.05, kappa=1.5, theta=0.05, xi=0.5, rho=-0.6)
    result = three_model_spread(
        _vanilla_call, S0, r, q, T, _surface(), heston, n_paths=20_000, n_steps=50, seed=900
    )
    for res in (result.local_vol, result.heston, result.historical_bootstrap):
        assert res.std_error > 0.0
        assert not np.isnan(res.std_error)
        assert res.price >= 0.0  # a call payoff is nonnegative in every measure

    assert result.q_measure_spread >= 0.0
    assert abs(result.q_measure_spread - abs(result.local_vol.price - result.heston.price)) < 1e-9


def test_bootstrap_leg_is_labeled_as_real_world_not_risk_neutral():
    """The whole point of the module's docstring warning -- this is the one
    mechanical check that the labeling is actually there, not just in prose."""
    heston = HestonParams(v0=0.05, kappa=1.5, theta=0.05, xi=0.5, rho=-0.6)
    result = three_model_spread(
        _vanilla_call, S0, r, q, T, _surface(), heston, n_paths=20_000, n_steps=50, seed=901
    )
    assert result.local_vol.meta["measure"] == "Q"
    assert result.heston.meta["measure"] == "Q"
    assert result.historical_bootstrap.meta["measure"] == "P"
    assert "warning" in result.historical_bootstrap.meta
    assert "NOT a risk-neutral price" in result.historical_bootstrap.meta["warning"]


def test_summary_string_mentions_the_boundary_warning():
    heston = HestonParams(v0=0.05, kappa=1.5, theta=0.05, xi=0.5, rho=-0.6)
    result = three_model_spread(
        _vanilla_call, S0, r, q, T, _surface(), heston, n_paths=5_000, n_steps=30, seed=902
    )
    text = result.summary()
    assert "NOT a price" in text or "never feed" in text.lower()
