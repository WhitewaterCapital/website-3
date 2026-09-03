"""Tests for sizing/ceiling.py (IMP-17)."""

from __future__ import annotations

import pytest

from ceiling import SizingDecision, resolve_position_size


def test_allocator_budget_smaller_wins():
    d = resolve_position_size(allocator_budget=10.0, portfolio_risk_ceiling=50.0)
    assert d.approved_size == 10.0
    assert d.binding_constraint == "allocator"
    assert d.allocator_budget == 10.0
    assert d.portfolio_risk_ceiling == 50.0


def test_portfolio_risk_ceiling_smaller_wins():
    d = resolve_position_size(allocator_budget=100.0, portfolio_risk_ceiling=25.0)
    assert d.approved_size == 25.0
    assert d.binding_constraint == "portfolio_risk"


def test_equal_ceilings_are_both_equal():
    d = resolve_position_size(allocator_budget=40.0, portfolio_risk_ceiling=40.0)
    assert d.approved_size == 40.0
    assert d.binding_constraint == "both_equal"


def test_zero_budget_forces_zero_even_if_risk_ceiling_is_large():
    d = resolve_position_size(allocator_budget=0.0, portfolio_risk_ceiling=1_000_000.0)
    assert d.approved_size == 0.0
    assert d.binding_constraint == "zero_budget"
    # the risk ceiling is still echoed back, even though it did not bind
    assert d.portfolio_risk_ceiling == 1_000_000.0


def test_zero_budget_and_zero_risk_ceiling_is_still_labelled_zero_budget():
    d = resolve_position_size(allocator_budget=0.0, portfolio_risk_ceiling=0.0)
    assert d.approved_size == 0.0
    assert d.binding_constraint == "zero_budget"


def test_negative_allocator_budget_raises():
    with pytest.raises(ValueError):
        resolve_position_size(allocator_budget=-1.0, portfolio_risk_ceiling=5.0)


def test_negative_portfolio_risk_ceiling_raises():
    with pytest.raises(ValueError):
        resolve_position_size(allocator_budget=5.0, portfolio_risk_ceiling=-1.0)


def test_nan_or_inf_inputs_raise_rather_than_silently_resolve():
    with pytest.raises(ValueError):
        resolve_position_size(allocator_budget=float("nan"), portfolio_risk_ceiling=5.0)
    with pytest.raises(ValueError):
        resolve_position_size(allocator_budget=5.0, portfolio_risk_ceiling=float("inf"))


def test_decision_carries_a_research_not_gated_note():
    d = resolve_position_size(allocator_budget=0.0, portfolio_risk_ceiling=10.0)
    assert "research" in d.note.lower()
    assert isinstance(d, SizingDecision)
