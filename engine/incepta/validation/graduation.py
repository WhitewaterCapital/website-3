"""MLVAL-04 — shadow-mode graduation gates.

"Minimum shadow period ... Live shadow performance consistent with validation
performance inside a stated tolerance ... Calibration holding in shadow ... A
written model card ... Two person approval ... no code path can set a
non-zero budget for a model that has not passed all five."

This module does not reimplement validation math (purged CV, DSR, PSR, Brier
all already live in `validation/metrics.py` / `validation/splits.py`) — it
implements the thing that was missing: a record of the five graduation gates
and a SINGLE, narrow function (`approved_budget`) through which every budget
decision must route, so "no code path can fund an ungraduated model" is a
property of the code, not a policy someone has to remember.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .store import RecordStore  # re-exported for callers that want to persist records


@dataclass
class ModelCard:
    """The written model card gate. A card only counts as "written" if every
    section actually has content — a ModelCard with blank fields is not a
    completed gate, it's an empty template."""

    purpose: str = ""
    data: str = ""
    features: str = ""
    training_window: str = ""
    validation_protocol: str = ""
    known_failure_modes: str = ""
    shutoff_conditions: str = ""

    def is_complete(self) -> bool:
        return all(
            isinstance(v, str) and v.strip()
            for v in (
                self.purpose, self.data, self.features, self.training_window,
                self.validation_protocol, self.known_failure_modes,
                self.shutoff_conditions,
            )
        )


@dataclass
class GraduationRecord:
    """Tracks the five graduation gates for one model, explicitly — each is
    independently inspectable via `gates()` / the individual `gate_*` methods,
    so a caller (or a test) can see exactly which gate is failing rather than
    a single opaque bool.
    """

    model_id: str

    # Gate 1 — minimum shadow period.
    shadow_days: int = 0
    shadow_days_required: int = 60

    # Gate 2 — live shadow performance consistent with validation, inside a
    # stated tolerance. `shadow_vs_validation_delta` is e.g.
    # |shadow Sharpe - validation Sharpe| (or any agreed distance metric) —
    # computed upstream from validation/metrics.py outputs, not here.
    shadow_vs_validation_delta: Optional[float] = None
    shadow_vs_validation_tolerance: float = 0.25

    # Gate 3 — calibration holding in shadow (e.g. |Brier_shadow - Brier_val|
    # or an ECE figure) — again computed upstream from metrics.brier_score.
    calibration_error: Optional[float] = None
    calibration_tolerance: float = 0.05

    # Gate 4 — a written model card.
    model_card: Optional[ModelCard] = None

    # Gate 5 — two-person approval, by DISTINCT approver identity.
    approvals: list = field(default_factory=list)
    min_approvals: int = 2

    # ---- individual gates --------------------------------------------------
    def gate_shadow_period(self) -> bool:
        return self.shadow_days >= self.shadow_days_required

    def gate_shadow_matches_validation(self) -> bool:
        return (
            self.shadow_vs_validation_delta is not None
            and abs(self.shadow_vs_validation_delta) <= self.shadow_vs_validation_tolerance
        )

    def gate_calibration(self) -> bool:
        return (
            self.calibration_error is not None
            and abs(self.calibration_error) <= self.calibration_tolerance
        )

    def gate_model_card(self) -> bool:
        return self.model_card is not None and self.model_card.is_complete()

    def gate_two_person_approval(self) -> bool:
        distinct = {a.strip() for a in self.approvals if isinstance(a, str) and a.strip()}
        return len(distinct) >= self.min_approvals

    def gates(self) -> dict:
        """All five gates, named, each independently evaluated. `can_fund`
        and `approved_budget` are defined purely in terms of this dict so
        there is exactly one place that decides what "all five" means."""
        return {
            "shadow_period": self.gate_shadow_period(),
            "shadow_matches_validation": self.gate_shadow_matches_validation(),
            "calibration": self.gate_calibration(),
            "model_card": self.gate_model_card(),
            "two_person_approval": self.gate_two_person_approval(),
        }


class GraduationGateError(PermissionError):
    """Raised by `require_can_fund` when one or more graduation gates fail."""


def can_fund(record: GraduationRecord) -> bool:
    """True only when ALL FIVE graduation gates pass. There is no partial-
    credit path here — `gates()` is a dict of five independent booleans and
    this is a plain `all(...)` over it, so it is structurally impossible for
    four-out-of-five to satisfy it."""
    return all(record.gates().values())


def require_can_fund(record: GraduationRecord) -> None:
    """Raise `GraduationGateError` (naming the failing gates) unless all five
    pass. Use this at any call site that must hard-stop rather than silently
    fall back to a zero budget."""
    if not can_fund(record):
        failing = [name for name, ok in record.gates().items() if not ok]
        raise GraduationGateError(
            f"Model {record.model_id!r} has not passed all five graduation "
            f"gates; failing: {failing}. Refusing to authorize funding."
        )


def approved_budget(record: GraduationRecord, requested_budget: float) -> float:
    """The ONLY function in this module that produces a budget number. Route
    every funding decision through this: it returns `requested_budget`
    unchanged when (and only when) `can_fund(record)` is True, and 0.0
    otherwise — never a partial amount, never based on which gates happened
    to pass. Because this is the sole source of a non-zero budget and it is
    gated by `can_fund`, no code path that goes through here can fund a model
    that hasn't passed all five gates.
    """
    if requested_budget < 0:
        raise ValueError("requested_budget must be >= 0")
    return requested_budget if can_fund(record) else 0.0
