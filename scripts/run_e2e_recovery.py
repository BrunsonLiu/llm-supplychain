"""Week 12 benchmark: mid-shift write-back under stock-placement imbalance.

Week 11 shows that where stock sits changes end-to-end service. This script
keeps each Week-11 placement, runs the pick layer to a declared review minute,
and then applies four recovery policies to the tickets that have not started:

* ``none``: freeze the allocation, replay the remaining shift;
* ``reroute``: move pick tickets projected to miss their cutoff;
* ``balance``: move any pending ticket when the target queue is shorter;
* ``oracle``: move the tickets that actually miss, using phase-1 hindsight.

All policies share the same phase-2 noise draw, so differences isolate the
write-back decision. The benchmark also sweeps the review minute and includes
a two-picker cell as a capacity control.

Usage:
    PYTHONPATH=src;. python scripts/run_e2e_recovery.py
    PYTHONPATH=src;. python scripts/run_e2e_recovery.py --orders 100 --seeds 5 --milp-time 5
"""
from __future__ import annotations

import argparse
import math
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
    DEFAULT_POLICIES,
    PROMISE_TIER,
    RECOVERY_POLICY_LABELS,
    TIER_CUTOFFS,
    RecoveryConfig,
    StressCell,
    build_e2e_instance,
    plan_row,
    plans_for,
    replay_recovery,
    recovery_summary,
    write_recovery_report,
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


def _allocation(instance, args) -> FulfillmentResult:
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


def _paired_vs_none(runs: pd.DataFrame) -> list[dict]:
    rows = []
    for (scenario, cell), block in runs.groupby(["scenario", "cell"], sort=False):
        base = block[block["policy"] == "none"].set_index("seed")
        if base.empty:
            continue
        for policy, other_block in block.groupby("policy", sort=False):
            if policy == "none":
                continue
            other = other_block.set_index("seed")
            common = base.index.intersection(other.index)
            delta = (
                other.loc[common, "e2e_otif_rate"].astype(float)
                - base.loc[common, "e2e_otif_rate"].astype(float)
            ).to_numpy()
            sd = float(delta.std(ddof=1)) if delta.size > 1 else 0.0
            rows.append(
                {
                    "scenario": scenario,
                    "cell": cell,
                    "cell_label": str(block["cell_label"].iloc[0]),
                    "policy": policy,
                    "policy_label": RECOVERY_POLICY_LABELS[policy],
                    "n": int(delta.size),
                    "mean_delta": float(delta.mean()),
                    "ci95": (
                        1.96 * sd / math.sqrt(delta.size)
                        if delta.size > 1
                        else 0.0
                    ),
                    "win_rate": float((delta > 0).mean()),
                    "loss_rate": float((delta < 0).mean()),
                    "tie_rate": float((delta == 0).mean()),
                    "min_delta": float(delta.min()),
                    "max_delta": float(delta.max()),
                }
            )
    return rows


def _over_shift(runs: pd.DataFrame, shift_minutes: float) -> list[dict]:
    rows = []
    for (scenario, cell, policy), block in runs.groupby(
        ["scenario", "cell", "policy"], sort=False
    ):
        rows.append(
            {
                "scenario": scenario,
                "cell": cell,
                "cell_label": str(block["cell_label"].iloc[0]),
                "policy": policy,
                "policy_label": str(block["policy_label"].iloc[0]),
                "n": int(len(block)),
                "over_shift_rate": float(
                    (block["pick_makespan"] > shift_minutes).mean()
                ),
                "mean_makespan": float(block["pick_makespan"].mean()),
                "p90_makespan": float(np.percentile(block["pick_makespan"], 90)),
            }
        )
    return rows


def _move_summary(runs: pd.DataFrame) -> list[dict]:
    rows = []
    for (scenario, cell, policy), block in runs.groupby(
        ["scenario", "cell", "policy"], sort=False
    ):
        rows.append(
            {
                "scenario": scenario,
                "cell": cell,
                "cell_label": str(block["cell_label"].iloc[0]),
                "policy": policy,
                "policy_label": str(block["policy_label"].iloc[0]),
                "runs": int(block["seed"].nunique()),
                "seeds_with_moves": int((block["moved_tickets"] > 0).sum()),
                "mean_moves": float(block["moved_tickets"].mean()),
                "mean_units": float(block["moved_units"].mean()),
                "mean_fee": float(block["transfer_fee"].mean()),
                "mean_transport_delta": float(block["transport_delta"].mean()),
                "rescued_orders": int(block["rescued_orders"].sum()),
                "lost_orders": int(block["lost_orders"].sum()),
            }
        )
    return rows


def _review_summary(
    runs: pd.DataFrame,
    sweep: pd.DataFrame,
    review_minute: float,
) -> list[dict]:
    frames = []
    if not sweep.empty:
        frames.append(
            sweep[
                [
                    "scenario",
                    "cell",
                    "review_minute",
                    "e2e_otif_rate",
                    "moved_tickets",
                    "rescued_orders",
                    "lost_orders",
                ]
            ]
        )
    base = runs[(runs["policy"] == "reroute") & (runs["cell"] == "base")].copy()
    if not base.empty:
        base["review_minute"] = float(review_minute)
        frames.append(
            base[
                [
                    "scenario",
                    "cell",
                    "review_minute",
                    "e2e_otif_rate",
                    "moved_tickets",
                    "rescued_orders",
                    "lost_orders",
                ]
            ]
        )
    if not frames:
        return []
    frame = pd.concat(frames, ignore_index=True)
    rows = []
    for (scenario, review), block in frame.groupby(
        ["scenario", "review_minute"], sort=False
    ):
        values = block["e2e_otif_rate"].astype(float).to_numpy()
        sd = float(values.std(ddof=1)) if values.size > 1 else 0.0
        rows.append(
            {
                "scenario": scenario,
                "review_minute": float(review),
                "n": int(values.size),
                "mean_otif": float(values.mean()),
                "ci95": (
                    1.96 * sd / math.sqrt(values.size) if values.size > 1 else 0.0
                ),
                "mean_moves": float(block["moved_tickets"].mean()),
                "rescued_orders": int(block["rescued_orders"].sum()),
                "lost_orders": int(block["lost_orders"].sum()),
            }
        )
    return sorted(rows, key=lambda row: (row["scenario"], row["review_minute"]))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 12 mid-shift write-back benchmark"
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
        "--placements",
        default="baseline,balanced,london",
        help="comma-separated Week-11 stock-placement keys",
    )
    parser.add_argument(
        "--policies",
        default=",".join(DEFAULT_POLICIES),
        help="comma-separated recovery policies",
    )
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--review-minute", type=float, default=120.0)
    parser.add_argument("--transfer-lead", type=float, default=30.0)
    parser.add_argument("--transfer-fee", type=float, default=10.0)
    parser.add_argument("--min-gain", type=float, default=5.0)
    parser.add_argument(
        "--review-sweep",
        default="60,180,240",
        help="comma-separated extra review minutes for the base cell",
    )
    parser.add_argument(
        "--skip-review-sweep",
        action="store_true",
        help="skip the extra review-minute sweep",
    )
    parser.add_argument("--service-time", type=float, default=30.0)
    parser.add_argument("--milp-time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--severe-sigma", type=float, default=0.40)
    parser.add_argument(
        "--title",
        default="Mid-shift write-back under stock-placement imbalance (Week 12)",
    )
    args = parser.parse_args()

    placement_keys = [
        key.strip() for key in args.placements.split(",") if key.strip()
    ]
    placements = plans_for(placement_keys)
    policy_keys = [key.strip() for key in args.policies.split(",") if key.strip()]
    unknown = sorted(set(policy_keys) - set(RECOVERY_POLICY_LABELS))
    if unknown:
        raise ValueError(f"未知回写策略: {unknown}")
    sweep = [
        float(value)
        for value in args.review_sweep.split(",")
        if value.strip() and not math.isclose(float(value), args.review_minute)
    ]
    if args.skip_review_sweep:
        sweep = []

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()

    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)

    seeds = list(range(1, args.seeds + 1))
    cells = _cells(args)
    config = RecoveryConfig(
        review_minute=args.review_minute,
        transfer_lead=args.transfer_lead,
        transfer_fee=args.transfer_fee,
        min_gain=args.min_gain,
    )

    print("=" * 110)
    print(args.title)
    print("=" * 110)
    print(
        f"orders {args.orders} | max lines/order {args.max_lines} | "
        f"stock factor {args.stock_factor:.0%} | seed {args.seed} | "
        f"pickers/DC {args.pickers} | shift {args.shift_minutes:.0f} min"
    )
    print(
        f"placements {placement_keys} | policies {policy_keys} | "
        f"seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) | cells {len(cells)}"
    )
    print(
        f"review {args.review_minute:.0f} min | transfer lead "
        f"{args.transfer_lead:.0f} min | fee €{args.transfer_fee:.0f}/ticket | "
        f"min gain {args.min_gain:.0f} min | sweep {sweep}"
    )

    placement_rows: list[dict] = []
    allocation_rows: list[dict] = []
    runs_frames: list[pd.DataFrame] = []
    move_frames: list[pd.DataFrame] = []
    dc_frames: list[pd.DataFrame] = []
    review_frames: list[pd.DataFrame] = []
    first_instance = None

    for plan in placements:
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
        placement_rows.append(row)
        print(
            f"\n[{plan.key}] {plan.label} | declared "
            f"{' / '.join(f'{value:.0%}' for value in plan.shares)} | realised "
            f"{' / '.join(f'{value:.0%}' for value in row['stock_mix'])} | "
            f"coverage {row['coverage']:.1%}"
        )
        allocation = _allocation(instance, args)
        allocation_rows.append(
            {
                "key": plan.key,
                "label": plan.label,
                "status": allocation.status,
                "fill": allocation.unit_fill_rate,
                "tickets": None,
                "alloc_otif_rate": allocation.otif_rate,
                "alloc_cost": allocation.total_cost,
                "solve_seconds": allocation.solve_seconds,
                "gap": allocation.gap,
            }
        )
        print(
            f"  allocation: {allocation.status} | fill "
            f"{allocation.unit_fill_rate:.1%} | alloc OTIF "
            f"{allocation.otif_rate:.1%} | cost €{allocation.total_cost:,.0f} | "
            f"solve {allocation.solve_seconds:.1f}s"
        )

        placement_runs = []
        placement_moves = []
        placement_dc = []
        placement_review = []
        for cell in cells:
            print(
                f"  [{plan.key}/{cell.key}] replaying {len(seeds)} seeds × "
                f"{len(policy_keys)} policies ..."
            )
            out = replay_recovery(
                instance,
                allocation,
                plan.key,
                cell,
                seeds,
                policies=policy_keys,
                config=config,
                review_sweep=sweep if cell.key == "base" else (),
            )
            placement_runs.append(out["runs"])
            placement_moves.append(out["moves"])
            placement_dc.append(out["dc"])
            if not out["review_sweep"].empty:
                placement_review.append(out["review_sweep"])
            otif = out["runs"][out["runs"]["policy"] == "none"]["e2e_otif_rate"].mean()
            best = out["runs"][out["runs"]["policy"] != "none"].groupby("policy")[
                "e2e_otif_rate"
            ].mean()
            best_key = best.idxmax() if not best.empty else "—"
            print(
                f"    none {otif:.1%} | best {best_key} {best.max():.1%}"
                if not best.empty
                else f"    none {otif:.1%}"
            )

        runs = pd.concat(placement_runs, ignore_index=True)
        runs_frames.append(runs)
        move_frames.append(pd.concat(placement_moves, ignore_index=True))
        dc_frames.append(pd.concat(placement_dc, ignore_index=True))
        if placement_review:
            review_frames.append(pd.concat(placement_review, ignore_index=True))
        allocation_rows[-1]["tickets"] = int(
            runs[(runs["cell"] == "base") & (runs["policy"] == "none")][
                "tickets"
            ].mean()
        )

    runs_all = pd.concat(runs_frames, ignore_index=True)
    moves_all = pd.concat(move_frames, ignore_index=True)
    dc_all = pd.concat(dc_frames, ignore_index=True)
    review_all = (
        pd.concat(review_frames, ignore_index=True)
        if review_frames
        else pd.DataFrame()
    )

    summary = recovery_summary(runs_all)
    paired = _paired_vs_none(runs_all)
    over = _over_shift(runs_all, args.shift_minutes)
    move_summary = _move_summary(runs_all)
    review_summary = _review_summary(runs_all, review_all, args.review_minute)

    otif = summary[summary["metric"] == "e2e_otif_rate"]
    print("\nEnd-to-end OTIF by placement × cell × policy:")
    print(
        otif[
            [
                "scenario",
                "cell_label",
                "policy_label",
                "mean",
                "ci95",
                "p10",
                "p50",
                "p90",
                "tail10",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:,.4f}")
    )

    move_routes = []
    if not moves_all.empty:
        routes = moves_all.copy()
        routes["policy_label"] = routes["policy"].map(RECOVERY_POLICY_LABELS)
        cell_labels = {cell.key: cell.label for cell in cells}
        routes["cell_label"] = routes["cell"].map(cell_labels)
        move_routes = (
            routes.groupby(
                ["scenario", "cell_label", "policy_label", "from_dc", "to_dc"],
                as_index=False,
            )
            .size()
            .rename(columns={"size": "moves"})
            .to_dict("records")
        )

    dc_snapshot = dc_all[
        (dc_all["seed"] == seeds[0]) & (dc_all["cell"] == "base")
    ].copy()
    dc_snapshot["policy_label"] = dc_snapshot["policy"].map(RECOVERY_POLICY_LABELS)

    dataset = {
        **first_instance.meta,
        "orders": first_instance.n_orders,
        "lines": first_instance.meta["order_lines"],
        "units": first_instance.meta["units"],
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
            "placements": placement_keys,
            "policies": policy_keys,
            "pickers": args.pickers,
            "shift_minutes": args.shift_minutes,
            "review_minute": args.review_minute,
            "transfer_lead": args.transfer_lead,
            "transfer_fee": args.transfer_fee,
            "min_gain": args.min_gain,
            "review_sweep": sweep,
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "service_late_weight": args.service_late_weight,
            "service_otif_bonus": args.service_otif_bonus,
            "pick_overload_penalty": args.pick_overload_penalty,
            "noise_sigma": args.noise_sigma,
            "severe_sigma": args.severe_sigma,
        },
        "placements": placement_rows,
        "allocations": allocation_rows,
        "policies": [
            {"key": key, "label": RECOVERY_POLICY_LABELS[key]}
            for key in policy_keys
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
        "paired": paired,
        "over_shift": over,
        "move_summary": move_summary,
        "move_routes": move_routes,
        "review_sweep_summary": review_summary,
        "dc_workload": dc_snapshot.to_dict("records"),
        "declared_assumptions": list(first_instance.meta.get("assumptions", []))
        + [
            "审核时点前已开工的波次锁定，只有未开工波次中的票据可以调动",
            "调动票据的库存随票据内部调拨到目标 DC，不要求目标 DC 有额外 SKU 库存，但受目标 DC 周产能约束",
            "调动票据按调拨前置时间延后开工，并保持原截单时间与客户承诺",
            "投影使用确定性 EDF 队列，不预知剩余班次的拣选时长噪声；先知策略只预知第一阶段的实际迟到集合",
            "所有策略共享第二阶段同一噪声种子，差异只来自调动决策",
            "跨 DC 调拨不重新求解分单，也不改变客户承诺、截单时间或总库存",
        ],
    }
    paths = write_recovery_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
