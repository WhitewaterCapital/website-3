"""
American / Bermudan option pricing via Longstaff-Schwartz (PATH-03).

Citation: Longstaff, F.A. & Schwartz, E.S. (2001), "Valuing American
Options by Simulation: A Simple Least-Squares Approach", The Review of
Financial Studies 14(1), pp. 113-147.

Algorithm (their Section 1): walk backward from maturity. At each exercise
date, among paths currently in-the-money, regress the *realized* discounted
continuation value (the cashflow the path actually received at its
currently-scheduled future exercise, discounted back to this date) on a
polynomial basis in the current spot. The regression's fitted value at each
in-the-money path is an estimate of that path's true (conditional) expected
continuation value; exercise now iff the immediate exercise value exceeds
it. Iterate backward to t=0; the price is the sample mean of each path's
(now fully determined) discounted realized cashflow.

Basis functions: plain monomials `1, x, x^2, ..., x^degree` in the
*normalized* spot `x = S / S0` (normalizing avoids the conditioning problems
of raw monomials in `np.linalg.lstsq` at typical equity price levels).
Laguerre polynomials are Longstaff & Schwartz's own choice and condition
better at high degree, but plain monomials are adequate at the low degrees
this module defaults to and keep the code simple to read; swapping the
basis is a one-line change in `_basis_matrix`.

**Documented bias**: this estimator is well known to be biased *upward*
(Longstaff & Schwartz 2001, Section 3, and subsequent literature, e.g.
Broadie & Glasserman (1997), "Pricing American-style securities using
simulation") — the regression is fit and then immediately used to decide
exercise on the *same* sample, so the exercise policy is implicitly
"peeking" at the very cashflows used to score it, which can only make the
in-sample policy look at least as good as the truth and typically better.
The bias shrinks as `n_paths` grows (more data per regression, less
overfitting) and, importantly, **grows with the number of basis functions**
at fixed `n_paths` (a higher-degree polynomial has more freedom to overfit
the in-sample continuation values) — `tests/test_american_lsm.py` checks
this directly: price at `basis_degree=1` is compared against price at a
much higher degree on the same paths, and the higher-degree price is
asserted to be >= the low-degree price (the direction the bias runs), not
merely "different." A second, independent simulation (out-of-sample paths,
regression coefficients frozen from a first "training" simulation) is the
standard fix when the in-sample bias needs to be squeezed out for
production use; not implemented here, noted as the natural next step.
"""
from __future__ import annotations

from typing import Literal

import numpy as np

from ..types import MonteCarloResult
from ..engine.mc import mc_stats

OptionType = Literal["call", "put"]


def _basis_matrix(x: np.ndarray, degree: int) -> np.ndarray:
    return np.vstack([x**p for p in range(degree + 1)]).T


def _exercise_value(S: np.ndarray, K: float, option_type: OptionType) -> np.ndarray:
    phi = 1.0 if option_type == "call" else -1.0
    return np.maximum(phi * (S - K), 0.0)


def american_option_lsm(
    paths: np.ndarray,
    times: np.ndarray,
    K: float,
    r: float,
    option_type: OptionType = "put",
    basis_degree: int = 3,
    exercise_idx: np.ndarray | None = None,
) -> MonteCarloResult:
    """Longstaff-Schwartz price of a Bermudan (American in the limit of
    dense `exercise_idx`) option.

    `exercise_idx` are column indices into `paths`/`times` where early
    exercise is permitted, defaulting to every simulated step (the usual
    "American, discretely monitored at the simulation grid" approximation —
    the finer the grid, the closer this sits to true American).
    `exercise_idx` must include the final column (maturity is always an
    exercise opportunity — European exercise is always available).
    """
    n_paths, n_cols = paths.shape
    idx = np.arange(n_cols) if exercise_idx is None else np.asarray(exercise_idx, dtype=int)
    if idx[-1] != n_cols - 1:
        raise ValueError("exercise_idx must include the final column (maturity)")
    if idx.size < 1:
        raise ValueError("need at least one exercise date")

    S0 = float(paths[0, 0])
    cashflow = _exercise_value(paths[:, idx[-1]], K, option_type)
    cashflow_time = np.full(n_paths, times[idx[-1]])

    for step_pos in range(idx.size - 2, -1, -1):
        col = idx[step_pos]
        t_now = times[col]
        S_now = paths[:, col]
        exercise_now = _exercise_value(S_now, K, option_type)

        itm = exercise_now > 0.0
        if np.any(itm):
            disc_cf = np.exp(-r * (cashflow_time[itm] - t_now)) * cashflow[itm]
            x = S_now[itm] / S0
            A = _basis_matrix(x, basis_degree)
            coeffs, *_ = np.linalg.lstsq(A, disc_cf, rcond=None)
            continuation_est = A @ coeffs

            exercise_here = exercise_now[itm] > continuation_est
            itm_positions = np.where(itm)[0]
            take = itm_positions[exercise_here]
            cashflow[take] = exercise_now[itm][exercise_here]
            cashflow_time[take] = t_now

    discounted = np.exp(-r * cashflow_time) * cashflow
    meta = {"basis_degree": basis_degree, "n_exercise_dates": int(idx.size)}
    return mc_stats(discounted, meta=meta)
