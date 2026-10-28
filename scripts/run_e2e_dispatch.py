"""Week 16 benchmark: outbound dispatch, carrier cutoffs and consolidation.

The allocation, stock, layout and pick simulation are the Week-9/15 chain.
This benchmark adds the dock: tickets finish picking, wait for a truck, and
are scored against the customer promise at delivery instead of at the pick
cutoff. It compares:

* ``pick_control``: Week-15 scoring, no outbound layer;
* ``dock_two_immediate`` / ``dock_two_hold6`` / ``dock_two_promise6`` /
  ``dock_two_promise10``: 13:00 + 19:00 departures with different holding rules;
* ``dock_single_13`` / ``dock_single_15`` / ``dock_single_19``: one departure
  per day, testing how much buffer the carrier cutoff carries;
* ``dock_promise6_noise`` and ``dock_promise6_pickers2``: the Week-15
  robustness axes applied to the dock policy.

Every cell shares one allocation and one empirical arrival curve per seed, so
the paired differences isolate the outbound layer.
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
    DispatchCell,
    build_e2e_instance,
    capacity_aware_allocation,
    fit_empirical_arrivals,
    lane_summary,
    paired_delta,
    run_dispatch_cell,
    run_dispatch_monte_carlo,
    summarize_runs,
    write_dispatch_report,
)

SCENARIO_KEY = "milp_load"
SCENARIO_LABEL = "MILP 拣选容量感知（Week-9 分单）"
SUMMARY_METRICS = [
    "dock_otif_rate",
    "pick_otif_rate",
    "dock_delta_orders",
    "departures",
    "orders_per_departure",
    "mean_wait_minutes",
    "p90_wait_minutes",
    "roll_rate",
    "dispatch_cost",
    "holding_cost",
    "dock_cost",
]
SHIFT_START_HOUR = 8


def _clock(minute: float) -> str:
    return f"{int(minute) // 60 + SHIFT_START_HOUR:02d}:{int(minute) % 60:02d}"


def _cells(args) -> list[DispatchCell]:
    two = (300.0, 660.0)
    dock = dict(
        load_minutes=args.load_minutes,
        max_hold_minutes=args.max_hold_hours * 60.0,
        dispatch_cost=args.dispatch_cost,
        holding_cost_per_order_hour=args.holding_cost,
    )
    return [
        DispatchCell(
            "pick_control",
            "仅拣选截单（Week-15 口径）",
            policy="none",
        ),
        DispatchCell(
            "dock_two_immediate",
            f"双班 {_clock(300)}/{_clock(660)} · 即时发车",
            policy="immediate",
            departures=two,
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_two_hold6",
            f"双班 · 凑 {args.min_load} 单/日终",
            policy="hold",
            min_load=args.min_load,
            departures=two,
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_two_promise6",
            f"双班 · 承诺感知 {args.min_load} 单",
            policy="promise",
            min_load=args.min_load,
            departures=two,
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_two_promise10",
            f"双班 · 承诺感知 {args.min_load + 4} 单",
            policy="promise",
            min_load=args.min_load + 4,
            departures=two,
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_single_13",
            f"单班 {_clock(300)} · 即时发车",
            policy="immediate",
            departures=(300.0,),
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_single_15",
            f"单班 {_clock(420)} · 即时发车",
            policy="immediate",
            departures=(420.0,),
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_single_19",
            f"单班 {_clock(660)} · 即时发车",
            policy="immediate",
            departures=(660.0,),
            capacity=args.capacity,
            **dock,
        ),
        DispatchCell(
            "dock_promise6_noise",
            f"承诺感知 {args.min_load} 单 · 噪声 σ={args.noise_sigma:.2f}",
            policy="promise",
            min_load=args.min_load,
            departures=two,
            capacity=args.capacity,
            **dock,
            duration_noise=args.noise_sigma,
        ),
        DispatchCell(
            "dock_promise6_pickers2",
            f"承诺感知 {args.min_load} 单 · 加 1 名拣货员/DC",
            policy="promise",
            min_load=args.min_load,
            departures=two,
            capacity=args.capacity,
            **dock,
            pickers_per_dc=args.pickers + 1,
        ),
    ]


def _paired_rows(frame: pd.DataFrame) -> list[dict]:
    comparisons = [
        ("pick_control", "dock_two_immediate"),
        ("dock_two_immediate", "dock_two_hold6"),
        ("dock_two_hold6", "dock_two_promise6"),
        ("dock_two_immediate", "dock_two_promise10"),
        ("dock_two_immediate", "dock_single_13"),
        ("dock_two_immediate", "dock_single_15"),
        ("dock_two_immediate", "dock_single_19"),
        ("dock_two_promise6", "dock_promise6_noise"),
        ("dock_two_promise6", "dock_promise6_pickers2"),
    ]
    frames = [
        paired_delta(frame, left, right, metric="dock_otif_rate")
        for left, right in comparisons
    ]
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 16 outbound dispatch and carrier-cutoff benchmark"
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
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--service-time", type=float, default=30.0)
    parser.add_argument("--milp-time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--min-load", type=int, default=6)
    parser.add_argument("--capacity", type=int, default=300)
    parser.add_argument("--load-minutes", type=float, default=30.0)
    parser.add_argument("--dispatch-cost", type=float, default=220.0)
    parser.add_argument("--holding-cost", type=float, default=0.15)
    parser.add_argument("--max-hold-hours", type=float, default=24.0)
    parser.add_argument(
        "--title",
        default="Outbound dispatch and carrier cutoffs (Week 16)",
    )
    args = parser.parse_args()
    if args.seeds < 1:
        raise ValueError("--seeds 必须 >= 1")
    if args.min_load < 1:
        raise ValueError("--min-load 必须 >= 1")
    if args.capacity < 1:
        raise ValueError("--capacity 必须 >= 1")

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
        f"seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) | cells {len(cells)} | "
        f"dock departures 13:00/19:00 | min load {args.min_load} | "
        f"truck ceiling {args.capacity} orders"
    )

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
    arrivals = fit_empirical_arrivals(
        clean, last_week, lookback_weeks=args.lookback_weeks
    )
    print(f"\nempirical curves: {len(arrivals)} prior weeks")

    print(f"\n[{SCENARIO_KEY}] solving capacity-aware allocation ...")
    allocation = capacity_aware_allocation(
        instance,
        service_time=args.service_time,
        milp_time=args.milp_time,
        workers=args.workers,
        service_late_weight=args.service_late_weight,
        service_otif_bonus=args.service_otif_bonus,
        pick_overload_penalty=args.pick_overload_penalty,
    )
    print(
        f"  {allocation.status} | fill {allocation.unit_fill_rate:.1%} | "
        f"alloc OTIF {allocation.otif_rate:.1%} | "
        f"cost €{allocation.total_cost:,.0f} | solve {allocation.solve_seconds:.1f}s"
    )

    frame = run_dispatch_monte_carlo(
        instance, allocation, cells, seeds, arrivals, scenario=SCENARIO_KEY
    )
    summary = summarize_runs(frame, metrics=SUMMARY_METRICS)
    paired = _paired_rows(frame)

    dock = summary[summary["metric"] == "dock_otif_rate"]
    print("\nDock OTIF by cell:")
    print(
        dock[["cell_label", "n", "mean", "ci95", "p10", "p90", "tail10"]].to_string(
            index=False, float_format=lambda value: f"{value:,.4f}"
        )
    )
    print("\nPaired differences (dock OTIF, right - left):")
    print(
        paired[["left", "right", "mean_delta", "ci95", "win_rate", "loss_rate"]].to_string(
            index=False, float_format=lambda value: f"{value:,.4f}"
        )
    )

    promise_cell = next(cell for cell in cells if cell.key == "dock_two_promise6")
    _, outcome = run_dispatch_cell(
        instance, allocation, promise_cell, seeds[0], arrivals
    )
    lanes = lane_summary(outcome).to_dict("records") if outcome is not None else []

    allocation_row = {
        "key": SCENARIO_KEY,
        "label": SCENARIO_LABEL,
        "status": allocation.status,
        "fill": allocation.unit_fill_rate,
        "otif_rate": allocation.otif_rate,
        "alloc_cost": allocation.total_cost,
        "solve_seconds": allocation.solve_seconds,
    }
    payload = {
        "dataset": {
            **instance.meta,
            "orders": instance.n_orders,
            "lines": instance.meta["order_lines"],
            "units": int(instance.fulfillment.line_qty.sum()),
            "week": str(last_week.date()),
            "pickers_per_dc": args.pickers,
            "shift_minutes": args.shift_minutes,
            "max_orders": instance.max_orders,
            "max_lines": instance.max_lines,
            "clean_rows": clean_stats["clean_rows"],
            "dcs": list(instance.fulfillment.dc_names),
        },
        "seeds": seeds,
        "cells": [cell.as_dict() for cell in cells],
        "settings": {
            "orders": args.orders,
            "max_lines": args.max_lines,
            "stock_factor": args.stock_factor,
            "seed": args.seed,
            "pickers": args.pickers,
            "shift_minutes": args.shift_minutes,
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "lookback_weeks": args.lookback_weeks,
            "noise_sigma": args.noise_sigma,
            "min_load": args.min_load,
            "capacity": args.capacity,
            "load_minutes": args.load_minutes,
            "dispatch_cost": args.dispatch_cost,
            "holding_cost": args.holding_cost,
            "max_hold_hours": args.max_hold_hours,
        },
        "allocation": allocation_row,
        "summary": summary.to_dict("records"),
        "paired": paired.to_dict("records"),
        "lanes": lanes,
        "limitations": [
            "发车时刻、装车提前量、车道划分、车辆上限与月台费率是声明值，公开数据中没有承运商时刻表。",
            "承诺截止日由 Week-8 的承诺与转运几何推导，不是承运商 SLA；转运日按距离每 700 km 一天取整。",
            "拣选完成时间来自仿真的班次时钟，不是仓库扫描时间；月台装卸、门位与司机等待未建模。",
            "每个 DC×目的国视为一条车道，未建模多站路由、承运商体积上限与预约时段。",
            "分单固定为 Week-9 容量感知 MILP，库存与订单集在所有格之间不变，因此只隔离出库层。",
            "月台成本（€220/车 + €0.15/单·小时）是规划代理，不含已经在分单运输成本中的干线变动费用。",
        ],
    }

    out_dir = Path(args.out_dir)
    paths = write_dispatch_report(payload, out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
