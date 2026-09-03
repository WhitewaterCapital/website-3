"""Tests for decision/reliability_fallback.py (IMP-19)."""

from __future__ import annotations

import pytest

from reliability_fallback import fixed_weight_fallback


def test_shrinkage_zero_tracks_raw_reliabilities_proportionally():
    reliabilities = {"a": 1.0, "b": 3.0, "c": 6.0}
    weights = fixed_weight_fallback(reliabilities, shrinkage=0.0)
    total = sum(reliabilities.values())
    for name, r in reliabilities.items():
        assert weights[name] == pytest.approx(r / total)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_shrinkage_one_gives_fully_equal_weights():
    reliabilities = {"a": 1.0, "b": 3.0, "c": 6.0, "d": 0.0}
    weights = fixed_weight_fallback(reliabilities, shrinkage=1.0)
    n = len(reliabilities)
    for w in weights.values():
        assert w == pytest.approx(1.0 / n)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_intermediate_shrinkage_is_between_raw_and_equal():
    reliabilities = {"a": 1.0, "b": 9.0}
    raw = fixed_weight_fallback(reliabilities, shrinkage=0.0)
    equal = fixed_weight_fallback(reliabilities, shrinkage=1.0)
    mid = fixed_weight_fallback(reliabilities, shrinkage=0.5)
    # 'a' has lower raw weight than equal weight -> shrinkage should pull it up
    assert raw["a"] < mid["a"] < equal["a"]
    assert equal["b"] < mid["b"] < raw["b"]


def test_weights_always_sum_to_one():
    reliabilities = {"a": 2.0, "b": 5.0, "c": 0.1}
    for s in (0.0, 0.25, 0.5, 0.75, 1.0):
        weights = fixed_weight_fallback(reliabilities, shrinkage=s)
        assert sum(weights.values()) == pytest.approx(1.0)


def test_empty_reliabilities_raises():
    with pytest.raises(ValueError):
        fixed_weight_fallback({}, shrinkage=0.5)


def test_negative_reliability_raises():
    with pytest.raises(ValueError):
        fixed_weight_fallback({"a": -1.0, "b": 2.0}, shrinkage=0.5)


def test_shrinkage_out_of_range_raises():
    with pytest.raises(ValueError):
        fixed_weight_fallback({"a": 1.0}, shrinkage=1.5)
    with pytest.raises(ValueError):
        fixed_weight_fallback({"a": 1.0}, shrinkage=-0.1)


def test_all_zero_reliabilities_with_partial_shrinkage_raises_rather_than_fabricate():
    with pytest.raises(ValueError):
        fixed_weight_fallback({"a": 0.0, "b": 0.0}, shrinkage=0.5)


def test_all_zero_reliabilities_with_full_shrinkage_is_fine():
    weights = fixed_weight_fallback({"a": 0.0, "b": 0.0}, shrinkage=1.0)
    assert weights == pytest.approx({"a": 0.5, "b": 0.5})
