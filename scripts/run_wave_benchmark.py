"""Week 6 benchmark: wave picking and order batching.

Uses real invoices from one trading week, ABC slots from Week 3, and an
explicit labor/capacity assumption layer.

Usage:
    PYTHONPATH=src;. python scripts/run_wave_benchmark.py
    PYTHONPATH=src;. python scripts/run_wave_benchmark.py --orders 60 --milp-time 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

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
    assign_slots,
    build_picking_orders,
)
from supply.wave import (  # noqa: E402
    build_wave_instance,
    fcfs_waves,
    optimize_waves,
    savings_batches,
    single_order_waves,
    wave_detail,
    wave_summary,
    write_wave_report,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Week 6 wave picking benchmark")
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
    parser.add_argument("--orders", type=int, default=200)
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--max-orders-per-wave", type=int, default=8)
    parser.add_argument("--max-lines-per-wave", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-pairs", type=int, default=2000)
    parser.add_argument("--random-runs", type=int, default=8)
    parser.add_argument("--jitter", type=float, default=0.30)
    parser.add_argument("--milp-time", type=float, default=15.0)
    parser.add_argument("--sensitivity-time", type=float, default=8.0)
    parser.add_argument("--skip-sensitivity", action="store_true")
    parser.add_argument("--title", default="Wave picking benchmark (Week 6)")
    args = parser.parse_args()

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)

    order_lines, velocity, order_meta = build_picking_orders(
        clean,
        skus,
        sample_orders=args.orders,
        max_lines=args.max_lines,
        seed=args.seed,
        week=last_week,
    )
    layout = WarehouseLayout(n_aisles=8, n_bays=16)
    assignment = assign_slots(skus, layout, velocity, strategy="abc", seed=args.seed)
    instance_meta = {
        "week": str(last_week.date()),
        "slotting": "abc",
        "arrival_seed": args.seed,
        "sampled_invoices": order_meta["sampled_invoices"],
        "eligible_invoices": order_meta["eligible_invoices"],
        "median_lines_per_order": order_meta["median_lines_per_order"],
    }

    def build(max_orders: int, max_lines: int):
        return build_wave_instance(
            order_lines,
            assignment,
            layout,
            max_orders=max_orders,
            max_lines=max_lines,
            meta=instance_meta,
        )

    instance = build(args.max_orders_per_wave, args.max_lines_per_wave)

    print("=" * 96)
    print(args.title)
    print("=" * 96)
    print(
        f"orders {instance.meta['orders']} | lines {instance.meta['lines']} | "
        f"units {instance.meta['units']:,.0f} | SKUs {instance.meta['skus']} | "
        f"wave cap {instance.max_orders} orders / {instance.max_lines} lines"
    )

    results = {
        "single_order": single_order_waves(instance),
        "fcfs": fcfs_waves(instance, seed=args.seed),
        "savings": savings_batches(instance, jitter=0.0, seed=args.seed),
        "milp": optimize_waves(
            instance,
            max_pairs=args.max_pairs,
            random_runs=args.random_runs,
            jitter=args.jitter,
            seed=args.seed,
            time_limit_seconds=args.milp_time,
        ),
    }
    summary = wave_summary(results)
    print()
    print(
        pd.DataFrame(summary)[
            [
                "scenario",
                "status",
                "waves",
                "travel_per_order",
                "travel_saving",
                "labor_per_order",
                "labor_saving",
                "orders_per_hour",
                "labor_cost",
                "solve_seconds",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    milp = results["milp"]
    print(
        f"\nCP-SAT: pool {milp.pool_size} waves | objective "
        f"{milp.objective:.1f} min | bound {milp.best_bound:.1f} | "
        f"gap {milp.gap:.1%}" if milp.gap is not None else ""
    )

    sensitivity = []
    if not args.skip_sensitivity:
        for max_orders, max_lines in ((8, 25), (4, 19), (3, 19)):
            if (max_orders, max_lines) == (
                args.max_orders_per_wave,
                args.max_lines_per_wave,
            ):
                continue
            cap_instance = build(max_orders, max_lines)
            cap_savings = savings_batches(cap_instance, seed=args.seed)
            cap_milp = optimize_waves(
                cap_instance,
                max_pairs=args.max_pairs,
                random_runs=args.random_runs,
                jitter=args.jitter,
                seed=args.seed,
                time_limit_seconds=args.sensitivity_time,
            )
            sensitivity.append(
                {
                    "caps": f"{max_orders}/{max_lines}",
                    "savings_waves": cap_savings.waves,
                    "savings_travel": cap_savings.travel_per_order,
                    "savings_labor": cap_savings.labor_per_order,
                    "mip_status": cap_milp.status,
                    "mip_waves": cap_milp.waves,
                    "mip_travel": cap_milp.travel_per_order,
                    "mip_labor": cap_milp.labor_per_order,
                    "mip_gap": cap_milp.gap,
                    "pool_size": cap_milp.pool_size,
                }
            )
        print("\nWave-cap sensitivity (orders/lines per wave):")
        print(
            pd.DataFrame(sensitivity).to_string(
                index=False, float_format=lambda value: f"{value:,.3f}"
            )
        )

    dataset = {
        "clean_rows": clean_stats["clean_rows"],
        "skus": len(skus),
        "period_start": str(last_week.date() - pd.Timedelta(weeks=51)),
        "period_end": str(last_week.date()),
        "transaction_start": str(pd.to_datetime(clean["invoice_date"]).min().date()),
        "transaction_end": str(pd.to_datetime(clean["invoice_date"]).max().date()),
    }
    report = {
        "dataset": dataset,
        "assumptions": {**instance.meta, **order_meta},
        "summary": summary,
        "sensitivity": sensitivity,
        "detail": wave_detail(instance, milp),
    }
    paths = write_wave_report(report, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
