"""Tests for the first-passage barrier-probability helper (fix #1)."""

from __future__ import annotations

import math

import pytest

from ie.levels.barrier import barrier_hit_prob, expectancy


def test_driftless_is_gamblers_ruin():
    # With no drift, P(target before stop) = b / (a + b), independent of vol.
    assert barrier_hit_prob(a=2.0, b=1.0, drift=0.0, vol=0.5) == pytest.approx(1 / 3)
    assert barrier_hit_prob(a=1.0, b=1.0, drift=0.0, vol=2.0) == pytest.approx(0.5)


def test_positive_drift_raises_probability():
    base = barrier_hit_prob(2.0, 1.0, drift=0.0, vol=1.0)
    up = barrier_hit_prob(2.0, 1.0, drift=0.5, vol=1.0)
    assert up > base


def test_more_vol_pulls_toward_half_ish_when_drift_present():
    # With favourable drift, lower vol lets the drift dominate (higher p); raising
    # vol dilutes the drift's advantage.
    low = barrier_hit_prob(2.0, 1.0, drift=0.3, vol=0.5)
    high = barrier_hit_prob(2.0, 1.0, drift=0.3, vol=3.0)
    assert low > high


def test_probability_bounds():
    for d in (-2.0, -0.1, 0.0, 0.1, 5.0):
        p = barrier_hit_prob(1.5, 0.7, drift=d, vol=1.0)
        assert 0.0 <= p <= 1.0


def test_invalid_inputs_return_none():
    assert barrier_hit_prob(0.0, 1.0, 0.1, 1.0) is None      # a <= 0
    assert barrier_hit_prob(1.0, 0.0, 0.1, 1.0) is None      # b <= 0
    assert barrier_hit_prob(1.0, 1.0, 0.1, 0.0) is None      # vol <= 0
    assert barrier_hit_prob(1.0, 1.0, float("nan"), 1.0) is None  # non-finite drift
    assert barrier_hit_prob(1.0, 1.0, 0.1, math.inf) is None      # non-finite vol


def test_expectancy_matches_formula():
    a, b, d, v = 2.0, 1.0, 0.0, 1.0
    p = barrier_hit_prob(a, b, d, v)
    R = a / b
    assert expectancy(a, b, d, v) == pytest.approx(p * R - (1 - p))


def test_expectancy_none_when_unestimable():
    assert expectancy(1.0, 1.0, 0.1, float("nan")) is None
