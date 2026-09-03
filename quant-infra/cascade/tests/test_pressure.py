"""Tests for cascade/pressure.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pressure import (
    FlowEstimate,
    compute_pressure,
    estimate_flow_from_shares_outstanding,
    estimate_flow_proxy,
)


# --- flow estimation ---------------------------------------------------------

def test_shares_outstanding_flow_basic():
    f = estimate_flow_from_shares_outstanding("FUNDA", "2026-01-01", 1_000_000, 1_050_000, 20.0)
    assert f.flow_dollars == pytest.approx(50_000 * 20.0)
    assert f.method == "shares_outstanding"
    assert f.is_proxy is False


def test_shares_outstanding_outflow_is_negative():
    f = estimate_flow_from_shares_outstanding("FUNDA", "2026-01-01", 1_000_000, 900_000, 10.0)
    assert f.flow_dollars < 0


def test_shares_outstanding_negative_input_raises():
    with pytest.raises(ValueError):
        estimate_flow_from_shares_outstanding("FUNDA", "d", -1, 100, 10.0)
    with pytest.raises(ValueError):
        estimate_flow_from_shares_outstanding("FUNDA", "d", 100, 200, -10.0)


def test_shares_outstanding_nan_input_yields_nan_flow():
    f = estimate_flow_from_shares_outstanding("FUNDA", "d", float("nan"), 100, 10.0)
    assert np.isnan(f.flow_dollars)


def test_shares_outstanding_zero_nav_yields_zero_flow():
    f = estimate_flow_from_shares_outstanding("FUNDA", "d", 100, 200, 0.0)
    assert f.flow_dollars == 0.0


def test_proxy_flow_basic_premium_positive_flow():
    # price above NAV (premium) with positive volume -> positive (inflow-like) proxy flow
    f = estimate_flow_proxy("ETF1", "d", volume_shares=1_000_000, price=101.0, nav_per_share=100.0)
    assert f.flow_dollars > 0
    assert f.is_proxy is True
    assert f.method == "proxy"


def test_proxy_flow_discount_is_negative():
    f = estimate_flow_proxy("ETF1", "d", volume_shares=1_000_000, price=99.0, nav_per_share=100.0)
    assert f.flow_dollars < 0


def test_proxy_flow_zero_volume_is_zero():
    f = estimate_flow_proxy("ETF1", "d", volume_shares=0.0, price=105.0, nav_per_share=100.0)
    assert f.flow_dollars == 0.0


def test_proxy_flow_zero_nav_is_nan():
    f = estimate_flow_proxy("ETF1", "d", volume_shares=1000, price=10.0, nav_per_share=0.0)
    assert np.isnan(f.flow_dollars)


def test_proxy_flow_negative_inputs_raise():
    with pytest.raises(ValueError):
        estimate_flow_proxy("ETF1", "d", volume_shares=-1, price=10.0, nav_per_share=10.0)
    with pytest.raises(ValueError):
        estimate_flow_proxy("ETF1", "d", volume_shares=1, price=-10.0, nav_per_share=10.0)
    with pytest.raises(ValueError):
        estimate_flow_proxy("ETF1", "d", volume_shares=1, price=10.0, nav_per_share=-10.0)


def test_proxy_flow_nan_inputs_yield_nan():
    f = estimate_flow_proxy("ETF1", "d", volume_shares=float("nan"), price=10.0, nav_per_share=10.0)
    assert np.isnan(f.flow_dollars)


# --- compute_pressure --------------------------------------------------------

def _holdings(rows):
    return pd.DataFrame(rows, columns=["product", "constituent", "weight", "as_at_date"])


def test_single_product_single_name():
    holdings = _holdings([("FUNDA", "AAPL", 0.05, "2026-01-01")])
    flow = FlowEstimate("FUNDA", "2026-01-01", flow_dollars=1_000_000, method="shares_outstanding", is_proxy=False)
    tv = {"AAPL": 500_000}
    result = compute_pressure(holdings, [flow], tv)
    row = result.pressure.set_index("constituent").loc["AAPL"]
    expected = 0.05 * 1_000_000 / 500_000
    assert row["pressure"] == pytest.approx(expected)
    assert row["n_products_used"] == 1
    assert row["n_products_total"] == 1
    assert not row["any_proxy"]


def test_name_in_twelve_funds_is_summed_across_all_of_them():
    """The doc's explicit failure-mode warning: a name in many funds must have
    its pressure correctly SUMMED across all of them, not just the last/first
    or averaged."""
    n_funds = 12
    rows = []
    flows = []
    expected_total = 0.0
    rng = np.random.default_rng(7)
    tv = {"MULTI": 2_000_000}
    for i in range(n_funds):
        product = f"FUND{i}"
        weight = float(rng.uniform(0.01, 0.08))
        flow_dollars = float(rng.uniform(-5_000_000, 5_000_000))
        rows.append((product, "MULTI", weight, "2026-01-01"))
        flows.append(FlowEstimate(product, "2026-01-01", flow_dollars, "shares_outstanding", False))
        expected_total += weight * flow_dollars / tv["MULTI"]

    holdings = _holdings(rows)
    result = compute_pressure(holdings, flows, tv)
    row = result.pressure.set_index("constituent").loc["MULTI"]
    assert row["n_products_used"] == n_funds
    assert row["n_products_total"] == n_funds
    assert row["pressure"] == pytest.approx(expected_total, rel=1e-9)
    # sanity: summed across 12 funds must differ from any single leg or a naive average
    single_leg = rows[0][2] * flows[0].flow_dollars / tv["MULTI"]
    assert row["pressure"] != pytest.approx(single_leg)
    assert row["pressure"] != pytest.approx(expected_total / n_funds)


def test_missing_flow_for_a_product_is_skipped_and_flagged():
    holdings = _holdings([
        ("FUNDA", "AAPL", 0.05, "d"),
        ("FUNDB", "AAPL", 0.03, "d"),
    ])
    flow = FlowEstimate("FUNDA", "d", 1_000_000, "shares_outstanding", False)
    tv = {"AAPL": 500_000}
    result = compute_pressure(holdings, [flow], tv)  # no flow for FUNDB
    row = result.pressure.set_index("constituent").loc["AAPL"]
    assert row["n_products_total"] == 2
    assert row["n_products_used"] == 1
    assert "FUNDB" in result.skipped_products
    assert row["pressure"] == pytest.approx(0.05 * 1_000_000 / 500_000)


def test_nan_flow_product_is_skipped():
    holdings = _holdings([("FUNDA", "AAPL", 0.05, "d")])
    flow = FlowEstimate("FUNDA", "d", float("nan"), "proxy", True)
    result = compute_pressure(holdings, [flow], {"AAPL": 100.0})
    row = result.pressure.set_index("constituent").loc["AAPL"]
    assert np.isnan(row["pressure"])
    assert row["n_products_used"] == 0
    assert "FUNDA" in result.skipped_products


def test_nan_weight_leg_is_skipped_not_summed_as_zero():
    holdings = _holdings([
        ("FUNDA", "AAPL", float("nan"), "d"),
        ("FUNDB", "AAPL", 0.03, "d"),
    ])
    flows = [
        FlowEstimate("FUNDA", "d", 1_000_000, "shares_outstanding", False),
        FlowEstimate("FUNDB", "d", 1_000_000, "shares_outstanding", False),
    ]
    result = compute_pressure(holdings, flows, {"AAPL": 500_000})
    row = result.pressure.set_index("constituent").loc["AAPL"]
    assert row["n_products_used"] == 1
    assert row["pressure"] == pytest.approx(0.03 * 1_000_000 / 500_000)


def test_missing_or_nonpositive_typical_volume_excludes_leg():
    holdings = _holdings([
        ("FUNDA", "AAPL", 0.05, "d"),
        ("FUNDA", "MSFT", 0.05, "d"),
        ("FUNDA", "ZERO_VOL", 0.05, "d"),
        ("FUNDA", "NEG_VOL", 0.05, "d"),
    ])
    flow = FlowEstimate("FUNDA", "d", 1_000_000, "shares_outstanding", False)
    tv = {"AAPL": 500_000, "ZERO_VOL": 0.0, "NEG_VOL": -100.0}  # MSFT missing entirely
    result = compute_pressure(holdings, [flow], tv)
    p = result.pressure.set_index("constituent")
    assert p.loc["AAPL", "n_products_used"] == 1
    for name in ("MSFT", "ZERO_VOL", "NEG_VOL"):
        assert p.loc[name, "n_products_used"] == 0
        assert np.isnan(p.loc[name, "pressure"])


def test_any_proxy_flag_true_when_a_contributing_leg_used_proxy():
    holdings = _holdings([
        ("FUNDA", "AAPL", 0.05, "d"),
        ("FUNDB", "AAPL", 0.02, "d"),
    ])
    flows = [
        FlowEstimate("FUNDA", "d", 1_000_000, "shares_outstanding", False),
        FlowEstimate("FUNDB", "d", 500_000, "proxy", True),
    ]
    result = compute_pressure(holdings, flows, {"AAPL": 500_000})
    row = result.pressure.set_index("constituent").loc["AAPL"]
    assert row["any_proxy"] is True or row["any_proxy"] == True  # noqa: E712 (numpy bool)


def test_empty_holdings_returns_empty_well_formed_result():
    holdings = _holdings([])
    result = compute_pressure(holdings, [], {})
    assert result.pressure.empty
    assert list(result.pressure.columns) == [
        "constituent", "pressure", "n_products_total", "n_products_used", "any_proxy",
    ]
    assert result.skipped_products == ()


def test_missing_required_column_raises():
    bad = pd.DataFrame({"product": ["A"], "constituent": ["X"], "weight": [0.1]})  # no as_at_date
    with pytest.raises(ValueError):
        compute_pressure(bad, [], {})


def test_negative_weight_short_leg_flows_through_signed():
    holdings = _holdings([("FUNDA", "AAPL", -0.05, "d")])  # short sleeve
    flow = FlowEstimate("FUNDA", "d", 1_000_000, "shares_outstanding", False)
    result = compute_pressure(holdings, [flow], {"AAPL": 500_000})
    row = result.pressure.set_index("constituent").loc["AAPL"]
    assert row["pressure"] == pytest.approx(-0.05 * 1_000_000 / 500_000)
    assert row["pressure"] < 0
