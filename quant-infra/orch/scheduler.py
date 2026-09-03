"""ORCH-01 — orchestration scheduler skeleton.

Models each job as a node in a dependency graph (`networkx.DiGraph`, edges
drawn from a job's declared `outputs` to whichever other job declares a
matching name in its `inputs`), with a declared cadence, declared
inputs/outputs, and a stale-input policy. `Scheduler` decides whether a job's
inputs are "fresh enough" for the JOB'S OWN cadence (not the cadence of
whatever produced the input), tracks per-run heartbeat/completion state so a
job that stops reporting is explicitly visible rather than silently assumed
fine, and makes re-running a job for a timestamp it already ran for a no-op
replay rather than a second side effect.

**Documented simplification vs the doc's ask**: there is no real task-queue
or thread pool here. "Each cadence tier as its own named-queue/budget
abstraction" is modelled as an in-memory `TierBudget` that tracks an
in-flight set and a `max_concurrent` capacity and can be asked to
`try_acquire`/`release` — a fully testable model of "the fast tier can only
have N jobs in flight at once," with no actual concurrency behind it. Wiring
this to a real scheduler (cron, Airflow, a queue) is future work; the state
machine here (fresh/stale, running/missing-heartbeat/completed,
idempotent-replay, downstream staleness) is the part that has to be correct
regardless of what runs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence

import networkx as nx

StaleInputPolicy = Literal["proceed_marked_stale", "skip_hold_previous", "fail_loud"]
RunStatus = Literal["running", "success", "failed", "skipped_stale", "stale_but_ran"]
HealthState = Literal["running", "missing_heartbeat", "success", "failed", "skipped_stale", "stale_but_ran", "unknown"]

_CADENCE_PATTERN = re.compile(r"^(\d+)(?:-(\d+))?(min|h)$")


class SchedulerError(Exception):
    """Raised for programmer-error-shaped misuse (unknown job, heartbeat on a
    run that was never started, a cyclic dependency graph) — never for a
    normal stale-input or infeasibility outcome, which are reported via
    `RunRecord`/`HealthState` instead."""


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass
class ManualClock:
    """Injectable clock for tests: time only moves when you tell it to."""
    _now: datetime

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta

    def set(self, dt: datetime) -> None:
        self._now = dt


@dataclass(frozen=True)
class JobSpec:
    name: str
    cadence: str  # e.g. "12h", "1h", "1-5min", "daily", "weekly"
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    stale_input_policy: StaleInputPolicy = "fail_loud"
    heartbeat_timeout: timedelta = timedelta(minutes=30)


@dataclass(frozen=True)
class RunRecord:
    job_name: str
    run_timestamp: datetime
    status: RunStatus
    started_at: datetime
    heartbeat_at: datetime
    completed_at: datetime | None
    detail: str
    outputs_produced: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DisableResult:
    disabled_job: str
    stale_downstream: frozenset[str]


def parse_cadence(cadence: str) -> timedelta:
    """Parse a cadence label into the maximum age an input may have and
    still count as "fresh enough" for a job running at that cadence.

    Recognised forms: `"daily"`, `"weekly"`, `"<N>h"`, `"<N>min"`, and a
    range form `"<A>-<B>h"` / `"<A>-<B>min"` (e.g. `"1-5min"`) — for a range,
    the UPPER bound is used as the freshness allowance, deliberately the
    looser of the two ends, so a job that legitimately runs anywhere in that
    window is not flagged stale by its own normal cadence.

    Raises `ValueError` on anything else, rather than guessing.
    """
    if cadence == "daily":
        return timedelta(days=1)
    if cadence == "weekly":
        return timedelta(weeks=1)
    m = _CADENCE_PATTERN.match(cadence)
    if not m:
        raise ValueError(f"unrecognized cadence string: {cadence!r}")
    lo_s, hi_s, unit = m.groups()
    value = int(hi_s) if hi_s is not None else int(lo_s)
    return timedelta(hours=value) if unit == "h" else timedelta(minutes=value)


def tier_for_cadence(cadence: str) -> str:
    """Each distinct cadence label is its own named tier (matches the doc's
    own examples: "12h"/"1h"/"1-5min"/"daily"/"weekly" read directly as tier
    names) — no further bucketing is applied."""
    return cadence


class TierBudget:
    """A documented, testable stand-in for "the `<cadence>` tier can only
    have `max_concurrent` jobs in flight at once." No real concurrency; just
    an in-flight set a caller must acquire/release around a job's execution.
    """

    def __init__(self, tier: str, max_concurrent: int = 2):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self.tier = tier
        self.max_concurrent = max_concurrent
        self._in_flight: set[str] = set()

    def try_acquire(self, job_name: str) -> bool:
        if job_name in self._in_flight:
            return True  # re-entrant: a job already holding a slot keeps it
        if len(self._in_flight) >= self.max_concurrent:
            return False
        self._in_flight.add(job_name)
        return True

    def release(self, job_name: str) -> None:
        self._in_flight.discard(job_name)

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)


class Scheduler:
    def __init__(
        self,
        jobs: Sequence[JobSpec],
        clock: Clock,
        tier_max_concurrent: Mapping[str, int] | None = None,
    ):
        self.jobs: dict[str, JobSpec] = {j.name: j for j in jobs}
        if len(self.jobs) != len(jobs):
            raise ValueError("duplicate job names in jobs")
        self.clock = clock
        self.graph = self._build_graph(jobs)
        if not nx.is_directed_acyclic_graph(self.graph):
            raise ValueError("job dependency graph contains a cycle")

        self.tiers: dict[str, TierBudget] = {}
        for j in jobs:
            tier = tier_for_cadence(j.cadence)
            if tier not in self.tiers:
                max_c = (tier_max_concurrent or {}).get(tier, 2)
                self.tiers[tier] = TierBudget(tier, max_c)

        self._records: dict[tuple[str, datetime], RunRecord] = {}
        self._input_freshness: dict[str, datetime] = {}
        self.disabled_jobs: set[str] = set()
        self.stale_jobs: set[str] = set()

    @staticmethod
    def _build_graph(jobs: Sequence[JobSpec]) -> nx.DiGraph:
        g = nx.DiGraph()
        for j in jobs:
            g.add_node(j.name)
        producer_of: dict[str, str] = {}
        for j in jobs:
            for out in j.outputs:
                producer_of[out] = j.name
        for j in jobs:
            for inp in j.inputs:
                producer = producer_of.get(inp)
                if producer is not None and producer != j.name:
                    g.add_edge(producer, j.name)
        return g

    # --- freshness -------------------------------------------------------

    def mark_input_ready(self, name: str, at: datetime | None = None) -> None:
        """Record that a named input/output artifact became available at
        `at` (default: current clock time). This is how an external feed
        (or a job's own completion, done automatically by `record_completion`)
        publishes freshness."""
        self._input_freshness[name] = at if at is not None else self.clock.now()

    def _is_fresh(self, input_name: str, consuming_cadence: str, now: datetime) -> bool:
        """True only if the input has a recorded freshness timestamp AND its
        age is within the CONSUMING job's own cadence allowance — an input
        that was never recorded as ready is never "fresh", not an unknown
        treated optimistically as fine."""
        ts = self._input_freshness.get(input_name)
        if ts is None:
            return False
        return (now - ts) <= parse_cadence(consuming_cadence)

    # --- low-level run lifecycle (heartbeat/completion visibility) -------

    def begin_run(self, job_name: str, run_timestamp: datetime) -> RunRecord:
        if job_name not in self.jobs:
            raise SchedulerError(f"unknown job {job_name!r}")
        key = (job_name, run_timestamp)
        if key in self._records:
            return self._records[key]
        now = self.clock.now()
        rec = RunRecord(job_name, run_timestamp, "running", now, now, None, "started")
        self._records[key] = rec
        return rec

    def record_heartbeat(self, job_name: str, run_timestamp: datetime) -> RunRecord:
        key = (job_name, run_timestamp)
        rec = self._records.get(key)
        if rec is None or rec.status != "running":
            raise SchedulerError(f"no in-flight run to heartbeat for {key}")
        updated = replace(rec, heartbeat_at=self.clock.now())
        self._records[key] = updated
        return updated

    def record_completion(
        self,
        job_name: str,
        run_timestamp: datetime,
        outputs: dict[str, Any] | None = None,
        status: RunStatus = "success",
        detail: str = "",
    ) -> RunRecord:
        key = (job_name, run_timestamp)
        rec = self._records.get(key)
        if rec is None:
            raise SchedulerError(f"no in-flight run to complete for {key}")
        now = self.clock.now()
        outputs = outputs or {}
        updated = replace(
            rec, status=status, completed_at=now, heartbeat_at=now,
            detail=detail or rec.detail, outputs_produced=outputs,
        )
        self._records[key] = updated
        for out_name in outputs:
            self.mark_input_ready(out_name, at=now)
        return updated

    def health(self, job_name: str, run_timestamp: datetime, now: datetime | None = None) -> HealthState:
        """Explicit health state for one (job, run_timestamp). A run that
        began and then stopped reporting (no heartbeat/completion within its
        `heartbeat_timeout`) surfaces as `"missing_heartbeat"` — the scheduler
        never silently treats an unreported job as fine."""
        now = now if now is not None else self.clock.now()
        rec = self._records.get((job_name, run_timestamp))
        if rec is None:
            return "unknown"
        if rec.status != "running":
            return rec.status
        timeout = self.jobs[job_name].heartbeat_timeout
        if (now - rec.heartbeat_at) > timeout:
            return "missing_heartbeat"
        return "running"

    # --- high-level convenience: freshness + idempotent run in one call --

    def run_job(
        self, job_name: str, run_timestamp: datetime, work_fn: Callable[[], dict[str, Any] | None]
    ) -> RunRecord:
        """Run `job_name` for `run_timestamp`, or replay the already-recorded
        result if this (job, run_timestamp) pair has been run before —
        `work_fn` is NOT invoked on replay, so a job is genuinely idempotent
        per timestamp rather than merely safe-to-repeat.

        Enforces, in order: (1) idempotent replay, (2) the job's cadence
        tier budget, (3) its declared `stale_input_policy` against every
        declared input's freshness for ITS OWN cadence.
        """
        if job_name not in self.jobs:
            raise SchedulerError(f"unknown job {job_name!r}")
        key = (job_name, run_timestamp)
        if key in self._records:
            return self._records[key]

        spec = self.jobs[job_name]
        now = self.clock.now()
        tier_budget = self.tiers[tier_for_cadence(spec.cadence)]

        if not tier_budget.try_acquire(job_name):
            rec = RunRecord(job_name, run_timestamp, "failed", now, now, now, "tier budget exhausted; deferred")
            self._records[key] = rec
            return rec

        try:
            stale_inputs = [inp for inp in spec.inputs if not self._is_fresh(inp, spec.cadence, now)]
            marked_stale = False
            if stale_inputs:
                if spec.stale_input_policy == "fail_loud":
                    rec = RunRecord(job_name, run_timestamp, "failed", now, now, now, f"stale inputs: {stale_inputs}")
                    self._records[key] = rec
                    return rec
                if spec.stale_input_policy == "skip_hold_previous":
                    rec = RunRecord(
                        job_name, run_timestamp, "skipped_stale", now, now, now,
                        f"held previous output; stale inputs: {stale_inputs}",
                    )
                    self._records[key] = rec
                    return rec
                marked_stale = True  # proceed_marked_stale: run, but flag it

            self.begin_run(job_name, run_timestamp)
            self.record_heartbeat(job_name, run_timestamp)
            try:
                outputs = work_fn() or {}
            except Exception as exc:
                return self.record_completion(
                    job_name, run_timestamp, outputs={}, status="failed",
                    detail=f"work_fn raised: {exc!r}",
                )
            status: RunStatus = "stale_but_ran" if marked_stale else "success"
            return self.record_completion(
                job_name, run_timestamp, outputs=outputs, status=status,
                detail="ran with stale inputs" if marked_stale else "ok",
            )
        finally:
            tier_budget.release(job_name)

    # --- dependency-graph staleness propagation ---------------------------

    def disable(self, job_name: str) -> DisableResult:
        """Disable `job_name` and mark every job reachable from it in the
        dependency graph (its transitive consumers) as stale. Independent
        jobs — anything not downstream of `job_name` — are left untouched."""
        if job_name not in self.graph:
            raise SchedulerError(f"unknown job {job_name!r}")
        self.disabled_jobs.add(job_name)
        downstream = frozenset(nx.descendants(self.graph, job_name))
        self.stale_jobs |= downstream
        return DisableResult(disabled_job=job_name, stale_downstream=downstream)

    def is_stale(self, job_name: str) -> bool:
        return job_name in self.stale_jobs
