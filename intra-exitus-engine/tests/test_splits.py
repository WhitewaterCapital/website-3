"""Tests for the purged + embargoed walk-forward splitter.

The headline is `test_no_leakage_gap`: in every fold, the last training day plus
the label horizon plus the embargo must fall strictly before the first test day.
If that gap is ever violated, a training label could have seen the test period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ie.validation.splits import PurgedWalkForwardCV


def _calendar(n_days: int, tickers: int = 1) -> np.ndarray:
    """A pooled sample time vector: `tickers` samples per trading day."""
    days = pd.bdate_range("2015-01-02", periods=n_days)
    return np.repeat(days.values, tickers)


def _positions(times):
    uniq = pd.DatetimeIndex(pd.to_datetime(times)).unique().sort_values()
    pos = {d: i for i, d in enumerate(uniq)}
    return np.array([pos[d] for d in pd.DatetimeIndex(pd.to_datetime(times))])


def test_no_leakage_gap():
    times = _calendar(2000, tickers=3)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=10, embargo=5, min_train=200)
    pos = _positions(times)
    folds = cv.split(times)
    assert len(folds) >= 3
    for train_idx, test_idx in folds:
        last_train = pos[train_idx].max()
        first_test = pos[test_idx].min()
        # The core guarantee: horizon + embargo of clear air between them.
        assert last_train + cv.horizon + cv.embargo < first_test


def test_train_strictly_before_test():
    times = _calendar(1500, tickers=2)
    cv = PurgedWalkForwardCV(n_splits=4, horizon=10, embargo=5, min_train=200)
    pos = _positions(times)
    for train_idx, test_idx in cv.split(times):
        assert pos[train_idx].max() < pos[test_idx].min()


def test_test_blocks_disjoint_and_ordered():
    times = _calendar(1800, tickers=1)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=10, embargo=5, min_train=200)
    folds = cv.split(times)
    prev_hi = -1
    seen = set()
    for _, test_idx in folds:
        block = set(test_idx.tolist())
        assert not (block & seen), "test folds overlap"
        seen |= block
        lo = test_idx.min()
        assert lo > prev_hi, "test blocks not forward-ordered"
        prev_hi = test_idx.max()


def test_a_date_is_never_split_across_boundary():
    # With pooled tickers, every sample sharing a date must land on the same side.
    times = _calendar(1200, tickers=4)
    tdt = pd.DatetimeIndex(pd.to_datetime(times))
    cv = PurgedWalkForwardCV(n_splits=4, horizon=10, embargo=5, min_train=200)
    for train_idx, test_idx in cv.split(times):
        train_dates = set(tdt[train_idx])
        test_dates = set(tdt[test_idx])
        assert not (train_dates & test_dates), "a date leaked across the split"


def test_bigger_embargo_widens_gap():
    times = _calendar(2000, tickers=1)
    pos = _positions(times)
    small = PurgedWalkForwardCV(n_splits=5, horizon=10, embargo=1, min_train=200)
    big = PurgedWalkForwardCV(n_splits=5, horizon=10, embargo=40, min_train=200)

    def min_gap(cv):
        gaps = []
        for tr, te in cv.split(times):
            gaps.append(pos[te].min() - pos[tr].max())
        return min(gaps)

    assert min_gap(big) > min_gap(small)


def test_purge_drops_label_windows_reaching_test():
    # Fix #4: frame the guarantee in terms of the LABEL, not the splitter's own
    # arithmetic. Give each training sample a forward label window [pos, pos+H];
    # NONE of those windows may touch the test block. This catches an under-sized
    # cv.horizon that would leak silently.
    H = 20
    times = _calendar(2500, tickers=2)
    pos = _positions(times)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=H, embargo=5, min_train=300)
    for train_idx, test_idx in cv.split(times):
        test_lo = pos[test_idx].min()
        test_hi = pos[test_idx].max()
        # Every training sample's label window end must fall before the test block.
        label_window_end = pos[train_idx] + H
        assert label_window_end.max() < test_lo
        # And obviously no training sample sits inside the test block.
        assert pos[train_idx].max() < test_lo or pos[train_idx].min() > test_hi


def test_raises_when_too_few_dates():
    times = _calendar(3, tickers=1)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=10, embargo=5)
    with pytest.raises(ValueError):
        cv.split(times)
