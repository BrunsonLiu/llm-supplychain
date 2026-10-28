"""Markdown + JSON report for the wave-picking benchmark."""
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
    return pd.DataFrame(
        [
            {
                "scenario": row["scenario"],
                "status": row["status"],
                "waves": row["waves"],
                "orders/wave": _num(row["avg_orders"], 1),
                "lines/wave": _num(row["avg_lines"], 1),
                "travel m/order": _num(row["travel_per_order"], 1),
                "travel saving": _pct(row["travel_saving"]),
                "labor min/order": _num(row["labor_per_order"], 2),
                "labor saving": _pct(row["labor_saving"]),
                "orders/hour": _num(row["orders_per_hour"], 1),
                "labor cost": _num(row["labor_cost"]),
                "solve (s)": _num(row["solve_seconds"], 2),
            }
            for row in rows
        ]
    )


def _capacity_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario": row["scenario"],
                "waves": row["waves"],
                "max lines/wave": row["max_lines"],
                "max units/wave": _num(row["max_units"], 0),
                "candidate pool": row["pool_size"],
            }
            for row in rows
        ]
    )


def _wave_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "wave": row["wave"],
                "orders": row["orders"],
                "lines": row["lines"],
                "units": _num(row["units"]),
                "travel m": _num(row["travel_m"], 1),
                "invoices": row["invoices"],
            }
            for row in rows
        ]
    )


def _sensitivity_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "capacity (orders/lines)": row["caps"],
                "savings waves": row["savings_waves"],
                "MIP waves": row["mip_waves"],
                "wave delta": row["mip_waves"] - row["savings_waves"],
                "savings min/order": _num(row["savings_labor"], 3),
                "MIP min/order": _num(row["mip_labor"], 3),
                "labor delta": _pct(
                    row["mip_labor"] / row["savings_labor"] - 1.0
                ),
                "MIP status": row["mip_status"],
                "pool": row["pool_size"],
            }
            for row in rows
        ]
    )


def _assumption_table(meta: Dict[str, Any]) -> pd.DataFrame:
    rows = [
        ("orders", _num(meta.get("orders")), "real invoices from one trading week"),
        ("lines", _num(meta.get("lines")), "invoice × SKU, duplicates removed"),
        ("SKUs", _num(meta.get("skus")), "mapped to ABC slots"),
        ("slots", _num(meta.get("layout_slots")), "8 aisles × 16 bays × 2 sides"),
        ("max orders/wave", _num(meta.get("max_orders")), "declared cart/tote capacity"),
        ("max lines/wave", _num(meta.get("max_lines")), "declared pick capacity"),
        (
            "walking speed",
            f"{_num(meta.get('travel_meters_per_minute'), 0)} m/min",
            "1.2 m/s with a cart; assumed",
        ),
        (
            "pick time",
            f"{_num(meta.get('pick_minutes_per_line'), 2)} min/line + "
            f"{_num(meta.get('pick_minutes_per_unit'), 2)} min/unit",
            "assumed",
        ),
        (
            "wave setup",
            f"{_num(meta.get('setup_minutes_per_wave'), 1)} min/wave",
            "release, tote induction; assumed",
        ),
        (
            "labor cost",
            f"{_num(meta.get('labor_cost_per_minute'), 2)} /min",
            "fully loaded picker cost; assumed",
        ),
    ]
    return pd.DataFrame(rows, columns=["parameter", "value", "source"])


def build_wave_report(
    results: Dict[str, Any],
    title: str = "Wave picking benchmark",
    generated: str = "",
) -> str:
    dataset = results["dataset"]
    meta = results["assumptions"]
    scenarios = results["summary"]
    best = min(
        scenarios,
        key=lambda row: (
            row["labor_minutes"],
            0 if row["key"] == "milp" else 1,
        ),
    )
    baseline = next(row for row in scenarios if row["key"] == "single_order")
    savings = next(row for row in scenarios if row["key"] == "savings")
    milp = next(row for row in scenarios if row["key"] == "milp")
    sensitivity = results.get("sensitivity", [])
    travel_delta = milp["travel_saving"] - savings["travel_saving"]
    labor_delta = milp["labor_saving"] - savings["labor_saving"]
    if (
        abs(travel_delta) < 5e-4
        and abs(labor_delta) < 5e-4
        and milp["status"] == "OPTIMAL"
    ):
        milp_effect = (
            "It matches the savings heuristic and, with "
            f"`{milp['status']}` status, proves that this partition is optimal "
            f"for the {_num(milp['pool_size'])}-wave candidate pool."
        )
    elif abs(travel_delta) < 5e-4 and abs(labor_delta) < 5e-4:
        milp_effect = (
            "It matches the savings heuristic but did not prove optimality "
            "within the time budget; the reported solution is the savings partition."
        )
    else:
        milp_effect = (
            f"Relative to the savings heuristic it changes travel savings by "
            f"{_pct(travel_delta)} and labor savings by {_pct(labor_delta)}."
        )
    if sensitivity:
        tight = min(
            sensitivity,
            key=lambda row: row["mip_waves"] - row["savings_waves"],
        )
        tight_text = (
            f"With a tighter **{tight['caps']}** cap the line limit binds: savings "
            f"needs {tight['savings_waves']} waves, CP-SAT packs it into "
            f"{tight['mip_waves']} (delta {tight['mip_waves'] - tight['savings_waves']:+d}), "
            f"and labor per order moves from {_num(tight['savings_labor'], 3)} to "
            f"{_num(tight['mip_labor'], 3)} minutes."
        )
    else:
        tight_text = (
            "Setup dominates when waves are small. The cap is a real operating "
            "constraint, not a free dial."
        )

    lines = [
        f"# {title}",
        "",
        f"- Generated: `{generated}`",
        (
            f"- Orders: **{_num(meta['orders'])}** real invoices / "
            f"**{_num(meta['lines'])}** lines / **{_num(meta['units'])}** units / "
            f"**{_num(meta['skus'])}** SKUs, week {dataset.get('period_end', '?')}"
        ),
        (
            f"- Warehouse: **{meta['layout_aisles']} aisles × "
            f"{meta['layout_bays']} bays**, ABC slotting; wave caps "
            f"**{meta['max_orders']} orders / {meta['max_lines']} lines**."
        ),
        f"- Best scenario in this run: **{best['scenario']}** "
        f"({_num(best['labor_minutes'], 0)} labor-minutes, "
        f"{_pct(best['labor_saving'])} below pick-by-order).",
        "",
        "## Assumptions",
        "",
        (
            "Orders, line quantities, and SKU mix come from real invoices. The "
            "warehouse layout, ABC slot assignment, wave capacity, walking speed, "
            "pick time, setup time, and labor rate are declared assumptions; "
            "none of them come from the dataset."
        ),
        "",
        _md_table(_assumption_table(meta)),
        "",
        "## Methods",
        "",
        "- **Pick-by-order (baseline)**: one wave per invoice; each order pays its own setup and dispatch trip.",
        "- **FCFS waves**: orders arrive in a seeded random sequence and fill a wave until the next order would exceed the order or line cap.",
        "- **Savings waves**: Clarke-Wright-style order savings. A pair is merged when the combined `return` route is shorter than the two separate routes, subject to wave capacity; randomized jitter gives the candidate pool several local variants.",
        "- **Set-partitioning CP-SAT**: candidate waves are singles, high-saving pairs, and waves from the savings runs. The model chooses one wave for every order and minimises travel minutes plus wave setup. `OPTIMAL` is optimal **for the candidate pool**, not over all subsets.",
        "",
        "## Scenario comparison",
        "",
        _md_table(_scenario_table(scenarios)),
        "",
        (
            "Travel is measured with the Week-3 `return` picker route over the "
            "union of wave slots. Labor = travel + line/unit pick time + wave "
            "setup; pick time is identical across scenarios, so the differences "
            "come from travel and setup."
        ),
        "",
        _md_table(_capacity_table(scenarios)),
        "",
        *(
            [
                "## 4. Wave-cap sensitivity",
                "",
                "The same orders are re-batched under tighter caps. This shows "
                "when the savings heuristic is already sufficient and when the "
                "solver earns its keep by repacking capacity.",
                "",
                _md_table(_sensitivity_table(sensitivity)),
                "",
            ]
            if sensitivity
            else []
        ),
        f"### Largest waves — {best['scenario']}",
        "",
        _md_table(_wave_table(results.get("detail", []))),
        "",
        "## How to read the result",
        "",
        (
            f"1. Pick-by-order needs **{baseline['waves']}** waves and "
            f"**{_num(baseline['travel_per_order'], 1)} m** of travel per order. "
            f"Savings batching cuts travel by **{_pct(savings['travel_saving'])}** "
            f"and labor by **{_pct(savings['labor_saving'])}** with "
            f"**{savings['waves']}** waves."
        ),
        (
            f"2. The CP-SAT row uses **{milp['waves']}** waves and reaches "
            f"**{_pct(milp['travel_saving'])}** travel savings / "
            f"**{_pct(milp['labor_saving'])}** labor savings versus pick-by-order. "
            f"{milp_effect}"
        ),
        f"3. {tight_text}",
        (
            "4. The gap between FCFS and batching is the value of grouping by "
            "slot proximity instead of arrival order. FCFS is intentionally a "
            "weak baseline; it shows why wave release needs a batching rule."
        ),
        "",
        "## Notes and limitations",
        "",
        "- One trading week and one static order pool; no cut-off times, picker shifts, wave sequencing, or carrier departure deadlines.",
        "- Wave capacity is modelled as order and line caps. Tote volume, weight, and cart cube are not modelled.",
        "- Pick time is linear in lines and units; congestion, replenishment, and picker learning are out of scope.",
        "- The CP-SAT model is a restricted set-partitioning model. Its `OPTIMAL` status is relative to the generated pool, and the pool is biased toward savings-style waves.",
        "- Solver runs use a wall-clock budget. On a different machine the sensitivity scenarios can switch between `OPTIMAL` and `FEASIBLE` and shift the packed waves slightly.",
        "- `return` routing is one policy; the Week-3 report shows that `optimal` routing changes absolute distances but not the slot layout ranking.",
        "",
    ]
    return "\n".join(lines)


def write_wave_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Wave picking benchmark",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    report_path = out / "WAVE_REPORT.md"
    summary_path = out / "wave_summary.json"
    report_path.write_text(
        build_wave_report(results, title=title, generated=generated),
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
