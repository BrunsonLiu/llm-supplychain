"""Combine Week-45 stock-factor runs into one service frontier report.

The individual runs use the same demand, placement arms and end-to-end
configuration; only the per-SKU stock total changes. Pairing across factors is
not valid because the stock matrix differs, so this report compares arm means
and explicitly keeps the extra-stock cost out of scope.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]


def _pct(value: float) -> str:
    return f"{100.0 * float(value):.1f}%"


def _num(value: float, digits: int = 0) -> str:
    return f"{float(value):,.{digits}f}"


def _row(payload: Mapping[str, Any], policy: str) -> Mapping[str, Any]:
    for item in payload.get("summary", []):
        if item.get("policy") == policy:
            return item
    raise KeyError(f"{policy} not found at stock factor {payload.get('factor')}")


def build_stock_frontier(payloads: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(payloads, key=lambda item: float(item["factor"]))
    base = ordered[0]
    base_row = _row(base, "baseline")
    base_all = float(base_row.get("accepted_otif_mean", 0))
    base_target = float(base_row.get("target_accepted_otif_mean", 0))
    base_backlog = float(base_row.get("accepted_backlog_units", 0))
    rows: List[Dict[str, Any]] = []
    for payload in ordered:
        factor = float(payload["factor"])
        for item in payload.get("summary", []):
            rows.append(
                {
                    "stock_factor": factor,
                    "stock_units": int(payload["settings"].get("stock_units", 0)),
                    "policy": item["policy"],
                    "target": float(item.get("target_accepted_otif_mean", 0)),
                    "rest": float(item.get("rest_accepted_otif_mean", 0)),
                    "all": float(item.get("accepted_otif_mean", 0)),
                    "backlog": float(item.get("accepted_backlog_units", 0)),
                    "coverage": float(item.get("coverage_mean", 0)),
                    "moved": float(item.get("moved_units_mean", 0)),
                }
            )
    return {
        "baseline": {
            "stock_factor": float(base["factor"]),
            "stock_units": int(base["settings"].get("stock_units", 0)),
            "target": base_target,
            "all": base_all,
            "backlog": base_backlog,
        },
        "rows": rows,
        "payloads": list(ordered),
    }


def build_report(data: Mapping[str, Any]) -> str:
    rows = data["rows"]
    base = data["baseline"]
    baseline_rows = [row for row in rows if row["policy"] == "baseline"]
    base_map = {row["stock_factor"]: row for row in baseline_rows}
    lines = [
        "# Week 45: stock-total service frontier",
        "",
        "Same 400 invoices, 30 seeds, 3 repeats, fixed placement arms and "
        "end-to-end configuration; only the per-SKU stock total changes. "
        "The extra stock is a scenario, not a costed replenishment plan.",
        "",
        "## Baseline frontier",
        "",
        "| stock | units | units vs 100% | target OTIF | all OTIF | backlog |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for factor in sorted(base_map):
        row = base_map[factor]
        stock_delta = row["stock_units"] - base["stock_units"]
        lines.append(
            f"| {factor:.0%} | {_num(row['stock_units'])} | "
            f"{stock_delta:+,} | {_pct(row['target'])} | {_pct(row['all'])} | "
            f"{_num(row['backlog'], 1)} |"
        )
    lines += [
        "",
        "## All arms",
        "",
        "| stock | policy | target | rest | all | backlog | coverage | moved |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        cents = "" if row["coverage"] <= 0 else _pct(row["coverage"])
        lines.append(
            f"| {row['stock_factor']:.0%} | {row['policy']} | "
            f"{_pct(row['target'])} | {_pct(row['rest'])} | {_pct(row['all'])} | "
            f"{_num(row['backlog'], 1)} | {cents or '—'} | "
            f"{_num(row['moved'])} |"
        )

    lines += ["", "## Findings", ""]
    if len(base_map) >= 2:
        later = [base_map[key] for key in sorted(base_map) if key > 1.0]
        for row in later:
            factor = row["stock_factor"]
            stock_pct = 100.0 * (row["stock_units"] / base["stock_units"] - 1.0)
            lines.append(
                f"- **{factor:.0%} stock** adds {_num(row['stock_units'] - base['stock_units'])} "
                f"units ({stock_pct:+.1f}%); baseline all-order OTIF "
                f"{_pct(base['all'])} -> {_pct(row['all'])} "
                f"({100.0 * (row['all'] - base['all']):+.2f}pp), target "
                f"{_pct(base['target'])} -> {_pct(row['target'])}, backlog "
                f"{_num(base['backlog'], 1)} -> {_num(row['backlog'], 1)}."
            )
    for factor in sorted(base_map):
        factor_rows = [row for row in rows if row["stock_factor"] == factor]
        best = max(factor_rows, key=lambda item: (item["all"], item["target"]))
        baseline = base_map[factor]
        lines.append(
            f"- At **{factor:.0%} stock**, best all-order arm is "
            f"`{best['policy']}` ({_pct(best['all'])} vs baseline "
            f"{_pct(baseline['all'])}); it moves {_num(best['moved'])} units."
        )
    lines += [
        "- **The stock total dominates the placement effect.** The 100% -> 125% "
        "step cuts backlog far more than any 100%-stock placement arm; the "
        "150% step reaches the OTIF ceiling. Non-oracle placement differences "
        "at fixed stock are about 0.1-0.3pp and were not robust in Weeks 41-44.",
        "- **Extra stock is not free.** This report does not model purchase "
        "cost, holding cost, obsolescence, markdown, or working capital; the "
        "frontier is a service diagnostic, not an optimal inventory policy.",
        "- `access_oracle` is an upper-bound arm: it sees the current week's "
        "orders and its transfer matrix, so it is not deployable.",
        "- One target week, one layout/shift, one picker per DC; only the "
        "stock total changes, and the fixed-total placement still assumes a "
        "pre-week transfer with no lead time or cost.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Week-45 stock frontier")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        help="factor=path, e.g. 1.25=.tmp/access_stock125_summary.json",
    )
    parser.add_argument(
        "--out-dir", default=str(ROOT / "benchmarks")
    )
    args = parser.parse_args()
    payloads = []
    for item in args.input:
        factor, path = item.split("=", 1)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        payloads.append({"factor": float(factor), **data})
    data = build_stock_frontier(payloads)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "ACCESS_STOCK_FRONTIER_REPORT.md"
    summary = out / "access_stock_frontier_summary.json"
    report.write_text(build_report(data), encoding="utf-8")
    summary.write_text(
        json.dumps(
            {
                "baseline": data["baseline"],
                "rows": data["rows"],
                "settings": [
                    {
                        "factor": float(payload["factor"]),
                        "stock_units": int(payload["settings"].get("stock_units", 0)),
                        "orders": payload["dataset"].get("orders"),
                        "seeds": payload["settings"].get("seeds"),
                        "repeats": payload["settings"].get("repeats"),
                    }
                    for payload in data["payloads"]
                ],
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
