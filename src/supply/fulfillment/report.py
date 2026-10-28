"""Markdown + JSON report for the order fulfillment benchmark."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_(empty)_"
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for _, row in frame.iterrows():
        cells = []
        for value in row:
            if isinstance(value, float):
                cells.append("—" if not math.isfinite(value) else f"{value:,.4g}")
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                cells.append("—")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2%}"


def _num(value: Any, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"


def _scenario_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    table = []
    for row in rows:
        table.append(
            {
                "scenario": row["name"],
                "status": row["status"],
                "unit fill": _pct(row["unit_fill"]),
                "order fill": _pct(row["order_fill"]),
                "OTIF": _pct(row["otif"]),
                "on-time units": _pct(row["on_time_unit_rate"]),
                "split orders": _pct(row["split_rate"]),
                "shipments": _num(row["shipments"]),
                "transport": _num(row["transport"]),
                "fixed": _num(row["fixed"]),
                "late": _num(row["late"]),
                "unmet": _num(row["unmet"]),
                "total": _num(row["total"]),
                "solve (s)": _num(row["solve_seconds"], 2),
            }
        )
    return pd.DataFrame(table)


def _dc_rows(load: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "DC": row["dc"],
                "units": _num(row["units"]),
                "capacity": _num(row["capacity"]),
                "capacity use": _pct(row["utilization"]),
                "stock left": _num(row["stock_left"]),
            }
            for row in load
        ]
    )


def _promise_rows(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "promise": row["promise"],
                "orders": _num(row["orders"]),
                "OTIF": _pct(row["otif"]),
                "late units": _num(row["late_units"]),
                "unmet units": _num(row["unmet_units"]),
            }
            for row in rows
        ]
    )


def _example_rows(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "order": row["order"],
                "destination": row["destination"],
                "promise": f"{row['promise']}d",
                "units": _num(row["units"]),
                "greedy DCs": " + ".join(row["greedy_dcs"]) or "—",
                "greedy OTIF": "yes" if row["greedy_otif"] else "no",
                "MILP DCs": " + ".join(row["milp_dcs"]) or "—",
                "MILP OTIF": "yes" if row["milp_otif"] else "no",
                "MILP late units": _num(row["milp_late_units"]),
            }
            for row in rows
        ]
    )


def build_fulfillment_report(
    results: Dict[str, Any],
    title: str = "Order fulfillment benchmark",
    generated: str = "",
) -> str:
    dataset = results["dataset"]
    instance = results["instance"]
    scenarios = results["scenarios"]
    best = max(scenarios, key=lambda row: (row["otif"], row["unit_fill"]))
    lines = [
        f"# {title}",
        "",
        f"- Generated: `{generated}`",
        (
            f"- Orders: **{_num(instance['orders'])}** real invoices / "
            f"**{_num(instance['order_lines'])}** lines / "
            f"**{_num(instance['units'])}** units / "
            f"**{_num(instance['skus'])}** SKUs, week {instance['week']}"
        ),
        (
            f"- Network: **{len(instance['dcs'])} DCs** "
            f"({', '.join(instance['dcs'])}); stock covers "
            f"**{_pct(instance['stock_coverage'])}** of sampled demand; "
            f"promise tiers {instance['promise_mix']}"
        ),
        (
            f"- Dataset window: {dataset['period_start']} → {dataset['period_end']} "
            f"({_num(dataset['clean_rows'])} cleaned transactions)"
        ),
        f"- Best scenario in this run: **{best['name']}** (OTIF {_pct(best['otif'])})",
        "",
        "## Assumptions",
        "",
        "- Orders, line quantities, SKU mix, and destination countries come from real invoices; stock placement, DC capacity, transit times, shipping rates, and SLA promises are declared assumptions.",
        (
            f"- Stock: {_pct(instance['stock_coverage'])} of demand, split by "
            f"{instance['stock_shares']} with deterministic per-SKU jitter; weekly "
            f"throughput caps are {instance['capacity_shares']} of total units."
        ),
        (
            f"- Transit: {instance['handling_days']} handling day + "
            f"ceil(road km / {_num(instance['transit_km_per_day'])}) days; "
            f"observed range **{instance['transit_days_range'][0]}–"
            f"{instance['transit_days_range'][1]}** days."
        ),
        (
            f"- Cost: road km × **{_num(instance['freight_cost_per_unit_km'], 4)}** "
            f"per unit + DC handling; fixed "
            f"**{_num(instance['fixed_ship_cost'], 2)}** per shipment, late "
            f"**{_num(instance['late_penalty_per_unit_day'], 2)}/unit/day**, "
            f"lost sale **{_num(instance['unmet_penalty_per_unit'], 2)}/unit**."
        ),
        "",
        "## Scenario comparison",
        "",
        _md_table(_scenario_table(scenarios)),
        "",
        "Metric definitions: unit fill = shipped / ordered units; order fill = orders with every unit shipped; OTIF = order fully shipped *and* fully on time; split orders = share of orders served by more than one DC; on-time units = shipped units that arrive within the promise.",
        "",
    ]
    service = results.get("service")
    if service:
        lines.extend(
            [
                (
                    f"All MILP rows share the same constraints and "
                    f"{_num(service['time_limit_seconds'])}s search budget. The last row "
                    f"re-weights the objective only: lateness × "
                    f"{_num(service['late_weight'], 1)} and a per-order OTIF bonus of "
                    f"{_num(service['otif_bonus'])}. Reported costs always use the base "
                    f"penalties, so rows are directly comparable."
                ),
                "",
            ]
        )
    for scenario in scenarios:
        lines.extend(
            [
                f"### {scenario['name']} — DC load",
                "",
                _md_table(_dc_rows(scenario["dc_load"])),
                "",
                f"### {scenario['name']} — promise tiers",
                "",
                _md_table(_promise_rows(scenario["promise"])),
                "",
            ]
        )

    examples = results.get("examples", [])
    if examples:
        lines.extend(
            [
                "## Orders where the MILP differs from greedy",
                "",
                _md_table(_example_rows(examples)),
                "",
            ]
        )

    lines.extend(
        [
            "## Notes and limitations",
            "",
            "- The instance is one trading week with a fixed stock snapshot; no replenishment, order cancellation, or multi-day promise rolling.",
            "- Transit days and SLA tiers are assumptions. They create the cost-vs-lateness trade-off but are not validated against carrier data.",
            "- The MILP is solved with a deterministic one-worker search and a wall-clock limit; `OPTIMAL` is not guaranteed on larger instances. Rows marked `FEASIBLE` are valid plans but not proven optimal; the JSON summary keeps the solver bound, which is loose here because of the fixed-charge and split binaries.",
            "- The service-weighted row is a policy choice, not a free improvement: it spends objective weight on whole-order OTIF, and the chosen weights are a declared assumption rather than a tuned production setting.",
            "- Lost sales are penalised at a flat per-unit rate, so the model does not distinguish strategic customers or backorders.",
            "- Distances are great-circle × road factor between DC and country centroid, not real lane distances.",
            "",
        ]
    )
    return "\n".join(lines)


def write_fulfillment_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Order fulfillment benchmark",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    report_path = out / "FULFILLMENT_REPORT.md"
    summary_path = out / "fulfillment_summary.json"
    report_path.write_text(
        build_fulfillment_report(results, title=title, generated=generated),
        encoding="utf-8",
    )
    payload = {
        "generated": generated,
        "title": title,
        **results,
    }
    summary_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": report_path, "summary": summary_path}
