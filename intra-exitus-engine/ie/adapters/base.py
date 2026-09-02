"""Price-adapter contract.

Only the price interface exists here — Intra / Exitus is a price/level model and
needs no fundamentals. Declaring the Protocol keeps swapping providers (a paid
vendor at scale) a drop-in, not a rewrite.
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable

from ..pit import PriceBar


@runtime_checkable
class PriceAdapter(Protocol):
    """Yields daily OHLCV bars for a ticker, oldest-first."""

    name: str

    def fetch_prices(
        self, ticker: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> list[PriceBar]:
        ...
