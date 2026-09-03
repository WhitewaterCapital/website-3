"""LOOP-03 — bounded exploration budget allocator.

A small, fixed slice of the book is set aside to try challengers that have
not yet earned a place via `champion_challenger.promote()`. This module
allocates that slice using an upper-confidence-bound (UCB) style rule:
higher `plausible_edge_estimate` OR higher `uncertainty` (worth learning
about) gets more of the exploration budget, in proportion to
`plausible_edge_estimate + exploration_k * uncertainty`, clipped at zero (a
challenger with a clearly negative expected edge gets no exploration budget
just for being uncertain about it).

**Architectural hard cap.** `_HARD_CEILING_SHARE` is a module-level constant,
not a function parameter — no caller, adversarial or not, can pass a value
that raises the true ceiling on total exploration spend. `total_share`
(the *requested* share, default 5%) is clamped into `[0, _HARD_CEILING_SHARE]`
before anything else happens, so `allocate_exploration_budget(..., total_share=1e9)`
is exactly as safe as the default call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Hard architectural ceiling on total exploration budget share. Deliberately
# NOT a parameter of allocate_exploration_budget: raising it requires editing
# this file (and the tests that pin it), not passing a config value.
_HARD_CEILING_SHARE = 0.10

DEFAULT_EXPLORATION_SHARE = 0.05


@dataclass(frozen=True)
class ChallengerInput:
    name: str
    uncertainty: float               # >= 0; how little is known about its edge
    plausible_edge_estimate: float   # a plausible (not necessarily shrunk) edge estimate


@dataclass(frozen=True)
class ExplorationAllocation:
    allocations: dict[str, float]  # name -> exploration budget share
    total_share_used: float        # sum(allocations.values())
    requested_share: float         # what the caller asked for, pre-clamp
    hard_capped: bool              # True if requested_share exceeded the architectural ceiling


def allocate_exploration_budget(
    challengers: Sequence[ChallengerInput],
    total_share: float = DEFAULT_EXPLORATION_SHARE,
    exploration_k: float = 1.0,
) -> ExplorationAllocation:
    """Allocate up to `min(total_share, _HARD_CEILING_SHARE)` of the book
    across `challengers`, proportional to each one's non-negative UCB score
    `plausible_edge_estimate + exploration_k * uncertainty`.

    Edge cases:
      - `total_share` is clamped into `[0, _HARD_CEILING_SHARE]` no matter
        what is passed (NaN, negative, or absurdly large) — never raises.
      - Empty `challengers` -> empty allocation, `total_share_used == 0`.
      - A NaN `uncertainty` or `plausible_edge_estimate` makes that
        challenger's UCB score untrustworthy -> treated as a score of 0
        (excluded from the split), not propagated as NaN into every other
        challenger's normalized share.
      - If every challenger's UCB score is <= 0, no budget is handed out at
        all (`total_share_used == 0`) — exploration is not force-spent on
        challengers with no plausible upside.
    """
    requested = total_share
    if not np.isfinite(requested):
        clamped_request = 0.0
    else:
        clamped_request = float(np.clip(requested, 0.0, _HARD_CEILING_SHARE))
    hard_capped = np.isfinite(requested) and requested > _HARD_CEILING_SHARE

    if not challengers:
        return ExplorationAllocation(
            allocations={}, total_share_used=0.0, requested_share=float(requested), hard_capped=hard_capped
        )

    scores = []
    for c in challengers:
        if not np.isfinite(c.uncertainty) or not np.isfinite(c.plausible_edge_estimate):
            scores.append(0.0)
            continue
        ucb = c.plausible_edge_estimate + exploration_k * c.uncertainty
        scores.append(max(ucb, 0.0))
    scores = np.array(scores, dtype=float)

    total_score = float(scores.sum())
    if total_score <= 0.0:
        allocations = {c.name: 0.0 for c in challengers}
        return ExplorationAllocation(
            allocations=allocations, total_share_used=0.0,
            requested_share=float(requested), hard_capped=hard_capped,
        )

    shares = scores / total_score * clamped_request
    allocations = {c.name: float(s) for c, s in zip(challengers, shares)}
    total_used = float(sum(allocations.values()))

    return ExplorationAllocation(
        allocations=allocations,
        total_share_used=total_used,
        requested_share=float(requested),
        hard_capped=hard_capped,
    )
