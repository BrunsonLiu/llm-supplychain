"""Benchmark: multi-DC order fulfillment (greedy vs CP-SAT).

Orders, line quantities, SKU mix, and destination countries are real invoices
from the last complete trading week of Online Retail II. Warehouse stock,
throughput caps, transit days, shipping rates, and SLA promises are the
explicit assumption layer in ``supply.fulfillment.instances``.

Usage:
    PYTHONPATH=src;. python scripts/run_fulfillment_benchmark.py
    PYTHONPATH=src;. python scripts/run_fulfillment_benchmark.py --orders 60 --milp-time 10
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data.online_retail import (  # noqa: E402
    clean_transactions,
    load_online_retail_raw,
    load_panel,
)
from supply.fulfillment import (  # noqa: E402
    FulfillmentResult,
    allocate_greedy,
    allocate_milp,
    build_fulfillment_instance,
    dc_table,
    order_table,
    promise_table,
    write_fulfillment_report,
)

SCENARIO_LABELS = {
    "greedy": "Greedy (deadline-first)",
    "milp_1": "MILP (max 1 DC/order)",
    "milp_2": "MILP (max 2 DCs/order)",
    "milp_service": "MILP (2 DCs, 5x late penalty)",
}


def _scenario_payload(key: str, result: FulfillmentResult, instance) -> Dict[str, Any]:
    dc_load = dc_table(instance, result)
    promise = promise_table(instance, result)
    return {
        "key": key,
        "name": SCENARIO_LABELS.get(key, key),
        "status": result.status,
        "unit_fill": result.unit_fill_rate,
        "order_fill": result.order_fill_rate,
        "otif": result.otif_rate,
        "on_time_unit_rate": result.on_time_unit_rate,
        "split_rate": result.split_rate,
        "shipments": result.shipments_count,
        "transport": result.transport_cost,
        "fixed": result.fixed_cost,
        "late": result.late_cost,
        "unmet": result.unmet_cost,
        "total": result.total_cost,
        "solve_seconds": result.solve_seconds,
        "best_bound": result.best_bound,
        "gap": result.gap,
        "dc_load": [
            {
                "dc": row["DC"],
                "units": int(row["units shipped"]),
                "capacity": int(row["weekly capacity"]),
                "utilization": float(row["capacity use"]),
                "stock_left": int(row["stock left"]),
            }
            for _, row in dc_load.iterrows()
        ],
        "promise": [
            {
                "promise": row["promise"],
                "orders": int(row["orders"]),
                "otif": float(row["OTIF"]),
                "late_units": int(row["late units"]),
                "unmet_units": int(row["unmet units"]),
            }
            for _, row in promise.iterrows()
        ],
    }


def _difference_examples(instance, greedy: FulfillmentResult, milp: FulfillmentResult):
    left = order_table(instance, greedy).set_index("order")
    right = order_table(instance, milp).set_index("order")
    joined = left.join(
        right[
            ["dcs", "otif", "late_units", "fulfilled"]
        ],
        lsuffix="_greedy",
        rsuffix="_milp",
    )
    improved = joined[
        (joined["otif_greedy"] == False) & (joined["otif_milp"] == True)  # noqa: E712
    ].sort_values("units", ascending=False)
    rows: List[Dict[str, Any]] = []
    for order, row in improved.head(6).iterrows():
        rows.append(
            {
                "order": order,
                "destination": row["destination"],
                "promise": int(row["promise"]),
                "units": int(row["units"]),
                "greedy_dcs": list(row["dcs_greedy"]),
                "greedy_otif": bool(row["otif_greedy"]),
                "milp_dcs": list(row["dcs_milp"]),
                "milp_otif": bool(row["otif_milp"]),
                "milp_late_units": int(row["late_units_milp"]),
            }
        )
    return rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Order fulfillment benchmark")
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
    parser.add_argument("--orders", type=int, default=120)
    parser.add_argument("--max-lines", type=int, default=8)
    parser.add_argument("--stock-factor", type=float, default=0.85)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--milp-time", type=float, default=25.0)
    parser.add_argument(
        "--service-late-weight",
        type=float,
        default=5.0,
        help="OTIF-weighted MILP multiplies the lateness penalty by this factor",
    )
    parser.add_argument(
        "--service-otif-bonus",
        type=float,
        default=200.0,
        help="per-order reward for fully on-time delivery in the service MILP",
    )
    parser.add_argument(
        "--title", default="Order fulfillment benchmark (multi-DC allocation)"
    )
    args = parser.parse_args()

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)

    instance = build_fulfillment_instance(
        clean,
        skus,
        sample_orders=args.orders,
        max_lines=args.max_lines,
        stock_factor=args.stock_factor,
        seed=args.seed,
        week=last_week,
    )

    print("=" * 72)
    print(args.title)
    print("=" * 72)
    print(
        f"orders {instance.n_orders} | lines {instance.n_lines} | "
        f"units {instance.meta['units']:,} | SKUs {instance.n_skus} | "
        f"stock coverage {instance.meta['stock_coverage']:.1%}"
    )

    results = {
        "greedy": allocate_greedy(instance, max_splits=2),
        "milp_1": allocate_milp(instance, max_splits=1, time_limit_seconds=args.milp_time),
        "milp_2": allocate_milp(instance, max_splits=2, time_limit_seconds=args.milp_time),
        "milp_service": allocate_milp(
            instance,
            max_splits=2,
            time_limit_seconds=args.milp_time,
            late_penalty_per_unit_day=instance.late_penalty_per_unit_day
            * args.service_late_weight,
            otif_bonus=args.service_otif_bonus,
        ),
    }

    print("\nScenario comparison:")
    table = pd.DataFrame(
        [
            {
                "scenario": SCENARIO_LABELS[key],
                "status": result.status,
                "unit fill": result.unit_fill_rate,
                "order fill": result.order_fill_rate,
                "OTIF": result.otif_rate,
                "split rate": result.split_rate,
                "shipments": result.shipments_count,
                "total cost": result.total_cost,
                "gap": result.gap,
                "solve s": result.solve_seconds,
            }
            for key, result in results.items()
        ]
    )
    print(table.to_string(index=False, float_format=lambda value: f"{value:,.3f}"))

    examples = _difference_examples(instance, results["greedy"], results["milp_2"])
    payload = {
        "dataset": {
            "clean_rows": clean_stats["clean_rows"],
            "skus": len(skus),
            "period_start": str(last_week.date() - pd.Timedelta(weeks=51)),
            "period_end": str(last_week.date()),
        },
        "instance": instance.meta,
        "scenarios": [
            _scenario_payload(key, result, instance)
            for key, result in results.items()
        ],
        "service": {
            "late_weight": args.service_late_weight,
            "otif_bonus": args.service_otif_bonus,
            "time_limit_seconds": args.milp_time,
        },
        "examples": examples,
    }
    paths = write_fulfillment_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
