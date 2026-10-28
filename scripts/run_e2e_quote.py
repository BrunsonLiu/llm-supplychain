"""Week 18 benchmark: promise quoting (ATP) and the promise-service frontier.

The order set, stock snapshot, layout and empirical arrivals are the Week-15
chain. This benchmark replaces the random 2/3/5-day promise with a quoting
policy, re-solves the capacity-aware allocation for each policy, and scores
every cell twice:

* ``quoted_otif``: delivered on or before the promise the policy quoted;
* ``static_sla_otif``: delivered on or before the Week-15 baseline promise,
  a common SLA that makes delivery speed comparable across policies.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
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
    QuoteCell,
    build_e2e_instance,
    fit_empirical_arrivals,
    paired_delta,
    quote_frontier,
    quote_promises,
    rebuild_pick_plan,
    run_quote_monte_carlo,
    solve_quote,
    summarize_runs,
    write_quote_report,
)

SCENARIO_KEY = "milp_load"
SUMMARY_METRICS = [
    "quoted_otif_rate",
    "static_sla_otif_rate",
    "avg_promise_days",
    "fast_share",
    "slow_share",
    "fill_rate",
    "alloc_otif_rate",
    "pick_otif_rate",
    "late_orders",
    "mean_delivered_day",
    "dock_cost",
    "departures",
]


def _dock_cell(key: str, label: str, **overrides) -> DispatchCell:
    base = dict(
        policy="immediate",
        departures=(300.0, 660.0),
        capacity=300,
        load_minutes=30.0,
        max_hold_minutes=1440.0,
        dispatch_cost=220.0,
        holding_cost_per_order_hour=0.15,
    )
    base.update(overrides)
    return DispatchCell(key, label, **base)


def _cells(args) -> list[QuoteCell]:
    return [
        QuoteCell(
            "static",
            "固定 2/3/5 混合（Week-15 基线）",
            "static",
            _dock_cell("static_dock", "固定承诺", capacity=args.capacity),
        ),
        QuoteCell(
            "atp",
            "ATP：按库存与转运日报最快层",
            "atp",
            _dock_cell("atp_dock", "ATP", capacity=args.capacity),
        ),
        QuoteCell(
            "atp_fixed_priority",
            "ATP · 沿用基线截单优先级",
            "atp",
            _dock_cell("fixed_dock", "ATP+固定优先级", capacity=args.capacity),
            keep_cutoffs=True,
        ),
        QuoteCell(
            "atp_buffer",
            "ATP + 1 天缓冲",
            "atp_buffer",
            _dock_cell("buffer_dock", "ATP+1", capacity=args.capacity),
        ),
        QuoteCell(
            "atp_cap2",
            "ATP 封顶 2 天",
            "atp_cap2",
            _dock_cell("cap2_dock", "ATP≤2", capacity=args.capacity),
        ),
        QuoteCell(
            "atp_cap3",
            "ATP 封顶 3 天",
            "atp_cap3",
            _dock_cell("cap3_dock", "ATP≤3", capacity=args.capacity),
        ),
        QuoteCell(
            "all_2",
            "全部报 2 天",
            "all_2",
            _dock_cell("all2_dock", "全 2 天", capacity=args.capacity),
        ),
        QuoteCell(
            "all_3",
            "全部报 3 天",
            "all_3",
            _dock_cell("all3_dock", "全 3 天", capacity=args.capacity),
        ),
        QuoteCell(
            "all_5",
            "全部报 5 天",
            "all_5",
            _dock_cell("all5_dock", "全 5 天", capacity=args.capacity),
        ),
        QuoteCell(
            "atp_pickers2",
            "ATP · 加 1 名拣货员/DC",
            "atp",
            _dock_cell(
                "pickers_dock",
                "ATP+人",
                capacity=args.capacity,
                pickers_per_dc=args.pickers + 1,
            ),
        ),
        QuoteCell(
            "atp_noise",
            f"ATP · 拣选噪声 σ={args.noise_sigma:.2f}",
            "atp",
            _dock_cell(
                "noise_dock",
                "ATP+噪声",
                capacity=args.capacity,
                duration_noise=args.noise_sigma,
            ),
        ),
    ]


def _paired_rows(frame: pd.DataFrame, cells: list[QuoteCell]) -> pd.DataFrame:
    keys = [cell.key for cell in cells]
    comparisons = [("static", key) for key in keys if key != "static"]
    rows = []
    for metric in ("quoted_otif_rate", "static_sla_otif_rate"):
        for left, right in comparisons:
            row = paired_delta(frame, left, right, metric=metric)
            row["metric"] = metric
            rows.append(row)
    return pd.concat(rows, ignore_index=True)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 18 promise quoting (ATP) benchmark"
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
    parser.add_argument("--milp-time", type=float, default=45.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--capacity", type=int, default=300)
    parser.add_argument(
        "--title", default="Promise quoting and the service frontier (Week 18)"
    )
    args = parser.parse_args()
    if args.seeds < 1:
        raise ValueError("--seeds 必须 >= 1")
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
        f"orders {args.orders} | seeds {len(seeds)} | cells {len(cells)} | "
        f"milp {args.milp_time:.0f}s/policy | capacity {args.capacity}"
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
    baseline = instance.fulfillment.promise_days.astype(int).copy()
    print(
        f"baseline promises: avg {baseline.mean():.2f} d | "
        f"2-day {np.mean(baseline == 2):.1%} | 5-day {np.mean(baseline == 5):.1%}"
    )

    frames = []
    allocations = {}
    solved = {}
    for cell in cells:
        promises = quote_promises(instance, cell.quote)
        key = tuple(int(value) for value in promises)
        if key not in solved:
            quoted, allocation = solve_quote(
                instance,
                cell.quote,
                service_time=args.service_time,
                milp_time=args.milp_time,
                workers=args.workers,
                service_late_weight=args.service_late_weight,
                service_otif_bonus=args.service_otif_bonus,
                pick_overload_penalty=args.pick_overload_penalty,
            )
            solved[key] = (quoted, allocation)
        else:
            quoted, allocation = solved[key]
        if cell.keep_cutoffs:
            quoted = rebuild_pick_plan(
                instance,
                promises,
                keep_cutoffs=True,
            )
        allocations[cell.key] = allocation
        frame = run_quote_monte_carlo(
            quoted, allocation, cell, seeds, arrivals, baseline, scenario=SCENARIO_KEY
        )
        frames.append(frame)
        print(
            f"  {cell.key:<12} avg promise {quoted.fulfillment.promise_days.mean():.2f} | "
            f"fill {allocation.unit_fill_rate:.1%} | alloc OTIF {allocation.otif_rate:.1%} | "
            f"quoted OTIF {frame['quoted_otif_rate'].mean():.1%} | "
            f"static-SLA {frame['static_sla_otif_rate'].mean():.1%}"
        )

    frame = pd.concat(frames, ignore_index=True)
    frontier = quote_frontier(frame)
    summary = summarize_runs(frame, metrics=SUMMARY_METRICS)
    paired = _paired_rows(frame, cells)

    print("\nPromise frontier:")
    print(
        frontier[
            [
                "label",
                "avg_promise_days",
                "fast_share",
                "quoted_otif_rate",
                "static_sla_otif_rate",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.4f}")
    )

    allocation_rows = [
        {
            "cell": cell.key,
            "label": cell.label,
            "quote": cell.quote,
            "status": allocations[cell.key].status,
            "fill": allocations[cell.key].unit_fill_rate,
            "otif_rate": allocations[cell.key].otif_rate,
            "alloc_cost": allocations[cell.key].total_cost,
            "solve_seconds": allocations[cell.key].solve_seconds,
            "avg_promise_days": float(
                frame.loc[frame["cell"] == cell.key, "avg_promise_days"].mean()
            ),
            "fast_share": float(
                frame.loc[frame["cell"] == cell.key, "fast_share"].mean()
            ),
        }
        for cell in cells
    ]

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
        "cells": [
            cell.dispatch.as_dict()
            | {
                "quote": cell.quote,
                "key": cell.key,
                "label": cell.label,
                "keep_cutoffs": cell.keep_cutoffs,
            }
            for cell in cells
        ],
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
            "capacity": args.capacity,
        },
        "baseline": {
            "avg_promise_days": float(baseline.mean()),
            "fast_share": float(np.mean(baseline == 2)),
            "slow_share": float(np.mean(baseline == 5)),
        },
        "allocations": allocation_rows,
        "frontier": frontier.to_dict("records"),
        "summary": summary.to_dict("records"),
        "paired": paired.to_dict("records"),
        "limitations": [
            "ATP 报价只用当前库存快照与声明转运日，不考虑未来补货、订单之间的库存竞争与取消/改单。",
            "承诺只允许 2/3/5 天三档；1 天与 4 天被并入相邻档，报价粒度是声明值。",
            "每个不同的承诺向量重解一次 Week-9 容量感知 MILP；相同承诺向量的回放格共享同一分单（所以封顶/缓冲会退化成对应的统一报价）。求解器时间预算内的差异仍会混入 static 与 ATP 的差异。",
            "报价改变截单层，但到达分钟固定为基线抽样，以隔离“报价/截单”而不是“到达时机”的变化。",
            "static-SLA 用 Week-15 基线承诺作为共同 SLA，只衡量送达速度，不代表客户真实可接受时效。",
            "库存、转运日、DC 产能与订单集都是声明/固定值，只验证一个目标周，绝对 OTIF 不可迁移。",
        ],
    }

    out_dir = Path(args.out_dir)
    paths = write_quote_report(payload, out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
