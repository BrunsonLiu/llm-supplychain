"""Week 8 benchmark: mid-shift arrivals and online wave release.

Reuses the Week-6/7 wave instance and promise plan, adds a synthetic arrival
process, and compares online single-order, EDF fill, re-batching and
wait-to-fill policies against an offline reference.

Usage:
    PYTHONPATH=src;. python scripts/run_dynamic_wave_benchmark.py
    PYTHONPATH=src;. python scripts/run_dynamic_wave_benchmark.py --orders 60 --loads 60 --tuning-waits 0 15 --tuning-fills 4 6
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

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
    assign_slots,
    build_picking_orders,
)
from supply.wave import (  # noqa: E402
    DEFAULT_TIER_ONSITE,
    DEFAULT_TIER_WINDOWS,
    TIER_LABELS,
    TIER_ORDER,
    assign_arrivals,
    assign_promises,
    build_wave_instance,
    dynamic_detail,
    dynamic_metrics,
    dynamic_summary,
    oracle_schedule,
    simulate_online,
    write_dynamic_report,
)


def _clock(minutes: float) -> str:
    total = int(round(minutes))
    return f"{8 + total // 60:02d}:{total % 60:02d}"


def _build_instance(
    clean: pd.DataFrame,
    skus: List[str],
    layout: WarehouseLayout,
    week: pd.Timestamp,
    orders: int,
    seed: int,
    max_lines: int,
    max_orders_per_wave: int,
    max_lines_per_wave: int,
):
    order_lines, velocity, order_meta = build_picking_orders(
        clean,
        skus,
        sample_orders=orders,
        max_lines=max_lines,
        seed=seed,
        week=week,
    )
    assignment = assign_slots(skus, layout, velocity, strategy="abc", seed=seed)
    instance = build_wave_instance(
        order_lines,
        assignment,
        layout,
        max_orders=max_orders_per_wave,
        max_lines=max_lines_per_wave,
        meta={
            "week": str(week.date()),
            "slotting": "abc",
            "arrival_seed": seed,
            "sampled_invoices": order_meta["sampled_invoices"],
            "eligible_invoices": order_meta["eligible_invoices"],
            "median_lines_per_order": order_meta["median_lines_per_order"],
        },
    )
    plan = assign_promises(instance, seed=seed)
    arrivals = assign_arrivals(instance, plan, seed=seed)
    return instance, plan, arrivals


def _arrival_profile(instance, plan, arrivals) -> List[Dict[str, object]]:
    invoices = [order.invoice for order in instance.orders]
    profile = []
    for tier in TIER_ORDER:
        selected = [invoice for invoice in invoices if plan.tier_of[invoice] == tier]
        times = np.array([arrivals.arrival_of[invoice] for invoice in selected])
        window = arrivals.tier_windows[tier]
        onsite = sum(1 for value in times if value <= 1e-9)
        profile.append(
            {
                "tier": TIER_LABELS[tier],
                "cutoff": _clock(plan.cutoffs[tier]),
                "orders": len(selected),
                "onsite": onsite,
                "onsite_rate": onsite / len(selected) if selected else 0.0,
                "mid_shift": len(selected) - onsite,
                "window": window,
                "mean_arrival": float(np.mean(times)) if len(times) else 0.0,
                "median_arrival": float(np.median(times)) if len(times) else 0.0,
                "after_cutoff": int(sum(1 for value in times if value > plan.cutoffs[tier])),
            }
        )
    return profile


def _policy_schedules(
    instance, plan, arrivals, common, wait_minutes, min_fill, aggressive
):
    aggressive_wait, aggressive_fill = aggressive
    return {
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
            wait_minutes=wait_minutes,
            min_fill=min_fill,
            name=f"在线节省 + 等待凑波（{wait_minutes:.0f} min / ≥{min_fill} 单）",
            **common,
        ),
        "wait_aggressive": simulate_online(
            instance,
            plan,
            arrivals,
            policy="savings_wait",
            wait_minutes=aggressive_wait,
            min_fill=aggressive_fill,
            name=(
                f"在线节省 + 激进等待（{aggressive_wait:.0f} min / "
                f"≥{aggressive_fill} 单）"
            ),
            **common,
        ),
        "oracle": oracle_schedule(
            instance,
            plan,
            picker_count=common["picker_count"],
            shift_minutes=common["shift_minutes"],
        ),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Week 8 online wave release benchmark")
    parser.add_argument("--xlsx", default=str(ROOT / "data/raw/online_retail_II.xlsx"))
    parser.add_argument(
        "--raw-cache", default=str(ROOT / "data/raw/online_retail_II.raw.parquet")
    )
    parser.add_argument(
        "--panel", default=str(ROOT / "data/processed/online_retail_ii_weekly.parquet")
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--orders", type=int, default=200)
    parser.add_argument("--loads", type=int, nargs="+", default=[60, 120, 200])
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--max-orders-per-wave", type=int, default=8)
    parser.add_argument("--max-lines-per-wave", type=int, default=40)
    parser.add_argument("--pickers", type=int, default=2)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--wait-minutes", type=float, default=15.0)
    parser.add_argument("--min-fill", type=int, default=4)
    parser.add_argument("--aggressive-wait", type=float, default=30.0)
    parser.add_argument("--aggressive-fill", type=int, default=6)
    parser.add_argument("--tuning-waits", type=float, nargs="+", default=[0, 10, 20, 30])
    parser.add_argument("--tuning-fills", type=int, nargs="+", default=[4, 6, 8])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--title", default="Online wave release benchmark (Week 8)"
    )
    args = parser.parse_args()

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    layout = WarehouseLayout(n_aisles=8, n_bays=16)

    loads = sorted(set(args.loads) | {args.orders})
    built: Dict[int, tuple] = {}
    for orders in loads:
        built[orders] = _build_instance(
            clean,
            skus,
            layout,
            last_week,
            orders,
            args.seed,
            args.max_lines,
            args.max_orders_per_wave,
            args.max_lines_per_wave,
        )

    instance, plan, arrivals = built[args.orders]
    common = dict(
        picker_count=args.pickers,
        shift_minutes=args.shift_minutes,
    )

    print("=" * 100)
    print(args.title)
    print("=" * 100)
    print(
        f"orders {instance.meta['orders']} | lines {instance.meta['lines']} | "
        f"units {instance.meta['units']:,.0f} | SKUs {instance.meta['skus']} | "
        f"wave cap {instance.max_orders}/{instance.max_lines} | "
        f"pickers {args.pickers} | shift {args.shift_minutes:.0f} min"
    )
    print(
        f"arrivals: onsite {arrivals.onsite_orders} | mid-shift "
        f"{arrivals.mid_shift_orders} | windows "
        + ", ".join(
            f"{TIER_LABELS[tier]} {arrivals.tier_windows[tier]:.0f} min"
            for tier in TIER_ORDER
        )
    )

    schedules = _policy_schedules(
        instance,
        plan,
        arrivals,
        common,
        args.wait_minutes,
        args.min_fill,
        (args.aggressive_wait, args.aggressive_fill),
    )
    summary = dynamic_summary(schedules, arrivals)
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
                "avg_wait",
                "p90_wait",
                "idle_minutes",
                "makespan",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    tuning = []
    for wait_minutes in args.tuning_waits:
        for min_fill in args.tuning_fills:
            schedule = simulate_online(
                instance,
                plan,
                arrivals,
                policy="savings_wait",
                wait_minutes=wait_minutes,
                min_fill=min_fill,
                name=f"等待 {wait_minutes:.0f} min / ≥{min_fill} 单",
                **common,
            )
            metrics = dynamic_metrics(schedule, arrivals)
            tuning.append(
                {
                    "wait_minutes": float(wait_minutes),
                    "min_fill": int(min_fill),
                    **metrics,
                    "makespan": metrics["makespan"],
                }
            )
    print("\nWait-policy tuning (base load):")
    print(
        pd.DataFrame(tuning)[
            [
                "wait_minutes",
                "min_fill",
                "waves",
                "labor_per_order",
                "on_time_rate",
                "total_tardiness",
                "avg_wait",
                "makespan",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    load_sweep = []
    for orders in loads:
        load_instance, load_plan, load_arrivals = built[orders]
        load_schedules = _policy_schedules(
            load_instance,
            load_plan,
            load_arrivals,
            common,
            args.wait_minutes,
            args.min_fill,
            (args.aggressive_wait, args.aggressive_fill),
        )
        for row in dynamic_summary(load_schedules, load_arrivals):
            load_sweep.append({"orders": orders, **row})
    print("\nLoad sensitivity:")
    print(
        pd.DataFrame(load_sweep)[
            [
                "orders",
                "scenario",
                "waves",
                "labor_per_order",
                "on_time_rate",
                "total_tardiness",
                "avg_wait",
                "makespan",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
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
        "arrivals": {
            "onsite_orders": arrivals.onsite_orders,
            "mid_shift_orders": arrivals.mid_shift_orders,
            "onsite_share": dict(DEFAULT_TIER_ONSITE),
            "windows": dict(DEFAULT_TIER_WINDOWS),
            "onsite_by_tier": dict(arrivals.onsite),
            "seed": arrivals.seed,
            "profile": _arrival_profile(instance, plan, arrivals),
        },
        "settings": {
            "pickers": args.pickers,
            "shift_minutes": args.shift_minutes,
            "start_hour": 8,
            "wait_minutes": args.wait_minutes,
            "min_fill": args.min_fill,
            "aggressive_wait": args.aggressive_wait,
            "aggressive_fill": args.aggressive_fill,
            "seed": args.seed,
        },
        "plan": {
            "mix": plan.mix,
            "cutoffs": plan.cutoffs,
            "tier_counts": plan.tier_counts,
            "seed": plan.seed,
        },
        "summary": summary,
        "tuning": tuning,
        "load_sweep": load_sweep,
        "detail": dynamic_detail(schedules["wait"], limit=10),
    }
    paths = write_dynamic_report(report, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
