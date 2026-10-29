"""Week 26: same-day dispatch consolidation under daily replenishment."""
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
    prepare_flow,
    run_flow_e2e,
    summarize_consolidation,
    write_consolidation_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


MODE_LABELS = {
    "immediate": "立即发车（逐单）",
    "same6": "同日凑 6 单",
    "same12": "同日凑 12 单",
}
MODE_MIN_LOAD = {"immediate": 1, "same6": 6, "same12": 12}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 26 same-day dispatch consolidation"
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
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.15)
    parser.add_argument("--doors", default="1,2")
    parser.add_argument("--door-window", type=float, default=480.0)
    parser.add_argument(
        "--quote-policies", default="static,atp"
    )
    parser.add_argument("--modes", default="immediate,same6,same12")
    parser.add_argument(
        "--title", default="Same-day dispatch consolidation (Week 26)"
    )
    args = parser.parse_args()
    quotes = [value for value in args.quote_policies.split(",") if value]
    doors = [int(value) for value in args.doors.split(",") if value]
    modes = [value for value in args.modes.split(",") if value]
    unknown = set(modes) - set(MODE_LABELS)
    if unknown:
        raise ValueError(f"未知发车方式: {sorted(unknown)}")
    if not quotes or not doors or not modes:
        raise ValueError("报价、门位、发车方式都不能为空")
    if min(doors) < 0:
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
        f"doors {doors} | modes {modes} | daily {args.milp_time:.0f}s"
    )
    print(
        "orders by day: "
        + ", ".join(
            f"{day}:{int((order_day == day).sum())}"
            for day in range(int(order_day.max()) + 1)
        )
    )

    frames = []
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
            for mode in modes:
                cell = DispatchCell(
                    key=f"week26_{quote}_{door}_{mode}",
                    label=f"{FRONTIER_QUOTE_LABELS[quote]} · {door} 门 · "
                    f"{MODE_LABELS[mode]}",
                    policy="immediate" if mode == "immediate" else "hold",
                    min_load=MODE_MIN_LOAD[mode],
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
                frame["mode"] = mode
                frames.append(frame)
                print(
                    f"  {quote:<6} {door} door {mode:<9} quoted "
                    f"{frame['e2e_otif_rate'].mean():.1%} | static "
                    f"{frame['static_sla_otif_rate'].mean():.1%} | fill "
                    f"{frame['fill_rate'].mean():.1%} | dep "
                    f"{frame['departures'].mean():.1f} | blocked "
                    f"{frame['door_blocked'].mean():.1f} | roll "
                    f"{frame['roll_rate'].mean():.1%} | cost "
                    f"{frame['dock_cost'].mean():.0f}"
                )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_consolidation(frame)
    labels = {
        "static": "每日补货 · 固定 2/3/5",
        "atp": "每日补货 · ATP",
    }
    summary["label"] = summary["quote_policy"].map(labels).fillna(
        summary["quote_policy"]
    )
    summary["mode_label"] = summary["mode"].map(MODE_LABELS).fillna(
        summary["mode"]
    )

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
            "workers": args.workers,
            "pickers": args.pickers,
            "noise": args.noise,
            "quote_policies": quotes,
            "doors": doors,
            "modes": modes,
            "door_window_minutes": args.door_window,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "limitations": [
            "只做同日集批：max_days=0、hold_day=0，订单只在当天 13:00/19:00 两班之间等待；roll_rate 必须为0，否则已不是同日口径。",
            "min_load 是每条 lane（DC × 目的国）的门槛，不是每个 DC 的总单量；没有跨 lane/跨 DC 拼车。",
            "容量是 300 单/车，实测装载率只有约 3%，所以节省来自减少发车事件（220/车），不是装满车厢/体积。",
            "dock 成本只含发车 + 等待（0.15/单/小时），不含门位固定成本、司机工资、承运商阶梯价、迟到赔付；不能跨门位比较 dock_cost，因为 blocked 的车没有发。",
            "门位是每日分钟预算（480 分钟、75 分钟/车 + 0.5 分钟/票），不是具体门位占用；未模拟叉车、装卸工排班、司机等待。",
            "ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/取消。",
            "日滚动每天只允许当天发车（max_days=0）；分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期。",
            "30 个种子在本配置下 OTIF/交付日完全相同；不是 30 个独立样本。",
            "MILP 时间预算下同一配置不同运行可差约 1.5pp；只验证 1 周、1 套库存/布局/劳动力。",
        ],
    }
    paths = write_consolidation_report(
        payload, Path(args.out_dir), title=args.title
    )
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
