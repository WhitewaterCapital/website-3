"""WW-CASCADE — permanent vs temporary pressure decomposition.

The doc asks to "split pressure into permanent vs temporary by fitting how
much of the move persists at various horizons." The model fitted here is the
standard price-impact decay curve:

    impact(h) = permanent + temporary * exp(-decay_rate * h)

`impact(h)` is the realised (pressure-attributable) return measured `h`
periods after the flow event. As `h -> infinity`, `impact -> permanent`: the
part of the move that never reverts (the market's genuinely repriced the
name). `temporary` is the extra move present at `h=0` that decays away —
mechanical, reversible price pressure. `decay_rate` sets how fast it reverts;
`1/decay_rate` is the (approximate) half-life-like time constant of the
temporary component (its true half-life is `ln(2)/decay_rate`).

Fit via `scipy.optimize.curve_fit` (nonlinear least squares), with
`decay_rate` constrained to be non-negative — pressure that persists forever
without decaying is exactly the definition of "permanent", not a negative
decay rate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit


@dataclass(frozen=True)
class DecomposeResult:
    permanent: float       # asymptotic floor as h -> infinity
    temporary: float       # extra impact at h=0 that decays away
    decay_rate: float      # per-horizon-unit decay constant (>= 0)
    r_squared: float
    n_obs: int
    converged: bool         # False => all other fields are NaN except n_obs


def _impact_curve(h: np.ndarray, permanent: float, temporary: float, decay_rate: float) -> np.ndarray:
    return permanent + temporary * np.exp(-decay_rate * h)


def decompose_pressure_impact(
    horizons: np.ndarray,
    impact: np.ndarray,
    initial_guess: tuple[float, float, float] | None = None,
) -> DecomposeResult:
    """Fit `impact(h) = permanent + temporary * exp(-decay_rate * h)`.

    Rows with a NaN in either array are dropped. Requires at least 4
    complete (horizon, impact) pairs (3 free parameters + 1 residual dof) —
    fewer than that returns `converged=False` rather than an overfit or a
    solver exception. A fit that raises inside `curve_fit` (non-convergence,
    singular Jacobian) is caught and reported the same way: `converged=False`,
    every numeric field NaN, `n_obs` still populated so the caller can see
    why it failed.
    """
    h = np.asarray(horizons, dtype=float)
    y = np.asarray(impact, dtype=float)
    if h.shape != y.shape:
        raise ValueError("horizons and impact must have the same shape")

    mask = ~(np.isnan(h) | np.isnan(y))
    h_c, y_c = h[mask], y[mask]
    n_obs = int(h_c.size)

    if n_obs < 4:
        return DecomposeResult(
            permanent=float("nan"),
            temporary=float("nan"),
            decay_rate=float("nan"),
            r_squared=float("nan"),
            n_obs=n_obs,
            converged=False,
        )

    if initial_guess is None:
        p0 = (float(y_c[-1]), float(y_c[0] - y_c[-1]), 1.0)
    else:
        p0 = initial_guess

    try:
        popt, _ = curve_fit(
            _impact_curve,
            h_c,
            y_c,
            p0=p0,
            bounds=([-np.inf, -np.inf, 0.0], [np.inf, np.inf, np.inf]),
            maxfev=10_000,
        )
    except (RuntimeError, ValueError):
        return DecomposeResult(
            permanent=float("nan"),
            temporary=float("nan"),
            decay_rate=float("nan"),
            r_squared=float("nan"),
            n_obs=n_obs,
            converged=False,
        )

    permanent, temporary, decay_rate = (float(v) for v in popt)
    pred = _impact_curve(h_c, permanent, temporary, decay_rate)
    ss_res = float(np.sum((y_c - pred) ** 2))
    ss_tot = float(np.sum((y_c - np.mean(y_c)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    return DecomposeResult(
        permanent=permanent,
        temporary=temporary,
        decay_rate=decay_rate,
        r_squared=r_squared,
        n_obs=n_obs,
        converged=True,
    )
