"""WW-CASCADE — transmission of estimated pressure into realised return.

The doc: "regress realised constituent return against estimated pressure,
controlling for the name's own news/sector move." This module fits

    realised_return_i = intercept + beta * pressure_i + sum_k gamma_k * control_{i,k} + eps_i

via OLS (`sklearn.linear_model.LinearRegression`) and reports `beta` — the
"transmission coefficient": how much of a unit of pressure (as defined in
`pressure.py`, a fraction of a day's typical volume) shows up in same-day
realised return once the name's own news/sector move is netted out.

This module makes no claim of correctness beyond "OLS recovers a known
linear coefficient from synthetic data" — see
`quant-infra/cascade/tests/test_transmission.py`, which generates returns
FROM a chosen true coefficient plus noise and asserts the fit recovers it
within a documented tolerance. Feeding it real, live pressure/return data is
future work; the math here is what will run once that data exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from sklearn.linear_model import LinearRegression


@dataclass(frozen=True)
class TransmissionResult:
    coefficient: float                     # fitted beta on pressure
    intercept: float
    control_coefficients: dict[str, float]  # fitted gamma_k, by control name
    r_squared: float
    n_obs: int
    std_error: float | None                # OLS std error of beta, or None if not computable


def fit_transmission(
    pressure: np.ndarray,
    realized_return: np.ndarray,
    controls: Mapping[str, np.ndarray] | None = None,
) -> TransmissionResult:
    """Fit the transmission coefficient of pressure into realised return.

    Rows with a NaN in `pressure`, `realized_return`, or any control are
    dropped before fitting (pairwise-complete would leak information across
    mismatched rows, so we require row-complete cases).

    Edge cases, all explicit rather than raising an obscure linalg error:
      - fewer complete rows than (1 + n_controls + 1) [need at least one
        residual degree of freedom] -> all-NaN result, n_obs reported.
      - zero-variance pressure (every value identical) -> coefficient is
        undefined (collinear with the intercept) -> NaN, not a fabricated 0.
    """
    controls = controls or {}
    control_names = list(controls.keys())

    p = np.asarray(pressure, dtype=float)
    y = np.asarray(realized_return, dtype=float)
    if p.shape != y.shape:
        raise ValueError("pressure and realized_return must have the same shape")

    control_arrays = []
    for name in control_names:
        c = np.asarray(controls[name], dtype=float)
        if c.shape != p.shape:
            raise ValueError(f"control {name!r} must have the same shape as pressure")
        control_arrays.append(c)

    n_features = 1 + len(control_names)
    stack = [p, y] + control_arrays
    mask = np.ones(p.shape, dtype=bool)
    for arr in stack:
        mask &= ~np.isnan(arr)

    n_obs = int(mask.sum())
    min_required = n_features + 2  # +1 for intercept, +1 residual dof
    if n_obs < min_required:
        return TransmissionResult(
            coefficient=float("nan"),
            intercept=float("nan"),
            control_coefficients={name: float("nan") for name in control_names},
            r_squared=float("nan"),
            n_obs=n_obs,
            std_error=None,
        )

    p_c = p[mask]
    y_c = y[mask]
    if np.std(p_c) == 0:
        return TransmissionResult(
            coefficient=float("nan"),
            intercept=float(np.mean(y_c)),
            control_coefficients={name: float("nan") for name in control_names},
            r_squared=float("nan"),
            n_obs=n_obs,
            std_error=None,
        )

    X_cols = [p_c] + [c[mask] for c in control_arrays]
    X = np.column_stack(X_cols)

    model = LinearRegression()
    model.fit(X, y_c)
    beta = float(model.coef_[0])
    gammas = {name: float(model.coef_[1 + i]) for i, name in enumerate(control_names)}
    r2 = float(model.score(X, y_c))

    std_error = _beta_std_error(X, y_c, model)

    return TransmissionResult(
        coefficient=beta,
        intercept=float(model.intercept_),
        control_coefficients=gammas,
        r_squared=r2,
        n_obs=n_obs,
        std_error=std_error,
    )


def _beta_std_error(X: np.ndarray, y: np.ndarray, model: LinearRegression) -> float | None:
    """Classical OLS standard error of the FIRST coefficient (pressure's beta)."""
    n, k = X.shape
    dof = n - k - 1  # minus intercept
    if dof <= 0:
        return None
    design = np.column_stack([np.ones(n), X])
    pred = model.predict(X)
    resid = y - pred
    sigma2 = float(np.sum(resid ** 2) / dof)
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        return None
    var_beta = sigma2 * xtx_inv[1, 1]  # index 1 = first real feature (pressure), after intercept
    if var_beta < 0:
        return None
    return float(np.sqrt(var_beta))
