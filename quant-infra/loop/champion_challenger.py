"""LOOP-01 — champion/challenger promotion gate.

The self-improvement loop never lets a challenger model take over the live
book just because it scored marginally better on one held-out run — noise in
a finite backtest can make a coin flip look like alpha. `promote()` only
promotes when the challenger clears the champion on the primary quality
metrics by MORE than a documented estimation-noise margin, AND does not lose
materially on either secondary (guardrail) metric. On a near-tie, the
champion is kept — promotion requires evidence, not a shrug.

**Vendored metrics.** This package is sealed/independent (per repo
convention — see `intra-exitus-engine/README.md`'s "shares no code and no
state" stance for the analogous engine). Two of the four metrics named in
the spec are small local copies of functions that already exist in
`engine/incepta/validation/metrics.py` (cited below, NOT imported — importing
would couple this sealed package's correctness to another engine's file
staying byte-for-byte compatible); the other two (`calibration_error`,
`turnover`) have no counterpart there and are implemented fresh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist
from typing import Literal

import numpy as np

_N = NormalDist()
_EULER = 0.5772156649015329


# --------------------------------------------------------------------------- #
# vendored metrics
# --------------------------------------------------------------------------- #

def rank_ic(pred, actual) -> float:
    """Spearman rank IC = Pearson correlation on the ranks.
    Vendored from `engine/incepta/validation/metrics.py::rank_ic` (same
    formula, copied rather than imported to keep this package sealed)."""
    a = np.asarray(pred, dtype=float)
    b = np.asarray(actual, dtype=float)
    m = ~(np.isnan(a) | np.isnan(b))
    a, b = a[m], b[m]
    if a.size < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a))
    rb = np.argsort(np.argsort(b))
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def _probabilistic_sharpe_ratio(sr, n_obs, sr_benchmark=0.0, skew=0.0, kurt=3.0) -> float:
    if n_obs < 2:
        return float("nan")
    denom = math.sqrt(1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2)
    if denom == 0:
        return float("nan")
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / denom
    return float(_N.cdf(z))


def deflated_sharpe_ratio(
    sr: float, n_obs: int, n_trials: int, sr_variance_across_trials: float,
    skew: float = 0.0, kurt: float = 3.0,
) -> float:
    """Bailey & Lopez de Prado (2014) deflated Sharpe.
    Vendored from `engine/incepta/validation/metrics.py::deflated_sharpe_ratio`
    (same formula, copied rather than imported to keep this package sealed)."""
    if n_trials <= 1 or sr_variance_across_trials <= 0:
        return _probabilistic_sharpe_ratio(sr, n_obs, 0.0, skew, kurt)
    sigma = math.sqrt(sr_variance_across_trials)
    e_max = (1 - _EULER) * _N.inv_cdf(1 - 1.0 / n_trials) + _EULER * _N.inv_cdf(
        1 - 1.0 / (n_trials * math.e)
    )
    sr_star = sigma * e_max
    return _probabilistic_sharpe_ratio(sr, n_obs, sr_star, skew, kurt)


def calibration_error(probs, outcomes, n_bins: int = 10) -> float:
    """Expected Calibration Error: bin predicted probabilities into `n_bins`
    equal-width bins and average |mean predicted prob - empirical frequency|
    within each non-empty bin, weighted by bin occupancy. No counterpart in
    `metrics.py` (which has Brier score but not binned calibration error) —
    implemented fresh here. Lower is better; 0 = perfectly calibrated."""
    p = np.asarray(probs, dtype=float)
    o = np.asarray(outcomes, dtype=float)
    m = ~(np.isnan(p) | np.isnan(o))
    p, o = p[m], o[m]
    if p.size == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    n = p.size
    for lo, hi in zip(edges[:-1], edges[1:]):
        in_bin = (p >= lo) & (p <= hi) if hi == edges[-1] else (p >= lo) & (p < hi)
        cnt = int(in_bin.sum())
        if cnt == 0:
            continue
        gap = abs(float(np.mean(p[in_bin])) - float(np.mean(o[in_bin])))
        total += (cnt / n) * gap
    return float(total)


def turnover(weights_over_time: np.ndarray) -> float:
    """Mean absolute period-over-period change in portfolio weights, summed
    across names each period then averaged across periods:
    `mean_t( sum_i |w_{i,t} - w_{i,t-1}| )`. No counterpart in `metrics.py` —
    implemented fresh. `weights_over_time` is (T periods x N names); needs at
    least 2 periods (turnover is undefined for a single snapshot)."""
    w = np.asarray(weights_over_time, dtype=float)
    if w.ndim != 2:
        raise ValueError("weights_over_time must be a 2D (T x N) array")
    if w.shape[0] < 2:
        return float("nan")
    diffs = np.abs(np.diff(w, axis=0)).sum(axis=1)
    return float(np.mean(diffs))


# --------------------------------------------------------------------------- #
# promotion gate
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ModelMetrics:
    """Held-out evaluation metrics for one model (champion or challenger).
    `rank_ic` and `deflated_sharpe` are PRIMARY quality metrics (higher
    better) — these must clear the noise margin. `calibration_error` and
    `turnover` are SECONDARY guardrails (lower better) — the challenger must
    not regress materially on either, even if it wins on the primaries."""
    rank_ic: float
    deflated_sharpe: float
    calibration_error: float
    turnover: float


@dataclass(frozen=True)
class NoiseEstimate:
    """Estimation-noise margins the challenger's primary-metric improvement
    must clear, and tolerances for how much the secondary guardrails may
    regress without blocking promotion. All must be non-negative."""
    rank_ic_margin: float
    deflated_sharpe_margin: float
    calibration_error_tolerance: float
    turnover_tolerance: float


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reason: str
    primary_improvement: dict[str, float]   # metric -> challenger - champion
    secondary_regression: dict[str, float]  # metric -> challenger - champion (positive = worse)
    secondary_checks: dict[str, bool]       # metric -> passed guardrail


def promote(
    champion_metrics: ModelMetrics,
    challenger_metrics: ModelMetrics,
    noise_estimate: NoiseEstimate,
) -> PromotionDecision:
    """Promote the challenger only if BOTH primary metrics beat the champion
    by more than their noise margin, AND neither secondary metric regresses
    beyond its tolerance. A marginal edge (within the noise margin) is
    treated as a tie and does NOT promote — the champion is the safe default.

    Any NaN in either model's metrics makes a sound comparison impossible;
    `promote=False` in that case (never promoted on missing information),
    with the offending metric named in `reason`.
    """
    all_fields = ["rank_ic", "deflated_sharpe", "calibration_error", "turnover"]
    for name in all_fields:
        if np.isnan(getattr(champion_metrics, name)) or np.isnan(getattr(challenger_metrics, name)):
            return PromotionDecision(
                promote=False,
                reason=f"cannot compare: NaN in metric {name!r} (champion or challenger)",
                primary_improvement={},
                secondary_regression={},
                secondary_checks={},
            )
    for name, val in (
        ("rank_ic_margin", noise_estimate.rank_ic_margin),
        ("deflated_sharpe_margin", noise_estimate.deflated_sharpe_margin),
        ("calibration_error_tolerance", noise_estimate.calibration_error_tolerance),
        ("turnover_tolerance", noise_estimate.turnover_tolerance),
    ):
        if val < 0:
            raise ValueError(f"NoiseEstimate.{name} must be non-negative, got {val}")

    rank_ic_gain = challenger_metrics.rank_ic - champion_metrics.rank_ic
    dsr_gain = challenger_metrics.deflated_sharpe - champion_metrics.deflated_sharpe
    primary_improvement = {"rank_ic": rank_ic_gain, "deflated_sharpe": dsr_gain}

    primary_pass = (
        rank_ic_gain > noise_estimate.rank_ic_margin
        and dsr_gain > noise_estimate.deflated_sharpe_margin
    )

    calib_regression = challenger_metrics.calibration_error - champion_metrics.calibration_error
    turnover_regression = challenger_metrics.turnover - champion_metrics.turnover
    secondary_regression = {"calibration_error": calib_regression, "turnover": turnover_regression}
    secondary_checks = {
        "calibration_error": calib_regression <= noise_estimate.calibration_error_tolerance,
        "turnover": turnover_regression <= noise_estimate.turnover_tolerance,
    }
    secondary_pass = all(secondary_checks.values())

    should_promote = primary_pass and secondary_pass
    if should_promote:
        reason = "challenger cleared both primary-metric noise margins with no material secondary regression"
    elif not primary_pass:
        reason = "primary-metric improvement did not clear the estimation-noise margin; champion retained"
    else:
        failed = [k for k, v in secondary_checks.items() if not v]
        reason = f"primary metrics cleared but secondary guardrail(s) regressed materially: {failed}"

    return PromotionDecision(
        promote=should_promote,
        reason=reason,
        primary_improvement=primary_improvement,
        secondary_regression=secondary_regression,
        secondary_checks=secondary_checks,
    )
