# -*- coding: utf-8 -*-
"""Week-2 tests: assumptions, policies, simulation, MILP, allocation, report.

Run: python tests/test_inventory.py
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.inventory import (
    InventoryAssumptions,
    MilpConfig,
    PolicySpec,
    aggregate_runs,
    allocation_scenarios,
    build_evaluation,
    build_inventory_report,
    build_sku_economics,
    build_store_network,
    economic_order_quantity,
    execute_orders,
    perfect_foresight,
    policy_parameters,
    rolling_horizon,
    run_policy,
    safety_stock,
    service_level_z,
    simulate_demand_scenarios,
    solve_allocation,
    solve_replenishment,
    store_table,
    summarize_portfolio,
    write_inventory_report,
)


def _econ(**overrides) -> dict:
    base = {
        "mean_weekly": 10.0,
        "sigma_weekly": 4.0,
        "moq": 5.0,
        "eoq": 40.0,
        "initial_inventory": 30.0,
        "holding_cost_per_unit_week": 0.01,
        "ordering_cost": 75.0,
        "stockout_cost_per_unit": 2.0,
    }
    base.update(overrides)
    return base


def _econ_frame(n_skus: int = 2, **overrides) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "mean_weekly": [10.0, 5.0][:n_skus],
            "sigma_weekly": [3.0, 2.0][:n_skus],
            "moq": [1.0, 1.0][:n_skus],
            "eoq": [20.0, 10.0][:n_skus],
            "initial_inventory": [0.0, 0.0][:n_skus],
            "holding_cost_per_unit_week": [0.01, 0.01][:n_skus],
            "ordering_cost": [75.0, 75.0][:n_skus],
            "stockout_cost_per_unit": [2.0, 2.0][:n_skus],
        }
    )
    for key, value in overrides.items():
        frame[key] = value
    return frame


def _panel(n_skus: int = 3, n_weeks: int = 60) -> pd.DataFrame:
    rows = []
    weeks = pd.date_range("2020-01-06", periods=n_weeks, freq="7D")
    for index in range(n_skus):
        for position, week in enumerate(weeks):
            base = 5 + index * 2
            seasonal = 1.0 + 0.3 * math.sin(2 * math.pi * position / 26)
            demand = float(round(base * seasonal))
            if position % 11 == 0:
                demand = 0.0
            rows.append(
                {
                    "sku": f"SKU{index:03d}",
                    "week": week,
                    "demand": demand,
                    "revenue": demand * (2.0 + index * 0.5),
                    "orders": int(demand > 0),
                    "description": f"item {index}",
                    "country": "United Kingdom",
                    "avg_price": 2.0 + index * 0.5,
                }
            )
    return pd.DataFrame(rows)


def test_assumption_formulas():
    z = service_level_z(0.95)
    assert 1.64 < z < 1.65
    assert safety_stock(0.95, 4.0, 9) == z * 4.0 * 3.0
    assert safety_stock(0.95, 4.0, 0) == 0.0
    assert economic_order_quantity(1000, 50, 2) == math.sqrt(2 * 1000 * 50 / 2)
    assert economic_order_quantity(0, 50, 2) == 0.0

    assumptions = InventoryAssumptions()
    assumptions.validate()
    assert assumptions.with_overrides(lead_time_weeks=5).lead_time_weeks == 5
    try:
        InventoryAssumptions(service_level=1.0).validate()
    except ValueError:
        pass
    else:
        raise AssertionError("service_level=1.0 应被拒绝")

    economics = build_sku_economics(_panel(), assumptions)
    assert len(economics) == 3
    assert set(
        ["mean_weekly", "sigma_weekly", "cv", "eoq", "moq", "initial_inventory"]
    ).issubset(economics.columns)
    assert (economics["moq"] >= 1.0).all()
    assert np.allclose(
        economics["initial_inventory"],
        economics["mean_weekly"] * assumptions.initial_inventory_weeks,
    )
    assert np.allclose(
        economics["unit_cost"], (economics["price"] * assumptions.cost_ratio).clip(lower=0.01)
    )
    print("[OK] 假设层与公式")


def test_policy_parameters():
    policy = PolicySpec("eoq_rop", 0.95)
    params = policy_parameters(_econ(), policy, lead_time_weeks=3)
    z = service_level_z(0.95)
    assert math.isclose(params["z"], z)
    assert math.isclose(
        params["safety_stock"], z * 4.0 * math.sqrt(3), rel_tol=1e-12
    )
    assert math.isclose(
        params["reorder_point"], 10.0 * 3 + z * 4.0 * math.sqrt(3), rel_tol=1e-12
    )
    assert params["order_quantity"] == 40.0
    try:
        PolicySpec("unknown", 0.95).validate()
    except ValueError:
        pass
    else:
        raise AssertionError("未知策略应被拒绝")
    print("[OK] 策略静态参数")


def test_policy_replay_conservation_and_lead_time():
    policy = PolicySpec("eoq_rop", 0.95)
    demand = np.array([[10.0, 10.0, 10.0, 10.0, 10.0, 10.0]])
    forecast = np.array([10.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    run = run_policy(
        demand,
        forecast,
        _econ(eoq=40.0, moq=5.0, initial_inventory=0.0),
        policy,
        lead_time_weeks=1,
    )
    weekly = run.weekly
    assert np.allclose(weekly["sales"] + weekly["lost"], weekly["demand"])
    assert (weekly["on_hand"] >= -1e-9).all()
    assert (weekly["order_count"] >= 0).all()
    assert np.all((weekly["orders"] == 0) | (weekly["orders"] >= 5.0))
    assert weekly["orders"][0, 0] > 0, "首周应按 ROP 下单"
    assert np.isclose(weekly["sales"][0, 0], 0.0)
    assert np.isclose(weekly["sales"][0, 1], 10.0), "首周订单应在 lead=1 后到货"
    assert run.summary["fill_rate"] < 1.0
    assert 0.0 <= run.summary["sku_week_instock_rate"] <= 1.0

    # (R, S): only review weeks can place an order.
    periodic = PolicySpec("periodic", 0.95, review_period_weeks=2)
    run = run_policy(
        demand,
        forecast,
        _econ(eoq=40.0, moq=1.0, initial_inventory=0.0),
        periodic,
        lead_time_weeks=0,
    )
    orders = run.weekly["order_count"][0]
    assert orders[1] == 0.0 and orders[3] == 0.0 and orders[5] == 0.0
    assert orders[0] > 0.0 and orders[2] > 0.0
    print("[OK] 策略仿真守恒、提前期与周期复核")


def test_monte_carlo_reproducible_and_mean_preserving():
    forecast = np.array([10.0, 20.0, 30.0])
    econ = {"zero_share": 0.25, "cv": 0.6}
    first = simulate_demand_scenarios(forecast, econ, n_simulations=4000, seed=11)
    second = simulate_demand_scenarios(forecast, econ, n_simulations=4000, seed=11)
    other = simulate_demand_scenarios(forecast, econ, n_simulations=4000, seed=12)
    assert first.shape == (4000, 3)
    assert np.array_equal(first, second)
    assert not np.array_equal(first, other)
    assert (first >= 0).all()
    assert np.allclose(first.mean(axis=0), forecast, rtol=0.10)
    # The zero-inflated branch should produce exact zeros.
    assert np.mean(first == 0) > 0.1
    print("[OK] Monte Carlo 可复现且均值保持")


def test_aggregate_runs_kpis():
    policies = [PolicySpec("eoq_rop", 0.95)]
    demand = np.array([[10.0, 5.0, 0.0, 8.0]])
    forecast = np.array([8.0, 8.0, 8.0, 8.0])
    runs = {
        "A": {"eoq_rop": run_policy(demand, forecast, _econ(initial_inventory=5.0), policies[0], 1)},
        "B": {"eoq_rop": run_policy(demand * 0.5, forecast, _econ(initial_inventory=2.0), policies[0], 1)},
    }
    economics = pd.DataFrame(
        {
            "holding_cost_per_unit_week": [0.01, 0.01],
            "ordering_cost": [75.0, 75.0],
            "stockout_cost_per_unit": [2.0, 2.0],
        },
        index=["A", "B"],
    )
    portfolio = aggregate_runs(runs, economics, "eoq_rop", weeks=4)
    assert len(portfolio) == 1
    row = portfolio.iloc[0]
    assert np.isclose(row["demand_units"], demand.sum() + (demand * 0.5).sum())
    assert 0.0 <= row["fill_rate"] <= 1.0
    assert 0.0 <= row["sku_week_instock_rate"] <= 1.0
    assert row["avg_on_hand"] >= 0.0
    assert row["total_cost"] >= 0.0
    summary = summarize_portfolio(portfolio, policies[0])
    assert summary["fill_rate"] == row["fill_rate"]
    assert summary["sku_week_instock_rate"] == row["sku_week_instock_rate"]
    print("[OK] 组合 KPI 聚合")


def test_milp_balance_and_capacity():
    demand = np.array([[10.0, 10.0, 10.0, 10.0], [5.0, 5.0, 5.0, 5.0]])
    economics = _econ_frame(
        ordering_cost=[5.0, 5.0], stockout_cost_per_unit=[20.0, 20.0]
    )
    config = MilpConfig(horizon_weeks=4, lead_time_weeks=1, time_limit_seconds=5, workers=1)
    plan = solve_replenishment(
        demand,
        economics,
        config,
        initial_inventory=np.zeros(2),
        storage_capacity=1000,
        throughput_capacity=1000,
    )
    assert plan.status in {"OPTIMAL", "FEASIBLE"}
    assert plan.orders.shape == demand.shape
    inventory = plan.inventory
    for i in range(2):
        for t in range(4):
            previous = 0.0 if t == 0 else inventory[i, t - 1]
            receipt = 0.0 if t < 1 else plan.orders[i, t - 1]
            assert np.isclose(
                inventory[i, t],
                previous + receipt - demand[i, t] + plan.unmet[i, t],
                atol=1e-6,
            )
            assert plan.orders[i, t] == 0.0 or plan.orders[i, t] >= 1.0 - 1e-6
    assert np.isclose(plan.unmet[:, 0].sum(), demand[:, 0].sum())

    perfect = perfect_foresight(
        demand,
        economics,
        config,
        storage_capacity=1000,
        throughput_capacity=1000,
        initial_inventory=np.zeros(2),
    )
    assert np.isclose(perfect["fill_rate"], 0.75), perfect["fill_rate"]
    assert np.isclose(
        perfect["sales"] + perfect["lost"], demand, atol=1e-6
    ).all()

    blocked = perfect_foresight(
        demand,
        economics,
        config,
        storage_capacity=1000,
        throughput_capacity=0.0,
        initial_inventory=np.zeros(2),
    )
    assert np.isclose(blocked["fill_rate"], 0.0)
    assert np.isclose(blocked["lost_units"], demand.sum())

    executed = execute_orders(
        perfect["orders"],
        demand,
        economics,
        initial_inventory=np.zeros(2),
        lead_time_weeks=1,
    )
    assert np.isclose(executed["fill_rate"], perfect["fill_rate"], atol=1e-6)
    assert np.isclose(executed["lost_units"], perfect["lost_units"], atol=1e-6)
    print("[OK] MILP 库存平衡、共享产能与出库执行")


def test_rolling_horizon_and_safety_buffer():
    actual = np.array([[10.0] * 6, [5.0] * 6])
    forecast = actual.copy()
    economics = _econ_frame()
    config = MilpConfig(horizon_weeks=6, lead_time_weeks=1, time_limit_seconds=5, workers=1)
    initial = np.array([20.0, 10.0])
    result = rolling_horizon(
        actual,
        forecast,
        economics,
        config,
        storage_capacity=1000,
        throughput_capacity=1000,
        initial_inventory=initial,
    )
    assert result["fill_rate"] >= 0.0
    assert result["replans"] == 6
    assert all(status in {"OPTIMAL", "FEASIBLE"} for status in result["statuses"])
    assert np.isclose(result["avg_on_hand"], result["inventory"].sum(axis=0).mean())
    deterministic = MilpConfig(
        horizon_weeks=6, lead_time_weeks=1, deterministic_time=1.0, workers=1
    )
    det_runs = [
        rolling_horizon(
            actual,
            forecast,
            economics,
            deterministic,
            storage_capacity=1000,
            throughput_capacity=1000,
            initial_inventory=initial,
        )
        for _ in range(2)
    ]
    assert np.array_equal(det_runs[0]["orders"], det_runs[1]["orders"])
    assert det_runs[0]["fill_rate"] == det_runs[1]["fill_rate"]
    buffered = rolling_horizon(
        actual,
        forecast,
        economics,
        config,
        storage_capacity=1000,
        throughput_capacity=1000,
        initial_inventory=initial,
        safety_stock=np.array([2.0, 1.0]),
    )
    assert buffered["orders"].shape == actual.shape
    assert buffered["fill_rate"] >= 0.0
    print("[OK] 滚动时域与安全库存缓冲")


def test_allocation_lp_constraints_and_priority():
    demand = np.array([[10.0, 5.0], [8.0, 6.0]])
    supply = np.array([[15.0, 10.0], [20.0, 20.0]])
    transport = np.array([[1.0, 2.0], [3.0, 1.0]])
    result = solve_allocation(
        demand,
        supply,
        transport,
        shortage_penalty=100.0,
        name="test",
    )
    assert result.status == "OPTIMAL"
    assert np.isclose(result.shipped_units, demand.sum())
    assert np.isclose(result.unmet_units, 0.0)
    assert np.isclose(result.fill_rate, 1.0)
    assert (result.shipments.sum(axis=1) <= supply + 1e-6).all()
    expected_transport = (result.shipments.sum(axis=2) * transport).sum()
    assert np.isclose(result.transport_cost, expected_transport)

    scarce = solve_allocation(
        np.array([[10.0], [5.0]]),
        np.array([[5.0], [0.0]]),
        np.zeros((2, 2)),
        priority=np.array([1.0, 2.0]),
        shortage_penalty=1.0,
        name="priority",
    )
    assert np.isclose(scarce.store_fill[1], 1.0)
    assert np.isclose(scarce.store_fill[0], 0.0)
    assert np.isclose(scarce.unmet_units, 10.0)

    capped = solve_allocation(
        np.array([[10.0, 10.0]]),
        np.array([[20.0, 20.0]]),
        np.zeros((1, 1)),
        store_capacity=np.array([12.0]),
        name="capped",
    )
    assert np.isclose(capped.shipped_units, 12.0)
    assert np.isclose(capped.unmet_units, 8.0)
    print("[OK] 分配 LP 约束、成本与优先级")


def test_store_network_and_scenarios():
    network = build_store_network(np.array([10.0, 5.0, 2.0, 1.0]), n_stores=8)
    assert network["demand"].shape == (8, 4)
    assert np.isclose(network["demand"].sum(), 18.0)
    assert np.isclose(network["supply"].sum(), 18.0 * network["supply_factor"])
    assert np.isclose(network["store_capacity"].sum(), network["demand"].sum(axis=1).sum() * network["store_capacity_factor"])
    assert network["priority"].shape == (8,)
    assert set(np.unique(network["priority"])) <= {0.6, 1.0, 1.6}
    results = allocation_scenarios(network, shortage_penalty=8.0)
    assert set(results) == {"unconstrained", "capacity", "priority"}
    assert np.isclose(results["unconstrained"].fill_rate, 1.0)
    assert 0.0 < results["capacity"].fill_rate < 1.0
    stores = store_table(results["priority"])
    assert len(stores) == 8
    assert np.allclose(stores["demand_units"], stores["shipped_units"] + stores["unmet_units"])
    print("[OK] 门店网络与分配场景")


def test_evaluation_and_report():
    panel = _panel(n_skus=3, n_weeks=60)
    evaluation = build_evaluation(panel, eval_weeks=8, history_weeks=52)
    assert len(evaluation.weeks) == 8
    assert evaluation.skus == ["SKU000", "SKU001", "SKU002"]
    assert evaluation.forecast["seasonal_naive"].shape == (8, 3)
    assert np.isfinite(evaluation.forecast_accuracy()["wmape"]).all()
    restricted = evaluation.restrict(["SKU001"])
    assert restricted.skus == ["SKU001"]
    assert restricted.forecast["seasonal_naive"].shape == (8, 1)

    replay = pd.DataFrame(
        [
            {
                "label": "(s, Q) 连续补货",
                "policy": "eoq_rop",
                "fill_rate": 0.93,
                "sku_week_instock_rate": 0.95,
                "stockout_week_rate": 0.96,
                "avg_on_hand": 100.0,
                "turns": 5.0,
                "holding_cost": 10.0,
                "ordering_cost": 20.0,
                "stockout_cost": 30.0,
                "total_cost": 60.0,
                "cost_per_unit": 0.2,
            }
        ]
    )
    mc = pd.DataFrame(
        [
            {
                "label": "(s, Q) 连续补货",
                "fill_rate_p5": 0.9,
                "fill_rate_p50": 0.92,
                "fill_rate_p95": 0.94,
                "total_cost_p5": 50.0,
                "total_cost_p50": 60.0,
                "total_cost_p95": 70.0,
                "turns": 5.0,
            }
        ]
    )
    accuracy = pd.DataFrame(
        [{"forecast": "lightgbm", "wmape": 0.75, "bias": 0.08, "units": 1000.0}]
    )
    sweep = pd.DataFrame(
        [
            {
                "service_level": 0.95,
                "z": 1.64,
                "fill_rate": 0.93,
                "sku_week_instock_rate": 0.95,
                "stockout_week_rate": 0.96,
                "avg_on_hand": 100.0,
                "turns": 5.0,
                "holding_cost": 10.0,
                "ordering_cost": 20.0,
                "stockout_cost": 30.0,
                "total_cost": 60.0,
            }
        ]
    )
    lead_time = pd.DataFrame(
        [
            {
                "lead_time_weeks": 3,
                "label": "(s, Q) 连续补货",
                "fill_rate": 0.93,
                "sku_week_instock_rate": 0.95,
                "avg_on_hand": 100.0,
                "turns": 5.0,
                "total_cost": 60.0,
            }
        ]
    )
    milp = {
        "skus": 2,
        "weeks": 4,
        "lead_time_weeks": 1,
        "storage_capacity": 1000.0,
        "throughput_capacity": 500.0,
        "comparison": pd.DataFrame(
            [
                {
                    "method": "MILP: rolling horizon",
                    "fill_rate": 0.8,
                    "total_cost": 100.0,
                    "cost_per_unit": 0.2,
                    "turns": 8.0,
                    "fixed_orders": 4.0,
                    "solve_seconds": 0.1,
                }
            ]
        ),
        "statuses": {"OPTIMAL": 4},
        "buffered_statuses": {"OPTIMAL": 4},
        "utilization": {
            "rolling_storage_peak": 0.4,
            "rolling_throughput_peak": 0.9,
            "buffered_storage_peak": 0.5,
            "buffered_throughput_peak": 0.95,
            "perfect_storage_peak": 0.6,
            "perfect_throughput_peak": 1.0,
        },
    }
    allocation = {
        "summary": pd.DataFrame(
            [
                {
                    "scenario": "capacity",
                    "status": "OPTIMAL",
                    "fill_rate": 0.9,
                    "unmet_units": 10.0,
                    "transport_cost": 20.0,
                    "shortage_cost": 30.0,
                    "total_cost": 50.0,
                    "cost_per_unit": 0.5,
                    "solve_seconds": 0.01,
                }
            ]
        ),
        "stores": pd.DataFrame(
            [
                {
                    "store": "S1",
                    "demand_units": 100.0,
                    "shipped_units": 90.0,
                    "unmet_units": 10.0,
                    "fill_rate": 0.9,
                    "dc1_share": 1.0,
                }
            ]
        ),
        "config": {"stores": 1, "skus": 2, "supply_factor": 0.9, "store_capacity_factor": 0.95},
    }
    results = {
        "dataset": {
            "skus": 3,
            "skus_excluded_insufficient_history": 0,
            "min_history_nonzero_weeks": 13,
            "eval_start": "2021-01-04",
            "eval_end": "2021-02-22",
            "eval_weeks": 8,
            "history_start": "2020-01-06",
            "history_end": "2020-12-28",
            "history_weeks": 52,
            "primary_forecast": "lightgbm",
            "forecast_wmape": 0.75,
        },
        "assumptions": InventoryAssumptions().to_dict(),
        "assumption_summary": {
            "annual_units": 1000.0,
            "annual_revenue_at_price": 2000.0,
            "median_cv": 0.8,
            "median_zero_share": 0.1,
            "median_eoq": 100.0,
        },
        "assumption_rows": [
            {"parameter": "lead time", "value": "3 weeks", "source": "assumed", "note": ""}
        ],
        "forecast_accuracy": accuracy,
        "policy_replay": replay,
        "policy_mc": mc,
        "forecast_comparison": pd.DataFrame(),
        "service_sweep": sweep,
        "lead_time": lead_time,
        "milp": milp,
        "allocation": allocation,
    }
    summary, markdown = build_inventory_report(results, title="Test report")
    for section in ("## 3.", "## 7.", "## 8.", "## 9."):
        assert section in markdown
    assert "SKU-week in-stock" in markdown
    assert summary["title"] == "Test report"
    assert summary["policy_replay"]

    with tempfile.TemporaryDirectory() as tmp:
        paths = write_inventory_report(results, tmp, title="Test report", detail=replay)
        for name in ("markdown", "summary", "detail"):
            assert paths[name].exists(), f"{name} 未生成"
        payload = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert payload["milp"]["skus"] == 2
        assert "MILP" in paths["markdown"].read_text(encoding="utf-8")
    print("[OK] 评估切分与报告生成")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 2 inventory tests")
    print("=" * 56)
    tests = [
        test_assumption_formulas,
        test_policy_parameters,
        test_policy_replay_conservation_and_lead_time,
        test_monte_carlo_reproducible_and_mean_preserving,
        test_aggregate_runs_kpis,
        test_milp_balance_and_capacity,
        test_rolling_horizon_and_safety_buffer,
        test_allocation_lp_constraints_and_priority,
        test_store_network_and_scenarios,
        test_evaluation_and_report,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All inventory tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
