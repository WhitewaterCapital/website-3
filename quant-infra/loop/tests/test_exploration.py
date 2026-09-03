"""Tests for loop/exploration.py."""

from __future__ import annotations

import numpy as np
import pytest

from exploration import (
    ChallengerInput,
    _HARD_CEILING_SHARE,
    allocate_exploration_budget,
)


def test_basic_allocation_sums_to_requested_share():
    challengers = [
        ChallengerInput("A", uncertainty=0.1, plausible_edge_estimate=0.5),
        ChallengerInput("B", uncertainty=0.2, plausible_edge_estimate=0.3),
    ]
    result = allocate_exploration_budget(challengers, total_share=0.05)
    assert result.total_share_used == pytest.approx(0.05)
    assert set(result.allocations) == {"A", "B"}
    assert result.hard_capped is False


def test_higher_ucb_score_gets_more_budget():
    challengers = [
        ChallengerInput("HIGH", uncertainty=0.5, plausible_edge_estimate=1.0),
        ChallengerInput("LOW", uncertainty=0.01, plausible_edge_estimate=0.01),
    ]
    result = allocate_exploration_budget(challengers, total_share=0.05, exploration_k=1.0)
    assert result.allocations["HIGH"] > result.allocations["LOW"]


def test_empty_challengers_gives_empty_allocation():
    result = allocate_exploration_budget([], total_share=0.05)
    assert result.allocations == {}
    assert result.total_share_used == 0.0


def test_all_negative_edge_gets_zero_budget_not_forced_spend():
    challengers = [
        ChallengerInput("A", uncertainty=0.0, plausible_edge_estimate=-1.0),
        ChallengerInput("B", uncertainty=0.0, plausible_edge_estimate=-0.5),
    ]
    result = allocate_exploration_budget(challengers, total_share=0.05, exploration_k=0.0)
    assert result.total_share_used == 0.0
    assert all(v == 0.0 for v in result.allocations.values())


def test_nan_inputs_excluded_not_propagated():
    challengers = [
        ChallengerInput("BAD", uncertainty=float("nan"), plausible_edge_estimate=1.0),
        ChallengerInput("GOOD", uncertainty=0.1, plausible_edge_estimate=0.2),
    ]
    result = allocate_exploration_budget(challengers, total_share=0.05)
    assert result.allocations["BAD"] == 0.0
    assert result.allocations["GOOD"] > 0.0
    assert not np.isnan(result.total_share_used)


# --- architectural hard cap: adversarial config cannot exceed it -----------------

def test_requesting_more_than_ceiling_is_clamped_and_flagged():
    challengers = [ChallengerInput("A", uncertainty=1.0, plausible_edge_estimate=1.0)]
    result = allocate_exploration_budget(challengers, total_share=1e9)
    assert result.total_share_used <= _HARD_CEILING_SHARE + 1e-9
    assert result.hard_capped is True
    assert result.requested_share == 1e9


@pytest.mark.parametrize(
    "adversarial_share",
    [1e9, float("inf"), 1.0, 0.5, 10.0, 100.0],
)
def test_no_adversarial_config_can_exceed_the_architectural_ceiling(adversarial_share):
    challengers = [
        ChallengerInput(f"C{i}", uncertainty=float(i + 1), plausible_edge_estimate=float(i + 1))
        for i in range(10)
    ]
    result = allocate_exploration_budget(challengers, total_share=adversarial_share)
    assert result.total_share_used <= _HARD_CEILING_SHARE + 1e-9


def test_nan_total_share_is_clamped_to_zero_not_propagated():
    challengers = [ChallengerInput("A", uncertainty=1.0, plausible_edge_estimate=1.0)]
    result = allocate_exploration_budget(challengers, total_share=float("nan"))
    assert result.total_share_used == 0.0


def test_negative_total_share_clamped_to_zero():
    challengers = [ChallengerInput("A", uncertainty=1.0, plausible_edge_estimate=1.0)]
    result = allocate_exploration_budget(challengers, total_share=-5.0)
    assert result.total_share_used == 0.0
    assert result.hard_capped is False  # negative is below the ceiling, not above it


def test_default_share_is_five_percent():
    challengers = [ChallengerInput("A", uncertainty=1.0, plausible_edge_estimate=1.0)]
    result = allocate_exploration_budget(challengers)
    assert result.total_share_used == pytest.approx(0.05)
