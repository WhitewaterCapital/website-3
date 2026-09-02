"""Point-in-time data model.

The dossier's six-timestamp taxonomy, made concrete. Every fundamental fact we
store carries the timestamps needed to answer one question honestly: *what was
knowable at time T?* A backtest that violates this leaks the future.

We store, per fact:
- period_start / period_end  → the fiscal period the number describes
                               (period_start is None for balance-sheet instants)
- form                       → 10-K, 10-Q, 8-K, etc.
- filed                      → the filing date = our proxy for "public at" time
- accn                       → SEC accession number (the filing's identity)
- is_first_reported          → True for the earliest filing of this
                               (concept, period) pair; later rows are restatements
- ingested_at                → when *our* pipeline captured it

Rule enforced by the store's `as_of` reads: a fact is visible at decision time T
only if `filed <= T`. First-reported values let a backtest use as-first-reported
numbers rather than later-restated ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class Fact:
    """One reported XBRL fact, fully point-in-time stamped."""

    cik: int
    ticker: str
    taxonomy: str          # e.g. "us-gaap", "dei"
    concept: str           # e.g. "Revenues", "NetIncomeLoss"
    unit: str              # e.g. "USD", "shares", "USD/shares"
    period_start: Optional[date]  # None for instantaneous (balance-sheet) facts
    period_end: date
    value: float
    accn: str              # SEC accession number
    form: str              # "10-K", "10-Q", ...
    fiscal_year: Optional[int]
    fiscal_period: Optional[str]  # "FY", "Q1", ...
    filed: date            # filing date — the public-availability proxy
    frame: Optional[str]   # e.g. "CY2020Q4I" when SEC assigns a calendar frame
    is_first_reported: bool
    ingested_at: date

    @property
    def period_key(self) -> tuple:
        """Identifies the (concept, unit, period) an amendment would restate."""
        return (self.taxonomy, self.concept, self.unit, self.period_start, self.period_end)


@dataclass(frozen=True)
class PriceBar:
    """One daily OHLCV bar. Prices are point-in-time by nature: a bar dated D is
    only knowable after D's close, so an `as_of` read is just `date <= asof`.

    `adjusted` records whether the source pre-adjusted for splits/dividends. For
    the free Stooq source this is only partially verifiable — see the adapter's
    docstring. Capital-grade use requires a corporate-action-audited feed.
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
