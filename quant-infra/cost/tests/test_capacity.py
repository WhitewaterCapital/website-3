"""Tests for cost/capacity.py (IMP-18)."""

from __future__ import annotations

import pytest

from capacity import estimate_capacity
from impact import estimate_impact_cost


def test_capacity_cost_at_capacity_equals_expected_edge():
    cap = estimate_capacity(
        expected_edge_bps=0.05,
        typical_volume=1000.0,
        volatility=0.03,
        effective_spread=0.004,
        impact_coefficient=0.6,
    )
    est = estimate_impact_cost(
        order_size=cap,
        typical_volume=1000.0,
        volatility=0.03,
        effective_spread=0.004,
        impact_coefficient=0.6,
    )
    assert est.cost == pytest.approx(0.05, rel=1e-6)


def test_capacity_increases_with_edge():
    base = dict(typical_volume=1000.0, volatility=0.03, effective_spread=0.004, impact_coefficient=0.6)
    small_edge_cap = estimate_capacity(expected_edge_bps=0.02, **base)
    large_edge_cap = estimate_capacity(expected_edge_bps=0.10, **base)
    assert large_edge_cap > small_edge_cap


def test_capacity_decreases_with_volatility():
    base = dict(expected_edge_bps=0.05, typical_volume=1000.0, effective_spread=0.004, impact_coefficient=0.6)
    low_vol_cap = estimate_capacity(volatility=0.02, **base)
    high_vol_cap = estimate_capacity(volatility=0.08, **base)
    assert high_vol_cap < low_vol_cap


def test_capacity_decreases_with_impact_coefficient():
    base = dict(expected_edge_bps=0.05, typical_volume=1000.0, volatility=0.03, effective_spread=0.004)
    low_impact_cap = estimate_capacity(impact_coefficient=0.3, **base)
    high_impact_cap = estimate_capacity(impact_coefficient=1.2, **base)
    assert high_impact_cap < low_impact_cap


def test_spread_alone_eating_edge_gives_zero_capacity():
    cap = estimate_capacity(
        expected_edge_bps=0.001,
        typical_volume=1000.0,
        volatility=0.03,
        effective_spread=0.01,  # half-spread 0.005 already > edge
        impact_coefficient=0.6,
    )
    assert cap == 0.0


def test_negative_edge_gives_zero_capacity():
    cap = estimate_capacity(
        expected_edge_bps=-0.01,
        typical_volume=1000.0,
        volatility=0.03,
        effective_spread=0.001,
        impact_coefficient=0.6,
    )
    assert cap == 0.0


def test_zero_impact_coefficient_gives_infinite_capacity_when_spread_ok():
    cap = estimate_capacity(
        expected_edge_bps=0.05,
        typical_volume=1000.0,
        volatility=0.03,
        effective_spread=0.001,
        impact_coefficient=0.0,
    )
    assert cap == float("inf")


def test_zero_volatility_gives_infinite_capacity_when_spread_ok():
    cap = estimate_capacity(
        expected_edge_bps=0.05,
        typical_volume=1000.0,
        volatility=0.0,
        effective_spread=0.001,
        impact_coefficient=0.6,
    )
    assert cap == float("inf")


def test_nonpositive_typical_volume_raises():
    with pytest.raises(ValueError):
        estimate_capacity(0.05, 0.0, 0.03, 0.001, 0.6)


def test_negative_impact_coefficient_raises():
    with pytest.raises(ValueError):
        estimate_capacity(0.05, 1000.0, 0.03, 0.001, -0.6)
