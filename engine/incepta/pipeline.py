"""Thin assembly layer that turns the point-in-time store into per-name feature
rows and a cross-sectional ranking. Slice-1..5 wired together on the fundamental
side (no prices required), so the whole chain is demonstrable on real SEC data.

Everything here reads the store `as_of` a date, so it is point-in-time by
construction — the ranking for a past date uses only what was public then.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from .models.quality import piotroski_f_score
from .models.scoring import composite_score
from .store.duckdb_store import DuckDBStore

_FIELDS = [
    "assets", "revenue", "net_income", "gross_profit", "operating_income",
    "stockholders_equity", "long_term_debt", "operating_cash_flow", "capex",
    "current_assets", "current_liabilities", "shares_outstanding",
]


def quality_snapshot(store: DuckDBStore, ticker: str, asof: date) -> Optional[dict]:
    """Build a fundamentals-only feature row for `ticker`, knowable as of `asof`.
    Aligns the two most-recent annual periods by period_end so growth/Piotroski
    compare like-for-like."""
    series = store.standardized_series_asof(ticker, asof, annual_only=True)
    anchor = series.get("assets") or series.get("revenue")
    if not anchor:
        return None
    pe_curr = anchor[-1]["period_end"]
    pe_prev = anchor[-2]["period_end"] if len(anchor) >= 2 else None

    def val_at(field: str, pe) -> Optional[float]:
        if pe is None:
            return None
        for row in series.get(field, []):
            if row["period_end"] == pe:
                return row["value"]
        return None

    curr = {f: val_at(f, pe_curr) for f in _FIELDS}
    prev = {f: val_at(f, pe_prev) for f in _FIELDS}

    def ratio(a, b):
        return (a / b) if (a is not None and b not in (None, 0)) else None

    fcf = None
    if curr["operating_cash_flow"] is not None and curr["capex"] is not None:
        fcf = curr["operating_cash_flow"] - abs(curr["capex"])

    comp = store.company(ticker)
    p = piotroski_f_score(curr, prev)

    return {
        "ticker": ticker.upper(),
        "sector": (comp or {}).get("sic_description") or "?",
        "period_end": pe_curr,
        "roa": ratio(curr["net_income"], curr["assets"]),
        "roe": ratio(curr["net_income"], curr["stockholders_equity"]),
        "gross_margin": ratio(curr["gross_profit"], curr["revenue"]),
        "net_margin": ratio(curr["net_income"], curr["revenue"]),
        "fcf_margin": ratio(fcf, curr["revenue"]),
        "leverage": ratio(curr["long_term_debt"], curr["assets"]),
        "rev_growth": ratio(curr["revenue"], prev["revenue"]) - 1
        if (curr["revenue"] and prev["revenue"]) else None,
        "piotroski_f": p.score,
        "piotroski_max": p.max_possible,
    }


# 'good is high' weights positive; leverage is 'lower is better' → negative.
QUALITY_WEIGHTS = {
    "roa": 1.0, "roe": 0.5, "gross_margin": 1.0, "net_margin": 1.0,
    "fcf_margin": 1.0, "rev_growth": 0.5, "leverage": -1.0, "piotroski_f": 1.5,
}


def quality_ranking(store: DuckDBStore, tickers: list, asof: date) -> pd.DataFrame:
    rows = [s for t in tickers if (s := quality_snapshot(store, t, asof))]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("ticker")
    return composite_score(df, QUALITY_WEIGHTS)  # sector-neutral off for tiny universes


def risk_snapshot(store: DuckDBStore, ticker: str, asof: Optional[date] = None) -> Optional[dict]:
    """The price/risk read: volatility (realized, downside, EWMA), momentum,
    drawdown, estimated spread, and factor exposures vs FF5+MOM. All computed on
    prices knowable on/before `asof` (point-in-time)."""
    import numpy as np
    import pandas as pd

    from .features import returns as R
    from .models.volatility import ewma_vol
    from .models.factor import factor_exposures
    from .adapters.famafrench import fetch_factors

    bars = store.prices(ticker, end=asof)
    if len(bars) < 120:
        return None
    dts = [b["date"] for b in bars]
    closes = np.array([b["close"] for b in bars], dtype=float)
    highs = np.array([b["high"] for b in bars], dtype=float)
    lows = np.array([b["low"] for b in bars], dtype=float)

    out = {
        "ticker": ticker.upper(),
        "last_close": float(closes[-1]),
        "n_bars": len(bars),
        "mom_12_1": R.momentum_12_1(closes),
        "ret_1m": R.cumulative_return(closes, 21),
        "realized_vol": R.realized_vol(closes, 63),
        "downside_vol": R.downside_vol(closes, 63),
        "ewma_vol": ewma_vol(R.daily_returns(closes)),
        "max_dd_1y": R.max_drawdown(closes[-252:]),
        "high_52w_ratio": R.high_52w_ratio(closes),
        "spread_bps": R.corwin_schultz_spread(highs[-63:], lows[-63:]) * 1e4,
    }

    rets = pd.Series(R.daily_returns(closes), index=pd.to_datetime(dts[1:]))
    factors = fetch_factors()
    factors.index = pd.to_datetime(factors.index)
    fit = factor_exposures(rets, factors, window=252)
    out.update({
        "beta_mkt": fit.betas.get("mkt_rf"),
        "beta_smb": fit.betas.get("smb"),
        "beta_hml": fit.betas.get("hml"),
        "beta_mom": fit.betas.get("mom"),
        "factor_r2": fit.r2,
        "idio_vol": fit.idio_vol_annual,
        "n_factor_obs": fit.n_obs,
    })
    return out
