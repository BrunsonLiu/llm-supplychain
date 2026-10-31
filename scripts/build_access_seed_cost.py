"""Build the Week-48 seed-level stock-cost decision report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e.access_cost import (  # noqa: E402
    build_seed_cost_report,
    seed_cost_choices,
)

DEFAULT_INSAMPLE = [
    "1.0=benchmarks/access_load_covered_summary.json",
    "1.25=benchmarks/access_stock125_summary.json",
    "1.35=benchmarks/access_stock135_summary.json",
    "1.4=benchmarks/access_stock140_summary.json",
    "1.5=benchmarks/access_stock15_summary.json",
]
DEFAULT_OOS = [
    "1.0=benchmarks/access_oos100_summary.json",
    "1.25=benchmarks/access_oos125_summary.json",
    "1.4=benchmarks/access_oos140_summary.json",
]


def _load(items: list[str]) -> list[tuple[float, dict]]:
    payloads = []
    for item in items:
        factor, path = item.split("=", 1)
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        payloads.append((float(factor), payload))
    return payloads


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed-level stock-cost stability")
    parser.add_argument("--insample", action="append", default=None)
    parser.add_argument("--oos", action="append", default=None)
    parser.add_argument("--holding-cost", type=float, default=0.10)
    parser.add_argument(
        "--ratios",
        default="0,50,75,100,200,1000,2000",
        help="comma-separated stockout/holding ratios",
    )
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"))
    parser.add_argument("--week", type=int, default=48)
    parser.add_argument("--stem", default="ACCESS_SEED_COST")
    args = parser.parse_args()
    insample = _load(args.insample or DEFAULT_INSAMPLE)
    oos = _load(args.oos or DEFAULT_OOS)
    ratios = [float(item) for item in args.ratios.split(",") if item.strip()]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    report.write_text(
        build_seed_cost_report(
            insample,
            oos,
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
                "insample": seed_cost_choices(
                    insample, ratios=ratios, holding_cost=args.holding_cost
                ),
                "oos": seed_cost_choices(
                    oos, ratios=ratios, holding_cost=args.holding_cost
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
