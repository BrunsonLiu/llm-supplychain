"""Week 3 benchmark: facility location, vehicle routing, warehouse picking.

Uses real transaction lines from Online Retail II for unit demand by country,
order composition, and SKU popularity. Coordinates, hub costs, fleet, store
positions, and the warehouse layout are an explicit assumption layer.

Usage:
    PYTHONPATH=src;. python scripts/run_network_benchmark.py
    PYTHONPATH=src;. python scripts/run_network_benchmark.py --orders 100
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data.online_retail import (  # noqa: E402
    clean_transactions,
    load_online_retail_raw,
    load_panel,
)
from supply.network import (  # noqa: E402
    WarehouseLayout,
    all_open_nearest,
    assign_slots,
    build_location_instance,
    build_picking_orders,
    build_route_network,
    evaluate_orders,
    exact_cvrp,
    facility_table,
    fixed_cost_sensitivity,
    naive_dispatch,
    routing_table,
    savings_heuristic,
    solve_cflp,
    solve_routing,
    summarize_picking,
    write_network_report,
)
from supply.network.routing import RoutingInstance  # noqa: E402


def _location_results(
    clean: pd.DataFrame,
    skus: list[str],
    top_countries: int,
    deterministic_time: float,
    end_week: pd.Timestamp,
) -> Dict[str, Any]:
    build = lambda multiplier: build_location_instance(  # noqa: E731
        clean,
        skus=skus,
        weeks=52,
        top_countries=top_countries,
        fixed_cost_multiplier=multiplier,
        end_week=end_week,
    )
    instance = build(1.0)
    baseline = all_open_nearest(instance)
    optimized = solve_cflp(instance, deterministic_time=deterministic_time)
    sensitivity = fixed_cost_sensitivity(
        build,
        multipliers=(0.25, 0.5, 1.0, 2.0, 4.0),
        deterministic_time=deterministic_time,
    )
    total = float(instance.demand_units.sum())
    demand_rows = [
        {
            "country": name,
            "units": float(units),
            "share": float(units) / total if total else 0.0,
        }
        for name, units in zip(instance.demand_countries, instance.demand_units)
    ]
    return {
        "meta": instance.meta,
        "baseline": {
            "status": baseline.status,
            "opened": len(baseline.open_indices),
            "fixed_cost": baseline.fixed_cost,
            "transport_cost": baseline.transport_cost,
            "total_cost": baseline.total_cost,
            "avg_distance_km": baseline.avg_distance_km,
            "solve_seconds": baseline.solve_seconds,
        },
        "optimized": {
            "status": optimized.status,
            "opened": len(optimized.open_indices),
            "fixed_cost": optimized.fixed_cost,
            "transport_cost": optimized.transport_cost,
            "total_cost": optimized.total_cost,
            "avg_distance_km": optimized.avg_distance_km,
            "solve_seconds": optimized.solve_seconds,
        },
        "facilities": facility_table(optimized, instance),
        "demand": demand_rows,
        "sensitivity": sensitivity,
    }


def _route_results(weekly_units: float, time_limit: float) -> Dict[str, Any]:
    network = build_route_network(weekly_units)
    instance = RoutingInstance(
        coords=network["coords"],
        demand=network["demand"],
        capacity=network["capacity"],
        n_vehicles=network["n_vehicles"],
        speed_kmh=network["speed_kmh"],
        service_minutes=network["service_minutes"],
        horizon_minutes=network["horizon_minutes"],
        time_windows=network["time_windows"],
        names=[f"S{index + 1}" for index in range(len(network["demand"]))],
    )
    plans = [
        naive_dispatch(instance),
        savings_heuristic(instance),
        exact_cvrp(instance),
        solve_routing(instance, time_windows=False, time_limit_seconds=time_limit),
    ]
    windows_plan = solve_routing(
        instance, time_windows=True, time_limit_seconds=time_limit
    )
    plans.append(windows_plan)

    routes = []
    for vehicle, route in enumerate(windows_plan.routes, start=1):
        load = float(instance.demand[np.array(route) - 1].sum())
        path = [0] + route + [0]
        distance = float(
            sum(instance.distance_km[a, b] for a, b in zip(path, path[1:]))
        )
        clock = 0.0
        previous = 0
        visits = []
        for node in route:
            clock += (
                instance.distance_km[previous, node] / instance.speed_kmh * 60.0
            )
            window_start, _ = instance.time_windows[node - 1]
            clock = max(clock, float(window_start))
            visits.append(
                f"S{node} {int(clock)}-{int(clock + instance.service_minutes)}min"
            )
            clock += instance.service_minutes
            previous = node
        routes.append(
            {
                "vehicle": f"V{vehicle}",
                "stores": " → ".join(instance.names[node - 1] for node in route),
                "load": load,
                "distance_km": distance,
                "arrivals": "; ".join(visits),
            }
        )
    return {
        "meta": {
            "customers": instance.n_customers,
            "vehicles": instance.n_vehicles,
            "capacity": instance.capacity,
            "speed_kmh": instance.speed_kmh,
            "service_minutes": instance.service_minutes,
            "horizon_minutes": instance.horizon_minutes,
            "weekly_units": weekly_units,
            "time_windows": instance.time_windows,
        },
        "plans": routing_table(plans),
        "routes": routes,
    }


def _warehouse_results(
    clean: pd.DataFrame,
    skus: list[str],
    sample_orders: int,
    seed: int,
    week: pd.Timestamp,
) -> Dict[str, Any]:
    orders, velocity, meta = build_picking_orders(
        clean, skus, sample_orders=sample_orders, max_lines=20, seed=seed, week=week
    )
    layout = WarehouseLayout(n_aisles=8, n_bays=16)
    results = {}
    assignments = {}
    for strategy in ("random", "abc"):
        assignment = assign_slots(
            skus, layout, velocity, strategy=strategy, seed=seed
        )
        assignments[strategy] = assignment
        results[strategy] = evaluate_orders(orders, assignment, layout)

    summary = summarize_picking(results)
    abc_assignment = assignments["abc"]
    top = velocity.sort_values(ascending=False).head(5)
    sample = [
        {
            "sku": sku,
            "abc": "A",
            "slot": f"({slot[0]}, {slot[1]})",
            "depot_m": layout.depot_distance(slot),
        }
        for sku, slot in ((sku, abc_assignment[sku]) for sku in top.index)
    ]
    return {
        "meta": {
            **meta,
            "aisles": layout.n_aisles,
            "bays": layout.n_bays,
            "slots": layout.slots,
            "bay_meters": 1.2,
            "aisle_gap_meters": 2.5,
            "skus_assigned": len(skus),
        },
        "summary": summary,
        "sample": sample,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Week 3 network benchmark")
    parser.add_argument(
        "--xlsx", default=str(ROOT / "data/raw/online_retail_II.xlsx")
    )
    parser.add_argument(
        "--raw-cache", default=str(ROOT / "data/raw/online_retail_II.raw.parquet")
    )
    parser.add_argument(
        "--panel", default=str(ROOT / "data/processed/online_retail_ii_weekly.parquet")
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--top-countries", type=int, default=14)
    parser.add_argument("--orders", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--location-time", type=float, default=5.0)
    parser.add_argument("--routing-time", type=float, default=2.0)
    parser.add_argument("--title", default="Network & warehouse benchmark (Week 3)")
    args = parser.parse_args()

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()
    recent = panel[pd.to_datetime(panel["week"]) > last_week - pd.Timedelta(weeks=52)]
    weekly_units = float(
        recent.groupby("week")["demand"].sum().mean()
    )

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)

    print("=" * 72)
    print(args.title)
    print("=" * 72)
    print(
        f"transactions {clean_stats['clean_rows']:,} | SKUs {len(skus)} | "
        f"weekly units {weekly_units:,.0f} | sample orders {args.orders}"
    )

    location = _location_results(
        clean, skus, args.top_countries, args.location_time, last_week
    )
    optimized = location["optimized"]
    baseline = location["baseline"]
    print("\nFacility location:")
    print(
        f"  all-open nearest: {baseline['opened']} hubs, "
        f"cost {baseline['total_cost']:,.0f}"
    )
    print(
        f"  CFLP optimum:     {optimized['opened']} hubs "
        f"({', '.join(row['facility'] for row in location['facilities'])}), "
        f"cost {optimized['total_cost']:,.0f}"
    )

    routing = _route_results(weekly_units, args.routing_time)
    print("\nVehicle routing:")
    print(pd.DataFrame(routing["plans"]).to_string(index=False))

    warehouse = _warehouse_results(clean, skus, args.orders, args.seed, last_week)
    print("\nWarehouse slotting / picking:")
    print(pd.DataFrame(warehouse["summary"]).to_string(index=False))

    dataset = {
        "clean_rows": clean_stats["clean_rows"],
        "skus": len(skus),
        "period_start": str(last_week.date() - pd.Timedelta(weeks=51)),
        "period_end": str(last_week.date()),
        "transaction_start": str(pd.to_datetime(clean["invoice_date"]).min().date()),
        "transaction_end": str(pd.to_datetime(clean["invoice_date"]).max().date()),
        "weekly_units": weekly_units,
    }
    results = {
        "dataset": dataset,
        "location": location,
        "routing": routing,
        "warehouse": warehouse,
    }
    paths = write_network_report(results, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
