"""PIT price features: the one "signal" this engine diffuses.

Why a short-horizon z-scored return, and not something fancier (RSI, vol-scaled
momentum, ...): the whole point of WW-GRAPH is to compare each name's recent
move against what its *graph neighbours* just did. A short (SIGNAL_WINDOW-day)
return is:

  * PIT by construction — `pct_change(window)` at row t only uses closes
    dated <= t, verified by an anti-look-ahead test;
  * fast enough that "this name ran vs. its peers this week" is a live,
    tradeable divergence rather than a stale one;
  * comparable across names once cross-sectionally z-scored, which is what
    the graph diffusion and the residual actually operate on.

A longer-horizon momentum feature would work too (and is a natural extension —
see README), but would blur the very short-horizon divergences this residual is
built to catch, and would overlap heavily with slower-moving factor models
elsewhere in the platform (Incepta already covers cross-sectional momentum).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Simple daily returns. Row t uses close[t] and close[t-1] only — PIT."""
    return prices.pct_change()


def rolling_return(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Trailing `window`-day return ending at each row. PIT: row t is a
    function of close[t] and close[t-window] only, never a future close."""
    return prices.pct_change(periods=window)


def cross_sectional_zscore(row: pd.Series) -> pd.Series:
    """Z-score one date's cross-section of names. Population std (ddof=0) is
    used because at any single date the cross-section IS the whole
    population we're standardizing over, not a sample of a larger one."""
    finite = row[np.isfinite(row)]
    if finite.size < 2:
        return row * np.nan
    mu = finite.mean()
    sd = finite.std(ddof=0)
    if not np.isfinite(sd) or sd <= 0:
        return (row - mu) * 0.0
    return (row - mu) / sd


def signal_frame(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Cross-sectionally z-scored trailing `window`-day return, one row per
    date, one column per ticker. PIT (see `rolling_return`)."""
    rets = rolling_return(prices, window)
    return rets.apply(cross_sectional_zscore, axis=1)


def corr_window_returns(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Daily returns, trailing `window` bars, for the correlation estimator.
    Kept separate from `rolling_return` (which is a multi-day return) — the
    graph is built on the covariance structure of DAILY moves, the diffused
    signal is a multi-day return."""
    return returns(prices).tail(window)
