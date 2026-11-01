"""Decompose the stock effect into SKU mix vs total units (Week 52)."""
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
    parser = argparse.ArgumentParser(description="Stock mix/total decomposition")
    parser.add_argument("--out-dir", default="benchmarks")
    parser.add_argument("--week", type=int, default=52)
    parser.add_argument("--stem", default="ACCESS_STOCK_MIX")
    parser.add_argument(
        "--oracle", default="benchmarks/access_stock140_summary.json"
    )
    parser.add_argument(
        "--actual-mix", default="benchmarks/access_mix_actual_summary.json"
    )
    parser.add_argument(
        "--history-mix", default="benchmarks/access_mix_history_summary.json"
    )
    parser.add_argument(
        "--history140", default="benchmarks/access_hist14_summary.json"
    )
    parser.add_argument(
        "--history200", default="benchmarks/access_hist20_summary.json"
    )
    args = parser.parse_args()
    rows: List[Dict[str, Any]] = [
        _row("actual mix @ 46,281", json.loads(
            Path(args.oracle).read_text(encoding="utf-8")
        )),
        _row("actual mix @ 44,824", json.loads(
            Path(args.actual_mix).read_text(encoding="utf-8")
        )),
        _row("history mix @ 44,824", json.loads(
            Path(args.history140).read_text(encoding="utf-8")
        )),
        _row("history mix @ 46,288", json.loads(
            Path(args.history_mix).read_text(encoding="utf-8")
        )),
        _row("history mix @ 64,039", json.loads(
            Path(args.history200).read_text(encoding="utf-8")
        )),
    ]
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / f"{args.stem}_REPORT.md"
    summary = out / f"{args.stem.lower()}_summary.json"
    a = rows[1]  # actual mix at history total
    h = rows[2]  # history mix at history total
    h_at_actual = rows[3]
    h200 = rows[4]
    lines = [
        f"# Week {args.week}: SKU mix dominates total stock",
        "",
        "Week49-51 changed the stock basis and total together, so they could not "
        "say whether the service loss came from **less total stock** or from "
        "**the wrong SKU mix**. Week52 holds one factor fixed at a time, using "
        "the same 400 orders, seeds and DC shares.",
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
        f"- **At the same 44,824 units, SKU mix moves target by "
        f"{100.0 * (a['target'] - h['target']):+.1f}pp**: actual mix "
        f"{_pct(a['target'])}/{_pct(a['all'])} vs history mix "
        f"{_pct(h['target'])}/{_pct(h['all'])}; backlog "
        f"{a['backlog']:,.1f} vs {h['backlog']:,.1f}. This is the cleanest "
        "mix-only comparison."
    )
    lines.append(
        f"- **At the actual 46,288 units, history mix still only reaches "
        f"{_pct(h_at_actual['target'])} target** vs actual mix "
        f"{_pct(rows[0]['target'])} at 46,281. Adding 1,464 units to the "
        f"wrong mix (44,824→46,288) buys "
        f"{100.0 * (h_at_actual['target'] - h['target']):+.1f}pp target, "
        f"{100.0 * (h_at_actual['all'] - h['all']):+.1f}pp all and cuts "
        f"backlog {h['backlog'] - h_at_actual['backlog']:,.0f}; the total "
        "effect is second-order next to the ~28pp mix gap."
    )
    lines.append(
        f"- **Even 64,039 units with the wrong mix is only "
        f"{_pct(h200['target'])} target**: history-200 has "
        f"{h200['stock_units'] - h['stock_units']:,} more units than "
        f"history-140 and buys {100.0 * (h200['target'] - h['target']):+.1f}pp, "
        f"while the actual mix at 44,824 buys "
        f"{100.0 * (a['target'] - h['target']):+.1f}pp with no extra stock. "
        "SKU mix is the first-order lever."
    )
    lines += [
        "- The actual-mix row is still an **oracle counterfactual**: it uses "
        "the target week's per-SKU demand. It is a decomposition tool, not a "
        "deployable policy. The deployable question is how to forecast the "
        "SKU mix; Week51 shows a 200-SKU LightGBM forecast is not enough.",
        "- Stock shares and per-SKU jitter are unchanged; this isolates the "
        "per-SKU total, not DC placement. One target week, 400 invoices, "
        "30 seeds × 3 repeats.",
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
