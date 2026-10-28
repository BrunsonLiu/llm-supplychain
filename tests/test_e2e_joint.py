# -*- coding: utf-8 -*-
"""Week-13 tests: joint allocation and stock placement.

Run: python tests/test_e2e_joint.py
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
    PlacementPlan,
    allocate_joint,
    build_joint_report,
    cap_shares,
    capacity_aware_allocation,
    destination_mix,
    paired_placements,
    placement_from_shares,
    with_stock,
    write_joint_report,
)
from supply.e2e.instances import E2EInstance, PickPlan
from supply.fulfillment import FulfillmentInstance
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)


def _instance(stock=(50, 0), capacity=(100, 100)) -> E2EInstance:
    n = 10
    fulfillment = FulfillmentInstance(
        order_ids=[f"O{index:02d}" for index in range(n)],
        destinations=["United Kingdom"] * n,
        line_order=np.arange(n),
        line_sku=np.zeros(n, dtype=np.int64),
        line_qty=np.full(n, 5, dtype=np.int64),
        sku_names=["A"],
        dc_names=["North", "South"],
        stock=np.array([[stock[0]], [stock[1]]], dtype=np.int64),
        dc_capacity=np.array(capacity, dtype=np.int64),
        ship_cost=np.ones((2, n), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.array([[5] * n, [1] * n], dtype=np.int64),
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
        slots={"A": (1, 1, 0)},
        pick=pick,
        pickers_per_dc=1,
        shift_minutes=600.0,
        meta={},
    )


def test_destination_mix_history_and_fallback():
    week = pd.Timestamp("2012-01-02")
    clean = pd.DataFrame(
        [
            ("A", "United Kingdom", 10.0, week - pd.Timedelta(weeks=1)),
            ("A", "France", 5.0, week - pd.Timedelta(weeks=1)),
            ("A", "United Kingdom", 20.0, week - pd.Timedelta(weeks=2)),
            ("A", "France", 5.0, week - pd.Timedelta(weeks=2)),
            ("A", "United Kingdom", 1000.0, week),
            ("B", "France", 7.0, week - pd.Timedelta(weeks=20)),
        ],
        columns=["sku", "country", "quantity", "week"],
    )
    mix = destination_mix(
        clean, ["A", "B"], week, lookback_weeks=8, eu_split=(0.45, 0.55)
    )
    assert mix.history_skus == 1 and mix.fallback_skus == 1
    assert mix.weeks_used == 2
    assert mix.start_week == "2011-12-19" and mix.end_week == "2011-12-26"
    assert np.allclose(mix.shares[0], [0.75, 0.1125, 0.1375])
    assert np.allclose(mix.shares[1], [0.34, 0.28, 0.38])
    assert np.allclose(mix.shares.sum(axis=1), 1.0)

    for kwargs in (
        dict(lookback_weeks=0),
        dict(eu_split=(0.6, 0.6)),
        dict(fallback=(0.5, 0.5)),
    ):
        try:
            destination_mix(clean, ["A"], week, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法目的地历史参数: {kwargs}")
    print("[OK] 目的地历史按 SKU 回看前 8 周，无历史回退声明占比")


def test_placement_materialization_keeps_totals():
    instance = _instance(stock=(3, 2))
    plan = placement_from_shares(
        instance,
        np.array([[2.0 / 3.0, 1.0 / 3.0]]),
        key="split",
        label="测试布点",
    )
    assert plan.stock.tolist() == [[3], [2]]
    assert plan.units == 5
    assert np.isclose(sum(plan.mix), 1.0)
    payload = plan.as_dict(instance.fulfillment.dc_names)
    assert payload["stock_units"] == [3, 2]
    assert payload["dcs"] == ["North", "South"]

    for bad in (
        dict(key="", label="x"),
        dict(key="x", label=""),
    ):
        try:
            PlacementPlan(stock=np.zeros((2, 1), dtype=np.int64), **bad)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝缺少 key/label 的布点: {bad}")

    try:
        placement_from_shares(
            instance, np.array([[1.0, 0.0, 0.0]]), key="x", label="x"
        )
    except ValueError:
        pass
    else:
        raise AssertionError("应拒绝与 DC 数不符的占比矩阵")
    print("[OK] 布点按最大余数法拆分，总量与占比保持不变")


def test_with_stock_preserves_orders_and_meta():
    instance = _instance(stock=(30, 20))
    moved = with_stock(
        instance, np.array([[10], [40]]), key="destination", label="目的地历史"
    )
    assert moved.fulfillment.stock.tolist() == [[10], [40]]
    assert moved.order_ids == instance.order_ids
    assert moved.pick.arrival_of == instance.pick.arrival_of
    assert moved.meta["stock_plan"] == "destination"
    assert moved.meta["stock_placement_label"] == "目的地历史"
    assert moved.meta["stock_units"] == 50
    assert np.allclose(moved.meta["stock_shares"], [0.2, 0.8])

    for bad in (
        np.array([[50], [1]]),
        np.array([[-1], [51]]),
        np.array([[10, 0], [40, 0]]),
    ):
        try:
            with_stock(instance, bad)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法库存替换: {bad.tolist()}")
    print("[OK] 替换库存保留订单/到达，更新元数据并校验每 SKU 总量")


def test_joint_places_stock_where_it_ships():
    instance = _instance(stock=(50, 0))
    declared = capacity_aware_allocation(instance, service_time=1.0, milp_time=1.0)
    assert declared.unit_fill_rate == 1.0
    assert declared.otif_rate == 0.0, "声明布点只能从 5 天的北方发货"

    joint = allocate_joint(
        instance,
        time_limit_seconds=5.0,
        workers=1,
        otif_bonus=200.0,
        pick_deadlines={2: 240},
        pick_overload_penalty=0.0,
    )
    assert joint.status in {"OPTIMAL", "FEASIBLE"}
    assert joint.allocation.otif_rate == 1.0
    assert joint.stock.tolist() == [[0], [50]]
    assert joint.stock.sum(axis=0).tolist() == [50]
    payload = joint.as_dict()
    assert payload["stock_units"] == [0, 50]
    print("[OK] 联合模型把库存放到实际发货的 DC，声明布点无法按时履约")


def test_joint_respects_pooled_stock_and_capacity():
    instance = _instance(stock=(50, 0), capacity=(100, 20))
    joint = allocate_joint(
        instance,
        time_limit_seconds=5.0,
        workers=1,
        max_splits=1,
        otif_bonus=200.0,
    )
    assert np.all(joint.allocation.dc_units <= instance.fulfillment.dc_capacity)
    assert joint.allocation.dc_units[1] <= 20
    assert joint.allocation.stock_used.sum() <= 50
    assert joint.stock.sum(axis=0).tolist() == [50]
    flags = np.zeros((instance.fulfillment.n_orders, 2), dtype=bool)
    for line in range(instance.fulfillment.n_lines):
        flags[instance.fulfillment.line_order[line]] |= (
            joint.allocation.shipments[line] > 0
        )
    assert int(flags.sum(axis=1).max()) <= 1
    print("[OK] 联合模型分摊后仍受每 SKU 总量、DC 产能与拆单上限约束")


def test_capacity_aware_allocation_two_stage():
    instance = _instance(stock=(50, 0))
    result = capacity_aware_allocation(instance, service_time=1.0, milp_time=1.0)
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.name.endswith("拣选容量感知")
    assert result.dc_units[0] == 50
    assert result.unit_fill_rate == 1.0
    try:
        capacity_aware_allocation(instance, service_time=0.0)
    except ValueError:
        pass
    else:
        raise AssertionError("应拒绝非正的服务优先时限")
    print("[OK] 固定布点上的两阶段容量感知分单可复现且参数受校验")


def test_cap_shares_clips_to_throughput():
    shares = np.array(
        [
            [0.90, 0.05, 0.05],
            [0.20, 0.50, 0.30],
        ]
    )
    capacity = np.array([500.0, 300.0, 200.0])  # caps 0.50 / 0.30 / 0.20
    capped = cap_shares(shares, capacity, stock_units=1000)
    assert np.allclose(capped.sum(axis=1), 1.0)
    assert np.all(capped <= capacity / 1000.0 + 1e-12)
    assert np.allclose(capped[0], [0.50, 0.30, 0.20]), "超额应按剩余空间再分配"
    assert np.allclose(capped[1], [0.50, 0.30, 0.20]), "两行最终都顶到产能上界"

    untouched = cap_shares(
        np.array([[0.40, 0.25, 0.35]]), np.array([500.0, 300.0, 400.0]), 1000
    )
    assert np.allclose(untouched, [[0.40, 0.25, 0.35]]), "未触顶的 SKU 不应被改动"

    for bad in (
        (np.zeros((2, 3)), capacity, 1000),  # 行和为 0
        (shares, capacity, 0),  # 库存总量非正
        (shares[:, :2], capacity, 1000),  # 形状不匹配
        (shares, np.array([100.0, 100.0, 100.0]), 1000),  # 产能之和不足
        (shares, np.array([500.0, 0.0, 500.0]), 1000),  # 产能非正
    ):
        try:
            cap_shares(*bad)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法封顶输入: {[np.shape(item) for item in bad]}")

    normalized = cap_shares(
        np.full((2, 3), 0.5), np.array([600.0, 500.0, 500.0]), 1000
    )
    assert np.allclose(normalized, 1.0 / 3.0)
    print("[OK] 历史占比按 DC 产能封顶并保持每 SKU 总量守恒")


def test_paired_placements_statistics():
    rows = []
    for seed, (left, right) in enumerate(
        [(0.30, 0.40), (0.40, 0.40), (0.30, 0.20)], start=1
    ):
        for cell in ("base", "noise"):
            rows.append(
                {
                    "scenario": "declared",
                    "cell": cell,
                    "cell_label": "基准" if cell == "base" else "噪声",
                    "seed": seed,
                    "e2e_otif_rate": left,
                }
            )
            rows.append(
                {
                    "scenario": "destination",
                    "cell": cell,
                    "cell_label": "基准" if cell == "base" else "噪声",
                    "seed": seed,
                    "e2e_otif_rate": right,
                }
            )
    frame = pd.DataFrame(rows)
    paired = paired_placements(
        frame,
        "declared",
        "destination",
        labels={"declared": "基线", "destination": "历史"},
    )
    assert len(paired) == 2
    for row in paired.itertuples():
        assert row.comparison == "历史 − 基线"
        assert row.n == 3
        assert abs(row.mean_delta) < 1e-12
        assert abs(row.win_rate - 1.0 / 3.0) < 1e-12
        assert abs(row.loss_rate - 1.0 / 3.0) < 1e-12
        assert abs(row.tie_rate - 1.0 / 3.0) < 1e-12
        assert row.metric == "e2e_otif_rate"
    try:
        paired_placements(frame, "declared", "destination", metric="missing")
    except ValueError:
        pass
    else:
        raise AssertionError("应拒绝缺失指标")
    print("[OK] 布点配对按共享种子计算差值、胜/负/平率与 95% 区间")


def _summary_rows(means: dict[tuple[str, str], float]) -> list[dict]:
    cells = {
        "base": "基准：均匀到达 · 确定性",
        "two_pickers": "加 1 名拣货员/DC",
    }
    rows = []
    for (scenario, cell), mean in means.items():
        for metric in (
            "e2e_otif_rate",
            "pick_on_time_rate",
            "pick_tardiness",
            "pick_makespan",
        ):
            if metric == "e2e_otif_rate":
                value = mean
            elif metric == "pick_on_time_rate":
                value = min(1.0, mean + 0.4)
            elif metric == "pick_tardiness":
                value = 1000.0 * (1.0 - mean)
            else:
                value = 500.0 + 100.0 * (1.0 - mean)
            rows.append(
                {
                    "scenario": scenario,
                    "cell": cell,
                    "cell_label": cells[cell],
                    "policy": "edf",
                    "profile": "均匀到达",
                    "duration_noise": 0.0,
                    "metric": metric,
                    "metric_label": metric,
                    "n": 30,
                    "mean": value,
                    "sd": 0.01,
                    "ci95": 0.01,
                    "p10": value * 0.95,
                    "p50": value,
                    "p90": value * 1.05,
                    "min": value * 0.9,
                    "max": value * 1.1,
                    "tail10": value * 0.95,
                    "tail_direction": "down"
                    if metric == "e2e_otif_rate"
                    else "up",
                }
            )
    return rows


def _payload() -> dict:
    keys = [
        "declared",
        "destination",
        "destination_capped",
        "joint_placement",
        "joint_plan",
    ]
    labels = {
        "declared": "Week-5 基线 34/28/38",
        "destination": "目的地历史布点",
        "destination_capped": "目的地历史 + 产能封顶",
        "joint_placement": "联合布点 + 标准分单",
        "joint_plan": "联合规划（分单+布点）",
    }
    means = {
        ("declared", "base"): 0.30,
        ("destination", "base"): 0.33,
        ("destination_capped", "base"): 0.38,
        ("joint_placement", "base"): 0.40,
        ("joint_plan", "base"): 0.42,
    }
    for key in keys:
        means[(key, "two_pickers")] = 0.50
    summaries = _summary_rows(means)

    allocations = [
        {
            "key": key,
            "label": labels[key],
            "status": "FEASIBLE",
            "fill": 0.82,
            "tickets": 576,
            "alloc_otif_rate": bound,
            "alloc_cost": 62000.0,
            "solve_seconds": 60.0,
            "gap": 0.05,
        }
        for key, bound in zip(keys, (0.500, 0.510, 0.530, 0.550, 0.600))
    ]
    placements = [
        {
            "key": "declared",
            "label": labels["declared"],
            "stock_mix": [0.35, 0.27, 0.38],
            "stock_units": [3400, 2800, 3800],
            "coverage": 0.85,
            "source": "declared",
            "note": "声明占比 + 抖动",
        },
        {
            "key": "destination",
            "label": labels["destination"],
            "stock_mix": [0.55, 0.20, 0.25],
            "stock_units": [5500, 2000, 2500],
            "coverage": 0.85,
            "source": "history",
            "note": "前 8 周目的地占比",
        },
        {
            "key": "destination_capped",
            "label": labels["destination_capped"],
            "stock_mix": [0.50, 0.28, 0.22],
            "stock_units": [5000, 2800, 2200],
            "coverage": 0.85,
            "source": "history",
            "note": "前 8 周目的地占比按产能封顶",
        },
        {
            "key": "joint",
            "label": "联合方案的隐含布点",
            "stock_mix": [0.50, 0.25, 0.25],
            "stock_units": [5000, 2500, 2500],
            "coverage": 0.85,
            "source": "plan",
            "note": "按周内订单落位",
        },
    ]

    paired = []
    for left, right, delta in (
        ("declared", "destination", 0.03),
        ("declared", "destination_capped", 0.08),
        ("declared", "joint_placement", 0.10),
        ("declared", "joint_plan", 0.12),
        ("joint_placement", "joint_plan", 0.02),
    ):
        for cell in ("base", "two_pickers"):
            paired.append(
                {
                    "scenario": right,
                    "cell": cell,
                    "cell_label": "基准：均匀到达 · 确定性"
                    if cell == "base"
                    else "加 1 名拣货员/DC",
                    "left": left,
                    "right": right,
                    "comparison": f"{labels[right]} − {labels[left]}",
                    "metric": "e2e_otif_rate",
                    "n": 30,
                    "mean_delta": 0.0 if cell == "two_pickers" else delta,
                    "ci95": 0.01,
                    "win_rate": 0.0 if cell == "two_pickers" else 0.7,
                    "loss_rate": 0.0 if cell == "two_pickers" else 0.3,
                    "tie_rate": 1.0 if cell == "two_pickers" else 0.0,
                    "min_delta": 0.0,
                    "max_delta": 0.20,
                }
            )

    cells = [
        {
            "key": "base",
            "label": "基准：均匀到达 · 确定性",
            "policy": "edf",
            "profile": "均匀到达",
            "duration_noise": 0.0,
            "pickers_per_dc": 1,
        },
        {
            "key": "two_pickers",
            "label": "加 1 名拣货员/DC",
            "policy": "edf",
            "profile": "均匀到达",
            "duration_noise": 0.0,
            "pickers_per_dc": 2,
        },
    ]
    over_shift = [
        {
            "scenario": key,
            "cell": cell,
            "n": 30,
            "over_shift_rate": 1.0 if cell == "base" else 0.0,
            "mean_makespan": 700.0 if cell == "base" else 470.0,
            "p90_makespan": 730.0 if cell == "base" else 480.0,
        }
        for key in keys
        for cell in ("base", "two_pickers")
    ]
    dc_rows = [
        {
            "scenario": key,
            "dc": dc,
            "tickets": 192,
            "waves": 25,
            "labor_minutes": 400.0,
            "on_time_tickets": 150,
            "tardy_tickets": 42,
            "tardiness_minutes": 300.0,
            "makespan": 700.0,
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
            "pickers_per_dc": 1,
            "shift_minutes": 600.0,
            "max_orders": 8,
            "max_lines": 40,
            "dcs": ["London", "Rotterdam", "Frankfurt"],
        },
        "seeds": list(range(1, 31)),
        "settings": {
            "lookback_weeks": 8,
            "eu_split": [0.45, 0.55],
        },
        "destination_mix": {
            "history_skus": 180,
            "fallback_skus": 9,
            "weeks_used": 8,
            "start_week": "2011-10-03",
            "end_week": "2011-11-21",
            "capacity_cap": [0.55, 0.24, 0.21],
        },
        "placements": placements,
        "allocations": allocations,
        "cells": cells,
        "summary": summaries,
        "over_shift": over_shift,
        "paired": paired,
        "dc_workload": dc_rows,
        "declared_assumptions": ["测试假设"],
    }


def test_report_sections_and_interpretation():
    markdown = build_joint_report(_payload(), title="test joint")
    for heading in (
        "# test joint",
        "## Assumptions",
        "## Methods",
        "## Stock placements",
        "## Allocation outcomes",
        "## End-to-end OTIF distribution",
        "## Execution risk",
        "## Paired comparisons",
        "## Per-DC workload (seed 1, baseline cell)",
        "## Interpretation",
        "## Declared assumptions",
        "## Limitations",
    ):
        assert heading in markdown, heading
    assert "180" in markdown and "9" in markdown
    assert "DC throughput cap" in markdown
    assert "Capacity-blind history is a demand signal, not a placement." in markdown
    assert "A deployable history mix must be capped to DC throughput." in markdown
    assert "upper bound" in markdown
    print("[OK] 联合报告包含假设、方法、配对、执行风险、解释与局限")


def test_report_writer():
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_joint_report(_payload(), tmp, title="test joint")
        assert set(paths) == {"report", "summary"}
        text = paths["report"].read_text(encoding="utf-8")
        assert "# test joint" in text
        data = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert data["title"] == "test joint"
        assert len(data["summary"]) == len(_payload()["summary"])
        assert data["placements"][0]["key"] == "declared"
    print("[OK] 联合报告写入 Markdown 与可解析 JSON")


if __name__ == "__main__":
    test_destination_mix_history_and_fallback()
    test_placement_materialization_keeps_totals()
    test_with_stock_preserves_orders_and_meta()
    test_joint_places_stock_where_it_ships()
    test_joint_respects_pooled_stock_and_capacity()
    test_capacity_aware_allocation_two_stage()
    test_cap_shares_clips_to_throughput()
    test_paired_placements_statistics()
    test_report_sections_and_interpretation()
    test_report_writer()
    print("=" * 56)
    print("All joint allocation/placement tests passed")
    print("=" * 56)
