# -*- coding: utf-8 -*-
"""Week-15 tests: empirical intraday arrival curves, replay and report.

Run: python tests/test_e2e_arrivals.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.e2e import (
    ArrivalCurve,
    CurveCell,
    arrival_timing,
    build_empirical_report,
    cutoff_coverage,
    fit_empirical_arrivals,
    l1_distance,
    mean_curve,
    rebuild_arrivals,
    uniform_curve,
    weekly_hourly_counts,
    write_empirical_report,
)
from supply.e2e.empirical import curve_for, replay_curves
from supply.e2e.instances import E2EInstance, PickPlan
from supply.fulfillment import FulfillmentInstance
from supply.fulfillment.solvers import FulfillmentResult
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)
TIERS = {0: "express", 1: "standard", 2: "economy"}
WINDOWS = {"express": 120.0, "standard": 360.0, "economy": 480.0}


def _clean_frame(weeks: int = 7, lines_per_week: int = 120, thin_week: bool = False) -> pd.DataFrame:
    """Synthetic invoice lines with explicit hours; one peak per week."""
    start = pd.Timestamp("2020-01-06")  # Monday
    rows = []
    for index in range(weeks):
        week = start + timedelta(weeks=index)
        count = lines_per_week
        if thin_week and index == 1:
            count = 10
        peak = 9 + (index % 4)
        for line in range(count):
            hour = peak if line % 3 else peak + 1
            stamp = week + timedelta(days=line % 5, hours=hour, minutes=line % 60)
            rows.append(
                {
                    "sku": f"S{line % 4}",
                    "invoice": f"I{index}-{line // 3}",
                    "week": week,
                    "invoice_date": stamp,
                    "quantity": 1,
                    "price": 1.0,
                    "revenue": 1.0,
                    "description": "x",
                    "country": "United Kingdom",
                }
            )
        # Weekend rows that must be excluded from the shape estimate.
        for line in range(10):
            rows.append(
                {
                    "sku": "S0",
                    "invoice": f"W{index}-{line}",
                    "week": week,
                    "invoice_date": week + timedelta(days=5, hours=12),
                    "quantity": 1,
                    "price": 1.0,
                    "revenue": 1.0,
                    "description": "x",
                    "country": "United Kingdom",
                }
            )
    return pd.DataFrame(rows)


def _instance() -> E2EInstance:
    n = 12
    n_skus = 2
    skus = ["A", "B"]
    fulfillment = FulfillmentInstance(
        order_ids=[f"O{index:02d}" for index in range(n)],
        destinations=["United Kingdom"] * n,
        line_order=np.arange(n),
        line_sku=(np.arange(n) % n_skus).astype(np.int64),
        line_qty=np.full(n, 5, dtype=np.int64),
        sku_names=skus,
        dc_names=["North", "South"],
        stock=np.full((2, n_skus), 20, dtype=np.int64),
        dc_capacity=np.full(2, 10_000, dtype=np.int64),
        ship_cost=np.ones((2, n), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.ones((2, n), dtype=np.int64),
        promise_days=np.array([2, 3, 5] * 4, dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=100.0,
        meta={},
    )
    tier_of = {f"O{index:02d}": TIERS[index % 3] for index in range(n)}
    pick = PickPlan(
        tier_of=tier_of,
        cutoff_of={
            f"O{index:02d}": {"express": 240, "standard": 480, "economy": 600}[
                TIERS[index % 3]
            ]
            for index in range(n)
        },
        arrival_of={f"O{index:02d}": 0.0 for index in range(n)},
        tier_onsite={tier: 0.5 for tier in WINDOWS},
        tier_windows=dict(WINDOWS),
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=LAYOUT,
        slots={name: (1, index + 1, 0) for index, name in enumerate(skus)},
        pick=pick,
        pickers_per_dc=1,
        shift_minutes=600.0,
        meta={"assumptions": ["合成测试实例"]},
    )


def _allocation(instance: E2EInstance) -> FulfillmentResult:
    lines = instance.fulfillment.line_order.size
    dcs = len(instance.fulfillment.dc_names)
    shipments = np.zeros((lines, dcs), dtype=np.int64)
    shipments[:, 0] = instance.fulfillment.line_qty
    demand = int(instance.fulfillment.line_qty.sum())
    return FulfillmentResult(
        name="test",
        status="FEASIBLE",
        shipments=shipments,
        unmet=np.zeros(lines, dtype=np.int64),
        objective=0.0,
        transport_cost=0.0,
        fixed_cost=0.0,
        late_cost=0.0,
        unmet_cost=0.0,
        demand_units=demand,
        fulfilled_units=demand,
        unmet_units=0,
        late_units=0,
        on_time_units=demand,
        unit_fill_rate=1.0,
        order_fill_rate=1.0,
        otif_rate=1.0,
        on_time_unit_rate=1.0,
        split_rate=0.0,
        shipments_count=lines,
        avg_transit_days=1.0,
        dc_units=np.array([demand, 0], dtype=np.int64),
        dc_utilization=np.zeros(dcs, dtype=float),
        stock_used=np.zeros((dcs, len(instance.fulfillment.sku_names)), dtype=np.int64),
        solve_seconds=0.0,
    )


def test_weekly_counts_filter_weekdays_and_window() -> None:
    clean = _clean_frame(weeks=1)
    stats = weekly_hourly_counts(clean, pd.Timestamp("2020-01-06"))
    assert stats["lines_total"] == len(clean)
    assert stats["lines_weekday"] == 120
    assert stats["lines_used"] == 120
    assert abs(sum(stats["shares"]) - 1.0) < 1e-9
    assert abs(stats["weekend_share"] - 10 / 130) < 1e-9
    assert stats["peak_hour"] == 9
    # Out-of-window lines are dropped from the shape, not from the totals.
    late = clean.copy()
    late.loc[late.index[:5], "invoice_date"] = clean.loc[late.index[:5], "week"] + timedelta(hours=21)
    stats = weekly_hourly_counts(late, pd.Timestamp("2020-01-06"))
    assert stats["lines_used"] == 115
    assert stats["coverage"] < 1.0
    try:
        weekly_hourly_counts(clean, pd.Timestamp("2020-01-06"), end_hour=8)
    except ValueError as exc:
        assert "结束小时" in str(exc)
    else:
        raise AssertionError("非法窗口应报错")
    print("[OK] 周度小时计数只保留工作日与营业窗口")


def test_curve_validation_and_roundtrip() -> None:
    curve = ArrivalCurve((0.1, 0.2, 0.3, 0.4), start_hour=0, end_hour=4, label="t")
    data = curve.as_dict()
    again = ArrivalCurve.from_dict(data)
    assert again.shares == curve.shares
    assert again.label == "t"
    scaled = ArrivalCurve((1, 2, 3, 4), start_hour=0, end_hour=4)
    assert abs(sum(scaled.shares) - 1.0) < 1e-9
    for bad in (
        lambda: ArrivalCurve((1.0, 1.0), start_hour=0, end_hour=4),
        lambda: ArrivalCurve((-0.1, 1.1), start_hour=0, end_hour=2),
        lambda: ArrivalCurve((0.0, 0.0), start_hour=0, end_hour=2),
        lambda: ArrivalCurve((1.0,), start_hour=4, end_hour=4),
    ):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法到达曲线应报错")
    print("[OK] 到达曲线校验与字典往返")


def test_curve_cdf_and_sampling() -> None:
    late = ArrivalCurve((0.0, 0.0, 0.0, 1.0), start_hour=0, end_hour=4)
    assert late.cdf_at(0.0) == 0.0
    assert abs(late.cdf_at(1.0) - 1.0) < 1e-9
    assert late.cdf_at(0.5) == 0.0
    assert abs(late.cdf_at(0.875) - 0.5) < 1e-9
    rng = np.random.default_rng(0)
    samples = [late.sample(rng, 480.0) for _ in range(200)]
    assert min(samples) >= 360.0 and max(samples) <= 480.0
    assert abs(np.mean(samples) - 420.0) < 12.0
    early = ArrivalCurve((1.0, 0.0, 0.0, 0.0), start_hour=0, end_hour=4)
    rng = np.random.default_rng(0)
    assert all(early.sample(rng, 480.0) <= 120.0 for _ in range(50))
    assert early.sample(rng, 0.0) == 0.0
    print("[OK] CDF 单调、采样落在窗口内且跟随形状")


def test_mean_and_distance_helpers() -> None:
    a = ArrivalCurve((0.1, 0.2, 0.3, 0.4), start_hour=0, end_hour=4, week="a")
    b = ArrivalCurve((0.4, 0.3, 0.2, 0.1), start_hour=0, end_hour=4, week="b")
    mid = mean_curve([a, b])
    assert np.allclose(mid.shares, (0.25, 0.25, 0.25, 0.25))
    assert abs(l1_distance(a, b) - 0.4) < 1e-9
    assert l1_distance(a, a) == 0.0
    uniform = uniform_curve(0, 4)
    assert abs(l1_distance(uniform, uniform)) < 1e-12
    assert abs(l1_distance(a, uniform) - 0.2) < 1e-9
    try:
        mean_curve([])
    except ValueError as exc:
        assert "至少" in str(exc)
    else:
        raise AssertionError("空曲线列表应报错")
    print("[OK] 平均曲线与总变差距离")


def test_fit_uses_prior_weeks_only() -> None:
    clean = _clean_frame(weeks=7)
    arrivals = fit_empirical_arrivals(clean, pd.Timestamp("2020-02-17"), lookback_weeks=6)
    assert len(arrivals) == 6
    weeks = [curve.week for curve in arrivals.curves]
    assert "2020-02-17" not in weeks
    assert arrivals.target.week == "2020-02-17"
    assert arrivals.mean.week == "mean"
    assert arrivals.diagnostics["target_peak_hour"] is not None
    assert arrivals.diagnostics["pairwise_l1_mean"] >= 0.0
    again = fit_empirical_arrivals(clean, pd.Timestamp("2020-02-17"), lookback_weeks=6)
    assert [curve.shares for curve in again.curves] == [curve.shares for curve in arrivals.curves]
    print("[OK] 经验曲线只用前若干周，目标周仅作留出")


def test_fit_skips_thin_weeks() -> None:
    clean = _clean_frame(weeks=7, thin_week=True)
    arrivals = fit_empirical_arrivals(
        clean, pd.Timestamp("2020-02-17"), lookback_weeks=6, min_lines=50
    )
    assert len(arrivals) == 5
    assert len(arrivals.skipped) == 1
    assert any(not row["used"] for row in arrivals.rows)
    try:
        fit_empirical_arrivals(clean.iloc[:5], pd.Timestamp("2020-02-17"), min_lines=1)
    except ValueError as exc:
        assert "样本不足" in str(exc) or "没有足够样本" in str(exc)
    else:
        raise AssertionError("空历史应报错")
    print("[OK] 样本不足的周被跳过且目标周缺样本会报错")


def test_pick_plan_samples_empirical_curve() -> None:
    instance = _instance()
    curve = ArrivalCurve(
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.5),
        start_hour=8,
        end_hour=18,
        week="w1",
    )
    shifted = rebuild_arrivals(instance, 7, arrival_curve=curve)
    plan = shifted.pick
    assert plan.arrival_curve is not None
    mid = [value for value in plan.arrival_of.values() if value > 0]
    assert mid, "应有班中到达订单"
    for invoice, arrival in plan.arrival_of.items():
        window = WINDOWS[plan.tier_of[invoice]]
        assert 0.0 <= arrival <= window + 1e-9
    onsite = [value for value in plan.arrival_of.values() if value <= 0]
    assert len(onsite) > 0
    again = rebuild_arrivals(instance, 7, arrival_curve=curve)
    assert again.pick.arrival_of == plan.arrival_of
    later = rebuild_arrivals(instance, 7, arrival_curve=curve).pick
    assert later.arrival_of == plan.arrival_of
    early = ArrivalCurve((1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 8, 18)
    shifted_early = rebuild_arrivals(instance, 7, arrival_curve=early)
    wide = rebuild_arrivals(instance, 7)
    assert np.mean([v for v in shifted_early.pick.arrival_of.values() if v > 0]) < np.mean(
        [v for v in wide.pick.arrival_of.values() if v > 0]
    )
    print("[OK] 曲线进入到达层：窗口约束、可复现、形状生效")


def test_pick_plan_rejects_profile_and_curve() -> None:
    instance = _instance()
    curve = uniform_curve(8, 18)
    try:
        rebuild_arrivals(
            instance,
            1,
            arrival_profile={"spike_share": 0.6, "spike_center": 0.5, "spike_width": 0.25},
            arrival_curve=curve,
        )
    except ValueError as exc:
        assert "二选一" in str(exc)
    else:
        raise AssertionError("尖峰与曲线互斥")
    print("[OK] 尖峰与经验曲线互斥")


def test_rebuild_arrivals_preserves_structure() -> None:
    instance = _instance()
    curve = uniform_curve(8, 18)
    shifted = rebuild_arrivals(instance, 3, arrival_curve=curve)
    assert shifted.fulfillment.stock.tolist() == instance.fulfillment.stock.tolist()
    assert shifted.slots == instance.slots
    assert shifted.pick.cutoff_of == instance.pick.cutoff_of
    assert shifted.pick.tier_of == instance.pick.tier_of
    assert shifted.pick.seed == 3
    assert shifted.meta["arrival_curve"]["shares"] == list(curve.shares)
    print("[OK] 只替换到达抽样，库存/槽位/截单不变")


def test_curve_cell_validation() -> None:
    cell = CurveCell("c", "cell", arrival="empirical", policy="edf")
    assert cell.profile is None
    assert "经验曲线" in cell.profile_label or cell.arrival == "empirical"
    spike = CurveCell(
        "s",
        "spike",
        arrival="spike",
        profile={"spike_share": 0.6, "spike_center": 0.5, "spike_width": 0.25},
    )
    assert "尖峰" in spike.profile_label
    for bad in (
        lambda: CurveCell("x", "x", arrival="empirical", profile={"spike_share": 1.0, "spike_center": 0.5, "spike_width": 0.5}),
        lambda: CurveCell("x", "x", arrival="spike"),
        lambda: CurveCell("x", "x", arrival="weird"),
        lambda: CurveCell("x", "x", policy="nope"),
        lambda: CurveCell("x", "x", duration_noise=-1.0),
        lambda: CurveCell("x", "x", pickers_per_dc=0),
    ):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("非法执行单元应报错")
    print("[OK] 执行单元校验")


def test_curve_for_and_replay() -> None:
    clean = _clean_frame(weeks=7)
    arrivals = fit_empirical_arrivals(clean, pd.Timestamp("2020-02-17"), lookback_weeks=6)
    instance = _instance()
    allocation = _allocation(instance)
    cells = [
        CurveCell("uniform", "均匀", arrival="uniform", pickers_per_dc=1),
        CurveCell("spike", "尖峰", arrival="spike", profile={"spike_share": 0.6, "spike_center": 0.5, "spike_width": 0.25}, pickers_per_dc=1),
        CurveCell("mean", "均值", arrival="mean", pickers_per_dc=1),
        CurveCell("week", "逐周", arrival="empirical", pickers_per_dc=1),
    ]
    assert curve_for(cells[0], 1, arrivals) is None
    assert curve_for(cells[2], 1, arrivals) is arrivals.mean
    assert curve_for(cells[3], 1, arrivals) is arrivals.curve_for(1)
    assert curve_for(cells[3], 7, arrivals) is arrivals.curve_for(7)
    frame = replay_curves(instance, allocation, "test", cells[3], [1, 2], arrivals)
    assert len(frame) == 2
    assert set(frame["cell"]) == {"week"}
    assert set(frame["curve_week"]) == {arrivals.curve_for(1).week, arrivals.curve_for(2).week}
    assert (frame["e2e_otif_rate"] >= 0).all()
    timing = arrival_timing(instance, cells, [1, 2, 3], arrivals)
    by_cell = {row["cell"]: row for row in timing}
    assert by_cell["week"]["mean_fraction"] > 0.0
    assert by_cell["uniform"]["mean_fraction"] > 0.0
    print("[OK] 曲线选择、回放行与到达时机汇总")


def _report_payload() -> dict:
    cells = [
        {"key": "uniform_edf", "label": "均匀", "arrival": "uniform", "policy": "edf", "profile": None, "duration_noise": 0.0, "pickers_per_dc": 1},
        {"key": "spike_edf", "label": "尖峰", "arrival": "spike", "policy": "edf", "profile": {}, "duration_noise": 0.0, "pickers_per_dc": 1},
        {"key": "empirical_mean_edf", "label": "均值", "arrival": "mean", "policy": "edf", "profile": None, "duration_noise": 0.0, "pickers_per_dc": 1},
        {"key": "empirical_week_edf", "label": "逐周", "arrival": "empirical", "policy": "edf", "profile": None, "duration_noise": 0.0, "pickers_per_dc": 1},
        {"key": "empirical_week_savings", "label": "逐周节省", "arrival": "empirical", "policy": "savings", "profile": None, "duration_noise": 0.0, "pickers_per_dc": 1},
        {"key": "spike_savings", "label": "尖峰节省", "arrival": "spike", "policy": "savings", "profile": {}, "duration_noise": 0.0, "pickers_per_dc": 1},
        {"key": "empirical_week_noise", "label": "逐周噪声", "arrival": "empirical", "policy": "edf", "profile": None, "duration_noise": 0.25, "pickers_per_dc": 1},
        {"key": "empirical_week_two_pickers", "label": "逐周加人", "arrival": "empirical", "policy": "edf", "profile": None, "duration_noise": 0.0, "pickers_per_dc": 2},
    ]
    means = {
        "uniform_edf": 0.400,
        "spike_edf": 0.380,
        "empirical_mean_edf": 0.360,
        "empirical_week_edf": 0.350,
        "empirical_week_savings": 0.360,
        "spike_savings": 0.390,
        "empirical_week_noise": 0.330,
        "empirical_week_two_pickers": 0.520,
    }
    summary = []
    for key, mean in means.items():
        for metric in ("e2e_otif_rate", "pick_on_time_rate", "pick_tardiness", "pick_makespan", "labor_per_ticket"):
            value = mean
            if metric in {"pick_tardiness", "pick_makespan"}:
                value = 100.0
            elif metric == "labor_per_ticket":
                value = 5.0
            summary.append(
                {
                    "scenario": "milp_load",
                    "cell": key,
                    "cell_label": key,
                    "metric": metric,
                    "n": 30,
                    "mean": value,
                    "ci95": 0.01 if metric == "e2e_otif_rate" else 1.0,
                    "p10": value - 0.02,
                    "p50": value,
                    "p90": value + 0.02,
                    "tail10": value - 0.03,
                }
            )
    paired = [
        {"left": "uniform_edf", "right": "empirical_week_edf", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": -0.050, "ci95": 0.01, "win_rate": 0.05, "loss_rate": 0.90, "tie_rate": 0.05},
        {"left": "spike_edf", "right": "empirical_week_edf", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": -0.030, "ci95": 0.01, "win_rate": 0.10, "loss_rate": 0.85, "tie_rate": 0.05},
        {"left": "empirical_mean_edf", "right": "empirical_week_edf", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": -0.010, "ci95": 0.02, "win_rate": 0.40, "loss_rate": 0.45, "tie_rate": 0.15},
        {"left": "empirical_week_edf", "right": "empirical_week_savings", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": 0.010, "ci95": 0.015, "win_rate": 0.50, "loss_rate": 0.35, "tie_rate": 0.15},
        {"left": "spike_edf", "right": "spike_savings", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": 0.012, "ci95": 0.008, "win_rate": 0.70, "loss_rate": 0.20, "tie_rate": 0.10},
        {"left": "empirical_week_edf", "right": "empirical_week_noise", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": -0.020, "ci95": 0.01, "win_rate": 0.10, "loss_rate": 0.85, "tie_rate": 0.05},
        {"left": "empirical_week_edf", "right": "empirical_week_two_pickers", "comparison": "x", "metric": "e2e_otif_rate", "n": 30, "mean_delta": 0.170, "ci95": 0.01, "win_rate": 1.00, "loss_rate": 0.00, "tie_rate": 0.00},
    ]
    hours = list(range(8, 18))
    rows = []
    for index, week in enumerate(["2020-01-06", "2020-01-13", "2020-02-17"]):
        shares = [0.02, 0.05, 0.08, 0.10, 0.12, 0.11, 0.13, 0.20, 0.16, 0.03]
        rows.append(
            {
                "week": week,
                "role": "目标周留出诊断" if index == 2 else "经验曲线",
                "lines_total": 1000,
                "lines_weekday": 900,
                "lines_used": 880,
                "coverage": 0.97,
                "weekend_share": 0.10,
                "peak_hour": 15,
                **{str(hour): value for hour, value in zip(hours, shares)},
            }
        )
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060, "week": "2011-11-28", "max_orders": 8, "max_lines": 40},
        "seeds": list(range(1, 31)),
        "settings": {"pickers": 1, "shift_minutes": 600.0, "milp_time": 60.0, "noise_sigma": 0.25},
        "arrivals": {
            "start_hour": 8,
            "end_hour": 18,
            "lookback_weeks": 6,
            "rows": rows,
            "diagnostics": {
                "target_peak_hour": 15,
                "target_peak_share": 0.20,
                "target_share_after_half": 0.62,
                "uniform_l1_mean": 0.30,
                "holdout_l1": 0.22,
                "holdout_percentile": 0.60,
            },
        },
        "cutoff_coverage": {"240": 0.23, "480": 0.78, "600": 1.0},
        "cells": cells,
        "timing": [
            {"cell": key, "label": key, "orders": 100, "mean_fraction": 0.55, "median_fraction": 0.58, "share_after_half": 0.65, "share_after_three_quarters": 0.30, "mean_minute": 200.0}
            for key in means
        ],
        "allocation": {"key": "milp_load", "label": "Week-9 分单", "status": "FEASIBLE", "fill": 0.75, "tickets": 650, "alloc_otif_rate": 0.54, "alloc_cost": 84000.0, "solve_seconds": 60.0},
        "summary": summary,
        "paired": paired,
        "over_shift": [
            {"cell_label": key, "over_shift_rate": 1.0, "mean_makespan": 700.0, "p90_makespan": 740.0, "n": 30}
            for key in means
        ],
    }


def test_report_sections_and_conditional_claims() -> None:
    markdown = build_empirical_report(_report_payload())
    for section in (
        "## Assumptions",
        "## Observed intraday curve",
        "## Benchmark cells",
        "## Where mid-shift orders land",
        "## End-to-end OTIF distribution",
        "## Paired differences",
        "## Execution risk",
        "## Interpretation",
        "## Limitations",
    ):
        assert section in markdown, section
    assert "The observed day is back-loaded" in markdown
    assert "the observed curve delivers fewer end-to-end on-time orders" in markdown
    assert "the declared spike still understates" in markdown
    assert "observed clock stresses the promise design" in markdown
    assert "nan%" not in markdown

    payload = _report_payload()
    for row in payload["paired"]:
        if row["left"] == "spike_edf" and row["right"] == "empirical_week_edf":
            row["mean_delta"] = 0.001
            row["ci95"] = 0.01
    for row in payload["summary"]:
        if row["cell"] == "empirical_week_edf" and row["metric"] == "e2e_otif_rate":
            row["mean"] = 0.381
    markdown = build_empirical_report(payload)
    assert "the declared spike is a reasonable proxy" in markdown
    print("[OK] 报告分节完整，条件解读按数值切换")


def test_write_empirical_report_roundtrips() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_empirical_report(_report_payload(), tmp, title="Week 15 测试")
        report = Path(paths["report"])
        summary = Path(paths["summary"])
        assert report.exists() and summary.exists()
        assert report.read_text(encoding="utf-8").startswith("# Week 15 测试")
        data = json.loads(summary.read_text(encoding="utf-8"))
        assert data["title"] == "Week 15 测试"
        assert data["dataset"]["orders"] == 400
        assert len(data["cells"]) == 8
    print("[OK] 报告写入 Markdown 与可回读的 JSON 摘要")


def main() -> None:
    test_weekly_counts_filter_weekdays_and_window()
    test_curve_validation_and_roundtrip()
    test_curve_cdf_and_sampling()
    test_mean_and_distance_helpers()
    test_fit_uses_prior_weeks_only()
    test_fit_skips_thin_weeks()
    test_pick_plan_samples_empirical_curve()
    test_pick_plan_rejects_profile_and_curve()
    test_rebuild_arrivals_preserves_structure()
    test_curve_cell_validation()
    test_curve_for_and_replay()
    test_report_sections_and_conditional_claims()
    test_write_empirical_report_roundtrips()
    print("\nAll Week 15 tests passed.")


if __name__ == "__main__":
    main()
