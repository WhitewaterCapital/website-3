"""Tests for clocks/market_hours.py (IMP-07)."""

from __future__ import annotations

from datetime import date, datetime, time

import pytest

from clocks.market_hours import MarketHoursGate, SessionHours, adapt_venue_calendar


class FakeCalendar:
    """Minimal CalendarLike stand-in: date -> "full" | "half" | "closed"."""

    def __init__(self, kinds: dict[date, str], default: str = "full"):
        self._kinds = kinds
        self._default = default

    def session_kind(self, d: date) -> str:
        return self._kinds.get(d, self._default)


WEEKDAY = date(2026, 6, 10)     # an ordinary Wednesday, a "full" session in our fake calendar
A_HOLIDAY = date(2026, 12, 25)  # Christmas, "closed" in our fake calendar
A_HALF_DAY = date(2026, 11, 27) # day after Thanksgiving, "half" in our fake calendar


def make_gate(default_kind: str = "full") -> MarketHoursGate:
    calendar = FakeCalendar(
        kinds={A_HOLIDAY: "closed", A_HALF_DAY: "half"},
        default=default_kind,
    )
    return MarketHoursGate(venue="TEST", calendar=calendar)


# (a) requires_market_hours=False is always allowed, even on a day the
#     calendar would otherwise refuse.

def test_market_hours_not_required_is_always_allowed_even_on_a_holiday():
    gate = make_gate()
    when = datetime(A_HOLIDAY.year, A_HOLIDAY.month, A_HOLIDAY.day, 3, 0)  # 3am on a holiday
    allowed, reason = gate.should_run(when, requires_market_hours=False)
    assert allowed is True
    assert "not required" in reason


def test_market_hours_not_required_is_always_allowed_at_any_hour():
    gate = make_gate()
    when = datetime(WEEKDAY.year, WEEKDAY.month, WEEKDAY.day, 23, 59)  # well outside any session
    allowed, reason = gate.should_run(when, requires_market_hours=False)
    assert allowed is True


# (b) requires_market_hours=True refuses on a closed day, with a clear reason.

def test_market_hours_required_refuses_on_a_holiday_with_clear_reason():
    gate = make_gate()
    when = datetime(A_HOLIDAY.year, A_HOLIDAY.month, A_HOLIDAY.day, 10, 0)  # would be mid-session hours
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is False
    assert "closed" in reason
    assert "TEST" in reason


def test_market_hours_required_refuses_outside_session_hours_on_an_open_day():
    gate = make_gate()
    when = datetime(WEEKDAY.year, WEEKDAY.month, WEEKDAY.day, 20, 0)  # 8pm, well after close
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is False
    assert "outside session" in reason


def test_market_hours_required_refuses_on_a_half_day_after_the_early_close():
    gate = make_gate()
    when = datetime(A_HALF_DAY.year, A_HALF_DAY.month, A_HALF_DAY.day, 14, 0)  # 2pm, after 1pm half-day close
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is False
    assert "half-day" in reason


# (c) requires_market_hours=True allows during a real session.

def test_market_hours_required_allows_during_a_normal_session():
    gate = make_gate()
    when = datetime(WEEKDAY.year, WEEKDAY.month, WEEKDAY.day, 11, 0)  # 11am on an ordinary weekday
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is True
    assert "open" in reason


def test_market_hours_required_allows_during_a_half_day_before_the_early_close():
    gate = make_gate()
    when = datetime(A_HALF_DAY.year, A_HALF_DAY.month, A_HALF_DAY.day, 10, 0)  # 10am, before 1pm half-day close
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is True


def test_market_hours_required_refuses_before_the_open():
    gate = make_gate()
    when = datetime(WEEKDAY.year, WEEKDAY.month, WEEKDAY.day, 6, 0)  # 6am, before 9:30 open
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is False
    assert "outside session" in reason


def test_custom_session_hours_are_respected():
    calendar = FakeCalendar(kinds={}, default="full")
    gate = MarketHoursGate(venue="LSE", calendar=calendar, hours=SessionHours(
        open_time=time(8, 0),
        full_close_time=time(16, 30),
        half_close_time=time(12, 30),
    ))
    allowed, _ = gate.should_run(datetime(2026, 6, 10, 8, 30), requires_market_hours=True)
    assert allowed is True
    allowed, _ = gate.should_run(datetime(2026, 6, 10, 17, 0), requires_market_hours=True)
    assert allowed is False


# adapt_venue_calendar: adapts any object with .session_type(date) returning
# something with .value in {"full_day","half_day","closed"}, without this
# module importing data-router itself.

class _FakeVenueCalendarStyleEnum:
    def __init__(self, value: str):
        self.value = value


class _FakeVenueCalendar:
    """Shaped exactly like data-router's calendar_data.VenueCalendar, but
    defined locally so this unit test does not depend on data-router."""

    def __init__(self, closed_dates: set[date], half_dates: set[date]):
        self._closed = closed_dates
        self._half = half_dates

    def session_type(self, d: date):
        if d in self._closed:
            return _FakeVenueCalendarStyleEnum("closed")
        if d in self._half:
            return _FakeVenueCalendarStyleEnum("half_day")
        return _FakeVenueCalendarStyleEnum("full_day")


def test_adapt_venue_calendar_translates_session_type_values():
    fake_venue_calendar = _FakeVenueCalendar(closed_dates={A_HOLIDAY}, half_dates={A_HALF_DAY})
    adapted = adapt_venue_calendar(fake_venue_calendar)
    assert adapted.session_kind(A_HOLIDAY) == "closed"
    assert adapted.session_kind(A_HALF_DAY) == "half"
    assert adapted.session_kind(WEEKDAY) == "full"

    gate = MarketHoursGate(venue="ADAPTED", calendar=adapted)
    allowed, reason = gate.should_run(datetime(A_HOLIDAY.year, A_HOLIDAY.month, A_HOLIDAY.day, 10, 0), True)
    assert allowed is False
    assert "closed" in reason
