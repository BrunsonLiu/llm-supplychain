"""Test destination-country DC mix against fixed shares (Week 55)."""
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
    parser = argparse.ArgumentParser(description="Destination-country DC mix")
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=55)
    parser.add_argument("--stem", default="ACCESS_DC_MIX")
    parser.add_argument(
        "--actual", default="benchmarks/access_mix_actual_summary.json"
    )
    parser.add_argument(
        "--history", default="benchmarks/access_hist14_summary.json"
    )
    parser.add_argument(
        "--dc", default="benchmarks/access_dc_mix14_summary.json"
    )
    parser.add_argument(
        "--forecast", default="benchmarks/access_forecast_share14_summary.json"
    )
    parser.add_argument(
        "--last", default="benchmarks/access_last_week14_summary.json"
    )
    parser.add_argument(
        "--point", default="benchmarks/access_forecast16_summary.json"
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
        _row("country-DC mix @44,824", json.loads(
            Path(args.dc).read_text(encoding="utf-8")
        )),
        _row("forecast point @55,776", json.loads(
            Path(args.point).read_text(encoding="utf-8")
        )),
    ]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    actual, history, forecast, last, dc, point = rows
    lines = [
        f"# Week {args.week}: Country-informed DC mix is a ~2pp trade, not a win",
        "",
        "Week52 isolated SKU mix; Weeks53/54 tested SKU-share forecasts. "
        "Week55 uses the only observed spatial signal — destination country — "
        "to place each SKU's stock in the nearest DC, at the same 44,824 "
        "units. No target demand is used.",
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
        f"- **No win at the same total**: country-DC mix reaches "
        f"{_pct(dc['target'])} target and {_pct(dc['all'])} all, vs history "
        f"{_pct(history['target'])}/{_pct(history['all'])}. Target +1.7pp, all "
        f"−1.9pp, backlog +{dc['backlog'] - history['backlog']:,.0f}. This "
        "is a trade near solver noise, not a robust improvement."
    )
    lines.append(
        f"- **The country mix concentrates stock in one DC**: the baseline "
        "shares become roughly 90% / 7% / 2% because most historical demand "
        "maps to London. That helps some target orders and hurts the tail; it "
        "does not change the SKU composition that Week52 identified."
    )
    lines.append(
        f"- **All simple structure signals now fail**: history "
        f"{_pct(history['target'])}, LightGBM {_pct(forecast['target'])}, "
        f"last week {_pct(last['target'])}, country-DC {_pct(dc['target'])}; "
        f"only actual target mix reaches {_pct(actual['target'])}. The missing "
        "input is a real SKU×DC demand signal, not another placement heuristic."
    )
    lines.append(
        f"- The forecast point at {point['stock_units']:,} units reaches "
        f"{_pct(point['target'])} target but only {_pct(point['all'])} all; "
        "more total stock still does not repair the structure."
    )
    lines += [
        "- Country→nearest-DC is a proxy, not observed DC demand: the actual "
        "DC demand is endogenous to the allocation MILP. One target week, "
        "400 invoices, 30 seeds × 3 repeats.",
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
