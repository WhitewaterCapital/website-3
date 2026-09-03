"""Cross-sectional transforms: rank and sector/universe-relative z-score.

These are the two mechanical operations features/panel.py applies on top of
the per-ticker base features to build the "raw + ranked" lagged-return block
and the "sector/universe-relative" versions of the technical block. Neither
is a per-ticker pure function (both need the whole week's cross-section), so
they live outside the @feature registry proper; panel.py folds their output
column names into the published feature manifest alongside it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_GROUP_SIZE_FOR_ZSCORE = 2


def cross_sectional_rank(panel: pd.DataFrame, col: str, group_cols: tuple[str, ...] = ("week",)) -> pd.Series:
    """Percentile rank (0..1) of `col` within each group (typically per week).

    Rank, not raw level, is what the model is ultimately validated against
    (rank IC) — putting a feature on a rank scale up front removes the
    across-name scale differences (price level, vol regime) a raw value would
    otherwise force the model to fight, and it is naturally robust to
    outliers a raw z-score is not.
    """
    return panel.groupby(list(group_cols))[col].rank(pct=True)


def cross_sectional_zscore(
    panel: pd.DataFrame, col: str, group_cols: tuple[str, ...] = ("week", "sector")
) -> pd.Series:
    """Cross-sectional z-score of `col` within each group (typically per
    week x sector). Expresses "hot/cold relative to peers" rather than an
    absolute level — the thing that actually transfers across regimes for a
    sector-neutral ranking product (see model/neutralize.py, which does the
    same demean-then-scale operation to the model's *output*).

    A group smaller than MIN_GROUP_SIZE_FOR_ZSCORE (e.g. a sector with one
    member that week) yields NaN by construction (std of one point is 0 ->
    division guarded to NaN, not a fabricated 0). Callers needing a value for
    thin sectors should fall back to a plain universe-wide z-score (see
    features/panel.py, which does exactly that for the sector_z columns).
    """
    grp = panel.groupby(list(group_cols))[col]
    size = grp.transform("size")
    mean = grp.transform("mean")
    std = grp.transform(lambda s: s.std(ddof=0))
    z = (panel[col] - mean) / std.replace(0.0, np.nan)
    return z.where(size >= MIN_GROUP_SIZE_FOR_ZSCORE, np.nan)
