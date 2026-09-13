"""Unit tests for fac/regression.py — the closed-form OLS primitive and the
honesty gate built on top of it (fit_factor_exposure).

No network, no mocking needed here: everything is either a synthetic array
built in-line with a KNOWN closed-form answer, or `fac.synthetic`'s
deterministic generator (itself pure numpy, no I/O).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fac.config import FACTOR_COLUMNS, RF_COLUMN
from fac.regression import fit_factor_exposure, fit_ols
from fac.synthetic import (
    DEMO_TRUE_BETAS,
    simulate_factor_panel,
    simulate_ticker_returns,
)


# --- fit_ols: the pure closed-form primitive -------------------------------


def test_fit_ols_regress_variable_against_itself_gives_beta_one_and_r2_one():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 500)
    y = x.copy()
    X = np.column_stack([np.ones_like(x), x])
    beta_hat, se, r2, cond = fit_ols(y, X)

    assert beta_hat[0] == pytest.approx(0.0, abs=1e-9)  # intercept
    assert beta_hat[1] == pytest.approx(1.0, abs=1e-9)  # slope
    assert r2 == pytest.approx(1.0, abs=1e-9)
    assert se[1] == pytest.approx(0.0, abs=1e-6)  # a perfect fit has zero standard error


def test_fit_ols_recovers_known_multivariate_coefficients():
    rng = np.random.default_rng(1)
    n = 5000
    x1 = rng.normal(0, 1, n)
    x2 = rng.normal(0, 1, n)
    noise = rng.normal(0, 0.01, n)  # tiny noise relative to signal
    y = 2.0 + 3.0 * x1 - 1.5 * x2 + noise
    X = np.column_stack([np.ones(n), x1, x2])

    beta_hat, se, r2, cond = fit_ols(y, X)

    assert beta_hat[0] == pytest.approx(2.0, abs=0.01)
    assert beta_hat[1] == pytest.approx(3.0, abs=0.01)
    assert beta_hat[2] == pytest.approx(-1.5, abs=0.01)
    assert r2 > 0.999


def test_fit_ols_raises_when_not_enough_observations():
    X = np.column_stack([np.ones(2), np.array([1.0, 2.0])])
    y = np.array([1.0, 2.0])
    with pytest.raises(ValueError, match="more observations"):
        fit_ols(y, X)  # n == k == 2, not n > k


def test_fit_ols_flags_high_condition_number_on_collinear_columns():
    rng = np.random.default_rng(2)
    x1 = rng.normal(0, 1, 300)
    x2 = x1 * 1.0000000001  # numerically collinear with x1
    y = rng.normal(0, 1, 300)
    X = np.column_stack([np.ones(300), x1, x2])
    _, _, _, cond = fit_ols(y, X)
    assert cond > 1e10  # fit_ols computes it; the gate that ACTS on it lives in fit_factor_exposure


# --- fit_factor_exposure: the honesty-gated entry point --------------------


def _panel_and_returns(n_days=300, seed=7, ticker="DEMO-A", **kwargs):
    panel = simulate_factor_panel(n_days, seed=seed)
    true_betas = DEMO_TRUE_BETAS[ticker]
    returns = simulate_ticker_returns(panel, true_betas, seed=seed + 1, **kwargs)
    return panel, returns, true_betas


def test_fit_factor_exposure_recovers_known_synthetic_betas():
    panel, returns, true_betas = _panel_and_returns(n_days=400, idio_vol=0.002)
    fit = fit_factor_exposure(returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252)

    assert fit.confidence == "ok"
    assert fit.abstain_reason is None
    assert fit.n_obs == 252  # windowed to the trailing 252 of the 400 available days
    assert fit.r2 is not None and fit.r2 > 0.8  # low idio noise relative to factor signal
    assert fit.betas is not None
    for factor, true_b in true_betas.items():
        got = fit.beta_of(factor)
        assert got is not None
        assert got.beta == pytest.approx(true_b, abs=0.25)


def test_fit_factor_exposure_flags_strong_beta_as_significant():
    panel, returns, _ = _panel_and_returns(ticker="DEMO-A", n_days=400, idio_vol=0.002)
    fit = fit_factor_exposure(returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252)
    mkt = fit.beta_of("Mkt-RF")
    assert mkt is not None
    assert mkt.significant is True  # true beta 1.4, tiny idio noise -> should be a clear detection


def test_fit_factor_exposure_abstains_on_insufficient_history():
    panel, returns, _ = _panel_and_returns(n_days=60)  # well below MIN_OBS=126
    fit = fit_factor_exposure(returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252, min_obs=126)

    assert fit.confidence == "insufficient_history"
    assert fit.betas is None
    assert fit.alpha is None
    assert fit.abstain_reason is not None and "126" in fit.abstain_reason


def test_fit_factor_exposure_abstains_on_zero_variance_ticker_returns():
    panel = simulate_factor_panel(200, seed=3)
    flat_returns = pd.Series(0.0, index=panel.index, name="_ticker")
    fit = fit_factor_exposure(flat_returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252, min_obs=126)

    assert fit.confidence == "degenerate"
    assert fit.betas is None
    assert "zero variance" in fit.abstain_reason


def test_fit_factor_exposure_abstains_on_collinear_factor_panel():
    panel = simulate_factor_panel(200, seed=4)
    # Force two factor columns to be (numerically) collinear over this window.
    panel["CMA"] = panel["HML"] * 1.0 + 1e-12
    true_betas = {"Mkt-RF": 1.0}
    returns = simulate_ticker_returns(panel, true_betas, seed=5)

    fit = fit_factor_exposure(returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252, min_obs=126)
    assert fit.confidence == "degenerate"
    assert fit.betas is None
    assert fit.condition_number is not None and fit.condition_number > 1e10


def test_fit_factor_exposure_drops_dates_missing_from_either_side():
    # Exactly `window` days of history available, so there is no surplus for
    # the trailing-window slice to "pad back" a dropped date with -- a gap
    # here must show up directly as a smaller n_obs.
    panel, returns, _ = _panel_and_returns(n_days=252)
    returns_with_gap = returns.drop(returns.index[100:105])
    fit_full = fit_factor_exposure(returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252, min_obs=126)
    fit_gapped = fit_factor_exposure(returns_with_gap, panel, FACTOR_COLUMNS, RF_COLUMN, window=252, min_obs=126)
    assert fit_full.n_obs == 252
    assert fit_gapped.n_obs == fit_full.n_obs - 5
    assert fit_gapped.confidence == "ok"


def test_beta_of_returns_none_when_abstained():
    panel, returns, _ = _panel_and_returns(n_days=60)
    fit = fit_factor_exposure(returns, panel, FACTOR_COLUMNS, RF_COLUMN, window=252, min_obs=126)
    assert fit.beta_of("Mkt-RF") is None
