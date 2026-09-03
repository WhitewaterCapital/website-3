"""Point-in-time store contract for the data router.

Mirrors `engine/incepta/store/base.py`'s shape: a small, storage-agnostic
Protocol so the router can write through to a local dev store today and a
production PIT store (e.g. the engine's DuckDB/Supabase store) later without
any router code changing — the router only ever calls `write(record)`.

`InMemoryPointInTimeStore` is a minimal reference implementation, useful for
tests and for local development; it is not a production store (no
durability, no as-of query surface) — that responsibility stays with the
engine's own PIT store (`engine/incepta/store/`).
"""

from __future__ import annotations

from typing import Any, Protocol


class PointInTimeStore(Protocol):
    def write(self, records: list[Any]) -> None:
        """Persist the batch of provenance-stamped records (`router.schema`
        instances) produced by one successful adapter call. The router calls
        this exactly once per successful `DataRouter.fetch` — one write-through
        per vendor call, not one per record — so a caller can assert
        "one successful fetch => one write call" directly against a call
        counter."""
        ...


class InMemoryPointInTimeStore:
    """Reference implementation: keeps every written batch, in write order.
    Good enough for tests and local dev; not a durable store."""

    def __init__(self) -> None:
        self.records: list[Any] = []
        self.write_calls: int = 0

    def write(self, records: list[Any]) -> None:
        self.write_calls += 1
        self.records.extend(records)

    def __len__(self) -> int:
        return len(self.records)
