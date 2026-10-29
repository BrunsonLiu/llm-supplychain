"""Week 27: revenue-weighted order acceptance under daily replenishment."""
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
    prepare_baseline,
    prepare_flow,
    run_flow_e2e,
    run_single_week_e2e,
    summarize_revenue_acceptance,
    write_revenue_acceptance_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 27 revenue-weighted order acceptance"
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
    parser.add_argument(
        "--scenarios",
        default="static_all,atp_all,atp_3,atp_2,static_3",
        help="static_all/atp_all/atp_3/atp_2/static_3",
    )
    parser.add_argument(
        "--title", default="Revenue-weighted order acceptance (Week 27)"
    )
    args = parser.parse_args()
    scenarios = [value for value in args.scenarios.split(",") if value]
    allowed = {"static_all", "atp_all", "atp_3", "atp_2", "static_3"}
    unknown = set(scenarios) - allowed
    if unknown:
        raise ValueError(f"未知场景: {sorted(unknown)}")

    panel, _ = load_panel(args.panel)
    skus = sorted(panel["sku"].astype(str).unique())
    last_week = pd.to_datetime(panel["week"]).max()
    raw = load_online_retail_raw(args.xlsx, cache_path=args.raw_cache)
    clean, clean_stats = clean_transactions(raw)
    clean["sku"] = clean["sku"].astype(str)
    clean["invoice"] = clean["invoice"].astype(str)
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
        raise ValueError("抽样订单收入为 0，无法做收入口径")

    seeds = tuple(range(1, int(args.seeds) + 1))
    print("=" * 112)
    print(args.title)
    print("=" * 112)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | scenarios {scenarios} | "
        f"daily {args.milp_time:.0f}s | revenue {demand_revenue:,.0f} | "
        f"coverage {revenue_coverage:.1%}"
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
        key="week27_single_week_static",
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
    baseline["policy"] = "single_week_static"
    baseline["demand_revenue"] = demand_revenue
    baseline["accepted_revenue"] = demand_revenue
    baseline["lost_revenue"] = 0.0
    baseline["revenue_accept_rate"] = 1.0
    frames.append(baseline)
    print(
        f"  single_week static all quoted {baseline['e2e_otif_rate'].mean():.1%} | "
        f"revenue {demand_revenue:,.0f}"
    )

    for key in scenarios:
        quote = "static" if key.startswith("static") else "atp"
        cutoff = 5 if key.endswith("_all") else int(key.rsplit("_", 1)[1])
        print(f"\n[{key}] preparing daily flow (quote={quote}, cutoff={cutoff}) ...")
        flow = prepare_flow(
            instance,
            order_day,
            "daily_1d",
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy=quote,
            accept_cutoff_days=cutoff,
        )
        cell = DispatchCell(
            key=f"week27_{key}",
            label=key,
            policy="immediate",
            min_load=1,
            max_days=0,
            pickers_per_dc=args.pickers,
            duration_noise=args.noise,
        )
        frame = run_flow_e2e(
            flow, instance, order_day, seeds, arrivals, cell
        )
        accepted = np.asarray(flow.accepted, dtype=bool)
        accepted_revenue = float(order_revenue[accepted].sum())
        lost_revenue = float(demand_revenue - accepted_revenue)
        frame["policy"] = key
        frame["demand_revenue"] = demand_revenue
        frame["accepted_revenue"] = accepted_revenue
        frame["lost_revenue"] = lost_revenue
        frame["revenue_accept_rate"] = (
            accepted_revenue / demand_revenue if demand_revenue else 0.0
        )
        frames.append(frame)
        print(
            f"  {key:<12} accepted {frame['accepted_orders'].mean():.1f} | "
            f"revenue {accepted_revenue:,.0f} ({accepted_revenue / demand_revenue:.1%}) | "
            f"lost {lost_revenue:,.0f} | accepted OTIF "
            f"{frame['accepted_otif_rate'].mean():.1%}"
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_revenue_acceptance(frame)
    labels = {
        "single_week_static": "单周快照 · 固定承诺",
        "static_all": "每日补货 · 接受全部",
        "atp_all": "每日补货 · ATP 接受全部",
        "atp_3": "每日补货 · ATP 只接 ≤3 天",
        "atp_2": "每日补货 · ATP 只接 ≤2 天",
        "static_3": "每日补货 · 固定承诺只接 ≤3 天",
    }
    quote_of = {
        "single_week_static": "static",
        "static_all": "static",
        "atp_all": "atp",
        "atp_3": "atp",
        "atp_2": "atp",
        "static_3": "static",
    }
    cutoff_of = {
        "single_week_static": "全部",
        "static_all": "全部",
        "atp_all": "全部",
        "atp_3": 3,
        "atp_2": 2,
        "static_3": 3,
    }
    summary["label"] = summary["policy"].map(labels).fillna(summary["policy"])
    summary["quote_policy"] = summary["policy"].map(quote_of).fillna("")
    summary["accept_cutoff"] = summary["policy"].map(cutoff_of).fillna("全部")

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
            "scenarios": scenarios,
            "revenue_coverage": revenue_coverage,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "limitations": [
            "收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。",
            "被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；收入接单率以全部需求收入为分母。",
            "接受池 OTIF/原 SLA 只对接受池计算；全量 OTIF 把被拒订单当未履约；订单/单位/收入三个接单率必须一起看。",
            "ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。",
            "分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期，不做预测/MOQ/供应商产能/DC 调拨。",
            "30 个种子在本配置下 OTIF/交付日完全相同，接受率与收入也是确定性的；不是 30 个独立需求样本。",
            "收入覆盖按订单发票匹配，未匹配的行按 0 收入；只验证 1 周、1 套库存/布局/劳动力。",
        ],
    }
    paths = write_revenue_acceptance_report(
        payload, Path(args.out_dir), title=args.title
    )
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
