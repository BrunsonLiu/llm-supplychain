"""Week 28: value-tiered order acceptance on the daily rolling flow."""
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
    summarize_value_acceptance,
    write_value_acceptance_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


SCENARIOS = {
    "atp_all": {
        "quote": "atp",
        "cutoff": 5,
        "top": None,
        "label": "ATP 接受全部",
    },
    "atp_3": {
        "quote": "atp",
        "cutoff": 3,
        "top": None,
        "label": "ATP 只接 ≤3 天",
    },
    "atp_3_top10": {
        "quote": "atp",
        "cutoff": 3,
        "top": 0.10,
        "label": "ATP ≤3 天 + 收入 Top 10% 破例",
    },
    "atp_3_top25": {
        "quote": "atp",
        "cutoff": 3,
        "top": 0.25,
        "label": "ATP ≤3 天 + 收入 Top 25% 破例",
    },
    "static_3": {
        "quote": "static",
        "cutoff": 3,
        "top": None,
        "label": "static 只接 ≤3 天",
    },
    "static_3_top10": {
        "quote": "static",
        "cutoff": 3,
        "top": 0.10,
        "label": "static ≤3 天 + 收入 Top 10% 破例",
    },
    "static_3_top25": {
        "quote": "static",
        "cutoff": 3,
        "top": 0.25,
        "label": "static ≤3 天 + 收入 Top 25% 破例",
    },
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 28 value-tiered order acceptance"
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
        default="atp_all,atp_3,atp_3_top10,atp_3_top25,"
        "static_3,static_3_top10,static_3_top25",
    )
    parser.add_argument(
        "--title", default="Value-tiered order acceptance (Week 28)"
    )
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
        raise ValueError("抽样订单收入为 0")
    thresholds = {
        "top10": float(np.quantile(order_revenue, 0.90)),
        "top25": float(np.quantile(order_revenue, 0.75)),
    }

    seeds = tuple(range(1, int(args.seeds) + 1))
    print("=" * 112)
    print(args.title)
    print("=" * 112)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | scenarios {selected} | "
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
    print(
        f"value thresholds: top10={thresholds['top10']:,.1f} "
        f"top25={thresholds['top25']:,.1f}"
    )

    baseline_alloc = prepare_baseline(
        instance,
        service_time=args.baseline_service_time,
        milp_time=args.baseline_milp_time,
        workers=args.workers,
    )
    baseline_cell = DispatchCell(
        key="week28_single_week_static",
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

    meta = {}
    for key in selected:
        spec = SCENARIOS[key]
        top = spec["top"]
        threshold = None
        value_label = "—"
        if top is not None:
            threshold = thresholds["top10" if top == 0.10 else "top25"]
            value_label = f"Top {int(top * 100)}% (≥{threshold:,.0f})"
        print(f"\n[{key}] preparing daily flow ...")
        flow = prepare_flow(
            instance,
            order_day,
            "daily_1d",
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy=spec["quote"],
            accept_cutoff_days=spec["cutoff"],
            accept_value_threshold=threshold,
            order_value=order_revenue if threshold is not None else None,
        )
        cell = DispatchCell(
            key=f"week28_{key}",
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
        frame["value_top"] = top if top is not None else "—"
        frame["value_label"] = value_label
        frames.append(frame)
        meta[key] = {
            "value_threshold": threshold,
            "value_top": top,
            "value_label": value_label,
        }
        print(
            f"  {key:<18} accepted {frame['accepted_orders'].mean():.1f} | "
            f"revenue {accepted_revenue:,.0f} "
            f"({accepted_revenue / demand_revenue:.1%}) | lost "
            f"{lost_revenue:,.0f} | accepted OTIF "
            f"{frame['accepted_otif_rate'].mean():.1%} | all "
            f"{frame['e2e_otif_rate'].mean():.1%}"
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_value_acceptance(frame)
    labels = {
        "single_week_static": "单周快照 · 固定承诺",
        **{key: spec["label"] for key, spec in SCENARIOS.items()},
    }
    quote_of = {
        "single_week_static": "static",
        **{key: spec["quote"] for key, spec in SCENARIOS.items()},
    }
    cutoff_of = {
        "single_week_static": "全部",
        **{
            key: ("全部" if key == "atp_all" else spec["cutoff"])
            for key, spec in SCENARIOS.items()
        },
    }
    summary["label"] = summary["policy"].map(labels).fillna(summary["policy"])
    summary["quote_policy"] = summary["policy"].map(quote_of).fillna("")
    summary["accept_cutoff"] = summary["policy"].map(cutoff_of).fillna("全部")
    summary["value_label"] = summary["policy"].map(
        {key: value["value_label"] for key, value in meta.items()}
    ).fillna("—")

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
            "scenarios": selected,
            "revenue_coverage": revenue_coverage,
            "value_thresholds": thresholds,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "limitations": [
            "价值阈值用本次 400 单的收入分位数（Top 10%/25%）计算，是样本内门槛，不是从历史外推的最优阈值；真实上线会面对收入漂移。",
            "收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。",
            "高价值破例只改“是否接受”，不预留库存、不提高优先级；接受后的高价值长承诺订单仍与所有订单竞争分单/拣选/发车，可能迟到。",
            "被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；接受池 OTIF/原 SLA 与全量 OTIF 是两个分母。",
            "ATP 只按当天开始时的在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。",
            "分单后不接收拣选/发车/门位失败的回写；补货是声明 order-up-to，1/2 天前置期。",
            "30 个种子在本配置下 OTIF/交付日/接单率完全相同，收入也是确定性的；不是 30 个独立需求样本。",
            "只验证 1 周、1 套库存/布局/劳动力；MILP 同配置可差约 1–1.5pp。",
        ],
    }
    paths = write_value_acceptance_report(
        payload, Path(args.out_dir), title=args.title
    )
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
