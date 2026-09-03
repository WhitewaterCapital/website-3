"""WW-COST — square-root market-impact cost estimate (IMP-18).

The doc: "Square root impact estimate as the baseline. Cost scales with the
square root of order size against typical volume, times volatility, plus
half the effective spread."

    cost = impact_coefficient * volatility * sqrt(order_size / typical_volume)
           + 0.5 * effective_spread

This is the classic square-root market-impact functional form: impact grows
with the square root of participation rate (`order_size / typical_volume`),
scaled by volatility, plus a fixed half-spread crossing cost that applies
regardless of size.

**Calibration status is a first-class, explicit field.** "Calibrate the
impact coefficient from realised fills. Until we have enough, use a
conservative default and mark the estimate uncalibrated." This module never
silently guesses a coefficient and presents it as calibrated:
  - Pass `impact_coefficient=None` (the default) to use
    `DEFAULT_IMPACT_COEFFICIENT` — a documented, conservative placeholder,
    not a fitted number — and the result comes back with `calibrated=False`.
  - Pass a coefficient obtained from `calibration.calibrate_impact_coefficient`
    to get `calibrated=True`.

`DEFAULT_IMPACT_COEFFICIENT = 1.0` is a round, deliberately conservative
placeholder (it is not derived from any market data): for typical volatility
and participation-rate ranges it produces an impact estimate on the high
side of empirically observed square-root-law coefficients (which commonly
fall well under 1 in the literature's usual units), so that *before*
real calibration exists, this module errs toward overstating cost — and
therefore toward under-funding and under-sizing strategies — rather than
understating it. It must be replaced by a calibrated coefficient
(`calibration.calibrate_impact_coefficient`) as soon as enough realised
fills exist; see that module's documented sample threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

DEFAULT_IMPACT_COEFFICIENT = 1.0  # conservative placeholder; see module docstring


@dataclass(frozen=True)
class CostEstimate:
    """Result of `estimate_impact_cost`.

    Fields:
      cost: the estimated transaction cost (same units as `effective_spread`
        / `volatility`, i.e. whatever the caller's convention is — this
        module does not impose a unit, it only implements the formula).
      calibrated: True iff `impact_coefficient_used` came from a real
        calibration fit (i.e. the caller passed one in); False iff it is
        `DEFAULT_IMPACT_COEFFICIENT`.
      impact_coefficient_used: the coefficient actually used in the formula.
      order_size, typical_volume, volatility, effective_spread: the inputs,
        echoed back so the estimate is self-contained and reproducible.
    """

    cost: float
    calibrated: bool
    impact_coefficient_used: float
    order_size: float
    typical_volume: float
    volatility: float
    effective_spread: float


def _check_finite_nonneg(name: str, value: float) -> None:
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must be non-negative, got {value!r}")


def estimate_impact_cost(
    order_size: float,
    typical_volume: float,
    volatility: float,
    effective_spread: float,
    impact_coefficient: Optional[float] = None,
) -> CostEstimate:
    """Square-root impact cost estimate.

        cost = impact_coefficient * volatility * sqrt(order_size / typical_volume)
               + 0.5 * effective_spread

    Raises `ValueError` if `order_size`, `volatility`, or `effective_spread`
    is negative or non-finite, or if `typical_volume` is not strictly
    positive (a zero or negative typical volume makes the participation
    rate undefined/infinite, not a valid market condition to estimate cost
    against) or non-finite. `impact_coefficient`, if given explicitly, must
    also be finite and non-negative (a negative impact coefficient would
    imply impact *reduces* cost, which is not a physically meaningful
    calibration result).
    """
    _check_finite_nonneg("order_size", order_size)
    _check_finite_nonneg("volatility", volatility)
    _check_finite_nonneg("effective_spread", effective_spread)

    if typical_volume != typical_volume or typical_volume in (float("inf"), float("-inf")):
        raise ValueError(f"typical_volume must be a finite number, got {typical_volume!r}")
    if typical_volume <= 0:
        raise ValueError(f"typical_volume must be strictly positive, got {typical_volume!r}")

    if impact_coefficient is None:
        coef = DEFAULT_IMPACT_COEFFICIENT
        calibrated = False
    else:
        _check_finite_nonneg("impact_coefficient", impact_coefficient)
        coef = float(impact_coefficient)
        calibrated = True

    participation = float(order_size) / float(typical_volume)
    cost = coef * float(volatility) * math.sqrt(participation) + 0.5 * float(effective_spread)

    return CostEstimate(
        cost=float(cost),
        calibrated=calibrated,
        impact_coefficient_used=float(coef),
        order_size=float(order_size),
        typical_volume=float(typical_volume),
        volatility=float(volatility),
        effective_spread=float(effective_spread),
    )
