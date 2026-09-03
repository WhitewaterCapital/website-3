"""
Generic Monte Carlo statistics: turning an array of per-path discounted
cashflows into a `MonteCarloResult`, correctly, whether or not antithetic
pairing or a control variate was used.

This is deliberately the *only* place that computes a standard error in
this engine — every payoff/pricer routes its per-path cashflows through one
of these three functions rather than reinventing `std / sqrt(n)` locally,
so "never a price without a standard error" is enforced structurally, not
by convention.
"""
from __future__ import annotations

import numpy as np

from ..types import MonteCarloResult


def mc_stats(discounted: np.ndarray, meta: dict | None = None) -> MonteCarloResult:
    """Plain Monte Carlo: sample mean and sample standard error."""
    discounted = np.asarray(discounted, dtype=float)
    n = discounted.shape[0]
    mean = float(np.mean(discounted))
    se = float(np.std(discounted, ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    return MonteCarloResult(price=mean, std_error=se, n_paths=n, meta=meta or {})


def mc_stats_antithetic(discounted: np.ndarray, meta: dict | None = None) -> MonteCarloResult:
    """Antithetic Monte Carlo: `discounted` must be ordered
    `[base_1..base_m, mirror_1..mirror_m]` (exactly what
    `pe.engine.random_streams.normal_increments(antithetic=True)` produces
    when paths are built straight off its output). Each (base, mirror) pair
    is averaged *before* computing sample statistics — using the raw n
    instead would ignore the negative correlation antithetic pairing
    introduces and overstate the standard error's independence assumption
    in the wrong direction (it would actually look *conservative*, but it
    also throws away the reduction that is the entire point of the
    technique, so we report the honest, tighter, pair-based SE instead).
    """
    discounted = np.asarray(discounted, dtype=float)
    n = discounted.shape[0]
    if n % 2 != 0:
        raise ValueError("antithetic array must have an even number of paths (base + mirror)")
    m = n // 2
    pair_avg = 0.5 * (discounted[:m] + discounted[m:])
    mean = float(np.mean(pair_avg))
    se = float(np.std(pair_avg, ddof=1) / np.sqrt(m)) if m > 1 else float("nan")
    meta = dict(meta or {})
    meta["antithetic"] = True
    return MonteCarloResult(price=mean, std_error=se, n_paths=n, meta=meta)


def control_variate_adjust(
    discounted_payoff: np.ndarray,
    discounted_control: np.ndarray,
    control_true_mean: float,
    antithetic: bool = False,
    meta: dict | None = None,
) -> MonteCarloResult:
    """Optimal-beta control variate estimator.

    Y_cv_i = Y_i - beta * (X_i - E[X]),  beta = Cov(Y, X) / Var(X)

    where Y is the target (discounted) payoff and X is a (discounted)
    control payoff with known analytic mean `control_true_mean` (same
    discounting convention as Y — both are "value today" per path). beta is
    estimated from the joint sample, which is the standard approach and
    costs only a slight loss of efficiency versus a hypothetically-known
    beta. If `antithetic=True`, pairing happens first (same convention as
    `mc_stats_antithetic`) and beta/variance are estimated on the paired
    series.
    """
    discounted_payoff = np.asarray(discounted_payoff, dtype=float)
    discounted_control = np.asarray(discounted_control, dtype=float)
    if discounted_payoff.shape != discounted_control.shape:
        raise ValueError("payoff and control arrays must have the same shape")

    if antithetic:
        n = discounted_payoff.shape[0]
        if n % 2 != 0:
            raise ValueError("antithetic array must have an even number of paths")
        m = n // 2
        y = 0.5 * (discounted_payoff[:m] + discounted_payoff[m:])
        x = 0.5 * (discounted_control[:m] + discounted_control[m:])
    else:
        y = discounted_payoff
        x = discounted_control

    if y.shape[0] < 2:
        raise ValueError("need at least 2 (paired) paths for a control variate estimate")

    cov = np.cov(y, x, ddof=1)
    var_x = cov[1, 1]
    beta = float(cov[0, 1] / var_x) if var_x > 0 else 0.0
    y_cv = y - beta * (x - control_true_mean)

    n_eff = y_cv.shape[0]
    mean = float(np.mean(y_cv))
    se = float(np.std(y_cv, ddof=1) / np.sqrt(n_eff)) if n_eff > 1 else float("nan")

    meta = dict(meta or {})
    meta.update({"control_variate": True, "beta": beta, "antithetic": antithetic})
    return MonteCarloResult(price=mean, std_error=se, n_paths=discounted_payoff.shape[0], meta=meta)
