"""Tests for cascade/decompose.py — includes the required synthetic
known-permanent/decay-rate recovery check."""

from __future__ import annotations

import numpy as np
import pytest

from decompose import decompose_pressure_impact

TRUE_PERMANENT = 0.02
TRUE_TEMPORARY = 0.05
TRUE_DECAY = 0.30


def _simulate(n_horizons=30, noise_std=0.001, seed=42):
    rng = np.random.default_rng(seed)
    horizons = np.arange(n_horizons, dtype=float)
    impact = TRUE_PERMANENT + TRUE_TEMPORARY * np.exp(-TRUE_DECAY * horizons)
    impact_noisy = impact + rng.normal(0, noise_std, n_horizons)
    return horizons, impact_noisy


def test_recovers_known_permanent_and_decay_within_tolerance():
    horizons, impact = _simulate()
    result = decompose_pressure_impact(horizons, impact)
    assert result.converged
    assert result.permanent == pytest.approx(TRUE_PERMANENT, abs=0.005)
    assert result.temporary == pytest.approx(TRUE_TEMPORARY, abs=0.01)
    assert result.decay_rate == pytest.approx(TRUE_DECAY, rel=0.15)
    assert result.r_squared > 0.95
    assert result.n_obs == horizons.size


def test_noiseless_fit_is_essentially_exact():
    horizons, impact = _simulate(noise_std=0.0)
    result = decompose_pressure_impact(horizons, impact)
    assert result.converged
    assert result.permanent == pytest.approx(TRUE_PERMANENT, abs=1e-4)
    assert result.decay_rate == pytest.approx(TRUE_DECAY, rel=1e-2)


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        decompose_pressure_impact(np.array([1.0, 2.0]), np.array([1.0]))


def test_too_few_points_does_not_converge():
    result = decompose_pressure_impact(np.array([0.0, 1.0, 2.0]), np.array([0.1, 0.05, 0.02]))
    assert not result.converged
    assert np.isnan(result.permanent)
    assert result.n_obs == 3


def test_nan_rows_dropped_before_fit():
    horizons, impact = _simulate(n_horizons=20, noise_std=0.0005)
    impact[3] = np.nan
    horizons[7] = np.nan
    result = decompose_pressure_impact(horizons, impact)
    assert result.converged
    assert result.n_obs == 18
    assert result.permanent == pytest.approx(TRUE_PERMANENT, abs=0.01)


def test_flat_impact_attributes_everything_to_permanent():
    # No decay at all: impact is constant across horizons -> all of it should
    # land in "permanent" with zero temporary component. decay_rate itself is
    # mathematically unidentifiable once temporary == 0 (any rate multiplies a
    # zero coefficient to the same curve), so we do not assert on it here.
    horizons = np.arange(10, dtype=float)
    impact = np.full(10, 0.03)
    result = decompose_pressure_impact(horizons, impact)
    assert result.converged
    assert result.permanent == pytest.approx(0.03, abs=1e-3)
    assert result.temporary == pytest.approx(0.0, abs=1e-3)
    assert result.r_squared == pytest.approx(1.0, abs=1e-6) or np.isnan(result.r_squared)
