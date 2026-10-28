"""Week 23: promise-service frontier for daily rolling replenishment."""
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
    FRONTIER_QUOTE_POLICIES,
    build_e2e_instance,
    fit_empirical_arrivals,
    order_day_map,
    prepare_baseline,
    prepare_flow,
    run_flow_e2e,
    run_single_week_e2e,
    service_frontiers,
    summarize_frontier,
    write_promise_frontier_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 23 promise-service frontier under daily replenishment"
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
    parser.add_argument("--pickers", type=int, default=1)
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--service-time", type=float, default=3.0)
    parser.add_argument("--milp-time", type=float, default=8.0)
    parser.add_argument("--baseline-milp-time", type=float, default=60.0)
    parser.add_argument("--baseline-service-time", type=float, default=30.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.15)
    parser.add_argument("--policy", default="daily_1d")
    parser.add_argument(
        "--quote-policies", default="static,atp,atp_buffer,all_2,all_3,all_5"
    )
    parser.add_argument(
        "--title", default="Promise-service frontier under daily replenishment (Week 23)"
    )
    args = parser.parse_args()
    quotes = [value for value in args.quote_policies.split(",") if value]
    for quote in quotes:
        if quote not in FRONTIER_QUOTE_POLICIES:
            raise ValueError(f"未知报价策略: {quote}")

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
    order_day = order_day_map(instance, clean)
    arrivals = fit_empirical_arrivals(
        clean, last_week, lookback_weeks=args.lookback_weeks
    )
    seeds = tuple(range(1, int(args.seeds) + 1))
    print("=" * 112)
    print(args.title)
    print("=" * 112)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | policy {args.policy} | "
        f"quotes {quotes} | daily {args.milp_time:.0f}s | baseline "
        f"{args.baseline_milp_time:.0f}s"
    )
    print(
        "orders by day: "
        + ", ".join(
            f"{day}:{int((order_day == day).sum())}"
            for day in range(int(order_day.max()) + 1)
        )
    )

    baseline_alloc = prepare_baseline(
        instance,
        service_time=args.baseline_service_time,
        milp_time=args.baseline_milp_time,
        workers=args.workers,
    )
    baseline_cell = DispatchCell(
        key="week23_single_week_static",
        label="单周快照 · 固定承诺",
        policy="promise",
        min_load=6,
        max_days=3,
        pickers_per_dc=args.pickers,
        duration_noise=args.noise,
    )
    frames = []
    baseline = run_single_week_e2e(
        instance, baseline_alloc, seeds, arrivals, baseline_cell
    )
    baseline["quote_policy"] = "static"
    frames.append(baseline)
    print(
        f"  single_week static quoted {baseline['e2e_otif_rate'].mean():.1%} | "
        f"static {baseline['static_sla_otif_rate'].mean():.1%}"
    )

    for quote in quotes:
        print(f"\n[{args.policy} · {quote}] preparing daily flow ...")
        flow = prepare_flow(
            instance,
            order_day,
            args.policy,
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy=quote,
        )
        cell = DispatchCell(
            key=f"week23_{args.policy}_{quote}",
            label=f"每日 1 天补货 · {quote}",
            policy="immediate",
            min_load=1,
            max_days=0,
            pickers_per_dc=args.pickers,
            duration_noise=args.noise,
        )
        frame = run_flow_e2e(
            flow, instance, order_day, seeds, arrivals, cell
        )
        frame["quote_policy"] = quote
        frames.append(frame)
        print(
            f"  {quote:<10} quoted {frame['e2e_otif_rate'].mean():.1%} | "
            f"static {frame['static_sla_otif_rate'].mean():.1%} | "
            f"promise {frame['avg_promise_days'].mean():.2f}d | "
            f"fill {frame['fill_rate'].mean():.1%}"
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_frontier(frame)
    daily = summary[summary["policy"] != "single_week"].to_dict("records")
    daily = service_frontiers(daily)
    baseline_row = summary[summary["policy"] == "single_week"].to_dict("records")
    if baseline_row:
        baseline_row[0]["static_pareto"] = False
        baseline_row[0]["quoted_pareto"] = False
        baseline_row[0]["static_dominated_by"] = ""
        baseline_row[0]["quoted_dominated_by"] = ""
    annotated = baseline_row + daily

    payload = {
        "dataset": {
            **instance.meta,
            "orders": instance.n_orders,
            "lines": instance.meta["order_lines"],
            "units": int(instance.fulfillment.line_qty.sum()),
            "week": str(last_week.date()),
            "clean_rows": clean_stats["clean_rows"],
            "dcs": list(instance.fulfillment.dc_names),
        },
        "settings": {
            "orders": args.orders,
            "max_lines": args.max_lines,
            "stock_factor": args.stock_factor,
            "seed": args.seed,
            "seeds": args.seeds,
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "baseline_milp_time": args.baseline_milp_time,
            "baseline_service_time": args.baseline_service_time,
            "workers": args.workers,
            "pickers": args.pickers,
            "noise": args.noise,
            "policy": args.policy,
            "quote_policies": quotes,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": annotated,
        "rows": frame.to_dict("records"),
        "limitations": [
            "每个报价方案都重新求解日滚动分单；quote 同时是分单截止期，因此 fill/backlog 会随方案变化，前沿不是纯文案比较。",
            "ATP 只按当天开始时的在库量报价，不预留在途补货、未来到达或跨订单库存；同一天多张订单可能同时报 2 天。",
            "旧订单保留到达时的绝对承诺日，不改单/不重报价；不模拟客户接受/拒绝/取消。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且把所有订单视作周一。",
            "分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期，不做预测/MOQ/供应商产能/DC 调拨。",
            "30 个种子在本配置下 OTIF/交付日完全相同，前沿上的点是确定性边界，不是 30 个独立样本。",
            "原 SLA 用 Week-20 固定 2/3/5 承诺，不是客户真实容忍度；只验证 1 周、1 套库存/布局/劳动力。",
            "Pareto 只在本次观测到的策略集合内成立；all_2/all_3/all_5 是压力测试，不代表商业上可接受的承诺菜单。",
        ],
    }
    paths = write_promise_frontier_report(
        payload, Path(args.out_dir), title=args.title
    )
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
