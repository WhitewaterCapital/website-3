"""Deterministic synthetic OHLCV panels — the only "data" this sandbox has.

Used by (a) the test suite, and (b) `export.py`'s demo mode, which produces a
real `public/data/graph/latest.json` so the website seam has something to
read even though no live universe/price history exists here. Anything built
from this module is clearly and permanently labeled synthetic wherever it
surfaces (see `export.py`'s `data_provenance` field) — it must never be
mistaken for a real market read.

Model: for each name, a shared market factor + a shared sector factor + an
idiosyncratic shock, all i.i.d. Gaussian by default (a caller can override a
given ticker's idiosyncratic path — see `idio_overrides` — to inject known
dynamics, e.g. a true OU or random-walk process, for estimator-validation
tests; see `tests/synthetic.py` for that).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_universe(n_sectors: int = 4, per_sector: int = 5) -> tuple[list[str], dict[str, str]]:
    """A deterministic ticker list and sector map, e.g. S0N0..S0N4, S1N0.., ..."""
    tickers: list[str] = []
    sector_of: dict[str, str] = {}
    for s in range(n_sectors):
        sector = f"SECTOR_{s}"
        for k in range(per_sector):
            t = f"S{s}N{k}"
            tickers.append(t)
            sector_of[t] = sector
    return tickers, sector_of


def simulate_returns(
    tickers: list[str],
    sector_of: dict[str, str],
    n_days: int,
    seed: int = 0,
    mkt_vol: float = 0.010,
    sector_vol: float = 0.007,
    idio_vol: float = 0.009,
    idio_overrides: dict[str, np.ndarray] | None = None,
) -> pd.DataFrame:
    """Daily returns panel (rows=dates, cols=tickers). `idio_overrides[t]`, if
    given, replaces ticker `t`'s idiosyncratic component with a caller-supplied
    length-`n_days` array (used to inject a known OU or random-walk path)."""
    rng = np.random.default_rng(seed)
    sectors = sorted(set(sector_of[t] for t in tickers))
    mkt = rng.normal(0.0, mkt_vol, n_days)
    sector_factor = {s: rng.normal(0.0, sector_vol, n_days) for s in sectors}

    idio_overrides = idio_overrides or {}
    cols = {}
    for t in tickers:
        if t in idio_overrides:
            idio = np.asarray(idio_overrides[t], dtype=float)
            if idio.shape[0] != n_days:
                raise ValueError(f"idio_overrides[{t}] must have length n_days={n_days}")
        else:
            idio = rng.normal(0.0, idio_vol, n_days)
        cols[t] = mkt + sector_factor[sector_of[t]] + idio

    dates = pd.bdate_range("2018-01-02", periods=n_days)
    return pd.DataFrame(cols, index=dates)[tickers]


def returns_to_prices(returns: pd.DataFrame, start_price: float = 100.0) -> pd.DataFrame:
    return start_price * (1.0 + returns).cumprod()


def prices_to_ohlcv(prices: pd.DataFrame, seed: int = 0, vol_scale: float = 1_000_000.0) -> dict[str, pd.DataFrame]:
    """A minimal deterministic OHLCV frame per ticker from a close-price
    series (open=prior close, high/low a small deterministic band around the
    close, volume a positive pseudo-random draw). Good enough to exercise a
    features layer that expects OHLCV; the graph/diffusion/residual math here
    only ever touches `close`."""
    rng = np.random.default_rng(seed)
    out: dict[str, pd.DataFrame] = {}
    for t in prices.columns:
        close = prices[t]
        open_ = close.shift(1).fillna(close.iloc[0])
        band = close * 0.004
        high = pd.concat([open_, close], axis=1).max(axis=1) + band.abs()
        low = pd.concat([open_, close], axis=1).min(axis=1) - band.abs()
        volume = rng.integers(1, 10, size=len(close)) * vol_scale / 10
        out[t] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=prices.index,
        )
    return out


def make_synthetic_panel(
    n_sectors: int = 4,
    per_sector: int = 5,
    n_days: int = 260,
    seed: int = 0,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Convenience one-shot: universe + close-price panel."""
    tickers, sector_of = make_universe(n_sectors, per_sector)
    rets = simulate_returns(tickers, sector_of, n_days, seed=seed)
    prices = returns_to_prices(rets)
    return prices, sector_of
