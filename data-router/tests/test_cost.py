"""Cost meter: pure request/cost accounting plus budget projection."""

import pytest

from router.cost import CostMeter, project_cost


def test_cost_meter_records_and_reads_back():
    meter = CostMeter()
    meter.record("alpha-vantage", "chaos-model", requests=1, cost=0.02)
    meter.record("alpha-vantage", "chaos-model", requests=1, cost=0.02)
    meter.record("alpha-vantage", "backtest-model", requests=5, cost=0.05)

    assert meter.requests("alpha-vantage", "chaos-model") == 2
    assert meter.cost("alpha-vantage", "chaos-model") == pytest.approx(0.04)
    assert meter.requests("alpha-vantage", "backtest-model") == 5
    assert meter.total_requests() == 7
    assert meter.total_cost() == pytest.approx(0.09)


def test_cost_meter_unrecorded_pair_reads_as_zero():
    meter = CostMeter()
    assert meter.requests("nobody", "nothing") == 0
    assert meter.cost("nobody", "nothing") == 0.0


def test_cost_meter_rejects_negative_requests():
    meter = CostMeter()
    with pytest.raises(ValueError):
        meter.record("v", "m", requests=-1)


def test_cost_meter_by_vendor_model_breakdown_is_sorted():
    meter = CostMeter()
    meter.record("z-vendor", "m", requests=1, cost=1.0)
    meter.record("a-vendor", "m", requests=2, cost=2.0)
    rows = meter.by_vendor_model()
    assert [r.vendor for r in rows] == ["a-vendor", "z-vendor"]
    assert rows[0].requests == 2 and rows[0].cost == 2.0


def test_project_cost_under_budget():
    result = project_cost(current_rate=10.0, plan_limit=100.0, periods_remaining=5)
    assert result["projected_total"] == pytest.approx(50.0)
    assert result["over_budget"] is False
    assert result["headroom"] == pytest.approx(50.0)
    assert result["utilization"] == pytest.approx(0.5)


def test_project_cost_over_budget():
    result = project_cost(current_rate=30.0, plan_limit=100.0, periods_remaining=5)
    assert result["projected_total"] == pytest.approx(150.0)
    assert result["over_budget"] is True
    assert result["headroom"] == pytest.approx(-50.0)


def test_project_cost_exactly_at_limit_is_not_over_budget():
    result = project_cost(current_rate=10.0, plan_limit=100.0, periods_remaining=10)
    assert result["projected_total"] == pytest.approx(100.0)
    assert result["over_budget"] is False  # strictly greater-than, not >=


def test_project_cost_zero_plan_limit_has_no_utilization_but_flags_over_budget_if_any_rate():
    result = project_cost(current_rate=1.0, plan_limit=0.0)
    assert result["utilization"] is None
    assert result["over_budget"] is True


def test_project_cost_zero_rate_and_zero_limit_is_not_over_budget():
    result = project_cost(current_rate=0.0, plan_limit=0.0)
    assert result["over_budget"] is False
    assert result["utilization"] is None


def test_project_cost_rejects_negative_inputs():
    with pytest.raises(ValueError):
        project_cost(current_rate=-1.0, plan_limit=10.0)
    with pytest.raises(ValueError):
        project_cost(current_rate=1.0, plan_limit=-10.0)
    with pytest.raises(ValueError):
        project_cost(current_rate=1.0, plan_limit=10.0, periods_remaining=-1)


def test_project_cost_default_periods_remaining_is_one():
    result = project_cost(current_rate=25.0, plan_limit=25.0)
    assert result["projected_total"] == pytest.approx(25.0)
    assert result["over_budget"] is False
