"""Test whether LightGBM's SKU mix beats history at the same total (Week 53)."""
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
    parser = argparse.ArgumentParser(description="Forecast SKU mix comparison")
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=53)
    parser.add_argument("--stem", default="ACCESS_FORECAST_SHARE")
    parser.add_argument(
        "--actual", default="benchmarks/access_mix_actual_summary.json"
    )
    parser.add_argument(
        "--history", default="benchmarks/access_hist14_summary.json"
    )
    parser.add_argument(
        "--share14", default="benchmarks/access_forecast_share14_summary.json"
    )
    parser.add_argument(
        "--share16", default="benchmarks/access_forecast_share16_summary.json"
    )
    parser.add_argument(
        "--history200", default="benchmarks/access_hist20_summary.json"
    )
    parser.add_argument(
        "--forecast", default="benchmarks/access_forecast16_summary.json"
    )
    args = parser.parse_args()
    rows: List[Dict[str, Any]] = [
        _row("actual mix @44,824", json.loads(
            Path(args.actual).read_text(encoding="utf-8")
        )),
        _row("history mix @44,824", json.loads(
            Path(args.history).read_text(encoding="utf-8")
        )),
        _row("forecast mix @44,826", json.loads(
            Path(args.share14).read_text(encoding="utf-8")
        )),
        _row("forecast mix @51,221", json.loads(
            Path(args.share16).read_text(encoding="utf-8")
        )),
        _row("history mix @64,039", json.loads(
            Path(args.history200).read_text(encoding="utf-8")
        )),
        _row("forecast point @55,776", json.loads(
            Path(args.forecast).read_text(encoding="utf-8")
        )),
    ]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    actual, history, share14, share16, history200, forecast = rows
    lines = [
        f"# Week {args.week}: Forecast SKU mix does not beat history",
        "",
        "Week52 showed SKU structure is the first-order lever. Week53 asks "
        "whether LightGBM's **predicted SKU shares** are a better structure "
        "than the historical mean, holding the total at the historical level. "
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
        f"- **At ~44,824 units, forecast shares do not improve target at all**: "
        f"forecast mix {_pct(share14['target'])} vs history "
        f"{_pct(history['target'])} (same within rounding), while all-service "
        f"falls from {_pct(history['all'])} to {_pct(share14['all'])}. "
        "The predicted composition is not a better composition."
    )
    lines.append(
        f"- **More units on the forecast mix still buy little**: forecast-160 "
        f"mix at {share16['stock_units']:,} units reaches "
        f"{_pct(share16['target'])} target, +4.2pp over 44,826 for +6,395 "
        f"units; history needs +19,215 units to reach "
        f"{_pct(history200['target'])}. Neither is close to the actual mix "
        f"at 44,824 ({_pct(actual['target'])})."
    )
    lines.append(
        f"- **Week51's target lift is not explained by a better mix**: "
        f"forecast point-160 holds {forecast['stock_units']:,} units and "
        f"reaches {_pct(forecast['target'])} target, vs "
        f"{_pct(share16['target'])} for the share-160 at "
        f"{share16['stock_units']:,}. The point policy also has ~4,555 more "
        "units and a different allocation, so this is not a clean level "
        "effect; it is consistent with the lift coming from more total stock, "
        "not from a better composition. All-service is still worse than "
        f"history-200 ({_pct(history200['all'])} vs {_pct(forecast['all'])})."
    )
    lines += [
        "- The forecast covers only 200 main SKUs; missing SKUs use history "
        "shares. The total is still historical, so this isolates composition, "
        "not the forecast level.",
        "- Actual mix is still an oracle decomposition row. One target week, "
        "400 invoices, 30 seeds × 3 repeats; no retraining, no SKU×DC model.",
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
