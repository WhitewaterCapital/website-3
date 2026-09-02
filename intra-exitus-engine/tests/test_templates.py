"""Tests for the regime-conditional level templates.

These assert the plans are *geometrically self-consistent* — for a long,
stop < entry < targets; for a short, targets < entry < stop — that direction is
read from the stretch / trend sign (never invented), and that the abstain paths
fire when they should.
"""

from __future__ import annotations

import numpy as np
import pytest

from ie.levels.ou import OUParams
from ie.levels.templates import (
    LevelConfig,
    abstain_plan,
    mean_revert_plan,
    trend_plan,
)


def _ou(mu, sigma_eq, half_life=20.0, reverts=True):
    """Hand-built OUParams for template tests (log-price units)."""
    return OUParams(
        mu=mu, theta=np.log(2) / half_life, sigma_eq=sigma_eq, half_life=half_life,
        b=float(np.exp(-np.log(2) / half_life)), sigma_resid=sigma_eq * 0.3,
        r2=0.5, n=200, reverts=reverts,
    )


# --- mean-revert ------------------------------------------------------------


def test_mean_revert_stretched_high_is_short_and_consistent():
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, half_life=20.0)
    price = float(np.exp(ou.mu + 2.2 * ou.sigma_eq))  # 2.2 sigma above mean
    plan = mean_revert_plan("TEST", price, ou, LevelConfig())
    assert plan.bias == "short"
    assert plan.confidence in ("actionable", "watch")
    lo, hi = plan.entry_zone
    # Short geometry: targets (toward mean, below) < entry < stop (above).
    assert max(plan.targets) < hi <= plan.stop
    assert plan.stop > hi
    assert plan.expected_r is not None and plan.expected_r > 0


def test_mean_revert_stretched_low_is_long_and_consistent():
    ou = _ou(mu=np.log(50.0), sigma_eq=0.04, half_life=15.0)
    price = float(np.exp(ou.mu - 2.2 * ou.sigma_eq))  # stretched below
    plan = mean_revert_plan("TEST", price, ou, LevelConfig())
    assert plan.bias == "long"
    lo, hi = plan.entry_zone
    # Long geometry: stop (below) < entry < targets (toward mean, above).
    assert plan.stop < lo
    assert min(plan.targets) > lo
    assert plan.expected_r is None or plan.expected_r > 0


def test_mean_revert_near_mean_is_watch():
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05)
    price = float(np.exp(ou.mu + 0.3 * ou.sigma_eq))  # inside the entry threshold
    plan = mean_revert_plan("TEST", price, ou, LevelConfig(enter_sigma=1.0))
    assert plan.bias == "none"
    assert plan.confidence == "watch"
    assert plan.entry_zone is None
    # The reason must land in `rationale` (not the time_stop slot).
    assert "sigma from the mean" in plan.rationale


def test_mean_revert_beyond_stop_abstains_short():
    # Fix #1: a stretch at/beyond stop_sigma has no room to fade -> abstain, never
    # ship inverted geometry (stop inside the entry zone / negative risk).
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, half_life=20.0)
    price = float(np.exp(ou.mu + 3.5 * ou.sigma_eq))  # 3.5 sigma > stop_sigma=3
    plan = mean_revert_plan("TEST", price, ou, LevelConfig(stop_sigma=3.0))
    assert plan.confidence == "insufficient"
    assert plan.entry_zone is None


def test_mean_revert_beyond_stop_abstains_long():
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, half_life=20.0)
    price = float(np.exp(ou.mu - 3.5 * ou.sigma_eq))
    plan = mean_revert_plan("TEST", price, ou, LevelConfig(stop_sigma=3.0))
    assert plan.confidence == "insufficient"
    assert plan.entry_zone is None


def test_actionable_implies_positive_expectancy_and_reachable():
    # Fix #1/#2/#6: expected_r is now EXPECTANCY. Any ACTIONABLE plan must clear
    # min_expectancy, and a real stretch inside [enter_sigma, stop_sigma) must be
    # able to reach actionable.
    cfg = LevelConfig()
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, half_life=20.0)
    found_actionable = False
    for zmult in [1.6, 1.8, 2.0, 2.2, 2.5, 2.8]:
        price = float(np.exp(ou.mu + zmult * ou.sigma_eq))
        plan = mean_revert_plan("T", price, ou, cfg)
        if plan.confidence == "actionable":
            found_actionable = True
            assert plan.expected_r >= cfg.min_expectancy
    assert found_actionable, "no stretch in [enter_sigma, stop_sigma) is actionable"


def test_mean_revert_expectancy_varies_with_stretch():
    # Fix #1: expected_r must MOVE with the setup, not be a constant. A deeper
    # stretch (bigger reward:risk and stronger pull) => higher expectancy.
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, half_life=20.0)
    er = []
    for zmult in [1.7, 2.2, 2.7]:
        price = float(np.exp(ou.mu + zmult * ou.sigma_eq))
        p = mean_revert_plan("T", price, ou, LevelConfig())
        er.append(p.expected_r)
    assert all(e is not None for e in er)
    assert er[0] < er[1] < er[2]  # monotonically increasing, i.e. not constant


def test_mean_revert_nonreverting_abstains():
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, reverts=False)
    plan = mean_revert_plan("TEST", 100.0, ou, LevelConfig())
    assert plan.confidence == "insufficient"


def test_mean_revert_too_slow_abstains():
    ou = _ou(mu=np.log(100.0), sigma_eq=0.05, half_life=120.0)
    price = float(np.exp(ou.mu + 2 * ou.sigma_eq))
    plan = mean_revert_plan("TEST", price, ou, LevelConfig(max_half_life=40.0))
    assert plan.confidence == "insufficient"
    assert "Half-life" in plan.rationale  # reason in the right field, not time_stop


def test_mean_revert_time_stop_scales_with_half_life():
    cfg = LevelConfig(time_stop_half_lives=2.0)
    short_hl = _ou(np.log(100.0), 0.05, half_life=10.0)
    long_hl = _ou(np.log(100.0), 0.05, half_life=30.0)
    price = float(np.exp(np.log(100.0) + 2.2 * 0.05))
    p_short = mean_revert_plan("T", price, short_hl, cfg)
    p_long = mean_revert_plan("T", price, long_hl, cfg)
    # 2x10=20d vs 2x30=60d -> the long-half-life plan quotes a longer time-stop.
    assert "20" in p_short.time_stop and "60" in p_long.time_stop


# --- trend ------------------------------------------------------------------


def test_trend_up_is_long_and_consistent():
    plan = trend_plan("TEST", price=105.0, anchor=104.0, atr=2.0,
                      swing_low=100.0, swing_high=108.0, direction="up",
                      drift_per_bar=0.05, vol_per_bar=1.0)
    assert plan.bias == "long"
    lo, hi = plan.entry_zone
    assert plan.stop < lo                      # stop below entry
    assert all(t > hi for t in plan.targets)   # targets above entry
    assert plan.targets == sorted(plan.targets)  # scale upward
    assert plan.expected_r is not None         # a real expectancy, not a constant


def test_trend_expected_r_varies_with_drift_and_vol():
    # Fix #1: expected_r must respond to drift and vol, not be hardcoded to 2.0.
    base = dict(ticker="T", price=100.0, anchor=100.0, atr=2.0,
                swing_low=97.0, swing_high=103.0, direction="up",
                cfg=LevelConfig(pullback_atr=0.0))
    strong = trend_plan(**base, drift_per_bar=0.10, vol_per_bar=1.0).expected_r
    weak = trend_plan(**base, drift_per_bar=0.00, vol_per_bar=1.0).expected_r
    noisier = trend_plan(**base, drift_per_bar=0.10, vol_per_bar=3.0).expected_r
    assert strong is not None and weak is not None and noisier is not None
    assert strong > weak                 # more favourable drift => higher expectancy
    assert strong != noisier             # vol changes the probability => not constant


def test_trend_expected_r_none_without_inputs_downgrades():
    # No drift/vol provided => expectancy can't be estimated => watch, not actionable.
    plan = trend_plan("T", price=105.0, anchor=104.0, atr=2.0,
                      swing_low=100.0, swing_high=108.0, direction="up")
    assert plan.expected_r is None
    assert plan.confidence == "watch"


def test_trend_down_is_short_and_consistent():
    plan = trend_plan("TEST", price=95.0, anchor=96.0, atr=2.0,
                      swing_low=92.0, swing_high=100.0, direction="down")
    assert plan.bias == "short"
    lo, hi = plan.entry_zone
    assert plan.stop > hi                       # stop above entry
    assert all(t < lo for t in plan.targets)    # targets below entry
    assert plan.targets == sorted(plan.targets, reverse=True)  # scale downward


def test_trend_targets_are_r_multiples():
    cfg = LevelConfig(trend_targets_r=(2.0, 4.0), pullback_atr=0.0, atr_buffer=1.0)
    plan = trend_plan("T", price=100.0, anchor=100.0, atr=2.0,
                      swing_low=97.0, swing_high=103.0, direction="up", cfg=cfg)
    entry = plan.entry_zone[1]
    risk = entry - plan.stop
    assert plan.targets[0] == pytest.approx(entry + 2 * risk, abs=0.01)
    assert plan.targets[1] == pytest.approx(entry + 4 * risk, abs=0.01)


def test_trend_zero_atr_abstains():
    plan = trend_plan("T", 100.0, 100.0, 0.0, 98.0, 102.0, "up")
    assert plan.confidence == "insufficient"


def test_trend_incoherent_long_at_fresh_lows_abstains():
    # Fix #8: "uptrend" (slow-MA read) but price is at fresh 20-day lows -> the
    # direction and the swing structure contradict; abstain.
    plan = trend_plan("T", price=100.0, anchor=104.0, atr=2.0,
                      swing_low=100.0, swing_high=112.0, direction="up")
    assert plan.confidence == "insufficient"
    assert "Incoherent" in plan.rationale


def test_trend_incoherent_short_at_fresh_highs_abstains():
    plan = trend_plan("T", price=112.0, anchor=108.0, atr=2.0,
                      swing_low=100.0, swing_high=112.0, direction="down")
    assert plan.confidence == "insufficient"


def test_trend_loose_stop_downgrades_to_watch():
    # A downtrend name whose swing high sits ~20% above entry: stop too loose.
    plan = trend_plan("F", price=14.0, anchor=14.0, atr=0.3,
                      swing_low=13.0, swing_high=16.0, direction="down",
                      cfg=LevelConfig(max_stop_frac=0.15))
    assert plan.confidence == "watch"
    assert "too loose" in plan.rationale


def test_trend_targets_never_negative():
    # Wide risk relative to price must never produce a negative-price target.
    plan = trend_plan("F", price=14.0, anchor=14.0, atr=0.4,
                      swing_low=13.0, swing_high=16.5, direction="down")
    assert all(t > 0 for t in plan.targets)


# --- abstain plumbing -------------------------------------------------------


def test_abstain_plan_shape():
    p = abstain_plan("T", "too hot")
    assert p.confidence == "insufficient"
    assert p.entry_zone is None and p.targets == []
    d = p.as_dict()
    assert d["entryZone"] is None and d["regime"] == "high-vol"
