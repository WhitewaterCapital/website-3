"""Data-adapter contracts.

The dossier and the Incepta plan both insist on an *adapter abstraction* so that
adding a paid vendor later (EODHD, FMP, Sharadar) is a new adapter, not a rewrite.
Slice 1 only implements the fundamentals adapter (SEC EDGAR); the price adapter
protocol is declared now so slice 2 slots in cleanly.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from ..pit import Fact


@runtime_checkable
class FundamentalsAdapter(Protocol):
    """Yields point-in-time fundamental facts for a security."""

    name: str

    def resolve_cik(self, ticker: str) -> Optional[int]:
        """Map a ticker to its SEC CIK (or None if unknown)."""
        ...

    def fetch_facts(self, ticker: str) -> list[Fact]:
        """Return every reported fundamental fact for the ticker, PIT-stamped."""
        ...


@runtime_checkable
class PriceAdapter(Protocol):
    """Slice 2. Declared now so the interface is stable."""

    name: str

    def fetch_prices(self, ticker: str, start: date, end: date) -> list:  # pragma: no cover
        ...
