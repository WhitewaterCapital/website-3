"""Tests for cost/tracking.py (IMP-18)."""

from __future__ import annotations

import datetime

import pytest

from tracking import CostErrorTracker, CostTrackingRecord


def _ts(year, month, day):
    return datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc).timestamp()


def test_record_error_and_abs_error():
    r = CostTrackingRecord(strategy_id="s1", timestamp=0.0, predicted_cost=0.01, realized_slippage=0.014)
    assert r.error == pytest.approx(0.004)
    assert r.abs_error == pytest.approx(0.004)

    r2 = CostTrackingRecord(strategy_id="s1", timestamp=0.0, predicted_cost=0.02, realized_slippage=0.015)
    assert r2.error == pytest.approx(-0.005)
    assert r2.abs_error == pytest.approx(0.005)


def test_mean_absolute_error_overall_and_per_strategy():
    tracker = CostErrorTracker()
    tracker.add_observation("s1", _ts(2026, 1, 5), predicted_cost=0.01, realized_slippage=0.012)  # abs err .002
    tracker.add_observation("s1", _ts(2026, 1, 6), predicted_cost=0.01, realized_slippage=0.008)  # abs err .002
    tracker.add_observation("s2", _ts(2026, 1, 6), predicted_cost=0.02, realized_slippage=0.03)   # abs err .01

    assert tracker.mean_absolute_error("s1") == pytest.approx(0.002)
    assert tracker.mean_absolute_error("s2") == pytest.approx(0.01)
    overall = tracker.mean_absolute_error()
    assert overall == pytest.approx((0.002 + 0.002 + 0.01) / 3)


def test_mean_absolute_error_is_none_with_no_observations():
    tracker = CostErrorTracker()
    assert tracker.mean_absolute_error() is None
    assert tracker.mean_absolute_error("nope") is None


def test_weekly_mean_absolute_error_buckets_by_iso_week():
    tracker = CostErrorTracker()
    # 2026-01-05 (Mon) and 2026-01-06 (Tue) are the same ISO week.
    # 2026-01-19 (Mon) is a different ISO week (two weeks later).
    tracker.add_observation("s1", _ts(2026, 1, 5), predicted_cost=0.01, realized_slippage=0.012)  # abs .002
    tracker.add_observation("s1", _ts(2026, 1, 6), predicted_cost=0.01, realized_slippage=0.014)  # abs .004
    tracker.add_observation("s1", _ts(2026, 1, 19), predicted_cost=0.01, realized_slippage=0.005)  # abs .005

    weekly = tracker.weekly_mean_absolute_error("s1")
    week1_key = datetime.datetime(2026, 1, 5, tzinfo=datetime.timezone.utc).isocalendar()
    week3_key = datetime.datetime(2026, 1, 19, tzinfo=datetime.timezone.utc).isocalendar()
    k1 = (week1_key[0], week1_key[1])
    k3 = (week3_key[0], week3_key[1])

    assert k1 != k3
    assert weekly[k1] == pytest.approx((0.002 + 0.004) / 2)
    assert weekly[k3] == pytest.approx(0.005)


def test_records_for_filters_by_strategy():
    tracker = CostErrorTracker()
    tracker.add_observation("s1", 0.0, 0.01, 0.011)
    tracker.add_observation("s2", 0.0, 0.02, 0.021)
    assert len(tracker.records_for("s1")) == 1
    assert len(tracker.records_for("s2")) == 1
    assert tracker.records_for("s1")[0].strategy_id == "s1"
