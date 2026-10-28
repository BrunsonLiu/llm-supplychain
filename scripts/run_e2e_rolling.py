"""Week 19 benchmark: multi-day rolling allocation with inventory carryover.

The 400 real invoices are placed on their actual weekday, then allocated day by
day against the remaining stock. Five replenishment policies restore consumed
units after a declared lead time. The baseline is the Week-18 one-shot weekly
snapshot on the same instance. Picking and dispatch are **not** replayed here;
this is the inventory-carryover layer, deliberately isolated from the dock.
"""
from __future__ import annotations

import argparse
import gc
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
    build_e2e_instance,
    rolling_cells,
    run_rolling_policy,
    single_week_baseline,
    write_rolling_report,
)
from supply.e2e.rolling import order_day_map  # noqa: E402

SUMMARY_METRICS = [
    "fill_rate",
    "otif_rate",
    "late_units",
    "backlog_units",
    "replenished_units",
    "stockout_days",
    "avg_inventory_units",
]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Week 19 multi-day rolling allocation benchmark"
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
    parser.add_argument("--service-time", type=float, default=3.0)
    parser.add_argument("--milp-time", type=float, default=8.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--baseline-milp-time", type=float, default=60.0)
    parser.add_argument("--baseline-service-time", type=float, default=30.0)
    parser.add_argument("--safety", type=float, default=0.10)
    parser.add_argument(
        "--policies",
        default=",".join(
            ["none", "daily_1d", "daily_2d", "daily_1d_safety", "batch_2d"]
        ),
    )
    parser.add_argument(
        "--title", default="Multi-day rolling allocation and replenishment (Week 19)"
    )
    parser.add_argument(
        "--baseline-json",
        default="",
        help="reuse a saved single-week baseline instead of re-solving it",
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
    cells = [cell for cell in rolling_cells() if cell.policy in args.policies.split(",")]
    if not cells:
        raise ValueError("至少需要一个补货策略")

    print("=" * 108)
    print(args.title)
    print("=" * 108)
    print(
        f"orders {instance.n_orders} | weekdays {int(order_day.max()) + 1} | "
        f"policies {len(cells)} | milp {args.milp_time:.0f}s/day"
    )
    print(
        "orders by day: "
        + ", ".join(
            f"{day}:{int((order_day == day).sum())}"
            for day in range(int(order_day.max()) + 1)
        )
    )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if args.baseline_json:
        baseline = json.loads(
            Path(args.baseline_json).read_text(encoding="utf-8")
        )["baseline"]
    else:
        baseline = single_week_baseline(
            instance,
            service_time=args.baseline_service_time,
            milp_time=args.baseline_milp_time,
            workers=args.workers,
        )
        (out / "rolling_baseline.json").write_text(
            json.dumps({"baseline": baseline}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(
        f"  single_week  OTIF {baseline['otif_rate']:.1%} | "
        f"fill {baseline['fill_rate']:.1%} | backlog {baseline['backlog_units']:,}"
    )

    rows = []
    daily_rows = []
    by_day_rows = []
    for cell in cells:
        result = run_rolling_policy(
            instance,
            order_day,
            cell.policy,
            service_time=args.service_time,
            milp_time=args.milp_time,
            workers=args.workers,
            safety=args.safety,
        )
        rows.append(
            {
                key: value
                for key, value in result.items()
                if key not in ("daily", "by_order_day")
            }
        )
        for row in result["daily"]:
            daily_rows.append({**row, "policy": cell.policy, "label": cell.label})
        for row in result["by_order_day"]:
            by_day_rows.append(
                {**row, "policy": cell.policy, "label": cell.label}
            )
        gc.collect()
        print(
            f"  {cell.policy:<15} OTIF {result['otif_rate']:.1%} | "
            f"fill {result['fill_rate']:.1%} | backlog {result['backlog_units']:,} | "
            f"replenished {result['replenished_units']:,} | "
            f"stockout-days {result['stockout_days']}"
        )

    summary = pd.DataFrame([baseline, *rows])
    daily = pd.DataFrame(daily_rows)
    by_day = pd.DataFrame(by_day_rows)
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
            "service_time": args.service_time,
            "milp_time": args.milp_time,
            "workers": args.workers,
            "safety": args.safety,
            "policies": [cell.policy for cell in cells],
        },
        "order_days": {
            str(day): int((order_day == day).sum())
            for day in range(int(order_day.max()) + 1)
        },
        "baseline": baseline,
        "summary": summary.to_dict("records"),
        "daily": daily.to_dict("records"),
        "by_order_day": by_day.to_dict("records"),
        "limitations": [
            "只重放分单层：拣选、在线释放、发车与月台不重跑；交付日按“分单日 + 声明转运日”计算，不含截单/发车/门位。",
            "订单日来自发票日期（周一至周五）；周六/周日发票并入周五，仓库当日可用性没有单独建模。",
            "补货采用剩余周 cover 的 order-up-to：目标从 85% 周库存线性降到 0，只把同一批库存往后几天移动，不额外创造总量；不做需求预测、MOQ、补货批量上限、供应商产能或 DC 间调拨。",
            "前置期是声明值（1/2 天），到货只发生在早晨；安全量按目标 cover 的 10% 向上取整。",
            "单周快照用 60s MILP，日滚动用 8s/天；求解器在时间预算内的差异会混入 OTIF；只验证一个目标周、一个库存/布局。",
            "绝对 OTIF 不可迁移；结果用于比较库存结转与补货前置期的方向，不是生产承诺。",
        ],
    }

    paths = write_rolling_report(payload, out, title=args.title)
    print("\nWrote:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
