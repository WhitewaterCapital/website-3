"""Tests for alloc/solve.py."""

from __future__ import annotations

import numpy as np
import pytest

from solve import (
    SolverConfig,
    StrategyInput,
    score_strategy,
    shrink_covariance,
    shrink_edge,
    solve,
)


# --- shrink_edge -------------------------------------------------------------

def test_short_track_record_shrinks_hard_towards_zero_regardless_of_raw_mean():
    for raw in (-50.0, -1.0, 0.02, 1.0, 50.0):
        shrunk = shrink_edge(raw, live_track_record_length=4, prior_pseudo_obs=60.0)
        # weight = 4/64 ~= 0.0625 -> retains well under 10% of the raw magnitude
        assert abs(shrunk) <= abs(raw) * 0.1 + 1e-12
        # and the sign is preserved (shrinkage, not fabrication)
        if raw != 0:
            assert np.sign(shrunk) == np.sign(raw)


def test_zero_track_record_gives_exactly_zero_edge():
    assert shrink_edge(123.0, live_track_record_length=0, prior_pseudo_obs=60.0) == 0.0


def test_long_track_record_approaches_full_trust():
    shrunk = shrink_edge(1.0, live_track_record_length=100_000, prior_pseudo_obs=60.0)
    assert shrunk == pytest.approx(1.0, rel=1e-3)


def test_negative_track_record_raises():
    with pytest.raises(ValueError):
        shrink_edge(1.0, -1, 60.0)


def test_nonpositive_prior_pseudo_obs_raises():
    with pytest.raises(ValueError):
        shrink_edge(1.0, 10, 0.0)


def test_nan_raw_edge_treated_as_zero_not_propagated():
    assert shrink_edge(float("nan"), 10, 60.0) == 0.0
    assert shrink_edge(float("inf"), 10, 60.0) == 0.0


# --- score_strategy -----------------------------------------------------------

def test_score_basic():
    cfg = SolverConfig(uncertainty_penalty=2.0, cost_penalty=0.5)
    s = score_strategy(shrunk_edge=1.0, uncertainty=0.1, cost_at_size=0.2, cfg=cfg)
    assert s == pytest.approx(1.0 - 2.0 * 0.1 - 0.5 * 0.2)


def test_score_negative_uncertainty_raises():
    with pytest.raises(ValueError):
        score_strategy(1.0, -0.1, 0.0, SolverConfig())


def test_score_negative_cost_raises():
    with pytest.raises(ValueError):
        score_strategy(1.0, 0.0, -0.1, SolverConfig())


def test_score_nan_inputs_propagate_to_nan_score():
    s = score_strategy(1.0, float("nan"), 0.0, SolverConfig())
    assert np.isnan(s)


# --- shrink_covariance ---------------------------------------------------------

def test_shrink_covariance_shape_and_psd():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, size=(200, 5))
    cov = shrink_covariance(returns)
    assert cov.shape == (5, 5)
    eigvals = np.linalg.eigvalsh(cov)
    assert (eigvals >= -1e-10).all()


def test_shrink_covariance_drops_nan_rows():
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.01, size=(100, 3))
    returns[5, 1] = np.nan
    cov = shrink_covariance(returns)
    assert cov.shape == (3, 3)
    assert np.isfinite(cov).all()


def test_shrink_covariance_too_few_complete_rows_raises():
    returns = np.array([[np.nan, 1.0], [1.0, np.nan], [0.5, 0.5]])
    with pytest.raises(ValueError):
        shrink_covariance(returns)


def test_shrink_covariance_single_strategy_raises():
    with pytest.raises(ValueError):
        shrink_covariance(np.ones((10, 1)))


# --- solve: basic behaviour -----------------------------------------------------

def _mk_strategy(name, edge=0.5, track=200, unc=0.05, cost=0.02, prev=0.1, shadow=False, cap=None):
    return StrategyInput(
        name=name,
        expected_edge_raw=edge,
        live_track_record_length=track,
        uncertainty=unc,
        cost_at_size=cost,
        previous_budget=prev,
        shadow_mode=shadow,
        cap=cap,
    )


def _diag_cov(n, var=0.01):
    return np.eye(n) * var


def test_empty_strategies_returns_empty_log():
    log = solve([], np.zeros((0, 0)))
    assert log.solution == {}
    assert log.feasible is True
    assert log.fallback_used is False


def test_covariance_shape_mismatch_raises():
    strategies = [_mk_strategy("A"), _mk_strategy("B")]
    with pytest.raises(ValueError):
        solve(strategies, np.eye(3))


def test_higher_edge_strategy_gets_more_budget():
    strategies = [
        _mk_strategy("HIGH", edge=2.0, prev=0.1),
        _mk_strategy("LOW", edge=0.1, prev=0.1),
    ]
    cov = _diag_cov(2, var=0.0001)  # low risk aversion drag, so edge differences show through
    cfg = SolverConfig(risk_aversion=0.1, turnover_penalty=0.0, max_step_fraction=1.0, default_cap=0.9)
    log = solve(strategies, cov, cfg)
    assert not log.fallback_used
    assert log.solution["HIGH"] > log.solution["LOW"]


def test_per_strategy_cap_is_respected():
    strategies = [_mk_strategy("A", edge=100.0, prev=0.0, cap=0.05)]
    cov = _diag_cov(1, var=0.0001)
    cfg = SolverConfig(risk_aversion=0.0, max_step_fraction=1.0, total_gross_limit=1.0)
    log = solve(strategies, cov, cfg)
    assert log.solution["A"] <= 0.05 + 1e-9


def test_total_gross_limit_is_respected():
    strategies = [_mk_strategy(f"S{i}", edge=5.0, prev=0.0, cap=1.0) for i in range(5)]
    cov = _diag_cov(5, var=0.0001)
    cfg = SolverConfig(risk_aversion=0.0, total_gross_limit=0.5, max_step_fraction=1.0, default_cap=1.0)
    log = solve(strategies, cov, cfg)
    total = sum(log.solution.values())
    assert total <= 0.5 + 1e-6


# --- solve: shadow mode hard zero -----------------------------------------------

def test_shadow_mode_strategy_gets_hard_zero_regardless_of_score():
    strategies = [
        _mk_strategy("SHADOW", edge=1000.0, prev=0.2, shadow=True),  # huge fake edge
        _mk_strategy("NORMAL", edge=0.3, prev=0.1),
    ]
    cov = _diag_cov(2, var=0.0001)
    cfg = SolverConfig(risk_aversion=0.0, max_step_fraction=1.0, total_gross_limit=1.0)
    log = solve(strategies, cov, cfg)
    assert log.solution["SHADOW"] == 0.0
    assert "shadow_zero:SHADOW" in log.active_constraints


def test_shadow_mode_stays_zero_even_under_solver_stress_many_trials():
    """No solver tolerance can push a shadow-mode budget above the razor-thin
    epsilon: run the solve many times with adversarial (huge, varied) fake
    edges and tight numerical settings, and demand an *exact* zero every
    time (the bound is [0,0], not a numerically-tolerant constraint)."""
    rng = np.random.default_rng(123)
    for trial in range(25):
        fake_edge = float(rng.uniform(-1e6, 1e6))
        strategies = [
            _mk_strategy("SHADOW", edge=fake_edge, prev=float(rng.uniform(0, 0.5)), shadow=True),
            _mk_strategy("NORMAL", edge=float(rng.uniform(-1, 1)), prev=0.1),
        ]
        cov = _diag_cov(2, var=float(rng.uniform(1e-6, 1.0)))
        cfg = SolverConfig(
            risk_aversion=float(rng.uniform(0, 5)),
            turnover_penalty=float(rng.uniform(0, 5)),
            max_step_fraction=1.0,
            total_gross_limit=1.0,
        )
        log = solve(strategies, cov, cfg)
        assert log.solution["SHADOW"] == 0.0, f"trial {trial} leaked shadow budget"


def test_shadow_mode_stays_zero_even_on_fallback_path():
    # force a fallback via an infeasible negative cap on the OTHER strategy,
    # while SHADOW carries a large nonzero previous_budget that a naive
    # "just return previous_budget" fallback would otherwise leak.
    strategies = [
        _mk_strategy("SHADOW", edge=1.0, prev=0.4, shadow=True),
        _mk_strategy("BADCAP", edge=1.0, prev=0.1, cap=-0.1),
    ]
    cov = _diag_cov(2)
    log = solve(strategies, cov, SolverConfig())
    assert log.fallback_used
    assert log.solution["SHADOW"] == 0.0


# --- solve: infeasibility and turnover-limited fallback -------------------------

def test_infeasible_negative_cap_triggers_fallback_to_previous_budget():
    strategies = [_mk_strategy("A", edge=1.0, prev=0.15, cap=-0.05)]
    cov = _diag_cov(1)
    log = solve(strategies, cov, SolverConfig())
    assert log.fallback_used
    assert log.feasible is False
    assert log.solution["A"] == 0.15  # exactly the previous budget, untouched
    assert log.fallback_reason is not None and "infeasible" in log.fallback_reason


def test_infeasible_negative_total_gross_limit_triggers_fallback():
    strategies = [_mk_strategy("A", edge=1.0, prev=0.1)]
    cov = _diag_cov(1)
    cfg = SolverConfig(total_gross_limit=-1.0)
    log = solve(strategies, cov, cfg)
    assert log.fallback_used
    assert log.solution["A"] == 0.1


def test_excessive_turnover_triggers_fallback_with_flag():
    # A strategy starting from zero previous budget, with a huge edge and no
    # turnover penalty of its own -> the unconstrained optimum wants to move
    # a lot; a tiny max_step_fraction must reject that and keep the old budget.
    strategies = [_mk_strategy("A", edge=50.0, prev=0.0, cap=0.9)]
    cov = _diag_cov(1, var=0.0001)
    cfg = SolverConfig(risk_aversion=0.0, turnover_penalty=0.0, max_step_fraction=0.01, total_gross_limit=1.0)
    log = solve(strategies, cov, cfg)
    assert log.fallback_used
    assert "moved" in log.fallback_reason
    assert log.solution["A"] == 0.0  # previous budget preserved exactly


def test_small_step_within_budget_is_not_flagged_as_fallback():
    strategies = [_mk_strategy("A", edge=0.5, prev=0.1, cap=0.15)]
    cov = _diag_cov(1, var=0.01)
    cfg = SolverConfig(risk_aversion=1.0, turnover_penalty=0.0, max_step_fraction=1.0, total_gross_limit=1.0)
    log = solve(strategies, cov, cfg)
    assert not log.fallback_used


# --- solve: NaN score handling ---------------------------------------------------

def test_nan_uncertainty_forces_that_strategy_to_zero_not_a_crash():
    strategies = [
        _mk_strategy("BAD", edge=1.0, prev=0.1, unc=float("nan")),
        _mk_strategy("GOOD", edge=1.0, prev=0.1),
    ]
    cov = _diag_cov(2, var=0.0001)
    cfg = SolverConfig(risk_aversion=0.0, max_step_fraction=1.0, total_gross_limit=1.0)
    log = solve(strategies, cov, cfg)
    assert np.isnan(log.scores["BAD"])
    assert log.solution["BAD"] == 0.0
    assert "nan_score_zero:BAD" in log.active_constraints


# --- SolveLog structure -----------------------------------------------------------

def test_solve_log_records_inputs_and_previous_budget():
    strategies = [_mk_strategy("A", prev=0.2), _mk_strategy("B", prev=0.05)]
    cov = _diag_cov(2)
    log = solve(strategies, cov, SolverConfig(max_step_fraction=1.0))
    assert log.inputs == tuple(strategies)
    assert log.previous_budget == {"A": 0.2, "B": 0.05}
    assert set(log.solution.keys()) == {"A", "B"}
    assert "total_gross_limit" in log.active_constraints
