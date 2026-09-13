"""Tiingo daily price adapter (free tier, requires a free API key), resampled
to weekly OHLCV for WW-WEEKLY.

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
       `wf/config.py`'s `_load_dotenv()` loads intra-exitus-engine's .env).

INTEGRITY NOTES (still true even with clean prices):
  - Tiingo covers listed names; a *survivorship-free* universe (delisted/
    bankrupt) still requires Sharadar/CRSP. `wf.config.UNIVERSE`/`SECTOR_MAP`
    are today's constituents, not a point-in-time historical universe/sector
    file — see README.md "What a real run needs" point 2.
  - Free-tier redistribution/commercial terms must be checked before shipping
    a paid members' product.

This is a self-contained copy of the same adapter pattern used by
`intra-exitus-engine/ie/adapters/prices_tiingo.py` and
`engine/incepta/adapters/prices_tiingo.py` — this engine shares no code with
either, by design (see weekly-engine/README.md: "This engine is its own
world"). One deliberate difference from those two: WW-WEEKLY's feature layer
(`wf/features/panel.py::prepare_base`) needs a WEEKLY-resampled OHLCV frame
per ticker (index = week-ending Friday, columns at least close/volume), never
a raw daily bar sequence — so alongside the same `PriceBar`/`TiingoClient`
shape those adapters use, this module adds the daily-to-weekly resampler and
a per-universe fetch helper.
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

_WEEKLY_COLUMNS = ["open", "high", "low", "close", "volume"]


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
            "then put it in weekly-engine/.env as TIINGO_API_KEY=your_token"
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
        # an intraday snapshot, not a real close. Drop it rather than build a
        # weekly bar on top of it.
        if bars and bars[-1].date >= date.today():
            bars = bars[:-1]
        return bars


def _bars_to_daily_frame(bars: list[PriceBar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=_WEEKLY_COLUMNS, index=pd.DatetimeIndex([], name="date"))
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp(b.date) for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        }
    ).set_index("date").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.index.name = "date"
    return df


def _resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Resample a daily OHLCV frame to weekly bars ending Friday — the same
    convention `wf.synthetic`'s fixtures use. Drops the most recent bucket
    when it is built from a partial (still-in-progress) week: if the last
    daily bar isn't itself a Friday, the current week hasn't closed yet, and
    publishing that bucket's close as if it were a real week-end close would
    be exactly the "unsettled bar" problem the daily client already guards
    against one level up (see `TiingoClient.fetch_prices`)."""
    if daily.empty:
        return pd.DataFrame(columns=_WEEKLY_COLUMNS, index=pd.DatetimeIndex([], name="date"))
    weekly = daily.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    weekly = weekly.dropna(how="all")
    if len(weekly) and daily.index[-1].weekday() != 4:  # 4 == Friday
        weekly = weekly.iloc[:-1]
    weekly.index.name = "date"
    return weekly


def fetch_weekly_ohlcv(
    ticker: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    client: Optional[TiingoClient] = None,
) -> pd.DataFrame:
    """One ticker's real weekly-resampled OHLCV frame — the exact shape
    `wf.features.panel.prepare_base` requires (ascending, unique
    DatetimeIndex, at least close/volume columns)."""
    client = client or TiingoClient()
    bars = client.fetch_prices(ticker, start=start, end=end)
    return _resample_weekly(_bars_to_daily_frame(bars))


def fetch_universe_weekly_prices(
    tickers: list[str],
    start: Optional[date] = None,
    end: Optional[date] = None,
    client: Optional[TiingoClient] = None,
) -> dict[str, pd.DataFrame]:
    """`{ticker: weekly_ohlcv_frame}` for every name in `tickers`, one Tiingo
    client shared across all of them (keeps the adapter's own rate-limit
    throttle in `TiingoClient._get` effective across the whole universe
    instead of resetting per ticker)."""
    client = client or TiingoClient()
    return {t: fetch_weekly_ohlcv(t, start=start, end=end, client=client) for t in tickers}
