"""WW-COST — calibrating the impact coefficient from realised fills (IMP-18).

The doc: "Calibrate the impact coefficient from realised fills. Until we
have enough, use a conservative default and mark the estimate uncalibrated."

Given the square-root impact model from `impact.py`

    cost = impact_coefficient * volatility * sqrt(order_size / typical_volume)
           + 0.5 * effective_spread

a realised fill's `realized_slippage` is treated as an observation of that
same `cost`. Subtracting the (known, not-fit) half-spread term isolates the
sqrt-impact term:

    y_i := realized_slippage_i - 0.5 * effective_spread_i
         ≈ impact_coefficient * (volatility_i * sqrt(order_size_i / typical_volume_i))
         =: impact_coefficient * x_i

`impact_coefficient` is then the single-variable, through-the-origin
least-squares fit of `y` on `x` (no intercept term — the model has no free
intercept once the spread term is subtracted out):

    impact_coefficient = sum(x_i * y_i) / sum(x_i^2)

**Minimum sample size — the "until we have enough" rule.** Fitting a
single-parameter regression off only a handful of noisy fills would produce
a number that *looks* calibrated but is actually just noise dressed up as
a fact — exactly what this codebase's honesty discipline forbids. This
module returns `None` (never a guess) when fewer than
`MIN_FILLS_FOR_CALIBRATION` usable fills are available. `20` is a
conservative, documented threshold: not derived from any statistical power
calculation on real data (none exists yet — that is exactly the point),
chosen only because it is the smallest round number that is clearly more
than "a small handful" while still being achievable early in a strategy's
live history. Revisit it once real fill data exists to check the fitted
coefficient's actual standard error at that sample size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

MIN_FILLS_FOR_CALIBRATION = 20  # see module docstring


@dataclass(frozen=True)
class FillRecord:
    """One realised fill used to calibrate the impact coefficient.

    `realized_slippage` is the actually-realised execution cost for this
    fill (same convention/units as `impact.CostEstimate.cost`).
    """

    order_size: float
    typical_volume: float
    volatility: float
    effective_spread: float
    realized_slippage: float


def _usable_xy(fills: Sequence[FillRecord]) -> tuple[np.ndarray, np.ndarray]:
    xs: list[float] = []
    ys: list[float] = []
    for f in fills:
        # Skip fills with a structurally invalid participation rate (undefined
        # sqrt-impact term) rather than raising — a single bad row in a
        # realised-fills feed should not blow up calibration of everything
        # else, but it must also not be silently coerced into a fake number.
        if not np.isfinite(f.typical_volume) or f.typical_volume <= 0:
            continue
        if not np.isfinite(f.order_size) or f.order_size < 0:
            continue
        if not np.isfinite(f.volatility) or not np.isfinite(f.effective_spread):
            continue
        if not np.isfinite(f.realized_slippage):
            continue
        x = f.volatility * float(np.sqrt(f.order_size / f.typical_volume))
        y = f.realized_slippage - 0.5 * f.effective_spread
        xs.append(x)
        ys.append(y)
    return np.array(xs, dtype=float), np.array(ys, dtype=float)


def calibrate_impact_coefficient(realized_fills: Sequence[FillRecord]) -> Optional[float]:
    """Fit `impact_coefficient` by through-the-origin least squares against
    realised fills, isolating the sqrt-impact term from the (known)
    half-spread term.

    Returns `None` — never a guess — if fewer than
    `MIN_FILLS_FOR_CALIBRATION` *usable* fills are available (a fill with a
    non-positive `typical_volume`, a negative `order_size`, or a non-finite
    field is excluded from the usable count; see `_usable_xy`), or if the
    usable fills carry no information to fit against (all `x_i == 0`, i.e.
    every usable fill had zero order size or zero volatility, so the
    denominator of the least-squares estimator is zero).
    """
    x, y = _usable_xy(realized_fills)
    if x.shape[0] < MIN_FILLS_FOR_CALIBRATION:
        return None
    denom = float(np.sum(x * x))
    if denom == 0.0:
        return None
    coef = float(np.sum(x * y) / denom)
    return coef
