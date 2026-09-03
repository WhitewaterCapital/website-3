"""Sample uniqueness weight tests, with hand-computed expected values.

Concurrency and averaging are done by hand in each test's docstring so the
expected numbers are checkable independent of the implementation.
"""

from __future__ import annotations

import pandas as pd
import pytest

from lbl.uniqueness import LabelWindow, UniquenessError, average_uniqueness_from_frame, average_uniqueness_weights


def _index(n=6):
    return pd.date_range("2020-01-01", periods=n, freq="D")


def test_non_overlapping_windows_get_weight_one():
    idx = _index(6)
    # A: bars 0-1, B: bars 2-3, C: bars 4-5 — no bar is shared by two windows.
    windows = [
        LabelWindow(idx[0], idx[1]),
        LabelWindow(idx[2], idx[3]),
        LabelWindow(idx[4], idx[5]),
    ]
    weights = average_uniqueness_weights(windows, idx)
    assert weights == pytest.approx([1.0, 1.0, 1.0])


def test_fully_coincident_windows_split_credit_in_half():
    """A and B occupy the EXACT same bars (0-2). At every one of those bars
    concurrency == 2, so each gets 1/2 credit at every bar in its window ->
    average uniqueness == 0.5 for both, hand-computed exactly."""
    idx = _index(5)
    windows = [
        LabelWindow(idx[0], idx[2]),
        LabelWindow(idx[0], idx[2]),
        LabelWindow(idx[3], idx[4]),  # C: non-overlapping control
    ]
    weights = average_uniqueness_weights(windows, idx)
    assert weights[0] == pytest.approx(0.5)
    assert weights[1] == pytest.approx(0.5)
    assert weights[2] == pytest.approx(1.0)  # non-overlapping control stays at 1.0


def test_partial_overlap_hand_computed():
    """D spans bars 0-3, E spans bars 2-4. Concurrency by bar:
        bar0=1, bar1=1, bar2=2, bar3=2, bar4=1
    D's own bars are 0-3 -> credits [1, 1, 1/2, 1/2] -> mean = 0.75
    E's own bars are 2-4 -> credits [1/2, 1/2, 1]   -> mean = 2/3
    """
    idx = _index(5)
    windows = [LabelWindow(idx[0], idx[3]), LabelWindow(idx[2], idx[4])]
    weights = average_uniqueness_weights(windows, idx)
    assert weights[0] == pytest.approx(0.75)
    assert weights[1] == pytest.approx(2.0 / 3.0)


def test_heavily_overlapping_windows_are_strictly_less_than_one():
    idx = _index(4)
    # Four windows all spanning the entire index -> concurrency == 4 throughout.
    windows = [LabelWindow(idx[0], idx[3]) for _ in range(4)]
    weights = average_uniqueness_weights(windows, idx)
    assert all(w < 1.0 for w in weights)
    assert weights == pytest.approx([0.25, 0.25, 0.25, 0.25])


def test_from_frame_preserves_the_caller_supplied_index():
    idx = _index(4)
    df = pd.DataFrame(
        {"start": [idx[0], idx[2]], "end": [idx[1], idx[3]]},
        index=["obs_a", "obs_b"],
    )
    weights = average_uniqueness_from_frame(df, idx)
    assert list(weights.index) == ["obs_a", "obs_b"]
    assert weights.tolist() == pytest.approx([1.0, 1.0])


def test_rejects_a_window_whose_endpoints_are_not_on_the_index():
    idx = _index(4)
    windows = [LabelWindow(pd.Timestamp("2099-01-01"), idx[1])]
    with pytest.raises(UniquenessError):
        average_uniqueness_weights(windows, idx)


def test_rejects_end_before_start():
    idx = _index(4)
    windows = [LabelWindow(idx[2], idx[0])]
    with pytest.raises(UniquenessError):
        average_uniqueness_weights(windows, idx)


def test_empty_windows_returns_empty_array():
    idx = _index(4)
    weights = average_uniqueness_weights([], idx)
    assert len(weights) == 0
