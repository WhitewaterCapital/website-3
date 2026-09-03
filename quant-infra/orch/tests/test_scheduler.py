"""Tests for orch/scheduler.py."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from scheduler import (
    JobSpec,
    ManualClock,
    Scheduler,
    SchedulerError,
    TierBudget,
    parse_cadence,
    tier_for_cadence,
)

T0 = datetime(2026, 1, 1, 9, 0, 0)


# --- parse_cadence -------------------------------------------------------------

def test_parse_simple_hour_and_minute():
    assert parse_cadence("12h") == timedelta(hours=12)
    assert parse_cadence("1h") == timedelta(hours=1)


def test_parse_daily_and_weekly():
    assert parse_cadence("daily") == timedelta(days=1)
    assert parse_cadence("weekly") == timedelta(weeks=1)


def test_parse_range_uses_upper_bound():
    assert parse_cadence("1-5min") == timedelta(minutes=5)


def test_parse_unrecognized_raises():
    with pytest.raises(ValueError):
        parse_cadence("fortnightly")
    with pytest.raises(ValueError):
        parse_cadence("")


def test_tier_for_cadence_is_identity():
    assert tier_for_cadence("12h") == "12h"


# --- TierBudget ------------------------------------------------------------------

def test_tier_budget_capacity_and_release():
    tb = TierBudget("fast", max_concurrent=1)
    assert tb.try_acquire("A") is True
    assert tb.try_acquire("B") is False  # capacity exhausted
    tb.release("A")
    assert tb.try_acquire("B") is True


def test_tier_budget_reentrant_for_same_job():
    tb = TierBudget("fast", max_concurrent=1)
    assert tb.try_acquire("A") is True
    assert tb.try_acquire("A") is True  # already holds the slot


def test_tier_budget_rejects_zero_concurrency():
    with pytest.raises(ValueError):
        TierBudget("fast", max_concurrent=0)


# --- graph construction ----------------------------------------------------------

def _three_job_chain():
    return [
        JobSpec("A", cadence="1h", inputs=(), outputs=("a_out",)),
        JobSpec("B", cadence="1h", inputs=("a_out",), outputs=("b_out",)),
        JobSpec("C", cadence="1h", inputs=("b_out",), outputs=("c_out",)),
        JobSpec("D", cadence="1h", inputs=(), outputs=("d_out",)),  # independent
    ]


def test_graph_edges_follow_declared_inputs_outputs():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    assert set(sched.graph.successors("A")) == {"B"}
    assert set(sched.graph.successors("B")) == {"C"}
    assert set(sched.graph.successors("D")) == set()


def test_cyclic_graph_raises():
    jobs = [
        JobSpec("X", cadence="1h", inputs=("y_out",), outputs=("x_out",)),
        JobSpec("Y", cadence="1h", inputs=("x_out",), outputs=("y_out",)),
    ]
    with pytest.raises(ValueError):
        Scheduler(jobs, ManualClock(T0))


def test_duplicate_job_names_raises():
    jobs = [JobSpec("A", "1h"), JobSpec("A", "1h")]
    with pytest.raises(ValueError):
        Scheduler(jobs, ManualClock(T0))


# --- the doc's "done when": disabling a job stales ONLY its downstream -----------

def test_disabling_one_job_stales_only_its_downstream_dependents():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    result = sched.disable("A")
    assert result.disabled_job == "A"
    assert result.stale_downstream == frozenset({"B", "C"})
    assert sched.is_stale("B") and sched.is_stale("C")
    assert not sched.is_stale("D")   # independent job untouched
    assert not sched.is_stale("A")   # the disabled job itself is "disabled", not "stale"


def test_disabling_a_leaf_job_stales_nothing():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    result = sched.disable("C")
    assert result.stale_downstream == frozenset()
    assert not sched.is_stale("D")


def test_disable_unknown_job_raises():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    with pytest.raises(SchedulerError):
        sched.disable("NOPE")


# --- freshness / stale-input policies ---------------------------------------------

def _consumer(policy):
    return [
        JobSpec("UPSTREAM", cadence="1h", inputs=(), outputs=("feed",)),
        JobSpec("DOWNSTREAM", cadence="1h", inputs=("feed",), outputs=("result",), stale_input_policy=policy),
    ]


def test_fail_loud_blocks_run_on_stale_input():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("fail_loud"), clock)
    # feed never marked ready -> definitely stale
    rec = sched.run_job("DOWNSTREAM", T0, work_fn=lambda: {"result": 1})
    assert rec.status == "failed"
    assert "stale inputs" in rec.detail


def test_skip_hold_previous_does_not_run_work_fn():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("skip_hold_previous"), clock)
    calls = []
    rec = sched.run_job("DOWNSTREAM", T0, work_fn=lambda: calls.append(1) or {"result": 1})
    assert rec.status == "skipped_stale"
    assert calls == []  # work_fn never invoked


def test_proceed_marked_stale_runs_but_flags_it():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("proceed_marked_stale"), clock)
    rec = sched.run_job("DOWNSTREAM", T0, work_fn=lambda: {"result": 1})
    assert rec.status == "stale_but_ran"
    assert rec.outputs_produced == {"result": 1}


def test_fresh_input_lets_the_job_run_normally():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("fail_loud"), clock)
    sched.mark_input_ready("feed", at=T0)  # fresh as of now
    rec = sched.run_job("DOWNSTREAM", T0, work_fn=lambda: {"result": 42})
    assert rec.status == "success"
    assert rec.outputs_produced == {"result": 42}


def test_input_fresh_for_its_own_cadence_but_would_be_stale_for_a_faster_one():
    # A "1h"-cadence job accepts an input that's 45 minutes old; a
    # hypothetical "1-5min" job would NOT (freshness is judged against the
    # CONSUMING job's own cadence, per the spec).
    jobs = [
        JobSpec("UPSTREAM", cadence="1h", inputs=(), outputs=("feed",)),
        JobSpec("SLOW", cadence="1h", inputs=("feed",), outputs=("slow_out",)),
        JobSpec("FAST", cadence="1-5min", inputs=("feed",), outputs=("fast_out",)),
    ]
    clock = ManualClock(T0)
    sched = Scheduler(jobs, clock)
    sched.mark_input_ready("feed", at=T0)
    clock.advance(timedelta(minutes=45))
    slow_rec = sched.run_job("SLOW", clock.now(), work_fn=lambda: {"slow_out": 1})
    fast_rec = sched.run_job("FAST", clock.now(), work_fn=lambda: {"fast_out": 1})
    assert slow_rec.status == "success"
    assert fast_rec.status == "failed"  # 45min > 5min allowance, fail_loud default


def test_unknown_job_raises():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    with pytest.raises(SchedulerError):
        sched.run_job("NOPE", T0, work_fn=lambda: {})


# --- idempotency -------------------------------------------------------------------

def test_running_same_job_twice_for_same_timestamp_is_idempotent():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("fail_loud"), clock)
    sched.mark_input_ready("feed", at=T0)
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        return {"result": calls["n"]}

    first = sched.run_job("DOWNSTREAM", T0, work_fn=work)
    second = sched.run_job("DOWNSTREAM", T0, work_fn=work)
    assert calls["n"] == 1                 # work_fn invoked exactly once
    assert first == second                 # identical recorded result
    assert first.outputs_produced == {"result": 1}


def test_different_timestamps_are_independent_runs():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("fail_loud"), clock)
    sched.mark_input_ready("feed", at=T0)
    calls = {"n": 0}

    def work():
        calls["n"] += 1
        return {"result": calls["n"]}

    t1 = sched.run_job("DOWNSTREAM", T0, work_fn=work)
    t2 = sched.run_job("DOWNSTREAM", T0 + timedelta(hours=1), work_fn=work)
    assert calls["n"] == 2
    assert t1.outputs_produced != t2.outputs_produced


def test_idempotent_replay_preserves_a_failed_result_too():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("fail_loud"), clock)  # feed never marked ready
    first = sched.run_job("DOWNSTREAM", T0, work_fn=lambda: {"result": 1})
    second = sched.run_job("DOWNSTREAM", T0, work_fn=lambda: {"result": 999})
    assert first.status == second.status == "failed"
    assert first == second


# --- heartbeat / missing-heartbeat visibility --------------------------------------

def test_health_unknown_for_a_run_never_started():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    assert sched.health("A", T0) == "unknown"


def test_health_running_shortly_after_heartbeat():
    clock = ManualClock(T0)
    sched = Scheduler(_three_job_chain(), clock)
    sched.begin_run("A", T0)
    clock.advance(timedelta(minutes=5))
    assert sched.health("A", T0, now=clock.now()) == "running"


def test_health_surfaces_missing_heartbeat_when_a_job_stops_reporting():
    clock = ManualClock(T0)
    jobs = [JobSpec("A", cadence="1h", heartbeat_timeout=timedelta(minutes=10))]
    sched = Scheduler(jobs, clock)
    sched.begin_run("A", T0)
    clock.advance(timedelta(minutes=11))  # past the heartbeat_timeout, never reported again
    assert sched.health("A", T0, now=clock.now()) == "missing_heartbeat"


def test_heartbeat_resets_the_missing_heartbeat_clock():
    clock = ManualClock(T0)
    jobs = [JobSpec("A", cadence="1h", heartbeat_timeout=timedelta(minutes=10))]
    sched = Scheduler(jobs, clock)
    sched.begin_run("A", T0)
    clock.advance(timedelta(minutes=8))
    sched.record_heartbeat("A", T0)
    clock.advance(timedelta(minutes=8))  # 8 min since the heartbeat, still within timeout
    assert sched.health("A", T0, now=clock.now()) == "running"


def test_health_after_completion_is_the_terminal_status_not_missing_heartbeat():
    clock = ManualClock(T0)
    jobs = [JobSpec("A", cadence="1h", heartbeat_timeout=timedelta(minutes=10))]
    sched = Scheduler(jobs, clock)
    sched.begin_run("A", T0)
    sched.record_completion("A", T0, outputs={}, status="success")
    clock.advance(timedelta(hours=5))  # long after completion
    assert sched.health("A", T0, now=clock.now()) == "success"


def test_heartbeat_on_a_never_started_run_raises():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    with pytest.raises(SchedulerError):
        sched.record_heartbeat("A", T0)


def test_completion_on_a_never_started_run_raises():
    sched = Scheduler(_three_job_chain(), ManualClock(T0))
    with pytest.raises(SchedulerError):
        sched.record_completion("A", T0, outputs={})


def test_work_fn_exception_is_recorded_as_failed_not_left_running():
    clock = ManualClock(T0)
    sched = Scheduler(_consumer("fail_loud"), clock)
    sched.mark_input_ready("feed", at=T0)

    def boom():
        raise RuntimeError("kaboom")

    rec = sched.run_job("DOWNSTREAM", T0, work_fn=boom)
    assert rec.status == "failed"
    assert "kaboom" in rec.detail
    assert sched.health("DOWNSTREAM", T0) == "failed"


# --- tier budget wired into run_job --------------------------------------------------

def test_tier_budget_exhaustion_defers_a_third_concurrent_job_in_same_tier():
    jobs = [JobSpec(f"J{i}", cadence="1h") for i in range(3)]
    clock = ManualClock(T0)
    sched = Scheduler(jobs, clock, tier_max_concurrent={"1h": 2})
    tb = sched.tiers["1h"]
    # simulate two still-in-flight jobs by acquiring directly
    assert tb.try_acquire("J0")
    assert tb.try_acquire("J1")
    rec = sched.run_job("J2", T0, work_fn=lambda: {})
    assert rec.status == "failed"
    assert "budget" in rec.detail
