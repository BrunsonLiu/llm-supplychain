"""Week 13 benchmark: joint allocation and stock placement under execution risk.

Weeks 9-12 hold the DC stock split fixed. Week 11 shows placement changes
service but re-solves allocation after the split; Week 12 shows mid-shift
rerouting needs spare pick capacity. This script makes placement and allocation
one decision and compares five scenarios on the same orders, promises, layout,
slots, pickers and seeds:

* ``declared``: the Week-5 34/28/38 split with the deterministic SKU jitter.
* ``destination``: per-SKU prior-week destination mix (UK -> London, EU split
  45/55 Rotterdam/Frankfurt by declaration), then the standard allocation.
  Capacity-blind: it can pile stock into a DC that cannot pick it.
* ``destination_capped``: the same history clipped to each DC's share of weekly
  throughput, with the excess redistributed by remaining headroom. This is the
  deployable comparator.
* ``joint_placement``: the joint MILP's implied placement, then the standard
  capacity-aware allocation. Isolates *where* stock sits from *how* it is split.
* ``joint_plan``: one MILP lets placement follow the allocation.

The plan-driven placements see the week's orders, so they are upper bounds for
a known week, not deployable policies. Use ``--orders`` / ``--seeds`` /
``--milp-time`` for a quick run.

Usage:
    PYTHONPATH=src;. python scripts/run_e2e_joint.py
    PYTHONPATH=src;. python scripts/run_e2e_joint.py --orders 100 --seeds 5 --milp-time 5
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
    PlacementPlan,
    StressCell,
    build_e2e_instance,
    cap_shares,
    capacity_aware_allocation,
    destination_mix,
    joint_plan,
    over_shift_rate,
    paired_placements,
    placement_from_shares,
    placement_row,
    rebuild_arrivals,
    run_monte_carlo,
    run_pick_layer,
    summarize_runs,
    with_stock,
    write_joint_report,
)
from supply.fulfillment import FulfillmentResult  # noqa: E402
from supply.wave.instances import (  # noqa: E402
    LABOR_COST_PER_MINUTE,
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_UNIT,
    SETUP_MINUTES_PER_WAVE,
    TRAVEL_METERS_PER_MINUTE,
)

SCENARIO_LABELS = {
    "declared": "Week-5 基线 34/28/38",
    "destination": "目的地历史布点",
    "destination_capped": "目的地历史 + 产能封顶",
    "joint_placement": "联合布点 + 标准分单",
    "joint_plan": "联合规划（分单+布点）",
}


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


def _allocation_row(
    key: str,
    allocation: FulfillmentResult,
    tickets: int,
) -> dict:
    return {
        "key": key,
        "label": SCENARIO_LABELS[key],
        "status": allocation.status,
        "fill": allocation.unit_fill_rate,
        "tickets": tickets,
        "alloc_otif_rate": allocation.otif_rate,
        "alloc_cost": allocation.total_cost,
        "solve_seconds": allocation.solve_seconds,
        "gap": allocation.gap,
    }


def _dc_workload(instance, allocation, scenario: str, seed: int) -> list[dict]:
    shifted = rebuild_arrivals(instance, seed)
    result = run_pick_layer(
        shifted,
        allocation,
        scenario=scenario,
        policy="edf",
        pickers_per_dc=instance.pickers_per_dc,
    )
    return [
        {
            "scenario": scenario,
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


def _strip_stock(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "stock"}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 13 joint allocation / stock placement benchmark"
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
    parser.add_argument("--lookback-weeks", type=int, default=8)
    parser.add_argument("--eu-split", type=float, nargs=2, default=(0.45, 0.55))
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--severe-sigma", type=float, default=0.40)
    parser.add_argument(
        "--title", default="Joint allocation and stock placement (Week 13)"
    )
    args = parser.parse_args()

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
        f"seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) | stress cells {len(cells)} | "
        f"lookback {args.lookback_weeks} weeks | EU split "
        f"{args.eu_split[0]:.2f}/{args.eu_split[1]:.2f}"
    )

    base = build_e2e_instance(
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

    mix = destination_mix(
        clean,
        base.fulfillment.sku_names,
        last_week,
        lookback_weeks=args.lookback_weeks,
        eu_split=tuple(args.eu_split),
    )
    print(
        f"\ndestination history: {mix.history_skus} SKUs with history, "
        f"{mix.fallback_skus} fallback | weeks {mix.start_week}..{mix.end_week}"
    )

    declared_plan = PlacementPlan(
        key="declared",
        label=SCENARIO_LABELS["declared"],
        stock=base.fulfillment.stock,
        note="声明占比 + 确定性 SKU 抖动",
        source="declared",
    )
    destination_plan = placement_from_shares(
        base,
        mix.shares,
        key="destination",
        label=SCENARIO_LABELS["destination"],
        note=(
            f"前 {args.lookback_weeks} 周目的地占比；UK→London，"
            f"欧洲内按 {args.eu_split[0]:.0%}/{args.eu_split[1]:.0%} 声明拆分"
        ),
        source="history",
    )
    stock_total = int(base.fulfillment.stock.sum())
    capacity_cap = base.fulfillment.dc_capacity.astype(float) / stock_total
    capped_shares = cap_shares(
        mix.shares, base.fulfillment.dc_capacity, stock_total
    )
    destination_capped_plan = placement_from_shares(
        base,
        capped_shares,
        key="destination_capped",
        label=SCENARIO_LABELS["destination_capped"],
        note=(
            "目的地历史按 DC 周产能封顶，超额按剩余产能再分配；"
            f"封顶后 London ≤ {capacity_cap[0]:.0%}"
        ),
        source="history",
    )
    print(
        "destination cap: "
        + " / ".join(
            f"{name} {value:.0%}"
            for name, value in zip(base.fulfillment.dc_names, capacity_cap)
        )
    )

    instances = {
        "declared": base,
        "destination": with_stock(
            base,
            destination_plan.stock,
            key="destination",
            label=SCENARIO_LABELS["destination"],
        ),
        "destination_capped": with_stock(
            base,
            destination_capped_plan.stock,
            key="destination_capped",
            label=SCENARIO_LABELS["destination_capped"],
        ),
    }
    allocations: dict[str, FulfillmentResult] = {}

    print("\n[declared] standard capacity-aware allocation ...")
    allocations["declared"] = capacity_aware_allocation(
        base,
        service_time=args.service_time,
        milp_time=args.milp_time,
        workers=args.workers,
        service_late_weight=args.service_late_weight,
        service_otif_bonus=args.service_otif_bonus,
        pick_overload_penalty=args.pick_overload_penalty,
    )
    print(
        f"  allocation: {allocations['declared'].status} | "
        f"fill {allocations['declared'].unit_fill_rate:.1%} | "
        f"alloc OTIF {allocations['declared'].otif_rate:.1%} | "
        f"cost €{allocations['declared'].total_cost:,.0f} | "
        f"solve {allocations['declared'].solve_seconds:.1f}s"
    )

    print("\n[destination] standard capacity-aware allocation ...")
    allocations["destination"] = capacity_aware_allocation(
        instances["destination"],
        service_time=args.service_time,
        milp_time=args.milp_time,
        workers=args.workers,
        service_late_weight=args.service_late_weight,
        service_otif_bonus=args.service_otif_bonus,
        pick_overload_penalty=args.pick_overload_penalty,
    )
    print(
        f"  allocation: {allocations['destination'].status} | "
        f"fill {allocations['destination'].unit_fill_rate:.1%} | "
        f"alloc OTIF {allocations['destination'].otif_rate:.1%} | "
        f"cost €{allocations['destination'].total_cost:,.0f} | "
        f"solve {allocations['destination'].solve_seconds:.1f}s"
    )

    print("\n[destination_capped] standard capacity-aware allocation ...")
    allocations["destination_capped"] = capacity_aware_allocation(
        instances["destination_capped"],
        service_time=args.service_time,
        milp_time=args.milp_time,
        workers=args.workers,
        service_late_weight=args.service_late_weight,
        service_otif_bonus=args.service_otif_bonus,
        pick_overload_penalty=args.pick_overload_penalty,
    )
    print(
        f"  allocation: {allocations['destination_capped'].status} | "
        f"fill {allocations['destination_capped'].unit_fill_rate:.1%} | "
        f"alloc OTIF {allocations['destination_capped'].otif_rate:.1%} | "
        f"cost €{allocations['destination_capped'].total_cost:,.0f} | "
        f"solve {allocations['destination_capped'].solve_seconds:.1f}s"
    )

    print("\n[joint] solving the placement-aware allocation ...")
    joint = joint_plan(
        base,
        mix,
        milp_time=args.milp_time,
        workers=args.workers,
        service_late_weight=args.service_late_weight,
        service_otif_bonus=args.service_otif_bonus,
        pick_overload_penalty=args.pick_overload_penalty,
    )
    joint_instance = with_stock(
        base,
        joint.stock,
        key="joint",
        label="联合方案的隐含布点",
    )
    instances["joint_placement"] = joint_instance
    instances["joint_plan"] = joint_instance
    allocations["joint_plan"] = joint.allocation
    print(
        f"  joint: {joint.status} | objective €{joint.objective:,.0f} | "
        f"gap {joint.gap:.1%} | solve {joint.solve_seconds:.1f}s | "
        f"mix {' / '.join(f'{value:.0%}' for value in joint.stock_mix)}"
    )

    print("\n[joint_placement] re-solving the standard allocation on that placement ...")
    allocations["joint_placement"] = capacity_aware_allocation(
        joint_instance,
        service_time=args.service_time,
        milp_time=args.milp_time,
        workers=args.workers,
        service_late_weight=args.service_late_weight,
        service_otif_bonus=args.service_otif_bonus,
        pick_overload_penalty=args.pick_overload_penalty,
    )
    print(
        f"  allocation: {allocations['joint_placement'].status} | "
        f"fill {allocations['joint_placement'].unit_fill_rate:.1%} | "
        f"alloc OTIF {allocations['joint_placement'].otif_rate:.1%} | "
        f"cost €{allocations['joint_placement'].total_cost:,.0f} | "
        f"solve {allocations['joint_placement'].solve_seconds:.1f}s"
    )

    order = [
        "declared",
        "destination",
        "destination_capped",
        "joint_placement",
        "joint_plan",
    ]
    frames = []
    for key in order:
        print(f"\n[{key}] replaying {len(cells)} cells × {len(seeds)} seeds ...")
        frames.append(
            run_monte_carlo(instances[key], {key: allocations[key]}, cells, seeds)
        )
    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_runs(frame)
    over = over_shift_rate(frame, args.shift_minutes)

    otif = summary[summary["metric"] == "e2e_otif_rate"]
    print("\nEnd-to-end OTIF by scenario × stress cell:")
    print(
        otif[
            ["scenario", "cell_label", "mean", "ci95", "p10", "p50", "p90", "tail10"]
        ].to_string(index=False, float_format=lambda value: f"{value:,.4f}")
    )

    labels = {key: SCENARIO_LABELS[key] for key in order}
    dc_rows: list[dict] = []
    allocation_rows: list[dict] = []
    for key in order:
        rows = _dc_workload(instances[key], allocations[key], key, seeds[0])
        dc_rows.extend(rows)
        allocation_rows.append(
            _allocation_row(key, allocations[key], sum(row["tickets"] for row in rows))
        )

    paired_frames = [
        paired_placements(frame, "declared", "destination", labels),
        paired_placements(frame, "declared", "destination_capped", labels),
        paired_placements(frame, "declared", "joint_placement", labels),
        paired_placements(frame, "declared", "joint_plan", labels),
        paired_placements(frame, "joint_placement", "joint_plan", labels),
    ]
    paired = pd.concat(paired_frames, ignore_index=True)

    declared_row = placement_row(declared_plan, base)
    destination_row = placement_row(destination_plan, base)
    capped_row = placement_row(destination_capped_plan, base)
    joint_row = {
        "key": "joint",
        "label": "联合方案的隐含布点",
        "stock_mix": joint.stock_mix,
        "stock_units": [int(value) for value in joint.stock.sum(axis=1)],
        "coverage": float(joint.stock.sum() / base.fulfillment.line_qty.sum()),
        "dcs": list(base.fulfillment.dc_names),
        "source": "plan",
        "note": "联合 MILP 按周内订单落位，剩余库存按目的地占比保留",
    }
    placements = [
        _strip_stock(row)
        for row in (declared_row, destination_row, capped_row, joint_row)
    ]

    dataset = {
        **base.meta,
        "orders": base.n_orders,
        "lines": base.meta["order_lines"],
        "week": str(last_week.date()),
        "pickers_per_dc": args.pickers,
        "shift_minutes": args.shift_minutes,
        "max_orders": base.max_orders,
        "max_lines": base.max_lines,
        "dcs": list(base.fulfillment.dc_names),
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
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "service_late_weight": args.service_late_weight,
            "service_otif_bonus": args.service_otif_bonus,
            "pick_overload_penalty": args.pick_overload_penalty,
            "lookback_weeks": args.lookback_weeks,
            "eu_split": list(args.eu_split),
            "noise_sigma": args.noise_sigma,
            "severe_sigma": args.severe_sigma,
            "scenarios": order,
        },
        "destination_mix": {
            **mix.as_dict(),
            "eu_split": list(args.eu_split),
            "lookback_weeks": args.lookback_weeks,
            "capacity_cap": [float(value) for value in capacity_cap],
        },
        "placements": placements,
        "allocations": allocation_rows,
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
        "paired": paired.to_dict("records"),
        "dc_workload": dc_rows,
        "declared_assumptions": list(base.meta.get("assumptions", []))
        + [
            "库存总量按 SKU 固定，只改变各 DC 的库存位置；目的地历史只使用本周之前的数据",
            "联合布点与联合规划看到本周订单，是已知周的上界，不是可部署的预测策略",
            "所有场景共享订单集、到达种子与拥堵 σ，但分单可行集不同，配对只共享随机种子",
            "联合 MILP 的拣选容量约束是线性分钟代理，不是波次仿真",
        ],
    }
    paths = write_joint_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
