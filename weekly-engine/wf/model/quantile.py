"""Quantile heads: p10 / p50 / p90 of next week's (sector-relative) return.

Checked against the installed sklearn (1.8.0, see requirements.txt):
`HistGradientBoostingRegressor(loss="quantile", quantile=alpha)` is natively
supported (unlike `GradientBoostingRegressor`, which needs `loss="quantile",
alpha=...` and a separate model per quantile with a different constructor
signature) — so this uses HistGradientBoostingRegressor, one fit per
quantile, sharing the same hard depth/leaf constraints as model/gbm.py's
point forecast (see that module's docstring for why they are set this
conservative). Three independent fits mean p10 <= p50 <= p90 is NOT
guaranteed algebraically; `sort_quantiles` below enforces it post-hoc
(pinball loss minimization doesn't promise monotonicity across separately
fit models, so the report must not either).
"""

from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from .gbm import GBM_PARAMS

QUANTILES = (0.1, 0.5, 0.9)


def fit_quantile_models(
    X_train: np.ndarray, y_train: np.ndarray, quantiles: tuple[float, ...] = QUANTILES
) -> dict[float, HistGradientBoostingRegressor]:
    """One HistGradientBoostingRegressor per quantile, same depth/leaf caps
    as the point-forecast GBM (see model/gbm.py::GBM_PARAMS)."""
    models: dict[float, HistGradientBoostingRegressor] = {}
    for q in quantiles:
        params = dict(GBM_PARAMS)
        params.pop("loss", None)
        params["loss"] = "quantile"
        params["quantile"] = q
        model = HistGradientBoostingRegressor(**params)
        model.fit(X_train, y_train)
        models[q] = model
    return models


def predict_quantiles(
    models: dict[float, HistGradientBoostingRegressor], X: np.ndarray, quantiles: tuple[float, ...] = QUANTILES
) -> dict[float, np.ndarray]:
    return {q: models[q].predict(X) for q in quantiles}


def sort_quantiles(preds: dict[float, np.ndarray], quantiles: tuple[float, ...] = QUANTILES) -> dict[float, np.ndarray]:
    """Enforce p10 <= p50 <= p90 row-wise. Three independently fit quantile
    models have no algebraic guarantee of monotonicity (each minimizes its
    own pinball loss); a raw crossing (p10 > p50, say) would render the band
    nonsensical downstream, so this sorts each row's predictions across
    quantiles rather than trusting the fits to agree."""
    stacked = np.vstack([preds[q] for q in sorted(quantiles)])
    stacked_sorted = np.sort(stacked, axis=0)
    return {q: stacked_sorted[i] for i, q in enumerate(sorted(quantiles))}
