"""Tests for the PIT price-feature layer.

The headline test is `test_no_lookahead`: it proves that a feature computed at row
t does not change when future bars are appended. If that ever fails, the whole
model is leaking the future and nothing downstream can be trusted.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from ie.features.price import (
    FeatureConfig,
    atr,
    compute_features,
    rsi,
    true_range,
)
from ie.pit import PriceBar, bars_to_frame


# --- synthetic data ---------------------------------------------------------


def make_ohlc(n: int = 600, seed: int = 7) -> pd.DataFrame:
    """Deterministic pseudo-real OHLC: a gentle trend plus a mean-reverting wobble,
    with a coherent high/low/open bracket around each close."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    trend = 100.0 * (1.0 + 0.0004 * t)
    cycle = 6.0 * np.sin(t / 25.0)
    noise = np.cumsum(rng.normal(0, 0.4, n))
    close = trend + cycle + noise
    close = np.maximum(close, 1.0)

    open_ = close + rng.normal(0, 0.3, n)
    span = np.abs(rng.normal(0, 0.6, n)) + 0.2
    high = np.maximum.reduce([open_, close]) + span
    low = np.minimum.reduce([open_, close]) - span
    low = np.maximum(low, 0.5)
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)

    idx = pd.date_range("2015-01-02", periods=n, freq="B", name="date")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


def const_ohlc(n: int, price: float = 50.0, rng_width: float = 2.0) -> pd.DataFrame:
    """A flat series: same close every day, a fixed high/low band around it."""
    idx = pd.date_range("2015-01-02", periods=n, freq="B", name="date")
    return pd.DataFrame(
        {
            "open": price,
            "high": price + rng_width / 2,
            "low": price - rng_width / 2,
            "close": price,
            "volume": 1_000_000.0,
        },
        index=idx,
    )


# --- the anti-look-ahead contract -------------------------------------------


def test_no_lookahead():
    """A feature at row t must be identical whether or not future bars exist.

    Compute features on the full series, then on the series truncated at t, and
    assert every column matches on the overlap. Tolerances are float round-off
    only. This is the property the entire model depends on."""
    cfg = FeatureConfig()
    df = make_ohlc(600)
    full = compute_features(df, cfg)

    for cut in (300, 450, 599):
        trunc = compute_features(df.iloc[: cut + 1], cfg)
        a = full.iloc[: cut + 1]
        # Same shape/columns on the overlap.
        assert list(a.columns) == list(trunc.columns)
        # NaN pattern must match (warm-up is identical up to t).
        assert (a.isna().to_numpy() == trunc.isna().to_numpy()).all()
        # Finite values must match to round-off.
        pd.testing.assert_frame_equal(
            a.dropna(), trunc.loc[a.dropna().index], atol=1e-9, rtol=1e-9
        )


def test_no_nan_after_warmup():
    cfg = FeatureConfig()
    feats = compute_features(make_ohlc(700), cfg)
    warm = feats.iloc[cfg.warmup :]
    na_cols = warm.columns[warm.isna().any()].tolist()
    assert not na_cols, f"unexpected NaN after warm-up in: {na_cols}"


def test_expected_columns_present():
    feats = compute_features(make_ohlc(400))
    for col in [
        "log_ret_1d", "mom_21", "mom_252", "mom_12_1",
        "atr_14", "atr_pct", "gk_vol", "rv_21", "ewma_vol",
        "dist_sma_20", "dist_sma_200", "dist_ema_21",
        "rsi_14", "bb_width", "bb_z",
        "dist_swing_high", "dist_swing_low", "swing_state", "pos_52w",
    ]:
        assert col in feats.columns, f"missing feature column {col}"


# --- known-value / sanity checks --------------------------------------------


def test_rsi_bounds_and_extremes():
    close = make_ohlc(400)["close"]
    r = rsi(close, 14).dropna()
    assert ((r >= 0) & (r <= 100)).all()

    # Monotonically rising close -> all gains -> RSI pinned at 100.
    up = pd.Series(np.linspace(10, 40, 100))
    assert rsi(up, 14).iloc[-1] == pytest.approx(100.0)
    # Monotonically falling -> all losses -> RSI 0.
    down = pd.Series(np.linspace(40, 10, 100))
    assert rsi(down, 14).iloc[-1] == pytest.approx(0.0)


def test_atr_constant_range_converges():
    """With a fixed daily H-L band and flat closes, ATR -> the band width."""
    band = 2.0
    df = const_ohlc(200, price=50.0, rng_width=band)
    a = atr(df, 14).iloc[-1]
    # True range each day is exactly `band` (prev close == close == mid).
    assert a == pytest.approx(band, abs=1e-6)
    assert true_range(df).iloc[1:].to_numpy() == pytest.approx(band, abs=1e-6)


def test_flat_series_zero_distances():
    """On a flat series, distance-from-MA and band z are 0 (mean == price)."""
    df = const_ohlc(300, price=50.0)
    feats = compute_features(df)
    tail = feats.iloc[-1]
    assert tail["dist_sma_20"] == pytest.approx(0.0, abs=1e-9)
    assert tail["dist_sma_200"] == pytest.approx(0.0, abs=1e-9)
    assert tail["dist_ema_21"] == pytest.approx(0.0, abs=1e-9)
    # bb_z is 0/0 (sd == 0) -> NaN on a perfectly flat series; that's honest.
    assert np.isnan(tail["bb_z"])


def test_bb_z_sign_tracks_position():
    """bb_z is positive when the close sits above its recent mean, negative below."""
    df = make_ohlc(400)
    feats = compute_features(df)
    mid = df["close"].rolling(20).mean()
    above = df["close"] > mid
    z = feats["bb_z"]
    ok = z[above.reindex(z.index)].dropna()
    assert (ok > 0).mean() > 0.99


def test_pos_52w_in_unit_interval():
    feats = compute_features(make_ohlc(500))
    p = feats["pos_52w"].dropna()
    assert ((p >= -1e-9) & (p <= 1 + 1e-9)).all()


# --- frame plumbing ---------------------------------------------------------


def test_bars_to_frame_sorts_and_dedupes():
    d0 = date(2020, 1, 2)
    bars = []
    # Out of order, with one duplicate date (later one should win).
    for i, px in [(2, 12.0), (0, 10.0), (1, 11.0), (1, 99.0)]:
        bars.append(
            PriceBar(
                ticker="TEST", date=d0 + timedelta(days=i),
                open=px, high=px + 1, low=px - 1, close=px, volume=1.0,
                source="synthetic", adjusted=True, ingested_at=d0,
            )
        )
    frame = bars_to_frame(bars)
    assert frame.index.is_monotonic_increasing
    assert frame.index.is_unique
    # Duplicate day collapsed to the last (99.0), not the first (11.0).
    assert frame.loc[pd.Timestamp(d0 + timedelta(days=1)), "close"] == 99.0


def test_empty_bars_to_frame():
    frame = bars_to_frame([])
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 0
