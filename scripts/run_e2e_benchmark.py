"""Week 9 benchmark: allocation -> per-DC wave picking -> online release.

Chains the Week-5 multi-DC allocation into the Week-6/7 pick-ticket build and
the Week-8 online release. The end-to-end OTIF requires the order to be fully
shipped on time *and* every pick ticket to finish before its cutoff.

Scenarios compare greedy, cost MILP, service MILP and a pick-capacity-aware
MILP. The load-aware allocation is then replayed under every release policy
and under 1/2/3 pickers per DC.

Usage:
    PYTHONPATH=src;. python scripts/run_e2e_benchmark.py
    PYTHONPATH=src;. python scripts/run_e2e_benchmark.py --orders 100 --milp-time 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data.online_retail import (  # noqa: E402
    clean_transactions,
    load_online_retail_raw,
    load_panel,
)
from supply.e2e import (  # noqa: E402
    POLICY_LABELS,
    PROMISE_TIER,
    TIER_CUTOFFS,
    build_e2e_instance,
    e2e_dc_table,
    run_pick_layer,
    write_e2e_report,
)
from supply.fulfillment import (  # noqa: E402
    FulfillmentResult,
    allocate_greedy,
    allocate_milp,
)
from supply.wave.instances import (  # noqa: E402
    LABOR_COST_PER_MINUTE,
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_UNIT,
    SETUP_MINUTES_PER_WAVE,
    TRAVEL_METERS_PER_MINUTE,
)

SCENARIO_LABELS = {
    "greedy": "贪心分单（截止期优先）",
    "milp_cost": "MILP 成本最优",
    "milp_service": "MILP 服务优先",
    "milp_load": "MILP 拣选容量感知",
}
PICK_DEADLINES = {days: TIER_CUTOFFS[tier] for days, tier in PROMISE_TIER.items()}


def _row(key: str, result) -> Dict[str, object]:
    return {
        "key": key,
        "name": result.name,
        "policy": result.policy,
        "pick_status": result.allocation.status,
        "solve_seconds": result.allocation.solve_seconds,
        "gap": result.allocation.gap,
        "best_bound": result.allocation.best_bound,
        **result.metrics,
    }


def _allocations(instance, args) -> Dict[str, FulfillmentResult]:
    fulfillment = instance.fulfillment
    greedy = allocate_greedy(fulfillment, max_splits=2)
    cost = allocate_milp(
        fulfillment,
        max_splits=2,
        time_limit_seconds=args.milp_time,
        workers=args.workers,
        name=SCENARIO_LABELS["milp_cost"],
    )
    service = allocate_milp(
        fulfillment,
        max_splits=2,
        time_limit_seconds=args.milp_time,
        workers=args.workers,
        late_penalty_per_unit_day=fulfillment.late_penalty_per_unit_day
        * args.service_late_weight,
        otif_bonus=args.service_otif_bonus,
        name=SCENARIO_LABELS["milp_service"],
    )
    load = allocate_milp(
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
        name=SCENARIO_LABELS["milp_load"],
    )
    return {"greedy": greedy, "milp_cost": cost, "milp_service": service, "milp_load": load}


def _release_sweep(instance, allocation, args) -> List[Dict[str, object]]:
    wait_label = (
        f"在线节省 + 等待凑波（{args.wait_minutes:.0f} min / ≥{args.min_fill} 单）"
    )
    plans = {
        "single": ("single", POLICY_LABELS["single"]),
        "edf": ("edf", POLICY_LABELS["edf"]),
        "savings": ("savings", POLICY_LABELS["savings"]),
        "savings_wait": ("savings_wait", wait_label),
    }
    rows: List[Dict[str, object]] = []
    for key, (policy, label) in plans.items():
        result = run_pick_layer(
            instance,
            allocation,
            scenario=f"milp_load · {label}",
            policy=policy,
            wait_minutes=args.wait_minutes,
            min_fill=args.min_fill,
            pickers_per_dc=args.pickers,
            name=label,
        )
        rows.append(_row(key, result))
    return rows


def _picker_sweep(instance, allocation, args) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for pickers in sorted(set(args.picker_sweep) | {args.pickers}):
        result = run_pick_layer(
            instance,
            allocation,
            scenario=f"milp_load · {pickers} picker(s)/DC",
            policy=args.policy,
            wait_minutes=args.wait_minutes,
            min_fill=args.min_fill,
            pickers_per_dc=pickers,
            name=f"每 DC {pickers} 名拣货员",
        )
        rows.append(_row(f"pickers_{pickers}", result))
    return rows


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Week 9 end-to-end fulfillment benchmark")
    parser.add_argument("--xlsx", default=str(ROOT / "data/raw/online_retail_II.xlsx"))
    parser.add_argument(
        "--raw-cache", default=str(ROOT / "data/raw/online_retail_II.raw.parquet")
    )
    parser.add_argument(
        "--panel", default=str(ROOT / "data/processed/online_retail_ii_weekly.parquet")
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--orders", type=int, default=400)
    parser.add_argument("--max-lines", type=int, default=20)
    parser.add_argument("--stock-factor", type=float, default=0.85)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--arrival-seed", type=int, default=42)
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--picker-sweep", type=int, nargs="+", default=[2, 3])
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--policy", default="edf", choices=sorted(POLICY_LABELS))
    parser.add_argument("--wait-minutes", type=float, default=15.0)
    parser.add_argument("--min-fill", type=int, default=4)
    parser.add_argument("--milp-time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument(
        "--title", default="End-to-end fulfillment benchmark (Week 9)"
    )
    args = parser.parse_args()

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)

    instance = build_e2e_instance(
        clean,
        skus,
        sample_orders=args.orders,
        max_lines=args.max_lines,
        stock_factor=args.stock_factor,
        seed=args.seed,
        week=last_week,
        pickers_per_dc=args.pickers,
        shift_minutes=args.shift_minutes,
        arrival_seed=args.arrival_seed,
    )

    print("=" * 100)
    print(args.title)
    print("=" * 100)
    print(
        f"orders {instance.meta['orders']} | lines {instance.meta['order_lines']} | "
        f"units {instance.meta['units']:,} | SKUs {instance.meta['skus']} | "
        f"stock coverage {instance.meta['stock_coverage']:.1%} | "
        f"pickers/DC {args.pickers} | shift {args.shift_minutes:.0f} min"
    )
    print(
        f"promise cutoffs {PICK_DEADLINES} | onsite {instance.pick.onsite_orders} | "
        f"mid-shift {instance.pick.mid_shift_orders}"
    )

    allocations = _allocations(instance, args)
    results = {
        key: run_pick_layer(
            instance,
            allocation,
            scenario=SCENARIO_LABELS[key],
            policy=args.policy,
            wait_minutes=args.wait_minutes,
            min_fill=args.min_fill,
            pickers_per_dc=args.pickers,
        )
        for key, allocation in allocations.items()
    }
    scenarios = [_row(key, result) for key, result in results.items()]

    print("\nScenario comparison:")
    print(
        pd.DataFrame(scenarios)[
            [
                "name",
                "pick_status",
                "alloc_otif_rate",
                "e2e_otif_rate",
                "pick_on_time_rate",
                "pick_loss_orders",
                "tickets",
                "waves",
                "labor_per_ticket",
                "alloc_cost",
                "total_cost",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    load_allocation = allocations["milp_load"]
    dc_workload = [
        {"key": "milp_load", **row}
        for row in e2e_dc_table(results["milp_load"])
    ]
    print("\nPer-DC workload — pick-capacity-aware allocation:")
    print(
        pd.DataFrame(dc_workload)[
            ["dc", "tickets", "orders", "waves", "labor_minutes", "on_time_tickets", "tardy_tickets", "makespan"]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    release = _release_sweep(instance, load_allocation, args)
    print("\nRelease-policy sweep — pick-capacity-aware allocation:")
    print(
        pd.DataFrame(release)[
            [
                "name",
                "waves",
                "labor_per_ticket",
                "pick_on_time_rate",
                "pick_tardiness",
                "pick_makespan",
                "e2e_otif_rate",
                "total_cost",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    pickers = _picker_sweep(instance, load_allocation, args)
    print("\nPicker sensitivity — pick-capacity-aware allocation:")
    print(
        pd.DataFrame(pickers)[
            [
                "name",
                "alloc_otif_rate",
                "pick_on_time_rate",
                "e2e_otif_rate",
                "pick_loss_orders",
                "waves",
                "pick_labor_minutes",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    dataset = {
        **instance.meta,
        "lines": instance.meta["order_lines"],
        "dcs": len(instance.meta.get("dcs", [])),
        "max_orders_per_wave": instance.max_orders,
        "max_lines_per_wave": instance.max_lines,
        "travel_m_per_minute": TRAVEL_METERS_PER_MINUTE,
        "pick_min_per_line": PICK_MINUTES_PER_LINE,
        "pick_min_per_unit": PICK_MINUTES_PER_UNIT,
        "setup_min_per_wave": SETUP_MINUTES_PER_WAVE,
        "labor_cost_per_minute": LABOR_COST_PER_MINUTE,
        "clean_rows": clean_stats["clean_rows"],
        "period_start": str(last_week.date() - pd.Timedelta(weeks=51)),
        "period_end": str(last_week.date()),
    }
    payload = {
        "dataset": dataset,
        "settings": {
            "orders": args.orders,
            "max_lines": args.max_lines,
            "stock_factor": args.stock_factor,
            "seed": args.seed,
            "arrival_seed": args.arrival_seed,
            "pickers": args.pickers,
            "picker_sweep": args.picker_sweep,
            "shift_minutes": args.shift_minutes,
            "policy": args.policy,
            "policy_label": POLICY_LABELS[args.policy],
            "wait_minutes": args.wait_minutes,
            "min_fill": args.min_fill,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "service_late_weight": args.service_late_weight,
            "service_otif_bonus": args.service_otif_bonus,
            "pick_overload_penalty": args.pick_overload_penalty,
            "pick_deadlines": PICK_DEADLINES,
        },
        "scenarios": scenarios,
        "dc_workload": dc_workload,
        "release": release,
        "picker_sensitivity": pickers,
        "assumptions": instance.meta.get("assumptions", []),
    }
    paths = write_e2e_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
