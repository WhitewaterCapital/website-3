"""Walk-forward validation harness.

Runs purged, embargoed walk-forward CV (splits.py) over the feature panel,
refitting the ridge baseline (model/ridge.py) and the constrained GBM
(model/gbm.py) fresh in every fold, and reports the metrics the spec asks
for: rank IC, decile spread, hit rate, turnover, and deflated Sharpe.

The one rule this module exists to enforce mechanically, not just narrate:
**GBM is only reported as "beats baseline" when it genuinely, repeatedly
does** — never on a single lucky fold, and never just because its mean IC
edges out ridge's by a hair. `_gbm_beats_baseline` requires (a) at least
`MIN_FOLDS_FOR_VERDICT` folds with both models scored, (b) GBM's mean rank IC
strictly above ridge's, (c) GBM's mean rank IC itself positive (showing
genuine skill, not just "less bad" than a baseline with none), and (d) GBM
beating ridge in a real majority of individual folds — not just on average.
tests/test_validation_harness.py proves this both ways: a fixture with an
embedded (weak, deliberately GBM-shaped) signal should trip the verdict, and
a fixture with NO signal must not, however the numbers happen to jitter.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..model.gbm import fit_gbm, predict_gbm
from ..model.ridge import fit_ridge, predict_ridge, rank_transform_features
from .metrics import (
    decile_spread,
    deflated_sharpe_ratio,
    hit_rate,
    rank_ic,
    sharpe_of_returns,
    turnover,
)
from .splits import PurgedWalkForwardCV

MIN_FOLDS_FOR_VERDICT = 3
# Spec: "a rank IC of 0.02 to 0.05 sustained out of sample is a genuinely
# good result" for this problem. A GBM mean rank IC below that floor, or an
# edge over ridge smaller than this margin, is not distinguishable from
# fold-to-fold noise — see tests/test_validation_harness.py's no-signal
# fixture, which without these floors produces an occasional false "win"
# from pure noise alone (verified empirically while calibrating this module).
MIN_MEANINGFUL_RANK_IC = 0.02
MIN_MEANINGFUL_MARGIN = 0.02


@dataclass
class FoldMetrics:
    fold: int
    test_start: str
    test_end: str
    n_test: int
    ridge_rank_ic: float
    gbm_rank_ic: float
    ridge_hit_rate: float
    gbm_hit_rate: float
    ridge_decile_spread: float
    gbm_decile_spread: float


@dataclass
class WalkForwardReport:
    n_folds: int
    folds: list[FoldMetrics] = field(default_factory=list)
    ridge_mean_rank_ic: float = float("nan")
    gbm_mean_rank_ic: float = float("nan")
    ridge_mean_hit_rate: float = float("nan")
    gbm_mean_hit_rate: float = float("nan")
    ridge_mean_decile_spread: float = float("nan")
    gbm_mean_decile_spread: float = float("nan")
    ridge_turnover: float = float("nan")
    gbm_turnover: float = float("nan")
    ridge_deflated_sharpe: float = float("nan")
    gbm_deflated_sharpe: float = float("nan")
    gbm_wins: int = 0
    gbm_beats_baseline: bool = False
    gbm_beats_baseline_reason: str = ""
    predictions: pd.DataFrame | None = None


def _fold_predictions(panel, feature_cols, label_col, train_idx, test_idx):
    train = panel.iloc[train_idx]
    test = panel.iloc[test_idx]
    train_ok = train[label_col].notna()
    test_ok = test[label_col].notna()
    train, test = train[train_ok], test[test_ok]
    if len(train) < 20 or len(test) < 5:
        return None

    # --- ridge, on rank-transformed features (fit fresh, this fold only) ---
    ranked_all = rank_transform_features(panel, feature_cols)
    X_train_r = ranked_all.loc[train.index].to_numpy(dtype=float)
    X_test_r = ranked_all.loc[test.index].to_numpy(dtype=float)
    y_train = train[label_col].to_numpy(dtype=float)
    ridge_model = fit_ridge(X_train_r, y_train)
    ridge_pred = predict_ridge(ridge_model, X_test_r)

    # --- GBM, on raw features (native NaN handling; fit fresh, this fold) --
    X_train_raw = train[feature_cols].to_numpy(dtype=float)
    X_test_raw = test[feature_cols].to_numpy(dtype=float)
    gbm_model = fit_gbm(X_train_raw, y_train)
    gbm_pred = predict_gbm(gbm_model, X_test_raw)

    out = pd.DataFrame(
        {
            "week": test["week"].values,
            "ticker": test["ticker"].values,
            "actual": test[label_col].to_numpy(dtype=float),
            "ridge_pred": ridge_pred,
            "gbm_pred": gbm_pred,
        }
    )
    return out


def _turnover_over_time(preds: pd.DataFrame, pred_col: str) -> float:
    """Mean week-over-week rank turnover of `pred_col`'s cross-sectional
    ranking, across every consecutive pair of weeks present in `preds`."""
    weeks = sorted(preds["week"].unique())
    if len(weeks) < 2:
        return float("nan")
    gaps = []
    prev_ranks = None
    prev_week = None
    for w in weeks:
        wk = preds[preds["week"] == w]
        ranks = wk.set_index("ticker")[pred_col].rank(pct=True)
        if prev_ranks is not None:
            gaps.append(turnover(prev_ranks, ranks))
        prev_ranks, prev_week = ranks, w
    gaps = [g for g in gaps if not math.isnan(g)]
    return float(np.mean(gaps)) if gaps else float("nan")


def _decile_spread_return_series(preds: pd.DataFrame, pred_col: str) -> np.ndarray:
    """One return per week: mean actual outcome of the top decile of
    `pred_col` minus the bottom decile, that week — the return series a
    simple long-top/short-bottom book would have realized. Feeds Sharpe /
    deflated Sharpe."""
    out = []
    for _, wk in preds.groupby("week"):
        s = decile_spread(wk[pred_col].to_numpy(dtype=float), wk["actual"].to_numpy(dtype=float))
        if not math.isnan(s):
            out.append(s)
    return np.asarray(out, dtype=float)


def _gbm_beats_baseline(folds: list[FoldMetrics], ridge_mean: float, gbm_mean: float) -> tuple[bool, str]:
    scored = [f for f in folds if not (math.isnan(f.ridge_rank_ic) or math.isnan(f.gbm_rank_ic))]
    if len(scored) < MIN_FOLDS_FOR_VERDICT:
        return False, f"only {len(scored)} fold(s) had both models scored (< {MIN_FOLDS_FOR_VERDICT} required)"
    wins = sum(1 for f in scored if f.gbm_rank_ic > f.ridge_rank_ic)
    majority_needed = len(scored) // 2 + 1
    if math.isnan(gbm_mean) or gbm_mean < MIN_MEANINGFUL_RANK_IC:
        return False, (
            f"GBM mean rank IC ({gbm_mean:.4f}) is below the materiality floor "
            f"({MIN_MEANINGFUL_RANK_IC}) — not distinguishable from noise even if nominally positive"
        )
    if not (gbm_mean - ridge_mean >= MIN_MEANINGFUL_MARGIN):
        return False, (
            f"GBM's edge over ridge ({gbm_mean - ridge_mean:.4f}) is below the materiality margin "
            f"({MIN_MEANINGFUL_MARGIN}) — too small to call a genuine win versus fold-to-fold noise"
        )
    if wins < majority_needed:
        return False, f"GBM only beat ridge in {wins}/{len(scored)} folds (need a majority)"
    return True, f"GBM beat ridge in {wins}/{len(scored)} folds; mean rank IC {gbm_mean:.4f} > {ridge_mean:.4f}"


def run_walk_forward(
    panel: pd.DataFrame,
    feature_cols: list[str],
    label_col: str = "sector_relative_fwd_return",
    n_splits: int = 5,
    horizon: int = 1,
    embargo: int = 1,
    min_train: int = 100,
) -> WalkForwardReport:
    """Run purged walk-forward CV over `panel`, refit ridge + GBM each fold,
    and return the aggregate report described in the module docstring."""
    cv = PurgedWalkForwardCV(n_splits=n_splits, horizon=horizon, embargo=embargo, min_train=min_train)
    fold_ranges = cv.fold_date_ranges(panel["week"].to_numpy())
    all_preds = []
    folds: list[FoldMetrics] = []

    for i, (train_idx, test_idx) in enumerate(cv.split(panel["week"].to_numpy())):
        fp = _fold_predictions(panel, feature_cols, label_col, train_idx, test_idx)
        rng = fold_ranges[i]
        if fp is None or fp.empty:
            continue
        all_preds.append(fp.assign(fold=i))
        folds.append(
            FoldMetrics(
                fold=i,
                test_start=str(rng["test_start"]),
                test_end=str(rng["test_end"]),
                n_test=len(fp),
                ridge_rank_ic=rank_ic(fp["ridge_pred"], fp["actual"]),
                gbm_rank_ic=rank_ic(fp["gbm_pred"], fp["actual"]),
                ridge_hit_rate=hit_rate(fp["ridge_pred"], fp["actual"]),
                gbm_hit_rate=hit_rate(fp["gbm_pred"], fp["actual"]),
                ridge_decile_spread=decile_spread(fp["ridge_pred"].to_numpy(), fp["actual"].to_numpy()),
                gbm_decile_spread=decile_spread(fp["gbm_pred"].to_numpy(), fp["actual"].to_numpy()),
            )
        )

    report = WalkForwardReport(n_folds=len(folds), folds=folds)
    if not folds:
        report.gbm_beats_baseline_reason = "no folds produced usable predictions"
        return report

    def _mean(attr):
        vals = [getattr(f, attr) for f in folds if not math.isnan(getattr(f, attr))]
        return float(np.mean(vals)) if vals else float("nan")

    report.ridge_mean_rank_ic = _mean("ridge_rank_ic")
    report.gbm_mean_rank_ic = _mean("gbm_rank_ic")
    report.ridge_mean_hit_rate = _mean("ridge_hit_rate")
    report.gbm_mean_hit_rate = _mean("gbm_hit_rate")
    report.ridge_mean_decile_spread = _mean("ridge_decile_spread")
    report.gbm_mean_decile_spread = _mean("gbm_decile_spread")

    preds = pd.concat(all_preds, axis=0, ignore_index=True) if all_preds else pd.DataFrame()
    report.predictions = preds
    if not preds.empty:
        report.ridge_turnover = _turnover_over_time(preds, "ridge_pred")
        report.gbm_turnover = _turnover_over_time(preds, "gbm_pred")

        ridge_returns = _decile_spread_return_series(preds, "ridge_pred")
        gbm_returns = _decile_spread_return_series(preds, "gbm_pred")
        if ridge_returns.size >= 4:
            sr = sharpe_of_returns(ridge_returns) / math.sqrt(52.0)  # de-annualize to per-observation
            report.ridge_deflated_sharpe = deflated_sharpe_ratio(sr, ridge_returns.size, n_trials=1, sr_variance_across_trials=0.0)
        if gbm_returns.size >= 4:
            sr = sharpe_of_returns(gbm_returns) / math.sqrt(52.0)
            report.gbm_deflated_sharpe = deflated_sharpe_ratio(sr, gbm_returns.size, n_trials=1, sr_variance_across_trials=0.0)

    report.gbm_wins = sum(
        1 for f in folds if not (math.isnan(f.ridge_rank_ic) or math.isnan(f.gbm_rank_ic)) and f.gbm_rank_ic > f.ridge_rank_ic
    )
    report.gbm_beats_baseline, report.gbm_beats_baseline_reason = _gbm_beats_baseline(
        folds, report.ridge_mean_rank_ic, report.gbm_mean_rank_ic
    )
    return report
