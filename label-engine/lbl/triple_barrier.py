"""Triple-barrier labels for short-horizon models (López de Prado, FEAT-02).

From an entry time, three barriers are set around the entry price:

  * an UPPER barrier at entry_price * (1 + upper_mult * sigma)
  * a LOWER barrier at entry_price * (1 - lower_mult * sigma)
  * a TIME barrier at entry_time + max_holding bars

where `sigma` is a trailing volatility estimate (stdev of returns) computed
ONLY from data at or before the entry time — see `_trailing_volatility`
below. The price path is walked forward bar by bar from the entry; whichever
barrier is touched first determines the label. This function only ever looks
at prices strictly after the entry to decide the outcome and at prices at-or
-before the entry to size the barriers, so it cannot leak the future into the
barrier levels themselves (see tests/test_triple_barrier.py::
test_barrier_levels_are_point_in_time_safe, which mutates the price path
strictly after entry and asserts the barrier levels do not move).

Label convention (there is more than one reasonable choice in the
literature; this is the one this module commits to and documents):

  * `label = +1` if the UPPER barrier is touched first.
  * `label = -1` if the LOWER barrier is touched first.
  * `label = 0`  if neither is touched before the TIME barrier (a "timeout").

This is the classic López de Prado directional triple-barrier label (as
opposed to encoding the realized return as the label). The realized return
from entry to the actual touch is also returned on every record
(`realized_return`), so a caller who wants a continuous target instead of
the discrete +1/-1/0 has it without recomputing anything — but `label` above
is what this module treats as "the" triple-barrier label, e.g. for the
meta-labeling convention in `meta_label.py`.

Tie-break convention for a single bar that would trip both barriers at once
(only possible with a close-only series when a bar gaps past both levels,
e.g. a sharp gap): whichever barrier the bar's close is *further* past (in
barrier-relative terms) is the one recorded as touched; an exact tie
resolves to the upper barrier. This is a documented, deterministic
convention — not a claim that OHLC intrabar path is known — and only matters
for gap bars; the tests exercise upper-touch, lower-touch, and timeout paths
that never hit this branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class TripleBarrierError(ValueError):
    """Raised for invalid triple-barrier inputs (e.g. entry time not in the
    price index, or a horizon that runs off the end of the available data
    with no bars remaining to walk)."""


@dataclass(frozen=True)
class TripleBarrierLabel:
    """One triple-barrier observation.

    Attributes:
        entry_time: when the position would have been opened.
        touch_time: the timestamp of the bar where a barrier was actually
            touched (or the time-barrier bar itself, on a timeout). This IS
            the label's `knowable_from` — the label cannot be known before
            this bar prints.
        barrier: which barrier fired first — "upper", "lower", or "time".
        label: +1 / -1 / 0 per the module-level convention above.
        realized_return: price[touch_time] / price[entry_time] - 1.
        entry_price: price at entry_time.
        upper_barrier_price / lower_barrier_price: the absolute price levels
            used, sized from `trailing_vol` (below).
        trailing_vol: the point-in-time volatility estimate the barriers were
            scaled by (stdev of returns using only data at-or-before entry).
    """

    entry_time: Any
    touch_time: Any
    barrier: str
    label: int
    realized_return: float
    entry_price: float
    upper_barrier_price: float
    lower_barrier_price: float
    trailing_vol: float

    @property
    def knowable_from(self) -> Any:
        return self.touch_time


def _trailing_volatility(prices: pd.Series, entry_pos: int, vol_lookback: int) -> float:
    """Trailing stdev of simple returns, using ONLY prices at or before
    `entry_pos` (positional index into `prices`). This is what makes barrier
    sizing point-in-time safe: nothing after the entry bar is ever read here.
    """
    window_start = max(0, entry_pos - vol_lookback)
    window = prices.iloc[window_start : entry_pos + 1]
    rets = window.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    return float(rets.std(ddof=1))


def triple_barrier_label(
    prices: pd.Series,
    entry_time: Any,
    upper_mult: float,
    lower_mult: float,
    max_holding: int,
    vol_lookback: int = 20,
) -> TripleBarrierLabel:
    """Compute one triple-barrier label for a position entered at `entry_time`.

    Args:
        prices: close-price series indexed by time, sorted ascending.
        entry_time: a timestamp present in `prices.index`.
        upper_mult: upper barrier distance, in multiples of trailing vol.
        lower_mult: lower barrier distance, in multiples of trailing vol.
            (Both are magnitudes; the lower barrier is placed BELOW entry.)
        max_holding: time barrier, in bars forward from entry (>= 1).
        vol_lookback: number of trailing bars (ending at entry, inclusive)
            used to estimate volatility. Must be point-in-time: only prices
            at or before `entry_time` are read.

    Returns:
        A TripleBarrierLabel. Raises TripleBarrierError if `entry_time` is
        not in the index, if `max_holding < 1`, or if there is no bar at all
        after entry to walk (entry is the last available bar).
    """
    if max_holding < 1:
        raise TripleBarrierError(f"max_holding must be >= 1 bar (got {max_holding})")
    if upper_mult < 0 or lower_mult < 0:
        raise TripleBarrierError("upper_mult and lower_mult must be non-negative")
    try:
        entry_pos = prices.index.get_loc(entry_time)
    except KeyError as e:
        raise TripleBarrierError(f"entry_time {entry_time!r} not found in prices.index") from e
    if isinstance(entry_pos, slice) or not np.isscalar(entry_pos):
        raise TripleBarrierError(f"entry_time {entry_time!r} is not a unique index label")
    if entry_pos >= len(prices) - 1:
        raise TripleBarrierError("entry_time is the last available bar; nothing to walk forward")

    entry_price = float(prices.iloc[entry_pos])
    vol = _trailing_volatility(prices, entry_pos, vol_lookback)
    upper_price = entry_price * (1.0 + upper_mult * vol)
    lower_price = entry_price * (1.0 - lower_mult * vol)

    time_barrier_pos = min(entry_pos + max_holding, len(prices) - 1)

    for pos in range(entry_pos + 1, time_barrier_pos + 1):
        p = float(prices.iloc[pos])
        hit_upper = p >= upper_price
        hit_lower = p <= lower_price
        if hit_upper and hit_lower:
            # Gap bar past both levels (only possible if upper_price <=
            # lower_price is false but the bar leapt over both, or barriers
            # collapsed onto entry_price at zero vol). Deterministic
            # tie-break: whichever level the close overshot by more wins;
            # exact tie -> upper. See module docstring.
            over_upper = p - upper_price
            over_lower = lower_price - p
            barrier = "upper" if over_upper >= over_lower else "lower"
        elif hit_upper:
            barrier = "upper"
        elif hit_lower:
            barrier = "lower"
        else:
            continue
        touch_time = prices.index[pos]
        return TripleBarrierLabel(
            entry_time=entry_time,
            touch_time=touch_time,
            barrier=barrier,
            label=1 if barrier == "upper" else -1,
            realized_return=p / entry_price - 1.0,
            entry_price=entry_price,
            upper_barrier_price=upper_price,
            lower_barrier_price=lower_price,
            trailing_vol=vol,
        )

    # Neither barrier touched by the time barrier: timeout.
    touch_time = prices.index[time_barrier_pos]
    p = float(prices.iloc[time_barrier_pos])
    return TripleBarrierLabel(
        entry_time=entry_time,
        touch_time=touch_time,
        barrier="time",
        label=0,
        realized_return=p / entry_price - 1.0,
        entry_price=entry_price,
        upper_barrier_price=upper_price,
        lower_barrier_price=lower_price,
        trailing_vol=vol,
    )
