"""Tests for position sizing."""

from __future__ import annotations

import numpy as np
import pytest

from ie.sizing.size import SizeConfig, compute_size


def test_risk_budget_caps_size():
    # Tight stop (1% away) with a generous vol cap -> risk budget binds:
    # 1% budget / 1% stop = 100% raw, clipped by max_weight.
    r = compute_size(entry=100.0, stop=99.0, asset_vol=0.05,
                     expected_r=3.0, cfg=SizeConfig(risk_budget_pct=0.01, max_weight=0.20))
    assert r.binding in ("risk", "max")
    assert r.sizing_pct <= 20.0


def test_wider_stop_smaller_size():
    tight = compute_size(100.0, 99.0, 0.30, 3.0)   # 1% stop
    wide = compute_size(100.0, 90.0, 0.30, 3.0)    # 10% stop
    assert wide.sizing_pct < tight.sizing_pct


def test_vol_target_binds_for_high_vol_names():
    # Tight stop (risk cap generous) + very high asset vol -> vol target binds.
    r = compute_size(100.0, 98.0, asset_vol=0.80,
                     expected_r=3.0, cfg=SizeConfig(target_vol=0.10, risk_budget_pct=0.01))
    # risk cap = 0.01/0.02 = 0.5; vol cap = 0.10/0.80 = 0.125 -> vol binds.
    assert r.binding == "vol"
    assert r.sizing_pct == pytest.approx(0.10 / 0.80 * 100, abs=0.5)


def test_never_exceeds_max_weight():
    r = compute_size(100.0, 99.9, 0.01, 5.0, SizeConfig(max_weight=0.15))
    assert r.sizing_pct <= 15.0


def test_cost_haircut_reduces_net_r():
    r = compute_size(100.0, 95.0, 0.20, expected_r=2.0,
                     cfg=SizeConfig(cost_bps=50))
    # 5% stop, 50bps round trip -> cost_r = 0.005/0.05 = 0.1R.
    assert r.net_r == pytest.approx(1.9, abs=1e-6)
    assert r.gross_r == 2.0


def test_cost_can_kill_a_thin_edge():
    # A trade with a tiny stop and thin edge gets eaten by costs -> not tradeable.
    r = compute_size(100.0, 99.5, 0.20, expected_r=1.1,
                     cfg=SizeConfig(cost_bps=30, min_net_r=1.0))
    # 0.5% stop, 30bps -> cost_r = 0.003/0.005 = 0.6R -> net 0.5R < 1.
    assert r.net_r < 1.0
    assert not r.tradeable


def test_degenerate_stop_is_untradeable():
    r = compute_size(100.0, 100.0, 0.20, 2.0)
    assert r.sizing_pct == 0.0 and not r.tradeable


def test_negative_expectancy_is_untradeable():
    # expected_r is now EXPECTANCY; a negative-edge trade must not be tradeable
    # even at the default (0.0) bar.
    r = compute_size(100.0, 95.0, asset_vol=0.20, expected_r=-0.3)
    assert r.net_r is not None and r.net_r < 0
    assert not r.tradeable


def test_nan_vol_is_untradeable_not_maxed():
    # Fix #7: unknown vol must NOT lift the cap to max_weight — it zeroes the vol
    # cap so the position is untradeable.
    r = compute_size(100.0, 95.0, asset_vol=float("nan"), expected_r=3.0)
    assert r.sizing_pct == 0.0
    assert not r.tradeable


def test_zero_and_inf_vol_are_untradeable():
    for bad in (0.0, -0.1, float("inf")):
        r = compute_size(100.0, 95.0, asset_vol=bad, expected_r=3.0)
        assert r.sizing_pct == 0.0 and not r.tradeable
