"""Deterministic synthetic-demo price panel for WW-KALMAN's no-live-key
fallback — built so the REAL cointegration test and REAL adaptive Kalman
filter run over genuinely structured data, never a shortcut that fakes the
filter's own output (see kf/export.py's module docstring for the honesty
gate this feeds).

## Design: two groups, so BOTH real outcomes get exercised

A single shared latent random-walk factor F_t drives one "cointegrated
group" of tickers (each = a different linear loading on F_t plus its own
STATIONARY AR(1) idiosyncratic noise); a separate "independent group" of
tickers is built from mutually independent random walks with no shared
factor and no stationary component at all. This is not an arbitrary
choice — it is what makes the synthetic-demo export honestly exercise
BOTH branches of kf/export.py's pipeline:

  * Within the cointegrated group, ANY two tickers share the same
    nonstationary factor F_t. Engle-Granger's own OLS step finds a hedge
    ratio that (asymptotically) cancels F_t out of the residual, leaving a
    stationary combination of the two AR(1) idiosyncratic components — so
    these pairs SHOULD be found cointegrated. See the derivation below.
  * Across groups, and within the independent group, there is no shared
    stochastic trend and no stationary combination exists — these pairs
    SHOULD be correctly abstained on.

## Why this genuinely produces cointegration (the actual math, briefly)

Let ticker i in the cointegrated group have log-price
    p_i(t) = a_i + b_i * F(t) + e_i(t),   e_i(t) a stationary AR(1)
For two tickers i, j in this group, OLS of p_i on p_j targets the beta that
minimizes residual variance; as sample size grows, that beta converges to
b_i / b_j (the ratio that cancels F(t)), leaving residual
    u(t) = (a_i - beta*a_j) + e_i(t) - beta*e_j(t)
a FIXED LINEAR COMBINATION OF TWO STATIONARY AR(1) SERIES, which is itself
stationary (a linear combination of jointly stationary processes with
finite-order ARMA representations is stationary) — so u(t) has no unit
root, and the ADF test on it is expected to reject, i.e. Engle-Granger
finds these two tickers cointegrated. This is the textbook justification
for why two prices sharing one common nonstationary factor, plus their own
mean-reverting idiosyncratic noise, are cointegrated (Engle & Granger 1987;
Vidyamurthy 2004, ch. 2's "common stochastic trend" framing) — reproduced
here as a real, checkable construction, not asserted.

## Not fabricated Kalman output

Nothing about the ADAPTIVE FILTER or Z-SCORE is faked here — this module
only produces PRICES. Every pair's cointegration verdict, hedge ratio,
Kalman state trajectory, and z-score in synthetic-demo mode comes from
running the real kf/cointegration.py and kf/filter.py code over these
prices, exactly like the live path — see kf/export.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import UNIVERSE

# Deliberately split UNIVERSE (AAPL, MSFT, NVDA, JPM, XOM, KO) into a
# 3-ticker group that shares a common stochastic trend (and should test as
# genuinely cointegrated, pairwise, within the group) and a 3-ticker group
# of mutually independent random walks (which should not). This split is a
# synthetic-demo construction detail only — it says nothing about whether
# the REAL companies AAPL/MSFT/JPM are actually cointegrated in real
# markets (almost certainly not, over any meaningful window — see README.md
# for why a real cointegration verdict must come from real prices, never
# assumed).
COINTEGRATED_GROUP: tuple[str, ...] = ("AAPL", "MSFT", "JPM")
INDEPENDENT_GROUP: tuple[str, ...] = ("NVDA", "XOM", "KO")

assert set(COINTEGRATED_GROUP) | set(INDEPENDENT_GROUP) == set(UNIVERSE)
assert set(COINTEGRATED_GROUP).isdisjoint(INDEPENDENT_GROUP)

N_DAYS = 260  # ~one trading year of daily closes
SEED = 20260914  # fixed, deterministic — same convention as this repo's other synthetic generators


def _ar1(n: int, phi: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """A stationary AR(1) series: x_t = phi*x_{t-1} + eps_t, |phi| < 1. This
    IS the idiosyncratic mean-reverting component each cointegrated-group
    ticker's log-price is built from — genuinely stationary by construction
    (any |phi|<1 AR(1) has a well-defined, time-invariant unconditional
    variance sigma^2/(1-phi^2), the defining property of stationarity)."""
    assert abs(phi) < 1.0
    x = np.empty(n)
    x[0] = rng.normal(0, sigma / np.sqrt(1 - phi ** 2))
    for t in range(1, n):
        x[t] = phi * x[t - 1] + rng.normal(0, sigma)
    return x


def synthetic_log_price_panel(n_days: int = N_DAYS, seed: int = SEED) -> pd.DataFrame:
    """Deterministic synthetic LOG-PRICE panel (columns = UNIVERSE tickers,
    one row per synthetic trading day) — see module docstring for the
    construction and why it genuinely produces cointegration within
    COINTEGRATED_GROUP and not elsewhere."""
    rng = np.random.default_rng(seed)

    # One shared nonstationary factor: a random walk, positive drift kept
    # small (equity-index-like), driving every cointegrated-group ticker.
    factor_steps = rng.normal(0.0003, 0.012, n_days)
    factor = np.cumsum(factor_steps)

    log_prices: dict[str, np.ndarray] = {}

    # Cointegrated group: distinct loadings on the shared factor, distinct
    # stationary AR(1) idiosyncratic noise (distinct phi/sigma per ticker so
    # the group isn't a trivially identical construction across names).
    coint_specs = {
        COINTEGRATED_GROUP[0]: dict(base=np.log(180.0), loading=1.00, phi=0.85, sigma=0.006),
        COINTEGRATED_GROUP[1]: dict(base=np.log(410.0), loading=0.92, phi=0.80, sigma=0.007),
        COINTEGRATED_GROUP[2]: dict(base=np.log(205.0), loading=0.65, phi=0.78, sigma=0.008),
    }
    for ticker, spec in coint_specs.items():
        idio = _ar1(n_days, phi=spec["phi"], sigma=spec["sigma"], rng=rng)
        log_prices[ticker] = spec["base"] + spec["loading"] * factor + idio

    # Independent group: each its own random walk, no shared factor, no
    # stationary component — genuinely NOT cointegrated with anything,
    # including each other (distinct, independently-drawn increments).
    indep_specs = {
        INDEPENDENT_GROUP[0]: dict(base=np.log(125.0), drift=0.0006, vol=0.020),
        INDEPENDENT_GROUP[1]: dict(base=np.log(115.0), drift=0.0001, vol=0.015),
        INDEPENDENT_GROUP[2]: dict(base=np.log(62.0), drift=0.0002, vol=0.011),
    }
    for ticker, spec in indep_specs.items():
        steps = rng.normal(spec["drift"], spec["vol"], n_days)
        log_prices[ticker] = spec["base"] + np.cumsum(steps)

    idx = pd.bdate_range("2025-09-15", periods=n_days, name="date")
    return pd.DataFrame({t: log_prices[t] for t in UNIVERSE}, index=idx)
