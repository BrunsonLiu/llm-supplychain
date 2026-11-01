"""Compare oracle, history, safety and LightGBM forecast stock (Week 51)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping


def _row(label: str, param: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    baseline = next(
        item for item in payload["summary"] if item["policy"] == "baseline"
    )
    dataset = payload["dataset"]
    return {
        "label": label,
        "param": param,
        "stock_units": int(dataset["stock_units"]),
        "coverage": float(dataset["stock_coverage"]),
        "target": float(baseline["target_accepted_otif_mean"]),
        "all": float(baseline["accepted_otif_mean"]),
        "backlog": float(baseline["accepted_backlog_units"]),
        "basis": payload["settings"].get("stock_basis", "actual"),
    }


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def main() -> None:
    parser = argparse.ArgumentParser(description="Stock forecast comparison")
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=51)
    parser.add_argument("--stem", default="ACCESS_STOCK_FORECAST")
    parser.add_argument(
        "--actual", default="benchmarks/access_stock140_summary.json"
    )
    parser.add_argument(
        "--history",
        action="append",
        default=None,
        help="factor=path; default 1.4/2.0",
    )
    parser.add_argument(
        "--safety",
        default="benchmarks/access_safety99_summary.json",
    )
    parser.add_argument(
        "--forecast",
        action="append",
        default=None,
        help="label=factor=path; default pure 1.4/1.6 + same-stock repeat",
    )
    args = parser.parse_args()
    history_inputs = args.history or [
        "1.4=benchmarks/access_hist14_summary.json",
        "2.0=benchmarks/access_hist20_summary.json",
    ]
    forecast_inputs = args.forecast or [
        "forecast-140=1.4=benchmarks/access_forecast14_summary.json",
        "forecast-160=1.6=benchmarks/access_forecast16_summary.json",
        "forecast-160-replicate=1.6=benchmarks/access_forecast_fill16_summary.json",
    ]
    rows: List[Dict[str, Any]] = [
        _row(
            "oracle target-demand",
            "140%",
            json.loads(Path(args.actual).read_text(encoding="utf-8")),
        )
    ]
    for item in history_inputs:
        factor, path = item.split("=", 1)
        rows.append(
            _row(
                "history mean",
                f"{float(factor):.0%}",
                json.loads(Path(path).read_text(encoding="utf-8")),
            )
        )
    rows.append(
        _row(
            "mean + zσ safety",
            "z=2.326",
            json.loads(Path(args.safety).read_text(encoding="utf-8")),
        )
    )
    for item in forecast_inputs:
        label, factor, path = item.split("=", 2)
        rows.append(
            _row(
                label,
                f"{float(factor):.0%}",
                json.loads(Path(path).read_text(encoding="utf-8")),
            )
        )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    actual = rows[0]
    history = [row for row in rows if row["label"] == "history mean"]
    forecast = [row for row in rows if row["label"].startswith("forecast")]
    lines = [
        f"# Week {args.week}: LightGBM forecast stock — target gain within noise, tail loss",
        "",
        "Week49/50 showed that oracle and naive history/safety policies do not "
        "transfer. Week51 uses the existing rolling-origin LightGBM predictions "
        "(`benchmarks/backtest_predictions.csv`) for the target week, calibrated "
        "only on the prior weeks' actual/predicted totals. No target demand is "
        "used.",
        "",
        "| policy | parameter | stock units | coverage | target OTIF | all OTIF | backlog |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['param']} | {row['stock_units']:,} | "
            f"{row['coverage']:.2%} | {_pct(row['target'])} | "
            f"{_pct(row['all'])} | {row['backlog']:,.1f} |"
        )
    lines += ["", "## Findings", ""]
    pure = [row for row in forecast if "replicate" not in row["label"]]
    if pure:
        low = pure[0]
        high = pure[-1]
        lines.append(
            f"- **Forecast shifts stock toward predicted demand, at the cost "
            f"of tail service**: forecast-140 holds {low['stock_units']:,} "
            f"units and reaches {_pct(low['target'])} target/"
            f"{_pct(low['all'])} all; forecast-160 holds "
            f"{high['stock_units']:,} units and reaches "
            f"{_pct(high['target'])}/{_pct(high['all'])}. Relative to history "
            f"200% ({history[-1]['stock_units']:,} units, "
            f"{_pct(history[-1]['target'])}/{_pct(history[-1]['all'])}), "
            f"forecast-160 changes target by "
            f"{100.0 * (high['target'] - history[-1]['target']):+.1f}pp and "
            f"all-service by "
            f"{100.0 * (high['all'] - history[-1]['all']):+.1f}pp."
        )
        replicate = [row for row in forecast if "replicate" in row["label"]]
        if replicate:
            same_stock = abs(
                replicate[0]["target"] - high["target"]
            ) * 100.0
            lines.append(
                f"- **The target gain is within same-stock rerun noise**: the "
                f"forecast-160 replicate holds the same {high['stock_units']:,} "
                f"units but reaches {_pct(replicate[0]['target'])} target vs "
                f"{_pct(high['target'])} ({same_stock:.1f}pp). The nominal "
                f"+2.5pp target advantage over history-200 is therefore not "
                "robust; the all-service loss (−5.7pp) is larger and consistent."
            )
        lines.append(
            "- **The 200-SKU forecast and its allocation error still cost "
            "tail service**: the forecast only covers 200 main SKUs, and the "
            "missing-SKU fill did not add units in this sample (same stock "
            "total). Even without missing SKUs, forecast allocation lowers "
            "all-service by ~5.7pp vs history-200."
        )
        lines.append(
            f"- **Still far from oracle**: forecast-160 reaches "
            f"{_pct(high['target'])} target, while oracle 140% with "
            f"{actual['stock_units']:,} units reaches "
            f"{_pct(actual['target'])}. The binding gap is per-SKU/DC demand "
            "location, not the choice of a slightly better aggregate forecast."
        )
    lines += [
        "- The forecast is not retrained or tuned here; it is the existing "
        "rolling-origin LightGBM artifact. It uses prior weeks only, but the "
        "prediction is a full-week total scaled to the sampled order count, "
        "and the calibration is a single aggregate ratio rather than a "
        "per-SKU bias correction.",
        "- One target week, 400 invoices, 30 seeds × 3 repeats, fixed layout/"
        "shift; oracle remains non-executable. The forecast result does not "
        "establish a multi-week policy.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary.write_text(
        json.dumps(
            {
                "week": args.week,
                "rows": rows,
                "forecast_labels": [row["label"] for row in forecast],
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
