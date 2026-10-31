"""Compare oracle, history-mean and safety-stock policies (Week 50)."""
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
    parser = argparse.ArgumentParser(description="Stock policy comparison")
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
        action="append",
        default=None,
        help="z=path; default 1.645/2.326",
    )
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=50)
    parser.add_argument("--stem", default="ACCESS_STOCK_SAFETY")
    args = parser.parse_args()
    history_inputs = args.history or [
        "1.4=benchmarks/access_hist14_summary.json",
        "2.0=benchmarks/access_hist20_summary.json",
    ]
    safety_inputs = args.safety or [
        "1.645=benchmarks/access_safety95_summary.json",
        "2.326=benchmarks/access_safety99_summary.json",
    ]
    rows: List[Dict[str, Any]] = [
        _row("oracle target-demand", "140%", json.loads(
            Path(args.actual).read_text(encoding="utf-8")
        ))
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
    for item in safety_inputs:
        z_value, path = item.split("=", 1)
        rows.append(
            _row(
                "mean + zσ safety",
                f"z={float(z_value):.3f}",
                json.loads(Path(path).read_text(encoding="utf-8")),
            )
        )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    actual = rows[0]
    history = [row for row in rows if row["label"] == "history mean"]
    safety = [row for row in rows if row["label"].startswith("mean")]
    lines = [
        f"# Week {args.week}: safety stock does not close the oracle gap",
        "",
        "Week49 showed that target-demand stock is an oracle upper bound. "
        "Week50 tests whether a standard order-up-to safety-stock rule closes "
        "the gap: per SKU, stock = `mean + z × std` of the prior 6 weekly "
        "demands, scaled to the sampled order count. No target demand is used.",
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
    if safety:
        low = safety[0]
        high = safety[-1]
        lines.append(
            f"- **Even a 99% safety factor is far below oracle service**: "
            f"{high['stock_units']:,} units ({high['coverage']:.0%} of target "
            f"demand) reaches only {_pct(high['target'])} target/"
            f"{_pct(high['all'])} all with {high['backlog']:,.1f} backlog. "
            f"The oracle 140% policy holds {actual['stock_units']:,} units "
            f"({actual['coverage']:.0%}) and reaches "
            f"{_pct(actual['target'])}/{_pct(actual['all'])}."
        )
        lines.append(
            f"- **Safety stock is not a free substitute for the right SKU "
            f"mix**: z=1.645 holds {low['stock_units']:,} units and reaches "
            f"{_pct(low['target'])} target, while the simpler history-200% "
            f"policy holds {history[-1]['stock_units']:,} units and reaches "
            f"{_pct(history[-1]['target'])}. Safety allocates stock by demand "
            "volatility, not by the target week's SKU ranking."
        )
        if len(safety) > 1 and len(history) > 1:
            lines.append(
                f"- **More safety stock improves backlog more than target "
                f"OTIF**: z=2.326 holds {high['stock_units']:,} units vs "
                f"history-200% {history[-1]['stock_units']:,}, cuts backlog "
                f"{history[-1]['backlog']:,.1f}→{high['backlog']:,.1f}, but "
                f"target OTIF moves {_pct(history[-1]['target'])}→"
                f"{_pct(high['target'])} (slightly down) and all OTIF "
                f"{_pct(history[-1]['all'])}→{_pct(high['all'])} (slightly "
                "down). Aggregate safety stock buys tail coverage, not the "
                "specific high-demand SKUs that drive target OTIF."
            )
    lines += [
        "- **The binding constraint is per-SKU/DC demand location, not total "
        "units.** A deployable policy needs a forecast of the target-week SKU "
        "mix, not a larger buffer on the historical mix.",
        "- Safety stock uses a normal approximation on 6 weekly observations; "
        "it has no seasonality, promotion, lead time, replenishment, "
        "substitution or DC-level forecast. It is a negative result about "
        "this simple policy, not a claim that all safety stock is useless.",
        "- One target week, 400 invoices, 30 seeds × 3 repeats, fixed layout/"
        "shift; the oracle row is still not executable.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary.write_text(
        json.dumps(
            {
                "week": args.week,
                "rows": rows,
                "actual_factor": 1.4,
                "history_factors": [1.4, 2.0],
                "safety_z": [1.645, 2.326],
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
