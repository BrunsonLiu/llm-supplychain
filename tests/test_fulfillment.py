# -*- coding: utf-8 -*-
"""Week-5 tests: multi-DC order fulfillment (greedy vs CP-SAT).

Run: python tests/test_fulfillment.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.fulfillment import (
    FulfillmentInstance,
    allocate_greedy,
    allocate_milp,
    build_fulfillment_instance,
    evaluate_allocation,
    order_table,
    promise_table,
)


def _instance(stock: np.ndarray | None = None) -> FulfillmentInstance:
    """2 DCs, 2 SKUs, 3 orders: default stock covers 30 of 40 units."""
    if stock is None:
        stock = np.array([[15, 0], [0, 15]], dtype=np.int64)
    return FulfillmentInstance(
        order_ids=["O0", "O1", "O2"],
        destinations=["United Kingdom", "Germany", "France"],
        line_order=np.array([0, 1, 1, 2]),
        line_sku=np.array([0, 0, 1, 1]),
        line_qty=np.array([10, 10, 10, 10]),
        sku_names=["A", "B"],
        dc_names=["North", "South"],
        stock=np.asarray(stock, dtype=np.int64),
        dc_capacity=np.array([50, 50], dtype=np.int64),
        ship_cost=np.array(
            [[1.0, 1.0, 2.0], [3.0, 3.0, 1.0]], dtype=float
        ),
        fixed_ship_cost=5.0,
        transit_days=np.array([[1, 2, 1], [2, 1, 1]], dtype=np.int64),
        promise_days=np.array([1, 1, 2], dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={},
    )


def test_greedy_conserves_units_and_resources():
    instance = _instance()
    result = allocate_greedy(instance, max_splits=2)

    assert np.array_equal(
        result.shipments.sum(axis=1) + result.unmet, instance.line_qty
    )
    assert result.stock_used.sum() + result.unmet.sum() == instance.line_qty.sum()
    assert np.all(result.stock_used <= instance.stock)
    assert np.all(result.dc_units <= instance.dc_capacity)
    assert result.unmet_units == 10  # stock covers 30 of 40 units
    assert np.isclose(result.unit_fill_rate, 0.75)
    print("[OK] 贪心分单守恒、库存与产能约束")


def test_split_cap_is_respected():
    instance = _instance()
    result = allocate_milp(instance, max_splits=1, time_limit_seconds=5.0)
    flags = np.zeros((instance.n_orders, instance.n_dcs), dtype=bool)
    for line in range(instance.n_lines):
        flags[instance.line_order[line]] |= result.shipments[line] > 0
    assert np.all(flags.sum(axis=1) <= 1)
    assert result.split_rate == 0.0

    relaxed = allocate_greedy(instance, max_splits=2)
    assert relaxed.split_rate >= 0.0
    print("[OK] 每单拆单上限生效（MILP 单仓模式拆单率为 0）")


def test_milp_is_no_worse_than_greedy():
    instance = _instance()
    greedy = allocate_greedy(instance, max_splits=2)
    milp = allocate_milp(instance, max_splits=2, time_limit_seconds=5.0)
    assert milp.status in {"OPTIMAL", "FEASIBLE"}
    assert milp.total_cost <= greedy.total_cost + 1e-6
    assert milp.unit_fill_rate >= greedy.unit_fill_rate - 1e-9
    print("[OK] MILP 目标成本不劣于贪心基线")


def test_late_and_otif_are_computed_from_promises():
    instance = _instance(stock=np.array([[15, 10], [10, 15]], dtype=np.int64))
    shipments = np.zeros((instance.n_lines, instance.n_dcs), dtype=np.int64)
    # O0 has a 1-day promise; the South DC needs 2 days, so all 10 units are late.
    shipments[0, 1] = 10
    result = evaluate_allocation(instance, shipments, name="manual")

    assert result.late_units == 10
    assert result.on_time_units == 0
    assert result.otif_rate == 0.0
    assert result.unit_fill_rate == 0.25
    assert np.isclose(result.late_cost, 10 * (2 - 1) * instance.late_penalty_per_unit_day)

    orders = order_table(instance, result)
    first = orders.set_index("order").loc["O0"]
    assert first["late_units"] == 10
    assert first["otif"] == False  # noqa: E712
    print("[OK] 迟到件数与 OTIF 按承诺时效计算")


def test_infeasible_allocations_are_rejected():
    instance = _instance()
    too_much_stock = np.zeros((instance.n_lines, instance.n_dcs), dtype=np.int64)
    too_much_stock[0, 0] = 25  # line 0 only ordered 10
    try:
        evaluate_allocation(instance, too_much_stock, name="bad")
    except ValueError as error:
        assert "数量" in str(error)
    else:
        raise AssertionError("超出订单行数量应被拒绝")

    over_stock = np.zeros((instance.n_lines, instance.n_dcs), dtype=np.int64)
    over_stock[0, 0] = 10
    over_stock[1, 0] = 10
    over_stock[2, 0] = 10  # 30 units of SKU A but only 20 in stock
    try:
        evaluate_allocation(instance, over_stock, name="bad")
    except ValueError as error:
        assert "库存" in str(error)
    else:
        raise AssertionError("超出库存应被拒绝")
    print("[OK] 非法分配（超量/超库存）被拒绝")


def _clean_frame() -> pd.DataFrame:
    rows = []
    countries = ["United Kingdom", "Germany", "France", "Netherlands"]
    quantities = [4, 6, 5, 7]
    for index, (country, qty) in enumerate(zip(countries, quantities)):
        invoice = f"INV{index}"
        rows.append(
            {
                "invoice": invoice,
                "sku": "A",
                "quantity": qty,
                "week": pd.Timestamp("2011-11-28"),
                "country": country,
            }
        )
        rows.append(
            {
                "invoice": invoice,
                "sku": "B",
                "quantity": qty,
                "week": pd.Timestamp("2011-11-28"),
                "country": country,
            }
        )
    return pd.DataFrame(rows)


def test_instance_builder_uses_real_orders_and_declared_assumptions():
    frame = _clean_frame()
    instance = build_fulfillment_instance(
        frame,
        skus=["A", "B"],
        sample_orders=4,
        max_lines=4,
        stock_factor=0.85,
        seed=7,
        week=pd.Timestamp("2011-11-28"),
    )
    assert instance.n_orders == 4
    assert instance.n_lines == 8
    assert instance.n_skus == 2
    assert instance.n_dcs == 3
    assert instance.line_qty.sum() == 2 * sum([4, 6, 5, 7])
    assert set(instance.promise_days.tolist()) <= {2, 3, 5}
    expected_stock = int(
        np.rint(instance.demand_by_sku() * 0.85).sum()
    )
    assert instance.stock.sum() == expected_stock
    assert np.isclose(
        instance.meta["stock_coverage"],
        instance.stock.sum() / instance.line_qty.sum(),
    )
    assert instance.transit_days.min() >= 2
    assert np.all(instance.dc_capacity > 0)

    again = build_fulfillment_instance(
        frame,
        skus=["A", "B"],
        sample_orders=4,
        max_lines=4,
        stock_factor=0.85,
        seed=7,
        week=pd.Timestamp("2011-11-28"),
    )
    assert np.array_equal(instance.stock, again.stock)
    assert np.array_equal(instance.transit_days, again.transit_days)
    print("[OK] 实例层使用真实订单并保持确定性")


def test_promise_table_groups_orders():
    instance = _instance()
    result = allocate_greedy(instance, max_splits=2)
    table = promise_table(instance, result)
    assert int(table["orders"].sum()) == instance.n_orders
    assert set(table["promise"]) <= {"1 days", "2 days", "3 days", "5 days"}
    print("[OK] 承诺时效分组统计完整")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 5 fulfillment tests")
    print("=" * 56)
    tests = [
        test_greedy_conserves_units_and_resources,
        test_split_cap_is_respected,
        test_milp_is_no_worse_than_greedy,
        test_late_and_otif_are_computed_from_promises,
        test_infeasible_allocations_are_rejected,
        test_instance_builder_uses_real_orders_and_declared_assumptions,
        test_promise_table_groups_orders,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All fulfillment tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
