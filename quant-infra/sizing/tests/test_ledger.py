"""Tests for sizing/ledger.py (IMP-17)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ceiling import resolve_position_size
from ledger import InMemorySizingLedger, JsonlSizingLedger


def test_in_memory_ledger_records_and_retrieves_with_correct_binding_constraint():
    ledger = InMemorySizingLedger()
    d1 = resolve_position_size(allocator_budget=10.0, portfolio_risk_ceiling=50.0)
    d2 = resolve_position_size(allocator_budget=0.0, portfolio_risk_ceiling=50.0)

    ledger.record("strat-a", d1, timestamp=1000.0)
    ledger.record("strat-a", d2, timestamp=1001.0)

    entries = ledger.entries_for("strat-a")
    assert len(entries) == 2
    assert entries[0].binding_constraint == "allocator"
    assert entries[0].approved_size == 10.0
    assert entries[1].binding_constraint == "zero_budget"
    assert entries[1].approved_size == 0.0


def test_in_memory_ledger_is_append_only_across_strategies():
    ledger = InMemorySizingLedger()
    d_a = resolve_position_size(allocator_budget=10.0, portfolio_risk_ceiling=20.0)
    d_b = resolve_position_size(allocator_budget=30.0, portfolio_risk_ceiling=5.0)
    ledger.record("strat-a", d_a, timestamp=1.0)
    ledger.record("strat-b", d_b, timestamp=2.0)

    assert len(ledger.entries_for("strat-a")) == 1
    assert len(ledger.entries_for("strat-b")) == 1
    all_entries = ledger.all_entries()
    assert len(all_entries) == 2
    assert {e.strategy_id for e in all_entries} == {"strat-a", "strat-b"}
    assert [e.binding_constraint for e in all_entries] == ["allocator", "portfolio_risk"]


def test_entries_for_unknown_strategy_is_empty_not_an_error():
    ledger = InMemorySizingLedger()
    assert ledger.entries_for("nope") == []


def test_jsonl_ledger_persists_and_reloads_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        ledger = JsonlSizingLedger(base)
        d = resolve_position_size(allocator_budget=15.0, portfolio_risk_ceiling=15.0)
        ledger.record("strat-c", d, timestamp=42.0)

        # a fresh ledger instance pointed at the same dir sees the same data
        ledger2 = JsonlSizingLedger(base)
        entries = ledger2.entries_for("strat-c")
        assert len(entries) == 1
        assert entries[0].binding_constraint == "both_equal"
        assert entries[0].approved_size == 15.0
        assert entries[0].timestamp == 42.0


def test_jsonl_ledger_append_only_never_overwrites_prior_lines():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = JsonlSizingLedger(tmp)
        d1 = resolve_position_size(allocator_budget=1.0, portfolio_risk_ceiling=2.0)
        d2 = resolve_position_size(allocator_budget=2.0, portfolio_risk_ceiling=1.0)
        ledger.record("strat-d", d1, timestamp=1.0)
        ledger.record("strat-d", d2, timestamp=2.0)

        entries = ledger.entries_for("strat-d")
        assert len(entries) == 2
        assert entries[0].binding_constraint == "allocator"
        assert entries[1].binding_constraint == "portfolio_risk"


def test_jsonl_ledger_all_entries_across_multiple_strategy_files():
    with tempfile.TemporaryDirectory() as tmp:
        ledger = JsonlSizingLedger(tmp)
        ledger.record(
            "strat-e",
            resolve_position_size(allocator_budget=0.0, portfolio_risk_ceiling=10.0),
            timestamp=5.0,
        )
        ledger.record(
            "strat-f",
            resolve_position_size(allocator_budget=10.0, portfolio_risk_ceiling=10.0),
            timestamp=3.0,
        )
        all_entries = ledger.all_entries()
        assert len(all_entries) == 2
        # sorted oldest-first across files
        assert all_entries[0].strategy_id == "strat-f"
        assert all_entries[1].strategy_id == "strat-e"
