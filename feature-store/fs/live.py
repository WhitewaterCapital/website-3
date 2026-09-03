"""Live serving path -- FEAT-01.

Spec: "Serve live inference from the same function called with as of now,
plus a test comparing batch and live on the same timestamp that fails on
any mismatch."

Neither function below reimplements a feature's math. Each takes the
`FeatureDef` straight out of the same `FeatureRegistry` `panel.py` reads,
truncates the caller's history/snapshot to `as_of`, and calls the literal
same `.compute` callable object the batch panel builder calls. Batch and
live can only disagree if `.compute` itself is not a pure, non-anticipative
function of its point-in-time input (see registry.py's docstring on that
requirement) -- these two paths never hold independent copies of the
computation to disagree with each other.
"""
from __future__ import annotations

import pandas as pd

from .missing_data import apply_missing_data_policy
from .registry import FeatureDef


def compute_live_feature(
    feature_def: FeatureDef,
    history: pd.DataFrame,
    as_of,
) -> object:
    """Serve `feature_def` "as of now" for a single security.

    `history` should already be point-in-time safe (no rows dated after
    `as_of`) -- as an extra guard this function truncates to `as_of`
    itself, so a caller who accidentally over-fetched is still safe here,
    though a real serving path should not rely on that.

    Returns `None` when there is no history at all as of `as_of` (nothing
    to compute from -- genuinely unknown, never fabricated). Otherwise
    returns the feature's value at `as_of` after its own missing-data
    policy has been applied (the value itself may still be NaN, e.g. under
    `treat_as_missing`, or under `forward_fill_max_age` when the last valid
    observation is older than `max_age_periods`) -- consistent with how
    `panel.py` represents "missing" in the batch panel.
    """
    if feature_def.kind != "per_security":
        raise ValueError(
            f"{feature_def.name!r} is a {feature_def.kind!r} feature; use "
            "compute_live_cross_sectional for cross-sectional features"
        )
    as_of = pd.Timestamp(as_of)
    truncated = history.loc[history.index <= as_of]
    if truncated.empty:
        return None

    raw = feature_def.compute(truncated)
    if not isinstance(raw, pd.Series):
        raise TypeError(
            f"feature {feature_def.name!r} compute() must return a pandas Series, "
            f"got {type(raw).__name__}"
        )
    raw = raw.reindex(truncated.index)
    filled = apply_missing_data_policy(raw, feature_def)

    if as_of not in filled.index:
        # `history` had no row exactly at as_of (e.g. a non-trading day) --
        # the most recent point-in-time value available is the honest
        # answer for "as of now", never a fabricated interpolation.
        return filled.iloc[-1]
    return filled.loc[as_of]


def compute_live_cross_sectional(
    feature_def: FeatureDef,
    cross_section: pd.DataFrame,
    as_of=None,
) -> pd.Series:
    """Serve a cross-sectional `feature_def` "as of now" across one
    snapshot: `cross_section` has one row per security (indexed by
    security) holding that base feature's already-computed value (and, for
    the sector variant, a "sector" column) as of a single date.

    Calls the exact same `feature_def.compute` that
    `cross_sectional.add_cross_sectional_column` calls per-date in the
    batch panel -- see that module. `as_of` is accepted only for
    call-site symmetry with `compute_live_feature` / logging; it plays no
    role in the computation itself, since `cross_section` is already a
    single date's snapshot.
    """
    if feature_def.kind != "cross_sectional":
        raise ValueError(
            f"{feature_def.name!r} is a {feature_def.kind!r} feature; use "
            "compute_live_feature for per-security features"
        )
    result = feature_def.compute(cross_section)
    if not isinstance(result, pd.Series):
        raise TypeError(
            f"cross-sectional feature {feature_def.name!r} compute() must return a "
            f"pandas Series, got {type(result).__name__}"
        )
    return apply_missing_data_policy(result, feature_def)
