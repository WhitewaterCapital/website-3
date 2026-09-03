"""IMP-07 — market-hours gate.

`scheduler.py` (ORCH-01) decides whether a job's *inputs* are fresh enough
for its own cadence. It has no notion at all of whether the *venue* the job
cares about is open — a job on an hourly cadence would happily fire at
3 a.m. on Thanksgiving and the scheduler would call the result "fresh"
because nothing there ever asked "is this venue even trading right now".

IMP-07 is explicit that this is not allowed: "No refreshing into a closed
market and calling the output new." `MarketHoursGate` is the missing check.
It is deliberately a separate, small object rather than a new field bolted
onto `scheduler.JobSpec` — the file-ownership boundary for this task treats
`scheduler.py` as read-only, and more importantly a market-hours decision is
a genuinely different axis from cadence/freshness: cadence asks "is this
input recent enough", market-hours asks "is anyone even trading right now,
for this date, at this venue". Composing two small single-purpose checks
(see `three_clocks.run_clock_job`) keeps each one testable on its own.

**Decoupling from `data-router`.** This module must not hard-import
anything from `data-router` — `orch` and `data-router` are separate
top-level packages in this repo, and previous passes (e.g.
`data-router/router/universe_publish/calendar_data.py`'s own header) treat
importing across that boundary from "core" logic as exactly the kind of
coupling this codebase avoids. Instead, `MarketHoursGate` depends only on
the small `CalendarLike` protocol below (`session_kind(date) -> SessionKind`)
duck-typed against whatever calendar object is handed to it. The one
concrete adapter for the real `data-router` calendar,
`adapt_venue_calendar`, is a pure function with no import of its own — it
takes an already-constructed venue-calendar-shaped object and wraps it.
Only the integration test in `tests/` actually imports
`data-router/router/universe_publish/calendar_data.py` and passes the real
object through that adapter; this module never does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Literal, Protocol

SessionKind = Literal["full", "half", "closed"]


class CalendarLike(Protocol):
    """Duck-typed calendar interface `MarketHoursGate` depends on. Anything
    exposing a `session_kind(d) -> "full" | "half" | "closed"` method
    satisfies this — no inheritance required."""

    def session_kind(self, d: date) -> SessionKind: ...


@dataclass(frozen=True)
class SessionHours:
    """Intraday open/close times for a venue's regular and half-day
    sessions. Neither `data-router`'s `TradingCalendar` nor its
    `VenueCalendar` wrapper track intraday times at all (both are
    date-granular: trading day / half day / holiday) — that clock-time
    knowledge belongs here, on the gate that actually needs to answer "is
    it open right now", not smuggled into the calendar-data module.

    Times are venue-local wall-clock times (e.g. NYSE = America/New_York).
    **Documented simplification**: this module does not do timezone
    conversion — callers must pass `when` to `MarketHoursGate.should_run`
    already expressed in the venue's local time. Wiring real timezone-aware
    scheduling (a UTC-scheduled job converting to each venue's local time,
    correctly across DST) is future work; see clocks/README.md.
    """

    open_time: time = time(9, 30)
    full_close_time: time = time(16, 0)
    half_close_time: time = time(13, 0)


def _kind_value(kind: object) -> str:
    """Accept either a plain string or an Enum-like object with `.value`
    (e.g. `calendar_data.SessionType`) without importing that enum."""
    return getattr(kind, "value", kind)


@dataclass(frozen=True)
class MarketHoursGate:
    """Gate that a clock consults before treating a market-hours-dependent
    refresh as legitimate.

    `venue` is a label only (used in the refusal reason string); `calendar`
    is any `CalendarLike`; `hours` overrides the default 9:30/16:00/13:00
    session times if the venue differs from that default.
    """

    venue: str
    calendar: CalendarLike
    hours: SessionHours = field(default_factory=SessionHours)

    def should_run(self, when: datetime, requires_market_hours: bool) -> tuple[bool, str]:
        """Returns (allowed, reason). Always allowed, with an explicit
        reason, when `requires_market_hours` is False (e.g. the macro
        clock: it does not care whether any venue is open). Otherwise
        gated by the calendar and session hours, with a specific,
        human-readable reason on refusal — the spec is explicit that
        refusing to refresh must never be a silent no-op."""
        if not requires_market_hours:
            return True, f"{self.venue}: market hours not required for this job"

        d = when.date()
        kind = _kind_value(self.calendar.session_kind(d))

        if kind == "closed":
            return False, f"closed: {self.venue} holiday or weekend on {d.isoformat()}"

        if kind not in ("full", "half"):
            raise ValueError(f"unrecognized session kind from calendar: {kind!r}")

        close_time = self.hours.full_close_time if kind == "full" else self.hours.half_close_time
        t = when.time()
        if t < self.hours.open_time or t >= close_time:
            return False, (
                f"closed: outside session ({self.venue} {kind}-day hours "
                f"{self.hours.open_time}-{close_time}, refresh requested at {t})"
            )
        return True, f"open: {self.venue} {kind}-day session"


def adapt_venue_calendar(venue_calendar: object) -> CalendarLike:
    """Wrap any object exposing `.session_type(date) -> <enum with .value
    in {"full_day","half_day","closed"} or one of those literal strings>`
    (this is exactly the shape of `data-router`'s
    `calendar_data.VenueCalendar`) as a `CalendarLike`.

    This function itself imports nothing from `data-router` — it is a
    structural adapter over whatever object satisfies that shape, so
    `market_hours.py` stays decoupled from the concrete `VenueCalendar`
    class. It is used by the integration test to plug the real NYSE
    calendar into a `MarketHoursGate` for the acceptance test wired against
    real stored holiday data.
    """

    class _VenueCalendarAdapter:
        def session_kind(self, d: date) -> SessionKind:
            raw = _kind_value(venue_calendar.session_type(d))
            if raw == "full_day":
                return "full"
            if raw == "half_day":
                return "half"
            if raw == "closed":
                return "closed"
            raise ValueError(f"unrecognized session_type value from adapted calendar: {raw!r}")

    return _VenueCalendarAdapter()
