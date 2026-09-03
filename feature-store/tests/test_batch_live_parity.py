"""Batch/live parity -- FEAT-01 (e), the core acceptance test.

Spec, verbatim: "Serve live inference from the same function called with
as of now, plus a test comparing batch and live on the same timestamp that
fails on any mismatch." ... "Done when batch and live produce identical
values for the same timestamp[.]"

This is deliberately the most important test file in this package. Every
other module exists to make this test trivially true; if it were ever
failing, FEAT-01 would not be done regardless of what else passes.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from fs.cross_sectional import add_cross_sectional_column, register_cross_sectional_transforms
from fs.live import compute_live_cross_sectional, compute_live_feature
from fs.panel import build_panel
from fs.registry import FeatureRegistry
from fs.sample_features import register_sample_features
from fs.synthetic import SAMPLE_SECTOR_MAP, SAMPLE_UNIVERSE, make_synthetic_ohlcv, make_synthetic_universe


def _values_match(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    a_nan = isinstance(a, float) and math.isnan(a)
    b_nan = isinstance(b, float) and math.isnan(b)
    if a_nan or b_nan:
        return a_nan and b_nan
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)


def _make_registry_and_histories():
    registry = FeatureRegistry()
    register_sample_features(registry, owner="test-owner")
    histories = make_synthetic_universe(universe=["DEMO_A", "DEMO_B"], n_periods=80, seed=42)
    return registry, histories


def test_batch_and_live_are_identical_for_every_sample_feature_and_timestamp():
    registry, histories = _make_registry_and_histories()
    per_security_defs = [fd for fd in registry.list() if fd.kind == "per_security"]

    universe = list(histories.keys())
    # Skip the first 25 rows so realized_vol_20 (policy='fail') and rsi_14
    # both have enough warm-up history for every requested date -- this
    # test is about batch/live AGREEMENT, not re-litigating the warm-up
    # tests in test_missing_data_policy.py.
    all_dates = histories[universe[0]].index
    check_dates = all_dates[25::7]  # a spread of as-of timestamps, not every single day
    assert len(check_dates) >= 5

    panel = build_panel(
        registry=registry,
        universe=universe,
        dates=check_dates,
        load_history=lambda sec: histories[sec],
        feature_names=[fd.name for fd in per_security_defs],
    )

    mismatches = []
    for security in universe:
        for as_of in check_dates:
            for fd in per_security_defs:
                batch_value = panel.loc[(security, as_of), fd.name]
                live_value = compute_live_feature(fd, histories[security], as_of)
                if not _values_match(batch_value, live_value):
                    mismatches.append((security, as_of, fd.name, batch_value, live_value))

    assert not mismatches, f"batch vs. live mismatches: {mismatches[:10]}"


def test_batch_and_live_stay_identical_when_live_only_sees_truncated_history():
    """The stronger version of the same guarantee: live is fed ONLY the
    history through `as_of` (simulating a real serving path that has never
    seen the future), not the full history batch was built from. If any
    registered feature secretly depended on later rows, this is where it
    would show up as a mismatch that the previous test could miss."""
    registry, histories = _make_registry_and_histories()
    per_security_defs = [fd for fd in registry.list() if fd.kind == "per_security"]
    universe = list(histories.keys())
    all_dates = histories[universe[0]].index
    check_dates = all_dates[25::7]

    panel = build_panel(
        registry=registry,
        universe=universe,
        dates=check_dates,
        load_history=lambda sec: histories[sec],
        feature_names=[fd.name for fd in per_security_defs],
    )

    for security in universe:
        truncated_history_cache = {}
        for as_of in check_dates:
            truncated = histories[security].loc[histories[security].index <= as_of]
            truncated_history_cache[as_of] = truncated
            for fd in per_security_defs:
                batch_value = panel.loc[(security, as_of), fd.name]
                live_value = compute_live_feature(fd, truncated, as_of)
                assert _values_match(batch_value, live_value), (
                    f"mismatch for {fd.name} on {security} @ {as_of}: "
                    f"batch={batch_value!r} live(truncated)={live_value!r}"
                )


def test_appending_future_rows_never_changes_a_past_computed_value():
    """The non-anticipative invariant every registered compute() must
    satisfy for batch/live parity to be possible at all: a feature's value
    at date t must not depend on any row dated after t."""
    registry, histories = _make_registry_and_histories()
    per_security_defs = [fd for fd in registry.list() if fd.kind == "per_security"]
    security = "DEMO_A"
    full_history = histories[security]
    cutoff = full_history.index[50]
    truncated_history = full_history.loc[full_history.index <= cutoff]

    for fd in per_security_defs:
        full_series = fd.compute(full_history).reindex(full_history.index)
        truncated_series = fd.compute(truncated_history).reindex(truncated_history.index)
        common_idx = truncated_series.index
        pd.testing.assert_series_equal(
            full_series.loc[common_idx],
            truncated_series,
            check_names=False,
            obj=fd.name,
            rtol=1e-12,
            atol=1e-12,
        )


def test_batch_and_live_identical_for_cross_sectional_features():
    """The same acceptance test, for the cross-sectional layer: rank,
    zscore_universe and zscore_sector must agree between the batch panel
    path (cross_sectional.add_cross_sectional_column) and the live snapshot
    path (live.compute_live_cross_sectional), for the same date."""
    registry = FeatureRegistry()
    sample = register_sample_features(registry, owner="test-owner")
    base_fd = sample["ret_lag_5"]
    rank_fd, zu_fd, zs_fd = register_cross_sectional_transforms(registry, base_fd, owner="test-owner")

    histories = make_synthetic_universe(universe=SAMPLE_UNIVERSE, n_periods=80, seed=99)
    universe = list(histories.keys())
    all_dates = histories[universe[0]].index
    check_date = all_dates[40]

    base_panel = build_panel(
        registry=registry,
        universe=universe,
        dates=[check_date],
        load_history=lambda sec: histories[sec],
        feature_names=[base_fd.name],
    )

    for xs_fd in (rank_fd, zu_fd, zs_fd):
        needs_sector = xs_fd is zs_fd
        batch_col = add_cross_sectional_column(
            base_panel,
            xs_fd,
            base_col=base_fd.name,
            sector_map=SAMPLE_SECTOR_MAP if needs_sector else None,
        )

        # Build the "live" snapshot exactly as a serving path would: one
        # row per security in today's universe, holding the SAME already-
        # computed base feature value the batch panel used.
        snapshot = pd.DataFrame(
            {base_fd.name: [base_panel.loc[(sec, check_date), base_fd.name] for sec in universe]},
            index=universe,
        )
        if needs_sector:
            snapshot["sector"] = [SAMPLE_SECTOR_MAP[sec] for sec in universe]

        live_values = compute_live_cross_sectional(xs_fd, snapshot, as_of=check_date)

        for sec in universe:
            batch_value = batch_col.loc[(sec, check_date)]
            live_value = live_values.loc[sec]
            assert _values_match(batch_value, live_value), (
                f"mismatch for {xs_fd.name} on {sec} @ {check_date}: "
                f"batch={batch_value!r} live={live_value!r}"
            )
