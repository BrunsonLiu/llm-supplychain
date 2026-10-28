# -*- coding: utf-8 -*-
"""Week-11 tests: stock deployment under execution risk.

Run: python tests/test_e2e_deployment.py
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.e2e import (
    DEFAULT_STOCK_PLANS,
    TIER_CUTOFFS,
    E2EInstance,
    PickPlan,
    StockPlan,
    StressCell,
    build_stock_deployment_report,
    dc_stock_units,
    plan_row,
    plans_for,
    run_monte_carlo,
    stock_mix,
    write_stock_deployment_report,
)
from supply.fulfillment import FulfillmentInstance, evaluate_allocation
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)
SLOTS = {"A": (1, 1, 0)}
WINDOWS = {"express": 120.0, "standard": 360.0, "economy": 480.0}
ONSITE = {"express": 0.0, "standard": 0.0, "economy": 0.0}


def _fulfillment(count: int = 12) -> FulfillmentInstance:
    promises = np.array([2, 3, 5] * count)[:count]
    return FulfillmentInstance(
        order_ids=[f"O{index:02d}" for index in range(count)],
        destinations=["United Kingdom"] * count,
        line_order=np.arange(count),
        line_sku=np.zeros(count, dtype=np.int64),
        line_qty=np.full(count, 5, dtype=np.int64),
        sku_names=["A"],
        dc_names=["North", "South"],
        stock=np.array([[count * 5], [0]], dtype=np.int64),
        dc_capacity=np.array([count * 5, count * 5], dtype=np.int64),
        ship_cost=np.ones((2, count), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.full((2, count), 2, dtype=np.int64),
        promise_days=promises.astype(np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={"stock_coverage": 0.85},
    )


def _instance(count: int = 12, stock: np.ndarray | None = None) -> E2EInstance:
    fulfillment = _fulfillment(count)
    if stock is not None:
        fulfillment = replace(
            fulfillment,
            stock=np.asarray(stock, dtype=np.int64),
            meta={"stock_coverage": 0.85},
        )
    tier_of = {
        invoice: {2: "express", 3: "standard", 5: "economy"}[int(days)]
        for invoice, days in zip(fulfillment.order_ids, fulfillment.promise_days)
    }
    pick = PickPlan(
        tier_of=tier_of,
        cutoff_of={invoice: TIER_CUTOFFS[tier] for invoice, tier in tier_of.items()},
        arrival_of={invoice: 0.0 for invoice in tier_of},
        tier_onsite=dict(ONSITE),
        tier_windows=dict(WINDOWS),
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=LAYOUT,
        slots=dict(SLOTS),
        pick=pick,
        pickers_per_dc=1,
        meta={"stock_coverage": 0.85},
    )


def _allocation(instance: E2EInstance, dc: int = 0):
    fulfillment = instance.fulfillment
    shipments = np.zeros((fulfillment.n_lines, fulfillment.n_dcs), dtype=np.int64)
    shipments[:, dc] = fulfillment.line_qty
    return evaluate_allocation(fulfillment, shipments, name=f"dc-{dc}")


def test_stock_plan_validation_and_formatting():
    plan = StockPlan("x", "X", (0.5, 0.5), "note")
    assert plan.share_text == "50% / 50%"
    assert plan.as_dict()["shares"] == [0.5, 0.5]

    bad_cases = [
        dict(key="", label="X", shares=(0.5, 0.5)),
        dict(key="x", label="", shares=(0.5, 0.5)),
        dict(key="x", label="X", shares=(1.0,)),
        dict(key="x", label="X", shares=(0.5, 0.4)),
        dict(key="x", label="X", shares=(1.2, -0.2)),
        dict(key="x", label="X", shares=(0.5, 0.5 + 1e-3)),
    ]
    for case in bad_cases:
        try:
            StockPlan(**case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法布点: {case}")
    print("[OK] 布点方案校验占比和、正数与 key/label")


def test_default_plans_and_selection():
    assert len(DEFAULT_STOCK_PLANS) == 4
    for plan in DEFAULT_STOCK_PLANS:
        assert math.isclose(sum(plan.shares), 1.0)
    selected = plans_for(["balanced", "baseline"])
    assert [plan.key for plan in selected] == ["balanced", "baseline"]
    try:
        plans_for(["baseline", "missing"])
    except ValueError:
        pass
    else:
        raise AssertionError("未知布点应被拒绝")
    print("[OK] 默认布点覆盖四种方案且按请求顺序选择")


def test_stock_units_mix_and_plan_row():
    instance = _instance(12, stock=np.array([[60], [40]], dtype=np.int64))
    assert dc_stock_units(instance) == [60, 40]
    assert stock_mix(instance) == [0.6, 0.4]

    plan = StockPlan("custom", "custom", (0.6, 0.4))
    row = plan_row(plan, instance)
    assert row["dcs"] == ["North", "South"]
    assert row["stock_units"] == [60, 40]
    assert math.isclose(sum(row["stock_mix"]), 1.0)
    assert math.isclose(row["coverage"], 0.85)

    empty = _instance(4, stock=np.zeros((2, 1), dtype=np.int64))
    try:
        dc_stock_units(empty)
    except ValueError:
        pass
    else:
        raise AssertionError("空库存应被拒绝")

    three = StockPlan("three", "three", (0.34, 0.33, 0.33))
    try:
        plan_row(three, instance)
    except ValueError:
        pass
    else:
        raise AssertionError("布点与 DC 数不匹配应被拒绝")
    print("[OK] 库存件数、实际占比与报告行按实例计算")


def test_plan_replays_are_separated_and_seeded():
    left = _instance(12, stock=np.array([[60], [0]], dtype=np.int64))
    right = _instance(12, stock=np.array([[0], [60]], dtype=np.int64))
    cell = StressCell("base", "base", "edf", None, 0.0, 1)
    seeds = [1, 2, 3]
    first = run_monte_carlo(left, {"left": _allocation(left, 0)}, [cell], seeds)
    second = run_monte_carlo(right, {"right": _allocation(right, 1)}, [cell], seeds)
    first_again = run_monte_carlo(left, {"left": _allocation(left, 0)}, [cell], seeds)

    frame = pd.concat([first, second], ignore_index=True)
    assert set(frame["scenario"]) == {"left", "right"}
    assert first["e2e_otif_rate"].equals(first_again["e2e_otif_rate"])
    assert first["pick_makespan"].equals(first_again["pick_makespan"])
    assert frame["e2e_otif_rate"].between(0.0, 1.0).all()
    print("[OK] 每个布点独立重放，scenario 不混淆且结果可复现")


def _summary_rows(means: dict[tuple[str, str], float]) -> list[dict]:
    rows = []
    cells = {
        "base": "基准：均匀到达 · 确定性",
        "severe": "重度拥堵 σ=0.40",
    }
    for (plan, cell), mean in means.items():
        for metric in (
            "e2e_otif_rate",
            "pick_on_time_rate",
            "pick_tardiness",
            "pick_makespan",
        ):
            if metric == "e2e_otif_rate":
                value = mean
            elif metric == "pick_on_time_rate":
                value = min(1.0, mean + 0.3)
            elif metric == "pick_tardiness":
                value = 1000.0 * (1.0 - mean)
            else:
                value = 500.0 + 100.0 * (1.0 - mean)
            rows.append(
                {
                    "scenario": plan,
                    "cell": cell,
                    "cell_label": cells[cell],
                    "policy": "edf",
                    "profile": "均匀到达",
                    "duration_noise": 0.0 if cell == "base" else 0.40,
                    "metric": metric,
                    "n": 30,
                    "mean": value,
                    "ci95": 0.005 if metric == "e2e_otif_rate" else 1.0,
                    "p10": value * 0.95,
                    "p50": value,
                    "p90": value * 1.05,
                    "min": value * 0.9,
                    "max": value * 1.1,
                    "tail10": value * 0.95,
                }
            )
    return rows


def _payload(means: dict[tuple[str, str], float]) -> dict:
    plans = [
        plan_row(
            StockPlan("baseline", "基线 60/40", (0.6, 0.4)),
            _instance(12, stock=np.array([[72], [48]], dtype=np.int64)),
        ),
        plan_row(
            StockPlan("balanced", "均衡 50/50", (0.5, 0.5)),
            _instance(12, stock=np.array([[60], [60]], dtype=np.int64)),
        ),
    ]
    allocations = []
    for index, plan in enumerate(plans):
        allocations.append(
            {
                "key": plan["key"],
                "label": plan["label"],
                "status": "FEASIBLE",
                "fill": 0.83 - 0.01 * index,
                "alloc_otif_rate": 0.50 + 0.02 * index,
                "alloc_cost": 62000.0 + 1000.0 * index,
                "solve_seconds": 60.0,
            }
        )
    summary = _summary_rows(means)
    over_shift = [
        {
            "scenario": plan["key"],
            "cell": cell,
            "n": 30,
            "over_shift_rate": 1.0,
            "mean_makespan": 720.0,
            "p90_makespan": 760.0,
        }
        for plan in plans
        for cell in ("base", "severe")
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
            "dcs": ["North", "South"],
        },
        "seeds": list(range(1, 31)),
        "cells": [
            {"key": "base", "label": "基准", "policy": "edf", "profile": "均匀到达", "duration_noise": 0.0, "pickers_per_dc": 1},
            {"key": "severe", "label": "重度拥堵", "policy": "edf", "profile": "均匀到达", "duration_noise": 0.4, "pickers_per_dc": 1},
        ],
        "plans": plans,
        "allocations": allocations,
        "summary": summary,
        "over_shift": over_shift,
        "dc_workload": [
            {
                "plan": "baseline",
                "dc": "London",
                "tickets": 200,
                "waves": 30,
                "labor_minutes": 800.0,
                "on_time_tickets": 150,
                "tardy_tickets": 50,
                "tardiness_minutes": 400.0,
                "makespan": 720.0,
            }
        ],
        "declared_assumptions": ["测试假设"],
    }


def test_report_sections_and_balanced_interpretation():
    means = {
        ("baseline", "base"): 0.40,
        ("balanced", "base"): 0.45,
        ("baseline", "severe"): 0.37,
        ("balanced", "severe"): 0.41,
    }
    markdown = build_stock_deployment_report(_payload(means), title="test deployment")
    for heading in (
        "# test deployment",
        "## Assumptions",
        "## Methods",
        "## Stock plans",
        "## Allocation outcomes",
        "## End-to-end OTIF distribution",
        "## Execution risk",
        "## Per-DC workload (seed 1, baseline cell)",
        "## Interpretation",
        "## Declared assumptions",
        "## Limitations",
    ):
        assert heading in markdown, heading
    assert "Stock placement is a real service lever" in markdown
    assert "The ranking survives congestion" in markdown
    print("[OK] 布点报告包含全部章节，均衡布点占优时给出对照解释")


def test_report_flags_default_split_when_it_wins():
    means = {
        ("baseline", "base"): 0.45,
        ("balanced", "base"): 0.42,
        ("baseline", "severe"): 0.41,
        ("balanced", "severe"): 0.38,
    }
    markdown = build_stock_deployment_report(_payload(means), title="default wins")
    assert "The default split is not beaten" in markdown
    assert "The placement frontier is not monotone" in markdown
    print("[OK] 默认布点胜出时如实报告而不是硬套均衡叙事")


def test_report_json_writer():
    means = {
        ("baseline", "base"): 0.40,
        ("balanced", "base"): 0.45,
        ("baseline", "severe"): 0.37,
        ("balanced", "severe"): 0.41,
    }
    payload = _payload(means)
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_stock_deployment_report(payload, tmp, title="test deployment")
        assert paths["report"].exists()
        assert paths["summary"].exists()
        stored = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert stored["title"] == "test deployment"
        assert len(stored["summary"]) == len(payload["summary"])
        assert len(stored["plans"]) == 2
    print("[OK] 布点报告写出 Markdown 与 JSON 摘要")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 11 stock deployment tests")
    print("=" * 56)
    tests = [
        test_stock_plan_validation_and_formatting,
        test_default_plans_and_selection,
        test_stock_units_mix_and_plan_row,
        test_plan_replays_are_separated_and_seeded,
        test_report_sections_and_balanced_interpretation,
        test_report_flags_default_split_when_it_wins,
        test_report_json_writer,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All stock deployment tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
