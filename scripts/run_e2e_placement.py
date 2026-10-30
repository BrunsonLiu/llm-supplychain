"""Week 40: fixed-total stock rebalance at 100% stock, 2x capacity, transit -1.

Run:
    PYTHONPATH=src;. python scripts/run_e2e_placement.py
Smoke:
    PYTHONPATH=src;. python scripts/run_e2e_placement.py --orders 80 --seeds 3 \
        --milp-time 2 --service-time 1 --placements baseline,balanced --workers 2
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
    order_day_map,
    prepare_flow,
    run_flow_e2e,
    summarize_placement,
    write_placement_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


PLACEMENTS = {
    "baseline": {
        "shares": (0.34, 0.28, 0.38),
        "label": "基线 34/28/38",
    },
    "balanced": {
        "shares": (0.33, 0.33, 0.34),
        "label": "均衡 33/33/34",
    },
    "rotterdam": {
        "shares": (0.30, 0.40, 0.30),
        "label": "Rotterdam 偏重 30/40/30",
    },
    "london": {
        "shares": (0.40, 0.24, 0.36),
        "label": "London 偏重 40/24/36",
    },
}


def _build(clean, skus, args, shares, last_week):
    return build_e2e_instance(
        clean,
        skus,
        sample_orders=args.orders,
        max_lines=args.max_lines,
        stock_factor=1.0,
        stock_shares=shares,
        seed=args.seed,
        week=last_week,
        pickers_per_dc=args.pickers,
        shift_minutes=args.shift_minutes,
        arrival_seed=1,
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Week 40 fixed-total placement")
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
    parser.add_argument("--service-time", type=float, default=3.0)
    parser.add_argument("--milp-time", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.15)
    parser.add_argument(
        "--placements", default="baseline,balanced,rotterdam,london"
    )
    parser.add_argument("--title", default="Fixed-total stock rebalance (Week 40)")
    args = parser.parse_args()
    selected = [value for value in args.placements.split(",") if value]
    unknown = set(selected) - set(PLACEMENTS)
    if unknown:
        raise ValueError(f"未知布点: {sorted(unknown)}")
    if "baseline" not in selected:
        raise ValueError("必须包含 baseline 作为对照")

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()
    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    clean["invoice"] = clean["invoice"].astype(str)

    first = None
    stock_totals = {}
    for key in selected:
        built = _build(clean, skus, args, PLACEMENTS[key]["shares"], last_week)
        if first is None:
            first = built
        elif list(built.fulfillment.order_ids) != list(first.fulfillment.order_ids):
            raise ValueError("不同布点的订单样本不一致")
        stock_totals[key] = int(built.fulfillment.stock.sum())

    assert first is not None
    if len(set(stock_totals.values())) != 1:
        raise ValueError(f"固定总量校验失败: {stock_totals}")

    order_day = order_day_map(first, clean)
    arrivals = fit_empirical_arrivals(
        clean, last_week, lookback_weeks=args.lookback_weeks
    )
    invoice_revenue = clean.groupby("invoice")["revenue"].sum()
    order_revenue = np.array(
        [
            float(invoice_revenue.get(str(invoice), 0.0))
            for invoice in first.fulfillment.order_ids
        ],
        dtype=float,
    )
    demand_revenue = float(order_revenue.sum())
    revenue_coverage = (
        float((order_revenue > 0).mean()) if len(order_revenue) else 0.0
    )
    if demand_revenue <= 0:
        raise ValueError("抽样订单收入为 0")
    target = order_revenue >= float(np.quantile(order_revenue, 0.90))

    seeds = tuple(range(1, int(args.seeds) + 1))
    print("=" * 120)
    print(args.title)
    print("=" * 120)
    print(
        f"orders {first.n_orders} | seeds {len(seeds)} | placements {selected} | "
        f"stock {stock_totals['baseline']:,} units (fixed) | "
        f"daily {args.milp_time:.0f}s | revenue {demand_revenue:,.0f}"
    )

    frames = []
    for key in selected:
        shares = PLACEMENTS[key]["shares"]
        built = _build(clean, skus, args, shares, last_week)
        instance = replace(
            built,
            fulfillment=replace(
                built.fulfillment,
                dc_capacity=np.maximum(
                    1, np.round(built.fulfillment.dc_capacity * 2.0)
                ).astype(np.int64),
                transit_days=np.maximum(
                    1, built.fulfillment.transit_days - 1
                ).astype(np.int64),
            ),
        )
        print(f"\n[{key}] {PLACEMENTS[key]['label']} | stock shares {shares} ...")
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
            key=f"week40_{key}",
            label=key,
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
            segments={"target": target, "rest": ~target},
        )
        accepted = np.asarray(flow.accepted, dtype=bool)
        accepted_revenue = float(order_revenue[accepted].sum())
        frame["placement"] = key
        frame["label"] = PLACEMENTS[key]["label"]
        frame["shares"] = "/".join(f"{value:.0%}" for value in shares)
        frame["stock_factor"] = 1.0
        frame["stock_units"] = int(built.fulfillment.stock.sum())
        frame["dc_capacity_factor"] = 2.0
        frame["transit_cut_days"] = 1
        frame["demand_revenue"] = demand_revenue
        frame["accepted_revenue"] = accepted_revenue
        frame["lost_revenue"] = float(demand_revenue - accepted_revenue)
        frame["revenue_accept_rate"] = (
            accepted_revenue / demand_revenue if demand_revenue else 0.0
        )
        frames.append(frame)
        print(
            f"  {key:<10} accepted {frame['accepted_orders'].mean():.1f} | "
            f"accepted OTIF {frame['accepted_otif_rate'].mean():.1%} | target "
            f"{frame['target_accepted_otif_rate'].mean():.1%} | rest "
            f"{frame['rest_accepted_otif_rate'].mean():.1%} | all "
            f"{frame['e2e_otif_rate'].mean():.1%} | backlog "
            f"{frame['accepted_backlog_units'].mean():,.0f}"
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_placement(frame)
    full_scale = args.orders >= 400 and args.seeds >= 30 and len(selected) >= 4
    limitations = [
        "只改 DC 库存占比，每个 SKU 的总库存固定在 100% 需求；不建模采购、在途、仓储成本、COGS、持有成本、过期/跌价。",
        "库存占比只扫 4 个声明布点（34/28/38、33/33/34、30/40/30、40/24/36），不是全可行域上的优化；null 不等于所有重摆位都无效。",
        "库存按 SKU 总量加确定性 0.75–1.25 jitter 分配，jitter 随 seed 固定；不同布点的总库存相同但 SKU×DC 分布仍受 jitter 影响。",
        "所有臂 2× DC 产能、transit −1、ATP accept-all，接受集/需求分母相同；仍只有 1 个目标周、1 套布局/班次。",
        "目标是样本内收入 Top10，不是外推客户价值；毛收入无退货/履约成本。",
        "日滚动只允许当天发车（max_days=0），与单周基线的发车自由度不同；不跨周比较绝对 OTIF。",
    ]
    if full_scale:
        limitations += [
            "CP-SAT 8s/day 时间受限：同一 34/28/38 baseline 的 400×30 重复运行得到 92.5/95.0/97.5 目标 OTIF（5pp 跨度），臂间 2–3pp 差异落在该波动内，不能当因果效应。",
            "库存布点只做 4 个声明的 DC 占比，不是全可行域优化；排名在两次运行间翻转（Rotterdam 97.5→95.0），固定总量重摆位没有稳健收益。",
        ]

    payload = {
        "dataset": {
            **first.meta,
            "orders": first.n_orders,
            "lines": first.meta["order_lines"],
            "units": int(first.fulfillment.line_qty.sum()),
            "week": str(last_week.date()),
            "clean_rows": clean_stats["clean_rows"],
            "dcs": list(first.fulfillment.dc_names),
            "demand_revenue": demand_revenue,
        },
        "settings": {
            "orders": args.orders,
            "max_lines": args.max_lines,
            "seed": args.seed,
            "seeds": args.seeds,
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "pickers": args.pickers,
            "noise": args.noise,
            "placements": selected,
            "stock_factor": 1.0,
            "stock_units": stock_totals,
            "dc_capacity_factor": 2.0,
            "transit_cut_days": 1,
            "target_top_share": 0.10,
            "revenue_coverage": revenue_coverage,
            "solver_noise_pp": 5.0 if full_scale else 0.0,
            "baseline_repeats": [92.5, 95.0, 97.5] if full_scale else [],
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "limitations": limitations,
    }
    paths = write_placement_report(payload, args.out_dir, title=args.title)
    print(f"\nWrote {paths['report']}")
    print(f"Wrote {paths['summary']}")


if __name__ == "__main__":
    main()
