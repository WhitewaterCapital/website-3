"""WW-DECISION — the allocator/fallback boundary switch (IMP-19).

The doc: "Keep the v1.0 reliability weighting with shrinkage as the
fallback path. If the allocator fails to solve or goes unstable we drop
back to fixed weights and raise an alarm... Done when disabling the
allocator degrades us to v1.0 behaviour with no code change and no
outage."

`get_strategy_weights` is the literal mechanism behind that "done when":
it tries the allocator, and on any failure — an exception, or a result the
allocator itself flags as infeasible/unstable, or a structurally malformed
result — it falls back to `reliability_fallback.fixed_weight_fallback`
(the v1.0 path) and sets `alarm_raised=True` with a written reason. The
caller never has to change code to get this behaviour: "disabling the
allocator" just means `allocator_solve_fn` starts raising or returning an
infeasible result, and this function already handles both.

**Decoupling from `alloc/solve.py`.** This module does not import
`alloc.solve` — `allocator_solve_fn` is an injected, zero-argument
callable (bind strategies/covariance/config into it with
`functools.partial` or a closure) so this module stays testable with a
bare stub and does not couple to that package's internals. In production
it would be a partial application of `alloc.solve.solve`, whose
`SolveLog` already exposes exactly the two fields this module reads.

**The result-shape contract.** `allocator_solve_fn()` is expected to
return an object exposing (as attributes, e.g. a dataclass, or as dict
keys):
  - `solution`: a `dict[str, float]` of per-strategy budgets/weights.
  - `feasible`: `bool` — whether the allocator considers this solution
    usable. `alloc.solve.solve`'s `SolveLog.feasible` is exactly this.

A result missing either field, a non-dict `solution`, or a `solution`
containing a non-finite weight is treated the same as an "unstable"
solution — this module never guesses a meaning for a shape it does not
recognise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from reliability_fallback import DEFAULT_SHRINKAGE, fixed_weight_fallback

BoundarySource = Literal["allocator", "fallback"]


@dataclass(frozen=True)
class BoundaryResult:
    """The outcome of trying the allocator and, if needed, falling back.

    Fields:
      weights: the final per-strategy dict actually returned to the
        caller — either the allocator's own `solution` (when
        `source == "allocator"`) or `fixed_weight_fallback`'s output
        (when `source == "fallback"`).
      source: which path produced `weights`.
      alarm_raised: True iff the fallback path was used — "raise an
        alarm" per the doc. Always False when `source == "allocator"`.
      reason: a written explanation of why the fallback was used (`None`
        when `source == "allocator"`).
      allocator_result: the raw object `allocator_solve_fn()` returned, if
        it returned one without raising (`None` if it raised). Kept for
        reproducibility (see `reproducibility.py`) even on the fallback
        path, so a saved `BoundaryResult` shows exactly what the allocator
        produced (or attempted) at decision time.
      fallback_shrinkage: the shrinkage value used to compute `weights`
        when `source == "fallback"` (`None` when `source == "allocator"`).
    """

    weights: dict[str, float]
    source: BoundarySource
    alarm_raised: bool
    reason: Optional[str]
    allocator_result: Optional[Any]
    fallback_shrinkage: Optional[float]


def _extract_feasible_solution(result: Any) -> tuple[bool, dict[str, float]]:
    """Pull `(feasible, solution)` out of an allocator result, accepting
    either attribute access (a dataclass/object, e.g. `SolveLog`) or dict
    access. Raises `ValueError` for anything else, or for a `solution`
    containing a non-finite weight — both are treated by the caller as
    "unstable," never silently trusted."""
    if hasattr(result, "feasible") and hasattr(result, "solution"):
        feasible = getattr(result, "feasible")
        solution = getattr(result, "solution")
    elif isinstance(result, dict) and "feasible" in result and "solution" in result:
        feasible = result["feasible"]
        solution = result["solution"]
    else:
        raise ValueError(
            "allocator result does not expose both 'feasible' and 'solution' "
            "(as attributes or dict keys)"
        )

    if not isinstance(solution, dict):
        raise ValueError(f"allocator result 'solution' must be a dict, got {type(solution)!r}")

    for name, weight in solution.items():
        if weight != weight or weight in (float("inf"), float("-inf")):
            raise ValueError(f"allocator solution weight for {name!r} is non-finite: {weight!r}")

    return bool(feasible), {k: float(v) for k, v in solution.items()}


def get_strategy_weights(
    allocator_solve_fn: Callable[[], Any],
    strategy_reliabilities: dict[str, float],
    fallback_shrinkage: float = DEFAULT_SHRINKAGE,
) -> BoundaryResult:
    """Try the allocator; fall back to v1.0 fixed weights (with an alarm)
    on any exception, infeasible/unstable result, or malformed result
    shape.

    `allocator_solve_fn` takes no arguments — bind whatever the real
    solver needs (strategies, covariance, config) via `functools.partial`
    or a closure before passing it in here, so this module never needs to
    know the allocator's call signature.

    `strategy_reliabilities` is the input to the fallback path
    (`reliability_fallback.fixed_weight_fallback`); it is required (not
    optional) even on the success path, because the whole point of this
    function is that the fallback is always ready to fire with no extra
    setup — "no code change, no outage."
    """
    try:
        result = allocator_solve_fn()
    except Exception as exc:  # the allocator "fails to solve" -- any exception at all
        fallback_weights = fixed_weight_fallback(strategy_reliabilities, fallback_shrinkage)
        return BoundaryResult(
            weights=fallback_weights,
            source="fallback",
            alarm_raised=True,
            reason=f"allocator_solve_fn raised an exception: {exc!r}",
            allocator_result=None,
            fallback_shrinkage=fallback_shrinkage,
        )

    try:
        feasible, solution = _extract_feasible_solution(result)
    except Exception as exc:  # malformed / unrecognisable result shape -> treat as unstable
        fallback_weights = fixed_weight_fallback(strategy_reliabilities, fallback_shrinkage)
        return BoundaryResult(
            weights=fallback_weights,
            source="fallback",
            alarm_raised=True,
            reason=f"allocator result was malformed/unstable: {exc!r}",
            allocator_result=result,
            fallback_shrinkage=fallback_shrinkage,
        )

    if not feasible:
        fallback_weights = fixed_weight_fallback(strategy_reliabilities, fallback_shrinkage)
        return BoundaryResult(
            weights=fallback_weights,
            source="fallback",
            alarm_raised=True,
            reason="allocator reported an infeasible/unstable solution (feasible=False)",
            allocator_result=result,
            fallback_shrinkage=fallback_shrinkage,
        )

    return BoundaryResult(
        weights=solution,
        source="allocator",
        alarm_raised=False,
        reason=None,
        allocator_result=result,
        fallback_shrinkage=None,
    )
