"""Deterministic synthetic price + factor panels — the only "data" this
sandbox can produce end to end without outbound network access.

Used by (a) the test suite, and (b) `export.py`'s demo mode, which produces a
real `public/data/factor/latest.json` so the website seam has something to
read even though no live Tiingo/French fetch exists here. Anything built
from this module is clearly and permanently labeled synthetic wherever it
surfaces (see `export.py`'s `data_provenance` field) — it must never be
mistaken for a real market read.

Model: six independent factor series (Mkt-RF, SMB, HML, RMW, CMA, Mom) plus a
risk-free rate, all i.i.d. Gaussian (RF a small positive constant drift, the
others zero-mean) — deliberately NOT modeling any real cross-factor
correlation structure (real Mkt-RF and SMB/HML/Mom are of course correlated
in practice) because this generator's only job is to exercise the regression
pipeline end to end with a KNOWN answer, not to imitate real factor dynamics.
Each demo ticker's return is built as a caller-specified LINEAR COMBINATION
of the six factors plus idiosyncratic noise — i.e. the synthetic universe is
constructed so the "true" betas are known by design, which is what lets
`tests/test_regression.py` and `tests/test_export.py` assert the recovered
betas land close to the injected ones (a positive control), on top of the
pure closed-form-OLS unit tests that don't need any panel at all.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import FACTOR_COLUMNS, RF_COLUMN

DEFAULT_TICKERS = ["DEMO-A", "DEMO-B", "DEMO-C"]

# One illustrative "true beta" vector per demo ticker, in the same order as
# FACTOR_COLUMNS (Mkt-RF, SMB, HML, RMW, CMA, Mom). Fixed and documented, not
# fit to anything:
#   DEMO-A: a high-beta, momentum-chasing growth name (big Mkt-RF and Mom,
#           negative HML/value tilt).
#   DEMO-B: a low-beta, value/profitability defensive name.
#   DEMO-C: a small-cap name with roughly market beta and little else.
DEMO_TRUE_BETAS: dict[str, dict[str, float]] = {
    "DEMO-A": {"Mkt-RF": 1.4, "SMB": 0.1, "HML": -0.5, "RMW": -0.1, "CMA": -0.2, "Mom": 0.6},
    "DEMO-B": {"Mkt-RF": 0.6, "SMB": -0.3, "HML": 0.5, "RMW": 0.4, "CMA": 0.3, "Mom": -0.1},
    "DEMO-C": {"Mkt-RF": 1.0, "SMB": 0.8, "HML": 0.0, "RMW": 0.0, "CMA": 0.0, "Mom": 0.0},
}


def simulate_factor_panel(
    n_days: int,
    seed: int = 0,
    start: str = "2023-01-02",
    factor_vol: dict[str, float] | None = None,
    rf_daily: float = 0.00015,
) -> pd.DataFrame:
    """A synthetic daily factor panel: columns `FACTOR_COLUMNS + [RF_COLUMN]`,
    business-day-indexed starting at `start`. `factor_vol` overrides any
    factor's daily volatility (defaults chosen to be roughly the right order
    of magnitude for real daily Fama-French factors, ~0.3-0.9% daily vol —
    illustrative, not calibrated to any real sample)."""
    rng = np.random.default_rng(seed)
    default_vol = {"Mkt-RF": 0.009, "SMB": 0.004, "HML": 0.004, "RMW": 0.003, "CMA": 0.003, "Mom": 0.005}
    vol = {**default_vol, **(factor_vol or {})}

    dates = pd.bdate_range(start, periods=n_days)
    cols = {f: rng.normal(0.0, vol[f], n_days) for f in FACTOR_COLUMNS}
    cols[RF_COLUMN] = np.full(n_days, rf_daily)
    df = pd.DataFrame(cols, index=dates)[FACTOR_COLUMNS + [RF_COLUMN]]
    df.index.name = "date"
    return df


def simulate_ticker_returns(
    factor_panel: pd.DataFrame,
    true_betas: dict[str, float],
    alpha: float = 0.0,
    idio_vol: float = 0.010,
    seed: int = 0,
) -> pd.Series:
    """A synthetic ticker's daily TOTAL return (not excess — RF is added back
    in), built as `alpha + RF + sum(beta_f * factor_f) + idio_noise` so that
    `return - RF` regressed on `factor_panel[FACTOR_COLUMNS]` recovers
    `true_betas` up to estimation noise — the positive-control property
    `tests/test_regression.py::test_recovers_known_synthetic_betas` checks."""
    rng = np.random.default_rng(seed)
    n = len(factor_panel)
    excess = np.full(n, alpha)
    for f, b in true_betas.items():
        excess = excess + b * factor_panel[f].to_numpy(dtype=float)
    idio = rng.normal(0.0, idio_vol, n)
    total_return = excess + idio + factor_panel[RF_COLUMN].to_numpy(dtype=float)
    return pd.Series(total_return, index=factor_panel.index, name="_ticker")


def make_synthetic_universe(
    n_days: int = 400,
    seed: int = 7,
    tickers: list[str] | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Convenience one-shot for `export.py`'s synthetic-demo path: a factor
    panel plus one return series per ticker in `DEMO_TRUE_BETAS` (or a
    caller-supplied subset of `tickers`)."""
    tickers = tickers if tickers is not None else DEFAULT_TICKERS
    panel = simulate_factor_panel(n_days, seed=seed)
    returns = {}
    for i, t in enumerate(tickers):
        true_betas = DEMO_TRUE_BETAS.get(t, DEMO_TRUE_BETAS[DEFAULT_TICKERS[0]])
        returns[t] = simulate_ticker_returns(panel, true_betas, seed=seed + i + 1)
    return panel, returns
