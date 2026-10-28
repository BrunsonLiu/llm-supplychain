# -*- coding: utf-8 -*-
"""Week-12 tests: mid-shift write-back of at-risk pick tickets.

Run: python tests/test_e2e_recovery.py
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
    RecoveryConfig,
    apply_recovery,
    build_recovery_report,
    pick_tickets,
    recovery_summary,
    replay_recovery,
    write_recovery_report,
)
from supply.e2e.instances import E2EInstance, PickPlan
from supply.e2e.pipeline import run_pick_layer
from supply.fulfillment import FulfillmentInstance, evaluate_allocation
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=8)
SLOTS = {"A": (1, 1, 0)}
PROMISES = [2] * 8 + [3] * 8 + [5] * 8
CUTOFFS = {"express": 5, "standard": 12, "economy": 18}
TIER_OF = {2: "express", 3: "standard", 5: "economy"}


def _instance(
    south_stock: int = 120, south_capacity: int = 120
) -> E2EInstance:
    n = len(PROMISES)
    promise = np.array(PROMISES)
    fulfillment = FulfillmentInstance(
        order_ids=[f"O{index:02d}" for index in range(n)],
        destinations=["United Kingdom"] * n,
        line_order=np.arange(n),
        line_sku=np.zeros(n, dtype=np.int64),
        line_qty=np.full(n, 5, dtype=np.int64),
        sku_names=["A"],
        dc_names=["North", "South"],
        stock=np.array([[120], [south_stock]], dtype=np.int64),
        dc_capacity=np.array([120, south_capacity], dtype=np.int64),
        ship_cost=np.ones((2, n), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.array([[2] * n, [3] * n], dtype=np.int64),
        promise_days=promise.astype(np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={},
    )
    pick = PickPlan(
        tier_of={
            f"O{index:02d}": TIER_OF[int(days)]
            for index, days in enumerate(promise)
        },
        cutoff_of={
            f"O{index:02d}": CUTOFFS[TIER_OF[int(days)]]
            for index, days in enumerate(promise)
        },
        arrival_of={f"O{index:02d}": 0.0 for index in range(n)},
        tier_onsite={"express": 1.0, "standard": 1.0, "economy": 1.0},
        tier_windows={"express": 0.0, "standard": 0.0, "economy": 0.0},
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=LAYOUT,
        slots=dict(SLOTS),
        pick=pick,
        pickers_per_dc=1,
        shift_minutes=600.0,
        meta={},
    )


def _allocation(instance: E2EInstance):
    n = instance.n_orders
    shipments = np.zeros((n, 2), dtype=np.int64)
    shipments[:, 0] = 5
    return evaluate_allocation(instance.fulfillment, shipments, name="all-north")


def _phase(instance: E2EInstance, pickers: int = 1):
    allocation = _allocation(instance)
    groups = pick_tickets(instance, allocation)
    result = run_pick_layer(
        instance,
        allocation,
        scenario="synthetic",
        policy="edf",
        pickers_per_dc=pickers,
    )
    return allocation, groups, result


def _config(**kwargs) -> RecoveryConfig:
    base = dict(
        review_minute=3.0,
        transfer_lead=2.0,
        transfer_fee=1.0,
        min_gain=1.0,
    )
    base.update(kwargs)
    return RecoveryConfig(**base)


def test_config_and_move_validation():
    for case in (
        dict(review_minute=0),
        dict(transfer_lead=-1),
        dict(transfer_fee=-1),
        dict(min_gain=-1),
        dict(max_moves=-1),
    ):
        try:
            _config(**case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法回写配置: {case}")

    instance = _instance()
    allocation, groups, phase = _phase(instance)
    for case in (
        dict(policy="missing"),
        dict(review_minute=600.0),
        dict(duration_noise=-0.1),
        dict(pickers=0),
    ):
        kwargs = dict(
            policy=case.pop("policy", "reroute"),
            config=_config(**{k: v for k, v in case.items() if k in {"review_minute"}}),
            duration_noise=case.get("duration_noise"),
            pickers=case.get("pickers", 1),
        )
        try:
            apply_recovery(instance, allocation, groups, phase, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法回写调用: {case}")

    move = apply_recovery(
        instance, allocation, groups, phase, "reroute", _config()
    ).moves[0]
    payload = move.as_dict()
    assert payload["ticket"] == move.ticket
    assert payload["from_dc"] == "North"
    print("[OK] 回写配置、未知策略与非法参数被拒绝，Move 可序列化")


def test_locked_waves_and_none_replay():
    instance = _instance()
    allocation, groups, phase = _phase(instance)
    locked = {
        invoice
        for job, start in zip(phase.dc[0].schedule.jobs, phase.dc[0].schedule.starts)
        if start <= 3.0 + 1e-9
        for invoice in job.invoices
    }
    assert locked, "审核时点前应有已开工波次"

    none = apply_recovery(
        instance, allocation, groups, phase, "none", _config()
    )
    assert none.moves == []
    assert set(none.ticket_end) == {
        invoice for group in groups for invoice in group.order_index
    }
    phase_ends = {
        invoice: float(end)
        for job, end in zip(phase.dc[0].schedule.jobs, phase.dc[0].schedule.ends)
        for invoice in job.invoices
    }
    for ticket, end in phase_ends.items():
        assert abs(none.ticket_end[ticket] - end) < 1e-6
    assert none.metrics["pick_makespan"] == phase.dc[0].makespan
    print("[OK] 已开工波次锁定，无回写策略精确复现第一阶段剩余排程")


def test_reroute_moves_late_tickets_and_improves_otif():
    instance = _instance()
    allocation, groups, phase = _phase(instance)
    locked = {
        invoice
        for job, start in zip(phase.dc[0].schedule.jobs, phase.dc[0].schedule.starts)
        if start <= 3.0 + 1e-9
        for invoice in job.invoices
    }

    reroute = apply_recovery(
        instance, allocation, groups, phase, "reroute", _config()
    )
    assert reroute.moves, "应至少调动一张迟到票据"
    assert reroute.otif_rate > 0.0
    assert reroute.metrics["pick_makespan"] <= phase.dc[0].makespan
    moved = {move.ticket for move in reroute.moves}
    assert not moved & locked, "已开工波次的票据不能被调动"
    assert all(move.source_end > move.cutoff for move in reroute.moves)
    assert all(move.estimated_end < move.source_end for move in reroute.moves)
    assert all(move.to_dc == "South" for move in reroute.moves)
    assert reroute.metrics["moved_tickets"] == len(reroute.moves)
    assert reroute.metrics["transfer_fee"] == len(reroute.moves) * 1.0

    balance = apply_recovery(
        instance, allocation, groups, phase, "balance", _config()
    )
    assert len(balance.moves) >= len(reroute.moves)
    assert balance.otif_rate >= reroute.otif_rate
    print("[OK] 迟到票据被跨 DC 调动，锁定波次不动且 OTIF 改善")


def test_moves_transfer_stock_and_respect_capacity():
    starved = _instance(south_stock=0)
    allocation, groups, phase = _phase(starved)
    reroute = apply_recovery(
        starved, allocation, groups, phase, "reroute", _config()
    )
    assert reroute.moves, "库存随票据内部调拨，目标 DC 无自有库存也能接单"
    assert all(move.to_dc == "South" for move in reroute.moves)

    tight = _instance(south_capacity=5)
    allocation, groups, phase = _phase(tight)
    reroute = apply_recovery(
        tight, allocation, groups, phase, "reroute", _config()
    )
    assert sum(move.units for move in reroute.moves) <= 5
    print("[OK] 调动随票据转移库存，并受目标 DC 周产能约束")


def test_oracle_and_capacity_control():
    instance = _instance()
    allocation, groups, phase = _phase(instance)
    oracle = apply_recovery(
        instance, allocation, groups, phase, "oracle", _config()
    )
    late = {
        invoice
        for job, end in zip(phase.dc[0].schedule.jobs, phase.dc[0].schedule.ends)
        for invoice in job.invoices
        if end > float(instance.pick.cutoff_of[invoice.split("@")[0]]) + 1e-9
    }
    assert {move.ticket for move in oracle.moves} <= late

    allocation, groups, phase_two = _phase(instance, pickers=2)
    control = apply_recovery(
        instance,
        allocation,
        groups,
        phase_two,
        "reroute",
        _config(),
        pickers=2,
    )
    assert control.moves == [], "加拣货员后没有可救的迟到票据"
    assert control.metrics["moved_tickets"] == 0
    print("[OK] 先知策略只动实际迟到票据，加拣货员后无需回写")


def test_replay_frames_and_summary_grouping():
    instance = _instance()
    allocation = _allocation(instance)
    from supply.e2e import StressCell

    cell = StressCell("base", "base", "edf", None, 0.0, 1)
    out = replay_recovery(
        instance,
        allocation,
        "synthetic",
        cell,
        [1, 2],
        policies=("none", "reroute"),
    )
    runs = out["runs"]
    assert set(runs["policy"]) == {"none", "reroute"}
    assert set(runs["seed"]) == {1, 2}
    assert len(runs) == 4
    assert runs["e2e_otif_rate"].between(0.0, 1.0).all()
    assert set(out["runs"].columns) >= {
        "rescued_orders",
        "lost_orders",
        "moved_tickets",
        "recovery_cost",
    }

    summary = recovery_summary(runs, metrics=("e2e_otif_rate", "moved_tickets"))
    assert len(summary) == 2 * 2
    assert set(summary["scenario"]) == {"synthetic"}
    for row in summary.itertuples():
        block = runs[
            (runs["scenario"] == row.scenario)
            & (runs["cell"] == row.cell)
            & (runs["policy"] == row.policy)
        ][row.metric]
        assert abs(row.mean - float(block.mean())) < 1e-12
    print("[OK] 回写重放按策略×种子产出，统计按布点×压力格×策略分组")


def _summary_rows(means: dict[tuple[str, str, str], float]) -> list[dict]:
    cells = {
        "base": "基准：均匀到达 · 确定性",
        "two_pickers": "加 1 名拣货员/DC",
    }
    policies = {
        "none": "无回写（分单冻结）",
        "reroute": "迟到票据跨 DC 调动",
        "balance": "全队列跨 DC 再平衡",
        "oracle": "先知迟到集合（上界参考）",
    }
    rows = []
    for (placement, cell, policy), mean in means.items():
        for metric in (
            "e2e_otif_rate",
            "pick_on_time_rate",
            "pick_tardiness",
            "pick_makespan",
            "moved_tickets",
            "recovery_cost",
        ):
            if metric == "e2e_otif_rate":
                value = mean
            elif metric == "pick_on_time_rate":
                value = min(1.0, mean + 0.5)
            elif metric == "pick_tardiness":
                value = 1000.0 * (1.0 - mean)
            elif metric == "pick_makespan":
                value = 500.0 + 100.0 * (1.0 - mean)
            elif metric == "moved_tickets":
                value = 0.0 if policy == "none" else 2.0 if policy == "reroute" else 5.0
            else:
                value = 0.0 if policy == "none" else 20.0
            rows.append(
                {
                    "scenario": placement,
                    "cell": cell,
                    "cell_label": cells[cell],
                    "policy": policy,
                    "policy_label": policies[policy],
                    "metric": metric,
                    "n": 30,
                    "mean": value,
                    "ci95": 0.004,
                    "p10": value * 0.95,
                    "p50": value,
                    "p90": value * 1.05,
                    "tail10": value * 0.95,
                    "direction": "down" if metric == "e2e_otif_rate" else "up",
                }
            )
    return rows


def _payload() -> dict:
    means = {
        ("baseline", "base", "none"): 0.300,
        ("baseline", "base", "reroute"): 0.315,
        ("baseline", "base", "balance"): 0.318,
        ("baseline", "base", "oracle"): 0.315,
        ("london", "base", "none"): 0.250,
        ("london", "base", "reroute"): 0.285,
        ("london", "base", "balance"): 0.300,
        ("london", "base", "oracle"): 0.290,
    }
    for placement in ("baseline", "london"):
        for policy in ("none", "reroute", "balance", "oracle"):
            means[(placement, "two_pickers", policy)] = (
                0.400 if placement == "baseline" else 0.360
            )

    placements = [
        {
            "key": "baseline",
            "label": "基线 34/28/38",
            "shares": [0.34, 0.28, 0.38],
            "stock_mix": [0.35, 0.27, 0.38],
            "stock_units": [3400, 2800, 3800],
            "coverage": 0.85,
        },
        {
            "key": "london",
            "label": "London 偏重 40/24/36",
            "shares": [0.40, 0.24, 0.36],
            "stock_mix": [0.41, 0.23, 0.36],
            "stock_units": [4000, 2400, 3600],
            "coverage": 0.85,
        },
    ]
    allocations = [
        {
            "key": "baseline",
            "label": "基线 34/28/38",
            "status": "FEASIBLE",
            "fill": 0.82,
            "alloc_otif_rate": 0.400,
            "alloc_cost": 62000.0,
        },
        {
            "key": "london",
            "label": "London 偏重 40/24/36",
            "status": "FEASIBLE",
            "fill": 0.80,
            "alloc_otif_rate": 0.360,
            "alloc_cost": 63000.0,
        },
    ]
    paired = []
    for placement, delta, win in (
        ("baseline", 0.015, 0.70),
        ("london", 0.035, 0.85),
    ):
        for cell in ("base", "two_pickers"):
            for policy in ("reroute", "balance", "oracle"):
                paired.append(
                    {
                        "scenario": placement,
                        "cell": cell,
                        "cell_label": "基准：均匀到达 · 确定性"
                        if cell == "base"
                        else "加 1 名拣货员/DC",
                        "policy": policy,
                        "policy_label": {
                            "reroute": "迟到票据跨 DC 调动",
                            "balance": "全队列跨 DC 再平衡",
                            "oracle": "先知迟到集合（上界参考）",
                        }[policy],
                        "n": 30,
                        "mean_delta": 0.0 if cell == "two_pickers" else delta,
                        "ci95": 0.005,
                        "win_rate": 0.0 if cell == "two_pickers" else win,
                        "loss_rate": 0.0,
                        "tie_rate": 1.0 if cell == "two_pickers" else 1.0 - win,
                        "min_delta": 0.0,
                        "max_delta": 0.05,
                    }
                )

    move_summary = []
    for placement, reroute_moves, balance_moves, rescues in (
        ("baseline", 2.0, 5.0, 12),
        ("london", 8.0, 20.0, 60),
    ):
        for policy, moves in (("reroute", reroute_moves), ("balance", balance_moves)):
            move_summary.append(
                {
                    "scenario": placement,
                    "cell": "base",
                    "cell_label": "基准：均匀到达 · 确定性",
                    "policy": policy,
                    "policy_label": {
                        "reroute": "迟到票据跨 DC 调动",
                        "balance": "全队列跨 DC 再平衡",
                    }[policy],
                    "runs": 30,
                    "seeds_with_moves": 25,
                    "mean_moves": moves,
                    "mean_units": moves * 5.0,
                    "mean_fee": moves * 10.0,
                    "mean_transport_delta": moves * 2.0,
                    "rescued_orders": rescues,
                    "lost_orders": 0,
                }
            )

    review = []
    for placement, values in (
        ("baseline", {60.0: 0.300, 120.0: 0.315, 180.0: 0.320}),
        ("london", {60.0: 0.270, 120.0: 0.285, 180.0: 0.300}),
    ):
        for minute, value in values.items():
            review.append(
                {
                    "scenario": placement,
                    "review_minute": minute,
                    "n": 30,
                    "mean_otif": value,
                    "ci95": 0.004,
                    "mean_moves": 5.0,
                    "rescued_orders": 30,
                    "lost_orders": 0,
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
    over_shift = []
    for placement in ("baseline", "london"):
        for policy in ("none", "reroute", "balance", "oracle"):
            over_shift.append(
                {
                    "scenario": placement,
                    "cell": "base",
                    "cell_label": "基准：均匀到达 · 确定性",
                    "policy": policy,
                    "policy_label": {
                        "none": "无回写（分单冻结）",
                        "reroute": "迟到票据跨 DC 调动",
                        "balance": "全队列跨 DC 再平衡",
                        "oracle": "先知迟到集合（上界参考）",
                    }[policy],
                    "n": 30,
                    "over_shift_rate": 1.0,
                    "mean_makespan": 700.0,
                    "p90_makespan": 730.0,
                }
            )
    dc_rows = [
        {
            "scenario": placement,
            "cell": "base",
            "policy": policy,
            "policy_label": "无回写（分单冻结）" if policy == "none" else "全队列跨 DC 再平衡",
            "seed": 1,
            "dc": name,
            "tickets": 230,
            "waves": 30,
            "on_time_tickets": 180,
            "tardy_tickets": 50,
            "tardiness_minutes": 400.0,
            "makespan": 700.0,
            "moved_in": 0 if policy == "none" else 4,
            "moved_out": 0 if policy == "none" else 4,
        }
        for placement in ("baseline", "london")
        for policy in ("none", "balance")
        for name in ("London", "Rotterdam", "Frankfurt")
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
            "review_minute": 120.0,
            "transfer_lead": 30.0,
            "transfer_fee": 10.0,
            "min_gain": 5.0,
        },
        "placements": placements,
        "allocations": allocations,
        "policies": [
            {"key": "none", "label": "无回写（分单冻结）"},
            {"key": "reroute", "label": "迟到票据跨 DC 调动"},
            {"key": "balance", "label": "全队列跨 DC 再平衡"},
            {"key": "oracle", "label": "先知迟到集合（上界参考）"},
        ],
        "cells": cells,
        "summary": _summary_rows(means),
        "paired": paired,
        "over_shift": over_shift,
        "move_summary": move_summary,
        "move_routes": [
            {
                "scenario": "london",
                "cell_label": "基准：均匀到达 · 确定性",
                "policy_label": "全队列跨 DC 再平衡",
                "from_dc": "London",
                "to_dc": "Rotterdam",
                "moves": 18,
            }
        ],
        "review_sweep_summary": review,
        "dc_workload": dc_rows,
        "declared_assumptions": ["测试假设"],
    }


def test_report_sections_and_interpretation():
    markdown = build_recovery_report(
        _payload(), title="test recovery"
    )
    for heading in (
        "# test recovery",
        "## Assumptions",
        "## Methods",
        "## Stock placements",
        "## Policy impact by stress cell",
        "## Execution risk",
        "## Move behaviour",
        "### Move directions",
        "## Review-timing sweep",
        "## Per-DC workload (seed 1, base cell)",
        "## Interpretation",
        "## Declared assumptions",
        "## Limitations",
    ):
        assert heading in markdown, heading
    assert "Mid-shift write-back recovers part of the pick-layer loss" in markdown
    assert "Recovery needs a spare DC" in markdown
    assert "Extra pick capacity does what write-back cannot" in markdown
    assert "Knowing the realised late set adds little" in markdown
    assert "Review timing is a real trade-off" in markdown
    assert "Write-back is small and targeted" in markdown
    assert "Preemptive balancing moves much more work" in markdown
    assert "London 偏重 40/24/36" in markdown
    print("[OK] 回写报告包含全部章节与布点交互解释")


def test_report_json_writer():
    payload = _payload()
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_recovery_report(payload, tmp, title="test recovery")
        assert paths["report"].exists()
        assert paths["summary"].exists()
        stored = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert stored["title"] == "test recovery"
        assert len(stored["summary"]) == len(payload["summary"])
        assert len(stored["move_summary"]) == len(payload["move_summary"])
    print("[OK] 回写报告写出 Markdown 与 JSON 摘要")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 12 mid-shift write-back tests")
    print("=" * 56)
    tests = [
        test_config_and_move_validation,
        test_locked_waves_and_none_replay,
        test_reroute_moves_late_tickets_and_improves_otif,
        test_moves_transfer_stock_and_respect_capacity,
        test_oracle_and_capacity_control,
        test_replay_frames_and_summary_grouping,
        test_report_sections_and_interpretation,
        test_report_json_writer,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All mid-shift write-back tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
