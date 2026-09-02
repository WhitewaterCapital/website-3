"""Feature-store contract.

Slice 1 stores raw PIT facts. The interface is deliberately small and storage-
agnostic so the same code can target local DuckDB now and Supabase Postgres for
the serving layer later (the `as_of` read is the one that must never leak).
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol

from ..pit import Fact


class FeatureStore(Protocol):
    def upsert_facts(self, facts: list[Fact]) -> int:
        """Insert facts idempotently. Returns rows written. Grain:
        (cik, taxonomy, concept, unit, period_end, accn)."""
        ...

    def facts_asof(
        self,
        ticker: str,
        asof: date,
        first_reported_only: bool = True,
    ) -> list[dict]:
        """Return the latest value per (concept, period) that was PUBLIC on/before
        `asof` — i.e. `filed <= asof`. This is the anti-look-ahead read."""
        ...

    def latest_standardized_asof(self, ticker: str, asof: date) -> dict:
        """Most-recent value per *standardized* field knowable as of `asof`."""
        ...

    def close(self) -> None:
        ...
