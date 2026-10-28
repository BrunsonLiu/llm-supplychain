"""Week 11 benchmark: stock deployment under execution risk.

Week 10 varies arrivals and pick durations but keeps the stock split fixed.
This script treats the DC stock split itself as the decision: for each declared
placement it rebuilds the instance, re-solves the pick-capacity-aware
allocation, and replays the same arrival and congestion seeds.

Only stock placement changes. Orders, promises, layout, slots, picker count and
release policy stay fixed, so differences isolate where inventory sits.

Usage:
    PYTHONPATH=src;. python scripts/run_e2e_deployment.py
    PYTHONPATH=src;. python scripts/run_e2e_deployment.py --orders 100 --seeds 5 --milp-time 5
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
from supply.e2e import (  # noqa: E402
    DEFAULT_STOCK_PLANS,
    PROMISE_TIER,
    TIER_CUTOFFS,
    StressCell,
    build_e2e_instance,
    over_shift_rate,
    plan_row,
    plans_for,
    rebuild_arrivals,
    run_monte_carlo,
    run_pick_layer,
    summarize_runs,
    write_stock_deployment_report,
)
from supply.fulfillment import FulfillmentResult, allocate_milp  # noqa: E402
from supply.wave.instances import (  # noqa: E402
    LABOR_COST_PER_MINUTE,
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_UNIT,
    SETUP_MINUTES_PER_WAVE,
    TRAVEL_METERS_PER_MINUTE,
)

PICK_DEADLINES = {days: TIER_CUTOFFS[tier] for days, tier in PROMISE_TIER.items()}
PLAN_LABELS = {plan.key: plan.label for plan in DEFAULT_STOCK_PLANS}


def _stock_plan_allocation(instance, args) -> FulfillmentResult:
    fulfillment = instance.fulfillment
    service = allocate_milp(
        fulfillment,
        max_splits=2,
        time_limit_seconds=args.service_time,
        workers=args.workers,
        late_penalty_per_unit_day=fulfillment.late_penalty_per_unit_day
        * args.service_late_weight,
        otif_bonus=args.service_otif_bonus,
        name=f"{instance.fulfillment.meta.get('stock_plan', '')} · 服务优先",
    )
    return allocate_milp(
        fulfillment,
        max_splits=2,
        time_limit_seconds=args.milp_time,
        workers=args.workers,
        late_penalty_per_unit_day=fulfillment.late_penalty_per_unit_day
        * args.service_late_weight,
        otif_bonus=args.service_otif_bonus,
        pick_deadlines=PICK_DEADLINES,
        pick_overload_penalty=args.pick_overload_penalty,
        hint=service,
        name=f"{instance.fulfillment.meta.get('stock_plan', '')} · 拣选容量感知",
    )


def _cells(args) -> list[StressCell]:
    return [
        StressCell("base", "基准：均匀到达 · 确定性", "edf", None, 0.0, args.pickers),
        StressCell(
            "noise",
            f"拣选噪声 σ={args.noise_sigma:.2f}",
            "edf",
            None,
            args.noise_sigma,
            args.pickers,
        ),
        StressCell(
            "severe",
            f"重度拥堵 σ={args.severe_sigma:.2f}",
            "edf",
            None,
            args.severe_sigma,
            args.pickers,
        ),
        StressCell(
            "two_pickers",
            "加 1 名拣货员/DC",
            "edf",
            None,
            0.0,
            args.pickers + 1,
        ),
    ]


def _dc_workload(instance, allocation, plan_key: str, seed: int) -> list[dict]:
    shifted = rebuild_arrivals(instance, seed)
    result = run_pick_layer(
        shifted,
        allocation,
        scenario=plan_key,
        policy="edf",
        pickers_per_dc=instance.pickers_per_dc,
    )
    return [
        {
            "plan": plan_key,
            "dc": row.dc,
            "tickets": row.tickets,
            "waves": row.waves,
            "labor_minutes": row.labor_minutes,
            "on_time_tickets": row.on_time_tickets,
            "tardy_tickets": row.tardy_tickets,
            "tardiness_minutes": row.tardiness_minutes,
            "makespan": row.makespan,
        }
        for row in result.dc
    ]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 11 stock-deployment benchmark"
    )
    parser.add_argument("--xlsx", default=str(ROOT / "data/raw/online_retail_II.xlsx"))
    parser.add_argument(
        "--raw-cache", default=str(ROOT / "data/raw/online_retail_II.raw.parquet")
    )
    parser.add_argument(
        "--panel",
        default=str(ROOT / "data/processed/online_retail_ii_weekly.parquet"),
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--orders", type=int, default=400)
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--stock-factor", type=float, default=0.85)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--plans",
        default=",".join(plan.key for plan in DEFAULT_STOCK_PLANS),
        help="comma-separated stock-plan keys",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=30,
        help="number of arrival seeds, drawn as 1..N",
    )
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--service-time", type=float, default=30.0)
    parser.add_argument("--milp-time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--severe-sigma", type=float, default=0.40)
    parser.add_argument(
        "--title", default="Stock deployment under execution risk (Week 11)"
    )
    args = parser.parse_args()

    plan_keys = [key.strip() for key in args.plans.split(",") if key.strip()]
    plans = plans_for(plan_keys)

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)

    seeds = list(range(1, args.seeds + 1))
    cells = _cells(args)

    print("=" * 110)
    print(args.title)
    print("=" * 110)
    print(
        f"orders {args.orders} | max lines/order {args.max_lines} | "
        f"stock factor {args.stock_factor:.0%} | seed {args.seed} | "
        f"pickers/DC {args.pickers} | shift {args.shift_minutes:.0f} min"
    )
    print(
        f"plans {[plan.key for plan in plans]} | seeds {seeds[0]}..{seeds[-1]} "
        f"({len(seeds)}) | stress cells {len(cells)}"
    )

    allocations: dict[str, FulfillmentResult] = {}
    plan_rows: list[dict] = []
    plan_tickets: dict[str, int] = {}
    frames = []
    dc_rows: list[dict] = []
    first_instance = None
    for plan in plans:
        instance = build_e2e_instance(
            clean,
            skus,
            sample_orders=args.orders,
            max_lines=args.max_lines,
            stock_factor=args.stock_factor,
            stock_shares=plan.shares,
            seed=args.seed,
            week=last_week,
            pickers_per_dc=args.pickers,
            shift_minutes=args.shift_minutes,
            arrival_seed=1,
        )
        first_instance = first_instance or instance
        instance.fulfillment.meta["stock_plan"] = plan.key
        row = plan_row(plan, instance)
        plan_rows.append(row)
        print(
            f"\n[{plan.key}] {plan.label} | declared {' / '.join(f'{value:.0%}' for value in plan.shares)} | "
            f"realised {' / '.join(f'{value:.0%}' for value in row['stock_mix'])} | "
            f"coverage {row['coverage']:.1%} | stock units "
            f"{' / '.join(f'{value:,}' for value in row['stock_units'])}"
        )
        allocation = _stock_plan_allocation(instance, args)
        allocations[plan.key] = allocation
        print(
            f"  allocation: {allocation.status} | fill {allocation.unit_fill_rate:.1%} | "
            f"alloc OTIF {allocation.otif_rate:.1%} | cost €{allocation.total_cost:,.0f} | "
            f"solve {allocation.solve_seconds:.1f}s"
        )
        print(f"  replaying {len(cells)} cells × {len(seeds)} seeds ...")
        frames.append(run_monte_carlo(instance, {plan.key: allocation}, cells, seeds))
        plan_dc_rows = _dc_workload(instance, allocation, plan.key, seeds[0])
        plan_tickets[plan.key] = sum(row["tickets"] for row in plan_dc_rows)
        dc_rows.extend(plan_dc_rows)

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_runs(frame)
    over = over_shift_rate(frame, args.shift_minutes)

    otif = summary[summary["metric"] == "e2e_otif_rate"]
    print("\nEnd-to-end OTIF by stock plan × stress cell:")
    print(
        otif[
            ["scenario", "cell_label", "mean", "ci95", "p10", "p50", "p90", "tail10"]
        ].to_string(index=False, float_format=lambda value: f"{value:,.4f}")
    )

    dataset = {
        **first_instance.meta,
        "orders": first_instance.n_orders,
        "lines": first_instance.meta["order_lines"],
        "week": str(last_week.date()),
        "pickers_per_dc": args.pickers,
        "shift_minutes": args.shift_minutes,
        "max_orders": first_instance.max_orders,
        "max_lines": first_instance.max_lines,
        "dcs": list(first_instance.fulfillment.dc_names),
        "clean_rows": clean_stats["clean_rows"],
        "travel_m_per_minute": TRAVEL_METERS_PER_MINUTE,
        "pick_min_per_line": PICK_MINUTES_PER_LINE,
        "pick_min_per_unit": PICK_MINUTES_PER_UNIT,
        "setup_min_per_wave": SETUP_MINUTES_PER_WAVE,
        "labor_cost_per_minute": LABOR_COST_PER_MINUTE,
    }
    payload = {
        "dataset": dataset,
        "seeds": seeds,
        "settings": {
            "orders": args.orders,
            "max_lines": args.max_lines,
            "stock_factor": args.stock_factor,
            "seed": args.seed,
            "plans": plan_keys,
            "pickers": args.pickers,
            "shift_minutes": args.shift_minutes,
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "service_late_weight": args.service_late_weight,
            "service_otif_bonus": args.service_otif_bonus,
            "pick_overload_penalty": args.pick_overload_penalty,
            "noise_sigma": args.noise_sigma,
            "severe_sigma": args.severe_sigma,
        },
        "plans": plan_rows,
        "allocations": [
            {
                "key": plan.key,
                "label": plan.label,
                "status": allocations[plan.key].status,
                "fill": allocations[plan.key].unit_fill_rate,
                "tickets": plan_tickets[plan.key],
                "alloc_otif_rate": allocations[plan.key].otif_rate,
                "alloc_cost": allocations[plan.key].total_cost,
                "solve_seconds": allocations[plan.key].solve_seconds,
                "gap": allocations[plan.key].gap,
            }
            for plan in plans
        ],
        "cells": [
            {
                "key": cell.key,
                "label": cell.label,
                "policy": cell.policy,
                "profile": cell.profile_label,
                "duration_noise": cell.duration_noise,
                "pickers_per_dc": cell.pickers_per_dc,
            }
            for cell in cells
        ],
        "summary": summary.to_dict("records"),
        "over_shift": over.to_dict("records"),
        "dc_workload": dc_rows,
        "declared_assumptions": list(first_instance.meta.get("assumptions", []))
        + [
            "库存总量固定，只改变各 DC 的库存占比；每 SKU 按最大余数法拆分并带确定性抖动",
            "每个布点重新求解分单 MILP，布点差异与求解器差异混合",
            "所有布点共享同一订单集、到达种子与拥堵 σ，但分单可行集不同，不能做逐种子配对",
        ],
    }
    paths = write_stock_deployment_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
