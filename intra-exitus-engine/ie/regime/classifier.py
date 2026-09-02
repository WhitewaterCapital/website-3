"""Regime classifier.

Predicts the regime label (regime/labels.py) from the PIT feature frame
(features/price.py). Model: a gradient-boosted tree
(HistGradientBoostingClassifier) — the sklearn cousin of XGBoost/LightGBM. Chosen
because it:
  * handles NaN natively (feature warm-ups need no imputation),
  * is strong and fast on tabular data, and
  * regularises cleanly (large min_samples_leaf tames financial noise).

Training is **class-weighted** (balanced sample weights) so the majority
"mean-revert" class doesn't drown out the minority "trend-down". Evaluation is
**out-of-sample only**, through the purged + embargoed walk-forward splitter, and
scored by **Cohen's kappa** (chance-corrected — a 54%-majority guesser scores ~0),
never raw accuracy.

The model exposes class *probabilities*, not just a hard label, so the level
engine downstream can gate on confidence and abstain when the top class is weak.

REVIEW FIXES (round 2, 2026-08):
  * #2 The gradient-boosted probabilities are miscalibrated, so a 0.50 gate did
    not mean "50% chance". RegimeModel now wraps the classifier in
    CalibratedClassifierCV (fit with an INTERNAL cross-validation, so calibration
    only ever sees that fold's training data — no test leakage). walk_forward_report
    additionally reports the multiclass Brier score and a reliability table
    (binned predicted-vs-observed) for the high-vol gate.
  * #5 build_dataset now asserts identical feature columns across tickers instead
    of silently overwriting the column list each iteration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    balanced_accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
)

from ..features.price import FeatureConfig, compute_features
from .labels import REGIMES, LabelConfig, make_labels


def build_dataset(
    prices_by_ticker: dict[str, pd.DataFrame],
    feat_cfg: FeatureConfig | None = None,
    label_cfg: LabelConfig | None = None,
) -> tuple[pd.DataFrame, pd.Series, pd.DatetimeIndex, np.ndarray, list[str]]:
    """Assemble the pooled training table across tickers.

    Returns (X, y, times, groups, feature_cols), row-aligned. Rows without a label
    (the unlabelable forward tail) or without full feature warm-up are dropped.
    """
    feat_cfg = feat_cfg or FeatureConfig()
    label_cfg = label_cfg or LabelConfig()
    frames = []
    feature_cols: list[str] | None = None
    for tk, df in prices_by_ticker.items():
        feats = compute_features(df, feat_cfg)
        # Fix #5: don't silently assume every ticker yields identical columns —
        # a mismatch would misalign the pooled matrix. Fail loudly instead.
        if feature_cols is None:
            feature_cols = list(feats.columns)
        elif list(feats.columns) != feature_cols:
            raise ValueError(
                f"feature columns for {tk!r} differ from the first ticker — "
                f"cannot pool a ragged feature matrix."
            )
        block = feats.copy()
        block["__label"] = make_labels(df["close"], label_cfg)["label"]
        block["__ticker"] = tk
        block["__date"] = feats.index
        frames.append(block)

    if feature_cols is None:
        raise ValueError("build_dataset requires at least one ticker")
    allf = pd.concat(frames, ignore_index=True)
    # Keep only labelled rows with a full warm-up (mom_252 present => >=252 bars).
    allf = allf[allf["__label"].notna() & allf["mom_252"].notna()].reset_index(drop=True)

    X = allf[feature_cols].copy()
    y = allf["__label"].astype("object")
    times = pd.DatetimeIndex(pd.to_datetime(allf["__date"].values))
    groups = allf["__ticker"].to_numpy()
    return X, y, times, groups, feature_cols


@dataclass
class RegimeModel:
    """A class-weighted gradient-boosted classifier over the feature frame, wrapped
    in probability calibration (fix #2), exposing hard labels and calibrated
    per-class probabilities.

    Imbalance is handled by `class_weight="balanced"` on the base estimator (so no
    sample_weight has to be routed through the calibrator). Calibration uses an
    INTERNAL cross-validation on whatever data `fit` is given, so when
    walk_forward_report calls `fit(train_fold)` the calibrator never sees test
    data."""

    learning_rate: float = 0.06
    max_iter: int = 250
    max_leaf_nodes: int = 31
    min_samples_leaf: int = 100  # heavy leaves — financial data is noisy
    l2_regularization: float = 1.0
    random_state: int = 7
    calibrate: bool = True
    calibration_method: str = "sigmoid"  # robust with limited per-class data
    calibration_cv: int = 3
    clf: object | None = field(default=None, repr=False)

    def _base(self) -> HistGradientBoostingClassifier:
        return HistGradientBoostingClassifier(
            learning_rate=self.learning_rate,
            max_iter=self.max_iter,
            max_leaf_nodes=self.max_leaf_nodes,
            min_samples_leaf=self.min_samples_leaf,
            l2_regularization=self.l2_regularization,
            early_stopping=False,  # deterministic; the walk-forward does the honest validation
            random_state=self.random_state,
            class_weight="balanced",
        )

    def fit(self, X: pd.DataFrame, y) -> "RegimeModel":
        base = self._base()
        if self.calibrate:
            # cv on the TRAINING data only => calibration is fold-internal.
            self.clf = CalibratedClassifierCV(
                base, method=self.calibration_method, cv=self.calibration_cv
            )
        else:
            self.clf = base
        self.clf.fit(X, y)
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        assert self.clf is not None, "fit first"
        return self.clf.predict(X)

    def predict_proba(self, X: pd.DataFrame) -> pd.DataFrame:
        assert self.clf is not None, "fit first"
        proba = self.clf.predict_proba(X)
        return pd.DataFrame(proba, columns=list(self.clf.classes_), index=X.index)


def walk_forward_report(
    X: pd.DataFrame,
    y: pd.Series,
    times: pd.DatetimeIndex,
    cv,
    model: RegimeModel | None = None,
) -> dict:
    """Fit fresh on each fold's train, predict its test, pool the out-of-sample
    predictions, and score. Returns a dict with overall kappa, balanced accuracy,
    per-fold kappa, and the confusion matrix (ordered by REGIMES)."""
    model = model or RegimeModel()
    y = pd.Series(y).reset_index(drop=True)
    X = X.reset_index(drop=True)

    labels = list(REGIMES)
    oof_true: list = []
    oof_pred: list = []
    oof_proba: list = []  # rows aligned to `labels`
    fold_kappa: list[float] = []

    copy_attrs = ["learning_rate", "max_iter", "max_leaf_nodes", "min_samples_leaf",
                  "l2_regularization", "random_state", "calibrate",
                  "calibration_method", "calibration_cv"]
    for train_idx, test_idx in cv.split(times):
        m = RegimeModel(**{k: getattr(model, k) for k in copy_attrs})
        m.fit(X.iloc[train_idx], y.iloc[train_idx])
        pred = m.predict(X.iloc[test_idx])
        # Calibrated probabilities, columns reindexed to a fixed REGIMES order.
        proba = m.predict_proba(X.iloc[test_idx]).reindex(columns=labels).fillna(0.0)
        truth = y.iloc[test_idx].to_numpy()
        oof_true.extend(truth.tolist())
        oof_pred.extend(pred.tolist())
        oof_proba.extend(proba.to_numpy().tolist())
        fold_kappa.append(float(cohen_kappa_score(truth, pred)))

    cm = confusion_matrix(oof_true, oof_pred, labels=labels)
    cm_df = pd.DataFrame(cm, index=[f"true:{l}" for l in labels],
                         columns=[f"pred:{l}" for l in labels])
    recall = {labels[i]: (cm[i, i] / cm[i].sum() if cm[i].sum() else float("nan"))
              for i in range(len(labels))}

    # Multiclass Brier score + a reliability table for the high-vol gate.
    P = np.asarray(oof_proba, dtype=float)
    Y = np.zeros_like(P)
    idx_of = {l: i for i, l in enumerate(labels)}
    for r, t in enumerate(oof_true):
        Y[r, idx_of[t]] = 1.0
    brier = float(np.mean(np.sum((P - Y) ** 2, axis=1)))
    reliability = _reliability_table(P[:, idx_of["high-vol"]], Y[:, idx_of["high-vol"]])

    return {
        "kappa": float(cohen_kappa_score(oof_true, oof_pred)),
        "balanced_accuracy": float(balanced_accuracy_score(oof_true, oof_pred)),
        "fold_kappa": fold_kappa,
        "n_oos": len(oof_true),
        "confusion": cm_df,
        "recall": recall,
        "brier": brier,
        "reliability_high_vol": reliability,
    }


def _reliability_table(p: np.ndarray, y: np.ndarray, n_bins: int = 5) -> list[dict]:
    """Binned predicted-vs-observed frequency for one class (a text reliability
    diagram). Well-calibrated => mean_pred ≈ obs_rate in each bin."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    out = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (p >= lo) & (p < hi) if i < n_bins - 1 else (p >= lo) & (p <= hi)
        if mask.sum() == 0:
            continue
        out.append({
            "bin": f"{lo:.1f}-{hi:.1f}",
            "mean_pred": float(p[mask].mean()),
            "obs_rate": float(y[mask].mean()),
            "n": int(mask.sum()),
        })
    return out
