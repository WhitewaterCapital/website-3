"""WW-COST — weekly realised-vs-predicted cost error tracking (IMP-18).

The doc: "Done when realised slippage is compared to predicted cost
weekly, the error is tracked, and no strategy is funded past its
capacity."

This module supplies the "compared... weekly, the error is tracked" half of
that sentence (the "no strategy is funded past its capacity" half is
`capacity.estimate_capacity`, enforced by whatever caller wires funding
decisions to it — out of scope here). It is a plain in-memory accumulator:
a caller records one `CostTrackingRecord` per fill (the cost that was
*predicted* at order time — e.g. `impact.CostEstimate.cost` — alongside the
slippage that was *actually realised*), and `CostErrorTracker` exposes a
running mean-absolute-error, both overall and bucketed by ISO week, so a
weekly job can pull "how far off were we this week" without recomputing
anything from raw fills.

Wiring this to an actual weekly cron/job and a real persisted fills feed is
out of scope for this pass (see the package README) — this module is the
aggregation logic a caller supplies real records to.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CostTrackingRecord:
    """One (predicted cost at order time, realised slippage) observation."""

    strategy_id: str
    timestamp: float  # seconds since epoch
    predicted_cost: float
    realized_slippage: float

    @property
    def error(self) -> float:
        """realised - predicted; positive means we under-predicted cost."""
        return self.realized_slippage - self.predicted_cost

    @property
    def abs_error(self) -> float:
        return abs(self.error)


def _iso_week_key(timestamp: float) -> tuple[int, int]:
    dt = datetime.datetime.utcfromtimestamp(timestamp)
    iso_year, iso_week, _ = dt.isocalendar()
    return (iso_year, iso_week)


class CostErrorTracker:
    """Accumulates `CostTrackingRecord`s and exposes running MAE, overall,
    per strategy, and per ISO week."""

    def __init__(self) -> None:
        self._records: list[CostTrackingRecord] = []

    def add(self, record: CostTrackingRecord) -> None:
        self._records.append(record)

    def add_observation(
        self, strategy_id: str, timestamp: float, predicted_cost: float, realized_slippage: float
    ) -> CostTrackingRecord:
        record = CostTrackingRecord(
            strategy_id=strategy_id,
            timestamp=float(timestamp),
            predicted_cost=float(predicted_cost),
            realized_slippage=float(realized_slippage),
        )
        self.add(record)
        return record

    def records_for(self, strategy_id: str) -> list[CostTrackingRecord]:
        return [r for r in self._records if r.strategy_id == strategy_id]

    def mean_absolute_error(self, strategy_id: Optional[str] = None) -> Optional[float]:
        """Running MAE across all recorded observations (optionally filtered
        to one strategy). `None` if there are no matching observations —
        never a fabricated 0.0."""
        records = [r for r in self._records if strategy_id is None or r.strategy_id == strategy_id]
        if not records:
            return None
        return sum(r.abs_error for r in records) / len(records)

    def weekly_mean_absolute_error(
        self, strategy_id: Optional[str] = None
    ) -> dict[tuple[int, int], float]:
        """MAE bucketed by ISO (year, week), across all recorded
        observations (optionally filtered to one strategy). This is the
        function a weekly job calls to get "the error, tracked, weekly."
        """
        buckets: dict[tuple[int, int], list[float]] = {}
        for r in self._records:
            if strategy_id is not None and r.strategy_id != strategy_id:
                continue
            key = _iso_week_key(r.timestamp)
            buckets.setdefault(key, []).append(r.abs_error)
        return {k: sum(v) / len(v) for k, v in buckets.items()}
