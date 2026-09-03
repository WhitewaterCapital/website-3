"""DATA-02: universe and trading-calendar service.

Two deliberate design choices straight from the spec:

1. **No live index-membership feed.** A real one (S&P index files, a paid
   membership vendor) is out of scope for this sandbox anyway (no network).
   Instead, `UniverseBuilder` accepts a synthetic membership table — a
   `pandas.DataFrame` of `(ticker, entry_date, exit_date)` rows, `exit_date`
   being `None`/`NaT` for names still active — as an explicit input. Wiring a
   real feed later means building that same three-column table from the real
   source and handing it to `UniverseBuilder`; nothing else changes.

2. **No runtime calendar computation.** `TradingCalendar` takes a *supplied*
   holiday list rather than computing US market holidays algorithmically at
   runtime (the planning doc explicitly warns against this — an algorithmic
   holiday calculation silently drifts from the exchange's actual calendar
   the moment a rule changes, e.g. an ad hoc market closure). The holiday
   list is just data; refreshing it is a data update, not a code change.

The one test this module exists to make possible is the spec's own named
test — see `tests/test_universe.py::test_survivorship_delisted_name_included_
before_exit_and_excluded_after`: a stock that was a real member of the
universe and later delisted must still appear in `universe_as_of` for a past
as-of date that falls before its exit, and must NOT appear for a date at or
after its exit. Silently dropping a since-delisted name from a historical
universe is exactly how survivorship bias creeps into a backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

import pandas as pd

_MEMBERSHIP_REQUIRED_COLUMNS = {"ticker", "entry_date", "exit_date"}
_LIQUIDITY_REQUIRED_COLUMNS = {"ticker", "date", "dollar_volume"}


@dataclass(frozen=True)
class TradingCalendar:
    """A trading calendar built from a *supplied* holiday list — never
    computed at runtime from a library's notion of "US market holidays".
    `holidays` and weekend days are the only two things that make a date not
    a trading day."""

    holidays: frozenset = field(default_factory=frozenset)
    weekend_days: frozenset = field(default_factory=lambda: frozenset({5, 6}))  # Mon=0 .. Sun=6

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() not in self.weekend_days and d not in self.holidays

    def next_trading_day(self, d: date) -> date:
        cur = d + timedelta(days=1)
        while not self.is_trading_day(cur):
            cur += timedelta(days=1)
        return cur

    def previous_trading_day(self, d: date) -> date:
        cur = d - timedelta(days=1)
        while not self.is_trading_day(cur):
            cur -= timedelta(days=1)
        return cur


class UniverseBuilder:
    """Builds a point-in-time universe from a membership table plus an
    optional liquidity floor.

    membership: DataFrame with columns `ticker`, `entry_date`, `exit_date`
                (python `date` objects; `exit_date` is `None`/`NaT` for a
                name still active). A ticker is a member on date D iff
                `entry_date <= D < exit_date` (or `exit_date` is null) — the
                exit date itself is the first day the name is OUT, matching
                "delisted effective <exit_date>".
    liquidity:  optional DataFrame with columns `ticker`, `date`,
                `dollar_volume`, used only when `liquidity_floor` is set.
                For a given as-of date, the *most recent* liquidity reading
                on or before that date is used (no look-ahead).
    liquidity_floor: minimum `dollar_volume` required to remain in the
                universe; `None` disables the liquidity filter entirely
                (membership alone determines the universe).
    """

    def __init__(
        self,
        membership: pd.DataFrame,
        calendar: Optional[TradingCalendar] = None,
        liquidity: Optional[pd.DataFrame] = None,
        liquidity_floor: Optional[float] = None,
    ) -> None:
        missing = _MEMBERSHIP_REQUIRED_COLUMNS - set(membership.columns)
        if missing:
            raise ValueError(f"membership table missing required column(s): {sorted(missing)}")
        if liquidity is not None:
            missing_liq = _LIQUIDITY_REQUIRED_COLUMNS - set(liquidity.columns)
            if missing_liq:
                raise ValueError(f"liquidity table missing required column(s): {sorted(missing_liq)}")

        self._membership = membership.reset_index(drop=True)
        self._calendar = calendar
        self._liquidity = liquidity.reset_index(drop=True) if liquidity is not None else None
        self._liquidity_floor = liquidity_floor

    def universe_as_of(self, as_of: date) -> list[str]:
        m = self._membership
        entered = m["entry_date"] <= as_of
        not_yet_exited = m["exit_date"].isna() | (m["exit_date"] > as_of)
        members = sorted(set(m.loc[entered & not_yet_exited, "ticker"].tolist()))

        if self._liquidity is not None and self._liquidity_floor is not None:
            members = [t for t in members if self._passes_liquidity_floor(t, as_of)]

        return members

    def _passes_liquidity_floor(self, ticker: str, as_of: date) -> bool:
        liq = self._liquidity
        candidates = liq.loc[(liq["ticker"] == ticker) & (liq["date"] <= as_of)]
        if candidates.empty:
            # No liquidity reading known as of this date yet — fail closed
            # rather than assuming it passes (no look-ahead, no free pass).
            return False
        latest = candidates.sort_values("date").iloc[-1]
        return bool(latest["dollar_volume"] >= self._liquidity_floor)
