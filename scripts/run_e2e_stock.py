"""Week 36: stock availability 85% vs 100% at the same accepted orders."""
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
    build_e2e_instance,
    fit_empirical_arrivals,
    order_day_map,
    prepare_flow,
    run_flow_e2e,
    summarize_stock,
    write_stock_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


SCENARIOS = {
    "atp_all_85": {"stock": 0.85, "label": "ATP 接受全部 · 85% 库存"},
    "atp_all_100": {"stock": 1.00, "label": "ATP 接受全部 · 100% 库存"},
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Week 36 stock availability")
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
    parser.add_argument("--scenarios", default="atp_all_85,atp_all_100")
    parser.add_argument("--title", default="Stock availability (Week 36)")
    args = parser.parse_args()
    selected = [value for value in args.scenarios.split(",") if value]
    unknown = set(selected) - set(SCENARIOS)
    if unknown:
        raise ValueError(f"未知场景: {sorted(unknown)}")

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()
    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    clean["invoice"] = clean["invoice"].astype(str)

    first = None
    for key in selected:
        factor = SCENARIOS[key]["stock"]
        built = build_e2e_instance(
            clean,
            skus,
            sample_orders=args.orders,
            max_lines=args.max_lines,
            stock_factor=factor,
            seed=args.seed,
            week=last_week,
            pickers_per_dc=args.pickers,
            shift_minutes=args.shift_minutes,
            arrival_seed=1,
        )
        if first is None:
            first = built
        elif (
            list(built.fulfillment.order_ids)
            != list(first.fulfillment.order_ids)
        ):
            raise ValueError("不同库存因子的订单样本不一致")

    assert first is not None
    instance = first
    order_day = order_day_map(instance, clean)
    arrivals = fit_empirical_arrivals(
        clean, last_week, lookback_weeks=args.lookback_weeks
    )
    invoice_revenue = clean.groupby("invoice")["revenue"].sum()
    order_revenue = np.array(
        [
            float(invoice_revenue.get(str(invoice), 0.0))
            for invoice in instance.fulfillment.order_ids
        ],
        dtype=float,
    )
    demand_revenue = float(order_revenue.sum())
    revenue_coverage = (
        float((order_revenue > 0).mean()) if len(order_revenue) else 0.0
    )
    if demand_revenue <= 0:
        raise ValueError("抽样订单收入为 0")
    top10_threshold = float(np.quantile(order_revenue, 0.90))
    target = order_revenue >= top10_threshold

    seeds = tuple(range(1, int(args.seeds) + 1))
    print("=" * 120)
    print(args.title)
    print("=" * 120)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | scenarios {selected} | "
        f"daily {args.milp_time:.0f}s | revenue {demand_revenue:,.0f} | "
        f"coverage {revenue_coverage:.1%}"
    )

    frames = []
    for key in selected:
        factor = SCENARIOS[key]["stock"]
        built = build_e2e_instance(
            clean,
            skus,
            sample_orders=args.orders,
            max_lines=args.max_lines,
            stock_factor=factor,
            seed=args.seed,
            week=last_week,
            pickers_per_dc=args.pickers,
            shift_minutes=args.shift_minutes,
            arrival_seed=1,
        )
        print(f"\n[{key}] preparing daily flow at stock {factor:.0%} ...")
        flow = prepare_flow(
            built,
            order_day,
            "daily_1d",
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy="atp",
            accept_cutoff_days=5,
        )
        cell = DispatchCell(
            key=f"week36_{key}",
            label=key,
            policy="immediate",
            min_load=1,
            max_days=0,
            pickers_per_dc=args.pickers,
            duration_noise=args.noise,
        )
        frame = run_flow_e2e(
            flow,
            built,
            order_day,
            seeds,
            arrivals,
            cell,
            segments={"target": target, "rest": ~target},
        )
        accepted = np.asarray(flow.accepted, dtype=bool)
        accepted_revenue = float(order_revenue[accepted].sum())
        frame["policy"] = key
        frame["stock_factor"] = factor
        frame["demand_revenue"] = demand_revenue
        frame["accepted_revenue"] = accepted_revenue
        frame["lost_revenue"] = float(demand_revenue - accepted_revenue)
        frame["revenue_accept_rate"] = (
            accepted_revenue / demand_revenue if demand_revenue else 0.0
        )
        frames.append(frame)
        print(
            f"  {key:<16} accepted {frame['accepted_orders'].mean():.1f} | "
            f"accepted OTIF {frame['accepted_otif_rate'].mean():.1%} | target "
            f"{frame['target_accepted_otif_rate'].mean():.1%} | rest "
            f"{frame['rest_accepted_otif_rate'].mean():.1%} | all "
            f"{frame['e2e_otif_rate'].mean():.1%} | fill "
            f"{frame['accepted_fill_rate'].mean():.1%} | backlog "
            f"{frame['accepted_backlog_units'].mean():,.0f}"
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_stock(frame)

    payload = {
        "dataset": {
            **instance.meta,
            "orders": instance.n_orders,
            "lines": instance.meta["order_lines"],
            "units": int(instance.fulfillment.line_qty.sum()),
            "week": str(last_week.date()),
            "clean_rows": clean_stats["clean_rows"],
            "dcs": list(instance.fulfillment.dc_names),
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
            "scenarios": selected,
            "revenue_coverage": revenue_coverage,
            "stock_factors": [SCENARIOS[key]["stock"] for key in selected],
            "target_top_share": 0.10,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "limitations": [
            "85%→100% 只改库存快照，不建模采购/在途/仓储成本、COGS、持有成本、过期/跌价；100% 是上界，不是补货计划。",
            "两个库存因子共用同一 400 单样本与 ATP accept-all（接受集/需求分母相同），但库存变化会改变日滚动分配/补货路径，仍属于情景比较。",
            "收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有退货、履约成本、门位/发车成本与客户终身价值。",
            "目标客群 Top10 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。",
            "被拒订单按即期流失处理；本实验 ATP 接受全部，因此 lost_orders=0，接受池=全量。",
            "ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。",
            "30 个种子在本配置下 OTIF/交付日完全相同；库存差异是确定性的可用量效应，不是 30 个独立样本。",
            "只验证 1 周、1 套库存布局/班次；100% 仍受 DC 分布、DC 产能、transit/promise 约束；MILP 8s/day 可差约 1–1.5pp。",
        ],
    }
    paths = write_stock_report(payload, Path(args.out_dir), title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
