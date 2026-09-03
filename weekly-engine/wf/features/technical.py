"""Per-ticker weekly technical features.

Every function here takes one ticker's own prepared weekly base frame
(columns `close`, `volume`, `ret` — see features/panel.py::prepare_base) and
returns a Series aligned to the same weekly DatetimeIndex. Nothing here looks
across tickers — that is the cross-sectional layer (features/cross_sectional.py
+ panel.py). Everything below is a backward rolling/EWMA window on `close`
and `volume` alone, so it is point-in-time by construction: the value at row
t never uses data dated after t.

The RSI formula is the same Wilder recursion intra-exitus-engine's
`ie/features/price.py::rsi` uses on daily bars; it is reimplemented here
(not imported) to keep this engine sealed — see README.md's "sealed engine"
note for why that duplication is deliberate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .registry import feature


def _wilder_rsi(close: pd.Series, window: int) -> pd.Series:
    """Wilder RSI in [0, 100]. All-gains -> 100; all-losses -> 0; perfectly
    flat window -> NaN (RSI is genuinely undefined with zero movement)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False).mean()
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), np.nan)


# --- RSI at three weekly windows --------------------------------------------

RSI_WINDOWS = (5, 9, 14)


@feature(
    "rsi_5", "1.0", lookback_weeks=15,
    rationale="Fast Wilder RSI (5 weeks): short-horizon overbought/oversold pressure.",
)
def rsi_5(base: pd.DataFrame) -> pd.Series:
    return _wilder_rsi(base["close"], 5)


@feature(
    "rsi_9", "1.0", lookback_weeks=27,
    rationale="Medium Wilder RSI (9 weeks): the classic swing-trading RSI window, applied weekly.",
)
def rsi_9(base: pd.DataFrame) -> pd.Series:
    return _wilder_rsi(base["close"], 9)


@feature(
    "rsi_14", "1.0", lookback_weeks=42,
    rationale="Standard Wilder RSI (14 weeks): the textbook window, slower and less noisy than rsi_5/rsi_9.",
)
def rsi_14(base: pd.DataFrame) -> pd.Series:
    return _wilder_rsi(base["close"], 14)


# --- Momentum, with a skip variant -------------------------------------------
# Momentum over N weeks, and a "skip" variant that excludes the most recent
# week. Rationale for the skip variant: short-term (1-2 week) reversal is a
# well-documented, *separate* effect from intermediate-horizon continuation
# (the classic "12-1" momentum construction in Jegadeesh & Titman 1993 exists
# precisely because the most recent month/week pollutes a pure momentum
# reading with reversal noise pulling the opposite direction). Excluding the
# most recent week isolates the continuation signal from that contamination.

MOMENTUM_WEEKS = (4, 8, 12, 26, 52)


def _momentum(close: pd.Series, window: int) -> pd.Series:
    return close / close.shift(window) - 1.0


def _momentum_skip(close: pd.Series, window: int) -> pd.Series:
    """Momentum over `window` weeks ending LAST week, excluding the most
    recent week's own (reversal-prone) return."""
    return close.shift(1) / close.shift(window + 1) - 1.0


def _register_momentum(window: int):
    @feature(
        name=f"mom_{window}",
        version="1.0",
        lookback_weeks=window,
        rationale=f"{window}-week price momentum (raw): cumulative return over the trailing {window} weeks.",
    )
    def _fn(base: pd.DataFrame, _w=window) -> pd.Series:
        return _momentum(base["close"], _w)

    _fn.__name__ = f"mom_{window}"

    @feature(
        name=f"mom_{window}_skip",
        version="1.0",
        lookback_weeks=window + 1,
        rationale=(
            f"{window}-week momentum excluding the most recent week — isolates intermediate-horizon "
            f"continuation from short-term reversal, which the raw mom_{window} does not."
        ),
    )
    def _fn_skip(base: pd.DataFrame, _w=window) -> pd.Series:
        return _momentum_skip(base["close"], _w)

    _fn_skip.__name__ = f"mom_{window}_skip"
    return _fn, _fn_skip


for _w in MOMENTUM_WEEKS:
    _register_momentum(_w)

MOMENTUM_COLUMNS = [f"mom_{w}" for w in MOMENTUM_WEEKS] + [f"mom_{w}_skip" for w in MOMENTUM_WEEKS]


# --- Realised volatility (two windows + their ratio) -------------------------

VOL_WINDOWS = (10, 26)


@feature(
    "vol_10", "1.0", lookback_weeks=10,
    rationale="Realised volatility of weekly returns over 10 weeks — the 'recent' vol regime reading.",
)
def vol_10(base: pd.DataFrame) -> pd.Series:
    return base["ret"].rolling(10).std(ddof=0)


@feature(
    "vol_26", "1.0", lookback_weeks=26,
    rationale="Realised volatility of weekly returns over 26 weeks — the 'settled' vol regime reading.",
)
def vol_26(base: pd.DataFrame) -> pd.Series:
    return base["ret"].rolling(26).std(ddof=0)


@feature(
    "vol_ratio_10_26", "1.0", lookback_weeks=26,
    rationale=(
        "vol_10 / vol_26: >1 flags a recent volatility expansion relative to the settled regime "
        "(useful independently of either window's absolute level, which varies a lot by name)."
    ),
)
def vol_ratio_10_26(base: pd.DataFrame) -> pd.Series:
    v10 = base["ret"].rolling(10).std(ddof=0)
    v26 = base["ret"].rolling(26).std(ddof=0)
    return v10 / v26.replace(0.0, np.nan)


# --- Distance from the 52-week high ------------------------------------------


@feature(
    "dist_52w_high", "1.0", lookback_weeks=52,
    rationale="close / trailing-52-week-high - 1 (<=0): how far the name sits below its own recent high.",
)
def dist_52w_high(base: pd.DataFrame) -> pd.Series:
    trailing_high = base["close"].rolling(52, min_periods=10).max()
    return base["close"] / trailing_high - 1.0


# --- Volume trend -------------------------------------------------------------


@feature(
    "vol_trend_4_26", "1.0", lookback_weeks=26,
    rationale=(
        "Recent (4-week) average volume / longer (26-week) average volume: a rising ratio flags "
        "fresh participation/attention, a classic precursor/confirmer of a move."
    ),
)
def vol_trend_4_26(base: pd.DataFrame) -> pd.Series:
    recent = base["volume"].rolling(4).mean()
    longer = base["volume"].rolling(26).mean()
    return recent / longer.replace(0.0, np.nan)


TECHNICAL_COLUMNS = (
    list(f"rsi_{w}" for w in RSI_WINDOWS)
    + MOMENTUM_COLUMNS
    + ["vol_10", "vol_26", "vol_ratio_10_26", "dist_52w_high", "vol_trend_4_26"]
)
