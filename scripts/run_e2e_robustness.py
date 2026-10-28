"""Week 10 benchmark: Monte Carlo robustness of the end-to-end chain.

Week 9 reports one arrival draw with deterministic pick minutes. This script
replays the same allocation over many arrival seeds and stress axes (arrival
spike, pick-time congestion, extra picker) to produce confidence intervals,
tail risk and paired policy comparisons.

The allocation set is fixed per scenario: greedy, service-weighted and
pick-capacity-aware. Only execution randomness is resampled.

Usage:
    PYTHONPATH=src;. python scripts/run_e2e_robustness.py
    PYTHONPATH=src;. python scripts/run_e2e_robustness.py --orders 100 --seeds 8 --milp-time 5
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
    DEFAULT_ARRIVAL_PROFILE,
    PROMISE_TIER,
    TIER_CUTOFFS,
    StressCell,
    build_e2e_instance,
    over_shift_rate,
    paired_delta,
    run_monte_carlo,
    summarize_runs,
    write_robustness_report,
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
    "milp_service": "MILP 服务优先",
    "milp_load": "MILP 拣选容量感知",
}
PICK_DEADLINES = {days: TIER_CUTOFFS[tier] for days, tier in PROMISE_TIER.items()}


def _allocations(instance, args) -> dict[str, FulfillmentResult]:
    fulfillment = instance.fulfillment
    greedy = allocate_greedy(fulfillment, max_splits=2)
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
    return {"greedy": greedy, "milp_service": service, "milp_load": load}


def _cells(args) -> list[StressCell]:
    spike = {
        "spike_share": args.spike_share,
        "spike_center": args.spike_center,
        "spike_width": args.spike_width,
    }
    base_pickers = args.pickers
    return [
        StressCell("base", "基准：均匀到达 · 确定性", "edf", None, 0.0, base_pickers),
        StressCell(
            "savings", "节省重批 · 均匀到达", "savings", None, 0.0, base_pickers
        ),
        StressCell("peak", "到达尖峰 · 确定性", "edf", spike, 0.0, base_pickers),
        StressCell(
            "peak_savings",
            "到达尖峰 · 节省重批",
            "savings",
            spike,
            0.0,
            base_pickers,
        ),
        StressCell(
            "noise", f"拣选噪声 σ={args.noise_sigma:.2f}", "edf", None, args.noise_sigma, base_pickers
        ),
        StressCell(
            "peak_noise",
            f"尖峰 + 噪声 σ={args.noise_sigma:.2f}",
            "edf",
            spike,
            args.noise_sigma,
            base_pickers,
        ),
        StressCell(
            "severe",
            f"重度拥堵 σ={args.severe_sigma:.2f}",
            "edf",
            None,
            args.severe_sigma,
            base_pickers,
        ),
        StressCell(
            "two_pickers",
            "加 1 名拣货员/DC · 均匀到达",
            "edf",
            None,
            0.0,
            base_pickers + 1,
        ),
    ]


def _paired_rows(frame: pd.DataFrame, cells: list[StressCell]) -> dict[str, list]:
    def one(left: str, right: str, metric: str, label: str):
        table = paired_delta(frame, left, right, metric=metric)
        if table.empty:
            return []
        table = table.copy()
        table["comparison"] = label
        return table.to_dict("records")

    metrics = ("e2e_otif_rate", "pick_tardiness", "pick_makespan")
    paired = {
        "savings_vs_edf": [
            row
            for metric in metrics
            for row in one("base", "savings", metric, "均匀到达：节省 − EDF")
            + one("peak", "peak_savings", metric, "尖峰到达：节省 − EDF")
        ],
        "peak_vs_base": [
            row for metric in metrics for row in one("base", "peak", metric, "尖峰 − 均匀")
        ],
        "noise_vs_base": [
            row for metric in metrics for row in one("base", "noise", metric, "含噪声 − 确定性")
        ],
        "severe_vs_base": [
            row for metric in metrics for row in one("base", "severe", metric, "重度拥堵 − 确定性")
        ],
        "capacity_vs_base": [
            row
            for metric in metrics
            for row in one("base", "two_pickers", metric, "2 名 − 1 名")
        ],
    }
    return paired


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 10 end-to-end robustness benchmark"
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
        "--seeds",
        type=int,
        default=30,
        help="number of arrival seeds, drawn as 1..N",
    )
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--milp-time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--severe-sigma", type=float, default=0.40)
    parser.add_argument(
        "--spike-share", type=float, default=DEFAULT_ARRIVAL_PROFILE["spike_share"]
    )
    parser.add_argument(
        "--spike-center", type=float, default=DEFAULT_ARRIVAL_PROFILE["spike_center"]
    )
    parser.add_argument(
        "--spike-width", type=float, default=DEFAULT_ARRIVAL_PROFILE["spike_width"]
    )
    parser.add_argument(
        "--title", default="End-to-end robustness benchmark (Week 10)"
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
        arrival_seed=1,
    )

    print("=" * 110)
    print(args.title)
    print("=" * 110)
    print(
        f"orders {instance.meta['orders']} | lines {instance.meta['order_lines']} | "
        f"units {instance.meta['units']:,} | SKUs {instance.meta['skus']} | "
        f"stock coverage {instance.meta['stock_coverage']:.1%} | "
        f"pickers/DC {args.pickers} | shift {args.shift_minutes:.0f} min"
    )
    seeds = list(range(1, args.seeds + 1))
    cells = _cells(args)
    print(
        f"seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) | stress cells {len(cells)} | "
        f"noise σ {args.noise_sigma:.2f}/{args.severe_sigma:.2f}"
    )

    allocations = _allocations(instance, args)
    print("\nAllocations:")
    print(
        pd.DataFrame(
            [
                {
                    "scenario": key,
                    "status": allocation.status,
                    "fill": allocation.unit_fill_rate,
                    "alloc OTIF": allocation.otif_rate,
                    "cost": allocation.total_cost,
                    "gap": allocation.gap,
                    "solve s": allocation.solve_seconds,
                }
                for key, allocation in allocations.items()
            ]
        ).to_string(index=False, float_format=lambda value: f"{value:,.3f}")
    )

    print("\nRunning Monte Carlo ...")
    frame = run_monte_carlo(instance, allocations, cells, seeds)
    summary = summarize_runs(frame)
    over = over_shift_rate(frame, args.shift_minutes)
    paired = _paired_rows(frame, cells)

    otif = summary[summary["metric"] == "e2e_otif_rate"]
    print("\nEnd-to-end OTIF by allocation × stress cell:")
    print(
        otif[
            ["scenario", "cell_label", "mean", "ci95", "p10", "p50", "p90", "tail10"]
        ].to_string(index=False, float_format=lambda value: f"{value:,.4f}")
    )
    tardy = summary[summary["metric"] == "pick_tardiness"]
    print("\nLate-ticket minutes by allocation × stress cell:")
    print(
        tardy[["scenario", "cell_label", "mean", "p90", "tail10"]].to_string(
            index=False, float_format=lambda value: f"{value:,.1f}"
        )
    )
    if paired["savings_vs_edf"]:
        print("\nPaired savings-vs-EDF (E2E OTIF):")
        print(
            pd.DataFrame(
                [
                    row
                    for row in paired["savings_vs_edf"]
                    if row["metric"] == "e2e_otif_rate"
                ]
            )[
                ["scenario", "comparison", "mean_delta", "ci95", "win_rate", "loss_rate"]
            ].to_string(index=False, float_format=lambda value: f"{value:,.4f}")
        )

    dataset = {
        **instance.meta,
        "orders": instance.n_orders,
        "lines": instance.meta["order_lines"],
        "week": str(last_week.date()),
        "pickers_per_dc": args.pickers,
        "shift_minutes": args.shift_minutes,
        "max_orders": instance.max_orders,
        "max_lines": instance.max_lines,
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
            "pickers": args.pickers,
            "shift_minutes": args.shift_minutes,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "service_late_weight": args.service_late_weight,
            "service_otif_bonus": args.service_otif_bonus,
            "pick_overload_penalty": args.pick_overload_penalty,
            "noise_sigma": args.noise_sigma,
            "severe_sigma": args.severe_sigma,
            "spike": {
                "spike_share": args.spike_share,
                "spike_center": args.spike_center,
                "spike_width": args.spike_width,
            },
        },
        "allocations": [
            {
                "key": key,
                "label": SCENARIO_LABELS[key],
                "status": allocation.status,
                "alloc_otif_rate": allocation.otif_rate,
                "alloc_cost": allocation.total_cost,
                "solve_seconds": allocation.solve_seconds,
                "gap": allocation.gap,
            }
            for key, allocation in allocations.items()
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
        "paired": paired,
        "declared_assumptions": list(instance.meta.get("assumptions", []))
        + [
            "随机性只来自到达重抽样与拣选时长乘子，订单、库存、槽位与分单固定",
            "拥堵乘子 exp(σZ) 截断在 [0.5, 2.0]，σ 为声明值而非拟合值",
            "配对种子共享到达抽样；不同策略的拥堵抽样因波次结构不同而不同",
        ],
    }
    paths = write_robustness_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
