"""IMP-07 — the three named clocks, wired against the existing scheduler.

"Build the scheduler first with all three clocks running against the
models we already have, confirm the timestamps behave, then attach
anything new." `orch/scheduler.py` is that scheduler (ORCH-01, already
generic and already tested). This module is the "attach" step: concrete
`JobSpec`s for macro/equity/chaos, plus the glue that makes each one
consult `MarketHoursGate` BEFORE the scheduler's own cadence/freshness
logic ever runs — so a market-hours refusal is never silently overridden
by "well the inputs looked fresh".

Each clock is deliberately its own scheduler tier already, for free: a
`JobSpec`'s cadence string doubles as its tier name (`tier_for_cadence` in
scheduler.py is the identity function), and `Scheduler` builds one
`TierBudget` per distinct cadence. Macro ("12h"), equity ("1h") and chaos
("1-5min") are three different cadence strings, so they land in three
different `TierBudget`s automatically — each with "its own queue" (the
budget's in-flight set) and "its own request budget" (`max_concurrent`),
exactly per the spec's "each clock gets its own queue, its own request
budget". A stuck/failing equity job can only exhaust the "1h" tier's
budget; it can never consume a slot out of the "12h" tier the macro job
runs in, so "a failing hourly job must never starve the macro cycle" holds
structurally, not by convention.

"Its own alarm" is the per-job `heartbeat_timeout` already on `JobSpec`
(surfaced via `Scheduler.health` as `"missing_heartbeat"`) — each clock
below sets its own, independent of the others.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Literal

from scheduler import JobSpec, RunRecord, Scheduler

from clocks.market_hours import MarketHoursGate

VenueName = Literal["NYSE"]


@dataclass(frozen=True)
class ClockJob:
    """A `JobSpec` plus the one thing the generic scheduler deliberately
    does not know about: whether this job requires the market to be open.

    Composition, not a scheduler.py edit: `spec` is a real, unmodified
    `scheduler.JobSpec` (same dataclass, same field names) that a plain
    `Scheduler` can run with no knowledge that `ClockJob` exists.
    `requires_market_hours` is consulted only by `run_clock_job` below,
    before it ever hands `spec` to the scheduler.
    """

    spec: JobSpec
    requires_market_hours: bool
    venue: VenueName | None = None  # required iff requires_market_hours


# --- concrete clock definitions ---------------------------------------------
#
# Stale-input policy choices, per job, documented per the spec's own framing
# of each clock's failure mode:

MACRO_CLOCK = ClockJob(
    spec=JobSpec(
        name="macro_regime_refresh",
        cadence="12h",
        inputs=(),
        outputs=("macro_regime",),
        # "On failure hold the previous output and mark it stale. Never
        # interpolate a macro series." skip_hold_previous is the one policy
        # that never fabricates a run from stale/missing inputs — it just
        # keeps serving the last good macro_regime value and leaves the
        # staleness visible via RunRecord.status == "skipped_stale".
        stale_input_policy="skip_hold_previous",
    ),
    requires_market_hours=False,  # macro/regime describes the world 24/7, not one venue's session
    venue=None,
)

EQUITY_CLOCK = ClockJob(
    spec=JobSpec(
        name="equity_research_refresh",
        cadence="1h",
        # Deliberately depends on the macro clock's output to demonstrate
        # cross-tier wiring: macro only refreshes every 12h, so under
        # equity's own 1h cadence the macro_regime input is essentially
        # *always* older than equity's freshness allowance. That is exactly
        # the case proceed_marked_stale exists for (see next comment) —
        # this is not a bug in the wiring, it is the intended shape of a
        # fast clock consuming a slow clock's output.
        inputs=("macro_regime",),
        outputs=("equity_research",),
        # Documented judgment call (spec allows either policy here):
        # proceed_marked_stale, not skip_hold_previous or fail_loud.
        # Equity research during market hours is expected to lean on a
        # slower-moving macro regime input that is legitimately "stale"
        # relative to equity's own hourly cadence (see above) — refusing to
        # run every single hour because of that would make the equity
        # clock nearly useless. proceed_marked_stale lets it run hourly as
        # intended while the RunRecord/status makes the staleness visible
        # (status="stale_but_ran") rather than hiding it, unlike a silent
        # "just run" would.
        stale_input_policy="proceed_marked_stale",
    ),
    requires_market_hours=True,  # equity research is scoped to the session it's about
    venue="NYSE",
)

CHAOS_CLOCK = ClockJob(
    spec=JobSpec(
        name="chaos_signal_refresh",
        cadence="1-5min",
        inputs=(),
        outputs=("chaos_signal",),
        # "Fail fast, because a stale chaos reading is worse than none."
        # fail_loud is the one policy that refuses to run at all (and
        # surfaces status="failed") rather than serving anything stale.
        stale_input_policy="fail_loud",
        # A 1-5min cadence needs a much tighter heartbeat timeout than the
        # scheduler's 30-minute default — a chaos job that misses its own
        # heartbeat for even a few minutes is already meaningfully behind.
        heartbeat_timeout=timedelta(minutes=3),
    ),
    requires_market_hours=True,  # chaos monitoring only means anything while the venue is live
    venue="NYSE",
)

ALL_CLOCKS: tuple[ClockJob, ...] = (MACRO_CLOCK, EQUITY_CLOCK, CHAOS_CLOCK)


def build_three_clock_scheduler(clock) -> Scheduler:
    """Convenience constructor: a `Scheduler` wired with exactly the three
    `JobSpec`s above (and nothing else) sharing one `clock` (an
    `orch.scheduler.Clock`, e.g. `ManualClock` in tests). Per-tier
    concurrency is left at the scheduler's own default (2) here; a real
    deployment would tune `tier_max_concurrent` per clock's actual request
    budget."""
    return Scheduler(jobs=[c.spec for c in ALL_CLOCKS], clock=clock)


def run_clock_job(
    scheduler: Scheduler,
    clock_job: ClockJob,
    gate: MarketHoursGate,
    run_timestamp: datetime,
    work_fn: Callable[[], dict[str, Any] | None],
) -> RunRecord:
    """Run one clock's job for `run_timestamp`, consulting `MarketHoursGate`
    BEFORE the scheduler's own cadence/freshness/tier-budget logic runs at
    all.

    This ordering is the crux of IMP-07's "no refreshing into a closed
    market and calling the output new": if the market-hours gate refuses,
    `scheduler.run_job` is never called for this (job, run_timestamp) —
    the scheduler's cadence/freshness view of the world (which has no
    concept of the venue being closed and would happily consider a
    long-stale input's absence "not our problem, we're not stale by our
    own clock") never gets a chance to say otherwise. The refusal is
    always accompanied by an explicit reason (never a silent no-op), and
    is recorded as an explicit `RunRecord` with a distinct detail message
    (not conflated with the scheduler's own `"skipped_stale"` from an
    unrelated cause) so a health check can tell the two apart.
    """
    allowed, reason = gate.should_run(run_timestamp, clock_job.requires_market_hours)
    if not allowed:
        now = scheduler.clock.now()
        return RunRecord(
            job_name=clock_job.spec.name,
            run_timestamp=run_timestamp,
            status="skipped_stale",
            started_at=now,
            heartbeat_at=now,
            completed_at=now,
            detail=f"market-hours gate refused: {reason}",
        )
    return scheduler.run_job(clock_job.spec.name, run_timestamp, work_fn)
