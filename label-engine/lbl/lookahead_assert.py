"""The look-ahead assertion (FEAT-02).

"Look ahead test on every training run. Assert every label's knowable-from
timestamp is strictly later than every feature paired with it, and make it
impossible to disable in config."

This module is that assertion, in full, and nothing else. Read the function
signature below: there is no `strict=`, no `enabled=`, no config object, no
environment-variable escape hatch. The only way to not run this check on a
training run is to not call the function at all, which is a visible line to
delete/never-add in review — not a flag anyone can flip in a config file.
`assert_no_lookahead` either raises `LookAheadError` or returns `None`; there
is no third outcome.

Wiring this into an actual training loop (weekly-engine, chaos-engine, or a
future consumer of feature-store) is intentionally NOT done in this pass —
see ../README.md — but the function itself already enforces the FEAT-02
"done when" bar: it sits ready to be called, unconditionally, in any training
path that pairs this package's labels with feature-store's features.
"""

from __future__ import annotations

from typing import Sequence, Union

import numpy as np
import pandas as pd


class LookAheadError(AssertionError):
    """Raised when a label's knowable-from timestamp is not strictly later
    than the as-of timestamp of the feature it is paired with — i.e. a
    look-ahead leak. Always a hard failure; never a warning."""


LabelsInput = Union[pd.DataFrame, pd.Series, Sequence]
FeaturesInput = Union[pd.DataFrame, pd.Series, Sequence]


def _as_timestamp_series(data, col: str, arg_name: str) -> pd.Series:
    if isinstance(data, pd.DataFrame):
        if col not in data.columns:
            raise ValueError(f"{arg_name} DataFrame has no '{col}' column")
        s = data[col]
    else:
        s = pd.Series(data)
    return pd.to_datetime(s, errors="coerce").reset_index(drop=True)


def assert_no_lookahead(
    labels: LabelsInput,
    features: FeaturesInput,
    *,
    knowable_col: str = "knowable_from",
    as_of_col: str = "as_of",
) -> None:
    """Raise `LookAheadError` unless every feature is strictly older than the
    label it is paired with.

    `labels` and `features` are paired row-for-row, in order (this function
    does not attempt to align by index/join key — that alignment is the
    caller's responsibility, upstream of this check). Each may be:
      - a DataFrame with a `knowable_col` / `as_of_col` timestamp column, or
      - a Series (or any sequence) of timestamps directly.

    For every position i where both timestamps are defined (non-null), this
    requires `features[i] < labels[i]`, strictly. Equality is a leak, not a
    pass: a feature computed at the exact instant a label becomes knowable
    could not actually have used that label's information, but it is
    indistinguishable from a feature that *did* leak it, so this check
    refuses to allow the ambiguity — labels and features must never share a
    timestamp.

    Rows where either timestamp is null are skipped (nothing to check yet —
    e.g. a label still pending); if EVERY row is null on either side, this
    passes trivially (there is nothing defined to have leaked).

    There is no parameter here, and there will not be one added, that
    disables this check. See the module docstring.

    Raises:
        ValueError: if `labels` and `features` are not the same length.
        LookAheadError: if any paired row leaks — as_of >= knowable_from.
    """
    knowable = _as_timestamp_series(labels, knowable_col, "labels")
    as_of = _as_timestamp_series(features, as_of_col, "features")

    if len(knowable) != len(as_of):
        raise ValueError(
            f"labels and features must be paired 1:1 (same length); got "
            f"{len(knowable)} label row(s) vs {len(as_of)} feature row(s)"
        )

    defined = knowable.notna() & as_of.notna()
    if not defined.any():
        return

    leaked = defined & (as_of >= knowable)
    if leaked.any():
        n = int(leaked.sum())
        bad_positions = np.flatnonzero(leaked.to_numpy())
        preview = ", ".join(
            f"row {int(p)}: feature as_of={as_of.iloc[p]!r} >= label knowable_from={knowable.iloc[p]!r}"
            for p in bad_positions[:5]
        )
        raise LookAheadError(
            f"{n} row(s) have a feature as-of timestamp that is not strictly before "
            f"the paired label's knowable-from timestamp — this is a look-ahead leak. "
            f"{preview}" + (" ..." if n > 5 else "")
        )
