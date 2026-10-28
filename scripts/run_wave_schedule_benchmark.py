"""Week 7 benchmark: deadline-aware wave release scheduling.

Reuses the Week-6 batching instance, adds promise tiers and cutoffs, and
compares pick-by-order, full batching and tier-aware batching under EDF and
CP-SAT scheduling.

Usage:
    PYTHONPATH=src;. python scripts/run_wave_schedule_benchmark.py
    PYTHONPATH=src;. python scripts/run_wave_schedule_benchmark.py --orders 60 --skip-sensitivity
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
    MAKESPAN_WEIGHT,
    TARDINESS_WEIGHT,
    assign_promises,
    build_wave_instance,
    jobs_from_result,
    optimize_waves,
    promise_summary,
    savings_batches,
    schedule_cpsat,
    schedule_detail,
    schedule_edf,
    schedule_metrics,
    schedule_summary,
    single_order_waves,
    write_schedule_report,
)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Week 7 wave release scheduling benchmark")
    parser.add_argument("--xlsx", default=str(ROOT / "data/raw/online_retail_II.xlsx"))
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
    parser.add_argument("--pickers", type=int, default=2)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-pairs", type=int, default=2000)
    parser.add_argument("--random-runs", type=int, default=8)
    parser.add_argument("--jitter", type=float, default=0.30)
    parser.add_argument("--milp-time", type=float, default=15.0)
    parser.add_argument("--schedule-time", type=float, default=10.0)
    parser.add_argument("--sensitivity-time", type=float, default=8.0)
    parser.add_argument("--skip-sensitivity", action="store_true")
    parser.add_argument("--title", default="Wave release scheduling benchmark (Week 7)")
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
    instance = build_wave_instance(
        order_lines,
        assignment,
        layout,
        max_orders=args.max_orders_per_wave,
        max_lines=args.max_lines_per_wave,
        meta=instance_meta,
    )
    plan = assign_promises(instance, seed=args.seed)

    print("=" * 96)
    print(args.title)
    print("=" * 96)
    print(
        f"orders {instance.meta['orders']} | lines {instance.meta['lines']} | "
        f"units {instance.meta['units']:,.0f} | SKUs {instance.meta['skus']} | "
        f"wave cap {instance.max_orders}/{instance.max_lines} | "
        f"pickers {args.pickers} | shift {args.shift_minutes:.0f} min"
    )
    print(
        "promise mix: express "
        f"{plan.tier_counts['express']} @ {plan.cutoffs['express']} min, standard "
        f"{plan.tier_counts['standard']} @ {plan.cutoffs['standard']} min, economy "
        f"{plan.tier_counts['economy']} @ {plan.cutoffs['economy']} min"
    )

    single = single_order_waves(instance)
    full = optimize_waves(
        instance,
        max_pairs=args.max_pairs,
        random_runs=args.random_runs,
        jitter=args.jitter,
        seed=args.seed,
        time_limit_seconds=args.milp_time,
    )
    tiered = savings_batches(
        instance,
        groups=plan.tier_of,
        name="承诺分层合并波次",
    )

    common = dict(
        picker_count=args.pickers,
        shift_minutes=args.shift_minutes,
        labor_cost_per_minute=instance.labor_cost_per_minute,
    )
    jobs = {
        "single": jobs_from_result(instance, single, plan),
        "full": jobs_from_result(instance, full, plan),
        "tiered": jobs_from_result(instance, tiered, plan),
    }
    schedules = {
        "single_edf": schedule_edf(jobs["single"], name="按单拣选 + EDF", **common),
        "full_edf": schedule_edf(jobs["full"], name="全量合并 + EDF", **common),
        "full_cpsat": schedule_cpsat(
            jobs["full"],
            time_limit_seconds=args.schedule_time,
            seed=args.seed,
            name="全量合并 + CP-SAT",
            **common,
        ),
        "tiered_edf": schedule_edf(jobs["tiered"], name="承诺分层合并 + EDF", **common),
        "tiered_cpsat": schedule_cpsat(
            jobs["tiered"],
            time_limit_seconds=args.schedule_time,
            seed=args.seed,
            name="承诺分层合并 + CP-SAT",
            **common,
        ),
    }
    summary = schedule_summary(schedules)
    print()
    print(
        pd.DataFrame(summary)[
            [
                "scenario",
                "status",
                "waves",
                "labor_per_order",
                "on_time_rate",
                "tardy_orders",
                "total_tardiness",
                "makespan",
                "overtime",
                "solve_seconds",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )
    tiered_mip = schedules["tiered_cpsat"]
    print(
        f"\ntier-aware CP-SAT: {tiered_mip.status} | objective "
        f"{tiered_mip.objective:.1f} | bound {tiered_mip.best_bound:.1f} | "
        f"gap {tiered_mip.gap:.2%}"
    )

    sensitivity = []
    if not args.skip_sensitivity:
        for pickers in (1, 2, 3):
            if pickers == args.pickers:
                edf = schedules["tiered_edf"]
                mip = schedules["tiered_cpsat"]
            else:
                edf = schedule_edf(
                    jobs["tiered"],
                    picker_count=pickers,
                    shift_minutes=args.shift_minutes,
                    labor_cost_per_minute=instance.labor_cost_per_minute,
                    name="承诺分层合并 + EDF",
                )
                mip = schedule_cpsat(
                    jobs["tiered"],
                    picker_count=pickers,
                    shift_minutes=args.shift_minutes,
                    labor_cost_per_minute=instance.labor_cost_per_minute,
                    time_limit_seconds=args.sensitivity_time,
                    seed=args.seed,
                    name="承诺分层合并 + CP-SAT",
                )
            edf_metrics = schedule_metrics(edf)
            mip_metrics = schedule_metrics(mip)
            sensitivity.append(
                {
                    "pickers": pickers,
                    "edf_on_time_rate": edf_metrics["on_time_rate"],
                    "edf_tardiness": edf_metrics["total_tardiness"],
                    "edf_makespan": edf_metrics["makespan"],
                    "mip_status": mip.status,
                    "mip_on_time_rate": mip_metrics["on_time_rate"],
                    "mip_tardiness": mip_metrics["total_tardiness"],
                    "mip_makespan": mip_metrics["makespan"],
                    "mip_seconds": mip.solve_seconds,
                }
            )
        print("\nPicker-count sensitivity (tier-aware partition):")
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
        "orders": instance.meta["orders"],
        "lines": instance.meta["lines"],
        "units": instance.meta["units"],
        "week": str(last_week.date()),
        "max_orders": instance.max_orders,
        "max_lines": instance.max_lines,
        "travel_m_per_minute": instance.travel_meters_per_minute,
        "pick_min_per_line": instance.pick_minutes_per_line,
        "pick_min_per_unit": instance.pick_minutes_per_unit,
        "setup_min_per_wave": instance.setup_minutes_per_wave,
    }
    report = {
        "dataset": dataset,
        "plan": {
            "mix": plan.mix,
            "cutoffs": plan.cutoffs,
            "tier_counts": plan.tier_counts,
            "seed": args.seed,
        },
        "schedule": {
            "pickers": args.pickers,
            "shift_minutes": args.shift_minutes,
            "start_hour": 8,
            "tardiness_weight": TARDINESS_WEIGHT,
            "makespan_weight": MAKESPAN_WEIGHT,
        },
        "batching": {
            "single_waves": single.waves,
            "full_waves": full.waves,
            "tiered_waves": tiered.waves,
            "full_labor_per_order": full.labor_per_order,
            "tiered_labor_per_order": tiered.labor_per_order,
            "full_batching_status": full.status,
            "full_pool_size": full.pool_size,
        },
        "summary": summary,
        "promises": {
            "full_edf": promise_summary(schedules["full_edf"]),
            "tiered_edf": promise_summary(schedules["tiered_edf"]),
        },
        "sensitivity": sensitivity,
        "detail": schedule_detail(schedules["tiered_cpsat"], limit=10),
    }
    paths = write_schedule_report(report, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
