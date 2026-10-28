# -*- coding: utf-8 -*-
"""Week-10 tests: Monte Carlo robustness of the end-to-end chain.

Run: python tests/test_e2e_robustness.py
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

from supply.e2e import (
    DEFAULT_ARRIVAL_PROFILE,
    TIER_CUTOFFS,
    E2EInstance,
    PickPlan,
    StressCell,
    build_robustness_report,
    normalize_arrival_profile,
    over_shift_rate,
    paired_delta,
    rebuild_arrivals,
    replay_allocation,
    run_monte_carlo,
    summarize_runs,
    write_robustness_report,
)
from supply.fulfillment import FulfillmentInstance, evaluate_allocation
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)
SLOTS = {"A": (1, 1, 0), "B": (1, 2, 0)}
WINDOWS = {"express": 120.0, "standard": 360.0, "economy": 480.0}
ONSITE = {"express": 0.0, "standard": 0.0, "economy": 0.0}


def _fulfillment(count: int = 24) -> FulfillmentInstance:
    promises = np.array([2, 3, 5][: count % 3] * 0 + [2, 3, 5] * count)[:count]
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
        meta={},
    )


def _instance(count: int = 24) -> E2EInstance:
    fulfillment = _fulfillment(count)
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
    )


def _allocation(instance: E2EInstance):
    fulfillment = instance.fulfillment
    shipments = np.zeros((fulfillment.n_lines, fulfillment.n_dcs), dtype=np.int64)
    shipments[:, 0] = fulfillment.line_qty
    return evaluate_allocation(fulfillment, shipments, name="single-dc")


def test_arrival_profile_is_seeded_and_stays_inside_windows():
    instance = _instance(12)
    first = rebuild_arrivals(instance, 7, DEFAULT_ARRIVAL_PROFILE)
    second = rebuild_arrivals(instance, 7, DEFAULT_ARRIVAL_PROFILE)
    assert first.pick.arrival_of == second.pick.arrival_of
    assert first.meta["arrival_seed"] == 7
    assert first.pick.arrival_profile == DEFAULT_ARRIVAL_PROFILE

    for invoice, arrival in first.pick.arrival_of.items():
        tier = first.pick.tier_of[invoice]
        assert 0.0 <= arrival <= first.pick.tier_windows[tier] + 1e-9

    baseline = rebuild_arrivals(instance, 7)
    assert baseline.pick.arrival_profile is None
    assert baseline.pick.arrival_of != first.pick.arrival_of
    print("[OK] 到达尖峰可复现、落在层内窗口且与均匀到达不同")


def test_normalize_arrival_profile_rejects_bad_shapes():
    assert normalize_arrival_profile(None) is None
    normalized = normalize_arrival_profile(DEFAULT_ARRIVAL_PROFILE)
    assert set(normalized) == {"spike_share", "spike_center", "spike_width"}

    bad_cases = [
        {"spike_share": 0.6, "spike_center": 0.5},
        {**DEFAULT_ARRIVAL_PROFILE, "spike_share": 1.5},
        {**DEFAULT_ARRIVAL_PROFILE, "spike_center": -0.1},
        {**DEFAULT_ARRIVAL_PROFILE, "spike_width": 0.0},
        {**DEFAULT_ARRIVAL_PROFILE, "unknown": 1.0},
    ]
    for case in bad_cases:
        try:
            normalize_arrival_profile(case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法尖峰参数: {case}")
    print("[OK] 到达尖峰参数校验覆盖缺键 / 越界 / 未知键")


def test_duration_noise_is_deterministic_and_optional():
    instance = _instance(12)
    allocation = _allocation(instance)
    base = replay_allocation(
        instance, allocation, "manual", StressCell("base", "base"), seeds=[1, 2]
    )
    again = replay_allocation(
        instance, allocation, "manual", StressCell("base", "base"), seeds=[1, 2]
    )
    assert base["pick_makespan"].tolist() == again["pick_makespan"].tolist()
    assert base["duration_noise"].eq(0.0).all()

    noisy = replay_allocation(
        instance,
        allocation,
        "manual",
        StressCell("noise", "noise", duration_noise=0.30),
        seeds=[1, 2],
    )
    noisy_again = replay_allocation(
        instance,
        allocation,
        "manual",
        StressCell("noise", "noise", duration_noise=0.30),
        seeds=[1, 2],
    )
    assert noisy["pick_makespan"].tolist() == noisy_again["pick_makespan"].tolist()
    assert noisy["duration_noise"].eq(0.30).all()
    assert not np.allclose(
        noisy.sort_values("seed")["pick_makespan"].to_numpy(),
        base.sort_values("seed")["pick_makespan"].to_numpy(),
    )
    assert noisy["e2e_otif_rate"].between(0.0, 1.0).all()
    print("[OK] 拣选噪声默认关闭、按种子可复现且改变完工时间")


def test_stress_cell_rejects_invalid_parameters():
    bad_cases = [
        dict(key="x", label="x", policy="unknown"),
        dict(key="x", label="x", duration_noise=-0.1),
        dict(key="x", label="x", pickers_per_dc=0),
        dict(key="x", label="x", profile={"spike_share": 2.0, "spike_center": 0.5, "spike_width": 0.2}),
    ]
    for case in bad_cases:
        try:
            StressCell(**case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法压力格: {case}")
    print("[OK] 压力格拒绝未知策略 / 负噪声 / 零拣货员 / 非法尖峰")


def test_summarize_runs_statistics_are_correct():
    seeds = list(range(1, 11))
    values = np.linspace(0.10, 0.55, len(seeds))
    frame = pd.DataFrame(
        {
            "scenario": "s",
            "cell": "c",
            "cell_label": "cell",
            "policy": "edf",
            "profile": "uniform",
            "duration_noise": 0.0,
            "seed": seeds,
            "e2e_otif_rate": values,
            "pick_on_time_rate": values + 0.2,
            "pick_makespan": 500.0 + 10 * np.arange(len(seeds)),
            "pick_tardiness": np.arange(len(seeds), dtype=float),
            "labor_per_ticket": np.full(len(seeds), 4.0),
            "total_cost": np.full(len(seeds), 1000.0),
        }
    )
    summary = summarize_runs(frame).set_index("metric")
    row = summary.loc["e2e_otif_rate"]
    assert row["n"] == len(seeds)
    assert math.isclose(row["mean"], float(values.mean()))
    expected_sd = float(values.std(ddof=1))
    assert math.isclose(row["sd"], expected_sd)
    assert math.isclose(row["ci95"], 1.96 * expected_sd / math.sqrt(len(seeds)))
    assert math.isclose(row["p50"], float(np.percentile(values, 50)))
    assert row["tail_direction"] == "down"
    assert row["tail10"] <= row["p10"]

    span = summary.loc["pick_makespan"]
    assert span["tail_direction"] == "up"
    assert span["tail10"] >= span["p90"]
    print("[OK] 汇总统计的均值 / 标准差 / 95% CI / 分位数 / 尾部均值正确")


def test_paired_delta_and_over_shift_rate():
    frame = pd.DataFrame(
        {
            "scenario": "s",
            "cell": ["base"] * 4 + ["alt"] * 4,
            "seed": [1, 2, 3, 4] * 2,
            "e2e_otif_rate": [0.2, 0.2, 0.2, 0.2, 0.3, 0.3, 0.3, 0.3],
            "pick_makespan": [590, 610, 590, 610] * 2,
        }
    )
    delta = paired_delta(frame, "base", "alt").iloc[0]
    assert delta["n"] == 4
    assert math.isclose(delta["mean_delta"], 0.1)
    assert math.isclose(delta["win_rate"], 1.0)
    assert math.isclose(delta["loss_rate"], 0.0)
    assert delta["comparison"] == "alt − base"

    over = over_shift_rate(frame, 600.0).set_index("cell")
    assert math.isclose(over.loc["base", "over_shift_rate"], 0.5)
    print("[OK] 配对差值、胜率与超班次概率计算正确")


def test_replay_and_monte_carlo_are_seeded():
    instance = _instance(12)
    allocation = _allocation(instance)
    cells = [
        StressCell("base", "base"),
        StressCell("peak", "peak", profile=DEFAULT_ARRIVAL_PROFILE),
        StressCell("noise", "noise", duration_noise=0.25),
    ]
    first = run_monte_carlo(instance, {"greedy": allocation}, cells, seeds=[1, 2, 3])
    second = run_monte_carlo(instance, {"greedy": allocation}, cells, seeds=[1, 2, 3])
    assert len(first) == 9
    assert first["e2e_otif_rate"].equals(second["e2e_otif_rate"])
    assert first["pick_makespan"].equals(second["pick_makespan"])
    assert set(first["cell"]) == {"base", "peak", "noise"}
    assert first["e2e_otif_rate"].between(0.0, 1.0).all()
    assert (first["tickets"] > 0).all()
    print("[OK] 多压力格 × 多随机种子的重放覆盖全部订单且可复现")


def test_invalid_monte_carlo_inputs_are_rejected():
    instance = _instance(6)
    allocation = _allocation(instance)
    cases = [
        dict(allocations={}, cells=[StressCell("base", "base")], seeds=[1]),
        dict(allocations={"g": allocation}, cells=[], seeds=[1]),
        dict(allocations={"g": allocation}, cells=[StressCell("base", "base")], seeds=[]),
    ]
    for case in cases:
        try:
            run_monte_carlo(instance, **case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝空输入: {case}")

    frame = replay_allocation(
        instance, allocation, "g", StressCell("base", "base"), seeds=[1]
    )
    try:
        summarize_runs(frame, metrics=["not_a_metric"])
    except ValueError:
        pass
    else:
        raise AssertionError("缺失指标列应被拒绝")
    try:
        over_shift_rate(frame, 0.0)
    except ValueError:
        pass
    else:
        raise AssertionError("非正班次时长应被拒绝")
    print("[OK] 空分单 / 空压力格 / 空种子 / 缺指标 / 非正班次被拒绝")


def test_report_sections_and_json_writer():
    instance = _instance(12)
    allocation = _allocation(instance)
    cells = [
        StressCell("base", "基准：均匀到达 · 确定性", pickers_per_dc=1),
        StressCell("peak", "到达尖峰 · 确定性", profile=DEFAULT_ARRIVAL_PROFILE, pickers_per_dc=1),
        StressCell("noise", "拣选噪声", duration_noise=0.25, pickers_per_dc=1),
    ]
    seeds = [1, 2, 3]
    frame = run_monte_carlo(instance, {"greedy": allocation}, cells, seeds=seeds)
    summary = summarize_runs(frame).to_dict("records")
    over = over_shift_rate(frame, 600.0).to_dict("records")
    paired = {
        "savings_vs_edf": [],
        "peak_vs_base": paired_delta(frame, "base", "peak", "e2e_otif_rate").to_dict("records"),
        "noise_vs_base": paired_delta(frame, "base", "noise", "e2e_otif_rate").to_dict("records"),
        "capacity_vs_base": [],
    }
    payload = {
        "dataset": {
            "orders": instance.n_orders,
            "lines": instance.fulfillment.n_lines,
            "units": int(instance.fulfillment.line_qty.sum()),
            "week": "test",
            "pickers_per_dc": 1,
            "shift_minutes": 600.0,
            "max_orders": instance.max_orders,
            "max_lines": instance.max_lines,
        },
        "seeds": seeds,
        "cells": [
            {
                "key": cell.key,
                "label": cell.label,
                "policy": cell.policy,
                "profile": cell.profile_label,
                "duration_noise": cell.duration_noise,
                "pickers_per_dc": cell.pickers_per_dc,
            }
            for cell in cells
        ],
        "allocations": [
            {
                "key": "greedy",
                "label": "贪心分单",
                "status": allocation.status,
                "alloc_otif_rate": allocation.otif_rate,
                "alloc_cost": allocation.total_cost,
                "solve_seconds": allocation.solve_seconds,
            }
        ],
        "summary": summary,
        "over_shift": over,
        "paired": paired,
        "declared_assumptions": ["测试假设"],
    }
    markdown = build_robustness_report(payload, title="test robustness")
    for heading in (
        "# test robustness",
        "## Assumptions",
        "## Methods",
        "## Allocation scenarios",
        "## Stress design",
        "## End-to-end OTIF distribution",
        "## Execution risk",
        "## Arrival spike vs uniform",
        "## Pick-time noise vs deterministic",
        "## Interpretation",
        "## Declared assumptions",
        "## Limitations",
    ):
        assert heading in markdown, heading

    with tempfile.TemporaryDirectory() as tmp:
        paths = write_robustness_report(payload, tmp, title="test robustness")
        assert paths["report"].exists()
        assert paths["summary"].exists()
        stored = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert stored["title"] == "test robustness"
        assert len(stored["summary"]) == len(summary)
    print("[OK] 稳健性报告包含设计/分布/执行风险/配对/解释/局限并写出 JSON")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 10 E2E robustness tests")
    print("=" * 56)
    tests = [
        test_arrival_profile_is_seeded_and_stays_inside_windows,
        test_normalize_arrival_profile_rejects_bad_shapes,
        test_duration_noise_is_deterministic_and_optional,
        test_stress_cell_rejects_invalid_parameters,
        test_summarize_runs_statistics_are_correct,
        test_paired_delta_and_over_shift_rate,
        test_replay_and_monte_carlo_are_seeded,
        test_invalid_monte_carlo_inputs_are_rejected,
        test_report_sections_and_json_writer,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All robustness tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
