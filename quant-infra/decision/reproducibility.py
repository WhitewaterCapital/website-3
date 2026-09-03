"""WW-DECISION — packaging a decision for reproducibility (IMP-19).

The doc: "Decisions stay reproducible from saved outputs, extended to
saved allocator inputs and the solver solution."

v1.0 reproducibility meant: given the decision engine's saved output, you
could see why a decision was made. IMP-19 extends that: because the
allocator (not the decision engine) now determines capital, reproducing
*what actually happened* to a strategy also requires the allocator inputs
that were live at the time and the solver's actual solution (or, on the
fallback path, the fixed weights that were used instead and why).

`build_decision_replay_record` packages exactly those three things —
the decision engine's `DecisionOutput`, whatever inputs were fed to the
allocator, and the `BoundaryResult` (allocator solution or fallback
weights, plus the alarm/reason) — into one plain, JSON-serialisable dict.

**Documented gap:** this module only builds the record. Actually
persisting it (a database, an append-only ledger analogous to
`sizing/ledger.py`, a data warehouse table) is out of scope for this pass
— wiring this record to a real store is future work. See the package
README.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

from boundary import BoundaryResult
from idea import DecisionOutput


def _to_jsonable(value: Any) -> Any:
    """Best-effort conversion of an arbitrary value (dataclass instance,
    dict, list, tuple, or plain scalar) into something `json.dumps` can
    serialise, recursively. Anything else (e.g. a custom object with no
    dataclass fields) is converted via `repr()` rather than silently
    dropped, so a saved record never loses information without saying so.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)  # explicit, visible fallback -- never silently dropped


def build_decision_replay_record(
    decision_output: DecisionOutput,
    allocator_inputs: Any,
    boundary_result: BoundaryResult,
) -> dict:
    """Package one decision's full context into a single JSON-serialisable
    dict for later replay/audit.

    Args:
      decision_output: the decision engine's verdict (`idea.DecisionOutput`)
        — "is this a good idea, how confident are we."
      allocator_inputs: whatever was actually fed to the allocator this
        cycle (e.g. a list of `alloc.solve.StrategyInput` plus the
        covariance matrix and `SolverConfig` used, however the caller
        chooses to package them) — echoed back verbatim (converted to a
        JSON-safe shape via `_to_jsonable`) so a saved record shows the
        allocator's actual live inputs, not just its output.
      boundary_result: the `boundary.BoundaryResult` describing whether
        the allocator's solution or the v1.0 fallback weights were used,
        and why.

    Returns a plain dict with keys `decision`, `allocator_inputs`, and
    `boundary`, each JSON-serialisable. This function does not write
    anything to disk or to any store — see module docstring's documented
    gap.
    """
    return {
        "decision": _to_jsonable(decision_output),
        "allocator_inputs": _to_jsonable(allocator_inputs),
        "boundary": _to_jsonable(boundary_result),
    }
