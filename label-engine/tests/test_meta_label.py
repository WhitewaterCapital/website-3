"""Meta-labeling tests: the core requirement is that non-firing rows are
excluded from the training set entirely, not kept with a default label."""

from __future__ import annotations

import pandas as pd
import pytest

from lbl.meta_label import MetaLabelError, build_meta_labels


def _idx(n=6):
    return pd.date_range("2020-01-01", periods=n, freq="D")


def test_non_firing_rows_are_excluded_entirely():
    idx = _idx(6)
    # Fired on rows 0, 2, 4 (direction != 0); rows 1, 3, 5 did not fire (0).
    direction = pd.Series([1, 0, -1, 0, 1, 0], index=idx)
    outcome = pd.Series([0.02, 0.01, 0.03, -0.02, -0.01, 0.05], index=idx)

    meta = build_meta_labels(direction, outcome)

    assert len(meta) == 3
    assert set(meta.index) == {idx[0], idx[2], idx[4]}
    # None of the non-firing timestamps appear anywhere in the result.
    for t in (idx[1], idx[3], idx[5]):
        assert t not in meta.index


def test_meta_label_convention_sign_match_is_profitable():
    idx = _idx(4)
    direction = pd.Series([1, 1, -1, -1], index=idx)
    outcome = pd.Series([0.05, -0.02, -0.03, 0.01], index=idx)
    # row0: +1 dir, +return -> profitable (1)
    # row1: +1 dir, -return -> not profitable (0)
    # row2: -1 dir, -return -> profitable (1) (shorted and it went down)
    # row3: -1 dir, +return -> not profitable (0)
    meta = build_meta_labels(direction, outcome)
    assert meta.loc[idx[0], "meta_label"] == 1
    assert meta.loc[idx[1], "meta_label"] == 0
    assert meta.loc[idx[2], "meta_label"] == 1
    assert meta.loc[idx[3], "meta_label"] == 0


def test_zero_realized_outcome_is_scored_not_profitable():
    idx = _idx(2)
    direction = pd.Series([1, -1], index=idx)
    outcome = pd.Series([0.0, 0.0], index=idx)  # e.g. both timed out with no net move
    meta = build_meta_labels(direction, outcome)
    assert (meta["meta_label"] == 0).all()


def test_explicit_fired_mask_overrides_the_direction_nonzero_default():
    idx = _idx(3)
    # direction has a legitimate 0 (e.g. "flat but fired to say so") at row 1.
    direction = pd.Series([1, 0, -1], index=idx)
    outcome = pd.Series([0.01, 0.00, 0.02], index=idx)
    fired = pd.Series([True, True, False], index=idx)

    meta = build_meta_labels(direction, outcome, fired=fired)

    assert set(meta.index) == {idx[0], idx[1]}
    assert idx[2] not in meta.index
    # row1: direction 0 -> sign 0, outcome 0.0 -> sign 0 -> matches -> profitable
    assert meta.loc[idx[1], "meta_label"] == 1


def test_rejects_misaligned_indices():
    direction = pd.Series([1, -1], index=_idx(2))
    outcome = pd.Series([0.01, -0.01], index=_idx(3)[1:])  # shifted index
    with pytest.raises(MetaLabelError):
        build_meta_labels(direction, outcome)


def test_rejects_nan_realized_outcome_on_a_fired_row_rather_than_defaulting():
    idx = _idx(3)
    direction = pd.Series([1, -1, 1], index=idx)
    outcome = pd.Series([0.02, float("nan"), 0.01], index=idx)  # row 1 unresolved
    with pytest.raises(MetaLabelError):
        build_meta_labels(direction, outcome)
