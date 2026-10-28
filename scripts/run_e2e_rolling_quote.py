"""Week 22: daily rolling replenishment with daily promise re-quoting."""
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
    E2E_ROLLING_POLICIES,
    build_e2e_instance,
    fit_empirical_arrivals,
    order_day_map,
    prepare_baseline,
    prepare_flow,
    run_flow_e2e,
    run_single_week_e2e,
    write_rolling_quote_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402
from supply.e2e.rolling_e2e import E2E_POLICY_LABELS  # noqa: E402


def summarize_quote(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (policy, quote), group in frame.groupby(
        ["policy", "quote_policy"], sort=False
    ):
        otif = group["e2e_otif_rate"].to_numpy(dtype=float)
        rows.append(
            {
                "policy": policy,
                "quote_policy": quote,
                "label": (
                    "单周一次性快照"
                    if policy == "single_week"
                    else E2E_POLICY_LABELS.get(policy, policy)
                ),
                "seeds": int(len(group)),
                "quoted_otif_mean": float(otif.mean()),
                "quoted_otif_p10": float(np.percentile(otif, 10)),
                "quoted_otif_p90": float(np.percentile(otif, 90)),
                "static_sla_otif_mean": float(
                    group["static_sla_otif_rate"].mean()
                ),
                "avg_promise_days": float(group["avg_promise_days"].mean()),
                "fast_share": float(group["fast_share"].mean()),
                "fill_mean": float(group["fill_rate"].mean()),
                "late_orders_mean": float(group["late_orders"].mean()),
                "backlog_units": int(group["backlog_units"].iloc[0]),
                "avg_delivery_day": float(group["avg_delivery_day"].mean()),
                "replenished_units": int(group["replenished_units"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def paired_quote(
    frame: pd.DataFrame, left: str, left_quote: str, right: str, right_quote: str
) -> dict:
    left_frame = frame[
        (frame["policy"] == left) & (frame["quote_policy"] == left_quote)
    ].set_index("seed")
    right_frame = frame[
        (frame["policy"] == right) & (frame["quote_policy"] == right_quote)
    ].set_index("seed")
    common = sorted(set(left_frame.index) & set(right_frame.index))
    if not common:
        return {}
    delta = (
        left_frame.loc[common, "e2e_otif_rate"].to_numpy()
        - right_frame.loc[common, "e2e_otif_rate"].to_numpy()
    )
    static_delta = (
        left_frame.loc[common, "static_sla_otif_rate"].to_numpy()
        - right_frame.loc[common, "static_sla_otif_rate"].to_numpy()
    )
    mean = float(delta.mean())
    std = float(delta.std(ddof=1)) if len(delta) > 1 else 0.0
    half = 1.96 * std / np.sqrt(len(delta)) if len(delta) > 1 else 0.0
    return {
        "left": f"{left}@{left_quote}",
        "right": f"{right}@{right_quote}",
        "n": int(len(delta)),
        "mean": mean,
        "ci95": half,
        "static_mean": float(static_delta.mean()),
        "win": float((delta > 0).mean()),
        "loss": float((delta < 0).mean()),
        "tie": float((delta == 0).mean()),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 22 rolling replenishment with daily promise re-quoting"
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
    parser.add_argument("--policies", default="none,daily_1d")
    parser.add_argument(
        "--quote-policies", default="static,atp,atp_buffer"
    )
    parser.add_argument(
        "--title", default="Rolling replenishment with daily promise re-quoting (Week 22)"
    )
    args = parser.parse_args()
    policies = [value for value in args.policies.split(",") if value]
    quote_policies = [
        value for value in args.quote_policies.split(",") if value
    ]
    if "static" not in quote_policies:
        quote_policies = ["static"] + quote_policies
    for policy in policies:
        if policy not in E2E_ROLLING_POLICIES:
            raise ValueError(f"未知补货策略: {policy}")

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
        f"orders {instance.n_orders} | seeds {len(seeds)} | policies {policies} | "
        f"quotes {quote_policies} | daily {args.milp_time:.0f}s | "
        f"baseline {args.baseline_milp_time:.0f}s"
    )
    print(
        "orders by day: "
        + ", ".join(
            f"{day}:{int((order_day == day).sum())}"
            for day in range(int(order_day.max()) + 1)
        )
    )

    print("\n[baseline] one-shot allocation + static promise ...")
    baseline_alloc = prepare_baseline(
        instance,
        service_time=args.baseline_service_time,
        milp_time=args.baseline_milp_time,
        workers=args.workers,
    )
    frames = []
    baseline_cell = DispatchCell(
        key="week22_single_week_static",
        label="单周快照 · 固定承诺",
        policy="promise",
        min_load=6,
        max_days=3,
        pickers_per_dc=args.pickers,
        duration_noise=args.noise,
    )
    baseline = run_single_week_e2e(
        instance, baseline_alloc, seeds, arrivals, baseline_cell
    )
    baseline["quote_policy"] = "static"
    frames.append(baseline)
    print(
        f"  single_week static  quoted {baseline['e2e_otif_rate'].mean():.1%} | "
        f"static {baseline['static_sla_otif_rate'].mean():.1%} | "
        f"promise {baseline['avg_promise_days'].mean():.2f}d"
    )

    for policy in policies:
        for quote in quote_policies:
            print(f"\n[{policy} · {quote}] preparing daily flow ...")
            flow = prepare_flow(
                instance,
                order_day,
                policy,
                service_time=args.service_time,
                milp_time=args.milp_time,
                workers=args.workers,
                quote_policy=quote,
            )
            cell = DispatchCell(
                key=f"week22_{policy}_{quote}",
                label=f"{E2E_POLICY_LABELS.get(policy, policy)} · {quote}",
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
                f"  {policy:<9} {quote:<10} quoted "
                f"{frame['e2e_otif_rate'].mean():.1%} | static "
                f"{frame['static_sla_otif_rate'].mean():.1%} | "
                f"promise {frame['avg_promise_days'].mean():.2f}d | "
                f"fast {frame['fast_share'].mean():.1%}"
            )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_quote(frame)
    paired = []
    for policy in policies:
        for quote in quote_policies:
            if quote != "static":
                paired.append(paired_quote(frame, policy, quote, policy, "static"))
        paired.append(
            paired_quote(frame, policy, "static", "single_week", "static")
        )
    paired = [row for row in paired if row]

    by_day = []
    for (policy, quote), group in frame.groupby(
        ["policy", "quote_policy"], sort=False
    ):
        row = {
            "policy": policy,
            "quote_policy": quote,
            "label": (
                "单周一次性快照"
                if policy == "single_week"
                else E2E_POLICY_LABELS.get(policy, policy)
            ),
        }
        for day in range(5):
            column = f"otif_day_{day}"
            row[column] = (
                float(group[column].mean())
                if column in group and not group[column].isna().all()
                else float("nan")
            )
        by_day.append(row)

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
            "policies": policies,
            "quote_policies": quote_policies,
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "summary": summary.to_dict("records"),
        "rows": frame.to_dict("records"),
        "paired": paired,
        "by_day": by_day,
        "limitations": [
            "ATP 只按当天开始时的在库量报价，不把在途补货、未来到达或跨订单库存预留放进报价；同一天多张订单可能同时被报 2 天，分单时再竞争库存。",
            "报价只允许 2/3/5 三档；新订单按 ATP 最快档报价，旧订单保留到达时的绝对承诺日，不做改单/取消/客户拒绝。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线把所有订单视作周一且允许 3 天发车，两者不是同一发车自由度。",
            "分单后不接收拣选/发车/门位失败的回写：未装车订单不进入次日 backlog 重试，库存已按分单扣减，失败被保守地当作终态。",
            "补货为剩余周 cover 的 order-up-to，1/2 天前置期；不做预测/MOQ/供应商产能/DC 调拨；只有 1 个目标周、1 套库存/布局/劳动力。",
            "单周基线 60s、日滚动 8s/天，求解器差异会混入 OTIF；30 个种子可能给出相同结果，配对 CI 为 0 时要按确定性边界读。",
            "静态 SLA 用 Week-20 的固定 2/3/5 承诺，不是客户真实容忍度；报价更短不等于更好，报价更长也不一定保住原 SLA。",
        ],
    }
    paths = write_rolling_quote_report(payload, Path(args.out_dir), title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
