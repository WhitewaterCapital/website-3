"""Gradient-boosted trees, depth/leaf-constrained hard for a low-signal problem.

Weekly equity returns are close to unpredictable (spec: a sustained OOS rank
IC of 0.02-0.05 is "genuinely good"). A tree ensemble with any real capacity
will happily carve the training set into leaves that fit its noise, not its
(tiny) signal, and then show a beautiful in-sample fit and a useless
out-of-sample one. So every knob here is set to under-fit rather than
over-fit relative to what a normal tabular-ML default would use:

  * `max_depth=3`        — at most 3 splits per tree; no room to memorize
    interaction-specific noise in a 40-ish-feature, weekly-cadence, few-year
    dataset.
  * `max_leaf_nodes=8`   — belt-and-suspenders on top of max_depth: caps
    total tree complexity directly, independent of how splits happen to fall.
  * `min_samples_leaf=50` — a leaf must average over at least 50 (ticker,
    week) rows before it is allowed to make a distinct prediction; this is
    the single biggest lever against fitting single-name idiosyncratic noise.
  * `learning_rate=0.03`, `max_iter=200` — slow learning with many small
    steps (rather than few large ones) is itself a regularizer (shrinkage),
    and early_stopping is left on so it doesn't even use every iteration if
    the validation loss stops improving.
  * `l2_regularization=1.0` — explicit L2 shrinkage on the leaf values.

`HistGradientBoostingRegressor` is used (not the older `GradientBoostingRegressor`)
for its native missing-value support (a feature's warm-up NaN is passed straight
through rather than needing an explicit imputation step, and the model learns a
direction to send missing values rather than an arbitrary imputed value biasing
the split).
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

GBM_PARAMS: dict = dict(
    loss="squared_error",
    max_depth=3,
    max_leaf_nodes=8,
    min_samples_leaf=50,
    learning_rate=0.03,
    max_iter=200,
    l2_regularization=1.0,
    early_stopping=True,
    validation_fraction=0.15,
    n_iter_no_change=15,
    random_state=13,
)


def fit_gbm(X_train: np.ndarray, y_train: np.ndarray, params: dict | None = None) -> HistGradientBoostingRegressor:
    """Fit a fresh, hard-constrained HistGradientBoostingRegressor. X_train may
    contain NaN (native missing-value support); y_train may not."""
    p = dict(GBM_PARAMS)
    if params:
        p.update(params)
    model = HistGradientBoostingRegressor(**p)
    model.fit(X_train, y_train)
    return model


def predict_gbm(model: HistGradientBoostingRegressor, X: np.ndarray) -> np.ndarray:
    return model.predict(X)
