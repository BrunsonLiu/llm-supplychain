"""Week 15 benchmark: replay the E2E chain on empirical intraday arrivals.

Weeks 8-14 sampled mid-shift arrivals from a declared uniform window or a
declared relative spike. Online Retail II carries invoice timestamps, so the
intraday *shape* can be estimated from the last six weeks instead of asserted.
This benchmark keeps one Week-9 allocation and changes only execution:

* ``uniform_edf``: declared uniform arrival (Week-10 control);
* ``spike_edf`` / ``spike_savings``: declared spike (Week-10 control);
* ``empirical_mean_edf``: equal-weight mean of the prior-week curves;
* ``empirical_week_edf`` / ``_savings`` / ``_noise`` / ``_two_pickers``: one
  prior-week curve per seed, with the Week-10 policy, noise and picker axes.

The target week's own curve is a holdout: it is printed and compared with the
prior weeks, but never sampled for planning or evaluation.
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
    DEFAULT_ARRIVAL_PROFILE,
    CurveCell,
    build_e2e_instance,
    capacity_aware_allocation,
    cell_dict,
    curve_share_table,
    cutoff_coverage,
    fit_empirical_arrivals,
    over_shift_rate,
    paired_delta,
    rebuild_arrivals,
    arrival_timing,
    run_curve_monte_carlo,
    run_pick_layer,
    summarize_runs,
    write_empirical_report,
)
from supply.wave.instances import (  # noqa: E402
    LABOR_COST_PER_MINUTE,
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_UNIT,
    SETUP_MINUTES_PER_WAVE,
    TRAVEL_METERS_PER_MINUTE,
)

SCENARIO_KEY = "milp_load"
SCENARIO_LABEL = "MILP 拣选容量感知（Week-9 分单）"
CUTOFFS = (240, 480, 600)


def _cells(args) -> list[CurveCell]:
    spike = dict(DEFAULT_ARRIVAL_PROFILE)
    return [
        CurveCell(
            "uniform_edf",
            "均匀到达 · EDF（Week-10 对照）",
            arrival="uniform",
            policy="edf",
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "spike_edf",
            "声明尖峰 · EDF（Week-10 对照）",
            arrival="spike",
            policy="edf",
            profile=spike,
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "empirical_mean_edf",
            "前 6 周平均经验曲线 · EDF",
            arrival="mean",
            policy="edf",
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "empirical_week_edf",
            "逐周经验曲线 · EDF",
            arrival="empirical",
            policy="edf",
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "empirical_week_savings",
            "逐周经验曲线 · 节省重批",
            arrival="empirical",
            policy="savings",
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "spike_savings",
            "声明尖峰 · 节省重批",
            arrival="spike",
            policy="savings",
            profile=spike,
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "empirical_week_noise",
            f"逐周经验曲线 · 噪声 σ={args.noise_sigma:.2f}",
            arrival="empirical",
            policy="edf",
            duration_noise=args.noise_sigma,
            pickers_per_dc=args.pickers,
        ),
        CurveCell(
            "empirical_week_two_pickers",
            "逐周经验曲线 · 加 1 名拣货员/DC",
            arrival="empirical",
            policy="edf",
            pickers_per_dc=args.pickers + 1,
        ),
    ]


def _paired_rows(frame: pd.DataFrame) -> list[dict]:
    comparisons = [
        ("uniform_edf", "empirical_week_edf"),
        ("spike_edf", "empirical_week_edf"),
        ("empirical_mean_edf", "empirical_week_edf"),
        ("empirical_week_edf", "empirical_week_savings"),
        ("spike_edf", "spike_savings"),
        ("empirical_week_edf", "empirical_week_noise"),
        ("empirical_week_edf", "empirical_week_two_pickers"),
    ]
    frames = [paired_delta(frame, left, right) for left, right in comparisons]
    return pd.concat(frames, ignore_index=True)


def _dc_workload(instance, allocation, arrivals, seed: int) -> list[dict]:
    curve = arrivals.curve_for(seed)
    shifted = rebuild_arrivals(instance, seed, arrival_curve=curve)
    result = run_pick_layer(
        shifted,
        allocation,
        scenario=SCENARIO_KEY,
        policy="edf",
        pickers_per_dc=instance.pickers_per_dc,
    )
    return [
        {
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
        description="Week 15 empirical intraday arrival benchmark"
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
    parser.add_argument("--start-hour", type=int, default=8)
    parser.add_argument("--end-hour", type=int, default=18)
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument(
        "--title",
        default="Empirical intraday arrivals (Week 15)",
    )
    args = parser.parse_args()
    if args.seeds < 1:
        raise ValueError("--seeds 必须 >= 1")

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
        f"window {args.start_hour:02d}:00-{args.end_hour:02d}:00 Mon-Fri | "
        f"lookback {args.lookback_weeks} weeks"
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
        clean,
        last_week,
        lookback_weeks=args.lookback_weeks,
        start_hour=args.start_hour,
        end_hour=args.end_hour,
    )
    print(f"\nempirical curves: {len(arrivals)} prior weeks")
    for row in arrivals.rows:
        shares = row.get("shares") or ()
        peak = f"{row['peak_hour']:02d}:00" if row.get("peak_hour") else "—"
        print(
            f"  {row['week']} | weekday {row['lines_weekday']:,} | "
            f"in-window {row['lines_used']:,} ({row['coverage']:.1%}) | "
            f"peak {peak} | " + " ".join(f"{value:.2f}" for value in shares)
        )
    target = arrivals.diagnostics
    print(
        f"holdout curve: peak {target['target_peak_hour']:02d}:00 | "
        f"share after half {target['target_share_after_half']:.1%} | "
        f"L1 to prior mean {target['holdout_l1']:.3f} | "
        f"percentile {target['holdout_percentile']:.0%}"
    )

    coverage = cutoff_coverage(
        arrivals.target, CUTOFFS, args.shift_minutes
    )
    mean_coverage = cutoff_coverage(arrivals.mean, CUTOFFS, args.shift_minutes)
    print(
        "cutoff coverage (target week): "
        + " | ".join(f"{key} min {value:.1%}" for key, value in coverage.items())
    )

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

    frame = run_curve_monte_carlo(
        instance, {SCENARIO_KEY: allocation}, cells, seeds, arrivals
    )
    summary = summarize_runs(frame)
    paired = _paired_rows(frame)
    over = over_shift_rate(frame, args.shift_minutes)
    timing = arrival_timing(instance, cells, seeds, arrivals)

    otif = summary[summary["metric"] == "e2e_otif_rate"]
    print("\nEnd-to-end OTIF by cell:")
    print(
        otif[["cell_label", "n", "mean", "ci95", "p10", "p90", "tail10"]].to_string(
            index=False, float_format=lambda value: f"{value:,.4f}"
        )
    )
    print("\nPaired differences (right - left):")
    print(
        paired[["left", "right", "mean_delta", "ci95", "win_rate", "loss_rate"]].to_string(
            index=False, float_format=lambda value: f"{value:,.4f}"
        )
    )

    dc_rows = _dc_workload(instance, allocation, arrivals, seeds[0])
    allocation_row = {
        "key": SCENARIO_KEY,
        "label": SCENARIO_LABEL,
        "status": allocation.status,
        "fill": allocation.unit_fill_rate,
        "tickets": int(sum(row["tickets"] for row in dc_rows)),
        "alloc_otif_rate": allocation.otif_rate,
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
            "dcs": list(instance.fulfillment.dc_names),
            "clean_rows": clean_stats["clean_rows"],
            "travel_m_per_minute": TRAVEL_METERS_PER_MINUTE,
            "pick_min_per_line": PICK_MINUTES_PER_LINE,
            "pick_min_per_unit": PICK_MINUTES_PER_UNIT,
            "setup_min_per_wave": SETUP_MINUTES_PER_WAVE,
            "labor_cost_per_minute": LABOR_COST_PER_MINUTE,
        },
        "seeds": seeds,
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
            "service_late_weight": args.service_late_weight,
            "service_otif_bonus": args.service_otif_bonus,
            "pick_overload_penalty": args.pick_overload_penalty,
            "lookback_weeks": args.lookback_weeks,
            "start_hour": args.start_hour,
            "end_hour": args.end_hour,
            "noise_sigma": args.noise_sigma,
            "cells": [cell.key for cell in cells],
        },
        "arrivals": {
            **arrivals.as_dict(),
            "rows": curve_share_table(arrivals),
        },
        "cutoff_coverage": coverage,
        "cutoff_coverage_mean": mean_coverage,
        "cells": [cell_dict(cell) for cell in cells],
        "timing": timing,
        "allocation": allocation_row,
        "summary": summary.to_dict("records"),
        "paired": paired.to_dict("records"),
        "over_shift": over.to_dict("records"),
        "dc_workload": dc_rows,
        "declared_assumptions": list(instance.meta.get("assumptions", []))
        + [
            "日内到达形状来自前 6 周 Online Retail II 发票时间戳（周一至周五、08:00-18:00）",
            "目标周曲线是留出诊断，不参与任何规划或评估抽样",
            "承诺窗口、班前占比、截单时间、拣选工时与拥堵噪声仍是声明值",
            "分单固定为 Week-9 容量感知 MILP，时间受限 FEASIBLE",
        ],
    }

    out_dir = Path(args.out_dir)
    paths = write_empirical_report(payload, out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
