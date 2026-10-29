"""Week 34: one vs two pickers per DC, with and without high-value priority."""
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
    summarize_capacity,
    write_capacity_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402


SCENARIOS = {
    "atp_all_1p": {
        "cutoff": 5,
        "top": None,
        "pickers": 1,
        "pick": False,
        "target": "top10",
        "label": "ATP 接受全部 · 1 拣货员",
    },
    "atp_all_2p": {
        "cutoff": 5,
        "top": None,
        "pickers": 2,
        "pick": False,
        "target": "top10",
        "label": "ATP 接受全部 · 2 拣货员",
    },
    "atp_3_top10_1p": {
        "cutoff": 3,
        "top": 0.10,
        "pickers": 1,
        "pick": False,
        "target": "top10",
        "label": "Top10 破例 · 1 拣货员 EDF",
    },
    "atp_3_top10_2p": {
        "cutoff": 3,
        "top": 0.10,
        "pickers": 2,
        "pick": False,
        "target": "top10",
        "label": "Top10 破例 · 2 拣货员 EDF",
    },
    "atp_3_top10_2p_pick": {
        "cutoff": 3,
        "top": 0.10,
        "pickers": 2,
        "pick": True,
        "target": "top10",
        "label": "Top10 破例 · 2 拣货员 + 优先拣选",
    },
    "atp_3_top25_1p": {
        "cutoff": 3,
        "top": 0.25,
        "pickers": 1,
        "pick": False,
        "target": "top25",
        "label": "Top25 破例 · 1 拣货员 EDF",
    },
    "atp_3_top25_2p": {
        "cutoff": 3,
        "top": 0.25,
        "pickers": 2,
        "pick": False,
        "target": "top25",
        "label": "Top25 破例 · 2 拣货员 EDF",
    },
    "atp_3_top25_2p_pick": {
        "cutoff": 3,
        "top": 0.25,
        "pickers": 2,
        "pick": True,
        "target": "top25",
        "label": "Top25 破例 · 2 拣货员 + 优先拣选",
    },
}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Week 34 extra pick capacity")
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
    parser.add_argument("--shift-minutes", type=float, default=600.0)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--service-time", type=float, default=3.0)
    parser.add_argument("--milp-time", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--lookback-weeks", type=int, default=6)
    parser.add_argument("--noise", type=float, default=0.15)
    parser.add_argument(
        "--scenarios",
        default="atp_all_1p,atp_all_2p,"
        "atp_3_top10_1p,atp_3_top10_2p,atp_3_top10_2p_pick,"
        "atp_3_top25_1p,atp_3_top25_2p,atp_3_top25_2p_pick",
    )
    parser.add_argument("--title", default="Extra pick capacity (Week 34)")
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
        pickers_per_dc=1,
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
    masks = {
        "top10": order_revenue >= thresholds["top10"],
        "top25": order_revenue >= thresholds["top25"],
    }

    seeds = tuple(range(1, int(args.seeds) + 1))
    print("=" * 120)
    print(args.title)
    print("=" * 120)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | scenarios {selected} | "
        f"daily {args.milp_time:.0f}s | revenue {demand_revenue:,.0f} | "
        f"coverage {revenue_coverage:.1%}"
    )
    print(
        f"thresholds: top10={thresholds['top10']:,.1f} "
        f"top25={thresholds['top25']:,.1f}"
    )

    frames = []
    meta = {}

    def add_run(key: str, flow, target, pickers: int, pick: bool) -> None:
        spec = SCENARIOS[key]
        cell = DispatchCell(
            key=f"week34_{key}",
            label=key,
            policy="immediate",
            min_load=1,
            max_days=0,
            pickers_per_dc=pickers,
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
            pick_priority_orders=(
                np.flatnonzero(target) if pick else None
            ),
        )
        accepted = np.asarray(flow.accepted, dtype=bool)
        accepted_revenue = float(order_revenue[accepted].sum())
        frame["policy"] = key
        frame["demand_revenue"] = demand_revenue
        frame["accepted_revenue"] = accepted_revenue
        frame["lost_revenue"] = float(demand_revenue - accepted_revenue)
        frame["revenue_accept_rate"] = (
            accepted_revenue / demand_revenue if demand_revenue else 0.0
        )
        frames.append(frame)
        meta[key] = {
            "label": spec["label"],
            "target_label": f"Top {int(spec['top'] * 100)}%"
            if spec["top"] is not None
            else "Top 10%",
        }
        print(
            f"  {key:<24} p{pickers} accepted {frame['accepted_orders'].mean():.1f} | "
            f"accepted OTIF {frame['accepted_otif_rate'].mean():.1%} | target "
            f"{frame['target_accepted_otif_rate'].mean():.1%} | rest "
            f"{frame['rest_accepted_otif_rate'].mean():.1%} | all "
            f"{frame['e2e_otif_rate'].mean():.1%} | labor "
            f"{frame['labor_minutes'].mean():,.0f} | pick span "
            f"{frame['pick_makespan_minutes'].mean():.0f}"
        )

    if "atp_all_1p" in selected or "atp_all_2p" in selected:
        print("\n[atp_all] preparing one daily flow ...")
        flow_all = prepare_flow(
            instance,
            order_day,
            "daily_1d",
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy="atp",
            accept_cutoff_days=5,
        )
        if "atp_all_1p" in selected:
            add_run("atp_all_1p", flow_all, masks["top10"], 1, False)
        if "atp_all_2p" in selected:
            add_run("atp_all_2p", flow_all, masks["top10"], 2, False)

    for target_key in ("top10", "top25"):
        keys = [
            f"atp_3_{target_key}_1p",
            f"atp_3_{target_key}_2p",
            f"atp_3_{target_key}_2p_pick",
        ]
        if not any(key in selected for key in keys):
            continue
        target = masks[target_key]
        print(f"\n[{target_key}] preparing one daily flow for 1p/2p/2p+priority ...")
        flow = prepare_flow(
            instance,
            order_day,
            "daily_1d",
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            quote_policy="atp",
            accept_cutoff_days=3,
            accept_value_threshold=thresholds[target_key],
            order_value=order_revenue,
        )
        if keys[0] in selected:
            add_run(keys[0], flow, target, 1, False)
        if keys[1] in selected:
            add_run(keys[1], flow, target, 2, False)
        if keys[2] in selected:
            add_run(keys[2], flow, target, 2, True)

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_capacity(frame)
    summary["label"] = summary["policy"].map(
        {key: value["label"] for key, value in meta.items()}
    )
    summary["target_label"] = summary["policy"].map(
        {key: value["target_label"] for key, value in meta.items()}
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
            "workers": args.workers,
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
            "1/2 拣货员共用同一 prepared flow（接受/库存分配固定），只改拣选劳动力；不模拟第二拣货员工资、招聘/培训、工位/设备约束。",
            "收入来自 Online Retail II 发票行 `quantity × UnitPrice`，是毛收入，不是毛利/净利；没有 COGS、退货、履约成本、门位/发车成本与客户终身价值。",
            "目标客群 Top10/Top25 由本次 400 单收入分位数定义，是样本内分层；不是真实客户价值/毛利分层。",
            "被拒订单按即期流失处理：不消耗库存、不重试、不转替代品、不计收入；同一 flow 下接单/收入按构造不变。",
            "ATP 只按当天开始时在库量报价，不预留在途/未来/跨订单库存；旧订单不重报价，不模拟客户接受/拒绝/取消。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线允许 3 天且所有订单视作周一。",
            "30 个种子在本配置下 OTIF/交付日/接单率完全相同；差异是确定性的资源效应，不是 30 个独立样本。",
            "只验证 1 周、1 套库存/布局/班次；2 拣货员共用 600 分钟班次；MILP/发车同配置可差约 1–1.5pp，小差异可能落在求解器噪声内。",
        ],
    }
    paths = write_capacity_report(payload, Path(args.out_dir), title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
