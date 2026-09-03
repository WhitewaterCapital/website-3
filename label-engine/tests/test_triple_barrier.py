"""Triple-barrier label tests.

All price paths here are constructed by hand (no randomness) so the outcome
of each test is provable by inspection, not just "the code agrees with
itself":

  - pre-entry prices alternate +1%/-1% returns exactly, so the trailing-vol
    estimate is an exact, hand-checkable number (std of [+.01,-.01,+.01,-.01],
    ddof=1 == sqrt(1/3 * 4 * .01^2) ~= 0.0115470054).
  - post-entry paths are built well clear of the resulting barrier levels
    (~102.29 upper / ~97.67 lower off an ~99.98 entry) so which barrier is
    touched, and when, is unambiguous.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lbl.triple_barrier import TripleBarrierError, triple_barrier_label

# Pre-entry: exact +1%, -1%, +1%, -1% returns off 100.0.
_PRE_ENTRY = [100.0, 101.0, 99.99, 100.98989999999999, 99.98000099999999]
_ENTRY_PRICE = _PRE_ENTRY[-1]  # ~99.980001
_EXPECTED_VOL = 0.011547005383792526
_EXPECTED_UPPER = _ENTRY_PRICE * (1 + 2.0 * _EXPECTED_VOL)  # ~102.28894
_EXPECTED_LOWER = _ENTRY_PRICE * (1 - 2.0 * _EXPECTED_VOL)  # ~97.67106


def _series(post_entry):
    prices = _PRE_ENTRY + post_entry
    idx = pd.date_range("2020-01-01", periods=len(prices), freq="D")
    return pd.Series(prices, index=idx), idx[len(_PRE_ENTRY) - 1]  # (series, entry_time)


def test_upper_barrier_touched_first():
    # 100.5 stays inside both barriers; 103.0 clears the upper (~102.29).
    prices, entry_time = _series([100.5, 103.0, 110.0])
    res = triple_barrier_label(prices, entry_time, upper_mult=2.0, lower_mult=2.0, max_holding=3, vol_lookback=4)
    assert res.barrier == "upper"
    assert res.label == 1
    assert res.touch_time == prices.index[6]  # second post-entry bar
    assert res.trailing_vol == pytest.approx(_EXPECTED_VOL)
    assert res.upper_barrier_price == pytest.approx(_EXPECTED_UPPER)
    assert res.lower_barrier_price == pytest.approx(_EXPECTED_LOWER)
    assert res.realized_return == pytest.approx(103.0 / _ENTRY_PRICE - 1.0)


def test_lower_barrier_touched_first():
    # 99.0 stays inside both barriers; 96.0 clears the lower (~97.67).
    prices, entry_time = _series([99.0, 96.0, 90.0])
    res = triple_barrier_label(prices, entry_time, upper_mult=2.0, lower_mult=2.0, max_holding=3, vol_lookback=4)
    assert res.barrier == "lower"
    assert res.label == -1
    assert res.touch_time == prices.index[6]
    assert res.trailing_vol == pytest.approx(_EXPECTED_VOL)
    assert res.realized_return == pytest.approx(96.0 / _ENTRY_PRICE - 1.0)


def test_time_barrier_reached_without_touching_either_side():
    # All three post-entry prices stay strictly inside (97.67, 102.29).
    prices, entry_time = _series([100.0, 101.0, 99.0])
    res = triple_barrier_label(prices, entry_time, upper_mult=2.0, lower_mult=2.0, max_holding=3, vol_lookback=4)
    assert res.barrier == "time"
    assert res.label == 0
    assert res.touch_time == prices.index[-1]  # entry_pos + max_holding
    assert res.realized_return == pytest.approx(99.0 / _ENTRY_PRICE - 1.0)


def test_barrier_levels_are_point_in_time_safe():
    """Two price paths, IDENTICAL up to and including entry, that diverge
    afterwards (one goes on to hit the upper barrier, the other the lower).
    If barrier sizing ever read post-entry data, these two runs would
    disagree on entry_price/trailing_vol/upper_barrier_price/lower_barrier_price.
    They must not."""
    prices_up, entry_time_up = _series([100.5, 103.0, 110.0])
    prices_down, entry_time_down = _series([99.0, 96.0, 90.0])
    assert entry_time_up == entry_time_down  # same entry instant on both paths

    res_up = triple_barrier_label(prices_up, entry_time_up, upper_mult=2.0, lower_mult=2.0, max_holding=3, vol_lookback=4)
    res_down = triple_barrier_label(prices_down, entry_time_down, upper_mult=2.0, lower_mult=2.0, max_holding=3, vol_lookback=4)

    # The barrier SIZING must be identical (computed only from shared, pre-entry data)...
    assert res_up.entry_price == pytest.approx(res_down.entry_price)
    assert res_up.trailing_vol == pytest.approx(res_down.trailing_vol)
    assert res_up.upper_barrier_price == pytest.approx(res_down.upper_barrier_price)
    assert res_up.lower_barrier_price == pytest.approx(res_down.lower_barrier_price)
    # ...even though the OUTCOME (which future actually happened) differs.
    assert res_up.barrier == "upper"
    assert res_down.barrier == "lower"


def test_rejects_unknown_entry_time():
    prices, _ = _series([100.0, 101.0, 99.0])
    with pytest.raises(TripleBarrierError):
        triple_barrier_label(prices, pd.Timestamp("2099-01-01"), upper_mult=2.0, lower_mult=2.0, max_holding=3)


def test_rejects_non_positive_max_holding():
    prices, entry_time = _series([100.0, 101.0, 99.0])
    with pytest.raises(TripleBarrierError):
        triple_barrier_label(prices, entry_time, upper_mult=2.0, lower_mult=2.0, max_holding=0)


def test_rejects_negative_barrier_multiples():
    prices, entry_time = _series([100.0, 101.0, 99.0])
    with pytest.raises(TripleBarrierError):
        triple_barrier_label(prices, entry_time, upper_mult=-1.0, lower_mult=2.0, max_holding=3)


def test_rejects_entry_at_the_last_available_bar():
    prices, _ = _series([])
    last_time = prices.index[-1]
    with pytest.raises(TripleBarrierError):
        triple_barrier_label(prices, last_time, upper_mult=2.0, lower_mult=2.0, max_holding=3)
