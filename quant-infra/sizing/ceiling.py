"""WW-SIZING — position-size ceiling resolution (IMP-17).

The doc: "Allocator sets the strategy budget, portfolio risk sets the
position ceiling inside that budget, smaller number always wins."

This module is deliberately tiny and pure: given the two numbers an upstream
allocator (`quant-infra/alloc/solve.py`'s per-strategy budget) and an
upstream portfolio-risk engine have already produced, it decides the one
number that gates an executed position, and it always records which of the
two inputs was the binding constraint so the decision is auditable after
the fact.

**Order of operations, exactly as specified:**
  1. The allocator sets a strategy budget (a dollar or notional ceiling).
  2. Portfolio risk sets a position ceiling *inside* that budget.
  3. The smaller of the two always wins.
  4. A budget of exactly zero means zero position at any size — this holds
     even if the portfolio-risk ceiling is a large positive number, because
     a budget of zero is not "no constraint from the allocator", it is "the
     allocator granted this strategy no capital right now."

**What this module does NOT do:** it does not gate research or analysis
output. A strategy with `approved_size == 0` (whether because its budget is
zero, or because both ceilings independently evaluate to zero) can and
should still publish its research/analysis — sizing to zero is a capital
decision, not a "stop thinking" decision. Nothing in this module reads,
writes, or blocks any research/analysis path; it only ever computes a
single non-negative size number and a label for which ceiling produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BindingConstraint = Literal["allocator", "portfolio_risk", "both_equal", "zero_budget"]


@dataclass(frozen=True)
class SizingDecision:
    """The outcome of resolving a position size against both ceilings.

    Fields:
      approved_size: the final, non-negative size a position may be sized
        to. Always `min(allocator_budget, portfolio_risk_ceiling)`, except
        that an `allocator_budget` of exactly 0 forces `approved_size` to 0
        regardless of `portfolio_risk_ceiling` (see module docstring).
      allocator_budget: the input budget from the allocator, echoed back
        so the decision is self-contained and replayable.
      portfolio_risk_ceiling: the input ceiling from portfolio risk, echoed
        back for the same reason.
      binding_constraint: which of the two ceilings actually determined
        `approved_size`:
          - "zero_budget": the allocator budget was exactly 0 (the special
            case above always wins, even if the risk ceiling was also 0 —
            in that degenerate double-zero case we still label it
            "zero_budget" since the allocator's zero is the doc's explicit
            named rule, not a coincidental tie).
          - "allocator": allocator_budget < portfolio_risk_ceiling (and
            allocator_budget > 0).
          - "portfolio_risk": portfolio_risk_ceiling < allocator_budget.
          - "both_equal": the two ceilings are numerically equal and both
            are > 0 (there is no distinguishable "binder" in that case).
      note: a fixed, human-readable reminder that a zero/low approved_size
        here does not imply anything about whether the strategy's research
        or analysis should be suppressed.
    """

    approved_size: float
    allocator_budget: float
    portfolio_risk_ceiling: float
    binding_constraint: BindingConstraint
    note: str = (
        "approved_size gates position sizing only; the strategy may still "
        "publish research/analysis regardless of approved_size."
    )


def resolve_position_size(
    allocator_budget: float, portfolio_risk_ceiling: float
) -> SizingDecision:
    """Resolve the final approved position size from the two upstream
    ceilings, per IMP-17's order of operations.

    Raises `ValueError` if either input is negative (a negative budget or
    a negative risk ceiling is not a physically meaningful ceiling — that
    is a caller bug upstream, not a value this function should silently
    clamp or coerce) or non-finite (NaN/inf ceilings must be resolved to a
    real number, or explicitly treated as unknown, before reaching this
    function; this function does not guess).
    """
    for label, value in (
        ("allocator_budget", allocator_budget),
        ("portfolio_risk_ceiling", portfolio_risk_ceiling),
    ):
        if value != value or value in (float("inf"), float("-inf")):  # NaN/inf check w/o numpy
            raise ValueError(f"{label} must be a finite number, got {value!r}")
        if value < 0:
            raise ValueError(f"{label} must be non-negative, got {value!r}")

    allocator_budget = float(allocator_budget)
    portfolio_risk_ceiling = float(portfolio_risk_ceiling)

    if allocator_budget == 0.0:
        # Budget of zero means no position at any size, full stop —
        # regardless of how large the portfolio-risk ceiling is.
        return SizingDecision(
            approved_size=0.0,
            allocator_budget=allocator_budget,
            portfolio_risk_ceiling=portfolio_risk_ceiling,
            binding_constraint="zero_budget",
        )

    if allocator_budget < portfolio_risk_ceiling:
        binding: BindingConstraint = "allocator"
        approved = allocator_budget
    elif portfolio_risk_ceiling < allocator_budget:
        binding = "portfolio_risk"
        approved = portfolio_risk_ceiling
    else:
        binding = "both_equal"
        approved = allocator_budget  # == portfolio_risk_ceiling

    return SizingDecision(
        approved_size=approved,
        allocator_budget=allocator_budget,
        portfolio_risk_ceiling=portfolio_risk_ceiling,
        binding_constraint=binding,
    )
