"""A per-venue trading calendar, extended with half (early-close) days, built
entirely from a *stored* table — never computed at runtime from a calendar
library that might change its notion of "US market holidays" out from under
this codebase.

``router.universe.TradingCalendar`` (already in this repo, unmodified here)
already does exactly this for full holidays vs. weekends. It has no notion of
a half day, so this module adds ``VenueCalendar``: a thin wrapper that holds
a ``TradingCalendar`` for the holiday/weekend logic plus an explicit stored
set of half-day dates, and answers "closed / half / full" per date. This is
composition on top of the existing module, not a fork of it — no code in
``router/universe.py`` is duplicated or altered.

Data provenance: the dates below are NYSE's own publicly published holiday
and early-close schedule (NYSE announces each calendar year's holidays and
early closes in advance; https://www.nyse.com/markets/hours-calendars is the
canonical published source). They are transcribed here as a literal, dated
table — precisely so that a future change to some calendar library's
algorithmic notion of holidays (or a one-off ad hoc market closure) cannot
silently drift this codebase's answer to "was market X open on date D".
Refreshing this table for a new year is a data update (edit the tuples
below, cite the source), never a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from router.universe import TradingCalendar

# --- NYSE, 2024-2027: full holidays -----------------------------------------
# (Observed-holiday rule already applied where a holiday falls on a weekend,
# e.g. Independence Day 2026 falls on Saturday 7/4 and is observed Friday
# 7/3 — that observed date is what's listed, not the calendar date.)
NYSE_HOLIDAYS: frozenset[date] = frozenset({
    # 2024
    date(2024, 1, 1),   # New Year's Day
    date(2024, 1, 15),  # Martin Luther King Jr. Day
    date(2024, 2, 19),  # Washington's Birthday
    date(2024, 3, 29),  # Good Friday
    date(2024, 5, 27),  # Memorial Day
    date(2024, 6, 19),  # Juneteenth
    date(2024, 7, 4),   # Independence Day
    date(2024, 9, 2),   # Labor Day
    date(2024, 11, 28), # Thanksgiving Day
    date(2024, 12, 25), # Christmas Day
    # 2025
    date(2025, 1, 1),
    date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 4, 18),
    date(2025, 5, 26),
    date(2025, 6, 19),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),   # Independence Day observed (7/4 falls on a Saturday)
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1),
    date(2027, 1, 18),
    date(2027, 2, 15),
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),
    date(2027, 6, 18),  # Juneteenth observed (6/19 falls on a Saturday)
    date(2027, 7, 5),   # Independence Day observed (7/4 falls on a Sunday)
    date(2027, 9, 6),
    date(2027, 11, 25),
    date(2027, 12, 24), # Christmas observed (12/25 falls on a Saturday)
})

# --- NYSE, 2024-2027: scheduled early closes (half days) -------------------
NYSE_HALF_DAYS: frozenset[date] = frozenset({
    date(2024, 7, 3),   # day before Independence Day
    date(2024, 11, 29), # day after Thanksgiving
    date(2024, 12, 24), # Christmas Eve
    date(2025, 7, 3),   # day before Independence Day
    date(2025, 11, 28), # day after Thanksgiving
    date(2025, 12, 24), # Christmas Eve
    date(2026, 7, 2),   # day before the observed Independence Day holiday
    date(2026, 11, 27), # day after Thanksgiving
    date(2026, 12, 24), # Christmas Eve
    date(2027, 11, 26), # day after Thanksgiving
    date(2027, 12, 23), # day before the observed Christmas holiday
})


class SessionType(str, Enum):
    CLOSED = "closed"
    HALF_DAY = "half_day"
    FULL_DAY = "full_day"


@dataclass(frozen=True)
class VenueCalendar:
    """A named venue's trading calendar: full holidays + weekends (delegated
    to ``router.universe.TradingCalendar``) plus an explicit half-day table.

    Nothing here is computed from a live calendar library; both the
    holiday set (via ``calendar``) and ``half_days`` are supplied data.
    """

    venue: str
    calendar: TradingCalendar
    half_days: frozenset = field(default_factory=frozenset)

    def session_type(self, d: date) -> SessionType:
        if not self.calendar.is_trading_day(d):
            return SessionType.CLOSED
        if d in self.half_days:
            return SessionType.HALF_DAY
        return SessionType.FULL_DAY

    def is_trading_day(self, d: date) -> bool:
        """A half day still counts as a trading day (the venue is open,
        just for fewer hours) — only ``CLOSED`` is a non-trading day."""
        return self.session_type(d) != SessionType.CLOSED

    def is_half_day(self, d: date) -> bool:
        return self.session_type(d) == SessionType.HALF_DAY


def nyse_calendar() -> VenueCalendar:
    """The stored NYSE calendar for 2024-2027. Extending the coverage window
    is a data update (add rows to the tables above), not a code change."""
    return VenueCalendar(
        venue="NYSE",
        calendar=TradingCalendar(holidays=NYSE_HOLIDAYS),
        half_days=NYSE_HALF_DAYS,
    )
