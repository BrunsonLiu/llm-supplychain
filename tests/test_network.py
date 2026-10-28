# -*- coding: utf-8 -*-
"""Week-3 tests: CFLP, CVRP/VRPTW, warehouse slotting and picking.

Run: python tests/test_network.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.network import (
    LocationInstance,
    RoutingInstance,
    WarehouseLayout,
    all_open_nearest,
    assign_slots,
    build_location_instance,
    evaluate_orders,
    exact_cvrp,
    naive_dispatch,
    route_optimal,
    route_return,
    route_s_shape,
    savings_heuristic,
    solve_cflp,
    solve_routing,
    summarize_picking,
)


def _location(capacity: tuple[float, float] = (100.0, 100.0)) -> LocationInstance:
    transport = np.full((2, 2), 0.1)
    return LocationInstance(
        demand_countries=["North", "South"],
        demand_units=np.array([60.0, 40.0]),
        demand_coords=np.zeros((2, 2)),
        candidate_names=["A", "B"],
        candidate_coords=np.zeros((2, 2)),
        capacities=np.array(capacity, dtype=float),
        fixed_costs=np.array([100.0, 900.0]),
        transport_cost=transport,
        distance_km=transport / 0.001,
        meta={},
    )


def test_cflp_opens_cheapest_hub_and_respects_capacity():
    result = solve_cflp(_location(), deterministic_time=1.0)
    assert result.status == "OPTIMAL"
    assert result.opened_names == ["A"]
    assert np.isclose(result.fixed_cost, 100.0)
    assert np.isclose(result.transport_cost, 10.0)
    assert np.isclose(result.total_cost, 110.0)
    assert np.isclose(result.flows.sum(), 100.0)

    tight = solve_cflp(_location(capacity=(50.0, 50.0)), deterministic_time=1.0)
    assert tight.status == "OPTIMAL"
    assert set(tight.opened_names) == {"A", "B"}
    assert np.isclose(tight.fixed_cost, 1000.0)
    used = tight.flows.sum(axis=0)
    assert used[0] <= 50.0 + 1e-9
    assert used[1] <= 50.0 + 1e-9
    assert np.allclose(tight.flows.sum(axis=1), [60.0, 40.0])

    baseline = all_open_nearest(_location(capacity=(50.0, 50.0)))
    assert baseline.status == "HEURISTIC"
    assert np.isclose(baseline.fixed_cost, 1000.0)
    assert baseline.total_cost >= tight.total_cost
    print("[OK] CFLP 选仓、容量约束与全开基线")


def _routing(n: int = 7, capacity: float = 50.0, vehicles: int = 3):
    angles = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    coords = np.vstack(
        [
            np.zeros(2),
            np.column_stack([20.0 * np.cos(angles), 20.0 * np.sin(angles)]),
        ]
    )
    return RoutingInstance(
        coords=coords,
        demand=np.full(n, 10.0),
        capacity=capacity,
        n_vehicles=vehicles,
        names=[f"S{i + 1}" for i in range(n)],
    )


def test_savings_vs_exact_and_capacity():
    instance = _routing()
    exact = exact_cvrp(instance)
    savings = savings_heuristic(instance)
    naive = naive_dispatch(instance)

    assert exact.feasible and savings.feasible and not naive.feasible
    assert exact.distance_km <= savings.distance_km + 1e-6
    assert exact.distance_km <= naive.distance_km + 1e-6
    assert exact.max_load <= instance.capacity + 1e-9
    visited = sorted(node for route in exact.routes for node in route)
    assert visited == list(range(1, instance.n_customers + 1))
    assert np.isclose(
        sum(instance.demand[np.array(route) - 1].sum() for route in exact.routes),
        instance.demand.sum(),
    )
    print("[OK] Clarke-Wright / 精确 DP 与容量一致性")


def test_vrptw_visits_every_store_within_capacity():
    instance = _routing(n=6, capacity=40.0, vehicles=3)
    instance.time_windows = [(0, 240)] * 3 + [(60, 300)] * 3
    instance.horizon_minutes = 300
    plan = solve_routing(instance, time_windows=True, time_limit_seconds=1.0)

    assert plan.feasible, plan
    assert plan.routes, "VRPTW 未返回路径"
    visited = sorted(node for route in plan.routes for node in route)
    assert visited == list(range(1, instance.n_customers + 1))
    assert all(
        instance.demand[np.array(route) - 1].sum() <= instance.capacity + 1e-9
        for route in plan.routes
    )
    assert plan.max_load <= instance.capacity + 1e-9
    print("[OK] VRPTW 时间窗可行、全客户覆盖与容量约束")


def test_slotting_assigns_unique_slots_and_puts_fast_skus_first():
    layout = WarehouseLayout(n_aisles=4, n_bays=5)
    skus = [f"SKU{i:02d}" for i in range(35)]
    velocity = {sku: float(len(skus) - index) for index, sku in enumerate(skus)}

    assignment = assign_slots(skus, layout, velocity, strategy="abc")
    assert len(set(assignment.values())) == len(skus)
    assert set(assignment.values()) <= set(layout.slot_catalog())
    fastest = max(velocity, key=velocity.get)
    assert layout.depot_distance(assignment[fastest]) == min(
        layout.depot_distance(slot) for slot in assignment.values()
    )

    random = assign_slots(skus, layout, velocity, strategy="random", seed=7)
    assert len(set(random.values())) == len(skus)
    assert set(random.values()) <= set(layout.slot_catalog())
    print("[OK] 槽位分配为双射且 ABC 优先放置高频 SKU")


def test_abc_slotting_shortens_picking_and_optimal_is_a_lower_bound():
    layout = WarehouseLayout(n_aisles=6, n_bays=10)
    skus = [f"SKU{i:02d}" for i in range(40)]
    velocity = {sku: (500.0 if index < 6 else 1.0) for index, sku in enumerate(skus)}

    rng = np.random.default_rng(11)
    hot = skus[:6]
    cold = skus[6:]
    rows = []
    for invoice in range(30):
        picks = rng.choice(hot, size=3, replace=False).tolist()
        picks += rng.choice(cold, size=3, replace=False).tolist()
        for sku in picks:
            rows.append({"invoice": f"INV{invoice:03d}", "sku": sku, "quantity": 1})
    orders = pd.DataFrame(rows)

    results = {}
    for strategy in ("random", "abc"):
        assignment = assign_slots(skus, layout, velocity, strategy=strategy, seed=5)
        results[strategy] = evaluate_orders(orders, assignment, layout)
        frame = results[strategy]
        assert (frame["optimal_m"] <= frame["return_m"] + 1e-6).all()
        assert (frame["return_m"] >= 0).all()
        assert (frame["s_shape_m"] >= 0).all()

    summary = {row["slotting"]: row for row in summarize_picking(results)}
    assert summary["abc"]["return_m"] < summary["random"]["return_m"]
    assert summary["abc"]["return_saving"] > 0.0
    assert summary["random"]["optimal_saving"] == 0.0
    print("[OK] ABC 槽位降低 return 拣选距离，optimal 不劣于 return")


def test_location_window_can_be_pinned_to_panel_week():
    frame = pd.DataFrame(
        {
            "sku": ["A", "A", "A"],
            "country": ["United Kingdom"] * 3,
            "quantity": [10.0, 20.0, 30.0],
            "week": pd.to_datetime(["2011-11-14", "2011-11-21", "2011-11-28"]),
        }
    )
    instance = build_location_instance(
        frame, weeks=2, end_week=pd.Timestamp("2011-11-21")
    )
    assert instance.meta["period_start"] == "2011-11-14"
    assert instance.meta["period_end"] == "2011-11-21"
    assert np.isclose(instance.demand_units.sum(), 30.0)
    print("[OK] 选址窗口可按面板最后完整周截断")


def test_empty_picking_routes_are_zero():
    layout = WarehouseLayout()
    assert route_return(layout, []) == 0.0
    assert route_s_shape(layout, []) == 0.0
    assert route_optimal(layout, []) == 0.0
    slot = layout.slot_catalog()[0]
    assert np.isclose(
        route_optimal(layout, [slot]), 2.0 * layout.depot_distance(slot)
    )
    print("[OK] 空订单与单点拣选距离")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 3 network & warehouse tests")
    print("=" * 56)
    tests = [
        test_cflp_opens_cheapest_hub_and_respects_capacity,
        test_savings_vs_exact_and_capacity,
        test_vrptw_visits_every_store_within_capacity,
        test_slotting_assigns_unique_slots_and_puts_fast_skus_first,
        test_abc_slotting_shortens_picking_and_optimal_is_a_lower_bound,
        test_location_window_can_be_pinned_to_panel_week,
        test_empty_picking_routes_are_zero,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All network tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
