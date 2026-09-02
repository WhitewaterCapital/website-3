"""Point-in-time price features.

The whole model rests on one contract: **the feature value at row t uses only
bars dated <= t.** No look-ahead, ever. Everything here is either a backward
rolling window or a causal (adjust=False) exponential smoother, so appending
future bars cannot change an earlier row. That is asserted directly in
tests/test_features.py (the "PIT / anti-look-ahead" test).

Design notes:
  * Wilder's indicators (ATR, RSI) use the classic recursive smoother, expressed
    as an EWMA with alpha = 1/n and adjust=False so it is causal and matches the
    textbook recursion once warmed up.
  * Garman-Klass is an OHLC volatility estimator — far more efficient than a
    close-to-close std for the same window — averaged over a window and
    annualised.
  * Distances (from moving averages, band edges, 52w extremes) are expressed as
    fractions so they are comparable across names of very different price levels.
  * Columns keep NaN during warm-up rather than back-filling — a fabricated warm-up
    value is a subtle look-ahead. Downstream code drops the warm-up explicitly.

These are *features* — inputs to the regime classifier and level engine. None of
them is a standalone trade signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FeatureConfig:
    """Windows for the feature set. Defaults are conventional; the point is that
    they live in one place and flow into the tests, not that they are optimal."""

    atr_n: int = 14
    rsi_n: int = 14
    gk_window: int = 20
    rv_window: int = 21
    ewma_lambda: float = 0.94  # RiskMetrics daily decay
    sma_windows: tuple[int, ...] = (20, 50, 200)
    ema_windows: tuple[int, ...] = (21,)
    bb_window: int = 20
    bb_k: float = 2.0
    swing_window: int = 20
    mom_windows: tuple[int, ...] = (21, 63, 126, 252)
    range_52w: int = 252
    trading_days: int = 252

    @property
    def warmup(self) -> int:
        """Bars needed before every column is defined. The longest window drives
        it; momentum 12-1 needs range_52w + 1, so add a small margin."""
        longest = max(
            self.range_52w,
            max(self.sma_windows),
            max(self.mom_windows),
        )
        return longest + 1


# --- primitive indicators ---------------------------------------------------


def _wilder(series: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothing (a.k.a. RMA): EWMA with alpha = 1/n, causal."""
    return series.ewm(alpha=1.0 / n, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    """max(H-L, |H - prevClose|, |L - prevClose|). Row 0 is just H-L."""
    prev_close = df["close"].shift(1)
    hl = df["high"] - df["low"]
    hc = (df["high"] - prev_close).abs()
    lc = (df["low"] - prev_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    return _wilder(true_range(df), n)


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder's RSI in [0, 100]. Uses Wilder-smoothed average gains/losses.

    Edge behaviour: an all-gains window => avg_loss 0 => RSI 100; an all-losses
    window => avg_gain 0 => RSI 0; a perfectly flat window => 0/0 => NaN (RSI is
    genuinely undefined with no movement)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = _wilder(gain, n)
    avg_loss = _wilder(loss, n)
    rs = avg_gain / avg_loss  # /0 -> inf -> RSI 100; 0/0 -> NaN (flat)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.where(~((avg_gain == 0.0) & (avg_loss == 0.0)), np.nan)


def garman_klass_vol(df: pd.DataFrame, window: int, trading_days: int) -> pd.Series:
    """Annualised Garman-Klass volatility over a rolling window.

    Per-bar GK variance: 0.5*(ln H/L)^2 - (2ln2 - 1)*(ln C/O)^2. Averaged over the
    window, annualised, square-rooted. Clipped at 0 before the sqrt (a single
    bar's estimate can go slightly negative; the window mean rarely does)."""
    log_hl = np.log(df["high"] / df["low"])
    log_co = np.log(df["close"] / df["open"])
    gk = 0.5 * log_hl**2 - (2.0 * np.log(2.0) - 1.0) * log_co**2
    daily_var = gk.rolling(window).mean().clip(lower=0.0)
    return np.sqrt(daily_var * trading_days)


def realized_vol(ret: pd.Series, window: int, trading_days: int) -> pd.Series:
    """Annualised close-to-close realised volatility (rolling std of log returns)."""
    return ret.rolling(window).std(ddof=0) * np.sqrt(trading_days)


def ewma_vol(ret: pd.Series, lam: float, trading_days: int) -> pd.Series:
    """RiskMetrics-style EWMA volatility, annualised. Causal by construction."""
    var = (ret**2).ewm(alpha=1.0 - lam, adjust=False).mean()
    return np.sqrt(var * trading_days)


# --- assembly ---------------------------------------------------------------


def compute_features(df: pd.DataFrame, cfg: FeatureConfig | None = None) -> pd.DataFrame:
    """Compute the full PIT feature frame from an OHLCV DataFrame.

    Input: DataFrame indexed by ascending unique date with columns
    open/high/low/close/volume (the shape `pit.bars_to_frame` produces).
    Output: DataFrame on the same index; warm-up rows carry NaN.
    """
    cfg = cfg or FeatureConfig()
    if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        raise ValueError("compute_features expects open/high/low/close/volume columns")
    if not df.index.is_monotonic_increasing:
        raise ValueError("price frame must be sorted ascending by date")

    close = df["close"]
    log_ret = np.log(close / close.shift(1))

    out = pd.DataFrame(index=df.index)
    out["log_ret_1d"] = log_ret

    # Multi-horizon momentum (simple cumulative return over the window).
    for n in cfg.mom_windows:
        out[f"mom_{n}"] = close / close.shift(n) - 1.0
    # 12-1 momentum: trailing 12 months excluding the most recent month.
    out["mom_12_1"] = close.shift(21) / close.shift(cfg.range_52w) - 1.0

    # Volatility family.
    out["atr_14"] = atr(df, cfg.atr_n)
    out["atr_pct"] = out["atr_14"] / close  # ATR as a fraction of price
    out["gk_vol"] = garman_klass_vol(df, cfg.gk_window, cfg.trading_days)
    out["rv_21"] = realized_vol(log_ret, cfg.rv_window, cfg.trading_days)
    out["ewma_vol"] = ewma_vol(log_ret, cfg.ewma_lambda, cfg.trading_days)

    # Trend location: distance from moving averages (as fractions).
    for n in cfg.sma_windows:
        sma = close.rolling(n).mean()
        out[f"dist_sma_{n}"] = close / sma - 1.0
    for n in cfg.ema_windows:
        ema = close.ewm(span=n, adjust=False).mean()
        out[f"dist_ema_{n}"] = close / ema - 1.0

    # Momentum oscillator.
    out["rsi_14"] = rsi(close, cfg.rsi_n)

    # Bollinger geometry: band width (a volatility proxy) and z-score of the close
    # relative to the band's mean (the mean-reversion "how many sigma" reading).
    mid = close.rolling(cfg.bb_window).mean()
    sd = close.rolling(cfg.bb_window).std(ddof=0)
    out["bb_width"] = (2.0 * cfg.bb_k * sd) / mid
    out["bb_z"] = (close - mid) / sd.replace(0.0, np.nan)

    # Swing structure: distance to rolling extremes, and a higher-high/lower-low
    # trend-state flag in {-1, 0, +1}.
    roll_high = df["high"].rolling(cfg.swing_window).max()
    roll_low = df["low"].rolling(cfg.swing_window).min()
    out["dist_swing_high"] = close / roll_high - 1.0   # <= 0, 0 at a new high
    out["dist_swing_low"] = close / roll_low - 1.0     # >= 0, 0 at a new low
    hh = roll_high > roll_high.shift(cfg.swing_window)
    ll = roll_low < roll_low.shift(cfg.swing_window)
    out["swing_state"] = hh.astype(int) - ll.astype(int)

    # Position within the trailing 52-week range, in [0, 1].
    hi = close.rolling(cfg.range_52w).max()
    lo = close.rolling(cfg.range_52w).min()
    out["pos_52w"] = (close - lo) / (hi - lo).replace(0.0, np.nan)

    return out
