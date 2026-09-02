"""Point-in-time data model for prices.

A daily bar dated D is only knowable after D's close, so a point-in-time read is
simply "every bar with date <= asof". The whole feature layer is built to respect
this: a feature at row t may look *back* over the series but never *forward*. That
property is asserted directly in the tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class PriceBar:
    """One daily OHLCV bar.

    `adjusted` records whether the source pre-adjusted for splits/dividends. Tiingo
    serves fully-adjusted fields; the free tier is fine for research but not a
    survivorship-free universe — see the adapter docstring for integrity caveats.
    """

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


def bars_to_frame(bars: list[PriceBar]) -> pd.DataFrame:
    """Turn a list of PriceBars into an OHLCV DataFrame indexed by date (ascending,
    de-duplicated). The canonical input shape for the feature layer.

    Columns: open, high, low, close, volume. Index: DatetimeIndex, sorted, unique.
    """
    if not bars:
        return pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"],
            index=pd.DatetimeIndex([], name="date"),
        )
    rows = [
        {
            "date": pd.Timestamp(b.date),
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
        }
        for b in bars
    ]
    df = pd.DataFrame(rows).set_index("date").sort_index()
    # Collapse any duplicate dates to the last ingested bar for that day.
    df = df[~df.index.duplicated(keep="last")]
    df.index.name = "date"
    return df
