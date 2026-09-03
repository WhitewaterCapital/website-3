"""Tests for cost/impact.py (IMP-18)."""

from __future__ import annotations

import math

import pytest

from impact import DEFAULT_IMPACT_COEFFICIENT, estimate_impact_cost


def test_formula_matches_hand_computed_value_default_coefficient():
    # order_size=100, typical_volume=400 -> participation=0.25 -> sqrt=0.5
    # volatility=0.02, effective_spread=0.001
    est = estimate_impact_cost(
        order_size=100.0, typical_volume=400.0, volatility=0.02, effective_spread=0.001
    )
    expected = DEFAULT_IMPACT_COEFFICIENT * 0.02 * 0.5 + 0.5 * 0.001
    assert est.cost == pytest.approx(expected)
    assert est.calibrated is False
    assert est.impact_coefficient_used == DEFAULT_IMPACT_COEFFICIENT


def test_formula_matches_hand_computed_value_explicit_coefficient():
    est = estimate_impact_cost(
        order_size=225.0,
        typical_volume=900.0,
        volatility=0.05,
        effective_spread=0.004,
        impact_coefficient=0.7,
    )
    # participation = 0.25, sqrt = 0.5
    expected = 0.7 * 0.05 * 0.5 + 0.5 * 0.004
    assert est.cost == pytest.approx(expected)
    assert est.calibrated is True
    assert est.impact_coefficient_used == 0.7


def test_inputs_echoed_back():
    est = estimate_impact_cost(10.0, 100.0, 0.03, 0.002)
    assert est.order_size == 10.0
    assert est.typical_volume == 100.0
    assert est.volatility == 0.03
    assert est.effective_spread == 0.002


def test_zero_order_size_gives_only_half_spread_cost():
    est = estimate_impact_cost(0.0, 100.0, 0.03, 0.002)
    assert est.cost == pytest.approx(0.001)


def test_negative_order_size_raises():
    with pytest.raises(ValueError):
        estimate_impact_cost(-1.0, 100.0, 0.03, 0.002)


def test_nonpositive_typical_volume_raises():
    with pytest.raises(ValueError):
        estimate_impact_cost(1.0, 0.0, 0.03, 0.002)
    with pytest.raises(ValueError):
        estimate_impact_cost(1.0, -5.0, 0.03, 0.002)


def test_negative_volatility_raises():
    with pytest.raises(ValueError):
        estimate_impact_cost(1.0, 100.0, -0.01, 0.002)


def test_negative_effective_spread_raises():
    with pytest.raises(ValueError):
        estimate_impact_cost(1.0, 100.0, 0.01, -0.002)


def test_negative_explicit_impact_coefficient_raises():
    with pytest.raises(ValueError):
        estimate_impact_cost(1.0, 100.0, 0.01, 0.002, impact_coefficient=-0.1)


def test_nan_inputs_raise():
    with pytest.raises(ValueError):
        estimate_impact_cost(float("nan"), 100.0, 0.01, 0.002)
