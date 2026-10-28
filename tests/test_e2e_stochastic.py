# -*- coding: utf-8 -*-
"""Week-14 tests: scenario construction, CVaR placement and report.

Run: python tests/test_e2e_stochastic.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.e2e import (
    DemandScenario,
    ScenarioSet,
    build_demand_scenarios,
    build_stochastic_report,
    empirical_cvar,
    pick_proxy,
    planned_stock_instance,
    planned_stock_totals,
    score_placement,
    stochastic_placement,
    write_stochastic_report,
)
from supply.e2e.instances import E2EInstance, PickPlan
from supply.fulfillment import FulfillmentInstance
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)


def _instance(
    stock=(10, 10, 0, 0),
    capacity=(100, 100),
    n_skus: int = 2,
) -> E2EInstance:
    """10 orders over ``n_skus`` SKUs, two DCs, North 1 day and South 5 days."""
    n = 10
    sku_index = np.arange(n) % n_skus
    skus = [chr(ord("A") + index) for index in range(n_skus)]
    stock_array = np.asarray(stock, dtype=np.int64)
    assert stock_array.size == 2 * n_skus
    stock_array = stock_array.reshape(2, n_skus)
    fulfillment = FulfillmentInstance(
        order_ids=[f"O{index:02d}" for index in range(n)],
        destinations=["United Kingdom"] * n,
        line_order=np.arange(n),
        line_sku=sku_index.astype(np.int64),
        line_qty=np.full(n, 5, dtype=np.int64),
        sku_names=skus,
        dc_names=["North", "South"],
        stock=stock_array,
        dc_capacity=np.asarray(capacity, dtype=np.int64),
        ship_cost=np.ones((2, n), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.array([[1] * n, [5] * n], dtype=np.int64),
        promise_days=np.full(n, 2, dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=100.0,
        meta={},
    )
    pick = PickPlan(
        tier_of={f"O{index:02d}": "express" for index in range(n)},
        cutoff_of={f"O{index:02d}": 240 for index in range(n)},
        arrival_of={f"O{index:02d}": 0.0 for index in range(n)},
        tier_onsite={"express": 1.0, "standard": 1.0, "economy": 1.0},
        tier_windows={"express": 0.0, "standard": 0.0, "economy": 0.0},
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=LAYOUT,
        slots={name: (1, index + 1, 0) for index, name in enumerate(skus)},
        pick=pick,
        pickers_per_dc=1,
        shift_minutes=600.0,
        meta={},
    )


def _scenario_set(
    demand=(10, 10),
    serviceable=None,
    target: int = 20,
    n_scenarios: int = 2,
) -> ScenarioSet:
    demand = np.asarray(demand, dtype=np.int64)
    if serviceable is None:
        serviceable = np.zeros((n_scenarios, 2, demand.size), dtype=np.int64)
        for scenario in range(n_scenarios):
            serviceable[scenario, 0] = demand
            serviceable[scenario, 1] = demand
    serviceable = np.asarray(serviceable, dtype=np.int64)
    scenarios = tuple(
        DemandScenario(
            week=f"2011-11-{7 + 7 * index:02d}",
            weight=1.0 / n_scenarios,
            demand=demand,
            serviceable=serviceable[index],
            raw_units=int(demand.sum()),
            scale=1.0,
            history_lines=10,
            active_skus=int((demand > 0).sum()),
        )
        for index in range(n_scenarios)
    )
    return ScenarioSet(
        scenarios=scenarios,
        sku_names=("A", "B"),
        dc_names=("North", "South"),
        target_units=target,
        promise_shares=((2, 1.0),),
    )


def test_build_demand_scenarios_alignment_and_scaling():
    week = pd.Timestamp("2012-01-30")
    clean = pd.DataFrame(
        [
            ("A", "United Kingdom", 10.0, week - pd.Timedelta(weeks=1)),
            ("A", "France", 10.0, week - pd.Timedelta(weeks=1)),
            ("B", "United Kingdom", 30.0, week - pd.Timedelta(weeks=1)),
            ("A", "United Kingdom", 20.0, week - pd.Timedelta(weeks=2)),
            ("B", "France", 20.0, week - pd.Timedelta(weeks=2)),
            # A week with only an unmapped country must be skipped, not zeroed.
            ("A", "Atlantis", 99.0, week - pd.Timedelta(weeks=3)),
            ("A", "United Kingdom", 999.0, week),
        ],
        columns=["sku", "country", "quantity", "week"],
    )
    scenarios = build_demand_scenarios(
        clean, ["A", "B"], week, target_units=1000, lookback_weeks=3
    )
    assert scenarios.weeks == ["2012-01-16", "2012-01-23"]
    assert "2012-01-09" not in scenarios.weeks
    assert len(scenarios.scenarios) == 2
    assert np.allclose(scenarios.weights, 0.5)
    assert scenarios.target_units == 1000
    for scenario in scenarios.scenarios:
        assert abs(int(scenario.demand.sum()) - 1000) <= 2
        assert scenario.serviceable.shape == (3, 2)
        assert np.all(scenario.serviceable >= 0)
        assert np.all(scenario.serviceable <= scenario.demand[None, :])
        assert scenario.active_skus == 2
        assert scenario.history_lines in (2, 3)
    # Equal weight and alignment: each scenario holds the same SKU order.
    assert np.array_equal(scenarios.demand.sum(axis=1), [1000, 1000])

    payload = scenarios.as_dict()
    assert payload["weeks"] == scenarios.weeks
    assert payload["target_units"] == 1000
    assert len(payload["scenarios"]) == 2

    for kwargs in (
        dict(lookback_weeks=0),
        dict(target_units=0),
        dict(lookback_weeks=1, target_units=1000, dcs=[]),
        dict(promise_shares=((2, 0.5), (3, 0.4))),
    ):
        try:
            build_demand_scenarios(
                clean,
                ["A", "B"],
                week,
                **{"target_units": 1000, **kwargs},
            )
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法场景参数: {kwargs}")

    try:
        build_demand_scenarios(clean, ["A", "A"], week, 1000)
    except ValueError:
        pass
    else:
        raise AssertionError("应拒绝重复 SKU 列表")

    try:
        build_demand_scenarios(
            clean, ["A", "B"], pd.Timestamp("2012-01-16"), 1000, lookback_weeks=1
        )
    except ValueError:
        pass
    else:
        raise AssertionError("回看窗口没有任何映射需求时应报错")
    print("[OK] 场景按周对齐、缩放为目标总量并跳过无映射数据的周")


def test_empirical_cvar_interpolates_upper_tail():
    assert np.isclose(empirical_cvar([1, 2, 3, 4], 0.5), 3.5)
    assert np.isclose(empirical_cvar([1, 2, 3, 4], 0.75), 4.0)
    values = [10, 20, 30, 40, 50, 60]
    # 1 - alpha = 0.2 -> mass 1.2: (60 + 0.2 * 50) / 1.2
    assert np.isclose(empirical_cvar(values, 0.8), (60 + 0.2 * 50) / 1.2)
    assert np.isclose(empirical_cvar([7, 7, 7], 0.9), 7.0)
    for bad in ([], values):
        for alpha in (0.0, 1.0, -0.5):
            try:
                empirical_cvar(bad, alpha)
            except ValueError:
                continue
            raise AssertionError(f"应拒绝非法 CVaR 输入: {bad}, {alpha}")
    try:
        empirical_cvar([1.0, float("inf")], 0.8)
    except ValueError:
        pass
    else:
        raise AssertionError("应拒绝非有限 CVaR 观测")
    print("[OK] 经验 CVaR 使用上尾线性插值并校验输入")


def test_planned_stock_uses_scenario_mean():
    scenarios = _scenario_set(demand=(10, 20), target=30)
    totals = planned_stock_totals(scenarios, stock_factor=0.85)
    # numpy rounds halves to even: 10 * 0.85 = 8.5 -> 8, 20 * 0.85 -> 17.
    assert totals.tolist() == [8, 17]

    totals = planned_stock_totals(
        _scenario_set(demand=(9, 21), target=30), stock_factor=0.85
    )
    assert totals.tolist() == [8, 18]

    for factor in (0.0, -0.1, 2.1):
        try:
            planned_stock_totals(scenarios, stock_factor=factor)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法 stock_factor: {factor}")

    empty = _scenario_set(demand=(0, 0), target=10)
    try:
        planned_stock_totals(empty)
    except ValueError:
        pass
    else:
        raise AssertionError("场景均值为零时应拒绝规划库存")
    print("[OK] 库存总量取场景均值 × stock_factor，不使用目标周结构")


def test_planned_stock_instance_equal_split():
    instance = _instance(stock=(10, 10, 0, 0))
    planned = planned_stock_instance(instance, np.array([5, 3]), key="mean", label="均值")
    assert planned.fulfillment.stock.sum(axis=0).tolist() == [5, 3]
    assert planned.fulfillment.stock.shape == (2, 2)
    assert planned.order_ids == instance.order_ids
    assert planned.meta["stock_plan"] == "mean"
    assert planned.meta["stock_source"] == "scenario_mean"
    assert planned.meta["stock_units"] == 8
    assert np.allclose(planned.meta["stock_shares"], [0.5, 0.5])

    for bad in (
        np.array([5, 3, 1]),
        np.array([-1, 3]),
        np.array([0, 0]),
    ):
        try:
            planned_stock_instance(instance, bad)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法库存总量: {bad.tolist()}")
    print("[OK] 场景均值库存等分到各 DC 并保留订单与元数据")


def test_pick_proxy_matches_route_model():
    instance = _instance()
    coefficient, capacity = pick_proxy(instance)
    assert coefficient > 0
    assert capacity == 600.0
    loose, _ = pick_proxy(instance, congestion_margin=0.0)
    assert np.isclose(coefficient, loose * 1.2)

    explicit, explicit_capacity = pick_proxy(
        instance, pick_minutes_per_unit=0.1, pickers_per_dc=2, shift_minutes=300
    )
    assert np.isclose(explicit, 0.1)
    assert explicit_capacity == 600.0

    no_slots = _instance()
    no_slots.slots = {}
    try:
        pick_proxy(no_slots)
    except ValueError:
        pass
    else:
        raise AssertionError("缺少槽位且未给系数时应报错")

    for kwargs in (
        dict(pick_minutes_per_unit=0.0),
        dict(congestion_margin=-0.1),
        dict(pickers_per_dc=0),
        dict(shift_minutes=0.0),
    ):
        try:
            pick_proxy(instance, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法拣选代理参数: {kwargs}")
    print("[OK] 拣选分钟代理由订单路线与工时模型校准，并校验参数")


def test_stochastic_placement_concentrates_stock():
    instance = _instance(stock=(10, 10, 0, 0))
    serviceable = np.array(
        [
            [[10, 0], [0, 10]],
            [[10, 0], [0, 10]],
        ]
    )
    scenarios = _scenario_set(demand=(10, 10), serviceable=serviceable)
    result = stochastic_placement(
        instance,
        scenarios,
        time_limit_seconds=5.0,
        workers=1,
        pick_minutes_per_unit=0.01,
        shift_minutes=100.0,
    )
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.stock.tolist() == [[10, 0], [0, 10]]
    assert result.expected_unmet == 0.0
    assert result.cvar_unmet == 0.0
    assert result.scenario_unmet.tolist() == [0.0, 0.0]
    assert result.stock.sum(axis=0).tolist() == [10, 10]
    assert np.allclose(result.mix, [0.5, 0.5])
    assert np.isclose(result.peak_minutes, 0.01 * 10)
    payload = result.as_dict()
    assert payload["stock_units"] == [10, 10]
    assert payload["peak_minutes"] == result.peak_minutes
    print("[OK] 两阶段模型把每个 SKU 放到唯一可服务的 DC，未满足为零")


def test_stochastic_placement_allows_zero_stock_sku():
    # SKU B has no stock but demand: all five units are unmet.
    instance = _instance(stock=(10, 0, 0, 0))
    scenarios = _scenario_set(demand=(10, 5), target=15)
    result = stochastic_placement(
        instance,
        scenarios,
        time_limit_seconds=5.0,
        workers=1,
        pick_minutes_per_unit=0.01,
        shift_minutes=100.0,
    )
    assert result.stock.sum(axis=0).tolist() == [10, 0]
    assert result.expected_unmet == 5.0
    assert result.silent_skus == 0
    print("[OK] 允许场景均值为零的 SKU，其需求全部计为未满足")


def test_stochastic_placement_falls_back_for_silent_sku():
    instance = _instance(stock=(10, 10, 5, 5), n_skus=2)
    # B has stock but zero demand in every scenario -> silent; fallback to South.
    serviceable = np.array(
        [
            [[10, 0], [0, 0]],
            [[10, 0], [0, 0]],
        ]
    )
    scenarios = _scenario_set(demand=(10, 0), serviceable=serviceable, target=10)
    fallback = np.array([[0.0, 1.0], [0.0, 1.0]])
    result = stochastic_placement(
        instance,
        scenarios,
        time_limit_seconds=5.0,
        workers=1,
        fallback_shares=fallback,
        pick_minutes_per_unit=0.01,
        shift_minutes=100.0,
    )
    assert result.silent_skus == 1
    assert result.expected_unmet == 0.0
    assert result.stock.sum(axis=0).tolist() == [15, 15]
    assert result.stock[:, 1].tolist() == [0, 15]
    print("[OK] 无场景信号的 SKU 按回退占比落位并保持总量")


def test_stochastic_placement_validates_inputs():
    instance = _instance(stock=(10, 10, 0, 0))
    scenarios = _scenario_set(demand=(10, 10))
    for kwargs in (
        dict(cvar_weight=-0.1),
        dict(cvar_weight=1.1),
        dict(alpha=0.0),
        dict(alpha=1.0),
        dict(time_limit_seconds=0.0),
        dict(workers=0),
    ):
        try:
            stochastic_placement(instance, scenarios, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法随机布点参数: {kwargs}")

    for hint in (
        np.zeros((3, 2), dtype=np.int64),
        np.array([[11, 10], [0, 0]], dtype=np.int64),
        np.array([[-1, 10], [21, 0]], dtype=np.int64),
    ):
        try:
            stochastic_placement(instance, scenarios, hint_stock=hint)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法提示布点: {hint.tolist()}")

    mismatch = _scenario_set(demand=(10, 10))
    mismatch = ScenarioSet(
        scenarios=mismatch.scenarios,
        sku_names=("A", "B"),
        dc_names=("South", "North"),
        target_units=20,
        promise_shares=((2, 1.0),),
    )
    try:
        stochastic_placement(instance, mismatch)
    except ValueError:
        pass
    else:
        raise AssertionError("应拒绝 DC 顺序不一致的场景集")
    print("[OK] 随机布点校验权重、alpha、时限、提示与实例对齐")


def test_score_placement_bounds_and_capacity():
    serviceable = np.array(
        [
            [[10, 0], [0, 10]],
            [[10, 0], [0, 10]],
        ]
    )
    scenarios = _scenario_set(demand=(10, 10), serviceable=serviceable)
    good = score_placement(
        np.array([[10, 0], [0, 10]]), scenarios, np.array([100, 100])
    )
    assert good["status"] == "OPTIMAL"
    assert np.isclose(good["expected_unmet_rate"], 0.0)
    assert np.isclose(good["cvar_unmet_rate"], 0.0)

    # Everything in North: South's SKU B cannot ship from North.
    partial = score_placement(
        np.array([[10, 10], [0, 0]]), scenarios, np.array([100, 100])
    )
    assert np.isclose(partial["expected_unmet"], 10.0)
    assert np.isclose(partial["expected_unmet_rate"], 0.5)

    # Pick budget of 5 units per DC leaves 10 of 20 units unserved.
    capped = score_placement(
        np.array([[10, 0], [0, 10]]),
        scenarios,
        np.array([100, 100]),
        pick_minutes_per_unit=1.0,
        pick_capacity_per_dc=5.0,
    )
    assert np.isclose(capped["expected_unmet"], 10.0)

    for bad in (
        dict(stock=np.zeros((3, 2), dtype=np.int64)),
        dict(stock=np.array([[10, 0], [-1, 11]])),
        dict(dc_capacity=np.zeros(2, dtype=np.int64)),
        dict(alpha=0.0),
        dict(time_limit_seconds=0.0),
        dict(pick_minutes_per_unit=0.1),
    ):
        kwargs = {
            "stock": np.array([[10, 0], [0, 10]]),
            "dc_capacity": np.array([100, 100]),
        }
        kwargs.update(bad)
        try:
            score_placement(scenarios=scenarios, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法固定布点评分: {bad}")
    print("[OK] 固定布点评分受可服务需求、产能与拣选预算约束")


def _summary_rows(means: dict[str, float], reps: int) -> list[dict]:
    rows = []
    for scenario, mean in means.items():
        for metric in ("e2e_otif_rate", "pick_on_time_rate", "pick_tardiness", "pick_makespan"):
            value = {
                "e2e_otif_rate": mean,
                "pick_on_time_rate": min(1.0, mean + 0.55),
                "pick_tardiness": 2000.0 * (1.0 - mean),
                "pick_makespan": 700.0,
            }[metric]
            rows.append(
                {
                    "scenario": scenario,
                    "cell": "base",
                    "cell_label": "基准：均匀到达 · 确定性",
                    "metric": metric,
                    "n": 30 * reps,
                    "mean": value,
                    "ci95": 0.01,
                    "p10": value * 0.95,
                    "p50": value,
                    "p90": value * 1.05,
                    "tail10": value * 0.95,
                }
            )
    return rows


def _report_payload(reps: int = 3, flat_sweep: bool = True) -> dict:
    keys = [
        "declared",
        "destination",
        "destination_capped",
        "stochastic_expected",
        "stochastic_cvar",
    ]
    labels = {
        "declared": "Week-5 基线 34/28/38",
        "destination": "目的地历史布点",
        "destination_capped": "目的地历史 + 产能封顶",
        "stochastic_expected": "场景均值最优 (λ=0)",
        "stochastic_cvar": "场景 CVaR (λ=0.5)",
    }
    mixes = {
        "declared": [0.34, 0.28, 0.38],
        "destination": [0.83, 0.08, 0.09],
        "destination_capped": [0.62, 0.19, 0.19],
        "stochastic_expected": [0.34, 0.34, 0.32],
        "stochastic_cvar": [0.33, 0.32, 0.35],
    }
    predicted_rates = {
        "declared": (0.320, 0.321),
        "destination": (0.636, 0.648),
        "destination_capped": (0.457, 0.469),
        "stochastic_expected": (0.320, 0.320),
        "stochastic_cvar": (0.320, 0.320),
    }
    means = {
        "declared": 0.320,
        "destination": 0.129,
        "destination_capped": 0.188,
        "stochastic_expected": 0.407,
        "stochastic_cvar": 0.373,
    }
    placements = []
    for key in keys:
        share = mixes[key]
        peak = 0.07952 * 28115 * max(share)
        placements.append(
            {
                "key": key,
                "label": labels[key],
                "stock_mix": share,
                "stock_units": [int(28115 * value) for value in share],
                "coverage": 0.85,
                "peak_pick_minutes": peak,
                "peak_vs_shift": peak / 600.0,
                "dcs": ["London", "Rotterdam", "Frankfurt"],
                "source": "stochastic" if key.startswith("stochastic") else "baseline",
                "note": "测试布点",
            }
        )
    predicted = [
        {
            "key": key,
            "label": labels[key],
            "expected_unmet_rate": predicted_rates[key][0],
            "cvar_unmet_rate": predicted_rates[key][1],
            "scenario_unmet_rate": [
                predicted_rates[key][0] - 0.001,
                predicted_rates[key][0] + 0.001,
            ],
            "status": "OPTIMAL",
        }
        for key in keys
    ]
    sweep = []
    flat_mixes = ([0.34, 0.34, 0.32], [0.33, 0.33, 0.34], [0.32, 0.34, 0.34])
    for index, lam in enumerate((0.0, 0.5, 1.0)):
        if flat_sweep:
            mix = flat_mixes[index]
            expected, cvar = 0.320, 0.320
        else:
            mix = [0.30 + 0.10 * lam, 0.35, 0.35 - 0.10 * lam]
            expected, cvar = 0.320 + 0.010 * lam, 0.330 + 0.005 * lam
        sweep.append(
            {
                "lambda": lam,
                "status": "OPTIMAL",
                "stock_mix": mix,
                "stock_units": [int(28115 * value) for value in mix],
                "expected_unmet_rate": expected,
                "cvar_unmet_rate": cvar,
                "objective": 10600.0,
                "gap": 0.0,
                "peak_minutes": 763.0,
                "solve_seconds": 12.0,
            }
        )
    allocations = [
        {
            "key": key,
            "label": labels[key],
            "status": "FEASIBLE",
            "fill": 0.695 if key == "declared" else 0.68,
            "fill_min": 0.69,
            "fill_max": 0.70,
            "tickets": 700,
            "alloc_otif_rate": 0.472 if key == "declared" else 0.42,
            "alloc_otif_min": 0.44 if reps > 1 else 0.42,
            "alloc_otif_max": 0.50 if reps > 1 else 0.42,
            "alloc_cost": 89000.0,
            "solve_seconds": 30.0,
            "gap": 0.03,
            "reps": reps,
        }
        for key in keys
    ]
    paired = [
        {
            "scenario": "stochastic_expected",
            "cell": "base",
            "cell_label": "基准：均匀到达 · 确定性",
            "left": "declared",
            "right": "stochastic_expected",
            "comparison": "场景均值最优 (λ=0) − Week-5 基线 34/28/38",
            "metric": "e2e_otif_rate",
            "n": 30 * reps,
            "mean_delta": 0.087,
            "ci95": 0.02 if reps > 1 else 0.0,
            "win_rate": 0.8,
            "loss_rate": 0.2,
            "tie_rate": 0.0,
            "min_delta": -0.05,
            "max_delta": 0.20,
        },
        {
            "scenario": "stochastic_cvar",
            "cell": "base",
            "cell_label": "基准：均匀到达 · 确定性",
            "left": "stochastic_expected",
            "right": "stochastic_cvar",
            "comparison": "场景 CVaR (λ=0.5) − 场景均值最优 (λ=0)",
            "metric": "e2e_otif_rate",
            "n": 30 * reps,
            "mean_delta": -0.034,
            "ci95": 0.01 if reps > 1 else 0.0,
            "win_rate": 0.2,
            "loss_rate": 0.8,
            "tie_rate": 0.0,
            "min_delta": -0.10,
            "max_delta": 0.02,
        },
    ]
    over_shift = [
        {
            "scenario": key,
            "cell": "base",
            "n": 30 * reps,
            "over_shift_rate": 1.0,
            "mean_makespan": 700.0,
            "p90_makespan": 720.0,
        }
        for key in keys
    ]
    dc_rows = [
        {
            "scenario": key,
            "dc": dc,
            "tickets": 200,
            "waves": 25,
            "labor_minutes": 400.0,
            "on_time_tickets": 180,
            "tardy_tickets": 20,
            "tardiness_minutes": 120.0,
            "makespan": 660.0,
        }
        for key in keys
        for dc in ("London", "Rotterdam", "Frankfurt")
    ]
    return {
        "dataset": {
            "orders": 400,
            "lines": 2477,
            "units": 33060,
            "week": "2011-11-28",
            "dcs": ["London", "Rotterdam", "Frankfurt"],
            "pickers_per_dc": 1,
            "shift_minutes": 600.0,
            "max_orders": 8,
            "max_lines": 40,
        },
        "seeds": list(range(1, 31)),
        "reps": reps,
        "settings": {
            "stock_factor": 0.85,
            "service_time": 30.0,
            "milp_time": 60.0,
            "lookback_weeks": 6,
            "cvar_weight": 0.5,
            "cvar_alpha": 0.8,
        },
        "scenarios": {
            "target_units": 33060,
            "weeks": ["2011-10-17", "2011-11-21"],
            "scenarios": [
                {
                    "week": "2011-10-17",
                    "weight": 0.5,
                    "raw_units": 33080,
                    "scale": 0.999,
                    "active_skus": 185,
                    "history_lines": 2859,
                    "serviceable_share": [0.918, 0.928, 0.697],
                },
                {
                    "week": "2011-11-21",
                    "weight": 0.5,
                    "raw_units": 45550,
                    "scale": 0.726,
                    "active_skus": 188,
                    "history_lines": 4281,
                    "serviceable_share": [0.955, 0.961, 0.701],
                },
            ],
        },
        "stock_plan": {
            "stock_units": 28115,
            "target_units": 33060,
            "coverage": 0.85,
        },
        "pick_proxy": {
            "minutes_per_unit": 0.07952,
            "capacity_per_dc": 600.0,
            "congestion_margin": 0.2,
        },
        "placements": placements,
        "predicted": predicted,
        "sweep": sweep,
        "allocations": allocations,
        "summary": _summary_rows(means, reps),
        "over_shift": over_shift,
        "paired": paired,
        "dc_workload": dc_rows,
        "cells": [
            {
                "key": "base",
                "label": "基准：均匀到达 · 确定性",
                "policy": "edf",
                "profile": "均匀到达",
                "duration_noise": 0.0,
                "pickers_per_dc": 1,
            }
        ],
        "declared_assumptions": ["订单来自 Online Retail II", "库存总量取场景均值"],
    }


def test_report_sections_and_conditional_claims():
    payload = _report_payload(reps=3)
    markdown = build_stochastic_report(payload)
    for section in (
        "## Assumptions",
        "## Methods",
        "## Demand scenarios",
        "## Stock placements",
        "## Predicted service",
        "## CVaR weight sweep",
        "## Allocation outcomes",
        "## End-to-end OTIF distribution",
        "## Execution risk",
        "## Placement differences",
        "## Per-DC workload",
        "## Interpretation",
        "## Limitations",
    ):
        assert section in markdown, section
    assert "The scenario placement wins the out-of-sample week" in markdown
    assert "The CVaR placement lowers realized OTIF" in markdown
    assert "CVaR weight is not identified on this scenario set" in markdown
    assert "The fluid score tracks unit fill, not end-to-end OTIF" in markdown
    assert "Allocation solver noise is material" in markdown
    assert "Demand history ignores pick capacity" in markdown
    assert "nan%" not in markdown

    single = _report_payload(reps=1)
    markdown = build_stochastic_report(single)
    assert "single allocation solve" in markdown
    assert "degenerate because every replay is identical" in markdown

    spread = _report_payload(reps=3, flat_sweep=False)
    markdown = build_stochastic_report(spread)
    assert "CVaR weight changes the predicted risk" in markdown
    assert (
        "The predicted risk moved across the sweep, yet the realized gain did not "
        "follow" in markdown
    )

    capped = _report_payload(reps=3)
    for row in capped["predicted"]:
        if row["key"] == "destination_capped":
            row["expected_unmet_rate"] = 0.240
            row["cvar_unmet_rate"] = 0.250
    markdown = build_stochastic_report(capped)
    assert "Capping demand history beats the declared split" in markdown

    short = _report_payload(reps=3)
    short["settings"]["lookback_weeks"] = 4
    markdown = build_stochastic_report(short)
    assert "The 4-week set is too short" in markdown
    print("[OK] 报告包含全部分节，并按数值条件选择解读语句")


def test_write_stochastic_report_roundtrips():
    payload = _report_payload(reps=3)
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_stochastic_report(payload, tmp, title="Week 14 测试")
        report = Path(paths["report"])
        summary = Path(paths["summary"])
        assert report.exists() and summary.exists()
        text = report.read_text(encoding="utf-8")
        assert text.startswith("# Week 14 测试")
        data = json.loads(summary.read_text(encoding="utf-8"))
        assert data["title"] == "Week 14 测试"
        assert data["dataset"]["orders"] == 400
        assert len(data["placements"]) == 5
        # Stock arrays must never leak into the JSON payload.
        assert all("stock" not in row for row in data["placements"])
    print("[OK] 报告写入 Markdown 与可回读的 JSON 摘要")


def main() -> None:
    test_build_demand_scenarios_alignment_and_scaling()
    test_empirical_cvar_interpolates_upper_tail()
    test_planned_stock_uses_scenario_mean()
    test_planned_stock_instance_equal_split()
    test_pick_proxy_matches_route_model()
    test_stochastic_placement_concentrates_stock()
    test_stochastic_placement_allows_zero_stock_sku()
    test_stochastic_placement_falls_back_for_silent_sku()
    test_stochastic_placement_validates_inputs()
    test_score_placement_bounds_and_capacity()
    test_report_sections_and_conditional_claims()
    test_write_stochastic_report_roundtrips()
    print("\nAll Week 14 tests passed.")


if __name__ == "__main__":
    main()
