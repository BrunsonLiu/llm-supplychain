"""Compare target-demand stock with a prior-history stock basis (Week 49)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping


def _row(label: str, factor: float, payload: Mapping[str, Any]) -> Dict[str, Any]:
    baseline = next(
        item for item in payload["summary"] if item["policy"] == "baseline"
    )
    dataset = payload["dataset"]
    return {
        "label": label,
        "factor": float(factor),
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
    parser = argparse.ArgumentParser(description="Stock-basis comparison")
    parser.add_argument(
        "--actual",
        default="benchmarks/access_stock140_summary.json",
    )
    parser.add_argument(
        "--history",
        action="append",
        default=None,
        help="factor=path; default 1.4/1.8/2.0 history runs",
    )
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=49)
    parser.add_argument("--stem", default="ACCESS_STOCK_BASIS")
    args = parser.parse_args()
    history_inputs = args.history or [
        "1.4=benchmarks/access_hist14_summary.json",
        "1.8=benchmarks/access_hist18_summary.json",
        "2.0=benchmarks/access_hist20_summary.json",
    ]
    actual = json.loads(Path(args.actual).read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = [_row("actual-demand", 1.4, actual)]
    for item in history_inputs:
        factor, path = item.split("=", 1)
        rows.append(
            _row(
                "history-mean",
                float(factor),
                json.loads(Path(path).read_text(encoding="utf-8")),
            )
        )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    actual_row = rows[0]
    history = rows[1:]
    lines = [
        f"# Week {args.week}: stock basis — target demand vs prior history",
        "",
        "The earlier stock frontier (Weeks 45-48) sets each SKU's stock to a "
        "percentage of the **target week's sampled demand**. That is an "
        "oracle-stock upper bound. Week49 uses the same 400 orders but sets "
        "stock from the mean of the **prior 6 weeks** by SKU, scaled by the "
        "sampled-order/historical-invoice ratio. No target demand is used.",
        "",
        "| stock basis | factor | stock units | coverage | target OTIF | all OTIF | backlog |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['label']} | {row['factor']:.0%} | "
            f"{row['stock_units']:,} | {row['coverage']:.2%} | "
            f"{_pct(row['target'])} | {_pct(row['all'])} | "
            f"{row['backlog']:,.1f} |"
        )
    first = history[0] if history else None
    last = history[-1] if history else None
    lines += ["", "## Findings", ""]
    if first is not None:
        lines.append(
            f"- **Same 140% factor, very different service**: actual-demand "
            f"{actual_row['stock_units']:,} units delivers "
            f"{_pct(actual_row['target'])}/{_pct(actual_row['all'])}/"
            f"{actual_row['backlog']:,.1f}; prior-history "
            f"{first['stock_units']:,} units delivers "
            f"{_pct(first['target'])}/{_pct(first['all'])}/"
            f"{first['backlog']:,.1f}. The stock totals are close, but the "
            "SKU mix is not: the target week's demand is concentrated in "
            "different SKUs."
        )
    if last is not None:
        lines.append(
            f"- **More aggregate history stock does not close the gap**: "
            f"history 200% holds {last['stock_units']:,} units "
            f"({last['coverage']:.0%} of target demand) but reaches only "
            f"{_pct(last['target'])}/{_pct(last['all'])} with "
            f"{last['backlog']:,.1f} backlog. Aggregate overstock cannot fix "
            "per-SKU mix error."
        )
    lines += [
        "- **The Weeks 45-48 frontier is an oracle-stock upper bound.** Those "
        "results answer what happens if stock is already in the right SKU "
        "proportions; they overstate deployable service. The cost decision "
        "and seed-stability layers inherit that caveat.",
        "- The history policy is a **naive 6-week mean**, not a forecast "
        "model: no seasonality, promotion, lead time, replenishment or "
        "substitution. It is a lower bound on what a real forecast could do, "
        "and a useful warning against treating the frontier as deployable.",
        "- One target week, 400 invoices, 30 seeds × 3 repeats, fixed layout/"
        "shift; stock shares and jitter are unchanged.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary.write_text(
        json.dumps(
            {
                "week": args.week,
                "rows": rows,
                "actual_factor": actual_row["factor"],
                "history_factors": [row["factor"] for row in history],
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
