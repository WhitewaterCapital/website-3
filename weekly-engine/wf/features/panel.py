"""Assembles the long-format cross-sectional feature+label panel.

One row per (ticker, week). Pipeline:
  1. `prepare_base` turns each ticker's weekly OHLCV frame into the minimal
     (close, volume, ret) frame every feature function reads.
  2. Every @feature-registered function runs per ticker -> the raw per-ticker
     feature block.
  3. Labels (labels.py::compute_labels) are attached per ticker.
  4. Frames are stacked into one long panel, tagged with `ticker`/`sector`/`week`.
  5. Cross-sectional derived columns are added on the STACKED panel (they
     need the whole week's cross-section): `ret_lag_k_xrank` for every lagged
     return, `{col}_sector_z` for every technical feature, and the
     sector-relative label.
  6. `assert_no_lookahead` runs before returning — this function is the one
     place look-ahead could sneak in silently, so it is checked here, not
     left to callers to remember.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..labels import assert_no_lookahead, compute_labels
from .cross_sectional import cross_sectional_rank, cross_sectional_zscore
from .registry import FEATURE_REGISTRY, base_manifest, manifest_hash
from .returns import RET_LAG_COLUMNS
from .technical import TECHNICAL_COLUMNS

REQUIRED_COLUMNS = {"close", "volume"}


def prepare_base(df: pd.DataFrame) -> pd.DataFrame:
    """Validate and derive the minimal (close, volume, ret) frame every
    feature function reads. `df` must be a weekly-resampled OHLCV frame,
    ascending, unique DatetimeIndex, with at least close/volume columns."""
    if not REQUIRED_COLUMNS.issubset(df.columns):
        missing = REQUIRED_COLUMNS - set(df.columns)
        raise ValueError(f"weekly price frame missing required columns: {sorted(missing)}")
    if not df.index.is_monotonic_increasing:
        raise ValueError("weekly price frame must be sorted ascending by date")
    if df.index.has_duplicates:
        raise ValueError("weekly price frame has duplicate dates")
    base = pd.DataFrame(index=df.index)
    base["close"] = df["close"].astype(float)
    base["volume"] = df["volume"].astype(float)
    base["ret"] = base["close"].pct_change()
    return base


def _sector_relative_zscore_with_fallback(panel: pd.DataFrame, col: str) -> pd.Series:
    """Sector z-score of `col`, falling back to a universe-wide (week-only)
    z-score wherever the sector group that week is too thin to standardize
    against (see cross_sectional.MIN_GROUP_SIZE_FOR_ZSCORE)."""
    sector_z = cross_sectional_zscore(panel, col, group_cols=("week", "sector"))
    needs_fallback = sector_z.isna() & panel[col].notna()
    if needs_fallback.any():
        universe_z = cross_sectional_zscore(panel, col, group_cols=("week",))
        sector_z = sector_z.where(~needs_fallback, universe_z)
    return sector_z


def build_feature_panel(
    weekly_prices: dict[str, pd.DataFrame],
    sector_map: dict[str, str],
) -> tuple[pd.DataFrame, list[str], list[dict]]:
    """Build the full long-format panel.

    Returns (panel, feature_columns, feature_manifest):
      - panel: one row per (ticker, week); columns = feature_columns +
        ticker/sector/week/fwd_return/sector_relative_fwd_return/label_knowable_from.
      - feature_columns: every column the model is allowed to train on (raw
        per-ticker features + ret_lag_*_xrank + *_sector_z).
      - feature_manifest: list of {name, version, lookback_weeks} dicts,
        including the derived cross-sectional columns (version tags the
        transform, not a re-derivation of the base feature's own version).
    """
    frames = []
    for ticker, df in weekly_prices.items():
        base = prepare_base(df)
        feat = pd.DataFrame(index=base.index)
        for spec in FEATURE_REGISTRY:
            feat[spec.name] = spec.fn(base)
        feat["ticker"] = ticker
        feat["sector"] = sector_map.get(ticker, "UNKNOWN")
        feat["week"] = feat.index
        lab = compute_labels(base)
        feat = feat.join(lab)
        frames.append(feat.reset_index(drop=True))

    panel = pd.concat(frames, axis=0, ignore_index=True)

    # --- cross-sectional derived columns ------------------------------------
    for col in RET_LAG_COLUMNS:
        panel[f"{col}_xrank"] = cross_sectional_rank(panel, col, group_cols=("week",))

    for col in TECHNICAL_COLUMNS:
        panel[f"{col}_sector_z"] = _sector_relative_zscore_with_fallback(panel, col)

    # Sector-relative label: this week's forward return minus that week's
    # cross-sectional sector-mean forward return. NaN sector means (a lone
    # member that week) fall back to the universe-wide mean forward return,
    # same fallback logic as the feature z-scores above.
    sector_mean = panel.groupby(["week", "sector"])["fwd_return"].transform("mean")
    sector_size = panel.groupby(["week", "sector"])["fwd_return"].transform("size")
    universe_mean = panel.groupby("week")["fwd_return"].transform("mean")
    baseline = sector_mean.where(sector_size >= 2, universe_mean)
    panel["sector_relative_fwd_return"] = panel["fwd_return"] - baseline

    feature_columns = (
        [s.name for s in FEATURE_REGISTRY]
        + [f"{c}_xrank" for c in RET_LAG_COLUMNS]
        + [f"{c}_sector_z" for c in TECHNICAL_COLUMNS]
    )

    manifest = list(base_manifest())
    for c in RET_LAG_COLUMNS:
        manifest.append({"name": f"{c}_xrank", "version": "xs-rank-1.0", "lookback_weeks": 0})
    for c in TECHNICAL_COLUMNS:
        manifest.append({"name": f"{c}_sector_z", "version": "xs-zscore-1.0", "lookback_weeks": 0})

    panel = panel.sort_values(["week", "ticker"]).reset_index(drop=True)
    assert_no_lookahead(panel)

    return panel, feature_columns, manifest


def feature_manifest_hash(manifest: list[dict]) -> str:
    return manifest_hash(manifest)
