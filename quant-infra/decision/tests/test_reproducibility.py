"""Tests for decision/reproducibility.py (IMP-19)."""

from __future__ import annotations

import json

from boundary import BoundaryResult
from idea import DecisionOutput
from reproducibility import build_decision_replay_record


def test_build_record_is_json_serializable_and_round_trips_key_fields():
    decision = DecisionOutput(is_good_idea=True, confidence=0.75, rationale="looks good")
    allocator_inputs = {"strategies": ["strat-a", "strat-b"], "risk_aversion": 1.0}
    boundary = BoundaryResult(
        weights={"strat-a": 0.2, "strat-b": 0.1},
        source="allocator",
        alarm_raised=False,
        reason=None,
        allocator_result=None,
        fallback_shrinkage=None,
    )

    record = build_decision_replay_record(decision, allocator_inputs, boundary)

    # must actually be JSON-serialisable, not just "dict-shaped"
    serialized = json.dumps(record)
    reloaded = json.loads(serialized)

    assert reloaded["decision"]["is_good_idea"] is True
    assert reloaded["decision"]["confidence"] == 0.75
    assert reloaded["allocator_inputs"]["risk_aversion"] == 1.0
    assert reloaded["boundary"]["source"] == "allocator"
    assert reloaded["boundary"]["weights"]["strat-a"] == 0.2


def test_build_record_on_fallback_path_captures_alarm_and_reason():
    decision = DecisionOutput(is_good_idea=None, confidence=0.2, rationale="inconclusive")
    boundary = BoundaryResult(
        weights={"strat-a": 0.5, "strat-b": 0.5},
        source="fallback",
        alarm_raised=True,
        reason="allocator_solve_fn raised an exception: RuntimeError('boom')",
        allocator_result=None,
        fallback_shrinkage=0.5,
    )

    record = build_decision_replay_record(decision, allocator_inputs=None, boundary_result=boundary)
    serialized = json.dumps(record)
    reloaded = json.loads(serialized)

    assert reloaded["boundary"]["alarm_raised"] is True
    assert "raised an exception" in reloaded["boundary"]["reason"]
    assert reloaded["boundary"]["fallback_shrinkage"] == 0.5
    assert reloaded["allocator_inputs"] is None


def test_build_record_handles_nested_dataclass_allocator_result():
    # Simulate an allocator_result-like nested dataclass structure to make
    # sure _to_jsonable recurses into it correctly rather than choking.
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Nested:
        solution: dict
        feasible: bool

    decision = DecisionOutput(is_good_idea=True, confidence=0.9, rationale="ok")
    boundary = BoundaryResult(
        weights={"strat-a": 1.0},
        source="allocator",
        alarm_raised=False,
        reason=None,
        allocator_result=_Nested(solution={"strat-a": 1.0}, feasible=True),
        fallback_shrinkage=None,
    )

    record = build_decision_replay_record(decision, {"n": 1}, boundary)
    serialized = json.dumps(record)  # must not raise
    reloaded = json.loads(serialized)
    assert reloaded["boundary"]["allocator_result"]["feasible"] is True
    assert reloaded["boundary"]["allocator_result"]["solution"]["strat-a"] == 1.0
