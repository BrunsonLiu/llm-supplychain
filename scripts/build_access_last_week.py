"""Test naive last-week SKU structure against history (Week 54)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping


def _row(label: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    baseline = next(
        item for item in payload["summary"] if item["policy"] == "baseline"
    )
    dataset = payload["dataset"]
    return {
        "label": label,
        "stock_units": int(dataset["stock_units"]),
        "coverage": float(dataset["stock_coverage"]),
        "target": float(baseline["target_accepted_otif_mean"]),
        "all": float(baseline["accepted_otif_mean"]),
        "backlog": float(baseline["accepted_backlog_units"]),
    }


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Last-week SKU structure")
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=54)
    parser.add_argument("--stem", default="ACCESS_LAST_WEEK")
    parser.add_argument(
        "--actual", default="benchmarks/access_mix_actual_summary.json"
    )
    parser.add_argument(
        "--history", default="benchmarks/access_hist14_summary.json"
    )
    parser.add_argument(
        "--forecast", default="benchmarks/access_forecast_share14_summary.json"
    )
    parser.add_argument(
        "--last", default="benchmarks/access_last_week14_summary.json"
    )
    parser.add_argument(
        "--forecast_point", default="benchmarks/access_forecast16_summary.json"
    )
    args = parser.parse_args()
    rows: List[Dict[str, Any]] = [
        _row("actual mix @44,824", json.loads(
            Path(args.actual).read_text(encoding="utf-8")
        )),
        _row("history mean mix @44,824", json.loads(
            Path(args.history).read_text(encoding="utf-8")
        )),
        _row("forecast mix @44,826", json.loads(
            Path(args.forecast).read_text(encoding="utf-8")
        )),
        _row("last-week mix @44,833", json.loads(
            Path(args.last).read_text(encoding="utf-8")
        )),
        _row("forecast point @55,776", json.loads(
            Path(args.forecast_point).read_text(encoding="utf-8")
        )),
    ]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    actual, history, forecast, last, point = rows
    lines = [
        f"# Week {args.week}: Last-week SKU mix is worse than the mean",
        "",
        "Week53 showed LightGBM's predicted SKU shares do not beat the "
        "historical mean. Week54 tests the simplest deployable alternative: "
        "use **last week's actual SKU shares**, at the same historical total. "
        "No target demand is used.",
        "",
        "| policy | stock units | coverage | target OTIF | all OTIF | backlog |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['stock_units']:,} | "
            f"{row['coverage']:.2%} | {_pct(row['target'])} | "
            f"{_pct(row['all'])} | {row['backlog']:,.1f} |"
        )
    lines += ["", "## Findings", ""]
    lines.append(
        f"- **Naive persistence fails badly**: at ~44,824 units, last-week "
        f"mix reaches {_pct(last['target'])} target and {_pct(last['all'])} "
        f"all, vs history mean {_pct(history['target'])}/"
        f"{_pct(history['all'])}. Backlog rises from "
        f"{history['backlog']:,.0f} to {last['backlog']:,.0f}."
    )
    lines.append(
        f"- **Only actual demand shares reach {_pct(actual['target'])}**; "
        f"forecast shares reach {_pct(forecast['target'])} and last-week "
        f"shares {_pct(last['target'])}. Neither simple signal is a usable "
        "substitute for the target-week composition."
    )
    lines.append(
        f"- **More total stock does not repair the bad mix**: the forecast "
        f"point policy at {point['stock_units']:,} units reaches "
        f"{_pct(point['target'])} target, but its all-service "
        f"({_pct(point['all'])}) is still below history. The structure "
        "problem is not a level problem."
    )
    lines += [
        "- Last week is a single adjacent week and the target week is a "
        "seasonal transition; the negative result is a stress case, not a "
        "general claim that persistence never works.",
        "- Actual mix is an oracle decomposition row. One target week, 400 "
        "invoices, 30 seeds × 3 repeats; no promotion/new-product signal.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary.write_text(
        json.dumps({"week": args.week, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {report}")
    print(f"Wrote {summary}")


if __name__ == "__main__":
    main()
