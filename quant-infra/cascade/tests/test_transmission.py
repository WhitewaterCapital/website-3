"""Tests for cascade/transmission.py — includes the required synthetic
known-coefficient recovery check."""

from __future__ import annotations

import numpy as np
import pytest

from transmission import fit_transmission

TRUE_BETA = 0.42
TRUE_GAMMA_SECTOR = -0.15
TRUE_INTERCEPT = 0.001


def _simulate(n=2000, noise_std=0.01, seed=11):
    rng = np.random.default_rng(seed)
    pressure = rng.normal(0, 1.0, n)
    sector_move = rng.normal(0, 0.5, n)
    noise = rng.normal(0, noise_std, n)
    y = TRUE_INTERCEPT + TRUE_BETA * pressure + TRUE_GAMMA_SECTOR * sector_move + noise
    return pressure, sector_move, y


def test_recovers_known_coefficient_within_tolerance():
    pressure, sector_move, y = _simulate()
    result = fit_transmission(pressure, y, controls={"sector_move": sector_move})
    assert result.n_obs == pressure.size
    # documented tolerance: within 5% relative or 0.01 absolute, whichever looser
    assert result.coefficient == pytest.approx(TRUE_BETA, rel=0.05, abs=0.01)
    assert result.control_coefficients["sector_move"] == pytest.approx(
        TRUE_GAMMA_SECTOR, rel=0.05, abs=0.01
    )
    assert result.intercept == pytest.approx(TRUE_INTERCEPT, abs=0.01)
    assert result.r_squared > 0.9
    assert result.std_error is not None and result.std_error > 0


def test_recovers_coefficient_without_controls():
    rng = np.random.default_rng(3)
    n = 1000
    pressure = rng.normal(0, 1.0, n)
    y = 0.0 + 0.7 * pressure + rng.normal(0, 0.05, n)
    result = fit_transmission(pressure, y)
    assert result.coefficient == pytest.approx(0.7, rel=0.05)
    assert result.control_coefficients == {}


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        fit_transmission(np.array([1.0, 2.0]), np.array([1.0]))


def test_control_shape_mismatch_raises():
    with pytest.raises(ValueError):
        fit_transmission(
            np.array([1.0, 2.0, 3.0]),
            np.array([1.0, 2.0, 3.0]),
            controls={"sector": np.array([1.0, 2.0])},
        )


def test_insufficient_observations_returns_nan_not_exception():
    p = np.array([1.0, 2.0])
    y = np.array([0.1, 0.2])
    result = fit_transmission(p, y)
    assert np.isnan(result.coefficient)
    assert result.n_obs == 2


def test_zero_variance_pressure_returns_nan_coefficient():
    p = np.full(20, 5.0)
    y = np.random.default_rng(1).normal(0, 1, 20)
    result = fit_transmission(p, y)
    assert np.isnan(result.coefficient)
    assert not np.isnan(result.intercept)  # mean(y) is still reported


def test_nan_rows_are_dropped_not_propagated():
    rng = np.random.default_rng(5)
    n = 500
    pressure = rng.normal(0, 1.0, n)
    y = 0.3 * pressure + rng.normal(0, 0.02, n)
    pressure[10] = np.nan
    y[20] = np.nan
    result = fit_transmission(pressure, y)
    assert result.n_obs == n - 2
    assert not np.isnan(result.coefficient)
    assert result.coefficient == pytest.approx(0.3, rel=0.1)
