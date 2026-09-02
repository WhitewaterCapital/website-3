"""Cross-sectional scoring.

The dossier's baseline: robust-z each feature across the universe, sector-
neutralize, combine with fixed weights, then convert to a percentile RANK. Ranking
(not price prediction) is the defensible target. Everything here is a pure
function over a pandas DataFrame so it is unit-testable and fully transparent.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize(s: pd.Series, limits: float = 0.02) -> pd.Series:
    if s.notna().sum() == 0:
        return s
    lo, hi = s.quantile(limits), s.quantile(1 - limits)
    return s.clip(lower=lo, upper=hi)


def robust_z(s: pd.Series) -> pd.Series:
    """(x - median) / (1.4826 * MAD). Falls back to std if MAD==0."""
    med = s.median()
    mad = (s - med).abs().median()
    scale = 1.4826 * mad
    if not scale or np.isnan(scale):
        std = s.std(ddof=0)
        scale = std if std and not np.isnan(std) else 1.0
    return (s - med) / scale


def _z_maybe_by_sector(s: pd.Series, sector: pd.Series = None) -> pd.Series:
    if sector is None:
        return robust_z(winsorize(s))
    out = pd.Series(index=s.index, dtype=float)
    for _, idx in sector.groupby(sector).groups.items():
        grp = s.loc[idx]
        out.loc[idx] = robust_z(winsorize(grp)) if grp.notna().sum() >= 5 else robust_z(winsorize(s)).loc[idx]
    return out


def composite_score(
    df: pd.DataFrame,
    feature_weights: dict,
    sector_col: str = None,
) -> pd.DataFrame:
    """`feature_weights`: {column: weight}. Use a NEGATIVE weight for features
    where 'low is good' (e.g. valuation, realized_vol, short-term reversal).
    Weights are renormalised per-row by the features actually available, so a name
    missing one feature isn't unfairly penalised. Returns df + `score` and `rank`.
    """
    sector = df[sector_col] if sector_col and sector_col in df.columns else None
    zmat = pd.DataFrame(index=df.index)
    weights = {}
    for col, w in feature_weights.items():
        if col not in df.columns:
            continue
        z = _z_maybe_by_sector(df[col], sector)
        zmat[col] = np.sign(w) * z   # signed z-score (sign encodes direction)
        weights[col] = abs(w)

    w = pd.Series(weights)
    # weighted mean of signed z-scores, normalised by the weight ACTUALLY present
    # in each row (so a name missing one feature isn't unfairly penalised).
    contrib = zmat.mul(w, axis=1)
    denom = (~zmat.isna()).mul(w, axis=1).sum(axis=1).replace(0, np.nan)
    score = contrib.sum(axis=1, min_count=1) / denom

    out = df.copy()
    out["score"] = score
    out["rank"] = score.rank(pct=True) * 100.0
    return out.sort_values("score", ascending=False)
