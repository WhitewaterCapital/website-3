"""DATA-02: universe/calendar service.

The doc's own named test lives here: `universe_as_of` for a PAST date must
still include a since-delisted name that was a real member on that date, and
must exclude it once its exit date has passed. Silently dropping delisted
names from a historical universe is exactly how survivorship bias creeps
into a backtest.
"""

from datetime import date

import pandas as pd
import pytest

from router.universe import TradingCalendar, UniverseBuilder


def _membership() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # A name that IPO'd, traded for years, and was delisted (acquired).
            {"ticker": "DELIST1", "entry_date": date(2015, 1, 1), "exit_date": date(2019, 6, 1)},
            # A name still active today.
            {"ticker": "SURVIVOR", "entry_date": date(2010, 1, 1), "exit_date": None},
            # A name that hasn't entered the universe yet as of some early dates.
            {"ticker": "LATECOMER", "entry_date": date(2022, 1, 1), "exit_date": None},
        ]
    )


def test_survivorship_delisted_name_included_before_exit_and_excluded_after_exit_date():
    builder = UniverseBuilder(_membership())

    # A date BEFORE the delisting: DELIST1 was a real, tradeable member and
    # MUST appear, exactly as the spec's own named survivorship test demands.
    before_exit = builder.universe_as_of(date(2018, 1, 1))
    assert "DELIST1" in before_exit, "delisted name must be included for a past as-of date before its exit"

    # On/after the exit date: DELIST1 must be gone.
    on_exit = builder.universe_as_of(date(2019, 6, 1))
    assert "DELIST1" not in on_exit

    after_exit = builder.universe_as_of(date(2020, 1, 1))
    assert "DELIST1" not in after_exit


def test_universe_excludes_names_before_their_entry_date():
    builder = UniverseBuilder(_membership())
    early = builder.universe_as_of(date(2011, 1, 1))
    assert "LATECOMER" not in early
    assert "SURVIVOR" in early


def test_universe_includes_active_names_with_null_exit_date():
    builder = UniverseBuilder(_membership())
    today_ish = builder.universe_as_of(date(2025, 1, 1))
    assert "SURVIVOR" in today_ish
    assert "LATECOMER" in today_ish
    assert "DELIST1" not in today_ish


def test_universe_missing_required_column_raises():
    bad = pd.DataFrame([{"ticker": "X", "entry_date": date(2020, 1, 1)}])  # no exit_date
    with pytest.raises(ValueError):
        UniverseBuilder(bad)


def test_liquidity_floor_excludes_illiquid_names():
    membership = _membership()
    liquidity = pd.DataFrame(
        [
            {"ticker": "SURVIVOR", "date": date(2018, 1, 1), "dollar_volume": 50_000_000.0},
            {"ticker": "DELIST1", "date": date(2018, 1, 1), "dollar_volume": 100.0},  # too illiquid
        ]
    )
    builder = UniverseBuilder(membership, liquidity=liquidity, liquidity_floor=1_000_000.0)
    members = builder.universe_as_of(date(2018, 1, 1))
    assert "SURVIVOR" in members
    assert "DELIST1" not in members  # membership says yes, liquidity says no


def test_liquidity_floor_uses_most_recent_reading_without_look_ahead():
    membership = pd.DataFrame([{"ticker": "X", "entry_date": date(2020, 1, 1), "exit_date": None}])
    liquidity = pd.DataFrame(
        [
            {"ticker": "X", "date": date(2020, 1, 1), "dollar_volume": 5_000_000.0},
            # A future, better reading must NOT be used for an earlier as-of date.
            {"ticker": "X", "date": date(2020, 6, 1), "dollar_volume": 5.0},
        ]
    )
    builder = UniverseBuilder(membership, liquidity=liquidity, liquidity_floor=1_000_000.0)
    assert "X" in builder.universe_as_of(date(2020, 2, 1))   # only the Jan reading is knowable
    assert "X" not in builder.universe_as_of(date(2020, 7, 1))  # June's low reading now applies


def test_liquidity_floor_fails_closed_with_no_reading_yet():
    membership = pd.DataFrame([{"ticker": "X", "entry_date": date(2020, 1, 1), "exit_date": None}])
    liquidity = pd.DataFrame([{"ticker": "X", "date": date(2021, 1, 1), "dollar_volume": 5_000_000.0}])
    builder = UniverseBuilder(membership, liquidity=liquidity, liquidity_floor=1_000_000.0)
    # As-of a date before any liquidity reading exists: fail closed, not a free pass.
    assert "X" not in builder.universe_as_of(date(2020, 6, 1))


# --- TradingCalendar --------------------------------------------------------


def test_trading_calendar_uses_supplied_holiday_list_not_computed():
    holidays = frozenset({date(2024, 1, 1), date(2024, 7, 4)})
    cal = TradingCalendar(holidays=holidays)
    assert cal.is_trading_day(date(2024, 1, 1)) is False  # New Year's, supplied
    assert cal.is_trading_day(date(2024, 1, 2)) is True
    assert cal.is_trading_day(date(2024, 1, 6)) is False  # Saturday


def test_trading_calendar_next_and_previous_trading_day_skip_weekends_and_holidays():
    holidays = frozenset({date(2024, 1, 1)})
    cal = TradingCalendar(holidays=holidays)
    # Dec 29, 2023 is a Friday; Dec 30/31 are weekend; Jan 1 is a holiday.
    assert cal.next_trading_day(date(2023, 12, 29)) == date(2024, 1, 2)
    assert cal.previous_trading_day(date(2024, 1, 2)) == date(2023, 12, 29)


def test_trading_calendar_empty_holiday_list_still_skips_weekends():
    cal = TradingCalendar()
    assert cal.is_trading_day(date(2024, 1, 6)) is False  # Saturday
    assert cal.is_trading_day(date(2024, 1, 8)) is True   # Monday
