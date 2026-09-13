"""Tiingo daily price adapter (free tier, requires a free API key).

Why Tiingo: verified (2026-08) as the cleanest free EOD source — a documented
JSON API, decades of history, and **split- AND dividend-adjusted** fields
(`adjClose` etc.). Stooq's free CSV endpoint is now behind a JavaScript
bot-detection wall and is no longer programmatically usable (and bypassing bot
detection is off-limits), so Tiingo is the working free source. See
`intra-exitus-engine/ie/adapters/prices_tiingo.py` for the original writeup of
that evaluation.

Setup:
    1. Register free at https://www.tiingo.com and copy your API token.
    2. Put it in this engine's .env:  TIINGO_API_KEY=your_token
       (or `export TIINGO_API_KEY=your_token` — either is read the same way
       `ge/config.py`'s `_load_dotenv()` loads intra-exitus-engine's .env).

INTEGRITY NOTES (still true even with clean prices):
  - Tiingo covers listed names; a *survivorship-free* universe (delisted/
    bankrupt) still requires Sharadar/CRSP. Adjusted prices != a
    survivorship-free universe — `ge.config.UNIVERSE` is today's constituents,
    not a point-in-time historical universe (see that module's docstring).
  - Free-tier redistribution/commercial terms must be checked before shipping
    a paid members' product.

This is a self-contained copy of the same adapter pattern used by
`intra-exitus-engine/ie/adapters/prices_tiingo.py` and
`engine/incepta/adapters/prices_tiingo.py` — this engine shares no code with
either, by design (see graph-engine/README.md: "This engine is its own
world"). One deliberate difference from those two: WW-GRAPH's pipeline
(`ge/pipeline.py`) only ever consumes a plain close-price PANEL — rows=dates,
columns=tickers, no gaps — never a per-ticker point-in-time `PriceBar`
sequence on its own. So alongside the same `PriceBar`/`TiingoClient` shape
those adapters use, this module adds `fetch_close_panel`, the combiner that
turns several tickers' bars into that one aligned panel.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests

_BASE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
_TIMEOUT = 30
_MIN_INTERVAL_S = 0.2


@dataclass(frozen=True)
class PriceBar:
    """One daily OHLCV bar. Field-for-field identical to
    `intra-exitus-engine/ie/pit.py`'s `PriceBar` — duplicated, not imported
    (this engine is sealed, see module docstring)."""

    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    adjusted: bool
    ingested_at: date


def tiingo_key() -> str:
    k = os.environ.get("TIINGO_API_KEY", "").strip()
    if not k:
        raise RuntimeError(
            "TIINGO_API_KEY is not set. Get a free key at https://www.tiingo.com "
            "then put it in graph-engine/.env as TIINGO_API_KEY=your_token"
        )
    return k


class TiingoClient:
    name = "tiingo"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._token = tiingo_key()
        self._last_ts = 0.0

    def _get(self, url: str, params: dict) -> list:
        gap = time.monotonic() - self._last_ts
        if gap < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - gap)
        self._last_ts = time.monotonic()
        params = {**params, "token": self._token}
        resp = self._session.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()

    def fetch_prices(
        self, ticker: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> list[PriceBar]:
        params: dict = {"format": "json", "resampleFreq": "daily"}
        if start:
            params["startDate"] = start.isoformat()
        if end:
            params["endDate"] = end.isoformat()
        rows = self._get(_BASE.format(ticker=ticker.lower()), params)
        ingested = date.today()
        bars: list[PriceBar] = []
        for r in rows:
            try:
                d = datetime.strptime(r["date"][:10], "%Y-%m-%d").date()
                # Prefer fully-adjusted fields (split + dividend).
                bars.append(
                    PriceBar(
                        ticker=ticker.upper(),
                        date=d,
                        open=float(r.get("adjOpen") or r["open"]),
                        high=float(r.get("adjHigh") or r["high"]),
                        low=float(r.get("adjLow") or r["low"]),
                        close=float(r.get("adjClose") or r["close"]),
                        volume=float(r.get("adjVolume") or r.get("volume") or 0.0),
                        source=self.name,
                        adjusted=True,
                        ingested_at=ingested,
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue  # skip malformed rows rather than corrupt the series
        bars.sort(key=lambda b: b.date)
        # Trust fix (same as engine/incepta's copy): Tiingo's daily endpoint
        # returns an UNSETTLED bar during market hours whose close is really
        # an intraday snapshot, not a real close. Anchoring a signal or a
        # correlation window on it contaminates the whole cross-section, so
        # drop it rather than trust it.
        if bars and bars[-1].date >= date.today():
            bars = bars[:-1]
        return bars


def fetch_close_panel(
    tickers: list[str],
    start: Optional[date] = None,
    end: Optional[date] = None,
    client: Optional[TiingoClient] = None,
) -> pd.DataFrame:
    """Fetch daily closes for every ticker in `tickers` and align them into
    one close-price panel: rows = dates, columns = tickers — exactly the
    shape `ge.pipeline.run_as_of`/`run_history` expect.

    A date is kept only if EVERY ticker has a bar for it (`dropna(how="any")`
    after an outer join). `ge.graph.construct.shrunk_correlation` requires a
    fully finite matrix, so a holiday-calendar mismatch or a gap in one
    name's history is resolved here, once, rather than pushed downstream into
    the graph/diffusion/residual math (which is untouched by this adapter and
    should never have to special-case missing data).
    """
    client = client or TiingoClient()
    closes: dict[str, pd.Series] = {}
    for t in tickers:
        bars = client.fetch_prices(t, start=start, end=end)
        if not bars:
            continue
        closes[t] = pd.Series(
            {pd.Timestamp(b.date): b.close for b in bars}, name=t
        )
    if not closes:
        return pd.DataFrame(columns=tickers, index=pd.DatetimeIndex([], name="date"))
    panel = pd.DataFrame(closes).sort_index()
    panel.index.name = "date"
    panel = panel.dropna(how="any")
    return panel
