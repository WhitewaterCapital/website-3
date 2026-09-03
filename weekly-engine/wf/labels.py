"""Labels: next-week forward return, sector-relative next-week forward return,
and the look-ahead guard that ties both back to the feature timestamps.

Two labels are produced and BOTH are trained/reported (spec: "train/report
both; note the relative one is usually more stable"):

  * `fwd_return`                — next week's raw forward return.
  * `sector_relative_fwd_return` — fwd_return minus that week's cross-sectional
    sector mean forward return (built in features/panel.py, since it needs
    the whole week's cross-section, not one ticker's own series).

Why the relative one is usually more stable: a sector- (or market-) wide move
next week is, by construction, exactly the part of next week's return this
engine has no business claiming to predict from lagged-return/RSI/momentum
features computed on one name at a time — those features carry no
macro/sector information. Demeaning it out before scoring removes a large
share of label variance that the model was never going to explain anyway,
which is why the *relative* label's rank IC is typically higher and more
consistent across folds than the raw label's.

The look-ahead guard: a label is only a valid training target if it is
*strictly* knowable later than the row's own feature timestamp. This module
tracks that explicitly as `label_knowable_from` rather than trusting the
shift arithmetic to always be right — see `assert_no_lookahead`, and
tests/test_labels.py for the falsification test that proves it actually
catches a shifted-by-one-row alignment bug rather than passing trivially.
"""

from __future__ import annotations

import pandas as pd


class LookAheadError(ValueError):
    """Raised when a label's knowable-from timestamp is not strictly later
    than the feature row's own timestamp — i.e. a look-ahead leak."""


def compute_labels(base: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker labels aligned to `base`'s weekly index.

    `base` has columns close/volume/ret (see features/panel.py::prepare_base).
    Returns a frame with:
      - fwd_return          : close[t+1]/close[t] - 1, i.e. next week's return.
      - label_knowable_from : the timestamp at which fwd_return is actually
        observable (the NEXT row's own date) — NaT for the last row, since
        there is no next week yet (that row is the live/current-week
        prediction row, never a training target).
    """
    idx = base.index
    close = base["close"]
    fwd_return = close.shift(-1) / close - 1.0
    # The next row's own timestamp, per ticker. Using the index's own values
    # (not "idx + 1 week") is deliberate: it is exact even if a real calendar
    # has holidays or an occasional short week, whereas a fixed offset could
    # silently understate the true knowable-from date.
    knowable_from = pd.Series(idx, index=idx).shift(-1)
    return pd.DataFrame({"fwd_return": fwd_return, "label_knowable_from": knowable_from}, index=idx)


def assert_no_lookahead(panel: pd.DataFrame, week_col: str = "week", knowable_col: str = "label_knowable_from") -> None:
    """Structural anti-leak check: for every row with a defined label, the
    label's knowable-from timestamp must be STRICTLY later than the row's own
    feature timestamp (`week_col`). Raises LookAheadError otherwise.

    This is the check tests/test_labels.py::test_lookahead_assertion_catches_a_shifted_alignment
    deliberately defeats by constructing a one-row-shifted (i.e. leaked)
    label frame, to prove the assertion is not a tautology.
    """
    defined = panel[knowable_col].notna()
    if not defined.any():
        return
    bad = defined & (panel[knowable_col] <= panel[week_col])
    if bad.any():
        n = int(bad.sum())
        raise LookAheadError(
            f"{n} row(s) have a label knowable no later than the feature timestamp — "
            "this is a look-ahead leak (label/feature alignment is broken)."
        )
