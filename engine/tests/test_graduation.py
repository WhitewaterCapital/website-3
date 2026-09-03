"""Tests for MLVAL-04 shadow-mode graduation gates: funding is provably
impossible unless ALL FIVE gates pass — tested by trying every
four-out-of-five combination and confirming every single one is refused.
"""

from __future__ import annotations

import pytest

from incepta.validation.graduation import (
    GraduationGateError,
    GraduationRecord,
    ModelCard,
    approved_budget,
    can_fund,
    require_can_fund,
)


def _complete_model_card() -> ModelCard:
    return ModelCard(
        purpose="Cross-sectional equity quality ranking for the paper sleeve.",
        data="SEC EDGAR XBRL company facts + Tiingo daily prices.",
        features="ROA, ROE, margins, leverage, Piotroski F, momentum, realized vol.",
        training_window="2015-01-01 to 2023-12-31, expanding, purged/embargoed.",
        validation_protocol="Purged k-fold + walk-forward; DSR and PSR reported together.",
        known_failure_modes="Degrades in low-dispersion regimes; sector concentration risk.",
        shutoff_conditions="Auto-pause if shadow DSR < 0.5 for 10 consecutive sessions.",
    )


def _passing_record() -> GraduationRecord:
    """A record where all five gates pass — the ONE baseline everything else
    in this file mutates away from."""
    return GraduationRecord(
        model_id="model_x",
        shadow_days=90,
        shadow_days_required=60,
        shadow_vs_validation_delta=0.10,
        shadow_vs_validation_tolerance=0.25,
        calibration_error=0.02,
        calibration_tolerance=0.05,
        model_card=_complete_model_card(),
        approvals=["Alice", "Bob"],
        min_approvals=2,
    )


def test_all_five_gates_passing_allows_funding():
    record = _passing_record()
    assert record.gates() == {
        "shadow_period": True,
        "shadow_matches_validation": True,
        "calibration": True,
        "model_card": True,
        "two_person_approval": True,
    }
    assert can_fund(record) is True
    assert approved_budget(record, 100_000.0) == 100_000.0
    require_can_fund(record)  # must not raise


# One mutation per gate that makes exactly that gate fail while leaving the
# other four passing — i.e. every "4 of 5 pass" combination.
_BREAK_ONE_GATE = {
    "shadow_period": lambda r: setattr(r, "shadow_days", 10),
    "shadow_matches_validation": lambda r: setattr(r, "shadow_vs_validation_delta", 5.0),
    "calibration": lambda r: setattr(r, "calibration_error", 0.9),
    "model_card": lambda r: setattr(r, "model_card", ModelCard()),  # blank card
    "two_person_approval": lambda r: setattr(r, "approvals", ["Alice", "Alice"]),  # not distinct
}


@pytest.mark.parametrize("gate_name", list(_BREAK_ONE_GATE.keys()))
def test_every_four_of_five_combination_refuses_funding(gate_name):
    record = _passing_record()
    _BREAK_ONE_GATE[gate_name](record)

    gates = record.gates()
    # Exactly the targeted gate should have flipped to False; the other four
    # still pass — this really is a 4-of-5 case, not accidentally worse.
    assert gates[gate_name] is False
    passing = [name for name, ok in gates.items() if ok]
    assert len(passing) == 4

    assert can_fund(record) is False
    assert approved_budget(record, 100_000.0) == 0.0
    with pytest.raises(GraduationGateError):
        require_can_fund(record)


def test_no_gates_passing_refuses_funding():
    record = GraduationRecord(model_id="model_z")  # every field at its default/blank
    assert can_fund(record) is False
    assert approved_budget(record, 1.0) == 0.0


def test_model_card_requires_every_section_nonblank():
    incomplete = ModelCard(purpose="x", data="", features="y", training_window="z",
                            validation_protocol="w", known_failure_modes="v",
                            shutoff_conditions="u")
    assert incomplete.is_complete() is False
    assert _complete_model_card().is_complete() is True


def test_two_person_approval_requires_distinct_names():
    record = _passing_record()
    record.approvals = ["Alice", "alice "]  # different casing/whitespace -> distinct here
    assert record.gate_two_person_approval() is True
    record.approvals = ["Alice", "Alice", "Alice"]
    assert record.gate_two_person_approval() is False
    record.approvals = ["Alice"]
    assert record.gate_two_person_approval() is False
    record.approvals = []
    assert record.gate_two_person_approval() is False


def test_approved_budget_rejects_negative_request():
    record = _passing_record()
    with pytest.raises(ValueError):
        approved_budget(record, -1.0)
