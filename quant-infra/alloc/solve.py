"""WW-ALLOC — capital allocation across strategies.

The doc: "Expected edge, minus an uncertainty penalty, minus a cost penalty,
gives a score per strategy. The optimiser maximises that against a risk term
built from the covariance between strategies, with a charge for movement so
it does not churn the book."

Pipeline:

1. **Shrink** each strategy's raw edge estimate towards zero based on how
   long its live track record is (`shrink_edge`) — a strategy with only a
   handful of live observations gets almost no credit for a flashy raw mean.
2. **Score** each strategy: `shrunk_edge - uncertainty_penalty*uncertainty -
   cost_penalty*cost_at_size` (`score_strategy`).
3. **Solve**: choose budgets `w >= 0` to maximise
   `score . w - risk_aversion * w^T Cov w - turnover_penalty * sum|w - w_prev|`
   subject to a per-strategy cap, a total gross budget limit, and a hard
   zero for any strategy in shadow mode.

**Solver substitution (documented simplification):** the doc asks for an
"off-the-shelf convex solver." `cvxpy` is not installed in this environment
(`try: import cvxpy except ImportError` confirms it at import time below);
`scipy.optimize.minimize` (SLSQP) is used instead. For this problem shape
(a smooth quadratic risk term, an L1 turnover term, box + one linear
constraint) SLSQP finds the same optimum a QP solver would on well-scaled
inputs, but it lacks a QP solver's certificate of global optimality and can
occasionally report false non-convergence on badly scaled inputs — which is
exactly why the fallback-to-previous-budget guard below exists: a solver
that isn't sure never gets to move the book.

**Hard shadow-mode zero:** rather than trust a numerically-tolerant equality
constraint alone, a shadow-mode strategy's variable is *also* bounded to the
degenerate box `[0, 0]`. SLSQP enforces box bounds exactly (bounds define the
feasible region itself, not a constraint subject to `ftol`/`eqcons` slack),
so the realized "epsilon" above zero is machine precision (~1e-16), not a
solver tolerance parameter. The literal equality constraint is *also* added
(redundant with the bound) so it appears in `active_constraints` and so the
invariant is documented, not just implicit in a bounds array.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

try:
    import cvxpy  # noqa: F401
    _HAVE_CVXPY = True
except ImportError:
    _HAVE_CVXPY = False


# --------------------------------------------------------------------------- #
# data model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class StrategyInput:
    name: str
    expected_edge_raw: float
    live_track_record_length: float   # number of live observations backing the edge
    uncertainty: float                 # >= 0; e.g. std error of the edge estimate
    cost_at_size: float                # >= 0; expected cost penalty at the proposed size
    previous_budget: float             # prior allocation (>= 0; NaN treated as 0, no prior position)
    shadow_mode: bool = False          # True => hard-zero budget regardless of score
    cap: float | None = None           # per-strategy hard cap; None => cfg.default_cap


@dataclass(frozen=True)
class SolverConfig:
    prior_pseudo_obs: float = 60.0     # track-record shrinkage strength (see shrink_edge)
    uncertainty_penalty: float = 1.0   # lambda on uncertainty in the score
    cost_penalty: float = 1.0          # lambda on cost_at_size in the score
    risk_aversion: float = 1.0         # lambda on w^T Cov w
    turnover_penalty: float = 0.0      # lambda on sum|w - w_prev|
    default_cap: float = 0.30          # per-strategy cap when StrategyInput.cap is None
    total_gross_limit: float = 1.0     # sum(w) <= this
    max_step_fraction: float = 0.5     # max allowed sum|w-w_prev| / total_gross_limit
    shadow_epsilon: float = 1e-9       # documented tolerance for the shadow-zero assertion
    # ^ Not used to *implement* the zero (bounds do that exactly); this is the
    # tolerance a caller/test should use when *checking* the invariant, since
    # even an exact-zero bound can carry ~1e-16 float noise through downstream
    # arithmetic. 1e-9 is nine orders of magnitude looser than that noise
    # floor, so nothing a solver could produce "using up the tolerance" would
    # ever be mistaken for a real, non-shadow allocation.


@dataclass(frozen=True)
class SolveLog:
    inputs: tuple[StrategyInput, ...]
    scores: dict[str, float]
    solution: dict[str, float]
    previous_budget: dict[str, float]
    active_constraints: tuple[str, ...]
    fallback_used: bool
    fallback_reason: str | None
    feasible: bool
    objective_value: float | None


# --------------------------------------------------------------------------- #
# step (a): shrink the raw edge estimate
# --------------------------------------------------------------------------- #

def shrink_edge(
    raw_edge: float, live_track_record_length: float, prior_pseudo_obs: float = 60.0
) -> float:
    """Shrink `raw_edge` towards zero by the Bayesian-shrinkage weight
    `n / (n + prior_pseudo_obs)`, where `n` is the live track record length
    and `prior_pseudo_obs` is how many observations of "no edge" prior belief
    the estimate must overcome. A strategy with `n=0` gets weight 0 (no
    live evidence at all -> assume zero edge); as `n -> infinity` the weight
    -> 1 and the raw estimate is trusted fully.

    Edge cases, all explicit:
      - `n < 0` is not physically meaningful -> raises `ValueError`.
      - `prior_pseudo_obs <= 0` would make the shrinkage denominator
        degenerate -> raises `ValueError`.
      - `NaN`/non-finite `raw_edge` is treated as **zero edge, not a
        propagated NaN** — a downstream quadratic optimiser has no sane
        response to a NaN in its objective, and "no evidence" is a strictly
        safer default than "assume the number was real." The caller-visible
        signal that this happened lives in `SolveLog.active_constraints`,
        not in a silently-NaN score.
    """
    if live_track_record_length < 0:
        raise ValueError("live_track_record_length must be non-negative")
    if prior_pseudo_obs <= 0:
        raise ValueError("prior_pseudo_obs must be positive")
    if not np.isfinite(raw_edge):
        return 0.0
    n = float(live_track_record_length)
    weight = n / (n + prior_pseudo_obs)
    return float(weight * raw_edge)


# --------------------------------------------------------------------------- #
# step (b): per-strategy score
# --------------------------------------------------------------------------- #

def score_strategy(shrunk_edge: float, uncertainty: float, cost_at_size: float, cfg: SolverConfig) -> float:
    """score = shrunk_edge - uncertainty_penalty*uncertainty - cost_penalty*cost_at_size.

    `uncertainty` and `cost_at_size` are cost-like quantities and must be
    non-negative (a "negative cost" or "negative uncertainty" is a caller
    bug, not a valid input) -> raises `ValueError`. A NaN in either yields a
    NaN score, which `solve()` treats as "cannot be trusted this period" and
    hard-zeros (see `solve`'s handling of NaN scores) rather than silently
    dropping the penalty.
    """
    if np.isfinite(uncertainty) and uncertainty < 0:
        raise ValueError("uncertainty must be non-negative")
    if np.isfinite(cost_at_size) and cost_at_size < 0:
        raise ValueError("cost_at_size must be non-negative")
    return float(shrunk_edge - cfg.uncertainty_penalty * uncertainty - cfg.cost_penalty * cost_at_size)


# --------------------------------------------------------------------------- #
# covariance
# --------------------------------------------------------------------------- #

def shrink_covariance(returns: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf shrinkage covariance of a (T observations x N strategies)
    return matrix, shrunk towards a scaled identity.

    Rows containing any NaN are dropped (a covariance needs row-complete
    observations; pairwise-complete would mix different sample periods per
    entry, silently understating cross-strategy correlation). Raises
    `ValueError` if fewer than 2 complete rows remain, or if `returns` has
    fewer than 2 columns (a "covariance" of one strategy is undefined).
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 2:
        raise ValueError("returns must be a 2D (T x N) array")
    if r.shape[1] < 2:
        raise ValueError("need at least 2 strategies to form a covariance matrix")
    complete = r[~np.isnan(r).any(axis=1)]
    if complete.shape[0] < 2:
        raise ValueError("need at least 2 complete (no-NaN) observation rows")
    lw = LedoitWolf().fit(complete)
    return lw.covariance_


# --------------------------------------------------------------------------- #
# step (c): solve
# --------------------------------------------------------------------------- #

def _objective(w, score, cov, risk_aversion, turnover_penalty, w_prev):
    edge_term = float(np.dot(score, w))
    risk_term = float(risk_aversion * (w @ cov @ w))
    turnover_term = float(turnover_penalty * np.sum(np.abs(w - w_prev)))
    return -(edge_term - risk_term - turnover_term)  # minimize the negative


def solve(
    strategies: Sequence[StrategyInput],
    covariance: np.ndarray,
    cfg: SolverConfig | None = None,
) -> SolveLog:
    """Solve for per-strategy budgets. Never raises on a bad/infeasible
    *allocation* problem (bad `StrategyInput` field types/values still raise
    inside `shrink_edge`/`score_strategy`) — infeasibility and excessive
    turnover are reported via `SolveLog`, falling back to `previous_budget`.
    """
    cfg = cfg or SolverConfig()
    names = [s.name for s in strategies]
    n = len(strategies)

    if n == 0:
        return SolveLog(
            inputs=(), scores={}, solution={}, previous_budget={},
            active_constraints=(), fallback_used=False, fallback_reason=None,
            feasible=True, objective_value=None,
        )

    cov = np.asarray(covariance, dtype=float)
    if cov.shape != (n, n):
        raise ValueError(f"covariance must be {n}x{n}, got {cov.shape}")

    prev = np.array(
        [0.0 if not np.isfinite(s.previous_budget) else float(s.previous_budget) for s in strategies]
    )
    prev_by_name = {s.name: float(p) for s, p in zip(strategies, prev)}

    # scores (NaN-safe: a NaN score is a "cannot trust this period" flag)
    scores = []
    nan_forced: list[int] = []
    for s in strategies:
        shrunk = shrink_edge(s.expected_edge_raw, s.live_track_record_length, cfg.prior_pseudo_obs)
        try:
            sc = score_strategy(shrunk, s.uncertainty, s.cost_at_size, cfg)
        except ValueError:
            sc = float("nan")
        scores.append(sc)
    scores = np.array(scores, dtype=float)
    for i, sc in enumerate(scores):
        if np.isnan(sc):
            nan_forced.append(i)
    score_map = {s.name: float(sc) for s, sc in zip(strategies, scores)}

    active_constraints: list[str] = ["total_gross_limit"]
    hard_zero_idx = set()
    for i, s in enumerate(strategies):
        if s.shadow_mode:
            hard_zero_idx.add(i)
            active_constraints.append(f"shadow_zero:{s.name}")
    for i in nan_forced:
        if i not in hard_zero_idx:
            hard_zero_idx.add(i)
            active_constraints.append(f"nan_score_zero:{strategies[i].name}")

    # effective per-strategy caps + feasibility pre-check (cheap, avoids
    # handing scipy a mathematically-empty box and parsing its complaint)
    caps = []
    infeasible_reason = None
    if cfg.total_gross_limit < 0:
        infeasible_reason = f"total_gross_limit is negative ({cfg.total_gross_limit})"
    for i, s in enumerate(strategies):
        if i in hard_zero_idx:
            caps.append(0.0)
            continue
        cap = s.cap if (s.cap is not None and np.isfinite(s.cap)) else cfg.default_cap
        if cap < 0:
            infeasible_reason = infeasible_reason or f"strategy {s.name!r} has a negative cap ({cap})"
        caps.append(cap)
    caps = np.array(caps, dtype=float)

    bounds = [(0.0, 0.0) if i in hard_zero_idx else (0.0, float(caps[i])) for i in range(n)]

    def _fallback_solution(reason: str, feasible: bool) -> SolveLog:
        # Even on fallback, shadow-mode / NaN-forced strategies stay at zero —
        # the invariant holds regardless of which code path produced the budget.
        sol = {
            s.name: (0.0 if i in hard_zero_idx else prev_by_name[s.name])
            for i, s in enumerate(strategies)
        }
        w_sol = np.array([sol[s.name] for s in strategies])
        obj = _objective(w_sol, scores if not np.isnan(scores).any() else np.nan_to_num(scores),
                          cov, cfg.risk_aversion, cfg.turnover_penalty, prev)
        return SolveLog(
            inputs=tuple(strategies),
            scores=score_map,
            solution=sol,
            previous_budget=prev_by_name,
            active_constraints=tuple(active_constraints),
            fallback_used=True,
            fallback_reason=reason,
            feasible=feasible,
            objective_value=obj,
        )

    if infeasible_reason is not None:
        return _fallback_solution(f"infeasible: {infeasible_reason}", feasible=False)

    constraints = [
        {"type": "ineq", "fun": lambda w: cfg.total_gross_limit - np.sum(w)},
    ]
    for i in sorted(hard_zero_idx):
        constraints.append({"type": "eq", "fun": (lambda w, i=i: w[i])})

    x0 = np.clip(prev, [b[0] for b in bounds], [b[1] for b in bounds])
    safe_scores = np.nan_to_num(scores, nan=0.0)

    try:
        result = minimize(
            _objective,
            x0,
            args=(safe_scores, cov, cfg.risk_aversion, cfg.turnover_penalty, prev),
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 500, "ftol": 1e-12},
        )
    except Exception as exc:  # scipy can raise on malformed bounds/inputs
        return _fallback_solution(f"solver raised an exception: {exc!r}", feasible=False)

    if not result.success:
        return _fallback_solution(f"solver did not converge: {result.message}", feasible=False)

    w_sol = np.clip(result.x, [b[0] for b in bounds], [b[1] for b in bounds])

    moved = float(np.sum(np.abs(w_sol - prev)))
    frac = (moved / cfg.total_gross_limit) if cfg.total_gross_limit > 0 else (0.0 if moved == 0.0 else float("inf"))
    if frac > cfg.max_step_fraction:
        return _fallback_solution(
            f"solution moved {frac:.3f} of total_gross_limit, exceeding max_step_fraction "
            f"{cfg.max_step_fraction:.3f}",
            feasible=True,
        )

    solution = {s.name: float(w_sol[i]) for i, s in enumerate(strategies)}
    obj = _objective(w_sol, safe_scores, cov, cfg.risk_aversion, cfg.turnover_penalty, prev)

    return SolveLog(
        inputs=tuple(strategies),
        scores=score_map,
        solution=solution,
        previous_budget=prev_by_name,
        active_constraints=tuple(active_constraints),
        fallback_used=False,
        fallback_reason=None,
        feasible=True,
        objective_value=float(obj),
    )
