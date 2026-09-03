"""Tests for decision/idea.py (IMP-19)."""

from __future__ import annotations

import dataclasses

import pytest

from idea import DecisionOutput


def test_basic_construction():
    d = DecisionOutput(is_good_idea=True, confidence=0.8, rationale="strong signal")
    assert d.is_good_idea is True
    assert d.confidence == 0.8
    assert d.rationale == "strong signal"


def test_inconclusive_is_good_idea_none_is_allowed():
    d = DecisionOutput(is_good_idea=None, confidence=0.1, rationale="not enough data yet")
    assert d.is_good_idea is None


def test_confidence_out_of_range_raises():
    with pytest.raises(ValueError):
        DecisionOutput(is_good_idea=True, confidence=1.5, rationale="x")
    with pytest.raises(ValueError):
        DecisionOutput(is_good_idea=False, confidence=-0.1, rationale="x")


def test_confidence_nan_raises():
    with pytest.raises(ValueError):
        DecisionOutput(is_good_idea=True, confidence=float("nan"), rationale="x")


def test_no_sizing_or_capital_fields_exist_on_decision_output():
    # The IMP-19 boundary is enforced in the code's actual shape, not just
    # in comments: DecisionOutput must not carry any sizing/capital field.
    field_names = {f.name for f in dataclasses.fields(DecisionOutput)}
    forbidden = {"size", "weight", "budget", "capital", "position_size", "approved_size"}
    assert field_names.isdisjoint(forbidden)
    assert field_names == {"is_good_idea", "confidence", "rationale"}
