"""LOOP-02 — drift detection and the escalation ladder.

The doc's escalation ladder, implemented exactly: "Drift raises a flag.
Sustained decay moves the model to monitoring. Breaching the lower control
band demotes it to shadow and sets its budget to zero. Demotion is
automatic, promotion never is."

This module can only ever move a model DOWN the ladder (flag -> monitoring
-> demote) or leave it where it is — there is no function here that can
increase a budget or promote a model. Promotion lives exclusively in
`champion_challenger.promote()`, which is a deliberate, opt-in decision, not
an automatic response to metrics. `severity()`'s only three possible outputs
are the three rungs of the ladder; nothing in this module can hand back a
value that means "give it more capital."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy.stats import ks_2samp

Severity = Literal["flag", "monitoring", "demote"]


@dataclass(frozen=True)
class DriftMetrics:
    feature_ks_stat: float
    feature_ks_pvalue: float
    feature_drifted: bool
    prediction_ks_stat: float
    prediction_ks_pvalue: float
    prediction_drifted: bool
    unexplained_prediction_drift: bool  # predictions drifted while features did not


@dataclass(frozen=True)
class PerformanceMetrics:
    """Pre-computed signals about live performance decay. Building these from
    a raw performance history (e.g. a rolling IC control chart) is out of
    scope for this module — it consumes the two booleans a monitoring
    process would already be tracking."""
    sustained_decay: bool              # performance has decayed over a sustained window
    breached_lower_control_band: bool  # performance crossed the hard statistical floor


def _clean_pair(reference, current) -> tuple[np.ndarray, np.ndarray]:
    r = np.asarray(reference, dtype=float)
    c = np.asarray(current, dtype=float)
    r = r[~np.isnan(r)]
    c = c[~np.isnan(c)]
    return r, c


def detect_feature_drift(
    reference: np.ndarray, current: np.ndarray, alpha: float = 0.01
) -> tuple[float, float, bool]:
    """Two-sample Kolmogorov-Smirnov test of `current` feature values against
    a stored training-time `reference` distribution. Returns
    `(ks_statistic, p_value, drifted)`, where `drifted = p_value < alpha`.

    Requires at least 2 (non-NaN) observations in each sample — fewer makes
    the KS test statistically meaningless, so this raises `ValueError`
    rather than returning a fabricated p-value.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1)")
    r, c = _clean_pair(reference, current)
    if r.size < 2 or c.size < 2:
        raise ValueError("need at least 2 non-NaN observations in each of reference and current")
    result = ks_2samp(r, c)
    drifted = bool(result.pvalue < alpha)
    return float(result.statistic), float(result.pvalue), drifted


def detect_prediction_drift(
    reference_predictions: np.ndarray, current_predictions: np.ndarray, alpha: float = 0.01
) -> tuple[float, float, bool]:
    """Same KS test, applied to model OUTPUTS rather than inputs. A model
    whose predictions shift while its inputs are stable ("stable inputs but
    shifted outputs", per the doc) signals the model itself has changed
    behaviour — not that the world has. Same edge-case handling as
    `detect_feature_drift`."""
    return detect_feature_drift(reference_predictions, current_predictions, alpha)


def assess_drift(
    reference_features: np.ndarray,
    current_features: np.ndarray,
    reference_predictions: np.ndarray,
    current_predictions: np.ndarray,
    alpha: float = 0.01,
) -> DriftMetrics:
    """Run both drift tests and flag the specifically diagnostic case: the
    model's outputs moved even though its inputs did not — the strongest
    signal that something changed in the model/pipeline rather than the
    market regime."""
    f_stat, f_p, f_drifted = detect_feature_drift(reference_features, current_features, alpha)
    p_stat, p_p, p_drifted = detect_prediction_drift(reference_predictions, current_predictions, alpha)
    unexplained = p_drifted and not f_drifted
    return DriftMetrics(
        feature_ks_stat=f_stat,
        feature_ks_pvalue=f_p,
        feature_drifted=f_drifted,
        prediction_ks_stat=p_stat,
        prediction_ks_pvalue=p_p,
        prediction_drifted=p_drifted,
        unexplained_prediction_drift=unexplained,
    )


def severity(drift_metrics: DriftMetrics, performance_metrics: PerformanceMetrics) -> Severity:
    """The doc's escalation ladder, in strict priority order (most severe
    first — a control-band breach outranks mere sustained decay, which
    outranks a bare drift signal):

      1. `breached_lower_control_band` -> `"demote"` (shadow mode, budget
         zero — see `quant-infra.alloc.solve.StrategyInput.shadow_mode`,
         which this label is meant to drive).
      2. `sustained_decay` -> `"monitoring"`.
      3. otherwise (feature or prediction drift observed) -> `"flag"`.

    This function has exactly three possible return values and always
    returns one of them — it is meant to be called once *some* drift or
    decay signal already exists in the caller's monitoring loop; it never
    reports "all clear" because clearing an existing flag is a promotion-like
    decision this module deliberately does not make.
    """
    if performance_metrics.breached_lower_control_band:
        return "demote"
    if performance_metrics.sustained_decay:
        return "monitoring"
    return "flag"
