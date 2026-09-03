"""Label tests — most importantly, the look-ahead falsification test.

The point of `assert_no_lookahead` is not just that it exists, but that it
would actually CATCH a real alignment bug. `test_lookahead_assertion_catches_a_shifted_alignment`
builds exactly the bug a one-row shift would introduce (label computed from
the SAME week's return instead of next week's) and confirms the assertion
raises on it — proving the check is not a tautology that always passes.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wf.features.panel import build_feature_panel
from wf.labels import LookAheadError, assert_no_lookahead, compute_labels
from wf.synthetic import default_sector_map, generate_synthetic_weekly_prices


def test_build_feature_panel_produces_a_lookahead_clean_panel():
    tickers = [f"T{i}" for i in range(6)]
    prices = generate_synthetic_weekly_prices(tickers, n_weeks=60, seed=1, signal_strength=0.2)
    sectors = default_sector_map(tickers)
    # build_feature_panel calls assert_no_lookahead internally; not raising IS the assertion.
    panel, _, _ = build_feature_panel(prices, sectors)
    assert_no_lookahead(panel)  # calling it again directly should also pass, trivially


def test_compute_labels_knowable_from_is_strictly_after_the_feature_week():
    tickers = ["A"]
    prices = generate_synthetic_weekly_prices(tickers, n_weeks=40, seed=0, signal_strength=0.1)
    from wf.features.panel import prepare_base

    base = prepare_base(prices["A"])
    lab = compute_labels(base)
    defined = lab["label_knowable_from"].notna()
    assert defined.sum() == len(lab) - 1  # every row except the very last
    assert (lab.loc[defined, "label_knowable_from"] > lab.loc[defined].index.to_series()).all()


def test_lookahead_assertion_catches_a_shifted_alignment():
    """Deliberately construct the bug: a label that uses the SAME week's
    return (as if someone forgot the shift(-1)/removed one row of alignment)
    rather than next week's. This is exactly what an accidental one-row
    shift in a merge/join would produce. The assertion MUST raise."""
    weeks = pd.date_range("2020-01-03", periods=10, freq="W-FRI")
    panel = pd.DataFrame(
        {
            "week": weeks,
            "ticker": ["Z"] * 10,
            # BUG: knowable_from == week itself, i.e. the label is claimed to
            # be knowable at the same instant as the feature row — this is
            # what a broken (unshifted) label/feature merge looks like.
            "label_knowable_from": weeks,
            "fwd_return": range(10),
        }
    )
    with pytest.raises(LookAheadError):
        assert_no_lookahead(panel)


def test_lookahead_assertion_also_catches_knowable_from_before_the_feature_week():
    weeks = pd.date_range("2020-01-03", periods=5, freq="W-FRI")
    panel = pd.DataFrame(
        {
            "week": weeks,
            "ticker": ["Z"] * 5,
            "label_knowable_from": weeks - pd.Timedelta(weeks=1),  # even worse: "knowable" in the past
            "fwd_return": range(5),
        }
    )
    with pytest.raises(LookAheadError):
        assert_no_lookahead(panel)


def test_lookahead_assertion_passes_on_a_correctly_shifted_label():
    weeks = pd.date_range("2020-01-03", periods=5, freq="W-FRI")
    panel = pd.DataFrame(
        {
            "week": weeks,
            "ticker": ["Z"] * 5,
            "label_knowable_from": weeks + pd.Timedelta(weeks=1),  # correct: one week later
            "fwd_return": range(5),
        }
    )
    assert_no_lookahead(panel)  # must not raise


def test_lookahead_assertion_ignores_rows_with_no_label_yet():
    # The live/current-week row has no defined label (NaT knowable_from) —
    # that must not trip the assertion.
    weeks = pd.date_range("2020-01-03", periods=3, freq="W-FRI")
    panel = pd.DataFrame(
        {
            "week": weeks,
            "ticker": ["Z"] * 3,
            "label_knowable_from": [weeks[1], weeks[2], pd.NaT],
            "fwd_return": [0.01, 0.02, float("nan")],
        }
    )
    assert_no_lookahead(panel)
