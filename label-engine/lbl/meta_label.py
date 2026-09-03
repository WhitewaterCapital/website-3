"""Meta-labeling (López de Prado, FEAT-02).

The primary model answers "which direction, if any" (e.g. +1/-1/0, or a
fired boolean plus a separate direction). Meta-labeling trains a SECOND,
independent target that answers a narrower question: "given that the primary
model fired, was acting on it actually a good idea?" This is usually a
bigger improvement than anything done to the primary model itself, because it
lets a classifier learn where the primary model's signal is trustworthy
without touching the primary model's own directional call.

The one rule this module exists to enforce mechanically: the meta-label
training set contains ONLY rows where the primary model actually fired. Rows
where it did not fire are not "acted on, badly" — there is no action to
grade — so they are dropped entirely, not kept with a placeholder/default
label. Keeping them with a default (e.g. label=0 for "didn't act") would
silently teach the meta-model to reproduce the primary model's own firing
decision instead of learning when to trust it.

Profitability convention (documented, since more than one reasonable
convention exists): a fired observation is labeled `meta_label = 1` iff the
SIGN of the primary model's direction matches the SIGN of the realized
outcome (whatever that outcome is — a forward return, or a triple-barrier
realized_return/label); otherwise `meta_label = 0`. A realized outcome of
exactly 0 (e.g. a triple-barrier timeout with zero net return) has sign 0,
which never matches a nonzero direction, so it is scored `meta_label = 0` —
conservative on purpose: no realized gain means the trade did not pay for
itself, whatever the reason.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class MetaLabelError(ValueError):
    """Raised for malformed meta-labeling inputs (misaligned indices, or a
    realized outcome missing for a row the primary model fired on)."""


def build_meta_labels(
    primary_direction: pd.Series,
    realized_outcome: pd.Series,
    fired: pd.Series | None = None,
) -> pd.DataFrame:
    """Build the meta-labeling training set.

    Args:
        primary_direction: the primary model's directional call per
            observation, e.g. values in {-1, 0, +1}. If `fired` is not given
            separately, 0 is treated as "the primary model did not fire" and
            excluded — this is the common convention for a signed direction
            series with no separate fired flag.
        realized_outcome: the realized outcome to grade the direction
            against (a forward return, a triple-barrier realized_return, or
            a triple-barrier discrete label — any signed quantity). Must
            share `primary_direction`'s index.
        fired: optional explicit boolean mask of which rows the primary
            model actually fired on. Pass this when 0 is a legitimate
            (nonzero-confidence) direction value in your primary model and
            firing is tracked separately. Defaults to
            `primary_direction != 0`.

    Returns:
        A DataFrame indexed by ONLY the fired rows (non-fired rows are
        absent entirely, not present with a default label), with columns:
          - `primary_direction`
          - `realized_outcome`
          - `meta_label`: 1 if sign(primary_direction) == sign(realized_outcome)
            else 0, per the module's documented convention.

    Raises:
        MetaLabelError if the two input series are not index-aligned, or if
        any fired row has a NaN realized outcome (an unresolved/live position
        cannot be used as a meta-labeling training example — it must be
        dropped from the training set, not defaulted).
    """
    if not primary_direction.index.equals(realized_outcome.index):
        raise MetaLabelError("primary_direction and realized_outcome must share the same index")

    if fired is None:
        fired = primary_direction != 0
    else:
        if not fired.index.equals(primary_direction.index):
            raise MetaLabelError("fired must share the same index as primary_direction")
        fired = fired.astype(bool)

    fired_idx = fired[fired].index
    direction = primary_direction.loc[fired_idx]
    outcome = realized_outcome.loc[fired_idx]

    if outcome.isna().any():
        n = int(outcome.isna().sum())
        raise MetaLabelError(
            f"{n} fired row(s) have no realized outcome yet (NaN) — drop unresolved "
            "positions from the input before building meta-labels; they cannot be "
            "given a default label without fabricating an outcome"
        )

    meta_label = (np.sign(direction.to_numpy()) == np.sign(outcome.to_numpy())).astype(int)

    return pd.DataFrame(
        {
            "primary_direction": direction,
            "realized_outcome": outcome,
            "meta_label": meta_label,
        },
        index=fired_idx,
    )
