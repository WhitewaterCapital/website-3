"""PATH-04: random number infrastructure -- CRN stream splitting, antithetic
pairing, and the Sobol+bridge honest fallback."""
from __future__ import annotations

import numpy as np

from pe.engine.random_streams import normal_increments, spawn_streams


def test_spawn_streams_gives_independent_reproducible_streams():
    streams_a = spawn_streams(123, 3)
    streams_b = spawn_streams(123, 3)
    for sa, sb in zip(streams_a, streams_b):
        draws_a = sa.standard_normal(10)
        draws_b = sb.standard_normal(10)
        np.testing.assert_array_equal(draws_a, draws_b)
    # different children of the same seed must not be identical to each other
    d0 = spawn_streams(123, 2)[0].standard_normal(20)
    d1 = spawn_streams(123, 2)[1].standard_normal(20)
    assert not np.allclose(d0, d1)


def test_common_random_numbers_reproducible_across_calls():
    z1, info1 = normal_increments(1000, 20, seed=7, antithetic=True, use_sobol=True, dt=0.01)
    z2, info2 = normal_increments(1000, 20, seed=7, antithetic=True, use_sobol=True, dt=0.01)
    np.testing.assert_array_equal(z1, z2)
    assert info1 == info2


def test_antithetic_pairing_is_exact_negation():
    n_paths, n_steps = 200, 10
    z, info = normal_increments(n_paths, n_steps, seed=8, antithetic=True, use_sobol=False)
    assert info["antithetic"] is True
    m = n_paths // 2
    np.testing.assert_allclose(z[:m], -z[m:])


def test_sobol_path_reports_used_sobol_when_dimension_is_small():
    z, info = normal_increments(100, 8, seed=9, antithetic=False, use_sobol=True)
    assert info["used_sobol"] is True
    assert info["used_bridge"] is True
    assert z.shape == (100, 8)


def test_falls_back_to_pseudo_random_above_max_sobol_dim():
    import pe.engine.random_streams as rs

    z, info = normal_increments(100, rs.MAX_SOBOL_DIM + 1, seed=10, antithetic=False, use_sobol=True)
    assert info["used_sobol"] is False
    assert info["used_bridge"] is False
    assert z.shape == (100, rs.MAX_SOBOL_DIM + 1)


def test_use_sobol_false_always_uses_pseudo_random():
    z, info = normal_increments(100, 8, seed=11, antithetic=False, use_sobol=False)
    assert info["used_sobol"] is False


def test_increments_are_standard_normal_like_in_aggregate():
    """Not a precision test -- just a sanity check that the Sobol-mapped
    normals aren't secretly biased or mis-scaled."""
    z, _ = normal_increments(20_000, 4, seed=12, antithetic=True, use_sobol=True)
    assert abs(np.mean(z)) < 0.02
    assert abs(np.std(z) - 1.0) < 0.05
