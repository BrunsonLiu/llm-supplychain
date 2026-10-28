# -*- coding: utf-8 -*-
"""Week-7 tests: promise cutoffs, tier-aware batching and wave scheduling.

Run: python tests/test_wave_schedule.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from supply.network import WarehouseLayout
from supply.wave import (
    WaveJob,
    assign_promises,
    build_wave_instance,
    build_schedule_report,
    jobs_from_result,
    promise_summary,
    savings_batches,
    schedule_cpsat,
    schedule_detail,
    schedule_edf,
    schedule_metrics,
    schedule_summary,
    single_order_waves,
)

LAYOUT = WarehouseLayout(n_aisles=2, n_bays=4)
ASSIGNMENT = {
    "S1": (1, 1, 0),
    "S2": (1, 2, 0),
    "S3": (2, 1, 0),
    "S4": (2, 2, 0),
    "S5": (1, 3, 0),
    "S6": (2, 3, 0),
    "S7": (1, 4, 0),
    "S8": (2, 4, 0),
}


def _lines() -> pd.DataFrame:
    rows = [
        ("A", "S1", 2),
        ("A", "S2", 3),
        ("B", "S3", 4),
        ("B", "S4", 5),
        ("C", "S5", 1),
        ("D", "S6", 2),
        ("E", "S7", 3),
        ("F", "S8", 4),
    ]
    return pd.DataFrame(rows, columns=["invoice", "sku", "quantity"])


def _instance():
    return build_wave_instance(
        _lines(),
        ASSIGNMENT,
        LAYOUT,
        max_orders=3,
        max_lines=4,
        meta={"week": "test"},
    )


def test_assign_promises_counts_and_cutoffs():
    instance = _instance()
    plan = assign_promises(instance, seed=3)
    assert sum(plan.tier_counts.values()) == len(instance.orders)
    assert plan.cutoffs == {"express": 240, "standard": 480, "economy": 600}
    for invoice in instance.order_ids:
        tier = plan.tier_of[invoice]
        assert plan.cutoff_of[invoice] == plan.cutoffs[tier]
    again = assign_promises(instance, seed=3)
    assert again.tier_of == plan.tier_of
    try:
        assign_promises(instance, mix={"express": 0.5, "standard": 0.5, "economy": 0.5})
    except ValueError:
        pass
    else:
        raise AssertionError("承诺占比之和不为 1 应报错")
    try:
        assign_promises(
            instance,
            cutoffs={"express": 600, "standard": 480, "economy": 240},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("截单时间倒序应报错")
    print("[OK] 承诺分层计数、截单映射与参数校验")


def test_tiered_savings_never_mixes_tiers():
    instance = _instance()
    plan = assign_promises(instance, seed=3)
    result = savings_batches(instance, groups=plan.tier_of)
    assert sorted(invoice for batch in result.batches for invoice in batch) == instance.order_ids
    for batch in result.batches:
        tiers = {plan.tier_of[invoice] for invoice in batch}
        assert len(tiers) == 1
        count, lines, _ = instance.capacity_of(batch)
        assert count <= instance.max_orders
        assert lines <= instance.max_lines
    try:
        savings_batches(instance, groups={"A": "express"})
    except ValueError:
        pass
    else:
        raise AssertionError("分组缺少订单应报错")
    print("[OK] 分层节省算法不在承诺层之间合并订单")


def test_jobs_cover_orders_and_labor_matches():
    instance = _instance()
    plan = assign_promises(instance, seed=3)
    result = single_order_waves(instance)
    jobs = jobs_from_result(instance, result, plan)
    assert sum(job.orders for job in jobs) == len(instance.orders)
    assert len({invoice for job in jobs for invoice in job.invoices}) == len(instance.orders)
    assert math.isclose(sum(job.minutes for job in jobs), result.labor_minutes)
    for job in jobs:
        assert math.isclose(job.deadline, min(job.cutoff_of.values()))
        assert set(job.tier_counts) == {"express", "standard", "economy"}
    print("[OK] 排程任务覆盖全部订单且工时与 Week 6 一致")


def test_edf_respects_pickers_and_coverage():
    instance = _instance()
    plan = assign_promises(instance, seed=3)
    jobs = jobs_from_result(instance, single_order_waves(instance), plan)
    schedule = schedule_edf(jobs, picker_count=2)
    assert len(schedule.starts) == len(jobs)
    for index, job in enumerate(jobs):
        assert math.isclose(schedule.ends[index] - schedule.starts[index], job.minutes)
    for picker in range(2):
        intervals = sorted(
            (schedule.starts[index], schedule.ends[index])
            for index in range(len(jobs))
            if schedule.pickers[index] == picker
        )
        for previous, current in zip(intervals, intervals[1:]):
            assert current[0] >= previous[1] - 1e-9
    try:
        schedule_edf(jobs, picker_count=0)
    except ValueError:
        pass
    else:
        raise AssertionError("拣货员数量为 0 应报错")
    print("[OK] EDF 覆盖全部波次且同一拣货员的波次不重叠")


def test_metrics_count_tardiness_per_order():
    job = WaveJob(
        index=0,
        invoices=("A", "B"),
        minutes=60.0,
        cutoff_of={"A": 240, "B": 480},
        tier_of={"A": "express", "B": "standard"},
        tier_counts={"express": 1, "standard": 1, "economy": 0},
        tier_cutoffs={"express": 240, "standard": 480, "economy": 600},
    )
    from supply.wave import Schedule

    schedule = Schedule(
        name="manual",
        status="HEURISTIC",
        jobs=[job],
        starts=[0.0],
        ends=[300.0],
        pickers=[0],
        picker_count=1,
        shift_minutes=600.0,
        labor_cost_per_minute=0.5,
    )
    metrics = schedule_metrics(schedule)
    assert metrics["orders"] == 2
    assert metrics["on_time_orders"] == 1
    assert metrics["tardy_orders"] == 1
    assert math.isclose(metrics["total_tardiness"], 60.0)
    assert math.isclose(metrics["max_tardiness"], 60.0)
    assert math.isclose(metrics["makespan"], 300.0)
    assert math.isclose(metrics["labor_cost"], 30.0)
    rows = promise_summary(schedule)
    assert sum(row["tardy"] for row in rows) == 1
    assert sum(row["total_tardiness"] for row in rows) == 60.0
    print("[OK] 准时指标按订单自身截单时间计算")


def test_cpsat_matches_or_beats_edf():
    instance = _instance()
    plan = assign_promises(instance, seed=3)
    jobs = jobs_from_result(instance, single_order_waves(instance), plan)
    edf = schedule_edf(jobs, picker_count=1)
    cpsat = schedule_cpsat(jobs, picker_count=1, time_limit_seconds=3.0, seed=3)
    edf_metrics = schedule_metrics(edf)
    mip_metrics = schedule_metrics(cpsat)
    assert cpsat.status in {"OPTIMAL", "FEASIBLE"}
    assert mip_metrics["total_tardiness"] <= edf_metrics["total_tardiness"] + 1e-3
    assert mip_metrics["makespan"] <= edf_metrics["makespan"] + 1e-2
    assert cpsat.objective is not None and cpsat.best_bound is not None
    assert cpsat.gap is not None and cpsat.gap >= 0.0
    print("[OK] CP-SAT 在 EDF 提示下不劣于 EDF")


def test_summary_detail_and_report():
    instance = _instance()
    plan = assign_promises(instance, seed=3)
    jobs = jobs_from_result(instance, savings_batches(instance), plan)
    edf = schedule_edf(jobs, picker_count=2)
    cpsat = schedule_cpsat(jobs, picker_count=2, time_limit_seconds=3.0, seed=3)
    summary = schedule_summary({"edf": edf, "cpsat": cpsat})
    rows = {row["key"]: row for row in summary}
    assert rows["edf"]["waves"] == len(jobs)
    assert 0.0 <= rows["edf"]["on_time_rate"] <= 1.0
    detail = schedule_detail(edf, limit=2)
    assert 1 <= len(detail) <= 2
    report = build_schedule_report(
        {
            "dataset": {
                "orders": instance.meta["orders"],
                "lines": instance.meta["lines"],
                "units": instance.meta["units"],
                "week": "test",
                "max_orders": instance.max_orders,
                "max_lines": instance.max_lines,
                "travel_m_per_minute": instance.travel_meters_per_minute,
                "pick_min_per_line": instance.pick_minutes_per_line,
                "pick_min_per_unit": instance.pick_minutes_per_unit,
                "setup_min_per_wave": instance.setup_minutes_per_wave,
            },
            "plan": {
                "mix": plan.mix,
                "cutoffs": plan.cutoffs,
                "tier_counts": plan.tier_counts,
                "seed": plan.seed,
            },
            "schedule": {
                "pickers": 2,
                "shift_minutes": 600.0,
                "start_hour": 8,
                "tardiness_weight": 100,
                "makespan_weight": 1,
            },
            "summary": summary,
            "promises": {"tiered_edf": promise_summary(edf)},
            "sensitivity": [],
            "detail": detail,
        },
        title="test report",
        generated="now",
    )
    for section in ("## Assumptions", "## Methods", "## Scenario comparison", "## Interpretation"):
        assert section in report
    assert "test report" in report
    print("[OK] 排程汇总、明细与报告结构一致")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 7 wave scheduling tests")
    print("=" * 56)
    tests = [
        test_assign_promises_counts_and_cutoffs,
        test_tiered_savings_never_mixes_tiers,
        test_jobs_cover_orders_and_labor_matches,
        test_edf_respects_pickers_and_coverage,
        test_metrics_count_tardiness_per_order,
        test_cpsat_matches_or_beats_edf,
        test_summary_detail_and_report,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All wave scheduling tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
