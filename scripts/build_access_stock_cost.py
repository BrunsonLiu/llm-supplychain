"""Turn a measured stock-service frontier into a cost-ratio decision."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e.access_cost import (  # noqa: E402
    build_stock_cost_report,
    cost_table,
    critical_ratios,
    efficient_frontier,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stock-service cost decision")
    parser.add_argument(
        "--frontier",
        default=str(ROOT / "benchmarks/access_stock_frontier_summary.json"),
    )
    parser.add_argument("--holding-cost", type=float, default=0.10)
    parser.add_argument(
        "--ratios",
        default="0,50,75,100,200,1000,2000",
        help="comma-separated stockout/holding ratios",
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--week", type=int, default=46)
    parser.add_argument("--stem", default="ACCESS_STOCK_COST")
    args = parser.parse_args()
    payload = json.loads(Path(args.frontier).read_text(encoding="utf-8"))
    rows = payload["rows"]
    ratios = [float(item) for item in args.ratios.split(",") if item.strip()]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    report.write_text(
        build_stock_cost_report(
            rows,
            holding_cost=args.holding_cost,
            ratios=ratios,
            week=args.week,
        ),
        encoding="utf-8",
    )
    summary.write_text(
        json.dumps(
            {
                "holding_cost": args.holding_cost,
                "ratios": ratios,
                "efficient_frontier": efficient_frontier(
                    [row for row in rows if row["policy"] == "baseline"]
                ),
                "critical_ratios": critical_ratios(rows),
                "cost_table": cost_table(
                    rows, ratios=ratios, holding_cost=args.holding_cost
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {report}")
    print(f"Wrote {summary}")


if __name__ == "__main__":
    main()
