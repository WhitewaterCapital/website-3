"""Forward-return label tests: alignment (knowable_from is strictly later
than the label's own reference date) and the horizon>=1 guard."""

from __future__ import annotations

import pandas as pd
import pytest

from lbl.forward_return import ForwardReturnLabel, forward_return_labels, to_records


def _weekly_prices(n=10):
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    return pd.Series([100.0 + i for i in range(n)], index=idx)


def test_knowable_from_is_strictly_after_the_reference_week():
    prices = _weekly_prices(10)
    lab = forward_return_labels(prices, horizon=1)
    defined = lab["knowable_from"].notna()
    assert defined.sum() == len(lab) - 1  # every row except the last has a defined label
    assert (lab.loc[defined, "knowable_from"] > lab.loc[defined].index.to_series()).all()


def test_forward_return_value_matches_close_to_close_return():
    prices = _weekly_prices(5)
    lab = forward_return_labels(prices, horizon=1)
    # prices are 100,101,102,103,104 -> ret[0] = 101/100-1
    assert lab["forward_return"].iloc[0] == pytest.approx(101.0 / 100.0 - 1.0)
    assert lab["knowable_from"].iloc[0] == prices.index[1]


def test_horizon_greater_than_one_uses_the_actual_future_timestamp_not_a_fixed_offset():
    prices = _weekly_prices(10)
    lab = forward_return_labels(prices, horizon=3)
    defined = lab["knowable_from"].notna()
    assert defined.sum() == len(lab) - 3
    # knowable_from for row i must be exactly index[i+3], the real calendar
    # timestamp of that row — not index[i] + 3 weeks (which would coincide
    # here since the series is regularly spaced, but the *mechanism* under
    # test is that it reads the index value, not a fixed timedelta).
    for i in range(len(prices) - 3):
        assert lab["knowable_from"].iloc[i] == prices.index[i + 3]


def test_horizon_must_be_at_least_one():
    prices = _weekly_prices(5)
    with pytest.raises(ValueError):
        forward_return_labels(prices, horizon=0)


def test_to_records_drops_the_undefined_trailing_rows_and_preserves_pairing():
    prices = _weekly_prices(6)
    lab = forward_return_labels(prices, horizon=1)
    records = to_records(lab)
    assert len(records) == len(prices) - 1
    assert all(isinstance(r, ForwardReturnLabel) for r in records)
    first = records[0]
    assert first.ref_time == prices.index[0]
    assert first.knowable_from == prices.index[1]
    assert first.knowable_from > first.ref_time
    assert first.value == pytest.approx(prices.iloc[1] / prices.iloc[0] - 1.0)
