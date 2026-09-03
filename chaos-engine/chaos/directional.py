"""CHAOS-02 — the directional model.

====================================================================
SIMPLIFICATION, STATED PROMINENTLY: the design doc calls for a causal
dilated temporal convolutional network (TCN). This sandbox has NO deep
learning framework installed (no torch, no tensorflow) and NO network
access to install one. Rather than fake a TCN or skip CHAOS-02 entirely,
this module substitutes a calibrated gradient-boosted tree classifier
(`sklearn.ensemble.GradientBoostingClassifier`) trained on the same kind of
lagged, causal-only features a TCN's receptive field would see. This is a
STAND-IN, not an equivalent model — a TCN can learn temporal structure a
tree ensemble over hand-built lag features cannot (long-range dependencies,
learned convolutional feature interactions). Swapping in a real TCN later
should be possible without changing anything downstream: the module's public
surface (`DirectionalModel.fit`/`predict`, `probability`, `uncertainty`,
`abstain`) does not depend on the model family.
====================================================================

Everything here is causal by construction: `build_features` only ever uses
`.shift(k)` for k >= 0 relative to the prediction row, so a feature at row t
is a function of bars at or before t, never after. This is verified directly
(see tests/test_directional.py::test_no_future_leakage) by shuffling FUTURE
bars and asserting PAST predictions are unchanged.

Calibration: `CalibratedClassifierCV(..., cv="prefit")` calibrates the base
classifier's probabilities against a held-out fold the base classifier never
trained on — isotonic regression on raw gradient-boosted scores, which are
not probabilities out of the box.

Abstention: a documented confidence-band gate (`DirectionalConfig.abstain_band`,
default (0.45, 0.55)) refuses to act when the calibrated probability is too
close to a coin flip. `MetaLabelGate` is an optional, more elaborate
alternative — a second classifier learning WHEN the primary call is worth
acting on (a simplified version of meta-labelling) — provided for
completeness but not the default export path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import brier_score_loss


@dataclass(frozen=True)
class DirectionalConfig:
    n_lag_returns: int = 10
    horizon: int = 5                     # forward bars the label looks ahead
    abstain_band: tuple[float, float] = (0.45, 0.55)  # |p - 0.5| gate
    n_bagged_estimators: int = 5          # bagged ensemble for the uncertainty proxy
    calibration_holdout_frac: float = 0.3  # fraction of (post-split) data held out for calibration
    random_state: int = 7
    n_estimators: int = 100
    max_depth: int = 3
    learning_rate: float = 0.05


# ---------------------------------------------------------------------------
# Features and labels — strictly causal.
# ---------------------------------------------------------------------------


def build_features(bars: pd.DataFrame, cfg: DirectionalConfig | None = None) -> pd.DataFrame:
    """Lagged, causal-only features. `ret_lag_1` is the return ending AT row
    t (known once bar t closes); `ret_lag_k` for k>1 is that same return
    shifted (k-1) further back. No feature at row t is a function of any bar
    dated after t."""
    cfg = cfg or DirectionalConfig()
    logret = np.log(bars["close"] / bars["close"].shift(1))
    feats = {}
    for lag in range(1, cfg.n_lag_returns + 1):
        feats[f"ret_lag_{lag}"] = logret.shift(lag - 1)
    feats["vol_5"] = logret.rolling(5).std(ddof=0)
    feats["vol_20"] = logret.rolling(20).std(ddof=0)
    feats["mom_10"] = np.log(bars["close"] / bars["close"].shift(10))
    vol_roll_mean = bars["volume"].rolling(20).mean()
    vol_roll_std = bars["volume"].rolling(20).std(ddof=0)
    feats["volume_z"] = (bars["volume"] - vol_roll_mean) / vol_roll_std.replace(0.0, np.nan)
    return pd.DataFrame(feats, index=bars.index)


def make_direction_labels(bars: pd.DataFrame, horizon: int) -> pd.Series:
    """Forward direction label: 1 if close rises over the next `horizon`
    bars, 0 if it falls or is unchanged. LOOK-AHEAD, STATED PLAINLY (as in
    intra-exitus-engine/ie/regime/labels.py): this is a TRAINING TARGET and
    deliberately uses the future; the last `horizon` rows cannot be labelled
    and come back NaN. Features, by contrast, are strictly causal — see
    `build_features`. Callers must not evaluate a model on overlapping-label
    windows without accounting for the induced autocorrelation; this
    simplified module uses a single chronological split, not purged CV (see
    README "Known simplifications")."""
    fwd = np.log(bars["close"].shift(-horizon) / bars["close"])
    y = pd.Series(np.nan, index=bars.index)
    y[fwd.notna()] = (fwd[fwd.notna()] > 0).astype(float)
    return y


# ---------------------------------------------------------------------------
# Calibration helper (reused by DirectionalModel and directly unit-tested
# against a synthetic dataset with a KNOWN true probability structure).
# ---------------------------------------------------------------------------


def calibrate_classifier(
    base: GradientBoostingClassifier,
    X_cal: pd.DataFrame,
    y_cal: pd.Series,
    method: str = "isotonic",
) -> CalibratedClassifierCV:
    """Wrap an ALREADY-FITTED `base` classifier in isotonic calibration fit on
    a held-out fold — the calibration data must be disjoint from whatever
    trained `base`, or the reported probabilities would be optimistic.
    Isotonic (not Platt/sigmoid) is used because gradient-boosted scores are
    frequently non-sigmoidal-miscalibrated and isotonic makes no parametric
    assumption about the miscalibration shape.

    sklearn >= 1.6 removed `CalibratedClassifierCV(cv="prefit")` in favour of
    wrapping the fitted estimator in `sklearn.frozen.FrozenEstimator` (the
    `cv="prefit"` fallback below is kept only for older sklearn)."""
    try:
        from sklearn.frozen import FrozenEstimator

        cal = CalibratedClassifierCV(FrozenEstimator(base), method=method)
    except ImportError:  # pragma: no cover - older sklearn
        cal = CalibratedClassifierCV(base, method=method, cv="prefit")
    cal.fit(X_cal, y_cal)
    return cal


def brier_and_reliability(
    predicted_p: np.ndarray, true_p_or_outcome: np.ndarray, n_bins: int = 10
) -> dict:
    """Brier score of `predicted_p` against `true_p_or_outcome` (which may be
    the KNOWN generating probability in a synthetic test, or realised 0/1
    outcomes in a live evaluation), plus a binned reliability table."""
    predicted_p = np.asarray(predicted_p, dtype=float)
    truth = np.asarray(true_p_or_outcome, dtype=float)
    brier = float(np.mean((predicted_p - truth) ** 2))
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    table = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (predicted_p >= lo) & (predicted_p < hi) if i < n_bins - 1 else (
            (predicted_p >= lo) & (predicted_p <= hi)
        )
        if mask.sum() == 0:
            continue
        table.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "mean_pred": float(predicted_p[mask].mean()),
                "mean_true": float(truth[mask].mean()),
                "n": int(mask.sum()),
            }
        )
    mean_abs_calibration_error = (
        float(np.mean([abs(r["mean_pred"] - r["mean_true"]) for r in table])) if table else float("nan")
    )
    return {"brier": brier, "reliability": table, "mean_abs_calibration_error": mean_abs_calibration_error}


# ---------------------------------------------------------------------------
# The model.
# ---------------------------------------------------------------------------


@dataclass
class DirectionalModel:
    """Calibrated gradient-boosted directional classifier — see the module
    docstring for the honest "this is not the doc's TCN" framing.

    fit() does a single CHRONOLOGICAL split of the labelled rows into a base
    training slice and a calibration slice (the calibration slice is strictly
    LATER in time, never shuffled in), then bags `n_bagged_estimators`
    bootstrap-resampled classifiers on the training slice ONLY, whose
    predict_proba spread is the uncertainty proxy (a stand-in for a real
    predictive-quantile head)."""

    cfg: DirectionalConfig = field(default_factory=DirectionalConfig)
    _feature_cols: list[str] = field(default_factory=list, repr=False)
    _calibrated: object = field(default=None, repr=False)
    _bagged: list = field(default_factory=list, repr=False)
    _fitted: bool = False

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "DirectionalModel":
        mask = X.notna().all(axis=1) & y.notna()
        Xc = X.loc[mask]
        yc = y.loc[mask].astype(int)
        n = len(Xc)
        if n < 40:
            raise ValueError("need at least 40 labelled, fully-featured rows to fit")

        split = int(n * (1.0 - self.cfg.calibration_holdout_frac))
        split = max(20, min(split, n - 10))  # leave a real calibration fold
        X_train, y_train = Xc.iloc[:split], yc.iloc[:split]
        X_cal, y_cal = Xc.iloc[split:], yc.iloc[split:]

        base = GradientBoostingClassifier(
            n_estimators=self.cfg.n_estimators,
            max_depth=self.cfg.max_depth,
            learning_rate=self.cfg.learning_rate,
            random_state=self.cfg.random_state,
        )
        base.fit(X_train, y_train)
        self._calibrated = calibrate_classifier(base, X_cal, y_cal, method="isotonic")

        rng = np.random.default_rng(self.cfg.random_state)
        self._bagged = []
        for k in range(self.cfg.n_bagged_estimators):
            boot_idx = rng.integers(0, len(X_train), len(X_train))
            m = GradientBoostingClassifier(
                n_estimators=self.cfg.n_estimators,
                max_depth=self.cfg.max_depth,
                learning_rate=self.cfg.learning_rate,
                random_state=self.cfg.random_state + k + 1,
            )
            m.fit(X_train.iloc[boot_idx], y_train.iloc[boot_idx])
            self._bagged.append(m)

        self._feature_cols = list(X.columns)
        self._fitted = True
        return self

    def _valid_rows(self, X: pd.DataFrame) -> pd.Series:
        return X[self._feature_cols].notna().all(axis=1)

    def probability(self, X: pd.DataFrame) -> pd.Series:
        """Calibrated P(up over the horizon). NaN where features are not
        fully warmed up — never a guessed 0.5."""
        assert self._fitted, "fit() first"
        valid = self._valid_rows(X)
        out = pd.Series(np.nan, index=X.index)
        if valid.any():
            p = self._calibrated.predict_proba(X.loc[valid, self._feature_cols])[:, 1]
            out.loc[valid] = p
        return out

    def uncertainty(self, X: pd.DataFrame) -> pd.Series:
        """Spread (std) of predict_proba across the bagged ensemble — a
        simple, honest uncertainty proxy in place of a real predictive
        quantile/interval from a probabilistic model."""
        assert self._fitted, "fit() first"
        valid = self._valid_rows(X)
        out = pd.Series(np.nan, index=X.index)
        if valid.any():
            Xv = X.loc[valid, self._feature_cols]
            preds = np.column_stack([m.predict_proba(Xv)[:, 1] for m in self._bagged])
            out.loc[valid] = preds.std(axis=1)
        return out

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        """Returns a frame with `probability`, `uncertainty`, and `abstain`
        (True when the calibrated probability falls inside
        `cfg.abstain_band`, OR when features are not warmed up)."""
        p = self.probability(X)
        u = self.uncertainty(X)
        lo, hi = self.cfg.abstain_band
        abstain = p.isna() | ((p >= lo) & (p <= hi))
        return pd.DataFrame({"probability": p, "uncertainty": u, "abstain": abstain})


# ---------------------------------------------------------------------------
# Optional alternative abstention gate: a simplified meta-labelling classifier
# (cf. Lopez de Prado's meta-labelling — a second model learns WHEN to trust
# the first, not WHAT direction to call). Not wired into the default export
# path; provided as a documented, tested alternative to the confidence band.
# ---------------------------------------------------------------------------


@dataclass
class MetaLabelGate:
    random_state: int = 11
    n_estimators: int = 100
    max_depth: int = 3
    _clf: object = field(default=None, repr=False)
    _feature_cols: list[str] = field(default_factory=list, repr=False)

    def fit(self, X: pd.DataFrame, primary_proba: pd.Series, y_true: pd.Series) -> "MetaLabelGate":
        """Trains on rows where the primary model made a call (primary_proba
        not NaN) and the true label is known. Target: was the primary call
        correct? (1 = primary's implied direction matched the realised
        outcome, 0 = it did not)."""
        mask = primary_proba.notna() & y_true.notna()
        Xc = X.loc[mask].copy()
        Xc["_primary_proba"] = primary_proba.loc[mask]
        primary_dir = (primary_proba.loc[mask] >= 0.5).astype(int)
        target = (primary_dir == y_true.loc[mask].astype(int)).astype(int)
        self._feature_cols = list(Xc.columns)
        self._clf = GradientBoostingClassifier(
            n_estimators=self.n_estimators, max_depth=self.max_depth, random_state=self.random_state
        )
        self._clf.fit(Xc, target)
        return self

    def act(self, X: pd.DataFrame, primary_proba: pd.Series, threshold: float = 0.5) -> pd.Series:
        """Returns a boolean Series: True = act on the primary call, False =
        abstain. Rows without a primary probability always abstain."""
        assert self._clf is not None, "fit() first"
        out = pd.Series(False, index=X.index)
        valid = primary_proba.notna()
        if not valid.any():
            return out
        Xc = X.loc[valid].copy()
        Xc["_primary_proba"] = primary_proba.loc[valid]
        Xc = Xc[self._feature_cols]
        p_correct = self._clf.predict_proba(Xc)[:, 1]
        out.loc[valid] = p_correct >= threshold
        return out
