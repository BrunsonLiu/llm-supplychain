"""Week 14 benchmark: two-stage stochastic stock placement under demand risk.

Week 13 chooses a placement *after* seeing the target week's orders. That is an
upper bound, not a deployable policy. This benchmark plans the placement from
the last six weeks only:

* each prior week becomes an equally weighted demand scenario, rescaled to the
  target week's total units (volume known, SKU x destination mix uncertain);
* per-SKU stock totals come from the scenario mean, not the target week;
* a two-stage integer program chooses one placement, then a fluid second stage
  allocates each scenario's demand subject to serviceability, DC throughput and
  a linear pick-minute budget;
* the objective mixes expected and CVaR unmet demand, with a peak-pick-minute
  tie-break to keep any one DC from holding more work than it can start.

Placements compared on the same orders, stock totals, promises, layout, slots,
pickers and seeds:

* ``declared``: Week-5 34/28/38 plus its deterministic SKU jitter, applied to
  the scenario-mean stock totals.
* ``destination``: per-SKU prior-week destination mix, capacity-blind.
* ``destination_capped``: that mix clipped to each DC's weekly throughput.
* ``stochastic_expected``: the scenario MILP with CVaR weight 0.
* ``stochastic_cvar``: the scenario MILP with CVaR weight 0.5 (the default).

Every placement is then scored by the Week-9 two-stage capacity-aware
allocation and replayed through the Week-10 E2E Monte Carlo. Allocation is
time-limited and solver-dependent, so it is repeated ``--reps`` times and the
report separates placement effects from solver noise.

Usage:
    PYTHONPATH=src;. python scripts/run_e2e_stochastic.py
    PYTHONPATH=src;. python scripts/run_e2e_stochastic.py --orders 100 --seeds 5 --reps 1 --milp-time 5
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
    StressCell,
    build_e2e_instance,
    cap_shares,
    capacity_aware_allocation,
    destination_mix,
    over_shift_rate,
    paired_placements,
    placement_from_shares,
    rebuild_arrivals,
    run_monte_carlo,
    run_pick_layer,
    summarize_runs,
    with_stock,
)
from supply.e2e.joint import PlacementPlan  # noqa: E402
from supply.e2e.stochastic import (  # noqa: E402
    build_demand_scenarios,
    pick_proxy,
    planned_stock_instance,
    planned_stock_totals,
    score_placement,
    stochastic_placement,
)
from supply.e2e.stochastic_report import write_stochastic_report  # noqa: E402
from supply.wave.instances import (  # noqa: E402
    LABOR_COST_PER_MINUTE,
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_UNIT,
    SETUP_MINUTES_PER_WAVE,
    TRAVEL_METERS_PER_MINUTE,
)

BASELINE_LABELS = {
    "declared": "Week-5 基线 34/28/38",
    "destination": "目的地历史布点",
    "destination_capped": "目的地历史 + 产能封顶",
    "stochastic_expected": "场景均值最优 (λ=0)",
    "stochastic_cvar": "场景 CVaR (λ=0.5)",
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


def _strip_stock(row: dict) -> dict:
    return {key: value for key, value in row.items() if key != "stock"}


def _placement_row(
    plan: PlacementPlan,
    base,
    minute_per_unit: float,
    pick_capacity: float,
) -> dict:
    units = [int(value) for value in plan.stock.sum(axis=1)]
    peak = minute_per_unit * max(units)
    return {
        "key": plan.key,
        "label": plan.label,
        "stock_mix": list(plan.mix),
        "stock_units": units,
        "coverage": float(plan.units / base.fulfillment.line_qty.sum()),
        "peak_pick_minutes": float(peak),
        "peak_vs_shift": float(peak / pick_capacity) if pick_capacity > 0 else 0.0,
        "dcs": list(base.fulfillment.dc_names),
        "source": plan.source,
        "note": plan.note,
    }


def _allocation_row(
    key: str,
    label: str,
    results: list,
    tickets: int,
) -> dict:
    otif = [float(result.otif_rate) for result in results]
    fill = [float(result.unit_fill_rate) for result in results]
    cost = [float(result.total_cost) for result in results]
    seconds = [float(result.solve_seconds) for result in results]
    gaps = [float(result.gap) for result in results if np.isfinite(result.gap)]
    return {
        "key": key,
        "label": label,
        "status": results[0].status,
        "fill": float(np.mean(fill)),
        "fill_min": float(np.min(fill)),
        "fill_max": float(np.max(fill)),
        "tickets": int(tickets),
        "alloc_otif_rate": float(np.mean(otif)),
        "alloc_otif_min": float(np.min(otif)),
        "alloc_otif_max": float(np.max(otif)),
        "alloc_cost": float(np.mean(cost)),
        "solve_seconds": float(np.mean(seconds)),
        "gap": float(np.mean(gaps)) if gaps else float("nan"),
        "reps": len(results),
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


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Week 14 stochastic stock placement benchmark"
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
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--service-time", type=float, default=30.0)
    parser.add_argument("--milp-time", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--service-late-weight", type=float, default=5.0)
    parser.add_argument("--service-otif-bonus", type=float, default=200.0)
    parser.add_argument("--pick-overload-penalty", type=float, default=5.0)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--eu-split", type=float, nargs=2, default=(0.45, 0.55))
    parser.add_argument("--scenario-time", type=float, default=60.0)
    parser.add_argument("--score-time", type=float, default=10.0)
    parser.add_argument("--cvar-weight", type=float, default=0.5)
    parser.add_argument("--cvar-alpha", type=float, default=0.8)
    parser.add_argument(
        "--sweep-lambdas", type=float, nargs="+", default=[0.0, 0.25, 0.5, 0.75, 1.0]
    )
    parser.add_argument("--noise-sigma", type=float, default=0.25)
    parser.add_argument("--severe-sigma", type=float, default=0.40)
    parser.add_argument(
        "--title",
        default="Uncertainty-aware stock placement (Week 14)",
    )
    args = parser.parse_args()
    if args.reps < 1:
        raise ValueError("--reps 必须 >= 1")
    if args.lookback_weeks < 1:
        raise ValueError("--lookback-weeks 必须 >= 1")

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
        f"seeds {seeds[0]}..{seeds[-1]} ({len(seeds)}) x {args.reps} allocation "
        f"replicate(s) | stress cells {len(cells)} | scenarios "
        f"{args.lookback_weeks} weeks | CVaR w={args.cvar_weight:.2f} "
        f"alpha={args.cvar_alpha:.2f}"
    )

    raw_base = build_e2e_instance(
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
    target_units = int(raw_base.fulfillment.line_qty.sum())
    scenarios = build_demand_scenarios(
        clean,
        raw_base.fulfillment.sku_names,
        last_week,
        target_units,
        lookback_weeks=args.lookback_weeks,
    )
    totals = planned_stock_totals(scenarios, stock_factor=args.stock_factor)
    base = planned_stock_instance(
        raw_base,
        totals,
        key="scenario_mean",
        label=f"前 {args.lookback_weeks} 周场景均值 × {args.stock_factor:.0%}",
    )
    print(
        f"\nscenario set: {len(scenarios.scenarios)} weeks "
        f"{scenarios.weeks[0]}..{scenarios.weeks[-1]} | "
        f"target {target_units:,} units | stock {int(totals.sum()):,} "
        f"({totals.sum() / target_units:.1%})"
    )
    for scenario in scenarios.scenarios:
        shares = scenario.serviceable.sum(axis=1) / scenario.demand.sum()
        print(
            f"  {scenario.week} | raw {scenario.raw_units:,} | "
            f"scale {scenario.scale:.3f} | active SKUs {scenario.active_skus} | "
            f"serviceable " + "/".join(f"{value:.0%}" for value in shares)
        )

    raw_totals = raw_base.fulfillment.stock.sum(axis=0)
    declared_shares = raw_base.fulfillment.stock.T / raw_totals[:, None]
    declared = placement_from_shares(
        base,
        declared_shares,
        key="declared",
        label=BASELINE_LABELS["declared"],
        note="Week-5 占比与确定性 SKU 抖动，应用到场景均值总量",
        source="declared",
    )
    mix = destination_mix(
        clean,
        base.fulfillment.sku_names,
        last_week,
        lookback_weeks=args.lookback_weeks,
        eu_split=tuple(args.eu_split),
    )
    destination = placement_from_shares(
        base,
        mix.shares,
        key="destination",
        label=BASELINE_LABELS["destination"],
        note=f"前 {args.lookback_weeks} 周目的地占比；产能盲区",
        source="history",
    )
    capped_shares = cap_shares(
        mix.shares, base.fulfillment.dc_capacity, int(totals.sum())
    )
    capped = placement_from_shares(
        base,
        capped_shares,
        key="destination_capped",
        label=BASELINE_LABELS["destination_capped"],
        note="目的地历史按 DC 周产能封顶，超额按剩余产能再分配",
        source="history",
    )
    print(
        f"\ndestination history: {mix.history_skus} SKUs with history, "
        f"{mix.fallback_skus} fallback | weeks {mix.start_week}..{mix.end_week}"
    )

    minute_per_unit, pick_capacity = pick_proxy(base)
    print(
        f"pick proxy: {minute_per_unit:.5f} min/unit | "
        f"{pick_capacity:.0f} min per DC per shift"
    )

    stochastic: dict[float, object] = {}
    for lam in sorted({0.0, args.cvar_weight, *args.sweep_lambdas}):
        print(f"\n[stochastic λ={lam:.2f}] solving scenario placement ...")
        result = stochastic_placement(
            base,
            scenarios,
            cvar_weight=lam,
            alpha=args.cvar_alpha,
            time_limit_seconds=args.scenario_time,
            workers=args.workers,
            hint_stock=declared.stock,
            pick_minutes_per_unit=minute_per_unit,
            pickers_per_dc=args.pickers,
            shift_minutes=args.shift_minutes,
        )
        stochastic[lam] = result
        print(
            f"  {result.status} | objective {result.objective:,.0f} unmet | "
            f"E {result.expected_unmet / target_units:.1%} | "
            f"CVaR {result.cvar_unmet / target_units:.1%} | "
            f"mix {' / '.join(f'{value:.0%}' for value in result.mix)} | "
            f"peak {result.peak_minutes:.0f} min | "
            f"solve {result.solve_seconds:.1f}s"
        )

    expected = stochastic[0.0]
    cvar = stochastic[args.cvar_weight]
    plans = {
        "declared": declared,
        "destination": destination,
        "destination_capped": capped,
        "stochastic_expected": PlacementPlan(
            key="stochastic_expected",
            label=BASELINE_LABELS["stochastic_expected"],
            stock=expected.stock,
            note="场景期望未满足最小；覆盖与峰值拣选分钟平局决胜",
            source="stochastic",
        ),
        "stochastic_cvar": PlacementPlan(
            key="stochastic_cvar",
            label=BASELINE_LABELS["stochastic_cvar"],
            stock=cvar.stock,
            note=f"期望 + CVaR(α={args.cvar_alpha:.2f}) 风险权重",
            source="stochastic",
        ),
    }
    order = list(plans)

    predicted = {}
    for key, plan in plans.items():
        score = score_placement(
            plan.stock,
            scenarios,
            base.fulfillment.dc_capacity,
            alpha=args.cvar_alpha,
            time_limit_seconds=args.score_time,
            workers=1,
            pick_minutes_per_unit=minute_per_unit,
            pick_capacity_per_dc=pick_capacity,
        )
        predicted[key] = {
            "key": key,
            "label": plan.label,
            "expected_unmet_rate": score["expected_unmet_rate"],
            "cvar_unmet_rate": score["cvar_unmet_rate"],
            "scenario_unmet_rate": [
                value / target_units for value in score["scenario_unmet"]
            ],
            "serviceable_units": int(
                scenarios.target_units * (1.0 - score["expected_unmet_rate"])
            ),
            "status": score["status"],
            "solve_seconds": score["solve_seconds"],
        }
        print(
            f"predicted {key}: E {score['expected_unmet_rate']:.1%} | "
            f"CVaR {score['cvar_unmet_rate']:.1%} | "
            f"scenario range "
            f"{min(predicted[key]['scenario_unmet_rate']):.1%}.."
            f"{max(predicted[key]['scenario_unmet_rate']):.1%}"
        )

    frames = []
    allocations: dict[str, list] = {}
    allocation_rows = []
    dc_rows: list[dict] = []
    for key in order:
        plan = plans[key]
        instance = with_stock(base, plan.stock, key=key, label=plan.label)
        allocations[key] = []
        for rep in range(1, args.reps + 1):
            print(f"\n[{key}] allocation replicate {rep}/{args.reps} ...")
            allocation = capacity_aware_allocation(
                instance,
                service_time=args.service_time,
                milp_time=args.milp_time,
                workers=args.workers,
                service_late_weight=args.service_late_weight,
                service_otif_bonus=args.service_otif_bonus,
                pick_overload_penalty=args.pick_overload_penalty,
            )
            allocations[key].append(allocation)
            print(
                f"  {allocation.status} | fill {allocation.unit_fill_rate:.1%} | "
                f"alloc OTIF {allocation.otif_rate:.1%} | "
                f"cost €{allocation.total_cost:,.0f} | "
                f"solve {allocation.solve_seconds:.1f}s"
            )
            frame = run_monte_carlo(instance, {key: allocation}, cells, seeds)
            frame["rep"] = rep
            frame["true_seed"] = frame["seed"]
            frame["seed"] = rep * 1000 + frame["seed"]
            frames.append(frame)
        tickets = sum(
            row["tickets"]
            for row in _dc_workload(
                instance, allocations[key][0], key, seeds[0]
            )
        )
        dc_rows.extend(
            _dc_workload(instance, allocations[key][0], key, seeds[0])
        )
        allocation_rows.append(
            _allocation_row(key, plan.label, allocations[key], tickets)
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_runs(frame)
    over = over_shift_rate(frame, args.shift_minutes)

    otif = summary[summary["metric"] == "e2e_otif_rate"]
    print("\nEnd-to-end OTIF by placement x stress cell:")
    print(
        otif[["scenario", "cell_label", "n", "mean", "ci95", "p10", "p90"]]
        .to_string(index=False, float_format=lambda value: f"{value:,.4f}")
    )

    labels = {key: plans[key].label for key in order}
    paired_frames = []
    for key in order[1:]:
        paired_frames.append(paired_placements(frame, "declared", key, labels))
    if "stochastic_cvar" in plans:
        paired_frames.append(
            paired_placements(
                frame, "stochastic_expected", "stochastic_cvar", labels
            )
        )
    paired = pd.concat(paired_frames, ignore_index=True)

    placements = [
        _placement_row(plans[key], base, minute_per_unit, pick_capacity)
        for key in order
    ]
    sweep = []
    for lam in sorted(stochastic):
        result = stochastic[lam]
        sweep.append(
            {
                "lambda": float(lam),
                "status": result.status,
                "stock_mix": result.mix,
                "stock_units": [int(value) for value in result.stock.sum(axis=1)],
                "expected_unmet_rate": result.expected_unmet / target_units,
                "cvar_unmet_rate": result.cvar_unmet / target_units,
                "objective": result.objective,
                "gap": result.gap,
                "peak_minutes": result.peak_minutes,
                "solve_seconds": result.solve_seconds,
            }
        )

    dataset = {
        **base.meta,
        "orders": base.n_orders,
        "lines": base.meta["order_lines"],
        "units": target_units,
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
        "reps": args.reps,
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
            "eu_split": [float(value) for value in args.eu_split],
            "scenario_time": args.scenario_time,
            "score_time": args.score_time,
            "cvar_weight": args.cvar_weight,
            "cvar_alpha": args.cvar_alpha,
            "sweep_lambdas": [float(value) for value in sorted(stochastic)],
            "noise_sigma": args.noise_sigma,
            "severe_sigma": args.severe_sigma,
            "scenarios": order,
        },
        "scenarios": scenarios.as_dict(),
        "stock_plan": {
            "source": "scenario_mean",
            "stock_factor": args.stock_factor,
            "stock_units": int(totals.sum()),
            "target_units": target_units,
            "coverage": float(totals.sum() / target_units),
        },
        "pick_proxy": {
            "minutes_per_unit": minute_per_unit,
            "capacity_per_dc": pick_capacity,
            "congestion_margin": 0.20,
        },
        "destination_mix": {
            **mix.as_dict(),
            "lookback_weeks": args.lookback_weeks,
            "capacity_cap": [
                float(value)
                for value in base.fulfillment.dc_capacity / max(1, totals.sum())
            ],
        },
        "placements": placements,
        "predicted": [predicted[key] for key in order],
        "sweep": sweep,
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
            "每个 SKU 的库存总量取前 6 周场景均值 × 85%，不使用目标周自身的 SKU 结构",
            "场景周按目标周总量缩放：周总量已知，SKU 与目的国结构不确定",
            "可服务需求按声明承诺 30/50/20 与各 DC 转运天数计算，不是观测值",
            "拣选分钟是订单路程 + 行/件工时 + 每波 setup + 20% 拥堵余量，不是波次仿真",
            "分单为时间受限 FEASIBLE，每个布点重复 3 次以区分求解器噪声",
        ],
    }
    paths = write_stochastic_report(payload, args.out_dir, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
