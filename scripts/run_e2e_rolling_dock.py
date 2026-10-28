"""Week 21: daily rolling allocation + pick/dispatch + dock doors."""
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
    write_rolling_dock_report,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402
from supply.e2e.rolling_e2e import E2E_POLICY_LABELS  # noqa: E402


def summarize_dock(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (policy, doors), group in frame.groupby(["policy", "doors"], sort=False):
        otif = group["e2e_otif_rate"].to_numpy(dtype=float)
        rows.append(
            {
                "policy": policy,
                "doors": int(doors),
                "label": E2E_POLICY_LABELS.get(policy, policy),
                "seeds": int(len(group)),
                "e2e_otif_mean": float(otif.mean()),
                "e2e_otif_p10": float(np.percentile(otif, 10)),
                "e2e_otif_p90": float(np.percentile(otif, 90)),
                "fill_mean": float(group["fill_rate"].mean()),
                "late_orders_mean": float(group["late_orders"].mean()),
                "backlog_units": int(group["backlog_units"].iloc[0]),
                "avg_delivery_day": float(group["avg_delivery_day"].mean()),
                "door_utilization": float(group["door_utilization"].mean()),
                "door_blocked_mean": float(group["door_blocked"].mean()),
            }
        )
    return pd.DataFrame(rows)


def paired_dock(
    frame: pd.DataFrame,
    left_policy: str,
    left_doors: int,
    right_policy: str,
    right_doors: int,
) -> dict:
    left = frame[
        (frame["policy"] == left_policy) & (frame["doors"] == left_doors)
    ].set_index("seed")
    right = frame[
        (frame["policy"] == right_policy) & (frame["doors"] == right_doors)
    ].set_index("seed")
    common = sorted(set(left.index) & set(right.index))
    if not common:
        return {}
    delta = (
        left.loc[common, "e2e_otif_rate"].to_numpy()
        - right.loc[common, "e2e_otif_rate"].to_numpy()
    )
    mean = float(delta.mean())
    std = float(delta.std(ddof=1)) if len(delta) > 1 else 0.0
    half = 1.96 * std / np.sqrt(len(delta)) if len(delta) > 1 else 0.0
    return {
        "left": f"{left_policy}@{left_doors}门",
        "right": f"{right_policy}@{right_doors}门",
        "n": int(len(delta)),
        "mean": mean,
        "ci95": half,
        "win": float((delta > 0).mean()),
        "loss": float((delta < 0).mean()),
        "tie": float((delta == 0).mean()),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 21 rolling end-to-end benchmark with dock doors"
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
    parser.add_argument("--door-window", type=float, default=480.0)
    parser.add_argument("--doors", default="0,1,2")
    parser.add_argument("--policies", default="none,daily_1d")
    parser.add_argument(
        "--title", default="Rolling end-to-end with dock doors (Week 21)"
    )
    args = parser.parse_args()
    doors = [int(value) for value in args.doors.split(",") if value]
    policies = [value for value in args.policies.split(",") if value]
    if 0 not in doors:
        doors = [0] + doors
    if "none" not in policies:
        policies = ["none"] + policies
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
    print("=" * 108)
    print(args.title)
    print("=" * 108)
    print(
        f"orders {instance.n_orders} | seeds {len(seeds)} | policies {policies} | "
        f"doors {doors} | daily {args.milp_time:.0f}s | baseline {args.baseline_milp_time:.0f}s"
    )
    print(
        "orders by day: "
        + ", ".join(
            f"{day}:{int((order_day == day).sum())}"
            for day in range(int(order_day.max()) + 1)
        )
    )

    print("\n[baseline] one-shot allocation + dock ...")
    baseline_alloc = prepare_baseline(
        instance,
        service_time=args.baseline_service_time,
        milp_time=args.baseline_milp_time,
        workers=args.workers,
    )
    frames = []
    for door in doors:
        cell = DispatchCell(
            key=f"week21_single_week_d{door}",
            label=f"单周快照 · {door} 门",
            policy="promise",
            min_load=6,
            max_days=3,
            doors_per_dc=door,
            door_window_minutes=args.door_window,
            pickers_per_dc=args.pickers,
            duration_noise=args.noise,
        )
        frame = run_single_week_e2e(instance, baseline_alloc, seeds, arrivals, cell)
        frame["doors"] = door
        frames.append(frame)
        print(
            f"  single_week d{door}  e2e {frame['e2e_otif_rate'].mean():.1%} | "
            f"fill {frame['fill_rate'].mean():.1%} | "
            f"door util {frame['door_utilization'].mean():.1%}"
        )

    for policy in policies:
        print(f"\n[{policy}] preparing daily allocations ...")
        flow = prepare_flow(
            instance,
            order_day,
            policy,
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
        )
        for door in doors:
            cell = DispatchCell(
                key=f"week21_{policy}_d{door}",
                label=f"{E2E_POLICY_LABELS.get(policy, policy)} · {door} 门",
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
            frame["doors"] = door
            frames.append(frame)
            print(
                f"  {policy:<9} d{door}  e2e {frame['e2e_otif_rate'].mean():.1%} | "
                f"fill {frame['fill_rate'].mean():.1%} | "
                f"door util {frame['door_utilization'].mean():.1%} | "
                f"blocked {frame['door_blocked'].mean():.1f}"
            )

    frame = pd.concat(frames, ignore_index=True)
    summary = summarize_dock(frame)
    paired = []
    for policy in policies:
        paired.append(paired_dock(frame, policy, 1, policy, 0))
        if 2 in doors:
            paired.append(paired_dock(frame, policy, 2, policy, 0))
    for door in doors:
        paired.append(paired_dock(frame, "daily_1d", door, "none", door))
        paired.append(paired_dock(frame, "daily_1d", door, "single_week", door))
    paired = [row for row in paired if row]

    by_day = []
    for (policy, door), group in frame.groupby(["policy", "doors"], sort=False):
        row = {
            "policy": policy,
            "doors": int(door),
            "label": E2E_POLICY_LABELS.get(policy, policy),
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
            "door_window": args.door_window,
            "policies": policies,
            "doors": doors,
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
            "门位是“每 DC 每日分钟预算”（默认 480 分钟，75 分钟/车 + 0.5 分钟/票），不模拟具体门位占用、叉车/装卸工排班、司机等待与预约时段。",
            "日滚动每天只允许当天发车（max_days=0）；单周基线把所有订单视作周一且允许 3 天发车，两者不是同一发车自由度。",
            "分单后不接收拣选/发车/门位失败的回写：未装车订单不进入次日 backlog 重试，库存已按分单扣减，失败被保守地当作终态。",
            "补货为剩余周 cover 的 order-up-to，1/2 天前置期；不做预测/MOQ/供应商产能/DC 调拨；只有 1 个目标周、1 套库存/布局/劳动力。",
            "单周基线 60s、日滚动 8s/天，求解器差异会混入 OTIF；30 个种子在本配置下可能给出相同 OTIF，配对 CI 为 0 时要按确定性边界读，而不是 30 个独立样本。",
            "绝对 OTIF 不可迁移；门位/装车费率与工时都是声明值，结论只用于比较“多日库存结转 + 门位资源”的方向。",
        ],
    }
    paths = write_rolling_dock_report(payload, Path(args.out_dir), title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
