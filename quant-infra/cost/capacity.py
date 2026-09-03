"""WW-COST — capacity estimate: the size where cost eats the edge (IMP-18).

The doc: "Capacity estimate per strategy. The size where cost eats the
edge is a hard limit."

Using the same square-root impact model as `impact.py`,

    cost(order_size) = impact_coefficient * volatility * sqrt(order_size / typical_volume)
                        + 0.5 * effective_spread

capacity is the `order_size` at which `cost(order_size) == expected_edge_bps`
— beyond that size, the strategy's edge is fully consumed by cost, so
`estimate_capacity` returns that size as a hard limit a caller should never
fund a strategy past (see `cost/tracking.py`'s docstring for how the
weekly realised-vs-predicted check is meant to keep this limit honest over
time).

Because `cost()` is monotonically non-decreasing in `order_size` (it is a
non-negative coefficient times a non-decreasing function of `order_size`,
plus a size-independent constant), the equation has a closed form — solved
directly here rather than by numerical search:

    impact_coefficient * volatility * sqrt(order_size / typical_volume)
        = expected_edge_bps - 0.5 * effective_spread
    =>  order_size = typical_volume *
            ((expected_edge_bps - 0.5*effective_spread) / (impact_coefficient*volatility))^2

**Degenerate cases, both explicit, neither a silent default:**
  - If the half-spread term alone already meets or exceeds
    `expected_edge_bps` (spread crossing alone eats the whole edge), no
    order size is profitable: capacity is `0.0`.
  - If `impact_coefficient == 0` or `volatility == 0`, cost never grows
    with size in this model (there is no impact term to grow), so once the
    spread term is below the edge, cost stays below the edge at any size:
    capacity is `float("inf")`. This is a real, documented consequence of
    the model with a zero impact term, not a numerical artefact — a caller
    that receives `inf` here should treat it as "this model currently
    imposes no size limit," not as an unhandled edge case.
"""

from __future__ import annotations

import math


def _check_finite(name: str, value: float) -> None:
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number, got {value!r}")


def estimate_capacity(
    expected_edge_bps: float,
    typical_volume: float,
    volatility: float,
    effective_spread: float,
    impact_coefficient: float,
) -> float:
    """The order_size at which `impact.estimate_impact_cost`'s cost equals
    `expected_edge_bps`, i.e. the hard capacity limit for this strategy at
    these market conditions and this (calibrated or default) impact
    coefficient.

    Raises `ValueError` if `typical_volume` is not strictly positive, or if
    `volatility`, `effective_spread`, or `impact_coefficient` is negative
    or non-finite, or if `expected_edge_bps` is non-finite. A negative
    `expected_edge_bps` is accepted (a strategy with no edge, or a
    documented negative edge, has zero capacity — see below) but every
    other input follows the same non-negativity convention as `impact.py`.
    """
    _check_finite("expected_edge_bps", expected_edge_bps)
    _check_finite("typical_volume", typical_volume)
    _check_finite("volatility", volatility)
    _check_finite("effective_spread", effective_spread)
    _check_finite("impact_coefficient", impact_coefficient)

    if typical_volume <= 0:
        raise ValueError(f"typical_volume must be strictly positive, got {typical_volume!r}")
    if volatility < 0:
        raise ValueError(f"volatility must be non-negative, got {volatility!r}")
    if effective_spread < 0:
        raise ValueError(f"effective_spread must be non-negative, got {effective_spread!r}")
    if impact_coefficient < 0:
        raise ValueError(f"impact_coefficient must be non-negative, got {impact_coefficient!r}")

    remaining_edge = float(expected_edge_bps) - 0.5 * float(effective_spread)
    if remaining_edge <= 0.0:
        # spread crossing alone already eats the whole edge (or the edge is
        # non-positive to begin with) -> no size is ever profitable.
        return 0.0

    denom = float(impact_coefficient) * float(volatility)
    if denom == 0.0:
        # no impact term in the model at these parameters -> cost never
        # grows with size once past the spread floor -> no size-based limit.
        return float("inf")

    ratio = remaining_edge / denom
    return float(typical_volume) * (ratio ** 2)
