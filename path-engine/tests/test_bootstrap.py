"""PATH-06: historical block-bootstrap path generator. Real-world (P), not
risk-neutral -- these tests check the resampling mechanics, not any
no-arbitrage property (there is none to check)."""
from __future__ import annotations

import numpy as np

from pe.engine.bootstrap import historical_bootstrap_paths, synthetic_historical_returns


def test_synthetic_historical_returns_matches_garch_unconditional_variance_on_average():
    returns = synthetic_historical_returns(n_days=50_000, seed=1, mu_annual=0.08, vol_annual=0.20)
    annualized_vol = np.std(returns, ddof=1) * np.sqrt(252)
    # GARCH unconditional variance is a population target; over 50k days the
    # sample estimate should land in a generous but real band around it.
    assert 0.15 < annualized_vol < 0.25


def test_synthetic_historical_returns_rejects_non_stationary_garch_params():
    try:
        synthetic_historical_returns(1000, seed=1, garch_alpha=0.6, garch_beta=0.6)
        assert False, "expected ValueError for alpha+beta >= 1"
    except ValueError:
        pass


def test_bootstrap_paths_start_at_S0_and_are_positive():
    returns = synthetic_historical_returns(2000, seed=2)
    times, paths, info = historical_bootstrap_paths(returns, S0=100.0, n_steps=252, n_paths=5000, seed=3, block_size=5)
    assert np.allclose(paths[:, 0], 100.0)
    assert np.all(paths > 0.0)
    assert paths.shape == (5000, 253)
    assert times.shape == (253,)


def test_bootstrap_is_deterministic_given_the_same_seed():
    returns = synthetic_historical_returns(2000, seed=2)
    _, paths_a, _ = historical_bootstrap_paths(returns, 100.0, 100, 1000, seed=42, block_size=5)
    _, paths_b, _ = historical_bootstrap_paths(returns, 100.0, 100, 1000, seed=42, block_size=5)
    np.testing.assert_array_equal(paths_a, paths_b)


def test_bootstrap_rejects_block_size_larger_than_history():
    returns = synthetic_historical_returns(10, seed=2)
    try:
        historical_bootstrap_paths(returns, 100.0, 50, 100, seed=1, block_size=20)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_bootstrap_info_reports_empirical_moments_not_model_parameters():
    """`BootstrapInfo` should reflect the actual resampled series' own
    empirical moments, not the GARCH generator's target parameters --
    check they're at least in the right ballpark and genuinely computed
    from `returns`, not hardcoded."""
    returns = synthetic_historical_returns(5000, seed=5, mu_annual=0.10, vol_annual=0.25)
    _, _, info = historical_bootstrap_paths(returns, 100.0, 50, 100, seed=1, block_size=5)
    assert abs(info.empirical_mean_daily - float(np.mean(returns))) < 1e-12
    assert abs(info.empirical_vol_daily - float(np.std(returns, ddof=1))) < 1e-12
    assert info.block_size == 5
    assert info.source_n_days == 5000
