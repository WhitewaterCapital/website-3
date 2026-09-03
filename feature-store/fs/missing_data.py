"""Missing-data policy enforcement -- FEAT-01.

Spec: "Every feature declares a missing data policy. Forward fill with a
maximum age, treat as missing, or fail. Never fill with zero, because zero
is a real value for a return."

This is the ONE place that policy gets applied to a feature's raw computed
output. `panel.py` (batch) and `live.py` (serving) both call
`apply_missing_data_policy` against a raw (possibly NaN-containing) series
produced by the SAME `FeatureDef.compute` -- neither reimplements the
other's fill logic, which is exactly the kind of duplication FEAT-01 exists
to prevent.
"""
from __future__ import annotations

import pandas as pd

from .registry import FeatureDef


class MissingDataFailure(Exception):
    """Raised when a FeatureDef declaring missing_data_policy='fail' hits a
    missing (NaN) value in its raw computed output."""


def apply_missing_data_policy(raw: pd.Series, feature_def: "FeatureDef") -> pd.Series:
    """Apply `feature_def`'s declared missing-data policy to `raw`.

    - "treat_as_missing": pass NaN through unchanged. The consumer (a
      training script, a model) must handle NaN explicitly. Never coerced
      to 0.
    - "fail": any NaN in `raw`, PAST the feature's own declared warm-up
      window (`feature_def.lookback` periods -- see registry.py), is an
      error and raises `MissingDataFailure` naming the first offending
      index. A NaN inside the warm-up window itself is not a policy
      violation: `lookback` already documents that a feature genuinely
      cannot produce a value there, so `raw`'s first `lookback - 1`
      positions are exempt from this check by construction. Never silently
      substitutes anything.
    - "forward_fill_max_age": forward-fills from the last valid observation,
      but only up to `feature_def.max_age_periods` consecutive periods.
      A gap OLDER than that stays NaN -- it is not fabricated as 0, and it
      is not fabricated as a stale value past its declared shelf life.

    Never, under any policy, substitutes 0.0 for a missing value -- zero is
    a real, meaningful value for a feature like a return or a z-score, so
    treating "missing" and "zero" as the same thing would silently corrupt
    every consumer's math.

    `raw` must be aligned to the same (chronologically ordered, no gaps in
    row count -- e.g. a security's full history index) index it was
    computed over, so that "position `i`" in `raw` really does mean "`i+1`
    periods of history were available" -- which is what makes the
    lookback-based warm-up exemption above meaningful. Both `panel.py` and
    `live.py` call this with exactly that alignment.
    """
    policy = feature_def.missing_data_policy

    if policy == "treat_as_missing":
        return raw

    if policy == "fail":
        warmup = max(feature_def.lookback - 1, 0)
        checkable = raw.iloc[warmup:]
        bad = checkable.index[checkable.isna()]
        if len(bad):
            raise MissingDataFailure(
                f"feature {feature_def.name!r} v{feature_def.version} "
                f"(missing_data_policy='fail') produced {len(bad)} missing value(s) past its "
                f"{feature_def.lookback}-period warm-up window; first at index {bad[0]!r}"
            )
        return raw

    if policy == "forward_fill_max_age":
        # pandas' ffill(limit=N) forward-fills at most N consecutive NaNs
        # following the last valid observation -- exactly "maximum age" in
        # periods. No fill_value is ever passed, so a gap longer than
        # max_age_periods is left as NaN rather than defaulting to 0.
        return raw.ffill(limit=feature_def.max_age_periods)

    # Unreachable: FeatureDef.__post_init__ validates missing_data_policy
    # against the same three literals at registration time.
    raise ValueError(f"unknown missing_data_policy: {policy!r}")
