"""Circuit breaker: pulls a vendor out of rotation after repeated failures or
rate-limit responses, and puts it back only after it has proven itself again.

Lifecycle (exactly the spec's wording):

    healthy (CLOSED) -> tripped (OPEN) -> cooldown (still OPEN, timer running)
    -> half-open probe (HALF_OPEN) -> recovered (CLOSED)

or, if the probe itself fails: half-open probe -> back to OPEN (a fresh
cooldown starts).

`window_seconds` bounds what "repeated" means — only failures within the
trailing window count toward the trip threshold, so a vendor that fails once
a week forever never trips. The clock is injectable
(`Callable[[], float]`, matching `time.monotonic`) so tests never sleep.

Every state transition appends to `self.events` (a plain list — "a simple
callback or event-log list is fine, no real alerting integration needed", per
the spec) and, if an `on_event` callback was supplied, calls it too, so a
real alerting integration is a one-line addition later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class CircuitState(str, Enum):
    CLOSED = "closed"  # healthy — requests flow normally
    OPEN = "open"  # tripped / in cooldown — vendor is out of rotation
    HALF_OPEN = "half_open"  # cooldown elapsed — a single probe is allowed


@dataclass
class CircuitEvent:
    name: str
    time: float
    detail: dict = field(default_factory=dict)


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        window_seconds: float,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
        on_event: Optional[Callable[[CircuitEvent], None]] = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._on_event = on_event
        self._state = CircuitState.CLOSED
        self._failure_times: list[float] = []
        self._opened_at: Optional[float] = None
        self.events: list[CircuitEvent] = []

    def _emit(self, name: str, **detail) -> None:
        event = CircuitEvent(name=name, time=self._clock(), detail=detail)
        self.events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def _settle(self) -> None:
        """Apply time-based transitions (OPEN -> HALF_OPEN once cooldown has
        elapsed) before reporting or acting on state. Idempotent."""
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if self._clock() - self._opened_at >= self._cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._emit("half_open")

    @property
    def state(self) -> CircuitState:
        self._settle()
        return self._state

    def allow_request(self) -> bool:
        """Whether the router may currently call this vendor. False only
        while OPEN (mid-cooldown); both CLOSED and HALF_OPEN allow a call —
        HALF_OPEN's single allowed call *is* the probe."""
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        state = self.state
        if state is CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._failure_times.clear()
            self._opened_at = None
            self._emit("recovered")
        elif state is CircuitState.CLOSED:
            # A success while healthy needs no state change; failures already
            # age out of the trailing window on their own in record_failure.
            pass

    def record_failure(self, *, rate_limited: bool = False) -> None:
        now = self._clock()
        state = self.state
        if state is CircuitState.HALF_OPEN:
            # The probe failed: back to OPEN, cooldown restarts from now.
            self._state = CircuitState.OPEN
            self._opened_at = now
            self._failure_times = [now]
            self._emit("probe_failed", rate_limited=rate_limited)
            return

        self._failure_times.append(now)
        self._failure_times = [t for t in self._failure_times if now - t <= self._window_seconds]

        if state is CircuitState.OPEN:
            # Already tripped; nothing new to do besides recording the
            # failure count (useful for diagnostics).
            return

        if len(self._failure_times) >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = now
            self._emit(
                "tripped",
                failure_count=len(self._failure_times),
                rate_limited=rate_limited,
            )
