"""Tests for clocks/three_clocks.py (IMP-07): the concrete macro/equity/chaos
clock definitions, and that market-hours gating overrides the scheduler's
own freshness view when it refuses."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from scheduler import ManualClock, parse_cadence

from clocks.market_hours import MarketHoursGate
from clocks.three_clocks import (
    ALL_CLOCKS,
    CHAOS_CLOCK,
    EQUITY_CLOCK,
    MACRO_CLOCK,
    build_three_clock_scheduler,
    run_clock_job,
)


# --- (d) each concrete clock job has the cadence/policy the spec calls for --

def test_macro_clock_is_twelve_hour_skip_hold_previous_and_not_market_gated():
    assert MACRO_CLOCK.spec.cadence == "12h"
    assert parse_cadence(MACRO_CLOCK.spec.cadence) == timedelta(hours=12)
    assert MACRO_CLOCK.spec.stale_input_policy == "skip_hold_previous"
    assert MACRO_CLOCK.requires_market_hours is False


def test_equity_clock_is_one_hour_and_market_gated():
    assert EQUITY_CLOCK.spec.cadence == "1h"
    assert parse_cadence(EQUITY_CLOCK.spec.cadence) == timedelta(hours=1)
    assert EQUITY_CLOCK.spec.stale_input_policy == "proceed_marked_stale"
    assert EQUITY_CLOCK.requires_market_hours is True
    assert EQUITY_CLOCK.venue == "NYSE"


def test_chaos_clock_is_one_to_five_minutes_fail_loud_and_market_gated():
    assert CHAOS_CLOCK.spec.cadence == "1-5min"
    # the range form's freshness allowance is the upper bound, per
    # scheduler.parse_cadence's own documented semantics
    assert parse_cadence(CHAOS_CLOCK.spec.cadence) == timedelta(minutes=5)
    assert CHAOS_CLOCK.spec.stale_input_policy == "fail_loud"
    assert CHAOS_CLOCK.requires_market_hours is True
    assert CHAOS_CLOCK.venue == "NYSE"


def test_all_three_clocks_have_distinct_cadence_tiers():
    cadences = {c.spec.cadence for c in ALL_CLOCKS}
    assert cadences == {"12h", "1h", "1-5min"}
    assert len(ALL_CLOCKS) == 3


def test_three_clock_scheduler_builds_one_tier_budget_per_clock():
    clock = ManualClock(datetime(2026, 6, 10, 12, 0))
    scheduler = build_three_clock_scheduler(clock)
    assert set(scheduler.tiers.keys()) == {"12h", "1h", "1-5min"}


# --- market-hours gating overrides scheduler freshness -----------------------

class AlwaysClosedCalendar:
    def session_kind(self, d: date) -> str:
        return "closed"


class AlwaysOpenCalendar:
    def session_kind(self, d: date) -> str:
        return "full"


def test_market_hours_gate_refuses_equity_job_when_market_closed_even_though_inputs_look_fine():
    """Core wiring assertion: even with macro_regime marked fresh a moment
    ago (so the scheduler's own freshness view would happily proceed), a
    closed-market timestamp must still refuse the equity job outright, and
    scheduler.run_job must never even be invoked for it."""
    when = datetime(2026, 12, 25, 11, 0)  # any timestamp; calendar always says closed
    clock = ManualClock(when)
    scheduler = build_three_clock_scheduler(clock)
    scheduler.mark_input_ready("macro_regime", at=when)  # inputs are as fresh as possible

    gate = MarketHoursGate(venue="NYSE", calendar=AlwaysClosedCalendar())
    calls = []
    record = run_clock_job(scheduler, EQUITY_CLOCK, gate, when, lambda: calls.append(1) or {"equity_research": 1})

    assert record.status == "skipped_stale"
    assert "market-hours gate refused" in record.detail
    assert "closed" in record.detail
    assert calls == []  # work_fn never ran
    # and the scheduler itself never recorded a run for this (job, ts) pair
    assert scheduler.health(EQUITY_CLOCK.spec.name, when) == "unknown"


def test_market_hours_gate_allows_equity_job_when_market_open_and_scheduler_runs_it():
    when = datetime(2026, 6, 10, 11, 0)  # a weekday during ordinary hours
    clock = ManualClock(when)
    scheduler = build_three_clock_scheduler(clock)
    scheduler.mark_input_ready("macro_regime", at=when)

    gate = MarketHoursGate(venue="NYSE", calendar=AlwaysOpenCalendar())
    record = run_clock_job(scheduler, EQUITY_CLOCK, gate, when, lambda: {"equity_research": 42})

    assert record.status in ("success", "stale_but_ran")
    assert record.outputs_produced == {"equity_research": 42}


def test_macro_clock_runs_regardless_of_market_hours_gate_state():
    when = datetime(2026, 12, 25, 3, 0)  # holiday, 3am — closed by any calendar
    clock = ManualClock(when)
    scheduler = build_three_clock_scheduler(clock)
    gate = MarketHoursGate(venue="NYSE", calendar=AlwaysClosedCalendar())

    record = run_clock_job(scheduler, MACRO_CLOCK, gate, when, lambda: {"macro_regime": "risk_off"})
    assert record.status == "success"
    assert record.outputs_produced == {"macro_regime": "risk_off"}
