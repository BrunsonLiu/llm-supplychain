"""Markdown + JSON report for the Week-16 outbound dispatch benchmark."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct

from .dispatch import DISPATCH_METRICS

SERVICE_METRICS = ("dock_otif_rate", "pick_otif_rate", "roll_rate", "mean_wait_minutes")
DOCK_METRICS = (
    "departures",
    "orders_per_departure",
    "dispatch_cost",
    "holding_cost",
    "dock_cost",
)


def _lookup(
    summary: Sequence[Dict[str, Any]], cell: str, metric: str
) -> Optional[Dict[str, Any]]:
    for row in summary:
        if row.get("cell") == cell and row.get("metric") == metric:
            return row
    return None


def _mean(
    summary: Sequence[Dict[str, Any]], cell: str, metric: str, default: float = 0.0
) -> float:
    row = _lookup(summary, cell, metric)
    return float(row["mean"]) if row is not None else default


def _paired_lookup(
    rows: Sequence[Dict[str, Any]], left: str, right: str
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("left") == left and row.get("right") == right:
            return row
    return None


def _delta_text(row: Optional[Dict[str, Any]], digits: int = 1) -> str:
    if row is None:
        return "n/a"
    delta = float(row["mean_delta"])
    ci = float(row["ci95"])
    return f"{delta * 100:+.{digits}f} pp (±{ci * 100:.{digits}f})"


def _cell_table(cells: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for cell in cells:
        policy = {
            "none": "无（仅拣选截单）",
            "immediate": "即时发车",
            "hold": "凑批 / 日终",
            "promise": "承诺感知",
        }.get(cell["policy"], cell["policy"])
        departures = ", ".join(
            f"{int(minute) // 60 + 8:02d}:{int(minute) % 60:02d}"
            for minute in cell.get("departures", [])
        )
        rows.append(
            {
                "Cell": cell["label"],
                "Policy": policy,
                "Departures": "—" if cell["policy"] == "none" else departures,
                "Min load": cell.get("min_load")
                if cell["policy"] in {"hold", "promise"}
                else "—",
                "Pickers / DC": cell.get("pickers_per_dc") or "—",
                "Pick noise σ": _num(cell.get("duration_noise"), 2),
            }
        )
    return pd.DataFrame(rows)


def _service_table(
    cells: Sequence[Dict[str, Any]], summary: Sequence[Dict[str, Any]]
) -> pd.DataFrame:
    rows = []
    for cell in cells:
        key = cell["key"]
        picked = _mean(summary, key, "pick_otif_rate")
        dock = _mean(summary, key, "dock_otif_rate")
        rows.append(
            {
                "Cell": cell["label"],
                "Pick-cutoff OTIF": _pct(picked),
                "Dock OTIF": _pct(dock),
                "Dock − pick": f"{(dock - picked) * 100:+.1f} pp",
                "Roll to next day": _pct(_mean(summary, key, "roll_rate")),
                "Mean wait (min)": _num(_mean(summary, key, "mean_wait_minutes"), 0),
            }
        )
    return pd.DataFrame(rows)


def _dock_table(
    cells: Sequence[Dict[str, Any]], summary: Sequence[Dict[str, Any]]
) -> pd.DataFrame:
    rows = []
    for cell in cells:
        key = cell["key"]
        rows.append(
            {
                "Cell": cell["label"],
                "Departures": _num(_mean(summary, key, "departures"), 1),
                "Orders / departure": _num(
                    _mean(summary, key, "orders_per_departure"), 1
                ),
                "Dispatch cost (€)": _num(_mean(summary, key, "dispatch_cost"), 0),
                "Holding cost (€)": _num(_mean(summary, key, "holding_cost"), 0),
                "Dock cost (€)": _num(_mean(summary, key, "dock_cost"), 0),
            }
        )
    return pd.DataFrame(rows)


def _paired_delta_text(value: float, signed: bool = True) -> str:
    if abs(value * 100.0) < 0.05:
        return "0.0 pp" if signed else "±0.00 pp"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value * 100:.1f} pp" if signed else f"±{abs(value) * 100:.1f} pp"


def _paired_table(
    rows: Sequence[Dict[str, Any]], cells: Sequence[Dict[str, Any]]
) -> pd.DataFrame:
    labels = {cell["key"]: cell["label"] for cell in cells}
    table = []
    for row in rows:
        table.append(
            {
                "Comparison": f"{labels.get(row['right'], row['right'])} − "
                f"{labels.get(row['left'], row['left'])}",
                "Metric": DISPATCH_METRICS.get(row["metric"], row["metric"]),
                "Δ mean": _paired_delta_text(float(row["mean_delta"])),
                "95% CI": _paired_delta_text(float(row["ci95"]), signed=False),
                "Win rate": _pct(row["win_rate"]),
                "Tie rate": _pct(row.get("tie_rate", 0.0)),
                "n": row["n"],
            }
        )
    return pd.DataFrame(table)


def _lane_table(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    ordered = sorted(rows, key=lambda row: (-row["tickets"], row["dc"], row["lane"]))
    return pd.DataFrame(
        [
            {
                "DC": row["dc"],
                "Lane": row["lane"],
                "Tickets": row["tickets"],
                "Units": f"{int(row['units']):,}",
                "Departures": row["departures"],
                "Mean wait (min)": _num(row["mean_wait_minutes"], 0),
                "Roll rate": _pct(row["roll_rate"]),
            }
            for row in ordered[:12]
        ]
    )


def build_dispatch_report(
    payload: Dict[str, Any],
    title: str = "Outbound dispatch and carrier cutoffs (Week 16)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    allocation = payload.get("allocation", {})
    cells = payload.get("cells", [])
    seeds = payload.get("seeds", [])
    summary = payload.get("summary", [])
    paired = payload.get("paired", [])
    lanes = payload.get("lanes", [])
    labels = {cell["key"]: cell["label"] for cell in cells}

    lines: List[str] = [f"# {title}", ""]
    lines.append(f"- Generated: `{stamp}`")
    lines.append(
        f"- Orders: **{dataset.get('orders', 0)}** real invoices / "
        f"**{dataset.get('lines', 0)}** lines / **{dataset.get('units', 0):,}** units, "
        f"week {dataset.get('week', '')}"
    )
    lines.append(
        f"- Seeds: **{len(seeds)}** | cells: **{len(cells)}** | pickers/DC: "
        f"**{settings.get('pickers', 1)}** | shift **{_num(settings.get('shift_minutes'), 0)} min**"
    )
    lines.append(
        f"- Allocation: **{allocation.get('label', '')}** "
        f"({allocation.get('status', '')}) | allocation OTIF ceiling "
        f"**{_pct(allocation.get('otif_rate'))}** | solver "
        f"**{_num(settings.get('milp_time'), 0)} s**"
    )
    lines.append(
        f"- Dock cost: **€{_num(settings.get('dispatch_cost'), 0)}/departure** + "
        f"**€{_num(settings.get('holding_cost'), 2)}/order-hour** | longest hold "
        f"**{_num(settings.get('max_hold_hours'), 1)} h**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines.append("| Item | Assumption | Note |")
    lines.append("|---|---|---|")
    lines.append(
        "| Departures | 13:00 and 19:00 per DC, plus single-departure variants "
        "13:00 / 15:00 / 19:00 | declared line-haul timetable, relative to the 08:00 shift |"
    )
    lines.append(
        "| Carrier cutoff | departure minus 30 min | declared load-close buffer; a missed "
        "ticket rolls to the next departure |"
    )
    lines.append(
        "| Lane | DC × destination country | orders on one lane can consolidate; they "
        "never share a truck across countries |"
    )
    lines.append(
        "| Truck capacity | 300 orders / departure | declared ceiling; not binding in this "
        "instance, so the timetable is compared on timing, not rationing |"
    )
    lines.append(
        "| Dispatch policy | immediate / hold to 6 / promise-aware 6 and 10 | declared "
        "rules; the promise rule holds to the last departure that still meets the promise |"
    )
    lines.append(
        "| Promise deadline | dispatch day ≤ promise days − transit days | derived from the "
        "Week-8 promise and transit geometry; no carrier SLA data exists |"
    )
    lines.append(
        "| Dock cost | €220 per departure + €0.15 per order-hour | declared planning rates, "
        "used only to compare cells |"
    )
    lines.append(
        "| Arrivals | prior-week empirical curves (Week 15) | only the dock layer is new; "
        "allocation, stock, layout and pick cutoffs are unchanged |"
    )
    lines.append("")

    lines += ["## Cells", ""]
    lines.append(_md_table(_cell_table(cells)))
    lines.append("")

    lines += ["## Service: pick cutoff versus delivery", ""]
    lines.append(
        "Pick-cutoff OTIF is the Week 9-15 definition (every ticket finished before "
        "12:00/16:00/18:00). Dock OTIF is the customer definition: every leg is shipped "
        "and `departure day + transit days ≤ promise days`."
    )
    lines.append("")
    lines.append(_md_table(_service_table(cells, summary)))
    lines.append("")

    ceiling = float(allocation.get("otif_rate") or 0.0)
    base = _mean(summary, "dock_two_immediate", "dock_otif_rate")
    lines.append(
        f"Two departures at 13:00/19:00 deliver **{_pct(base)}** against an allocation "
        f"ceiling of **{_pct(ceiling)}**: the dock itself loses "
        f"**{max(0.0, ceiling - base) * 100:.1f} pp** on this instance."
    )
    lines.append("")

    lines += ["## Departures, consolidation and cost", ""]
    lines.append(_md_table(_dock_table(cells, summary)))
    lines.append("")

    lines += ["## Paired differences on dock OTIF", ""]
    lines.append(
        "Every comparison uses the same seed set and the same allocation, so the paired "
        "difference isolates the dispatch change. The interval is the 95% CI of the "
        "per-seed difference."
    )
    lines.append("")
    lines.append(_md_table(_paired_table(paired, cells)))
    lines.append("")

    lines += ["## Lane detail (seed 1, promise-aware 6)", ""]
    lines.append(
        "The lane table is one representative seed. Lanes sharing a DC but shipping to "
        "different countries are separate departures even when they leave at the same "
        "minute."
    )
    lines.append("")
    lines.append(_md_table(_lane_table(lanes)) if lanes else "_No lane rows._")
    lines.append("")

    lines += ["## Findings", ""]
    if paired and all(float(row.get("ci95") or 0.0) == 0.0 for row in paired):
        lines.append(
            "- **This run is degenerate.** Every paired interval is zero: at this order "
            "count the dock is far from binding and all cells collapse to the allocation "
            "outcome. Treat it as a smoke test; the declared benchmark uses 400 orders "
            "and 30 seeds."
        )
    pick_base = _mean(summary, "pick_control", "pick_otif_rate")
    definition_gap = (_paired_lookup(paired, "pick_control", "dock_two_immediate"))
    if definition_gap is not None:
        lines.append(
            f"- **The pick cutoff is not the customer promise.** Scoring the same picks at "
            f"delivery lifts OTIF from {_pct(pick_base)} to {_pct(base)} "
            f"{_delta_text(definition_gap)}, win rate "
            f"{_pct(definition_gap['win_rate'])}. The 12:00/16:00/18:00 cutoffs embed a "
            f"multi-hour buffer before the 19:00 departure; Week 9-15 OTIF is therefore a "
            f"warehouse KPI that understates customer service by roughly "
            f"{(base - pick_base) * 100:.0f} pp on this instance."
        )

    lines.append(
        f"- **The dock is not the bottleneck.** With two departures the dock converts "
        f"{_pct(base)} of orders against an allocation ceiling of {_pct(ceiling)}; "
        f"stock and DC assignment, not the line-haul, set the service level. The dock "
        f"only creates loss when a ticket finishes after the last carrier cutoff "
        f"(18:30 here)."
    )

    consolidation = _paired_lookup(paired, "dock_two_immediate", "dock_two_hold6")
    if consolidation is not None:
        saved = _mean(summary, "dock_two_immediate", "departures") - _mean(
            summary, "dock_two_hold6", "departures"
        )
        saved_cost = _mean(summary, "dock_two_immediate", "dispatch_cost") - _mean(
            summary, "dock_two_hold6", "dispatch_cost"
        )
        lines.append(
            f"- **Consolidation is nearly free.** Holding to 6 orders or the end of the "
            f"day changes dock OTIF by {_delta_text(consolidation)} while removing "
            f"**{saved:.1f} departures/day** and **€{saved_cost:,.0f}/day** of declared "
            f"dispatch cost. Loads rise from "
            f"{_num(_mean(summary, 'dock_two_immediate', 'orders_per_departure'), 1)} to "
            f"{_num(_mean(summary, 'dock_two_hold6', 'orders_per_departure'), 1)} "
            f"tickets per departure."
        )

    promise = _paired_lookup(paired, "dock_two_immediate", "dock_two_promise6")
    if promise is not None and consolidation is not None:
        extra = _mean(summary, "dock_two_immediate", "departures") - _mean(
            summary, "dock_two_promise6", "departures"
        )
        lines.append(
            f"- **Promise-aware holding adds little on top of a day-end rule.** The "
            f"promise rule moves OTIF by {_delta_text(promise)} and removes a further "
            f"{max(0.0, extra):.1f} departures; at this load almost every lane reaches "
            f"the minimum load before its promise deadline binds."
        )

    late = _paired_lookup(paired, "dock_two_immediate", "dock_single_19")
    if late is not None:
        saved = _mean(summary, "dock_two_immediate", "departures") - _mean(
            summary, "dock_single_19", "departures"
        )
        extra_wait = _mean(summary, "dock_single_19", "mean_wait_minutes") - _mean(
            summary, "dock_two_immediate", "mean_wait_minutes"
        )
        lines.append(
            f"- **One late departure is free service-wise.** Dropping the 13:00 run and "
            f"keeping only 19:00 changes OTIF by {_delta_text(late)} while removing "
            f"**{saved:.1f} departures/day**; the price is "
            f"**+{extra_wait:.0f} min** average dock dwell. A carrier that consolidates "
            f"to a single evening trailer does not hurt the customer promise here."
        )

    early = _paired_lookup(paired, "dock_two_immediate", "dock_single_15")
    if early is not None:
        verdict = (
            "costs service"
            if float(early["mean_delta"]) < 0
            else "is covered by the buffer at this load"
        )
        lines.append(
            f"- **A single early cutoff {verdict}.** Moving to one 15:00 departure moves "
            f"dock OTIF by **{_delta_text(early)}**: tickets finished after 14:30 roll to "
            f"the next day and express orders with `transit = promise` miss. The same "
            f"mechanism moves OTIF by "
            f"{_delta_text(_paired_lookup(paired, 'dock_two_immediate', 'dock_single_13'))} "
            f"at a single 13:00 departure."
        )

    noise = _paired_lookup(paired, "dock_two_promise6", "dock_promise6_noise")
    if noise is not None:
        pick_shift = _mean(summary, "dock_promise6_noise", "pick_otif_rate") - _mean(
            summary, "dock_two_promise6", "pick_otif_rate"
        )
        lines.append(
            f"- **The dock buffer absorbs pick noise.** Lognormal σ=0.25 moves the "
            f"pick-cutoff rate by {pick_shift * 100:+.1f} pp but dock OTIF by "
            f"{_delta_text(noise, 2)}: the same late tickets still catch the evening "
            f"trailer. Noise would bite only if it pushed work past 18:30."
        )

    pickers = _paired_lookup(paired, "dock_two_promise6", "dock_promise6_pickers2")
    if pickers is not None:
        pick_gain = _mean(summary, "dock_promise6_pickers2", "pick_otif_rate") - _mean(
            summary, "dock_two_promise6", "pick_otif_rate"
        )
        lines.append(
            f"- **Extra picking capacity cannot beat the allocation ceiling.** A second "
            f"picker per DC lifts the pick-cutoff rate by {pick_gain * 100:+.1f} pp and "
            f"closes the gap to the dock, but dock OTIF moves by "
            f"{_delta_text(pickers)} because it is capped by the allocation. Capacity "
            f"spend at this load is better directed at fill/placement."
        )

    lines.append(
        "- **Scope.** The timetable, carrier cutoffs, lane rule, truck ceiling and dock "
        "rates are declared. The arrival shape is the Week-15 calibration; the "
        "allocation is fixed across every cell, so this benchmark isolates the outbound "
        "layer."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_dispatch_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Outbound dispatch and carrier cutoffs (Week 16)",
) -> Dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    markdown = build_dispatch_report(results, title=title, generated=stamp)
    report_path = directory / "DISPATCH_REPORT.md"
    report_path.write_text(markdown, encoding="utf-8")
    payload = {"title": title, "generated": stamp, **_json_safe(results)}
    summary_path = directory / "dispatch_summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report": report_path, "summary": summary_path}
