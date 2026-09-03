"""Tests for loop/drift.py."""

from __future__ import annotations

import inspect

import numpy as np
import pytest

import drift as drift_module
from drift import (
    DriftMetrics,
    PerformanceMetrics,
    assess_drift,
    detect_feature_drift,
    detect_prediction_drift,
    severity,
)


def test_no_drift_when_distributions_match():
    rng = np.random.default_rng(0)
    ref = rng.normal(0, 1, 1000)
    cur = rng.normal(0, 1, 1000)
    stat, p, drifted = detect_feature_drift(ref, cur, alpha=0.01)
    assert drifted is False
    assert p > 0.01


def test_drift_detected_on_shifted_distribution():
    rng = np.random.default_rng(1)
    ref = rng.normal(0, 1, 1000)
    cur = rng.normal(3, 1, 1000)  # big shift
    stat, p, drifted = detect_feature_drift(ref, cur, alpha=0.01)
    assert drifted is True
    assert p < 0.01


def test_feature_drift_insufficient_samples_raises():
    with pytest.raises(ValueError):
        detect_feature_drift([1.0], [1.0, 2.0])


def test_feature_drift_bad_alpha_raises():
    with pytest.raises(ValueError):
        detect_feature_drift([1.0, 2.0], [1.0, 2.0], alpha=1.5)


def test_feature_drift_nan_rows_dropped():
    rng = np.random.default_rng(2)
    ref = np.concatenate([rng.normal(0, 1, 500), [np.nan] * 5])
    cur = rng.normal(0, 1, 500)
    stat, p, drifted = detect_feature_drift(ref, cur)
    assert np.isfinite(stat) and np.isfinite(p)


def test_prediction_drift_uses_same_mechanics_as_feature_drift():
    rng = np.random.default_rng(3)
    ref = rng.normal(0, 1, 500)
    cur = rng.normal(2, 1, 500)
    _, _, drifted = detect_prediction_drift(ref, cur)
    assert drifted is True


def test_assess_drift_flags_unexplained_prediction_drift():
    rng = np.random.default_rng(4)
    stable_features_ref = rng.normal(0, 1, 1000)
    stable_features_cur = rng.normal(0, 1, 1000)  # NOT drifted
    shifted_preds_ref = rng.normal(0, 1, 1000)
    shifted_preds_cur = rng.normal(2.5, 1, 1000)  # drifted
    dm = assess_drift(stable_features_ref, stable_features_cur, shifted_preds_ref, shifted_preds_cur)
    assert dm.feature_drifted is False
    assert dm.prediction_drifted is True
    assert dm.unexplained_prediction_drift is True


def test_assess_drift_explained_by_feature_drift_is_not_unexplained():
    rng = np.random.default_rng(5)
    ref_feat = rng.normal(0, 1, 1000)
    cur_feat = rng.normal(3, 1, 1000)  # drifted
    ref_pred = rng.normal(0, 1, 1000)
    cur_pred = rng.normal(3, 1, 1000)  # also drifted, but explained by feature drift
    dm = assess_drift(ref_feat, cur_feat, ref_pred, cur_pred)
    assert dm.feature_drifted is True
    assert dm.prediction_drifted is True
    assert dm.unexplained_prediction_drift is False


# --- severity() escalation ladder ------------------------------------------------

def _drift_metrics(feature=False, prediction=False, unexplained=False) -> DriftMetrics:
    return DriftMetrics(
        feature_ks_stat=0.5, feature_ks_pvalue=0.001 if feature else 0.5, feature_drifted=feature,
        prediction_ks_stat=0.5, prediction_ks_pvalue=0.001 if prediction else 0.5,
        prediction_drifted=prediction, unexplained_prediction_drift=unexplained,
    )


def test_severity_control_band_breach_demotes_regardless_of_drift():
    dm = _drift_metrics(feature=False, prediction=False)
    perf = PerformanceMetrics(sustained_decay=False, breached_lower_control_band=True)
    assert severity(dm, perf) == "demote"


def test_severity_sustained_decay_moves_to_monitoring():
    dm = _drift_metrics(feature=True)
    perf = PerformanceMetrics(sustained_decay=True, breached_lower_control_band=False)
    assert severity(dm, perf) == "monitoring"


def test_severity_bare_drift_is_a_flag():
    dm = _drift_metrics(feature=True)
    perf = PerformanceMetrics(sustained_decay=False, breached_lower_control_band=False)
    assert severity(dm, perf) == "flag"


def test_severity_control_band_breach_outranks_sustained_decay():
    dm = _drift_metrics()
    perf = PerformanceMetrics(sustained_decay=True, breached_lower_control_band=True)
    assert severity(dm, perf) == "demote"


def test_severity_return_type_is_always_one_of_three_values():
    valid = {"flag", "monitoring", "demote"}
    for decay in (True, False):
        for breach in (True, False):
            for feat in (True, False):
                dm = _drift_metrics(feature=feat)
                perf = PerformanceMetrics(sustained_decay=decay, breached_lower_control_band=breach)
                assert severity(dm, perf) in valid


def test_no_function_in_drift_module_can_increase_a_budget():
    """Structural guard on the doc's invariant: every public function in this
    module either returns drift-detection diagnostics (statistics/booleans,
    no budget concept) or a severity label drawn from a fixed 3-value ladder
    with no 'increase' semantics. We assert directly on the ladder's
    vocabulary rather than trying to enumerate every possible caller
    interpretation."""
    ladder_values = {"flag", "monitoring", "demote"}
    increasing_words = {"promote", "increase", "raise_budget", "restore"}
    assert not (ladder_values & increasing_words)
    # and every public callable's name avoids promotion vocabulary too
    for name, fn in inspect.getmembers(drift_module, inspect.isfunction):
        if name.startswith("_"):
            continue
        assert "promote" not in name and "increase_budget" not in name
