# -*- coding: utf-8 -*-
"""Week-6 tests: wave capacity, order batching, and restricted CP-SAT.

Run: python tests/test_wave.py
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
    build_wave_instance,
    candidate_pool,
    evaluate_waves,
    fcfs_waves,
    optimize_waves,
    savings_batches,
    single_order_waves,
    wave_detail,
    wave_summary,
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


def _instance(max_orders: int = 3, max_lines: int = 4):
    return build_wave_instance(
        _lines(),
        ASSIGNMENT,
        LAYOUT,
        max_orders=max_orders,
        max_lines=max_lines,
        meta={"week": "test"},
    )


def test_instance_aggregates_orders_and_slots():
    instance = _instance()
    assert instance.order_ids == ["A", "B", "C", "D", "E", "F"]
    order = instance.by_id()["A"]
    assert order.lines == 2
    assert order.units == 5
    assert set(order.slots) == {(1, 1, 0), (1, 2, 0)}
    assert instance.meta["orders"] == 6
    assert instance.meta["lines"] == 8
    assert instance.meta["skus"] == 8
    assert instance.fits(["A", "B"])  # 2 orders / 4 lines
    assert not instance.fits(["C", "D", "E", "F"])  # 4 orders > cap
    print("[OK] 波次实例聚合订单、槽位与容量判断")


def test_single_order_is_one_wave_per_invoice_and_labor_is_exact():
    instance = _instance()
    result = single_order_waves(instance)
    assert result.waves == 6
    assert result.status == "BASELINE"
    assert all(len(batch) == 1 for batch in result.batches)
    expected_travel = result.travel_m / instance.travel_meters_per_minute
    expected_pick = (
        instance.meta["lines"] * instance.pick_minutes_per_line
        + instance.meta["units"] * instance.pick_minutes_per_unit
    )
    expected_setup = 6 * instance.setup_minutes_per_wave
    assert math.isclose(result.travel_minutes, expected_travel)
    assert math.isclose(result.pick_minutes, expected_pick)
    assert math.isclose(result.setup_minutes, expected_setup)
    assert math.isclose(
        result.labor_minutes,
        expected_travel + expected_pick + expected_setup,
    )
    assert math.isclose(
        result.labor_cost,
        result.labor_minutes * instance.labor_cost_per_minute,
    )
    print("[OK] 按单拣选的波次数量与工时公式")


def test_fcfs_and_savings_respect_capacity_and_cover_orders():
    instance = _instance()
    for result in (fcfs_waves(instance, seed=7), savings_batches(instance)):
        assert result.waves >= 2
        assert sorted(invoice for batch in result.batches for invoice in batch) == (
            instance.order_ids
        )
        for batch in result.batches:
            count, lines, _ = instance.capacity_of(batch)
            assert count <= instance.max_orders
            assert lines <= instance.max_lines
        assert result.max_lines <= instance.max_lines
    print("[OK] FCFS / 节省算法波次满足容量且恰好覆盖所有订单")


def test_savings_reduces_travel_against_pick_by_order():
    instance = _instance()
    single = single_order_waves(instance)
    savings = savings_batches(instance)
    assert savings.travel_m <= single.travel_m + 1e-9
    assert savings.setup_minutes < single.setup_minutes
    assert savings.labor_minutes < single.labor_minutes
    print("[OK] 订单合并降低行走距离与波次 setup 工时")


def test_candidate_pool_is_feasible_and_covers_every_order():
    instance = _instance()
    pool = candidate_pool(instance, max_pairs=20, random_runs=2, seed=3)
    assert pool
    covered = {invoice for wave in pool for invoice in wave.invoices}
    assert covered == set(instance.order_ids)
    for wave in pool:
        assert instance.fits(wave.invoices)
        assert wave.lines <= instance.max_lines
    print("[OK] 候选波次池可行且覆盖全部订单")


def test_milp_covers_once_and_never_loses_to_savings():
    instance = _instance()
    savings = savings_batches(instance)
    milp = optimize_waves(
        instance,
        max_pairs=20,
        random_runs=2,
        seed=3,
        time_limit_seconds=3.0,
    )
    assert milp.status in {"OPTIMAL", "FEASIBLE"}
    assert sorted(invoice for batch in milp.batches for invoice in batch) == (
        instance.order_ids
    )
    assert milp.labor_minutes <= savings.labor_minutes + 1e-6
    assert milp.pool_size > 0
    assert milp.gap is not None and milp.gap >= 0.0
    print("[OK] CP-SAT 恰好覆盖一次且不劣于节省算法")


def test_invalid_batches_are_rejected():
    instance = _instance()
    cases = [
        [["A", "A"], ["B"], ["C"], ["D"], ["E"], ["F"]],
        [["A", "B"], ["C"], ["D"], ["E"]],
        [["A", "B"], ["C"], ["D"], ["E"], ["F"], ["X"]],
        [["A", "B", "C", "D"], ["E"], ["F"]],
    ]
    for batches in cases:
        try:
            evaluate_waves(instance, batches, name="invalid")
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法波次: {batches}")
    print("[OK] 重复、缺失、未知订单与超容量波次被拒绝")


def test_builder_rejects_unmapped_sku_and_oversized_order():
    lines = _lines().copy()
    lines.loc[0, "sku"] = "UNKNOWN"
    try:
        build_wave_instance(lines, ASSIGNMENT, LAYOUT)
    except ValueError:
        pass
    else:
        raise AssertionError("未分配槽位的 SKU 应报错")

    try:
        build_wave_instance(_lines(), ASSIGNMENT, LAYOUT, max_lines=1)
    except ValueError:
        pass
    else:
        raise AssertionError("单行上限低于订单行数应报错")
    print("[OK] 实例构建拒绝未映射 SKU 与不可行容量")


def test_summary_and_detail_are_consistent():
    instance = _instance()
    results = {
        "single_order": single_order_waves(instance),
        "savings": savings_batches(instance),
    }
    summary = wave_summary(results)
    rows = {row["key"]: row for row in summary}
    assert math.isclose(rows["single_order"]["travel_saving"], 0.0)
    assert rows["savings"]["travel_saving"] >= 0.0
    detail = wave_detail(instance, results["savings"], limit=3)
    assert 1 <= len(detail) <= 3
    assert all(row["orders"] >= 1 for row in detail)
    assert sum(row["orders"] for row in detail) <= instance.meta["orders"]
    print("[OK] 汇总节省率与波次明细一致")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 6 wave picking tests")
    print("=" * 56)
    tests = [
        test_instance_aggregates_orders_and_slots,
        test_single_order_is_one_wave_per_invoice_and_labor_is_exact,
        test_fcfs_and_savings_respect_capacity_and_cover_orders,
        test_savings_reduces_travel_against_pick_by_order,
        test_candidate_pool_is_feasible_and_covers_every_order,
        test_milp_covers_once_and_never_loses_to_savings,
        test_invalid_batches_are_rejected,
        test_builder_rejects_unmapped_sku_and_oversized_order,
        test_summary_and_detail_are_consistent,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All wave tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
