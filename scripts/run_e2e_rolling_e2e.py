"""Week 20: daily rolling allocation + picking + dispatch, absolute OTIF."""
from __future__ import annotations

import argparse
import json
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
    E2E_ROLLING_POLICIES,
    build_e2e_instance,
    fit_empirical_arrivals,
    order_day_map,
    paired_e2e_delta,
    prepare_baseline,
    prepare_flow,
    run_flow_e2e,
    run_single_week_e2e,
    summarize_flow,
    write_rolling_e2e_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402
from supply.e2e.rolling_e2e import E2E_POLICY_LABELS  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 20 daily rolling end-to-end benchmark"
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
        "--policies", default=",".join(E2E_ROLLING_POLICIES)
    )
    parser.add_argument(
        "--title", default="Multi-day rolling end-to-end benchmark (Week 20)"
    )
    args = parser.parse_args()

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
    cells = [policy for policy in args.policies.split(",") if policy]
    if not cells:
        raise ValueError("至少需要一个补货策略")

    print("=" * 108)
    print(args.title)
    print("=" * 108)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | policies {len(cells)} | "
        f"daily {args.milp_time:.0f}s | baseline {args.baseline_milp_time:.0f}s"
    )
    print(
        "orders by day: "
        + ", ".join(
            f"{day}:{int((order_day == day).sum())}"
            for day in range(int(order_day.max()) + 1)
        )
    )

    print("\n[baseline] one-shot allocation + Week-16 dock ...")
    baseline_alloc = prepare_baseline(
        instance,
        service_time=args.baseline_service_time,
        milp_time=args.baseline_milp_time,
        workers=args.workers,
    )
    baseline_cell = DispatchCell(
        key="week20_single_week",
        label=E2E_POLICY_LABELS["single_week"],
        policy="promise",
        min_load=6,
        max_days=3,
        pickers_per_dc=args.pickers,
        duration_noise=args.noise,
    )
    frames = [
        run_single_week_e2e(instance, baseline_alloc, seeds, arrivals, baseline_cell)
    ]
    print(
        f"  single_week  e2e {frames[0]['e2e_otif_rate'].mean():.1%} | "
        f"fill {frames[0]['fill_rate'].mean():.1%}"
    )

    for policy in cells:
        print(f"\n[{policy}] preparing daily allocations ...")
        flow = prepare_flow(
            instance,
            order_day,
            policy,
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
        )
        cell = DispatchCell(
            key=f"week20_{policy}",
            label=E2E_POLICY_LABELS.get(policy, policy),
            policy="immediate",
            min_load=1,
            max_days=0,
            pickers_per_dc=args.pickers,
            duration_noise=args.noise,
        )
        frame = run_flow_e2e(
            flow, instance, order_day, seeds, arrivals, cell
        )
        frames.append(frame)
        print(
            f"  {policy:<9} e2e {frame['e2e_otif_rate'].mean():.1%} | "
            f"fill {frame['fill_rate'].mean():.1%} | "
            f"backlog {int(frame['backlog_units'].iloc[0]):,}"
        )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_flow(frame)
    paired = [
        paired_e2e_delta(frame, policy, "none") for policy in cells if policy != "none"
    ]
    paired += [
        paired_e2e_delta(frame, policy, "single_week") for policy in cells
    ]
    by_day = []
    for policy in frame["policy"].unique():
        subset = frame[frame["policy"] == policy]
        by_day.append(
            {
                "policy": policy,
                "label": E2E_POLICY_LABELS.get(policy, policy),
                "e2e_otif_mean": float(subset["e2e_otif_rate"].mean()),
            }
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
            "baseline_milp_time": args.baseline_milp_time,
            "baseline_service_time": args.baseline_service_time,
            "workers": args.workers,
            "pickers": args.pickers,
            "noise": args.noise,
            "policies": cells,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "paired": paired,
        "by_policy": by_day,
        "limitations": [
            "日滚动每天只允许当天最后发车（max_days=0）；错过当天发车的票据直接失败，不滚到次日。单周基线用 Week-16 的 3 天发车窗口，两者不是同一发车自由度。",
            "只重放“分单 → 经验到达 → EDF 拣选 → 截单 → 发车”；门位/装车资源不重跑，门位默认 0（不限制）。",
            "单周基线把所有订单视作周一到达，用承诺日从周一起算；日滚动按真实订单日算绝对承诺。两者不是逐单同口径，单周基线只作“一次性分单”的端到端对照。",
            "分单后不接收拣选/发车失败的回写：未装车订单不进入次日 backlog 重试，且库存已按分单扣减；失败订单被保守地当作终态。",
            "补货为剩余周 cover 的 order-up-to，1/2 天前置期；不做预测/MOQ/供应商产能/DC 调拨。",
            "订单日按发票日期映射，周六/周日并入周五；单周基线与日滚动用同一批种子，但日滚动每天重新抽样到达曲线，不是逐日配对的同一批到达。",
            "单周基线 60s、日滚动 8s/天，求解器差异会混入 OTIF；只验证 1 个目标周、1 套库存/布局/劳动力。",
            "绝对 OTIF 不可迁移；结论用于比较“多日库存结转 + 拣选/发车”的方向。",
        ],
    }
    paths = write_rolling_e2e_report(payload, Path(args.out_dir), title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
