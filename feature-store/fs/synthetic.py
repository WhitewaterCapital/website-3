"""SYNTHETIC / SAMPLE data generator -- FOR TESTING THIS PACKAGE'S MECHANICS
ONLY.

Everything this module produces is fabricated: a deterministic geometric
random walk driven by a fixed `numpy.random.Generator` seed. It is NOT
real market data, NOT a calibrated market simulator, and NOT a source of
any economically meaningful number. It exists solely so `feature-store`'s
own tests (and README demo) have some OHLCV-shaped, point-in-time-ordered
input to register features against and to prove batch/live parity on.

Do not import this module from anywhere that isn't this package's own
tests -- there is no real feature panel here, only a proof that the store's
plumbing works. See feature-store/README.md.
"""
from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

# A small SAMPLE universe + sector map used across this package's tests.
# "DEMO_*" is deliberately not a real ticker naming convention.
SAMPLE_UNIVERSE = ["DEMO_A", "DEMO_B", "DEMO_C", "DEMO_D", "DEMO_E"]
SAMPLE_SECTOR_MAP = {
    "DEMO_A": "SAMPLE_SECTOR_1",
    "DEMO_B": "SAMPLE_SECTOR_1",
    "DEMO_C": "SAMPLE_SECTOR_2",
    "DEMO_D": "SAMPLE_SECTOR_2",
    "DEMO_E": "SAMPLE_SECTOR_3",
}


def _stable_seed(security: str, seed: int) -> int:
    """A reproducible per-security seed derived from a stable hash (NOT
    Python's built-in `hash()`, which is salted per-process for strings
    and would make this generator non-deterministic across runs/PYTHONHASHSEED)."""
    digest = hashlib.sha256(f"{security}:{seed}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], byteorder="big")


def make_synthetic_ohlcv(
    security: str,
    n_periods: int = 120,
    start: str = "2024-01-02",
    seed: int = 0,
    daily_vol: float = 0.02,
    drift: float = 0.0002,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """A deterministic SAMPLE daily OHLCV frame for `security`.

    `close` follows geometric Brownian motion (fixed-seed
    `numpy.random.Generator`); `open`/`high`/`low`/`volume` are simple
    synthetic derivatives of `close`, not independently modeled -- this is
    a mechanics fixture, not a market simulator. Business-day-only index
    (`pd.bdate_range`), ascending, no duplicates -- matching what
    `fs.panel.build_panel` and `fs.live.compute_live_feature` require of a
    point-in-time history frame.

    Deterministic: the same (security, n_periods, start, seed, ...) always
    produces bit-identical output, which is what lets
    `tests/test_batch_live_parity.py` regenerate the "same" history twice
    and compare batch vs. live results.
    """
    rng = np.random.default_rng(_stable_seed(security, seed))
    dates = pd.bdate_range(start=start, periods=n_periods)

    log_returns = rng.normal(loc=drift, scale=daily_vol, size=n_periods)
    log_returns[0] = 0.0  # first bar has no prior bar to return off of
    close = start_price * np.exp(np.cumsum(log_returns))

    intraday_up = rng.uniform(0.0, 0.01, size=n_periods)
    intraday_down = rng.uniform(0.0, 0.01, size=n_periods)
    high = close * (1.0 + intraday_up)
    low = close * (1.0 - intraday_down)
    open_ = np.concatenate([[start_price], close[:-1]])
    volume = rng.integers(low=1_000_000, high=5_000_000, size=n_periods).astype(float)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=pd.DatetimeIndex(dates, name="date"),
    )


def make_synthetic_universe(
    universe: list = None,
    n_periods: int = 120,
    start: str = "2024-01-02",
    seed: int = 0,
) -> dict:
    """`{security: make_synthetic_ohlcv(security, ...)}` for a SAMPLE
    universe, all sharing the same date index (business days from `start`)."""
    universe = list(SAMPLE_UNIVERSE if universe is None else universe)
    return {sec: make_synthetic_ohlcv(sec, n_periods=n_periods, start=start, seed=seed) for sec in universe}
