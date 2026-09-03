"""
Historical (block) bootstrap path generator (PATH-06) — an alternative,
explicitly **real-world, not risk-neutral**, path source used only for
model comparison (`pe.validation.model_comparison`), never as a pricer in
its own right.

**This module produces P-measure (real-world) sample paths, not Q-measure
(risk-neutral) ones.** Resampling blocks of a historical-looking return
series estimates *what happened* (or, here, what a synthetic series
constructed to look like a plausible return series does); it says nothing
about no-arbitrage pricing, because it makes no reference to the actual
market price of any hedging instrument. See `path-engine/README.md` for why
that distinction matters and must never be blurred with the GBM / local-vol
/ Heston pricers in this package, all three of which price under Q.

Block bootstrap (Kunsch, H.R. (1989), "The Jackknife and the Bootstrap for
General Stationary Observations", Annals of Statistics 17(3), pp.
1217-1241; see also Politis & Romano (1994), "The Stationary Bootstrap") is
used instead of an i.i.d. bootstrap over daily returns because daily
returns in any real (or realistic-looking) series exhibit volatility
clustering — resampling single days independently destroys that
autocorrelation structure and understates the resulting path variance for
any path-dependent payoff. Resampling contiguous blocks of `block_size`
days preserves within-block dependence while still being nonparametric
(no distributional assumption on the returns themselves).

There is no real market data feed wired into this environment (see
`path-engine/README.md` — the same data-vendor gap that blocks PATH-01),
so `synthetic_historical_returns` below generates a single long,
GARCH(1,1)-flavored synthetic daily log-return series purely as a
stand-in "historical" series to resample from. It is clearly labeled
synthetic in its own name and docstring; swapping it for a real adapter
that returns actual historical daily log-returns (Tiingo, as used
elsewhere in this repo) is a drop-in change — `historical_bootstrap_paths`
only needs a 1-D array of daily log-returns, it does not care where they
came from.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def synthetic_historical_returns(
    n_days: int,
    seed: int,
    mu_annual: float = 0.08,
    vol_annual: float = 0.20,
    garch_alpha: float = 0.08,
    garch_beta: float = 0.88,
    trading_days: int = 252,
) -> np.ndarray:
    """A synthetic daily log-return series with GARCH(1,1) volatility
    clustering, standing in for a real historical series (see module
    docstring — this is a stand-in, not a forecast or a claim about any
    real underlying's actual historical behavior).

    GARCH(1,1): h_t = omega + alpha*eps_{t-1}^2 + beta*h_{t-1}, calibrated so
    the *unconditional* daily variance matches `vol_annual^2 / trading_days`
    (standard GARCH(1,1) unconditional-variance identity:
    omega = h_bar * (1 - alpha - beta), requiring alpha + beta < 1 for
    stationarity, which the defaults satisfy: 0.08 + 0.88 = 0.96).
    """
    if not (0.0 < garch_alpha + garch_beta < 1.0):
        raise ValueError("garch_alpha + garch_beta must be in (0, 1) for a stationary GARCH(1,1)")
    rng = np.random.default_rng(seed)
    h_bar = (vol_annual**2) / trading_days
    omega = h_bar * (1.0 - garch_alpha - garch_beta)
    mu_daily = mu_annual / trading_days

    h = h_bar
    eps_prev = 0.0
    returns = np.empty(n_days)
    for t in range(n_days):
        h = omega + garch_alpha * eps_prev**2 + garch_beta * h
        z = rng.standard_normal()
        eps = np.sqrt(h) * z
        returns[t] = mu_daily + eps
        eps_prev = eps
    return returns


@dataclass(frozen=True)
class BootstrapInfo:
    """Diagnostics for a block-bootstrap path draw — meant to be surfaced
    (e.g. via `MonteCarloResult.meta`) rather than hidden, since a caller
    comparing this to a risk-neutral price needs to see at a glance that
    this used a different measure and a different (empirical) drift."""

    source_n_days: int
    block_size: int
    empirical_mean_daily: float
    empirical_vol_daily: float


def historical_bootstrap_paths(
    returns: np.ndarray,
    S0: float,
    n_steps: int,
    n_paths: int,
    seed: int,
    block_size: int = 5,
) -> tuple[np.ndarray, np.ndarray, BootstrapInfo]:
    """Build `n_paths` price paths of `n_steps` daily steps by resampling
    overlapping blocks of `block_size` consecutive days (with replacement)
    from `returns` and compounding them: S_{t+1} = S_t * exp(r_t).

    Blocks are drawn until at least `n_steps` returns are assembled per
    path, then truncated to exactly `n_steps` — the last partial block is
    simply cut short, which is the standard, simplest block-bootstrap
    truncation rule (Kunsch 1989) and introduces no bias in the mean or
    autocovariance structure beyond ordinary sampling noise, since block
    start points are drawn uniformly over all valid starting indices.

    Returns (times, paths, info): `times` is a unit-step grid
    `0, 1, ..., n_steps` in **trading-day units**, not year fractions — the
    caller decides how to annualize/discount, since a bootstrap path's
    natural sampling frequency is whatever `returns` was sampled at.
    """
    returns = np.asarray(returns, dtype=float)
    n_hist = returns.shape[0]
    if n_hist < block_size:
        raise ValueError("returns series shorter than block_size")
    if block_size < 1:
        raise ValueError("block_size must be >= 1")

    rng = np.random.default_rng(seed)
    n_valid_starts = n_hist - block_size + 1
    n_blocks_needed = int(np.ceil(n_steps / block_size))

    path_returns = np.empty((n_paths, n_blocks_needed * block_size))
    for p in range(n_paths):
        starts = rng.integers(0, n_valid_starts, size=n_blocks_needed)
        blocks = [returns[s : s + block_size] for s in starts]
        path_returns[p] = np.concatenate(blocks)
    path_returns = path_returns[:, :n_steps]

    log_paths = np.concatenate(
        [np.zeros((n_paths, 1)), np.cumsum(path_returns, axis=1)], axis=1
    )
    paths = S0 * np.exp(log_paths)
    times = np.arange(n_steps + 1, dtype=float)

    info = BootstrapInfo(
        source_n_days=n_hist,
        block_size=block_size,
        empirical_mean_daily=float(np.mean(returns)),
        empirical_vol_daily=float(np.std(returns, ddof=1)),
    )
    return times, paths, info
