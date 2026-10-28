"""Week 25: promise policy x dock-door interaction under daily replenishment."""
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
    FRONTIER_QUOTE_LABELS,
    build_e2e_instance,
    fit_empirical_arrivals,
    order_day_map,
    prepare_baseline,
    prepare_flow,
    run_flow_e2e,
    run_single_week_e2e,
    summarize_promise_door,
    write_promise_door_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 25 promise policy x dock doors"
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
    parser.add_argument("--doors", default="0,1,2")
    parser.add_argument("--door-window", type=float, default=480.0)
    parser.add_argument(
        "--quote-policies", default="static,atp,all_3,all_5"
    )
    parser.add_argument(
        "--title", default="Promise policy x dock doors (Week 25)"
    )
    args = parser.parse_args()
    quotes = [value for value in args.quote_policies.split(",") if value]
    doors = [int(value) for value in args.doors.split(",") if value]
    if not quotes:
        raise ValueError("至少需要一个报价策略")
    if not doors or min(doors) < 0:
        raise ValueError("门位必须是非负整数")
    for quote in quotes:
        if quote not in FRONTIER_QUOTE_LABELS:
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
        f"orders {instance.n_orders} | seeds {len(seeds)} | quotes {quotes} | "
        f"doors {doors} | window {args.door_window:.0f} min | "
        f"daily {args.milp_time:.0f}s"
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
        key="week25_single_week_static_0",
        label="单周快照 · 固定承诺 · 0 门",
        policy="promise",
        min_load=6,
        max_days=3,
        doors_per_dc=0,
        door_window_minutes=args.door_window,
        pickers_per_dc=args.pickers,
        duration_noise=args.noise,
    )
    frames = []
    baseline = run_single_week_e2e(
        instance, baseline_alloc, seeds, arrivals, baseline_cell
    )
    baseline["quote_policy"] = "static"
    baseline["door"] = "—"
    frames.append(baseline)
    print(
        f"  single_week static 0-door quoted "
        f"{baseline['e2e_otif_rate'].mean():.1%}"
    )

    for quote in quotes:
        print(f"\n[{quote}] preparing daily flow ...")
        flow = prepare_flow(
            instance,
            order_day,
            "daily_1d",
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy=quote,
        )
        for door in doors:
            cell = DispatchCell(
                key=f"week25_{quote}_{door}",
                label=f"{FRONTIER_QUOTE_LABELS[quote]} · {door} 门",
                policy="immediate",
                min_load=1,
                max_days=0,
                doors_per_dc=door,
                door_window_minutes=args.door_window,
                pickers_per_dc=args.pickers,
                duration_noise=args.noise,
            )
            frame = run_flow_e2e(
                flow, instance, order_day, seeds, arrivals, cell
            )
            frame["quote_policy"] = quote
            frame["door"] = int(door)
            frames.append(frame)
            print(
                f"  {quote:<9} {door} door quoted "
                f"{frame['e2e_otif_rate'].mean():.1%} | static "
                f"{frame['static_sla_otif_rate'].mean():.1%} | fill "
                f"{frame['fill_rate'].mean():.1%} | blocked "
                f"{frame['door_blocked'].mean():.1f} | util "
                f"{frame['door_utilization'].mean():.1%}"
            )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_promise_door(frame)
    labels = {
        "single_week": "单周快照",
        "static": "每日补货 · 固定 2/3/5",
        "atp": "每日补货 · ATP",
        "atp_buffer": "每日补货 · ATP+缓冲",
        "all_2": "每日补货 · 全部 2 天",
        "all_3": "每日补货 · 全部 3 天",
        "all_5": "每日补货 · 全部 5 天",
    }
    summary["label"] = summary["quote_policy"].map(labels).fillna(
        summary["quote_policy"]
    )
    summary.loc[summary["door"] == "—", "label"] = "单周快照"
    summary["quote_label"] = summary["quote_policy"].map(
        FRONTIER_QUOTE_LABELS
    ).fillna(summary["quote_policy"])

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
            "quote_policies": quotes,
            "doors": doors,
            "door_window_minutes": args.door_window,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "limitations": [
            "门位是每日分钟预算（480 分钟、75 分钟/车 + 0.5 分钟/票），不是具体门位占用；未模拟叉车、装卸工排班、司机等待。",
            "0 门位表示模型中没有门位分钟预算，不是无限真实装卸能力；结论只针对该预算是否绑定。",
            "每个报价策略重解日滚动分单，quote 同时是分单截止期，fill/backlog 会随策略变化；门位差异与分单差异混合。",
            "ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/取消。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。",
            "分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期。",
            "30 个种子在本配置下 OTIF/交付日完全相同；不是 30 个独立样本。",
            "MILP 时间预算下同一配置不同运行可差约 1pp；只验证 1 周、1 套库存/布局/劳动力。",
        ],
    }
    paths = write_promise_door_report(
        payload, Path(args.out_dir), title=args.title
    )
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
