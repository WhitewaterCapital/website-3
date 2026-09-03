"""Integration test: clocks/market_hours.py wired to the REAL data-router
calendar (`data-router/router/universe_publish/calendar_data.py`).

This is the one place in this whole `clocks/` package that imports across
the orch <-> data-router boundary, and it does so only to prove
`adapt_venue_calendar` really works against the concrete `VenueCalendar`
class, not just a hand-rolled fake — everywhere else (market_hours.py,
three_clocks.py, derived_value_guard.py) stays duck-typed and
import-free of data-router.

`data-router` is a sibling top-level package to `quant-infra`, not a
subpackage of it, so it is not on sys.path just because we're running
orch's own test suite — this file adds it explicitly, exactly the way a
real cross-package integration test would.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]  # .../WhiteWaterCapital-main
_DATA_ROUTER_ROOT = _REPO_ROOT / "data-router"

if str(_DATA_ROUTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_DATA_ROUTER_ROOT))

from router.universe_publish.calendar_data import nyse_calendar  # noqa: E402  (see sys.path setup above)

from clocks.market_hours import MarketHoursGate, adapt_venue_calendar
from clocks.three_clocks import EQUITY_CLOCK


def test_data_router_root_is_actually_present():
    # Fails loudly (rather than the import above silently having found some
    # other `router` package) if the repo layout assumption above is wrong.
    assert (_DATA_ROUTER_ROOT / "router" / "universe_publish" / "calendar_data.py").exists()


def test_real_nyse_calendar_refuses_a_known_holiday():
    venue_calendar = nyse_calendar()
    gate = MarketHoursGate(venue="NYSE", calendar=adapt_venue_calendar(venue_calendar))

    # 2025-12-25: Christmas Day, a full NYSE holiday in the stored table.
    when = datetime(2025, 12, 25, 11, 0)
    allowed, reason = gate.should_run(when, requires_market_hours=EQUITY_CLOCK.requires_market_hours)
    assert allowed is False
    assert "closed" in reason
    assert "NYSE" in reason


def test_real_nyse_calendar_refuses_a_weekend():
    venue_calendar = nyse_calendar()
    gate = MarketHoursGate(venue="NYSE", calendar=adapt_venue_calendar(venue_calendar))

    # 2026-06-13 is a Saturday.
    when = datetime(2026, 6, 13, 11, 0)
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is False
    assert "closed" in reason


def test_real_nyse_calendar_allows_an_ordinary_trading_day_during_session():
    venue_calendar = nyse_calendar()
    gate = MarketHoursGate(venue="NYSE", calendar=adapt_venue_calendar(venue_calendar))

    # 2026-06-10 is a Wednesday with no entry in either the holiday or
    # half-day stored tables.
    when = datetime(2026, 6, 10, 11, 0)
    allowed, reason = gate.should_run(when, requires_market_hours=True)
    assert allowed is True
    assert "open" in reason


def test_real_nyse_calendar_treats_a_known_half_day_as_open_before_but_not_after_early_close():
    venue_calendar = nyse_calendar()
    gate = MarketHoursGate(venue="NYSE", calendar=adapt_venue_calendar(venue_calendar))

    # 2025-12-24: Christmas Eve, a stored NYSE half day.
    before_close = datetime(2025, 12, 24, 11, 0)
    after_close = datetime(2025, 12, 24, 14, 0)

    allowed_before, _ = gate.should_run(before_close, requires_market_hours=True)
    allowed_after, reason_after = gate.should_run(after_close, requires_market_hours=True)

    assert allowed_before is True
    assert allowed_after is False
    assert "half-day" in reason_after
