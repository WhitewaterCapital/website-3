"""Tests for decision/boundary.py (IMP-19)."""

from __future__ import annotations

import functools
import sys
from pathlib import Path

import numpy as np
import pytest

from boundary import BoundaryResult, get_strategy_weights

RELIABILITIES = {"strat-a": 2.0, "strat-b": 4.0, "strat-c": 6.0}


# --- fallback: allocator raises ---------------------------------------------

def test_allocator_raising_falls_back_and_raises_alarm():
    def boom():
        raise RuntimeError("solver blew up")

    result = get_strategy_weights(boom, RELIABILITIES)
    assert isinstance(result, BoundaryResult)
    assert result.source == "fallback"
    assert result.alarm_raised is True
    assert "raised an exception" in result.reason
    assert result.allocator_result is None
    assert sum(result.weights.values()) == pytest.approx(1.0)
    assert set(result.weights.keys()) == set(RELIABILITIES.keys())


# --- fallback: allocator reports infeasible ---------------------------------

class _FakeSolveLog:
    def __init__(self, feasible, solution):
        self.feasible = feasible
        self.solution = solution


def test_allocator_infeasible_result_falls_back_and_raises_alarm():
    def unstable():
        return _FakeSolveLog(feasible=False, solution={"strat-a": 0.0, "strat-b": 0.0, "strat-c": 0.0})

    result = get_strategy_weights(unstable, RELIABILITIES)
    assert result.source == "fallback"
    assert result.alarm_raised is True
    assert "infeasible" in result.reason.lower() or "unstable" in result.reason.lower()
    assert result.allocator_result is not None
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_allocator_infeasible_via_dict_shape_falls_back():
    def unstable_dict():
        return {"feasible": False, "solution": {"strat-a": 0.0, "strat-b": 0.0, "strat-c": 0.0}}

    result = get_strategy_weights(unstable_dict, RELIABILITIES)
    assert result.source == "fallback"
    assert result.alarm_raised is True


# --- fallback: malformed result shape ---------------------------------------

def test_allocator_result_missing_fields_falls_back():
    def malformed():
        return object()  # no .feasible / .solution at all

    result = get_strategy_weights(malformed, RELIABILITIES)
    assert result.source == "fallback"
    assert result.alarm_raised is True
    assert "malformed" in result.reason.lower()


def test_allocator_result_with_non_finite_weight_falls_back():
    def nan_weight():
        return _FakeSolveLog(feasible=True, solution={"strat-a": float("nan"), "strat-b": 0.1, "strat-c": 0.1})

    result = get_strategy_weights(nan_weight, RELIABILITIES)
    assert result.source == "fallback"
    assert result.alarm_raised is True


# --- success path -------------------------------------------------------------

def test_allocator_success_path_uses_allocator_solution_directly():
    solution = {"strat-a": 0.1, "strat-b": 0.2, "strat-c": 0.05}

    def ok():
        return _FakeSolveLog(feasible=True, solution=solution)

    result = get_strategy_weights(ok, RELIABILITIES)
    assert result.source == "allocator"
    assert result.alarm_raised is False
    assert result.reason is None
    assert result.weights == solution
    assert result.fallback_shrinkage is None


# --- integration with the real allocator (read-only import) -----------------

_ALLOC_DIR = Path(__file__).resolve().parents[2] / "alloc"


def _import_real_alloc_solve():
    sys.path.insert(0, str(_ALLOC_DIR))
    import solve as alloc_solve  # noqa: PLC0415 -- deliberate, path-guarded import

    return alloc_solve


def test_real_allocator_success_path_end_to_end():
    alloc_solve = _import_real_alloc_solve()

    strategies = [
        alloc_solve.StrategyInput(
            name="strat-a",
            expected_edge_raw=0.05,
            live_track_record_length=200,
            uncertainty=0.01,
            cost_at_size=0.005,
            previous_budget=0.1,
        ),
        alloc_solve.StrategyInput(
            name="strat-b",
            expected_edge_raw=0.03,
            live_track_record_length=200,
            uncertainty=0.01,
            cost_at_size=0.005,
            previous_budget=0.1,
        ),
    ]
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, size=(50, 2))
    covariance = alloc_solve.shrink_covariance(returns)
    cfg = alloc_solve.SolverConfig()

    solve_fn = functools.partial(alloc_solve.solve, strategies, covariance, cfg)
    result = get_strategy_weights(solve_fn, {"strat-a": 1.0, "strat-b": 1.0})

    assert result.source == "allocator"
    assert result.alarm_raised is False
    assert set(result.weights.keys()) == {"strat-a", "strat-b"}


def test_real_allocator_infeasible_path_falls_back_end_to_end():
    alloc_solve = _import_real_alloc_solve()

    strategies = [
        alloc_solve.StrategyInput(
            name="strat-a",
            expected_edge_raw=0.05,
            live_track_record_length=200,
            uncertainty=0.01,
            cost_at_size=0.005,
            previous_budget=0.1,
            cap=-1.0,  # negative cap -> solve() reports infeasible
        ),
    ]
    covariance = np.array([[0.0001]])
    cfg = alloc_solve.SolverConfig()

    solve_fn = functools.partial(alloc_solve.solve, strategies, covariance, cfg)
    result = get_strategy_weights(solve_fn, {"strat-a": 1.0})

    assert result.source == "fallback"
    assert result.alarm_raised is True
    assert result.weights == pytest.approx({"strat-a": 1.0})
