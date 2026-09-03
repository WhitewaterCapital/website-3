"""Tests for clocks/derived_value_guard.py — the IMP-07 acceptance test:

'a monthly CPI series shows the same source observed date across 60
consecutive hourly refreshes while its derived z score only updates when
a genuinely new input arrives.'
"""

from __future__ import annotations

from datetime import date

import pytest

from clocks.derived_value_guard import SourceAwareRefresh, SourceObservation, zscore


def test_zscore_basic():
    assert zscore(10.0, [10.0, 10.0, 10.0]) == 0.0
    z = zscore(12.0, [10.0, 10.0, 10.0, 10.0])
    assert z == 0.0  # zero-variance window: defined as 0.0, not a ZeroDivisionError

    z2 = zscore(6.0, [2.0, 4.0, 6.0, 8.0])  # mean=5, population std=sqrt(5)
    assert z2 == pytest.approx((6.0 - 5.0) / (5.0 ** 0.5))


def test_zscore_matches_hand_computed_value():
    window = [1.0, 2.0, 3.0, 4.0, 5.0]  # mean=3, population std=sqrt(2)
    z = zscore(5.0, window)
    assert z == pytest.approx((5.0 - 3.0) / (2.0 ** 0.5))


def test_refresh_requires_nonempty_window():
    guard = SourceAwareRefresh("cpi", initial=SourceObservation(date(2026, 1, 13), 3.1))
    with pytest.raises(ValueError):
        guard.refresh(SourceObservation(date(2026, 1, 13), 3.1), context_window=[])


# --- the named acceptance test: 60 hourly refreshes, one real vintage change --

CPI_JAN_DATE = date(2026, 1, 13)   # source observed/release date for the January print
CPI_FEB_DATE = date(2026, 2, 11)   # source observed/release date for the February print (the "new" vintage)
CPI_JAN_VALUE = 3.1
CPI_FEB_VALUE = 3.3


def test_observed_date_holds_for_40_calls_jumps_once_at_call_41_then_holds_again():
    guard = SourceAwareRefresh("cpi_yoy", initial=SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE))
    base_window = [2.9, 3.0, 3.0, 3.1, 3.2]

    # Calls 1-40: the upstream is refetched every hour but keeps handing back
    # the SAME January vintage (as any real hourly poll of a monthly series
    # would, 39 times out of 40 in a typical month).
    for i in range(40):
        result = guard.refresh(
            SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE),
            context_window=base_window,
        )
        assert result.stored.observed_date == CPI_JAN_DATE
        assert result.observed_date_advanced is False

    assert len(set(guard.observed_date_history[:40])) == 1
    assert guard.observed_date_history[0] == CPI_JAN_DATE

    # Call 41: a genuinely new vintage arrives.
    result_41 = guard.refresh(
        SourceObservation(CPI_FEB_DATE, CPI_FEB_VALUE),
        context_window=base_window,
    )
    assert result_41.stored.observed_date == CPI_FEB_DATE
    assert result_41.observed_date_advanced is True

    # Calls 42-60: back to steady state on the new (February) vintage.
    for i in range(19):
        result = guard.refresh(
            SourceObservation(CPI_FEB_DATE, CPI_FEB_VALUE),
            context_window=base_window,
        )
        assert result.stored.observed_date == CPI_FEB_DATE
        assert result.observed_date_advanced is False

    assert len(guard.observed_date_history) == 60
    assert guard.observed_date_history[:40] == [CPI_JAN_DATE] * 40
    assert guard.observed_date_history[40] == CPI_FEB_DATE          # the jump, exactly at call 41 (index 40)
    assert guard.observed_date_history[41:] == [CPI_FEB_DATE] * 19
    # exactly one jump across the whole 60-call sequence
    transitions = sum(
        1 for a, b in zip(guard.observed_date_history, guard.observed_date_history[1:]) if a != b
    )
    assert transitions == 1


def test_derived_zscore_recomputes_every_call_even_while_observed_date_is_flat():
    """Proves the other half of the crux: even though the source observed
    date is pinned across all 40 of these calls, the derived z-score is
    NOT frozen — it moves whenever the rolling context window it's scored
    against moves, because a shifted denominator changes the answer even
    when the CPI print itself hasn't changed."""
    guard = SourceAwareRefresh("cpi_yoy", initial=SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE))

    # Feed slightly different rolling-window context at a few of the 40 calls
    # (as would happen in reality: the window is trailing context data, e.g.
    # other months' values or a broader reference series, which keeps
    # arriving/revising even while CPI itself is between prints).
    windows = []
    for i in range(40):
        window = [2.9 + 0.01 * i, 3.0, 3.0, 3.1, 3.2 - 0.01 * i]
        windows.append(window)
        guard.refresh(SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE), context_window=window)

    # The observed date never moved...
    assert len(set(guard.observed_date_history)) == 1
    # ...but the derived z-score took more than one distinct value across
    # those same 40 calls.
    assert len(set(guard.derived_history)) > 1

    # And each derived value is exactly what independently recomputing
    # zscore(value, that call's window) would give — i.e. it really is
    # recomputed fresh every call, not cached from call 1.
    for i in range(40):
        expected = zscore(CPI_JAN_VALUE, windows[i])
        assert guard.derived_history[i] == pytest.approx(expected)


def test_stale_dated_or_out_of_order_fetch_never_regresses_the_stored_observation():
    guard = SourceAwareRefresh("cpi_yoy", initial=SourceObservation(CPI_FEB_DATE, CPI_FEB_VALUE))
    older = SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE)
    result = guard.refresh(older, context_window=[3.0, 3.0, 3.0])
    assert result.stored.observed_date == CPI_FEB_DATE  # unchanged, not regressed to the older date
    assert result.stored.value == CPI_FEB_VALUE
    assert result.observed_date_advanced is False


def test_same_dated_revision_does_not_restate_the_stored_value_or_date():
    guard = SourceAwareRefresh("cpi_yoy", initial=SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE))
    revised_same_date = SourceObservation(CPI_JAN_DATE, CPI_JAN_VALUE + 0.2)  # vendor noise, same vintage date
    result = guard.refresh(revised_same_date, context_window=[3.0, 3.0, 3.0])
    assert result.stored.observed_date == CPI_JAN_DATE
    assert result.stored.value == CPI_JAN_VALUE  # not restated to the revised value
    assert result.observed_date_advanced is False
