# -*- coding: utf-8 -*-
"""Week-8 tests: mid-shift arrivals and online wave release.

Run: python tests/test_dynamic_wave.py
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

from supply.network import WarehouseLayout
from supply.wave import (
    ArrivalPlan,
    assign_arrivals,
    assign_promises,
    build_dynamic_report,
    build_wave_instance,
    dynamic_detail,
    dynamic_metrics,
    dynamic_summary,
    oracle_schedule,
    simulate_online,
    write_dynamic_report,
)

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)
ASSIGNMENT = {f"S{bay}": (1, bay, 0) for bay in range(1, 9)}
ALL_STANDARD = {"express": 0.0, "standard": 1.0, "economy": 0.0}


def _instance(count: int = 8, max_orders: int = 8):
    rows = [(f"INV{index:02d}", f"S{index}", 2) for index in range(1, count + 1)]
    lines = pd.DataFrame(rows, columns=["invoice", "sku", "quantity"])
    return build_wave_instance(
        lines,
        ASSIGNMENT,
        LAYOUT,
        max_orders=max_orders,
        max_lines=count,
    )


def _plan(instance, mix=None):
    return assign_promises(instance, mix=mix)


def _manual_arrivals(instance, plan):
    arrivals = {
        order.invoice: float(2 * index)
        for index, order in enumerate(instance.orders)
    }
    return ArrivalPlan(
        arrival_of=arrivals,
        tier_onsite={"express": 0.0, "standard": 1.0, "economy": 0.0},
        tier_windows={"express": 30.0, "standard": 30.0, "economy": 30.0},
        onsite={"express": 0, "standard": 1, "economy": 0},
        seed=0,
    )


def test_assign_arrivals_covers_orders_and_stays_inside_windows():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=7)
    assert set(arrivals.arrival_of) == set(instance.order_ids)
    assert arrivals.orders == len(instance.orders)
    for invoice, minute in arrivals.arrival_of.items():
        tier = plan.tier_of[invoice]
        assert -1e-9 <= minute <= arrivals.tier_windows[tier] + 1e-9
        assert minute <= plan.cutoff_of[invoice]
    assert arrivals.onsite_orders + arrivals.mid_shift_orders == arrivals.orders
    print("[OK] 到达时间覆盖全部订单、落在窗口内且早于截单")


def test_assign_arrivals_is_seeded_and_rejects_bad_parameters():
    instance = _instance()
    plan = _plan(instance)
    first = assign_arrivals(instance, plan, seed=3)
    second = assign_arrivals(instance, plan, seed=3)
    assert first.arrival_of == second.arrival_of

    bad_cases = [
        dict(tier_onsite={"express": 0.5, "standard": 0.5}),
        dict(tier_onsite={"express": 1.5, "standard": 0.5, "economy": 0.0}),
        dict(tier_windows={"express": 30.0, "standard": -1.0, "economy": 30.0}),
    ]
    for case in bad_cases:
        try:
            assign_arrivals(instance, plan, **case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法到达参数: {case}")
    print("[OK] 到达抽样可复现且拒绝缺失层级 / 越界占比 / 负窗口")


def test_every_policy_covers_orders_once_and_never_picks_early():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=5)
    results = {
        policy: simulate_online(instance, plan, arrivals, policy=policy)
        for policy in ("single", "edf", "savings", "savings_wait")
    }
    for policy, schedule in results.items():
        seen = [invoice for job in schedule.jobs for invoice in job.invoices]
        assert sorted(seen) == sorted(instance.order_ids), policy
        assert len(seen) == len(set(seen)), policy
        for job, start in zip(schedule.jobs, schedule.starts):
            for invoice in job.invoices:
                assert start >= arrivals.arrival_of[invoice] - 1e-9, policy
        for picker in range(schedule.picker_count):
            intervals = sorted(
                (schedule.starts[index], schedule.ends[index])
                for index in range(len(schedule.jobs))
                if schedule.pickers[index] == picker
            )
            for previous, current in zip(intervals, intervals[1:]):
                assert current[0] >= previous[1] - 1e-6, policy
    print("[OK] 四种在线策略恰好覆盖全部订单且不早于到达 / 不重叠")


def test_single_order_policy_releases_one_invoice_per_wave():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=2)
    schedule = simulate_online(instance, plan, arrivals, policy="single")
    assert len(schedule.jobs) == len(instance.orders)
    assert all(job.orders == 1 for job in schedule.jobs)
    print("[OK] 按单释放策略每个波次只含一张发票")


def test_tiered_policies_never_mix_promise_tiers():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=11)
    for policy in ("edf", "savings", "savings_wait"):
        schedule = simulate_online(instance, plan, arrivals, policy=policy)
        for job in schedule.jobs:
            assert len(set(job.tier_of.values())) == 1, policy
    print("[OK] EDF 装满 / 节省重批 / 等待凑波均不跨承诺层合并")


def test_wait_policy_delays_dispatch_to_fill_a_wave():
    instance = _instance(count=4, max_orders=4)
    plan = _plan(instance, mix=ALL_STANDARD)
    arrivals = _manual_arrivals(instance, plan)

    waited = simulate_online(
        instance,
        plan,
        arrivals,
        policy="savings_wait",
        picker_count=1,
        wait_minutes=10.0,
        min_fill=4,
    )
    immediate = simulate_online(
        instance, plan, arrivals, policy="savings", picker_count=1
    )
    zero_wait = simulate_online(
        instance,
        plan,
        arrivals,
        policy="savings_wait",
        picker_count=1,
        wait_minutes=0.0,
        min_fill=4,
    )
    assert len(waited.jobs) == 1
    assert waited.starts[0] >= max(arrivals.arrival_of.values()) - 1e-9
    assert len(immediate.jobs) > len(waited.jobs)
    assert math.isclose(zero_wait.meta["wait_minutes"], 0.0)
    assert len(zero_wait.jobs) == len(immediate.jobs)
    assert math.isclose(zero_wait.jobs[0].minutes, immediate.jobs[0].minutes)
    print("[OK] 等待策略等到订单凑满才发波，零窗口时退化为立即发波")


def test_oracle_is_offline_tiered_and_complete():
    instance = _instance()
    plan = _plan(instance)
    schedule = oracle_schedule(instance, plan, picker_count=2)
    seen = [invoice for job in schedule.jobs for invoice in job.invoices]
    assert sorted(seen) == sorted(instance.order_ids)
    assert all(len(set(job.tier_of.values())) == 1 for job in schedule.jobs)
    assert all(start >= 0 for start in schedule.starts)
    print("[OK] 离线参考覆盖全部订单、不跨层且从开班时刻起排")


def test_dynamic_metrics_count_waits_and_idle_capacity():
    instance = _instance(count=4, max_orders=4)
    plan = _plan(instance, mix=ALL_STANDARD)
    arrivals = _manual_arrivals(instance, plan)
    schedule = simulate_online(
        instance,
        plan,
        arrivals,
        policy="savings_wait",
        picker_count=1,
        wait_minutes=10.0,
        min_fill=4,
    )
    metrics = dynamic_metrics(schedule, arrivals)
    waits = [
        schedule.starts[0] - arrivals.arrival_of[invoice]
        for invoice in schedule.jobs[0].invoices
    ]
    assert math.isclose(metrics["avg_wait"], float(np.mean(waits)))
    assert math.isclose(metrics["max_wait"], float(np.max(waits)))
    assert math.isclose(
        metrics["idle_minutes"],
        schedule.picker_count * metrics["makespan"] - metrics["labor_minutes"],
    )
    assert metrics["onsite_orders"] == 1
    assert metrics["mid_shift_orders"] == 3
    print("[OK] 动态指标正确计算等待、开班前订单与空闲产能")


def test_summary_and_detail_expose_online_and_offline_rows():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=9)
    schedules = {
        "single": simulate_online(instance, plan, arrivals, policy="single"),
        "edf_fill": simulate_online(instance, plan, arrivals, policy="edf"),
        "savings": simulate_online(instance, plan, arrivals, policy="savings"),
        "wait": simulate_online(instance, plan, arrivals, policy="savings_wait"),
        "oracle": oracle_schedule(instance, plan),
    }
    summary = dynamic_summary(schedules, arrivals)
    rows = {row["key"]: row for row in summary}
    assert rows["single"]["policy"] == "single"
    assert rows["oracle"]["policy"] == "offline"
    assert "avg_wait" in rows["wait"]
    assert "avg_wait" not in rows["oracle"]
    detail = dynamic_detail(schedules["wait"], limit=3)
    assert 1 <= len(detail) <= 3
    assert all(row["orders"] >= 1 for row in detail)
    print("[OK] 汇总区分在线/离线行，明细返回波次摘要")


def test_report_builder_and_writer_produce_expected_sections():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=13)
    common = dict(picker_count=2, shift_minutes=600.0)
    schedules = {
        "single": simulate_online(
            instance, plan, arrivals, policy="single", name="在线按单释放", **common
        ),
        "edf_fill": simulate_online(
            instance, plan, arrivals, policy="edf", name="在线 EDF 即时装满", **common
        ),
        "savings": simulate_online(
            instance, plan, arrivals, policy="savings", name="在线节省重批", **common
        ),
        "wait": simulate_online(
            instance,
            plan,
            arrivals,
            policy="savings_wait",
            wait_minutes=15.0,
            min_fill=4,
            name="在线节省 + 等待凑波（15 min / ≥4 单）",
            **common,
        ),
        "wait_aggressive": simulate_online(
            instance,
            plan,
            arrivals,
            policy="savings_wait",
            wait_minutes=30.0,
            min_fill=6,
            name="在线节省 + 激进等待（30 min / ≥6 单）",
            **common,
        ),
        "oracle": oracle_schedule(instance, plan, **common),
    }
    summary = dynamic_summary(schedules, arrivals)
    tuning = []
    for wait_minutes in (0.0, 15.0):
        for min_fill in (4, 6):
            schedule = simulate_online(
                instance,
                plan,
                arrivals,
                policy="savings_wait",
                wait_minutes=wait_minutes,
                min_fill=min_fill,
            )
            tuning.append(
                {
                    "wait_minutes": wait_minutes,
                    "min_fill": min_fill,
                    **dynamic_metrics(schedule, arrivals),
                }
            )
    results = {
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
        "arrivals": {
            "onsite_orders": arrivals.onsite_orders,
            "mid_shift_orders": arrivals.mid_shift_orders,
            "onsite_share": dict(arrivals.tier_onsite),
            "windows": dict(arrivals.tier_windows),
            "seed": arrivals.seed,
            "profile": [
                {
                    "tier": "全部",
                    "cutoff": "16:00",
                    "orders": arrivals.orders,
                    "onsite": arrivals.onsite_orders,
                    "onsite_rate": arrivals.onsite_orders / arrivals.orders,
                    "mid_shift": arrivals.mid_shift_orders,
                    "window": 30.0,
                    "mean_arrival": 15.0,
                    "median_arrival": 14.0,
                    "after_cutoff": 0,
                }
            ],
        },
        "settings": {
            "pickers": 2,
            "shift_minutes": 600.0,
            "wait_minutes": 15.0,
            "min_fill": 4,
        },
        "summary": summary,
        "tuning": tuning,
        "load_sweep": [{"orders": instance.meta["orders"], **row} for row in summary],
        "detail": dynamic_detail(schedules["wait"], limit=3),
    }
    markdown = build_dynamic_report(results, title="test report")
    for heading in (
        "# test report",
        "## Assumptions",
        "## Methods",
        "## Arrival profile",
        "## Scenario comparison",
        "## Wait-policy tuning",
        "## Load sensitivity",
        "## Interpretation",
        "## Limitations",
    ):
        assert heading in markdown, heading

    with tempfile.TemporaryDirectory() as tmp:
        paths = write_dynamic_report(results, tmp, title="test report")
        assert paths["report"].exists()
        assert paths["summary"].exists()
        payload = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert payload["title"] == "test report"
        assert len(payload["summary"]) == len(summary)
    print("[OK] 报告包含假设/方法/到达/对比/调参/负载/解释/局限并写出 JSON")


def test_invalid_policies_and_parameters_are_rejected():
    instance = _instance()
    plan = _plan(instance)
    arrivals = assign_arrivals(instance, plan, seed=1)
    cases = [
        dict(policy="unknown"),
        dict(policy="single", picker_count=0),
        dict(policy="savings_wait", min_fill=instance.max_orders + 1),
        dict(policy="savings_wait", wait_minutes=-1.0),
    ]
    for case in cases:
        try:
            simulate_online(instance, plan, arrivals, **case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法在线参数: {case}")
    print("[OK] 未知策略、零拣货员、超容量填单数与负等待被拒绝")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 8 online wave release tests")
    print("=" * 56)
    tests = [
        test_assign_arrivals_covers_orders_and_stays_inside_windows,
        test_assign_arrivals_is_seeded_and_rejects_bad_parameters,
        test_every_policy_covers_orders_once_and_never_picks_early,
        test_single_order_policy_releases_one_invoice_per_wave,
        test_tiered_policies_never_mix_promise_tiers,
        test_wait_policy_delays_dispatch_to_fill_a_wave,
        test_oracle_is_offline_tiered_and_complete,
        test_dynamic_metrics_count_waits_and_idle_capacity,
        test_summary_and_detail_expose_online_and_offline_rows,
        test_report_builder_and_writer_produce_expected_sections,
        test_invalid_policies_and_parameters_are_rejected,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All online wave release tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
