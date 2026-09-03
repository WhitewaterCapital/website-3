"""The core FEAT-02 acceptance test: `assert_no_lookahead` raises on a
deliberately leaky feature/label pair, passes cleanly on a properly-aligned
one, and has no parameter anywhere that can suppress the raise."""

from __future__ import annotations

import inspect

import pandas as pd
import pytest

from lbl.forward_return import forward_return_labels
from lbl.lookahead_assert import LookAheadError, assert_no_lookahead


def _weekly_prices(n=8):
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI")
    return pd.Series([100.0 + i for i in range(n)], index=idx)


def test_raises_on_a_deliberately_leaky_pairing():
    """The feature's as_of is the SAME timestamp the label becomes knowable
    at (i.e. the feature effectively saw the very close the label depends
    on) — a textbook one-row leak."""
    weeks = pd.date_range("2020-01-03", periods=5, freq="W-FRI")
    labels = pd.DataFrame({"knowable_from": weeks + pd.Timedelta(weeks=1)})
    leaky_features = pd.DataFrame({"as_of": weeks + pd.Timedelta(weeks=1)})  # == knowable_from
    with pytest.raises(LookAheadError):
        assert_no_lookahead(labels, leaky_features)


def test_raises_when_feature_as_of_is_even_later_than_knowable_from():
    weeks = pd.date_range("2020-01-03", periods=5, freq="W-FRI")
    labels = pd.DataFrame({"knowable_from": weeks + pd.Timedelta(weeks=1)})
    features = pd.DataFrame({"as_of": weeks + pd.Timedelta(weeks=2)})  # even later
    with pytest.raises(LookAheadError):
        assert_no_lookahead(labels, features)


def test_passes_cleanly_on_a_properly_aligned_pairing():
    weeks = pd.date_range("2020-01-03", periods=5, freq="W-FRI")
    labels = pd.DataFrame({"knowable_from": weeks + pd.Timedelta(weeks=1)})
    features = pd.DataFrame({"as_of": weeks})  # strictly before knowable_from
    assert_no_lookahead(labels, features)  # must not raise


def test_end_to_end_with_real_forward_return_labels():
    """Build actual forward_return_labels and pair them with features whose
    as_of is the label's own reference week (correct) vs. the label's
    knowable_from week (a real, easy-to-make one-row shift bug)."""
    prices = _weekly_prices(8)
    lab = forward_return_labels(prices, horizon=1)
    defined = lab["knowable_from"].notna()
    lab = lab.loc[defined]

    good_features = pd.DataFrame({"as_of": lab.index.to_series().reset_index(drop=True)})
    assert_no_lookahead(lab.reset_index(drop=True), good_features)  # must not raise

    leaky_features = pd.DataFrame({"as_of": lab["knowable_from"].reset_index(drop=True)})
    with pytest.raises(LookAheadError):
        assert_no_lookahead(lab.reset_index(drop=True), leaky_features)


def test_accepts_raw_timestamp_sequences_not_just_dataframes():
    weeks = pd.date_range("2020-01-03", periods=3, freq="W-FRI")
    knowable_from = weeks + pd.Timedelta(weeks=1)
    as_of_good = weeks
    as_of_bad = knowable_from
    assert_no_lookahead(knowable_from, as_of_good)
    with pytest.raises(LookAheadError):
        assert_no_lookahead(knowable_from, as_of_bad)


def test_rows_with_no_defined_label_yet_are_skipped_not_flagged():
    weeks = pd.date_range("2020-01-03", periods=3, freq="W-FRI")
    labels = pd.DataFrame({"knowable_from": [weeks[1], weeks[2], pd.NaT]})
    features = pd.DataFrame({"as_of": weeks})
    assert_no_lookahead(labels, features)  # last row has no label yet -> not a leak


def test_mismatched_lengths_raise_value_error_not_silently_truncate():
    labels = pd.DataFrame({"knowable_from": pd.date_range("2020-01-01", periods=5, freq="D")})
    features = pd.DataFrame({"as_of": pd.date_range("2020-01-01", periods=4, freq="D")})
    with pytest.raises(ValueError):
        assert_no_lookahead(labels, features)


def test_there_is_no_parameter_to_disable_the_check():
    """Per FEAT-02: 'make it impossible to disable in config.' Verify by
    inspecting the actual function signature — there is no strict=/enabled=/
    config= parameter, only the two required positional inputs and the two
    column-name overrides (which name WHICH columns to read, not whether to
    check them)."""
    sig = inspect.signature(assert_no_lookahead)
    param_names = set(sig.parameters.keys())
    assert param_names == {"labels", "features", "knowable_col", "as_of_col"}
    for forbidden in ("strict", "enabled", "disable", "skip", "config", "bypass", "force"):
        assert forbidden not in param_names

    # And passing any such flag anyway is simply a TypeError -- there is no
    # hidden **kwargs sink absorbing an attempt to silence this.
    weeks = pd.date_range("2020-01-03", periods=3, freq="W-FRI")
    labels = pd.DataFrame({"knowable_from": weeks + pd.Timedelta(weeks=1)})
    features = pd.DataFrame({"as_of": weeks + pd.Timedelta(weeks=1)})  # leaky
    with pytest.raises(TypeError):
        assert_no_lookahead(labels, features, strict=False)  # type: ignore[call-arg]
