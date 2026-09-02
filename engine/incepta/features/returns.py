"""Price/return features. Pure functions over numpy arrays so they are trivially
unit-testable against known answers. All inputs are assumed already
point-in-time (the store's `prices(..., end=asof)` handles the cutoff).

Conventions:
- `closes` is a 1-D array oldest→newest of adjusted closes.
- Returns are simple daily returns unless noted.
- Volatility is annualized with 252 trading days.
"""

from __future__ import annotations

import numpy as np

TRADING_DAYS = 252


def daily_returns(closes: np.ndarray) -> np.ndarray:
    closes = np.asarray(closes, dtype=float)
    if closes.size < 2:
        return np.array([])
    return closes[1:] / closes[:-1] - 1.0


def cumulative_return(closes: np.ndarray, lookback: int) -> float:
    """Total return over the last `lookback` bars (e.g. 21≈1m, 252≈1y)."""
    closes = np.asarray(closes, dtype=float)
    if closes.size <= lookback:
        return float("nan")
    return float(closes[-1] / closes[-1 - lookback] - 1.0)


def momentum_12_1(closes: np.ndarray) -> float:
    """Classic cross-sectional momentum: return from ~12m ago to ~1m ago,
    skipping the most recent month (Jegadeesh-Titman 1993). Needs ~252 bars."""
    closes = np.asarray(closes, dtype=float)
    if closes.size < TRADING_DAYS + 1:
        return float("nan")
    start = closes[-TRADING_DAYS - 1]   # ~12m ago
    end = closes[-21 - 1]               # skip most recent ~1m
    return float(end / start - 1.0)


def short_term_reversal(closes: np.ndarray, lookback: int = 21) -> float:
    """Recent (~1m) return; the reversal SIGNAL is its negative. We return the
    raw recent return and let the scorer flip the sign, to avoid double-negation."""
    return cumulative_return(closes, lookback)


def realized_vol(closes: np.ndarray, lookback: int = 63, annualize: bool = True) -> float:
    r = daily_returns(closes)
    if r.size < 2:
        return float("nan")
    r = r[-lookback:]
    v = float(np.std(r, ddof=1))
    return v * np.sqrt(TRADING_DAYS) if annualize else v


def downside_vol(closes: np.ndarray, lookback: int = 63, annualize: bool = True) -> float:
    """Downside deviation (target semi-deviation, target = 0). Squares only the
    negative daily returns but divides by the TOTAL number of observations — the
    standard definition used by the Sortino ratio (Sortino & Price 1994), not an
    average over the negatives only (which would overstate it by ~sqrt(N/N_neg))."""
    r = daily_returns(closes)
    if r.size < 2:
        return float("nan")
    r = r[-lookback:]
    downside = np.minimum(r, 0.0)  # negative returns; 0 where return >= target(0)
    v = float(np.sqrt(np.mean(downside ** 2)))  # denominator = len(r)
    return v * np.sqrt(TRADING_DAYS) if annualize else v


def max_drawdown(closes: np.ndarray) -> float:
    """Worst peak-to-trough decline over the window (negative number)."""
    closes = np.asarray(closes, dtype=float)
    if closes.size < 2:
        return float("nan")
    peak = np.maximum.accumulate(closes)
    dd = closes / peak - 1.0
    return float(dd.min())


def high_52w_ratio(closes: np.ndarray, window: int = TRADING_DAYS) -> float:
    """Price relative to its trailing 52-week high (George-Hwang 2004).
    1.0 = at the high; 0.8 = 20% below it."""
    closes = np.asarray(closes, dtype=float)
    if closes.size < 2:
        return float("nan")
    hi = float(np.max(closes[-window:]))
    return float(closes[-1] / hi) if hi > 0 else float("nan")


def amihud_illiquidity(closes: np.ndarray, dollar_volume: np.ndarray, lookback: int = 63) -> float:
    """Amihud (2002): average of |daily return| / daily dollar volume. Higher =
    more illiquid (bigger price impact per dollar traded)."""
    closes = np.asarray(closes, dtype=float)
    dv = np.asarray(dollar_volume, dtype=float)
    r = np.abs(daily_returns(closes))
    dv = dv[1:]  # align with returns
    n = min(r.size, dv.size, lookback)
    if n < 2:
        return float("nan")
    r, dv = r[-n:], dv[-n:]
    mask = dv > 0
    if mask.sum() < 2:
        return float("nan")
    return float(np.mean(r[mask] / dv[mask]))


def corwin_schultz_spread(highs: np.ndarray, lows: np.ndarray) -> float:
    """Corwin-Schultz (2012) effective bid-ask spread estimate from daily
    high/low ranges — lets us estimate transaction cost WITHOUT quote data.
    Returns an average proportional spread (e.g. 0.004 = 40 bps). Negative
    two-day estimates are floored at 0 per the paper."""
    highs = np.asarray(highs, dtype=float)
    lows = np.asarray(lows, dtype=float)
    n = min(highs.size, lows.size)
    if n < 2:
        return float("nan")
    spreads = []
    for t in range(1, n):
        h2 = max(highs[t], highs[t - 1])
        l2 = min(lows[t], lows[t - 1])
        if lows[t] <= 0 or lows[t - 1] <= 0 or l2 <= 0:
            continue
        beta = (np.log(highs[t] / lows[t]) ** 2) + (np.log(highs[t - 1] / lows[t - 1]) ** 2)
        gamma = np.log(h2 / l2) ** 2
        denom = 3 - 2 * np.sqrt(2)
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)
        s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
        spreads.append(max(s, 0.0))
    return float(np.mean(spreads)) if spreads else float("nan")
