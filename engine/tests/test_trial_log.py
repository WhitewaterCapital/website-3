"""Tests for MLVAL-02 trial logging: the running trial count is read back
from an append-only log (never supplied by the caller), and `report()`
refuses to ever emit a raw Sharpe without its deflated counterpart.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from incepta.validation.store import JsonlRecordStore
from incepta.validation.trial_log import default_store, log_trial, report


def _tmp_store():
    d = Path(tempfile.mkdtemp())
    return JsonlRecordStore(d), d


def test_log_trial_computes_and_stores_paired_deflated_sharpe():
    store, d = _tmp_store()
    try:
        rec = log_trial("model_a", {"lr": 0.01}, raw_sharpe=0.05, n_obs=500, store=store)
        assert rec["raw_sharpe"] == 0.05
        assert "deflated_sharpe_ratio" in rec
        assert 0.0 <= rec["deflated_sharpe_ratio"] <= 1.0
        assert rec["n_trials_at_log_time"] == 1
        assert rec["trial_index"] == 1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_running_trial_count_is_read_back_from_the_log_and_deflates_more():
    """Log the SAME raw Sharpe many times (simulating many configurations
    tried, abandoned ones included) and confirm the deflated Sharpe for a
    later trial is <= the deflated Sharpe of the first — exactly the
    'more trials searched -> lower confidence it's real' effect already
    proven for the raw metric in test_validation_and_backtest.py, but now
    exercised through the trial-count bookkeeping this module adds."""
    store, d = _tmp_store()
    try:
        first = log_trial("model_b", {"i": 0}, raw_sharpe=0.08, n_obs=1000, store=store)
        last = None
        for i in range(1, 50):
            last = log_trial("model_b", {"i": i}, raw_sharpe=0.08, n_obs=1000, store=store)
        assert last["n_trials_at_log_time"] == 50
        assert first["n_trials_at_log_time"] == 1
        assert last["deflated_sharpe_ratio"] <= first["deflated_sharpe_ratio"]
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_abandoned_trials_still_count_toward_n_trials():
    store, d = _tmp_store()
    try:
        for i in range(10):
            log_trial(
                "model_c", {"attempt": i, "abandoned": True},
                raw_sharpe=-0.5, n_obs=300, store=store,
            )
        good = log_trial(
            "model_c", {"final": True, "abandoned": False},
            raw_sharpe=0.15, n_obs=300, store=store,
        )
        assert good["n_trials_at_log_time"] == 11  # the 10 abandoned ones counted
        history = report("model_c", store=store)
        assert len(history) == 11
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_report_refuses_raw_only():
    store, d = _tmp_store()
    try:
        log_trial("model_d", {}, raw_sharpe=0.1, n_obs=500, store=store)
        with pytest.raises(RuntimeError):
            report("model_d", store=store, raw_only=True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_report_refuses_corrupted_record_missing_deflated_counterpart():
    store, d = _tmp_store()
    try:
        # Simulate a corrupted/hand-edited log: raw_sharpe with no deflated pair.
        store.append("model_e", {"model_id": "model_e", "raw_sharpe": 0.2})
        with pytest.raises(RuntimeError):
            report("model_e", store=store)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_report_raises_lookup_error_for_unknown_model():
    store, d = _tmp_store()
    try:
        with pytest.raises(LookupError):
            report("nonexistent_model", store=store)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_report_returns_full_paired_history():
    store, d = _tmp_store()
    try:
        for i in range(5):
            log_trial("model_f", {"i": i}, raw_sharpe=0.01 * i, n_obs=400, store=store)
        history = report("model_f", store=store)
        assert len(history) == 5
        for r in history:
            assert "raw_sharpe" in r and "deflated_sharpe_ratio" in r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_default_store_points_at_gitignored_trials_dir():
    store = default_store()
    assert store.base_dir.name == "_trials"
    assert store.base_dir.parent.name == "incepta"


def test_jsonl_record_store_append_list_get_roundtrip():
    d = Path(tempfile.mkdtemp())
    try:
        s = JsonlRecordStore(d)
        assert s.list("k") == []
        s.append("k", {"a": 1})
        s.append("k", {"a": 2})
        assert s.list("k") == [{"a": 1}, {"a": 2}]
        assert s.get("k", 0) == {"a": 1}
        assert s.get("k", 1) == {"a": 2}
        assert s.get("k", 5) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)
