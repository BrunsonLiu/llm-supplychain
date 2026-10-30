"""Week 41: demand-weighted stock placement MILP, 400 invoices x 30 seeds.

Run:
    PYTHONPATH=src;. python scripts/run_e2e_access.py
Smoke:
    PYTHONPATH=src;. python scripts/run_e2e_access.py --orders 80 --seeds 3 \
        --milp-time 2 --service-time 1 --workers 2
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
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
    build_e2e_instance,
    fit_empirical_arrivals,
    history_access,
    order_day_map,
    oracle_access,
    paired_differences,
    placement_milp,
    prepare_flow,
    run_flow_e2e,
    summarize_access,
    write_access_report,
)
from supply.e2e.access import apply_target  # noqa: E402
from supply.e2e.dispatch import DispatchCell  # noqa: E402
from supply.fulfillment.solvers import (  # noqa: E402
    PICK_MINUTES_PER_LINE,
    PICK_MINUTES_PER_SHIPMENT,
    PICK_MINUTES_PER_UNIT,
)

BASE_SHARES = (0.34, 0.28, 0.38)
POLICIES = {
    "baseline": "基线布点 34/28/38（无调拨）",
    "access_history": "历史可达需求 MILP",
    "access_oracle": "本周可达需求 MILP（上界）",
}
LOAD_POLICIES = {
    "access_history_load": "历史需求 + stock 负荷 MILP",
    "access_oracle_load": "本周需求 + stock 负荷 MILP",
    "access_history_load_covered": "历史需求 + covered 负荷 MILP",
    "access_oracle_load_covered": "本周需求 + covered 负荷 MILP",
}


def _adjust(instance):
    """Apply the Week-40 stress cell: 2x capacity and transit -1."""
    return replace(
        instance,
        fulfillment=replace(
            instance.fulfillment,
            dc_capacity=np.maximum(
                1, np.round(instance.fulfillment.dc_capacity * 2.0)
            ).astype(np.int64),
            transit_days=np.maximum(
                1, instance.fulfillment.transit_days - 1
            ).astype(np.int64),
        ),
    )


def _build(clean, skus, args, last_week):
    return build_e2e_instance(
        clean,
        skus,
        sample_orders=args.orders,
        max_lines=args.max_lines,
        stock_factor=1.0,
        stock_shares=BASE_SHARES,
        seed=args.seed,
        week=last_week,
        pickers_per_dc=args.pickers,
        shift_minutes=args.shift_minutes,
        arrival_seed=1,
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Week 41 access placement")
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
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--service-time", type=float, default=3.0)
    parser.add_argument("--milp-time", type=float, default=8.0)
    parser.add_argument("--solver-time", type=float, default=10.0)
    parser.add_argument("--min-share", type=float, default=0.10)
    parser.add_argument("--max-share", type=float, default=0.60)
    parser.add_argument("--load-aware", action="store_true")
    parser.add_argument(
        "--load-basis", choices=("stock", "covered"), default="stock"
    )
    parser.add_argument("--load-capacity", type=float, default=600.0)
    parser.add_argument("--load-penalty", type=int, default=10_000_000)
    parser.add_argument("--stem", default="ACCESS")
    parser.add_argument("--week", type=int, default=41)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.15)
    parser.add_argument("--title", default="Demand-weighted stock placement (Week 41)")
    args = parser.parse_args()

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()
    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    clean["invoice"] = clean["invoice"].astype(str)

    base = _build(clean, skus, args, last_week)
    baseline = _adjust(base)
    stock_total = int(baseline.fulfillment.stock.sum())
    order_day = order_day_map(baseline, clean)
    arrivals = fit_empirical_arrivals(
        clean, last_week, lookback_weeks=args.lookback_weeks
    )
    invoice_revenue = clean.groupby("invoice")["revenue"].sum()
    order_revenue = np.array(
        [
            float(invoice_revenue.get(str(invoice), 0.0))
            for invoice in baseline.fulfillment.order_ids
        ],
        dtype=float,
    )
    demand_revenue = float(order_revenue.sum())
    if demand_revenue <= 0:
        raise ValueError("抽样订单收入为 0")
    target_mask = order_revenue >= float(np.quantile(order_revenue, 0.90))

    units = int(baseline.fulfillment.line_qty.sum())
    total_pick_minutes = (
        baseline.fulfillment.n_lines * PICK_MINUTES_PER_LINE
        + units * PICK_MINUTES_PER_UNIT
        + baseline.fulfillment.n_orders * PICK_MINUTES_PER_SHIPMENT
    )
    pick_load_coeff = total_pick_minutes / units if units else 0.0
    oracle_demand = oracle_access(baseline)
    history_demand = history_access(
        clean,
        baseline,
        last_week,
        lookback_weeks=args.lookback_weeks,
    )

    load_suffix = "_load" if args.load_basis == "stock" else "_load_covered"
    history_load_key = f"access_history{load_suffix}"
    oracle_load_key = f"access_oracle{load_suffix}"

    def _solve(demand, load_aware: bool = False):
        kwargs = {}
        if load_aware:
            kwargs = {
                "pick_minutes_per_unit": pick_load_coeff,
                "pick_capacity": args.load_capacity,
                "pick_load_penalty": args.load_penalty,
                "pick_load_basis": args.load_basis,
            }
        return placement_milp(
            baseline,
            demand,
            time_limit=args.solver_time,
            min_share=args.min_share,
            max_share=args.max_share,
            **kwargs,
        )

    targets = {
        "access_oracle": _solve(oracle_demand),
        "access_history": _solve(history_demand),
    }
    if args.load_aware:
        targets[history_load_key] = _solve(history_demand, load_aware=True)
        targets[oracle_load_key] = _solve(oracle_demand, load_aware=True)
    labels = {**POLICIES, **LOAD_POLICIES}
    print("=" * 120)
    print(args.title)
    print("=" * 120)
    print(
        f"orders {baseline.n_orders} | seeds {args.seeds} | repeats {args.repeats} | "
        f"stock {stock_total:,} units | "
        f"daily {args.milp_time:.0f}s | solver {args.solver_time:.0f}s | "
        f"shares {args.min_share:.0%}-{args.max_share:.0%} | revenue {demand_revenue:,.0f}"
    )
    print(
        f"oracle: {targets['access_oracle'].status} coverage "
        f"{targets['access_oracle'].coverage:.1%} moved "
        f"{targets['access_oracle'].moved_units:,} units | "
        f"history: {targets['access_history'].status} coverage "
        f"{targets['access_history'].coverage:.1%} moved "
        f"{targets['access_history'].moved_units:,} units"
    )
    if args.load_aware:
        print(
            f"pick load: basis {args.load_basis} | "
            f"coeff {pick_load_coeff:.3f} min/unit | "
            f"cap {args.load_capacity:.0f} min/DC | "
            f"oracle peak {targets[oracle_load_key].peak_pick_minutes:.0f} min "
            f"over {targets[oracle_load_key].overload_minutes:.0f} | "
            f"history peak {targets[history_load_key].peak_pick_minutes:.0f} min "
            f"over {targets[history_load_key].overload_minutes:.0f}"
        )

    seeds = tuple(range(1, int(args.seeds) + 1))
    policies = ["baseline", "access_history"]
    if args.load_aware:
        policies.append(history_load_key)
    policies.append("access_oracle")
    if args.load_aware:
        policies.append(oracle_load_key)
    frames = []
    for repeat in range(int(args.repeats)):
        print(f"\n=== repeat {repeat + 1}/{args.repeats} ===")
        for policy in policies:
            if policy == "baseline":
                instance = baseline
                target = None
                label = labels[policy]
                moved = 0
                status = "—"
            else:
                target = targets[policy]
                instance = apply_target(baseline, target)
                label = labels[policy]
                moved = target.moved_units
                status = target.status
            shares = instance.fulfillment.stock.sum(axis=1) / stock_total
            print(f"\n[{policy}] {label} | shares "
                  f"{'/'.join(f'{value:.0%}' for value in shares)} ...")
            flow = prepare_flow(
                instance,
                order_day,
                "daily_1d",
                service_time=args.service_time,
                milp_time=args.milp_time,
                workers=args.workers,
                quote_policy="atp",
                accept_cutoff_days=5,
            )
            cell = DispatchCell(
                key=f"week41_{policy}",
                label=policy,
                policy="immediate",
                min_load=1,
                max_days=0,
                pickers_per_dc=args.pickers,
                duration_noise=args.noise,
            )
            frame = run_flow_e2e(
                flow,
                instance,
                order_day,
                seeds,
                arrivals,
                cell,
                segments={"target": target_mask, "rest": ~target_mask},
            )
            accepted = np.asarray(flow.accepted, dtype=bool)
            accepted_revenue = float(order_revenue[accepted].sum())
            frame["policy"] = policy
            frame["label"] = label
            frame["shares"] = "/".join(f"{value:.0%}" for value in shares)
            frame["stock_units"] = int(instance.fulfillment.stock.sum())
            frame["stock_factor"] = 1.0
            frame["dc_capacity_factor"] = 2.0
            frame["transit_cut_days"] = 1
            frame["moved_units"] = int(moved)
            frame["milp_status"] = status
            frame["coverage"] = (
                float(target.coverage) if target is not None else 0.0
            )
            frame["peak_pick_minutes"] = (
                float(target.peak_pick_minutes) if target is not None else 0.0
            )
            frame["pick_capacity"] = (
                float(target.pick_capacity) if target is not None else 0.0
            )
            frame["overload_minutes"] = (
                float(target.overload_minutes) if target is not None else 0.0
            )
            frame["pick_load_basis"] = (
                target.pick_load_basis if target is not None else ""
            )
            frame["pick_load_coeff"] = float(pick_load_coeff)
            frame["demand_revenue"] = demand_revenue
            frame["accepted_revenue"] = accepted_revenue
            frame["lost_revenue"] = float(demand_revenue - accepted_revenue)
            frame["revenue_accept_rate"] = (
                accepted_revenue / demand_revenue if demand_revenue else 0.0
            )
            frame["repeat"] = repeat
            frames.append(frame)
            print(
                f"  accepted {frame['accepted_orders'].mean():.1f} | "
                f"accepted OTIF {frame['accepted_otif_rate'].mean():.1%} | target "
                f"{frame['target_accepted_otif_rate'].mean():.1%} | rest "
                f"{frame['rest_accepted_otif_rate'].mean():.1%} | all "
                f"{frame['e2e_otif_rate'].mean():.1%} | backlog "
                f"{frame['accepted_backlog_units'].mean():,.0f}"
            )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_access(frame)
    full_scale = args.orders >= 400 and args.seeds >= 30
    limitations = [
        "固定总量：每个 SKU 的总库存 = 100% 需求，只允许 DC→DC 重摆位；不建模采购、在途、仓储成本、COGS、持有成本、过期/跌价。",
        "access_oracle 使用本周实际订单，是可达需求上界，不是可在周前执行的生产策略。",
        "access_history 使用前 6 周 country×SKU 数量，但仍使用本周 destination/transit 矩阵来判定可达性；它是半可部署估计，不是完整因果策略。",
        "库存按 SKU 总量加确定性 jitter 分配；不同 target 的总量相同，但 SKU×DC 分布受 jitter 影响。",
        "所有臂 2× DC 产能、transit −1、ATP accept-all，接受集/需求分母相同；仍只有 1 个目标周、1 套布局/班次。",
        "调拨假设在周前完成且无运输时间/费用；真实 DC 调拨需要提前期、批次和成本。",
        "布点 MILP 是单线程固定 seed；端到端分单 MILP 仍是 2 workers/时间受限，跨臂重解会带来 1–3pp 差异。",
    ]
    if args.load_aware:
        basis_text = (
            "stock-implied（按 DC 库存乘单位分钟）"
            if args.load_basis == "stock"
            else "covered（只按该 DC 实际覆盖的需求乘单位分钟）"
        )
        limitations += [
            f"负荷臂是 {basis_text} 代理，不是波次/到达仿真的真实队列；"
            "cap 是 1 名拣货员 × 600 分钟，软超载惩罚，"
            "所以它约束的是“库存/覆盖需求停在哪”，不是“实际先拣谁”。",
            "负荷臂用同一份 demand，但目标里 coverage 与 overload 的权重是声明值；"
            "cap、basis 与惩罚变化会改变 target，不能把单点结果当全局最优。",
        ]
    if full_scale:
        limitations += [
            "Week 40 同一 baseline 的 400×30 重复运行得到 92.5/95.0/97.5 目标 OTIF（5pp 跨度）；本周臂间差异必须和这个波动一起读。",
            "oracle/history 的 target 只由当前实例的订单结构决定，不随 arrival seed 变化；种子只改变到达/拣选噪声。",
            f"本次每个策略重复 {args.repeats} 次；报告同时给出 target 的 min–max，单次 2.5pp 不能当效应。",
        ]

    payload = {
        "dataset": {
            **base.meta,
            "orders": base.n_orders,
            "lines": base.meta["order_lines"],
            "units": int(base.fulfillment.line_qty.sum()),
            "week": str(last_week.date()),
            "clean_rows": clean_stats["clean_rows"],
            "dcs": list(base.fulfillment.dc_names),
            "demand_revenue": demand_revenue,
        },
        "settings": {
            "week": args.week,
            "orders": args.orders,
            "max_lines": args.max_lines,
            "seed": args.seed,
            "seeds": args.seeds,
            "repeats": args.repeats,
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "solver_time": args.solver_time,
            "min_share": args.min_share,
            "max_share": args.max_share,
            "workers": args.workers,
            "load_aware": bool(args.load_aware),
            "load_basis": args.load_basis,
            "pick_load_coeff": pick_load_coeff,
            "load_capacity": args.load_capacity,
            "load_penalty": args.load_penalty,
            "pickers": args.pickers,
            "noise": args.noise,
            "policies": list(policies),
            "stock_factor": 1.0,
            "stock_units": stock_total,
            "dc_capacity_factor": 2.0,
            "transit_cut_days": 1,
            "lookback_weeks": args.lookback_weeks,
            "target_top_share": 0.10,
            "solver_noise_pp": 5.0 if full_scale else 0.0,
            "baseline_repeats": [92.5, 95.0, 97.5] if full_scale else [],
            "milp": {
                key: {
                    "status": value.status,
                    "coverage": value.coverage,
                    "moved_units": value.moved_units,
                    "objective": value.objective,
                }
                for key, value in targets.items()
            },
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "paired": paired_differences(frame),
        "rows": frame.to_dict("records"),
        "limitations": limitations,
    }
    paths = write_access_report(
        payload, args.out_dir, title=args.title, stem=args.stem
    )
    print(f"\nWrote {paths['report']}")
    print(f"Wrote {paths['summary']}")


if __name__ == "__main__":
    main()
