"""MLVAL-03 — calibration and abstention testing.

"Accuracy is not enough. A model right sixty percent of the time that says
ninety percent will destroy the allocator, because the allocator treats the
number as a probability." This module builds the reliability curve, the
expected calibration error (ECE), and the classical Murphy (1973) three-term
Brier decomposition (Brier = Reliability - Resolution + Uncertainty) that
`validation/metrics.py`'s plain `brier_score()` does not break out on its own.
It also reports the abstention gate's own honesty: performance on the traded
subset vs. the abstained subset, so "if the abstained subset would have been
profitable, the gate is wrong" is a number, not a feeling.

`graduation.py`'s `GraduationRecord.calibration_error` / `gate_calibration()`
already gate on a raw calibration-error float, taken as an upstream input by
design ("again computed upstream from metrics.brier_score") — this module
IS that upstream computation. `reliability_curve(...).expected_calibration_error`
is meant to be fed directly into that field.

Uses only numpy + stdlib, matching `metrics.py`'s own dependency discipline
(no scipy/sklearn).

Validation note: as directed, this module is exercised here only against
synthetic/constructed probability data — no real model has produced real
shadow-mode predictions in this environment yet. Wiring `reliability_curve`
as the actual upstream source of a REAL model's `GraduationRecord.calibration_error`
during a live shadow-mode run is future work, once a real model exists to
calibrate against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .metrics import _clean_pair, brier_score, hit_rate, information_coefficient, sharpe, sortino


@dataclass
class ReliabilityBin:
    """One non-empty bin of the reliability curve."""

    lo: float
    hi: float
    mean_predicted: float
    observed_frequency: float
    count: int


@dataclass
class ReliabilityCurve:
    """The reliability curve plus its summary calibration-error figure.

    `expected_calibration_error` is the count-weighted mean absolute gap
    between mean predicted probability and observed frequency across bins —
    this is exactly the `calibration_error` figure `graduation.py`'s
    `GraduationRecord`/`gate_calibration()` expects as an upstream input.
    """

    bins: list = field(default_factory=list)   # list[ReliabilityBin]
    n_bins: int = 10
    n_obs: int = 0
    expected_calibration_error: float = float("nan")


def reliability_curve(probs, outcomes, n_bins: int = 10) -> ReliabilityCurve:
    """Bin predicted probabilities into `n_bins` equal-width bins over [0, 1]
    (0-0.1, 0.1-0.2, ... for the default n_bins=10). For each non-empty bin,
    report the mean predicted probability, the observed frequency of
    outcome == 1, and the bin count. `expected_calibration_error` (ECE) is the
    count-weighted mean absolute difference between mean_predicted and
    observed_frequency across non-empty bins:

        ECE = sum_b (count_b / N) * |mean_predicted_b - observed_frequency_b|

    NaN pairs are dropped first (consistent with `metrics._clean_pair`).
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    p, o = _clean_pair(probs, outcomes)
    if p.size == 0:
        return ReliabilityCurve(bins=[], n_bins=n_bins, n_obs=0, expected_calibration_error=float("nan"))

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # right-inclusive on the final bin only, so p == 1.0 lands in the last bin
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, n_bins - 1)

    bins: list[ReliabilityBin] = []
    weighted_abs_gap = 0.0
    n = p.size
    for b in range(n_bins):
        mask = idx == b
        count = int(mask.sum())
        if count == 0:
            continue
        mean_pred = float(p[mask].mean())
        obs_freq = float(o[mask].mean())
        bins.append(
            ReliabilityBin(
                lo=float(edges[b]), hi=float(edges[b + 1]),
                mean_predicted=mean_pred, observed_frequency=obs_freq, count=count,
            )
        )
        weighted_abs_gap += count * abs(mean_pred - obs_freq)

    ece = weighted_abs_gap / n
    return ReliabilityCurve(bins=bins, n_bins=n_bins, n_obs=n, expected_calibration_error=float(ece))


@dataclass
class BrierDecomposition:
    """Murphy (1973) three-term decomposition: Brier = Reliability - Resolution
    + Uncertainty. Reliability (a.k.a. calibration-in-the-large term, lower is
    better) measures how far each bin's mean prediction is from its observed
    frequency; Resolution (higher is better, subtracted) measures how much the
    bins' observed frequencies vary from the overall base rate — i.e. how much
    the forecast actually discriminates; Uncertainty is the irreducible
    variance of the outcome itself (base_rate * (1 - base_rate)), independent
    of the forecaster.
    """

    reliability: float
    resolution: float
    uncertainty: float
    brier: float          # reliability - resolution + uncertainty (reconstructed)
    curve: ReliabilityCurve


def brier_decomposition(probs, outcomes, n_bins: int = 10) -> BrierDecomposition:
    """Classical bin-based Murphy (1973) decomposition, reusing
    `reliability_curve`'s binning so the two stay consistent:

        Reliability  = sum_b (n_b/N) * (mean_predicted_b - observed_freq_b)^2
        Resolution   = sum_b (n_b/N) * (observed_freq_b - base_rate)^2
        Uncertainty  = base_rate * (1 - base_rate)
        Brier        = Reliability - Resolution + Uncertainty

    This is verified in tests to reconstruct plain `metrics.brier_score`
    within floating-point tolerance.
    """
    p, o = _clean_pair(probs, outcomes)
    curve = reliability_curve(p, o, n_bins=n_bins)
    if curve.n_obs == 0:
        nan = float("nan")
        return BrierDecomposition(nan, nan, nan, nan, curve)

    n = curve.n_obs
    base_rate = float(o.mean())
    reliability = 0.0
    resolution = 0.0
    for bn in curve.bins:
        w = bn.count / n
        reliability += w * (bn.mean_predicted - bn.observed_frequency) ** 2
        resolution += w * (bn.observed_frequency - base_rate) ** 2
    uncertainty = base_rate * (1.0 - base_rate)
    brier = reliability - resolution + uncertainty

    return BrierDecomposition(
        reliability=float(reliability), resolution=float(resolution),
        uncertainty=float(uncertainty), brier=float(brier), curve=curve,
    )


@dataclass
class SubsetReport:
    """Performance summary for one subset (traded or abstained)."""

    count: int
    hit_rate: float = float("nan")
    information_coefficient: float = float("nan")
    brier_score: float = float("nan")
    sharpe: float = float("nan")
    sortino: float = float("nan")


@dataclass
class AbstentionReport:
    """Traded-vs-abstained performance split, plus a `gate_looks_wrong` flag.

    Trip condition for `gate_looks_wrong` (documented explicitly, per spec,
    since this is a judgment call):

    The metric actually used to decide is `hit_rate` whenever both subsets
    have at least one prediction whose sign is decidable (predictions are
    treated as return-like: hit_rate measures whether the demeaned prediction
    sign matches the outcome sign) — this is the direct operationalisation of
    "if the abstained subset would have been profitable, the gate is wrong".
    We flip to comparing `brier_score` instead (lower = better; the gate is
    wrong if the abstained subset is MORE calibrated, i.e. its Brier score is
    materially lower) only when `is_probability` is True, i.e. the caller
    tells us `predictions` are probabilities rather than signed return-like
    scores, since hit_rate on raw probabilities (which are all >= 0) is not
    meaningful.

    The trip margin is `margin` (default 0.05): the gate looks wrong when
        abstained_metric - traded_metric > margin      (hit_rate: higher wins)
        traded_metric - abstained_metric > margin        (brier: lower wins)
    i.e. the abstained subset beats the traded subset by more than `margin`
    on whichever metric is in play. A tie or the traded subset performing
    better never trips it.
    """

    traded: SubsetReport
    abstained: SubsetReport
    metric_used: str
    margin: float
    gate_looks_wrong: bool


def abstention_gate_report(
    predictions,
    outcomes,
    fired_mask,
    weights=None,
    is_probability: bool = False,
    margin: float = 0.05,
) -> AbstentionReport:
    """Split `predictions`/`outcomes` by boolean `fired_mask` (True = traded,
    False = abstained) and report a performance summary for each subset
    separately, reusing `metrics.py`'s existing `hit_rate`,
    `information_coefficient`, `brier_score`, `sharpe` and `sortino`.

    `weights` is accepted for API symmetry with the rest of the codebase but
    is currently unused by any of the underlying `metrics.py` functions
    (none of them are weighted) — reserved for future use, not silently
    misapplied.

    Set `is_probability=True` when `predictions` are probabilities (0-1) so
    the wrongness check compares `brier_score` instead of `hit_rate` (see
    `AbstentionReport` docstring for the exact trip condition).
    """
    pred = np.asarray(predictions, dtype=float)
    out = np.asarray(outcomes, dtype=float)
    fired = np.asarray(fired_mask, dtype=bool)
    if pred.shape != out.shape or pred.shape != fired.shape:
        raise ValueError("predictions, outcomes and fired_mask must be the same shape")

    def _subset_report(mask) -> SubsetReport:
        p, o = pred[mask], out[mask]
        count = int(mask.sum())
        if count == 0:
            return SubsetReport(count=0)
        report = SubsetReport(
            count=count,
            hit_rate=hit_rate(p, o),
            information_coefficient=information_coefficient(p, o),
        )
        if is_probability:
            report.brier_score = brier_score(p, o)
        else:
            report.sharpe = sharpe(o)
            report.sortino = sortino(o)
        return report

    traded = _subset_report(fired)
    abstained = _subset_report(~fired)

    if is_probability:
        metric_used = "brier_score"
        gate_looks_wrong = (
            traded.count > 0 and abstained.count > 0
            and not np.isnan(traded.brier_score) and not np.isnan(abstained.brier_score)
            and (traded.brier_score - abstained.brier_score) > margin
        )
    else:
        metric_used = "hit_rate"
        gate_looks_wrong = (
            traded.count > 0 and abstained.count > 0
            and not np.isnan(traded.hit_rate) and not np.isnan(abstained.hit_rate)
            and (abstained.hit_rate - traded.hit_rate) > margin
        )

    return AbstentionReport(
        traded=traded, abstained=abstained,
        metric_used=metric_used, margin=margin,
        gate_looks_wrong=bool(gate_looks_wrong),
    )


def calibration_gate_check(reliability_curve_result: ReliabilityCurve, tolerance: float = 0.05) -> bool:
    """Literal wrapper around the same check `graduation.py`'s
    `GraduationRecord.gate_calibration()` performs manually against a raw
    `calibration_error` float: is the (absolute) calibration error inside a
    stated tolerance? Does not modify or call into `graduation.py` — it
    exists to make explicit that `reliability_curve(...).expected_calibration_error`
    is the number that gate consumes.
    """
    ece = reliability_curve_result.expected_calibration_error
    return ece is not None and not np.isnan(ece) and abs(ece) <= tolerance
