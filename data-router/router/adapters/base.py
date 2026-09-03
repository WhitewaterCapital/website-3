"""Vendor-adapter contract.

Mirrors `engine/incepta/adapters/base.py`'s Protocol-per-data-class shape,
generalized across every data class the router spec names. A vendor is one
adapter class; adding a vendor later is "write one new `Adapter` subclass",
never a router change and never a model change.

Not every vendor covers every data class (a news vendor may not carry
fundamentals; a fundamentals vendor may not carry news). Rather than forcing
every adapter to implement every method, each adapter declares a
`capabilities` set of `DataClass` values it actually supports, and the base
class's default method bodies raise `NotImplementedError` for anything a
subclass didn't override. The router checks `adapter.supports(...)` before
ever calling a method, so an adapter's "I don't do this" is a documented,
inspectable fact (the `capabilities` set) rather than something the router
discovers by catching an exception.
"""

from __future__ import annotations

from abc import ABC
from datetime import date
from enum import Enum
from typing import Optional

from ..schema import (
    Bar,
    CorporateAction,
    FundamentalFact,
    Holding,
    MacroObservation,
    NewsItem,
)


class DataClass(str, Enum):
    """The data classes the spec names. String-valued so a quota/circuit key
    like `(vendor, data_class)` serializes and logs cleanly."""

    BARS = "bars"
    FUNDAMENTALS = "fundamentals"
    CORPORATE_ACTIONS = "corporate_actions"
    HOLDINGS = "holdings"
    NEWS = "news"
    MACRO = "macro"


class VendorNotConfiguredError(RuntimeError):
    """Raised by a real-vendor adapter when it is called without the
    credentials (env var) it needs. Named after the missing env var so the
    fix is obvious from the exception message alone."""


class Adapter(ABC):
    """Base class for every vendor adapter.

    Subclasses set `name` (the internal vendor id used in quota/circuit/PIT
    records — never a model-facing concept) and `capabilities` (the subset of
    `DataClass` the vendor actually serves), then override only the
    `get_*` methods that capability set requires.
    """

    name: str = "unconfigured"
    capabilities: frozenset[DataClass] = frozenset()

    def supports(self, data_class: DataClass) -> bool:
        return data_class in self.capabilities

    # -- one method per data class -------------------------------------------
    def get_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        raise NotImplementedError(f"{self.name} does not implement get_bars")

    def get_fundamentals(self, ticker: str) -> list[FundamentalFact]:
        raise NotImplementedError(f"{self.name} does not implement get_fundamentals")

    def get_corporate_actions(self, ticker: str) -> list[CorporateAction]:
        raise NotImplementedError(f"{self.name} does not implement get_corporate_actions")

    def get_holdings(self, portfolio_id: str, as_of: date) -> list[Holding]:
        raise NotImplementedError(f"{self.name} does not implement get_holdings")

    def get_news(self, ticker: Optional[str] = None, since: Optional[date] = None) -> list[NewsItem]:
        raise NotImplementedError(f"{self.name} does not implement get_news")

    def get_macro(self, series_id: str, start: date, end: date) -> list[MacroObservation]:
        raise NotImplementedError(f"{self.name} does not implement get_macro")


# Maps a DataClass to the Adapter method name that serves it. The router uses
# this instead of a chain of if/elif so adding a data class is a one-line
# change in exactly one place (here) plus the schema/adapter method.
METHOD_FOR_DATA_CLASS: dict[DataClass, str] = {
    DataClass.BARS: "get_bars",
    DataClass.FUNDAMENTALS: "get_fundamentals",
    DataClass.CORPORATE_ACTIONS: "get_corporate_actions",
    DataClass.HOLDINGS: "get_holdings",
    DataClass.NEWS: "get_news",
    DataClass.MACRO: "get_macro",
}
