"""Ridge regression on ranked features — the MANDATORY baseline.

Spec: "ridge regression on ranked features as the mandatory baseline, refit
per walk-forward fold." Two design choices worth being explicit about:

  * **Ranked, not raw, features.** Ridge is a linear model in feature space,
    so a single outlier week in a raw feature (an earnings gap, a halt) would
    dominate the fit, and raw feature *scale* differs by name (price level,
    vol regime) in ways that have nothing to do with signal. Cross-sectional
    percentile-ranking every feature to [0,1] within its own week removes
    both problems using only that week's own cross-section — no leakage risk
    relative to fitting a scaler on the training split, because it is a
    per-row transform, not a fitted one.
  * **Refit per fold.** A single ridge fit over the whole history would let
    the coefficients quietly drift to fit later regimes using earlier-regime
    weights; refitting fresh inside every walk-forward fold (train on that
    fold's past only) is what makes the reported IC an honest walk-forward
    number rather than an in-sample one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from ..features.cross_sectional import cross_sectional_rank

DEFAULT_ALPHA = 5.0
NEUTRAL_RANK = 0.5  # a feature missing for a name/week is treated as "typical", not zero


def rank_transform_features(panel: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    """Cross-sectional percentile-rank every column in `feature_cols`, within
    its own week, aligned to `panel`'s index. NaNs (missing feature, e.g.
    during a name's warm-up) become NEUTRAL_RANK rather than being dropped,
    so a fold doesn't lose rows just because one feature warmed up late."""
    ranked = pd.DataFrame(index=panel.index)
    for c in feature_cols:
        ranked[c] = cross_sectional_rank(panel, c, group_cols=("week",)).fillna(NEUTRAL_RANK)
    return ranked


def fit_ridge(X_train: np.ndarray, y_train: np.ndarray, alpha: float = DEFAULT_ALPHA) -> Ridge:
    """Fit a fresh Ridge model. `X_train` is expected already rank-transformed
    (see rank_transform_features) and NaN-free; `y_train` may not contain NaN."""
    model = Ridge(alpha=alpha)
    model.fit(X_train, y_train)
    return model


def predict_ridge(model: Ridge, X: np.ndarray) -> np.ndarray:
    return model.predict(X)
