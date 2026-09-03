"""WW-DECISION — the decision engine's output (IMP-19).

The doc: "The decision engine answers whether this is a good idea and how
confident we are. The allocator answers how much capital that strategy
carries right now."

`DecisionOutput` is that first answer, and only that first answer. It
carries no sizing, budget, weight, or capital field of any kind, on
purpose: the whole point of IMP-19 is that "keeps the idea" and "takes the
money" are two different jobs done by two different systems, and the doc's
"done when" criterion depends on the *code's* shape enforcing that split,
not merely a comment saying so. A caller that wants a position size must
go to `sizing/ceiling.py` (fed by the allocator's budget and portfolio
risk's ceiling — see IMP-17), never to this module.

If you find yourself wanting to add a `size`, `weight`, `budget`, or
`capital` field here: don't. That is the allocator's job (`alloc/solve.py`
upstream of the sizing/allocator boundary in `decision/boundary.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DecisionOutput:
    """The decision engine's verdict on one idea.

    Fields:
      is_good_idea: True/False, or `None` if the decision engine is
        inconclusive (not enough signal to call it either way — `None` is
        an honest "don't know," never coerced to a fabricated True/False).
      confidence: a number in [0, 1] expressing how confident the decision
        engine is in `is_good_idea`. When `is_good_idea is None`,
        `confidence` still describes how confident the engine is in its
        *inconclusiveness* (e.g. a low, near-0 confidence for "not enough
        data yet" is expected and valid).
      rationale: a free-text explanation of the verdict, for audit/replay
        (see `reproducibility.py`).

    Deliberately absent: any position-size, budget, weight, or capital
    field. See module docstring.
    """

    is_good_idea: Optional[bool]
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        if self.confidence != self.confidence or self.confidence in (float("inf"), float("-inf")):
            raise ValueError(f"confidence must be a finite number, got {self.confidence!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence!r}")
