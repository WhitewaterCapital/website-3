"""Tests for MLVAL-03 calibration and abstention testing: reliability curve /
ECE, the Murphy (1973) Brier decomposition identity, the abstention-gate
report's traded-vs-abstained split and its `gate_looks_wrong` trip condition,
and the end-to-end composition with `graduation.py`'s real gate."""

from __future__ import annotations

import numpy as np

from incepta.validation.calibration import (
    abstention_gate_report,
    brier_decomposition,
    calibration_gate_check,
    reliability_curve,
)
from incepta.validation.graduation import GraduationRecord
from incepta.validation.metrics import brier_score


# ---- reliability_curve / ECE ----------------------------------------------
def test_perfectly_calibrated_case_has_near_zero_ece():
    rng = np.random.default_rng(0)
    # 10 probability levels, each fed outcomes at exactly that rate (large N
    # per level so the empirical frequency converges tightly to p).
    levels = np.linspace(0.05, 0.95, 10)
    probs, outcomes = [], []
    n_per_level = 5000
    for p in levels:
        probs.extend([p] * n_per_level)
        outcomes.extend((rng.random(n_per_level) < p).astype(float))
    curve = reliability_curve(probs, outcomes, n_bins=10)
    assert curve.n_obs == len(probs)
    assert curve.expected_calibration_error < 0.01


def test_overconfident_case_produces_large_correctly_signed_ece():
    # The doc's own example: "a model right sixty percent of the time that
    # says ninety percent" -- predicted prob is always 0.9, true hit rate 0.6.
    rng = np.random.default_rng(1)
    n = 4000
    probs = np.full(n, 0.9)
    outcomes = (rng.random(n) < 0.6).astype(float)
    curve = reliability_curve(probs, outcomes, n_bins=10)
    # Single bin (all mass at 0.9): mean_predicted ~0.9, observed ~0.6 -> gap ~0.3
    assert len(curve.bins) == 1
    assert curve.bins[0].mean_predicted > 0.85
    assert 0.5 < curve.bins[0].observed_frequency < 0.7
    assert curve.expected_calibration_error > 0.2  # large
    # correctly signed: predicted overstates the true rate
    assert curve.bins[0].mean_predicted > curve.bins[0].observed_frequency


def test_reliability_curve_bin_counts_and_edges():
    probs = [0.05, 0.05, 0.15, 0.95]
    outcomes = [0, 1, 1, 1]
    curve = reliability_curve(probs, outcomes, n_bins=10)
    counts = {(): None}
    total = sum(b.count for b in curve.bins)
    assert total == 4
    # bin [0.0,0.1) should hold the two 0.05 preds
    first = [b for b in curve.bins if b.lo == 0.0][0]
    assert first.count == 2
    assert abs(first.mean_predicted - 0.05) < 1e-9
    assert abs(first.observed_frequency - 0.5) < 1e-9  # one of two outcomes is 1


def test_reliability_curve_empty_input_is_nan_not_crash():
    curve = reliability_curve([], [], n_bins=10)
    assert curve.n_obs == 0
    assert np.isnan(curve.expected_calibration_error)


# ---- Brier decomposition identity -----------------------------------------
def _assert_decomposition_matches_plain_brier(probs, outcomes, n_bins=10, tol=1e-9):
    dec = brier_decomposition(probs, outcomes, n_bins=n_bins)
    reconstructed = dec.reliability - dec.resolution + dec.uncertainty
    plain = brier_score(probs, outcomes)
    assert abs(reconstructed - plain) < tol
    assert abs(dec.brier - plain) < tol


def test_brier_decomposition_identity_trivial_case():
    # constant prediction, deterministic outcomes
    probs = [0.5, 0.5, 0.5, 0.5]
    outcomes = [0, 1, 0, 1]
    _assert_decomposition_matches_plain_brier(probs, outcomes, n_bins=5)


def test_brier_decomposition_identity_perfect_forecaster():
    probs = [0.0, 1.0, 0.0, 1.0, 0.0]
    outcomes = [0, 1, 0, 1, 0]
    _assert_decomposition_matches_plain_brier(probs, outcomes, n_bins=10)


def test_brier_decomposition_identity_nontrivial_random_case():
    # The classical Murphy decomposition is exact only when the forecast
    # value is constant WITHIN each bin (otherwise binning to a mean forecast
    # per bin discards genuine within-bin forecast dispersion and the
    # identity becomes an approximation, not an equality). So this
    # "non-trivial" case uses 10 distinct forecast levels, one per bin, each
    # with its OWN randomly chosen true hit rate decoupled from the forecast
    # value itself (i.e. genuinely miscalibrated, varying by level) -- this
    # is non-trivial (multiple bins, non-uniform miscalibration) while still
    # keeping forecasts constant per bin so the identity holds exactly.
    rng = np.random.default_rng(42)
    centers = np.linspace(0.05, 0.95, 10)
    true_rates = rng.uniform(0.1, 0.9, size=10)
    n_per_level = 300
    probs, outcomes = [], []
    for c, r in zip(centers, true_rates):
        probs.extend([c] * n_per_level)
        outcomes.extend((rng.random(n_per_level) < r).astype(float))
    _assert_decomposition_matches_plain_brier(probs, outcomes, n_bins=10, tol=1e-9)


def test_brier_decomposition_identity_miscalibrated_case():
    rng = np.random.default_rng(7)
    n = 300
    probs = np.full(n, 0.9)
    outcomes = (rng.random(n) < 0.6).astype(float)
    _assert_decomposition_matches_plain_brier(probs, outcomes, n_bins=10)
    dec = brier_decomposition(probs, outcomes, n_bins=10)
    # single-bin case -> reliability is the whole (mean_pred - obs_freq)^2 term,
    # resolution is 0 (only one bin, so its observed freq equals the base rate)
    assert dec.resolution == 0.0
    assert dec.reliability > 0.05


# ---- abstention gate report -------------------------------------------------
def test_abstention_report_splits_by_count_and_metric():
    # 4 traded (all predictions correctly signed vs outcome -> hit_rate should
    # reflect that), 2 abstained.
    predictions = np.array([1.0, 1.0, -1.0, -1.0, 0.5, -0.5])
    outcomes = np.array([0.01, 0.02, -0.01, -0.02, 0.03, -0.03])
    fired_mask = np.array([True, True, True, True, False, False])

    report = abstention_gate_report(predictions, outcomes, fired_mask)
    assert report.traded.count == 4
    assert report.abstained.count == 2
    # traded subset: demeaned predictions/outcomes perfectly sign-matched
    assert report.traded.hit_rate == 1.0
    assert report.metric_used == "hit_rate"


def test_abstention_report_probability_mode_uses_brier():
    predictions = np.array([0.9, 0.9, 0.9, 0.9, 0.1, 0.1])
    outcomes = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
    fired_mask = np.array([True, True, True, True, False, False])
    report = abstention_gate_report(
        predictions, outcomes, fired_mask, is_probability=True
    )
    assert report.metric_used == "brier_score"
    # traded: brier = (0.9-1)^2 = 0.01 ; abstained: brier = (0.1-1)^2 = 0.81
    assert abs(report.traded.brier_score - 0.01) < 1e-9
    assert abs(report.abstained.brier_score - 0.81) < 1e-9


def test_gate_looks_wrong_trips_on_inverted_case():
    # Abstained subset is clearly MORE profitable (better hit rate) than
    # traded. NOTE: `metrics.hit_rate` demeans by the SUBSET's own mean before
    # comparing signs, so each subset's predictions must have some variation
    # around zero for the sign comparison to be meaningful (an all-identical
    # -- zero-variance -- prediction subset demeans to all-zero and is
    # sign-degenerate, not "correct").
    predictions = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    outcomes = np.array([-0.01, 0.01, -0.02, 0.02, 0.01, -0.01, 0.02, -0.02])
    # traded = first 4 (all sign-mismatched -> hit_rate 0.0),
    # abstained = last 4 (all sign-matched -> hit_rate 1.0)
    fired_mask = np.array([True, True, True, True, False, False, False, False])
    report = abstention_gate_report(predictions, outcomes, fired_mask, margin=0.05)
    assert report.traded.hit_rate == 0.0
    assert report.abstained.hit_rate == 1.0
    assert report.gate_looks_wrong is True


def test_gate_looks_wrong_does_not_trip_on_normal_case():
    # Traded subset performs at least as well as abstained -> gate is fine.
    predictions = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    outcomes = np.array([0.01, -0.01, 0.02, -0.02, -0.01, 0.01, -0.02, 0.02])
    # traded = first 4 (all sign-matched -> hit_rate 1.0),
    # abstained = last 4 (all sign-mismatched -> hit_rate 0.0)
    fired_mask = np.array([True, True, True, True, False, False, False, False])
    report = abstention_gate_report(predictions, outcomes, fired_mask, margin=0.05)
    assert report.traded.hit_rate == 1.0
    assert report.abstained.hit_rate == 0.0
    assert report.gate_looks_wrong is False


# ---- end-to-end integration with graduation.py -----------------------------
def test_calibration_gate_check_matches_graduation_gate_calibration():
    tolerance = 0.05

    # Well-calibrated synthetic case -> low ECE -> gate should PASS.
    rng = np.random.default_rng(2)
    n = 5000
    probs_good = rng.random(n)
    outcomes_good = (rng.random(n) < probs_good).astype(float)
    curve_good = reliability_curve(probs_good, outcomes_good, n_bins=10)

    assert calibration_gate_check(curve_good, tolerance=tolerance) is True

    record_good = GraduationRecord(
        model_id="model_good",
        calibration_error=curve_good.expected_calibration_error,
        calibration_tolerance=tolerance,
    )
    assert record_good.gate_calibration() == calibration_gate_check(curve_good, tolerance=tolerance)
    assert record_good.gate_calibration() is True

    # Poorly-calibrated synthetic case (the doc's 60%/90% example) -> high ECE
    # -> gate should FAIL.
    rng2 = np.random.default_rng(3)
    probs_bad = np.full(n, 0.9)
    outcomes_bad = (rng2.random(n) < 0.6).astype(float)
    curve_bad = reliability_curve(probs_bad, outcomes_bad, n_bins=10)

    assert calibration_gate_check(curve_bad, tolerance=tolerance) is False

    record_bad = GraduationRecord(
        model_id="model_bad",
        calibration_error=curve_bad.expected_calibration_error,
        calibration_tolerance=tolerance,
    )
    assert record_bad.gate_calibration() == calibration_gate_check(curve_bad, tolerance=tolerance)
    assert record_bad.gate_calibration() is False
