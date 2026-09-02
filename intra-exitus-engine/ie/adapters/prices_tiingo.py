"""Tiingo daily price adapter (free tier, requires a free API key).

Why Tiingo: verified (2026-08) as the cleanest free EOD source — a documented
JSON API, decades of history, and **split- AND dividend-adjusted** fields
(`adjClose` etc.). Stooq's free CSV endpoint is now behind a JavaScript
bot-detection wall and is no longer programmatically usable (and bypassing bot
detection is off-limits), so Tiingo is the working free source.

Setup:
    1. Register free at https://www.tiingo.com and copy your API token.
    2. Put it in this engine's .env:  TIINGO_API_KEY=your_token

INTEGRITY NOTES (still true even with clean prices):
  - Tiingo covers listed names; a *survivorship-free* universe (delisted/bankrupt)
    still requires Sharadar/CRSP. Adjusted prices != survivorship-free universe.
  - Free-tier redistribution/commercial terms must be checked before shipping a
    paid members' product.

This is a self-contained copy of the same adapter pattern the Incepta engine uses
— the two engines share no code, by design.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from typing import Optional

import requests

from ..pit import PriceBar

_BASE = "https://api.tiingo.com/tiingo/daily/{ticker}/prices"
_TIMEOUT = 30
_MIN_INTERVAL_S = 0.2


def tiingo_key() -> str:
    k = os.environ.get("TIINGO_API_KEY", "").strip()
    if not k:
        raise RuntimeError(
            "TIINGO_API_KEY is not set. Get a free key at https://www.tiingo.com "
            "then put it in intra-exitus-engine/.env as TIINGO_API_KEY=your_token"
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
        return bars
