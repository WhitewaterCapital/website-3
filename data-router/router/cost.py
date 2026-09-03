"""Cost meter: a pure, per-vendor per-model request/cost counter plus budget
projection.

Deliberately has zero knowledge of quota (`quota.py`) or circuits
(`circuit.py`) — this module only counts what has already happened and
projects forward from a rate, so it is trivial to unit test in isolation and
trivial to wire into a dashboard or an alert later. `record()` is the only
mutating call; everything else is a pure read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CostRecord:
    vendor: str
    model: str
    requests: int
    cost: float


class CostMeter:
    """Accumulates request counts and cost by `(vendor, model)`. `cost` is
    whatever unit the caller wants (dollars, "credits", vendor-defined
    request-units) — the meter does not interpret it, only sums it."""

    def __init__(self) -> None:
        self._requests: dict[tuple, int] = {}
        self._cost: dict[tuple, float] = {}

    def record(self, vendor: str, model: str, *, requests: int = 1, cost: float = 0.0) -> None:
        if requests < 0:
            raise ValueError("requests must be non-negative")
        key = (vendor, model)
        self._requests[key] = self._requests.get(key, 0) + requests
        self._cost[key] = self._cost.get(key, 0.0) + cost

    def requests(self, vendor: str, model: str) -> int:
        return self._requests.get((vendor, model), 0)

    def cost(self, vendor: str, model: str) -> float:
        return self._cost.get((vendor, model), 0.0)

    def total_cost(self) -> float:
        return sum(self._cost.values())

    def total_requests(self) -> int:
        return sum(self._requests.values())

    def by_vendor_model(self) -> list[CostRecord]:
        return [
            CostRecord(vendor=v, model=m, requests=self._requests.get((v, m), 0), cost=c)
            for (v, m), c in sorted(self._cost.items())
        ]


def project_cost(current_rate: float, plan_limit: float, *, periods_remaining: float = 1.0) -> dict:
    """Project spend forward from a per-period `current_rate` (e.g. "$/day"
    or "requests/day" — whatever unit `plan_limit` is denominated in) over
    `periods_remaining` more periods, and say whether that projection alone
    would already exceed `plan_limit`.

    Pure function, no state — the caller decides what "current_rate" means
    (a `CostMeter.cost(...)` reading divided by elapsed periods, a rolling
    average, whatever) and passes it in.

    Returns:
        {
          "current_rate": float,
          "plan_limit": float,
          "projected_total": float,   # current_rate * periods_remaining
          "over_budget": bool,        # projected_total > plan_limit
          "headroom": float,          # plan_limit - projected_total (negative if over)
          "utilization": float,       # projected_total / plan_limit (inf-safe: None if plan_limit == 0)
        }
    """
    if current_rate < 0:
        raise ValueError("current_rate must be non-negative")
    if plan_limit < 0:
        raise ValueError("plan_limit must be non-negative")
    if periods_remaining < 0:
        raise ValueError("periods_remaining must be non-negative")

    projected_total = current_rate * periods_remaining
    headroom = plan_limit - projected_total
    utilization: Optional[float] = (projected_total / plan_limit) if plan_limit > 0 else None

    return {
        "current_rate": current_rate,
        "plan_limit": plan_limit,
        "projected_total": projected_total,
        "over_budget": projected_total > plan_limit,
        "headroom": headroom,
        "utilization": utilization,
    }
