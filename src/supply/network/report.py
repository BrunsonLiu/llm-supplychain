"""Markdown + JSON report for the network and warehouse benchmark."""
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
    if pd.isna(value):
        return None
    return value


def _md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_(empty)_"
    columns = [str(col) for col in frame.columns]
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


def _cost_table(location: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for key, label in (("baseline", "all hubs open, nearest"), ("optimized", "CFLP optimum")):
        row = location.get(key, {})
        rows.append(
            {
                "method": label,
                "status": row.get("status"),
                "hubs": row.get("opened"),
                "fixed cost": _num(row.get("fixed_cost")),
                "transport cost": _num(row.get("transport_cost")),
                "total cost": _num(row.get("total_cost")),
                "avg road km": _num(row.get("avg_distance_km"), 0),
                "solve (s)": _num(row.get("solve_seconds"), 2),
            }
        )
    return pd.DataFrame(rows)


def _facility_table(location: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in location.get("facilities", []):
        rows.append(
            {
                "hub": row["facility"],
                "units": _num(row.get("units")),
                "capacity use": _pct(row.get("utilization")),
                "fixed cost": _num(row.get("fixed_cost")),
            }
        )
    return pd.DataFrame(rows)


def _sensitivity_table(location: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in location.get("sensitivity", []):
        rows.append(
            {
                "fixed-cost multiplier": f"{row['fixed_cost_multiplier']:g}x",
                "status": row["status"],
                "hubs": row["opened"],
                "fixed cost": _num(row.get("fixed_cost")),
                "transport": _num(row.get("transport_cost")),
                "total": _num(row.get("total_cost")),
                "hubs opened": row.get("facilities", ""),
            }
        )
    return pd.DataFrame(rows)


def _demand_table(location: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in location.get("demand", []):
        rows.append(
            {
                "country": row["country"],
                "units": _num(row.get("units")),
                "share": _pct(row.get("share")),
            }
        )
    return pd.DataFrame(rows)


def _routing_table(routing: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in routing.get("plans", []):
        rows.append(
            {
                "method": row["method"],
                "distance km": _num(row.get("distance_km"), 1),
                "vehicles": row.get("vehicles"),
                "max load": _num(row.get("max_load")),
                "route minutes": _num(row.get("total_minutes"), 0),
                "feasible": "yes" if row.get("feasible") else "no",
                "solve (s)": _num(row.get("solve_seconds"), 3),
            }
        )
    return pd.DataFrame(rows)


def _route_detail(routing: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in routing.get("routes", []):
        rows.append(
            {
                "vehicle": row["vehicle"],
                "stores": row["stores"],
                "load": _num(row.get("load")),
                "distance km": _num(row.get("distance_km"), 1),
                "visits (minutes)": row.get("arrivals", ""),
            }
        )
    return pd.DataFrame(rows)


def _picking_table(warehouse: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in warehouse.get("summary", []):
        rows.append(
            {
                "slotting": row["slotting"],
                "orders": row.get("orders"),
                "avg lines": _num(row.get("avg_lines"), 1),
                "return m": _num(row.get("return_m"), 1),
                "S-shape m": _num(row.get("s_shape_m"), 1),
                "optimal m": _num(row.get("optimal_m"), 1),
                "return saving": _pct(row.get("return_saving")),
                "optimal saving": _pct(row.get("optimal_saving")),
            }
        )
    return pd.DataFrame(rows)


def _assignment_table(warehouse: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in warehouse.get("sample", []):
        rows.append(
            {
                "SKU": row["sku"],
                "ABC class": row["abc"],
                "slot (aisle, bay)": row["slot"],
                "distance to dispatch (m)": _num(row.get("depot_m"), 1),
            }
        )
    return pd.DataFrame(rows)


def build_network_report(
    results: Dict[str, Any], title: str = "Network & warehouse benchmark"
) -> tuple[Dict[str, Any], str]:
    dataset = results.get("dataset", {})
    location = results.get("location", {})
    routing = results.get("routing", {})
    warehouse = results.get("warehouse", {})
    timestamp = datetime.now(timezone.utc).isoformat()

    summary = {
        "generated_at": timestamp,
        "title": title,
        "dataset": _json_safe(dataset),
        "location": _json_safe(location),
        "routing": _json_safe(routing),
        "warehouse": _json_safe(warehouse),
    }

    lines = [f"# {title}", ""]
    lines.append(f"- Generated: `{timestamp}`")
    lines.append(
        f"- Data: Online Retail II transaction lines (full span "
        f"`{dataset.get('transaction_start', '?')}` → `{dataset.get('transaction_end', '?')}`); "
        f"{dataset.get('skus', '?')} SKUs, demand window "
        f"`{dataset.get('period_start', '?')}` → `{dataset.get('period_end', '?')}`."
    )
    lines.append(
        f"- Observed: unit demand by country, order lines, SKU popularity. "
        f"Assumed: country centroids, hub candidates/costs, fleet, store coordinates, "
        f"warehouse layout and travel speed."
    )
    lines.append("")

    lines.extend(["## 1. Capacitated facility location (CFLP)", ""])
    meta = location.get("meta", {})
    lines.append(
        f"- Demand coverage: **{_pct(meta.get('coverage_share'))}** of selected units "
        f"({_num(meta.get('covered_units'))} of {_num(meta.get('total_units_all_countries'))}); "
        f"countries without a mapped coordinate are excluded."
    )
    lines.append(
        f"- Transport: {_num(meta.get('transport_cost_per_unit_km'), 5)} currency/unit/road-km, "
        f"road factor {_num(meta.get('road_factor'), 2)}; fixed costs are per year."
    )
    lines.append(
        "- Model: CP-SAT with integer unit flows. The baseline opens every hub and "
        "assigns each country to the cheapest hub with remaining capacity."
    )
    lines.append("")
    lines.append(_md_table(_cost_table(location)))
    lines.append("")
    if location.get("optimized"):
        optimized = location["optimized"]
        baseline = location.get("baseline", {})
        saving = 1.0 - optimized.get("total_cost", 0.0) / baseline.get("total_cost", 1.0)
        lines.append(
            f"- CFLP opens **{optimized.get('opened')}** hubs and cuts annual cost by "
            f"**{_pct(saving)}** versus all-open nearest assignment."
        )
        lines.append("")
    lines.append(_md_table(_facility_table(location)))
    lines.append("")
    lines.extend(["### 1b. Demand geography", ""])
    lines.append(_md_table(_demand_table(location)))
    lines.append("")
    lines.extend(["### 1c. Fixed-cost sensitivity", ""])
    lines.append(
        "Fixed costs are assumptions, so the open/close decision is re-solved across "
        "multipliers. This is the honest way to show how sensitive the network is."
    )
    lines.append("")
    lines.append(_md_table(_sensitivity_table(location)))
    lines.append("")

    lines.extend(["## 2. Vehicle routing (CVRP / VRPTW)", ""])
    routing_meta = routing.get("meta", {})
    lines.append(
        f"- One depot, **{routing_meta.get('customers', '?')}** stores, "
        f"**{routing_meta.get('vehicles', '?')}** vehicles, capacity "
        f"{_num(routing_meta.get('capacity'))} units, speed "
        f"{_num(routing_meta.get('speed_kmh'))} km/h, service "
        f"{_num(routing_meta.get('service_minutes'))} min, horizon "
        f"{_num(routing_meta.get('horizon_minutes'))} min."
    )
    lines.append(
        "- Store demand comes from the real weekly basket; store shares and coordinates "
        "are the same assumed network as the allocation LP. Distances are Euclidean km "
        "on that grid."
    )
    lines.append("")
    lines.append(_md_table(_routing_table(routing)))
    lines.append("")
    if routing.get("routes"):
        lines.append("OR-Tools CVRP routes, store level:")
        lines.append("")
        lines.append(_md_table(_route_detail(routing)))
        lines.append("")
    lines.append(
        "- The exact subset DP is a proven optimum for this small instance and is used "
        "to validate the OR-Tools result, not as a production solver. Clarke-Wright is a "
        "fast constructive baseline; the gap between it and the solver is the value of "
        "local search on this instance."
    )
    lines.append("")

    lines.extend(["## 3. Warehouse slotting and picking", ""])
    warehouse_meta = warehouse.get("meta", {})
    lines.append(
        f"- Layout: {warehouse_meta.get('aisles', '?')} aisles × "
        f"{warehouse_meta.get('bays', '?')} bays × 2 sides = "
        f"**{warehouse_meta.get('slots', '?')}** slots; front and back cross-aisles; "
        f"bay {_num(warehouse_meta.get('bay_meters'), 1)} m, aisle gap "
        f"{_num(warehouse_meta.get('aisle_gap_meters'), 1)} m."
    )
    lines.append(
        f"- Orders: {warehouse_meta.get('sampled_invoices', '?')} sampled invoices from "
        f"the week of `{warehouse_meta.get('week', '?')}`, "
        f"{_num(warehouse_meta.get('median_lines_per_order'), 0)} median lines/order, "
        f"{warehouse_meta.get('unique_skus', '?')} unique SKUs."
    )
    lines.append(
        "- ``abc`` places SKUs by 52-week velocity, closest to dispatch first; "
        "``random`` is the control. Savings are relative to the random-slotting "
        "distance under the same routing policy."
    )
    lines.append("")
    lines.append(_md_table(_picking_table(warehouse)))
    lines.append("")
    lines.append("Highest-velocity SKUs under ABC slotting:")
    lines.append("")
    lines.append(_md_table(_assignment_table(warehouse)))
    lines.append("")
    lines.append(
        "- ``return`` walks into an aisle and back to the front cross-aisle; "
        "``S-shape`` traverses the full aisle and alternates ends; ``optimal`` solves "
        "the picker TSP (Held-Karp at ≤12 picks, 2-opt above). S-shape only wins when "
        "picks are dense: with ~6 lines spread over 256 slots it adds empty aisle "
        "travel, which is why it trails the return policy here."
    )
    lines.append("")

    lines.extend(
        [
            "## 4. Limitations",
            "",
            "- Country centroids, hub fixed costs/capacities, store coordinates, fleet "
            "size, and warehouse layout are assumptions. They are declared in one module "
            "and configurable; none of them come from the dataset.",
            "- CFLP uses annualised units from the last 52 weeks as a steady-state "
            "demand; seasonality and demand growth are not modelled.",
            "- The CVRP instance has eight stores. Exact DP validates the solver only at "
            "this scale; large instances would need the OR-Tools model and a longer "
            "search budget.",
            "- VRPTW uses four coarse two-hour receiving blocks and no driver shift "
            "rules, loading time, or stochastic travel times.",
            "- Warehouse distances are grid metrics with constant travel speed; pick "
            "time, congestion, and replenishment are out of scope here. Order batching "
            "and picker labor are covered in the Week-6 wave benchmark.",
            "- Routing search uses a fixed wall-clock limit, so a heavily loaded machine "
            "can return a slightly different plan. The CFLP uses a deterministic budget.",
        ]
    )
    return summary, "\n".join(lines)


def write_network_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Network & warehouse benchmark",
) -> Dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary, markdown = build_network_report(results, title=title)
    paths = {
        "markdown": out_dir / "NETWORK_REPORT.md",
        "summary": out_dir / "network_summary.json",
    }
    paths["markdown"].write_text(markdown, encoding="utf-8")
    with open(paths["summary"], "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    return paths
