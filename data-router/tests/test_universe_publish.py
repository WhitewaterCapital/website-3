"""Tests for the DATA-02 additions in ``router.universe_publish``: the
concrete sample universe, the venue calendar's half-day support, and the
dated weekly-publish file format.

The core survivorship acceptance test already lives in ``test_universe.py``
against ``router.universe.UniverseBuilder`` directly (that module was
already in the repo with its own green suite before this pass — see
``router/universe_publish/__init__.py`` for why this pass didn't touch it).
This file re-proves the same survivorship property end-to-end against the
concrete sample dataset and the published-file format this pass adds, so
the fixture DATA-02's acceptance criterion describes ("a fixture asks for
the universe at a past date that includes a since delisted name and fails
if that name is missing") is exercised for the actual sample universe, not
just an inline ad hoc fixture.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from router.universe import UniverseBuilder
from router.universe_publish.calendar_data import SessionType, nyse_calendar
from router.universe_publish.publish import (
    build_published_universe,
    load_published_universe,
    publish_universe_snapshot,
)
from router.universe_publish.sample_membership import (
    SAMPLE_LIQUIDITY_FLOOR,
    UNIVERSE_NAME,
    VENUE,
    sample_liquidity,
    sample_membership,
)


# --- survivorship, on the concrete sample dataset ---------------------------


def test_survivorship_sample_delisted_name_included_before_its_exit_date():
    membership = sample_membership()
    builder = UniverseBuilder(membership)

    # SYN-DELIST-01 exited 2023-08-15. A query for a PAST date before that
    # exit must still include it — it was a real, tradeable member then.
    before_exit = builder.universe_as_of(date(2022, 1, 1))
    assert "SYN-DELIST-01" in before_exit, (
        "a since-delisted sample name must appear in the universe as of a "
        "past date before its exit — dropping it here is exactly the "
        "survivorship bias DATA-02 exists to prevent"
    )


def test_survivorship_sample_delisted_name_excluded_on_and_after_exit_date():
    membership = sample_membership()
    builder = UniverseBuilder(membership)

    on_exit = builder.universe_as_of(date(2023, 8, 15))
    after_exit = builder.universe_as_of(date(2024, 1, 1))
    assert "SYN-DELIST-01" not in on_exit
    assert "SYN-DELIST-01" not in after_exit


def test_all_three_sample_delisted_names_appear_before_their_own_exit():
    membership = sample_membership()
    builder = UniverseBuilder(membership)
    # A date safely before all three delisted names' exits.
    members = builder.universe_as_of(date(2021, 1, 1))
    for ticker in ("SYN-DELIST-01", "SYN-DELIST-02", "SYN-DELIST-03"):
        assert ticker in members


def test_recent_entrant_excluded_before_its_entry_date():
    membership = sample_membership()
    builder = UniverseBuilder(membership)
    early = builder.universe_as_of(date(2024, 1, 1))
    assert "SYN-IPO-01" not in early  # enters 2025-04-07
    assert "SYN-IPO-02" not in early  # enters 2026-02-02
    late = builder.universe_as_of(date(2026, 6, 1))
    assert "SYN-IPO-01" in late
    assert "SYN-IPO-02" in late


def test_liquidity_floor_drops_illiquid_sample_name():
    membership = sample_membership()
    liquidity = sample_liquidity()
    builder = UniverseBuilder(
        membership, liquidity=liquidity, liquidity_floor=SAMPLE_LIQUIDITY_FLOOR
    )
    members = builder.universe_as_of(date(2026, 9, 3))
    assert "SYN-ILLIQUID-01" not in members
    assert "SYN-CORE-01" in members


# --- venue calendar half-days ------------------------------------------------


def test_calendar_recognizes_known_holiday_as_non_trading():
    cal = nyse_calendar()
    assert cal.session_type(date(2026, 1, 1)) == SessionType.CLOSED       # New Year's Day
    assert cal.session_type(date(2026, 12, 25)) == SessionType.CLOSED     # Christmas
    assert cal.is_trading_day(date(2026, 1, 1)) is False


def test_calendar_recognizes_known_trading_day_as_full_day():
    cal = nyse_calendar()
    # An ordinary Tuesday, no holiday, no half day.
    assert cal.session_type(date(2026, 3, 3)) == SessionType.FULL_DAY
    assert cal.is_trading_day(date(2026, 3, 3)) is True
    assert cal.is_half_day(date(2026, 3, 3)) is False


def test_calendar_recognizes_known_half_day_distinct_from_full_and_closed():
    cal = nyse_calendar()
    # Day after Thanksgiving 2026 — a scheduled NYSE early close.
    half_day = date(2026, 11, 27)
    assert cal.session_type(half_day) == SessionType.HALF_DAY
    assert cal.is_trading_day(half_day) is True   # venue is open, just shorter
    assert cal.is_half_day(half_day) is True


def test_calendar_weekend_is_closed_even_though_not_in_holiday_table():
    cal = nyse_calendar()
    assert cal.is_trading_day(date(2026, 9, 5)) is False  # a Saturday


# --- published-file round trip -----------------------------------------------


def test_published_universe_states_as_of_date_and_sample_size():
    membership = sample_membership()
    pu = build_published_universe(
        membership,
        date(2026, 9, 3),
        universe_name=UNIVERSE_NAME,
        venue=VENUE,
        note="SYNTHETIC sample universe — see sample_membership.py",
    )
    assert pu.as_of_date == date(2026, 9, 3)
    assert pu.sample_size == len(pu.members)
    assert pu.sample_size > 0
    assert pu.venue == VENUE
    assert pu.universe_name == UNIVERSE_NAME


def test_published_json_round_trips_exactly():
    membership = sample_membership()
    as_of = date(2022, 1, 1)  # before all three delistings' exits

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "universe" / f"{VENUE}-{as_of.isoformat()}.json"
        publish_universe_snapshot(
            membership,
            as_of,
            out_path,
            universe_name=UNIVERSE_NAME,
            venue=VENUE,
            note="SYNTHETIC sample universe — test fixture, not production data",
        )

        assert out_path.exists()
        loaded = load_published_universe(out_path)

    # What building it fresh (no file round trip) would produce, for comparison.
    fresh = build_published_universe(
        membership, as_of, universe_name=UNIVERSE_NAME, venue=VENUE
    )

    assert loaded.as_of_date == fresh.as_of_date == as_of
    assert loaded.sample_size == fresh.sample_size
    assert sorted(m.ticker for m in loaded.members) == sorted(m.ticker for m in fresh.members)
    for loaded_m, fresh_m in zip(
        sorted(loaded.members, key=lambda m: m.ticker),
        sorted(fresh.members, key=lambda m: m.ticker),
    ):
        assert loaded_m.ticker == fresh_m.ticker
        assert loaded_m.entry_date == fresh_m.entry_date
        assert loaded_m.exit_date == fresh_m.exit_date
        assert loaded_m.inclusion_reason == fresh_m.inclusion_reason

    # The literal DATA-02 survivorship check, replayed against the published
    # (write-then-read-back) file rather than the live builder: a since
    # delisted name asked about at a past as-of date before its exit must be
    # present in the artifact models actually read.
    assert "SYN-DELIST-01" in {m.ticker for m in loaded.members}


def test_published_json_excludes_delisted_name_when_as_of_is_after_exit():
    membership = sample_membership()
    as_of = date(2026, 9, 3)  # after all three sample delistings

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / f"{VENUE}-{as_of.isoformat()}.json"
        publish_universe_snapshot(
            membership, as_of, out_path, universe_name=UNIVERSE_NAME, venue=VENUE
        )
        loaded = load_published_universe(out_path)

    tickers = {m.ticker for m in loaded.members}
    assert "SYN-DELIST-01" not in tickers
    assert "SYN-DELIST-02" not in tickers
    assert "SYN-DELIST-03" not in tickers
    assert "SYN-CORE-01" in tickers
