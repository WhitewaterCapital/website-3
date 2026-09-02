"""Stooq daily price adapter (free, no API key).

⚠️  INTEGRITY CAVEATS — read before trusting any backtest built on this:
  1. **Survivorship.** Stooq generally serves *currently listed* tickers. Delisted
     / bankrupt companies are often missing → a backtest universe built ONLY from
     Stooq is survivor-biased and will OVERSTATE returns. This is flagged by the
     data-quality layer and must be fixed with a survivorship-free feed (e.g.
     Sharadar/CRSP) before real capital. See the research dossier §10/§16.
  2. **Adjustment.** Stooq's US daily series is split-adjusted; full
     dividend-adjustment is **UNVERIFIED**. We record `adjusted=True` but treat it
     as provisional. Total-return work needs an audited corporate-action feed.
  3. **No official API / licence.** These CSV endpoints are undocumented and their
     redistribution terms are unclear. Fine for private research; NOT for
     redistribution or a commercial product without checking terms.

This adapter exists so the pipeline is real end-to-end now; it is deliberately
behind the `PriceAdapter` interface so a paid feed replaces it without a rewrite.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime
from typing import Optional

import requests

from ..pit import PriceBar

_STOOQ_CSV = "https://stooq.com/q/d/l/?s={sym}&i=d"
_TIMEOUT = 30
_MIN_INTERVAL_S = 0.3  # be polite to a free host


def _to_stooq_symbol(ticker: str) -> str:
    # US equities on Stooq are suffixed ".us" and lower-cased.
    return f"{ticker.strip().lower()}.us"


class StooqClient:
    name = "stooq"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "incepta-research/0.1"})
        self._last_ts = 0.0

    def _get(self, url: str) -> str:
        gap = time.monotonic() - self._last_ts
        if gap < _MIN_INTERVAL_S:
            time.sleep(_MIN_INTERVAL_S - gap)
        self._last_ts = time.monotonic()
        resp = self._session.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def fetch_prices(
        self, ticker: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> list[PriceBar]:
        text = self._get(_STOOQ_CSV.format(sym=_to_stooq_symbol(ticker)))
        ingested = date.today()
        bars: list[PriceBar] = []

        # As of 2026-08, Stooq gates the CSV endpoint behind a JavaScript
        # proof-of-work bot-detection challenge. Defeating that is bot-detection
        # bypass — we DO NOT do it. Detect the challenge and fail honestly.
        stripped = text.lstrip()
        if stripped.startswith("<") or "requires JavaScript" in text:
            raise RuntimeError(
                "Stooq is serving a bot-detection challenge, not data. This free "
                "endpoint is no longer programmatically usable (and bypassing bot "
                "detection is off-limits). Use a keyed adapter instead — set "
                "TIINGO_API_KEY and use the Tiingo adapter. See prices_tiingo.py."
            )

        reader = csv.DictReader(io.StringIO(text))
        # Expected header: Date,Open,High,Low,Close,Volume
        if reader.fieldnames is None or "Close" not in (reader.fieldnames or []):
            # Stooq returns a plain-text error (e.g. "No data") instead of CSV.
            raise ValueError(
                f"Stooq returned no usable price data for {ticker!r}. "
                f"This is common for delisted/foreign tickers (survivorship gap)."
            )

        for row in reader:
            try:
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            if start and d < start:
                continue
            if end and d > end:
                continue
            try:
                bars.append(
                    PriceBar(
                        ticker=ticker.upper(),
                        date=d,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=float(row["Volume"]) if row.get("Volume") else 0.0,
                        source=self.name,
                        adjusted=True,  # provisional — see module caveats
                        ingested_at=ingested,
                    )
                )
            except (ValueError, KeyError):
                continue  # skip malformed rows rather than corrupt the series

        bars.sort(key=lambda b: b.date)
        return bars
