"""Tests for the purged + embargoed walk-forward splitter (weekly cadence).

Headline: `test_no_leakage_gap` — in every fold, the last training week plus
the label horizon plus the embargo must fall strictly before the first test
week. If that gap is ever violated, a training label could have seen the
test period.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from wf.validation.splits import PurgedWalkForwardCV


def _calendar(n_weeks: int, tickers: int = 1) -> np.ndarray:
    weeks = pd.bdate_range("2015-01-02", periods=n_weeks, freq="W-FRI")
    return np.repeat(weeks.values, tickers)


def _positions(times):
    uniq = pd.DatetimeIndex(pd.to_datetime(times)).unique().sort_values()
    pos = {d: i for i, d in enumerate(uniq)}
    return np.array([pos[d] for d in pd.DatetimeIndex(pd.to_datetime(times))])


def test_no_leakage_gap():
    times = _calendar(400, tickers=5)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=1, embargo=1, min_train=100)
    pos = _positions(times)
    folds = cv.split(times)
    assert len(folds) >= 3
    for train_idx, test_idx in folds:
        last_train = pos[train_idx].max()
        first_test = pos[test_idx].min()
        assert last_train + cv.horizon + cv.embargo < first_test


def test_train_strictly_before_test():
    times = _calendar(300, tickers=4)
    cv = PurgedWalkForwardCV(n_splits=4, horizon=1, embargo=1, min_train=80)
    pos = _positions(times)
    for train_idx, test_idx in cv.split(times):
        assert pos[train_idx].max() < pos[test_idx].min()


def test_test_blocks_disjoint_and_ordered():
    times = _calendar(350, tickers=1)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=1, embargo=1, min_train=100)
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


def test_a_week_is_never_split_across_boundary():
    times = _calendar(260, tickers=4)
    tdt = pd.DatetimeIndex(pd.to_datetime(times))
    cv = PurgedWalkForwardCV(n_splits=4, horizon=1, embargo=1, min_train=60)
    for train_idx, test_idx in cv.split(times):
        train_weeks = set(tdt[train_idx])
        test_weeks = set(tdt[test_idx])
        assert not (train_weeks & test_weeks), "a week leaked across the split"


def test_bigger_embargo_widens_gap():
    times = _calendar(400, tickers=1)
    pos = _positions(times)
    small = PurgedWalkForwardCV(n_splits=5, horizon=1, embargo=1, min_train=100)
    big = PurgedWalkForwardCV(n_splits=5, horizon=1, embargo=20, min_train=100)

    def min_gap(cv):
        gaps = [pos[te].min() - pos[tr].max() for tr, te in cv.split(times)]
        return min(gaps)

    assert min_gap(big) > min_gap(small)


def test_purge_drops_label_windows_reaching_test():
    H = 1  # weekly label horizon
    times = _calendar(400, tickers=3)
    pos = _positions(times)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=H, embargo=1, min_train=120)
    for train_idx, test_idx in cv.split(times):
        test_lo = pos[test_idx].min()
        test_hi = pos[test_idx].max()
        label_window_end = pos[train_idx] + H
        assert label_window_end.max() < test_lo
        assert pos[train_idx].max() < test_lo or pos[train_idx].min() > test_hi


def test_raises_when_too_few_weeks():
    times = _calendar(3, tickers=1)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=1, embargo=1)
    with pytest.raises(ValueError):
        cv.split(times)


def test_raises_when_min_train_never_satisfied():
    times = _calendar(50, tickers=1)
    cv = PurgedWalkForwardCV(n_splits=5, horizon=1, embargo=1, min_train=10_000)
    with pytest.raises(ValueError):
        cv.split(times)
