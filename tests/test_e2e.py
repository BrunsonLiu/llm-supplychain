# -*- coding: utf-8 -*-
"""Week-9 tests: allocation -> per-DC pick tickets -> online release.

Run: python tests/test_e2e.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.e2e import (
    TIER_CUTOFFS,
    E2EResult,
    PickPlan,
    E2EInstance,
    allocation_order_status,
    build_e2e_instance,
    build_e2e_report,
    e2e_dc_table,
    e2e_summary,
    pick_tickets,
    run_pick_layer,
    run_release_sweep,
    write_e2e_report,
)
from supply.fulfillment import (
    FulfillmentInstance,
    allocate_greedy,
    allocate_milp,
    evaluate_allocation,
)
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=4)
SLOTS = {"A": (1, 1, 0), "B": (1, 2, 0)}
ALL_ONSITE = {"express": 1.0, "standard": 1.0, "economy": 1.0}
NO_WINDOW = {"express": 0.0, "standard": 0.0, "economy": 0.0}


def _fulfillment(transit: Optional[np.ndarray] = None) -> FulfillmentInstance:
    """2 DCs, 2 SKUs, 3 orders with promise 2/3/5 days."""
    if transit is None:
        transit = np.array([[2, 2, 2], [2, 2, 2]], dtype=np.int64)
    return FulfillmentInstance(
        order_ids=["O0", "O1", "O2"],
        destinations=["United Kingdom", "Germany", "France"],
        line_order=np.array([0, 1, 1, 2]),
        line_sku=np.array([0, 0, 1, 1]),
        line_qty=np.array([10, 10, 10, 10]),
        sku_names=["A", "B"],
        dc_names=["North", "South"],
        stock=np.array([[20, 10], [10, 20]], dtype=np.int64),
        dc_capacity=np.array([50, 50], dtype=np.int64),
        ship_cost=np.ones((2, 3), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=transit,
        promise_days=np.array([2, 3, 5], dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={},
    )


def _instance(
    arrivals: Optional[Dict[str, float]] = None,
    cutoffs: Optional[Dict[str, int]] = None,
    pickers: int = 1,
    transit: Optional[np.ndarray] = None,
) -> E2EInstance:
    fulfillment = _fulfillment(transit)
    tier_of = {"O0": "express", "O1": "standard", "O2": "economy"}
    pick = PickPlan(
        tier_of=tier_of,
        cutoff_of=cutoffs
        or {invoice: TIER_CUTOFFS[tier] for invoice, tier in tier_of.items()},
        arrival_of=arrivals or {"O0": 0.0, "O1": 0.0, "O2": 0.0},
        tier_onsite=dict(ALL_ONSITE),
        tier_windows=dict(NO_WINDOW),
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=LAYOUT,
        slots=dict(SLOTS),
        pick=pick,
        pickers_per_dc=pickers,
    )


def _split_allocation(instance: E2EInstance):
    """O0 from North; O1 split across both DCs; O2 from South."""
    fulfillment = instance.fulfillment
    shipments = np.zeros((fulfillment.n_lines, fulfillment.n_dcs), dtype=np.int64)
    shipments[0, 0] = 10
    shipments[1, 0] = 10
    shipments[2, 1] = 10
    shipments[3, 1] = 10
    return evaluate_allocation(fulfillment, shipments, name="manual")


def test_pick_tickets_split_orders_per_dc():
    instance = _instance()
    allocation = _split_allocation(instance)
    groups = pick_tickets(instance, allocation)

    assert [group.dc for group in groups] == ["North", "South"]
    north, south = groups
    assert len(north.frame) == 2
    assert len(south.frame) == 2
    assert north.frame["invoice"].nunique() == 2
    assert set(north.frame["quantity"]) == {10}
    assert north.order_index["O1@North"] == 1
    assert south.order_index["O1@South"] == 1
    assert sum(len(group.order_index) for group in groups) == 4
    assert set(north.frame["sku"]) == {"A"}
    assert set(south.frame["sku"]) == {"B"}
    print("[OK] 拆单订单在每个 DC 生成独立票据且数量来自分单结果")


def test_pick_tickets_rejects_wrong_shape():
    instance = _instance()
    allocation = _split_allocation(instance)
    allocation.shipments = allocation.shipments[:, :1]
    try:
        pick_tickets(instance, allocation)
    except ValueError:
        pass
    else:
        raise AssertionError("分单矩阵形状不匹配应被拒绝")
    print("[OK] 票据层拒绝与实例不匹配的分单矩阵")


def test_allocation_status_matches_week5_otif():
    instance = _instance()
    allocation = _split_allocation(instance)
    status = allocation_order_status(instance, allocation)

    assert status["fully_filled"].all()
    assert status["alloc_ok"].all()
    assert np.isclose(status["alloc_ok"].mean(), allocation.otif_rate)

    late_instance = _instance(
        transit=np.array([[2, 2, 2], [3, 2, 2]], dtype=np.int64)
    )
    shipments = np.zeros((4, 2), dtype=np.int64)
    shipments[0, 1] = 10  # O0 needs 2 days, South takes 3
    shipments[1, 0] = 10
    shipments[2, 1] = 10
    shipments[3, 1] = 10
    late = evaluate_allocation(late_instance.fulfillment, shipments, name="late")
    late_status = allocation_order_status(late_instance, late)
    assert not late_status["alloc_ok"][0]
    assert late_status["alloc_ok"][1:].all()
    assert np.isclose(late_status["alloc_ok"].mean(), late.otif_rate)
    print("[OK] 订单级 OTIF 与 Week-5 分单评估一致")


def test_end_to_end_otif_requires_both_layers():
    instance = _instance(pickers=1)
    allocation = _split_allocation(instance)

    on_time = run_pick_layer(instance, allocation, "manual", policy="edf")
    assert on_time.metrics["tickets"] == 4
    assert on_time.metrics["pick_tardy_tickets"] == 0
    assert np.isclose(on_time.metrics["e2e_otif_rate"], on_time.metrics["alloc_otif_rate"])
    assert on_time.metrics["pick_loss_orders"] == 0

    late_instance = _instance(arrivals={"O0": 500.0, "O1": 0.0, "O2": 0.0}, pickers=1)
    late = run_pick_layer(
        late_instance, _split_allocation(late_instance), "manual", policy="edf"
    )
    assert late.metrics["alloc_on_time_orders"] == 3
    assert late.metrics["pick_tardy_tickets"] == 1
    assert late.metrics["pick_loss_orders"] == 1
    assert late.metrics["e2e_otif_orders"] == 2
    assert not late.order_otif[0]
    assert late.order_otif[1:].all()
    assert late.metrics["tickets"] == 4
    assert np.isclose(
        late.metrics["e2e_otif_rate"], 2 / 3
    )
    print("[OK] 端到端 OTIF = 分单达标 ∩ 每张票据在截单前完成")


def test_metrics_aggregate_dc_results_and_pickers():
    instance = _instance(pickers=2)
    allocation = _split_allocation(instance)
    result = run_pick_layer(instance, allocation, "manual", policy="edf")

    assert result.pickers_per_dc == 2
    assert result.metrics["dcs"] == 2
    assert sum(row.tickets for row in result.dc) == result.metrics["tickets"]
    assert sum(row.waves for row in result.dc) == result.metrics["waves"]
    assert np.isclose(
        result.metrics["pick_labor_minutes"],
        sum(row.labor_minutes for row in result.dc),
    )
    assert np.isclose(
        result.metrics["labor_cost"],
        result.metrics["pick_labor_minutes"] * 0.45,
    )
    assert np.isclose(
        result.metrics["total_cost"],
        result.metrics["alloc_cost"] + result.metrics["labor_cost"],
    )
    assert result.metrics["pick_makespan"] == max(row.makespan for row in result.dc)

    rows = e2e_summary({"manual": result})
    assert rows[0]["key"] == "manual"
    assert rows[0]["pickers_per_dc"] == 2
    dc_rows = e2e_dc_table(result)
    assert {row["dc"] for row in dc_rows} == {"North", "South"}
    print("[OK] 端到端指标跨 DC 聚合且成本与工时一致")


def test_more_pickers_do_not_reduce_service():
    instance = _instance(pickers=1)
    allocation = _split_allocation(instance)
    one = run_pick_layer(instance, allocation, "manual", policy="edf", pickers_per_dc=1)
    four = run_pick_layer(
        instance, allocation, "manual", policy="edf", pickers_per_dc=4
    )
    assert four.metrics["pick_on_time_rate"] >= one.metrics["pick_on_time_rate"] - 1e-9
    assert four.metrics["e2e_otif_rate"] >= one.metrics["e2e_otif_rate"] - 1e-9
    assert four.metrics["pickers_per_dc"] == 4
    print("[OK] 增加拣货员不会降低票据或端到端准时率")


def test_release_sweep_keeps_allocation_fixed():
    instance = _instance(pickers=2)
    allocation = _split_allocation(instance)
    results = run_release_sweep(
        instance,
        allocation,
        "manual",
        {
            "single": {"policy": "single"},
            "edf": {"policy": "edf"},
            "savings": {"policy": "savings"},
            "wait": {"policy": "savings_wait", "wait_minutes": 5.0, "min_fill": 2},
        },
    )
    assert set(results) == {"single", "edf", "savings", "wait"}
    assert results["single"].policy == "single"
    assert results["wait"].policy == "savings_wait"
    assert results["single"].metrics["waves"] == results["single"].metrics["tickets"]
    for result in results.values():
        assert np.isclose(result.metrics["alloc_otif_rate"], allocation.otif_rate)
        assert result.metrics["tickets"] == 4
    print("[OK] 释放策略扫描复用同一分单且按单释放逐票成波")


def test_greedy_and_milp_allocations_run_through_the_pick_layer():
    instance = _instance(pickers=4)
    greedy = allocate_greedy(instance.fulfillment, max_splits=2)
    milp = allocate_milp(instance.fulfillment, max_splits=2, time_limit_seconds=2.0)

    greedy_result = run_pick_layer(instance, greedy, "greedy", policy="edf")
    milp_result = run_pick_layer(instance, milp, "milp", policy="edf")
    for result in (greedy_result, milp_result):
        assert result.metrics["tickets"] >= result.metrics["orders"]
        assert 0.0 <= result.metrics["e2e_otif_rate"] <= 1.0
        assert result.metrics["e2e_otif_orders"] <= result.metrics["alloc_on_time_orders"]
    assert milp_result.metrics["alloc_cost"] <= greedy_result.metrics["alloc_cost"] + 1e-6
    print("[OK] 贪心与 MILP 分单均可直接进入拣选与在线释放层")


def _payload_row(
    key: str, result: E2EResult, name: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "key": key,
        "name": name or result.name,
        "pick_status": result.allocation.status,
        "solve_seconds": result.allocation.solve_seconds,
        "gap": result.allocation.gap,
        "best_bound": result.allocation.best_bound,
        **result.metrics,
    }
    row.update(overrides)
    return row


def test_report_builder_and_writer_produce_expected_sections():
    instance = _instance(pickers=1)
    allocation = _split_allocation(instance)
    base = run_pick_layer(instance, allocation, "manual", policy="edf")
    late_instance = _instance(arrivals={"O0": 500.0, "O1": 0.0, "O2": 0.0})
    late = run_pick_layer(
        late_instance, _split_allocation(late_instance), "manual", policy="edf"
    )

    scenarios = [
        _payload_row("greedy", base, "Greedy"),
        _payload_row(
            "milp_cost",
            base,
            "Cost MILP",
            e2e_otif_rate=0.2,
            total_cost=base.metrics["total_cost"] + 100.0,
        ),
        _payload_row("milp_service", late, "Service MILP"),
        _payload_row("milp_load", late, "Load MILP"),
    ]
    release = [
        _payload_row("single", base, "Single"),
        _payload_row("edf", base, "EDF"),
        _payload_row("savings", base, "Savings"),
        _payload_row("savings_wait", base, "Savings + wait"),
    ]
    pickers = [
        _payload_row("pickers_1", late, "1 picker"),
        _payload_row("pickers_2", base, "2 pickers"),
    ]
    results = {
        "dataset": {
            "orders": instance.n_orders,
            "lines": instance.fulfillment.n_lines,
            "units": int(instance.fulfillment.line_qty.sum()),
            "week": "test",
            "dcs": 2,
            "stock_coverage": 0.9,
            "max_orders_per_wave": instance.max_orders,
            "max_lines_per_wave": instance.max_lines,
            "tier_onsite": dict(ALL_ONSITE),
        },
        "settings": {"pickers": 1, "shift_minutes": 600.0, "policy": "edf"},
        "scenarios": scenarios,
        "dc_workload": [
            {"key": "milp_load", **row} for row in e2e_dc_table(late)
        ],
        "release": release,
        "picker_sensitivity": pickers,
        "assumptions": instance.meta.get("assumptions", ["test assumption"]),
    }
    markdown = build_e2e_report(results, title="test report")
    for heading in (
        "# test report",
        "## Assumptions",
        "## Methods",
        "## Scenario comparison",
        "## Per-DC workload",
        "## Release-policy sweep",
        "## Picker sensitivity",
        "## Interpretation",
        "## Limitations",
    ):
        assert heading in markdown, heading

    with tempfile.TemporaryDirectory() as tmp:
        paths = write_e2e_report(results, tmp, title="test report")
        assert paths["report"].exists()
        assert paths["summary"].exists()
        payload = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert payload["title"] == "test report"
        assert len(payload["scenarios"]) == 4
        assert len(payload["release"]) == 4
    print("[OK] 报告包含假设/方法/对比/逐 DC/释放/拣货员/解释/局限并写出 JSON")


def _clean_frame(orders: int = 12) -> pd.DataFrame:
    rows = []
    countries = ["United Kingdom", "Germany", "France", "Netherlands"]
    for index in range(orders):
        invoice = f"INV{index:02d}"
        for sku in ("A", "B"):
            rows.append(
                {
                    "invoice": invoice,
                    "sku": sku,
                    "quantity": 3 + index % 5,
                    "week": pd.Timestamp("2011-11-28"),
                    "country": countries[index % len(countries)],
                }
            )
    return pd.DataFrame(rows)


def test_instance_builder_links_promise_tier_and_cutoff():
    frame = _clean_frame()
    kwargs = dict(
        sample_orders=8,
        max_lines=4,
        stock_factor=0.9,
        seed=7,
        week=pd.Timestamp("2011-11-28"),
        pickers_per_dc=2,
        arrival_seed=11,
    )
    instance = build_e2e_instance(frame, skus=["A", "B"], **kwargs)

    assert instance.n_orders == 8
    assert instance.pickers_per_dc == 2
    assert instance.pick.orders == instance.n_orders
    for invoice in instance.order_ids:
        tier = instance.pick.tier_of[invoice]
        assert instance.pick.cutoff_of[invoice] == TIER_CUTOFFS[tier]
        assert instance.pick.arrival_of[invoice] <= instance.pick.cutoff_of[invoice]
    assert instance.pick.onsite_orders + instance.pick.mid_shift_orders == instance.n_orders
    assert set(instance.slots) >= set(instance.fulfillment.sku_names)
    assert instance.meta["promise_cutoffs"] == dict(TIER_CUTOFFS)
    assert any("截单" in item for item in instance.meta["assumptions"])

    again = build_e2e_instance(frame, skus=["A", "B"], **kwargs)
    assert instance.pick.arrival_of == again.pick.arrival_of
    assert np.array_equal(instance.fulfillment.stock, again.fulfillment.stock)
    print("[OK] 实例层用同一承诺字段驱动分单时效、截单与到达抽样")


def test_invalid_parameters_are_rejected():
    instance = _instance()
    allocation = _split_allocation(instance)
    cases = [
        dict(instance=instance, allocation=allocation, scenario="x", policy="unknown"),
        dict(
            instance=instance,
            allocation=allocation,
            scenario="x",
            policy="edf",
            pickers_per_dc=0,
        ),
    ]
    for case in cases:
        try:
            run_pick_layer(**case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法端到端参数: {case}")

    frame = _clean_frame()
    bad_cases = [
        dict(pickers_per_dc=0),
        dict(shift_minutes=0.0),
        dict(tier_onsite={"express": 1.5, "standard": 0.5, "economy": 0.5}),
        dict(tier_windows={"express": -1.0, "standard": 60.0, "economy": 60.0}),
    ]
    for case in bad_cases:
        try:
            build_e2e_instance(
                frame,
                skus=["A", "B"],
                sample_orders=4,
                max_lines=4,
                week=pd.Timestamp("2011-11-28"),
                **case,
            )
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法实例参数: {case}")
    print("[OK] 未知策略、零拣货员、零班次、越界到达参数被拒绝")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 9 end-to-end fulfillment tests")
    print("=" * 56)
    tests = [
        test_pick_tickets_split_orders_per_dc,
        test_pick_tickets_rejects_wrong_shape,
        test_allocation_status_matches_week5_otif,
        test_end_to_end_otif_requires_both_layers,
        test_metrics_aggregate_dc_results_and_pickers,
        test_more_pickers_do_not_reduce_service,
        test_release_sweep_keeps_allocation_fixed,
        test_greedy_and_milp_allocations_run_through_the_pick_layer,
        test_report_builder_and_writer_produce_expected_sections,
        test_instance_builder_links_promise_tier_and_cutoff,
        test_invalid_parameters_are_rejected,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All end-to-end fulfillment tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
