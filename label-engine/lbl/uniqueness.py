"""Sample uniqueness weights (López de Prado, FEAT-02).

A label's window is [start, end] — for a forward-return label that's [t,
t+horizon]; for a triple-barrier label that's [entry_time, touch_time].
Overlapping windows mean the underlying observations are not independent: two
labels whose windows both cover the same stretch of the market are, in part,
scored on the very same price move. Training on them unweighted double(or
N-)counts that one move as if it were several independent samples.

Average uniqueness (the standard concept from purged/embargo-style
overlapping-label research) fixes this directly rather than approximately:
walk the common time grid bar by bar; at each bar, count how many labels'
windows are "live" (concurrency); each live label gets a fractional credit of
1/concurrency for that bar. A label's uniqueness weight is the average of its
own per-bar credit over its own window.

By construction:
  - A label whose window never overlaps any other label's window gets
    weight 1.0 at every bar in its window, so its average is 1.0.
  - A label whose window is completely covered by other labels' windows gets
    a fractional credit strictly less than 1.0 at every bar, so its average
    is strictly less than 1.0.
  - Two labels with IDENTICAL windows split credit exactly in half at every
    bar (concurrency == 2 throughout both windows), so both get exactly 0.5.

See tests/test_uniqueness.py for the hand-computed numeric checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd


class UniquenessError(ValueError):
    """Raised for malformed windows (e.g. a start/end not found on the
    supplied common index, or an end before its start)."""


@dataclass(frozen=True)
class LabelWindow:
    """One label's [start, end] window, both inclusive, both timestamps that
    must appear in the common `index` passed to `average_uniqueness_weights`.
    """

    start: Any
    end: Any


def average_uniqueness_weights(windows: Sequence[LabelWindow], index: pd.Index) -> np.ndarray:
    """Compute the average-uniqueness weight for each window in `windows`.

    Args:
        windows: the label windows to weight, in the order weights should be
            returned in.
        index: the common time grid every window's start/end is drawn from
            (e.g. the same price series index the labels were built over).
            This must be the actual bar-by-bar clock — not just the sorted
            set of window endpoints — because concurrency has to be counted
            on every bar a window spans, not only at its endpoints.

    Returns:
        A 1-D numpy array of weights, same length and order as `windows`.
        Each weight is in (0, 1]: 1.0 for a window with no concurrent
        overlap anywhere in its span, strictly less than 1.0 wherever it
        overlaps any other window.
    """
    if len(windows) == 0:
        return np.array([], dtype=float)

    n_bars = len(index)
    positions = []
    for w in windows:
        try:
            s = index.get_loc(w.start)
            e = index.get_loc(w.end)
        except KeyError as exc:
            raise UniquenessError(f"window {w!r} has a start/end not present in the supplied index") from exc
        if isinstance(s, slice) or isinstance(e, slice) or not np.isscalar(s) or not np.isscalar(e):
            raise UniquenessError(f"window {w!r} start/end is not a unique position on the index")
        if e < s:
            raise UniquenessError(f"window {w!r} has end before start")
        positions.append((int(s), int(e)))

    concurrency = np.zeros(n_bars, dtype=float)
    for s, e in positions:
        concurrency[s : e + 1] += 1.0

    weights = np.empty(len(windows), dtype=float)
    for i, (s, e) in enumerate(positions):
        c = concurrency[s : e + 1]
        weights[i] = float(np.mean(1.0 / c))
    return weights


def average_uniqueness_from_frame(
    windows: pd.DataFrame,
    index: pd.Index,
    start_col: str = "start",
    end_col: str = "end",
) -> pd.Series:
    """Convenience wrapper: same computation as `average_uniqueness_weights`,
    but takes a DataFrame with start/end columns and returns a Series of
    weights aligned to `windows.index` (rather than a bare positional array).
    """
    ws = [LabelWindow(start=row[start_col], end=row[end_col]) for _, row in windows.iterrows()]
    weights = average_uniqueness_weights(ws, index)
    return pd.Series(weights, index=windows.index, name="uniqueness_weight")
