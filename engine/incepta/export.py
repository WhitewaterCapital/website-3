"""Handoff exporter: turns the engine's outputs into ONE JSON document the
website can consume. Every security carries a `data_quality` block and a
`confidence` level so the UI can honestly show what to trust and grey out what it
can't — the "abstain when data is thin" principle, enforced in the payload.

The JSON schema is mirrored in `contracts/equity_export.ts` (TypeScript types for
the website) and documented in `INTEGRATION.md`.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from . import __version__
from .models.valuation import compute_valuation
from .pipeline import quality_snapshot, risk_snapshot
from .store.duckdb_store import DuckDBStore

SCHEMA_VERSION = "1.0.0"
DISCLAIMER = (
    "Research/paper output only. Not investment advice, not a validated alpha "
    "model, and not to be used for real-capital decisions. Built on free data "
    "with known survivorship and point-in-time limitations."
)


def _clean(obj):
    """Make values JSON-safe: numpy scalars -> python, NaN/inf -> None."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy scalar
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def _annual_latest(store: DuckDBStore, ticker: str, asof: date) -> dict:
    series = store.standardized_series_asof(ticker, asof, annual_only=True)
    return {f: (s[-1]["value"] if s else None) for f, s in series.items()}


def _confidence(has_px: bool, has_fund: bool, flags: list) -> str:
    if not has_px and not has_fund:
        return "insufficient"
    if has_px and has_fund:
        return "medium" if flags else "high"
    return "low"


def build_security(store: DuckDBStore, ticker: str, asof: date) -> dict:
    comp = store.company(ticker) or {}
    q = quality_snapshot(store, ticker, asof)   # None if no fundamentals
    r = risk_snapshot(store, ticker, asof)      # None if no prices

    valuation = None
    if r is not None:
        ann = _annual_latest(store, ticker, asof)
        v = compute_valuation(
            price=r["last_close"],
            shares_outstanding=ann.get("shares_outstanding"),
            net_income=ann.get("net_income"),
            stockholders_equity=ann.get("stockholders_equity"),
            revenue=ann.get("revenue"),
            operating_cash_flow=ann.get("operating_cash_flow"),
            capex=ann.get("capex"),
            long_term_debt=ann.get("long_term_debt"),
            cash_and_equivalents=ann.get("cash_and_equivalents"),
            sic=comp.get("sic"),
        )
        valuation = {
            "market_cap": v.market_cap, "pe": v.pe, "earnings_yield": v.earnings_yield,
            "pb": v.pb, "ps": v.ps, "fcf_yield": v.fcf_yield, "ev": v.ev,
            "ev_sales": v.ev_sales, "flags": v.flags,
        }

    has_px, has_fund = r is not None, q is not None
    flags: list = []
    if not has_px:
        flags.append("no price history")
    if not has_fund:
        flags.append("no fundamentals")
    if valuation and valuation["flags"]:
        flags.extend(valuation["flags"])

    fund_pe = q["period_end"] if q else None
    stale = False
    if fund_pe:
        age_days = (asof - fund_pe).days
        if age_days > 460:  # > ~15 months since last annual → stale
            flags.append(f"fundamentals {age_days}d old")
            stale = True

    return _clean({
        "ticker": ticker.upper(),
        "name": comp.get("name"),
        "sector": comp.get("sic_description"),
        "sic": comp.get("sic"),
        "as_of": asof,
        "data_quality": {
            "has_prices": has_px,
            "has_fundamentals": has_fund,
            "fundamentals_period_end": fund_pe,
            "price_last_close": r["last_close"] if r else None,
            "stale": stale,
            "flags": flags,
        },
        "confidence": _confidence(has_px, has_fund, flags),
        "risk": r,
        "quality": q,
        "valuation": valuation,
    })


def build_export(store: DuckDBStore, tickers: list, asof: date) -> dict:
    securities = [build_security(store, t.upper(), asof) for t in tickers]

    # quality ranking (only names with fundamentals)
    from .pipeline import quality_ranking
    qr = quality_ranking(store, [t.upper() for t in tickers], asof)
    rankings = {"quality": []}
    if not qr.empty:
        rankings["quality"] = _clean([
            {"ticker": idx, "rank": row["rank"], "score": row["score"]}
            for idx, row in qr.iterrows()
        ])

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": __version__,
        "generated_at": datetime.now().isoformat(),
        "as_of": asof.isoformat(),
        "universe": [t.upper() for t in tickers],
        "disclaimer": DISCLAIMER,
        "securities": securities,
        "rankings": rankings,
    }


def write_export(payload: dict, paths: list) -> list:
    written = []
    for p in paths:
        p = Path(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
        written.append(str(p))
    return written
