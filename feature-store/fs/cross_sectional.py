"""Cross-sectional transforms -- FEAT-01.

Spec: "Cross sectional transforms are separate registered features. Rank,
z score within universe and z score within sector are three different
features and get named as such."

Each transform here is its OWN `FeatureDef` (`kind="cross_sectional"`),
registered under its own name (`{base}_rank`, `{base}_zscore_universe`,
`{base}_zscore_sector`) and its own version -- not a helper method bolted
onto the base feature. Its `.compute` is a pure function of a single
date's cross-section (one row per security: the base feature's already-
computed value, plus a "sector" column for the sector variant) -- it never
recomputes the base feature's own time-series math, it only consumes the
base feature's already-computed panel column.

`add_cross_sectional_column` (batch) and `live.compute_live_cross_sectional`
(serving) both call the identical registered `.compute` function, same as
the per-security path in panel.py / live.py.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .missing_data import apply_missing_data_policy
from .registry import FeatureDef, FeatureRegistry

# A group (universe, or a sector) smaller than this cannot be meaningfully
# standardized (std of 0 or 1 points is 0 or undefined) -- such groups get
# NaN by construction, never a fabricated 0.
MIN_GROUP_SIZE_FOR_ZSCORE = 2


def _rank_compute(base_col: str):
    def compute(cross_section: pd.DataFrame) -> pd.Series:
        return cross_section[base_col].rank(pct=True)

    return compute


def _zscore_universe_compute(base_col: str):
    def compute(cross_section: pd.DataFrame) -> pd.Series:
        s = cross_section[base_col]
        n_valid = s.notna().sum()
        if n_valid < MIN_GROUP_SIZE_FOR_ZSCORE:
            return pd.Series(np.nan, index=s.index)
        std = s.std(ddof=0)
        if not std or pd.isna(std):
            return pd.Series(np.nan, index=s.index)
        return (s - s.mean()) / std

    return compute


def _zscore_sector_compute(base_col: str, sector_col: str = "sector"):
    def compute(cross_section: pd.DataFrame) -> pd.Series:
        if sector_col not in cross_section.columns:
            raise ValueError(
                f"zscore_sector feature requires a {sector_col!r} column in the cross-section"
            )
        s = cross_section[base_col]
        grp = cross_section.groupby(sector_col)[base_col]
        size = grp.transform(lambda x: x.notna().sum())
        mean = grp.transform("mean")
        std = grp.transform(lambda x: x.std(ddof=0))
        z = (s - mean) / std.replace(0.0, np.nan)
        return z.where(size >= MIN_GROUP_SIZE_FOR_ZSCORE, np.nan)

    return compute


def register_cross_sectional_transforms(
    registry: FeatureRegistry,
    base_feature: FeatureDef,
    owner: str,
    version: str = "1.0.0",
):
    """Register rank / zscore-within-universe / zscore-within-sector, each
    as a distinct named `FeatureDef` built on top of `base_feature`'s
    already-computed panel column. Returns (rank_def, zscore_universe_def,
    zscore_sector_def)."""
    if base_feature.kind != "per_security":
        raise ValueError(
            f"cross-sectional transforms must be built on a per_security base feature, "
            f"got {base_feature.name!r} (kind={base_feature.kind!r})"
        )
    base = base_feature.name

    rank_def = registry.register(
        FeatureDef(
            name=f"{base}_rank",
            version=version,
            owner=owner,
            lookback=0,
            rationale=(
                f"Cross-sectional percentile rank of {base!r} within the universe on a "
                "given date. Puts every name on a common 0-1 ordering scale so the model "
                "consumes relative standing rather than a raw level it would otherwise have "
                "to re-derive per name; also naturally robust to outliers, unlike a raw "
                "z-score."
            ),
            missing_data_policy="treat_as_missing",
            compute=_rank_compute(base),
            kind="cross_sectional",
            base_feature=(base_feature.name, base_feature.version),
        )
    )
    zscore_universe_def = registry.register(
        FeatureDef(
            name=f"{base}_zscore_universe",
            version=version,
            owner=owner,
            lookback=0,
            rationale=(
                f"Cross-sectional z-score of {base!r} against the full universe on a given "
                "date -- expresses how extreme a name's value is relative to the rest of the "
                "universe that day, standardized so the scale is comparable across dates with "
                "different dispersion regimes."
            ),
            missing_data_policy="treat_as_missing",
            compute=_zscore_universe_compute(base),
            kind="cross_sectional",
            base_feature=(base_feature.name, base_feature.version),
        )
    )
    zscore_sector_def = registry.register(
        FeatureDef(
            name=f"{base}_zscore_sector",
            version=version,
            owner=owner,
            lookback=0,
            rationale=(
                f"Cross-sectional z-score of {base!r} against same-sector peers on a given "
                "date -- isolates a name's idiosyncratic standing from a sector-wide move "
                "that a universe-wide z-score would otherwise mix in."
            ),
            missing_data_policy="treat_as_missing",
            compute=_zscore_sector_compute(base),
            kind="cross_sectional",
            base_feature=(base_feature.name, base_feature.version),
        )
    )
    return rank_def, zscore_universe_def, zscore_sector_def


def add_cross_sectional_column(
    panel: pd.DataFrame,
    feature_def: FeatureDef,
    base_col: str,
    sector_map: Optional[dict] = None,
) -> pd.Series:
    """Batch-apply a `kind="cross_sectional"` FeatureDef across every date
    in `panel` (a (security, date)-indexed frame, e.g. the output of
    `panel.build_panel`). Groups rows by date, builds each date's
    cross-section frame, and calls `feature_def.compute` on it -- the same
    function `live.compute_live_cross_sectional` calls for a single "as of
    now" snapshot.
    """
    if feature_def.kind != "cross_sectional":
        raise ValueError(f"{feature_def.name!r} is not a cross_sectional FeatureDef")
    if base_col not in panel.columns:
        raise KeyError(f"base column {base_col!r} not found in panel")

    out = pd.Series(index=panel.index, dtype=float, name=feature_def.name)
    for date, group in panel.groupby(level="date"):
        securities = group.index.get_level_values("security")
        cross_section = pd.DataFrame({base_col: group[base_col].to_numpy()}, index=securities)
        if sector_map is not None:
            cross_section["sector"] = [sector_map.get(sec) for sec in securities]
        values = feature_def.compute(cross_section)
        values = apply_missing_data_policy(values, feature_def)
        for sec, val in values.items():
            out.loc[(sec, date)] = val
    return out
