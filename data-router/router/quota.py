"""Quota manager: per-vendor, per-minute AND per-day token buckets, plus a
priority queue so a high-priority request (e.g. a live chaos-engine pull)
is served ahead of a low-priority one (e.g. a bulk fundamentals backfill)
regardless of arrival order.

Two independent mechanisms, deliberately kept separate:

- `TokenBucket` / `QuotaManager` answer "is this vendor allowed to be called
  right now" — pure rate limiting, no notion of request priority at all.
- `Priority` / `PriorityRequestQueue` answer "given several pending requests
  all waiting on quota (or on each other), which one goes first" — pure
  ordering, no notion of vendor limits at all.

The router (`router.py`) composes both: it drains the priority queue in
priority order and, for each request, asks the quota manager whether the
vendor has budget before calling the adapter.

Every clock in this module is injectable (`Callable[[], float]`, matching
`time.monotonic`'s signature) so tests never sleep — a test clock is just a
mutable float a test advances by hand.
"""

from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Optional


class QuotaExceededError(RuntimeError):
    """Raised when a caller demands a vendor call be made (rather than
    checking first) and the vendor has no budget left."""


# --- Token bucket -------------------------------------------------------


@dataclass
class TokenBucket:
    """Classic token bucket: `capacity` tokens max, refilling continuously at
    `refill_rate_per_sec`. `try_consume` is the only mutating call and is
    atomic — it refills first, then either takes the tokens or takes nothing.
    """

    capacity: float
    refill_rate_per_sec: float
    clock: Callable[[], float] = time.monotonic
    tokens: float = field(init=False)
    _last_refill: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("capacity must be positive")
        if self.refill_rate_per_sec < 0:
            raise ValueError("refill_rate_per_sec must be non-negative")
        self.tokens = self.capacity
        self._last_refill = self.clock()

    def _refill(self) -> None:
        now = self.clock()
        elapsed = max(0.0, now - self._last_refill)
        if elapsed:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate_per_sec)
            self._last_refill = now

    def try_consume(self, n: float = 1.0) -> bool:
        """Refill, then consume `n` tokens if available. Returns whether the
        consumption happened; never partially consumes."""
        self._refill()
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    def available(self) -> float:
        """Current token count after applying refill (does not consume)."""
        self._refill()
        return self.tokens


# --- Per-vendor quota (minute + day) -------------------------------------


@dataclass(frozen=True)
class VendorLimits:
    per_minute: int
    per_day: int


class QuotaManager:
    """Owns one minute-bucket and one day-bucket per configured vendor. A
    call only succeeds if BOTH buckets have budget — checked before either is
    consumed, so a vendor at its daily cap never gets debited a minute-token
    it can't use."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[TokenBucket, TokenBucket]] = {}
        self._limits: dict[str, VendorLimits] = {}

    def configure(
        self,
        vendor: str,
        per_minute: int,
        per_day: int,
        burst_per_minute: Optional[int] = None,
        burst_per_day: Optional[int] = None,
    ) -> None:
        """Register (or replace) a vendor's limits. `burst_*` sets the bucket
        capacity (how many requests can fire back-to-back) independent of the
        steady-state refill rate; defaults to the limit itself (no extra
        burst headroom)."""
        minute_bucket = TokenBucket(
            capacity=burst_per_minute or per_minute,
            refill_rate_per_sec=per_minute / 60.0,
            clock=self._clock,
        )
        day_bucket = TokenBucket(
            capacity=burst_per_day or per_day,
            refill_rate_per_sec=per_day / 86400.0,
            clock=self._clock,
        )
        self._buckets[vendor] = (minute_bucket, day_bucket)
        self._limits[vendor] = VendorLimits(per_minute=per_minute, per_day=per_day)

    def _require(self, vendor: str) -> tuple[TokenBucket, TokenBucket]:
        if vendor not in self._buckets:
            raise KeyError(f"vendor {vendor!r} is not configured in QuotaManager")
        return self._buckets[vendor]

    def can_consume(self, vendor: str, n: float = 1.0) -> bool:
        minute_bucket, day_bucket = self._require(vendor)
        return minute_bucket.available() >= n and day_bucket.available() >= n

    def try_consume(self, vendor: str, n: float = 1.0) -> bool:
        """Atomically consume `n` from both the minute and day buckets, or
        neither. Returns whether the consumption succeeded."""
        minute_bucket, day_bucket = self._require(vendor)
        if minute_bucket.available() >= n and day_bucket.available() >= n:
            minute_bucket.tokens -= n
            day_bucket.tokens -= n
            return True
        return False

    def consume_or_raise(self, vendor: str, n: float = 1.0) -> None:
        if not self.try_consume(vendor, n):
            raise QuotaExceededError(f"vendor {vendor!r} has no remaining quota")

    def remaining(self, vendor: str) -> dict:
        minute_bucket, day_bucket = self._require(vendor)
        return {"per_minute": minute_bucket.available(), "per_day": day_bucket.available()}


# --- Priority queue -------------------------------------------------------


class Priority(IntEnum):
    """Lower value = served first (standard heapq convention). A live
    chaos-engine request must never queue behind a bulk backfill, so CHAOS
    sorts before BULK_BACKFILL regardless of arrival order."""

    CHAOS = 0
    INTERACTIVE = 5
    BULK_BACKFILL = 10


class PriorityRequestQueue:
    """A FIFO-within-priority-class queue: requests of equal priority are
    served in arrival order, but a higher-priority request always jumps ahead
    of a lower-priority one already waiting."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, Any]] = []
        self._counter = itertools.count()

    def push(self, priority: Priority, item: Any) -> None:
        heapq.heappush(self._heap, (int(priority), next(self._counter), item))

    def pop(self) -> Any:
        if not self._heap:
            raise IndexError("pop from an empty PriorityRequestQueue")
        _, _, item = heapq.heappop(self._heap)
        return item

    def peek(self) -> Any:
        if not self._heap:
            raise IndexError("peek on an empty PriorityRequestQueue")
        return self._heap[0][2]

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)
