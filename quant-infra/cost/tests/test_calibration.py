"""Tests for cost/calibration.py (IMP-18)."""

from __future__ import annotations

import numpy as np
import pytest

from calibration import MIN_FILLS_FOR_CALIBRATION, FillRecord, calibrate_impact_coefficient


def _make_synthetic_fills(true_coef: float, n: int, seed: int = 0, noise_scale: float = 1e-5):
    rng = np.random.default_rng(seed)
    fills = []
    for _ in range(n):
        order_size = float(rng.uniform(10.0, 500.0))
        typical_volume = float(rng.uniform(1000.0, 5000.0))
        volatility = float(rng.uniform(0.01, 0.05))
        effective_spread = float(rng.uniform(0.0005, 0.003))
        impact_term = true_coef * volatility * np.sqrt(order_size / typical_volume)
        noise = float(rng.normal(0.0, noise_scale))
        realized_slippage = impact_term + 0.5 * effective_spread + noise
        fills.append(
            FillRecord(
                order_size=order_size,
                typical_volume=typical_volume,
                volatility=volatility,
                effective_spread=effective_spread,
                realized_slippage=realized_slippage,
            )
        )
    return fills


def test_returns_none_below_minimum_sample_threshold():
    fills = _make_synthetic_fills(true_coef=0.8, n=MIN_FILLS_FOR_CALIBRATION - 1)
    assert calibrate_impact_coefficient(fills) is None


def test_returns_none_for_empty_input():
    assert calibrate_impact_coefficient([]) is None


def test_recovers_known_coefficient_above_threshold():
    true_coef = 0.8
    fills = _make_synthetic_fills(true_coef=true_coef, n=200, noise_scale=1e-5)
    fitted = calibrate_impact_coefficient(fills)
    assert fitted is not None
    assert fitted == pytest.approx(true_coef, rel=1e-2)


def test_recovers_a_different_known_coefficient():
    true_coef = 0.35
    fills = _make_synthetic_fills(true_coef=true_coef, n=300, noise_scale=1e-5, seed=7)
    fitted = calibrate_impact_coefficient(fills)
    assert fitted is not None
    assert fitted == pytest.approx(true_coef, rel=1e-2)


def test_invalid_fills_are_excluded_from_the_usable_count():
    # Enough rows numerically, but many are unusable (typical_volume <= 0),
    # so the *usable* count falls below threshold -> None.
    good = _make_synthetic_fills(true_coef=0.5, n=5)
    bad = [
        FillRecord(order_size=10.0, typical_volume=0.0, volatility=0.02, effective_spread=0.001, realized_slippage=0.01)
        for _ in range(50)
    ]
    fills = good + bad
    assert calibrate_impact_coefficient(fills) is None


def test_all_zero_order_size_gives_none_not_a_divide_by_zero_crash():
    fills = [
        FillRecord(order_size=0.0, typical_volume=100.0, volatility=0.02, effective_spread=0.001, realized_slippage=0.0005)
        for _ in range(MIN_FILLS_FOR_CALIBRATION + 5)
    ]
    assert calibrate_impact_coefficient(fills) is None
