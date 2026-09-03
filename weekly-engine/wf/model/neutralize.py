"""Neutralize the model's raw prediction into the published output.

Spec: "Neutralize the output: subtract sector mean, scale by cross-sectional
dispersion." Two steps, in that order:

  1. **Sector-demean**: subtract that week's cross-sectional sector-mean
     prediction. A raw prediction can pick up a sector-wide tilt (the model
     saw every tech name's momentum feature move together and leaned long
     tech that week) that has nothing to do with telling AAPL from MSFT —
     exactly the thing a rank product should not be claiming credit for.
     Falls back to the universe-wide mean when a sector has fewer than 2
     members that week (same fallback rule as features/panel.py's sector-z
     columns, for the same reason: a "mean of one" isn't a mean).
  2. **Dispersion-scale**: divide by that week's cross-sectional standard
     deviation of the demeaned predictions. Weeks differ in how spread out
     the model's raw output is (a volatile week vs a quiet one); scaling by
     that week's own dispersion puts every week's published
     `expected_relative_return` on a comparable footing before ranking, so a
     "decile 10" one week means roughly the same thing as a "decile 10"
     another week.

This acts on the model's PREDICTIONS, mirroring exactly what
features/cross_sectional.py::cross_sectional_zscore does to input features —
same operation, applied to the other end of the pipeline.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_SECTOR_SIZE = 2


def neutralize_predictions(
    df: pd.DataFrame,
    pred_col: str,
    week_col: str = "week",
    sector_col: str = "sector",
) -> pd.Series:
    """Return the sector-demeaned, dispersion-scaled version of `df[pred_col]`."""
    sector_mean = df.groupby([week_col, sector_col])[pred_col].transform("mean")
    sector_size = df.groupby([week_col, sector_col])[pred_col].transform("size")
    universe_mean = df.groupby(week_col)[pred_col].transform("mean")
    baseline = sector_mean.where(sector_size >= MIN_SECTOR_SIZE, universe_mean)
    demeaned = df[pred_col] - baseline

    dispersion = demeaned.groupby(df[week_col]).transform(lambda s: s.std(ddof=0))
    scaled = demeaned / dispersion.replace(0.0, np.nan)
    return scaled


def decile_of(series: pd.Series, week: pd.Series) -> pd.Series:
    """1..10 decile of `series` within each week (10 = highest-ranked)."""

    def _decile(s: pd.Series) -> pd.Series:
        if s.notna().sum() < 2 or s.std(ddof=0) == 0:
            return pd.Series(np.nan, index=s.index)
        ranks = s.rank(method="first")
        n = int(s.notna().sum())
        buckets = pd.qcut(ranks, min(10, n), labels=False, duplicates="drop")
        return buckets.astype(float) + 1.0

    return series.groupby(week).transform(_decile)
