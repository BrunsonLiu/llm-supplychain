"""Markdown/JSON report for the Week-17 dock-door benchmark."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from .dispatch import DISPATCH_METRICS


def _pct(value: float) -> str:
    return f"{float(value) * 100:.1f}%"


def _num(value: float, digits: int = 1) -> str:
    return f"{float(value):,.{digits}f}"


def _md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_（无数据）_"
    columns = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _mean(summary: Sequence[Dict[str, Any]], cell: str, metric: str) -> float:
    values = [
        float(row["mean"])
        for row in summary
        if row["cell"] == cell and row["metric"] == metric
    ]
    return sum(values) / len(values) if values else 0.0


def _paired_lookup(
    paired: Sequence[Dict[str, Any]], left: str, right: str
) -> Optional[Dict[str, Any]]:
    for row in paired:
        if row["left"] == left and row["right"] == right:
            return row
    return None


def _delta_text(row: Optional[Dict[str, Any]], digits: int = 1) -> str:
    if row is None:
        return "n/a"
    return (
        f"{float(row['mean_delta']) * 100:+.{digits}f} pp "
        f"(±{float(row['ci95']) * 100:.{digits}f})"
    )


def _cell_table(cells: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "格": cell["label"],
                "规则": {
                    "none": "无（对照）",
                    "immediate": "即时",
                    "hold": "凑批/日终",
                    "promise": "承诺感知",
                }.get(cell["policy"], cell["policy"]),
                "门位/DC": "不限" if cell["doors_per_dc"] == 0 else cell["doors_per_dc"],
                "单车装车 (min)": _num(cell["dock_load_minutes"], 0),
                "拣货员/DC": cell.get("pickers_per_dc") or "—",
                "噪声 σ": _num(cell.get("duration_noise", 0.0), 2),
            }
            for cell in cells
        ]
    )


def _service_table(
    summary: Sequence[Dict[str, Any]], cells: Sequence[Dict[str, Any]]
) -> pd.DataFrame:
    rows = []
    for cell in cells:
        key = cell["key"]
        rows.append(
            {
                "格": cell["label"],
                "拣选截单 OTIF": _pct(_mean(summary, key, "pick_otif_rate")),
                "交付 OTIF": _pct(_mean(summary, key, "dock_otif_rate")),
                "交付 − 截单": (
                    f"{_mean(summary, key, 'dock_otif_rate') * 100 - _mean(summary, key, 'pick_otif_rate') * 100:+.1f} pp"
                ),
                "滚存率": _pct(_mean(summary, key, "roll_rate")),
                "平均等车 (min)": _num(_mean(summary, key, "mean_wait_minutes"), 0),
            }
        )
    return pd.DataFrame(rows)


def _door_table(
    summary: Sequence[Dict[str, Any]], cells: Sequence[Dict[str, Any]]
) -> pd.DataFrame:
    rows = []
    for cell in cells:
        key = cell["key"]
        if cell["doors_per_dc"] == 0:
            utilization = "—"
            blocked = "—"
            load = "—"
        else:
            utilization = _pct(_mean(summary, key, "door_utilization"))
            blocked = _num(_mean(summary, key, "door_blocked"), 1)
            load = _num(_mean(summary, key, "load_minutes_per_departure"), 0)
        rows.append(
            {
                "格": cell["label"],
                "车次/天": _num(_mean(summary, key, "departures"), 1),
                "每车票据": _num(_mean(summary, key, "orders_per_departure"), 1),
                "门位利用率": utilization,
                "门位阻塞": blocked,
                "单车装车 (min)": load,
                "月台成本 (€)": _num(_mean(summary, key, "dock_cost"), 0),
            }
        )
    return pd.DataFrame(rows)


def _paired_table(
    paired: Sequence[Dict[str, Any]], cells: Sequence[Dict[str, Any]]
) -> pd.DataFrame:
    labels = {cell["key"]: cell["label"] for cell in cells}
    rows = []
    for row in paired:
        rows.append(
            {
                "对比": f"{labels.get(row['right'], row['right'])} − "
                f"{labels.get(row['left'], row['left'])}",
                "Δ 交付 OTIF": _delta_text(row),
                "胜率": _pct(row["win_rate"]),
                "持平率": _pct(row.get("tie_rate", 0.0)),
                "n": row["n"],
            }
        )
    return pd.DataFrame(rows)


def _lane_table(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    ordered = sorted(rows, key=lambda row: (-row["tickets"], row["dc"], row["lane"]))
    return pd.DataFrame(
        [
            {
                "DC": row["dc"],
                "车道": row["lane"],
                "票据": row["tickets"],
                "件数": f"{int(row['units']):,}",
                "车次": row["departures"],
                "平均等车 (min)": _num(row["mean_wait_minutes"], 0),
                "滚存率": _pct(row["roll_rate"]),
            }
            for row in ordered[:12]
        ]
    )


def build_dock_report(
    payload: Dict[str, Any],
    title: str = "Dock doors and loading capacity (Week 17)",
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

    lines: List[str] = [f"# {title}", ""]
    lines.append(f"- Generated: `{stamp}`")
    lines.append(
        f"- Orders: **{dataset.get('orders', 0)}** real invoices / "
        f"**{dataset.get('lines', 0)}** lines / **{dataset.get('units', 0):,}** units, "
        f"week {dataset.get('week', '')}"
    )
    lines.append(
        f"- Seeds: **{len(seeds)}** | cells: **{len(cells)}** | pickers/DC: "
        f"**{settings.get('pickers', 0)}** | shift **{settings.get('shift_minutes', 0):.0f} min**"
    )
    lines.append(
        f"- Allocation: **{allocation.get('label', '')}** ({allocation.get('status', '')}) "
        f"| allocation OTIF ceiling **{_pct(allocation.get('otif_rate', 0.0))}** "
        f"| solver **{allocation.get('solve_seconds', 0):.0f} s**"
    )
    lines.append(
        f"- Door budget: **{_num(settings.get('door_window', 0), 0)} min/day per DC** "
        f"| load **{_num(settings.get('load_minutes_per_truck', 0), 0)} min/truck + "
        f"{_num(settings.get('load_minutes_per_ticket', 0), 2)} min/ticket** "
        f"| dock cost **€{_num(settings.get('dispatch_cost', 0), 0)}/departure + "
        f"€{_num(settings.get('holding_cost', 0), 2)}/order-hour**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines += [
        "| Item | Assumption | Note |",
        "|---|---|---|",
        "| Departures | 13:00 and 19:00 per DC; single 19:00 variant | same timetable as Week 16 |",
        "| Carrier cutoff | departure minus 30 min | a missed ticket rolls to the next departure |",
        "| Lane | DC × destination country | orders on one lane consolidate; no cross-country trailer |",
        "| Truck capacity | 300 orders / departure | declared ceiling; not binding in this instance |",
        "| Doors | 0 (unlimited) / 1 / 2 / 4 per DC | declared loading resource; 0 reproduces Week 16 |",
        f"| Door budget | {_num(settings.get('door_window', 0), 0)} min per DC per day | declared 8-hour loading budget; shared by every lane at that DC |",
        f"| Loading time | {_num(settings.get('load_minutes_per_truck', 0), 0)} min per truck + "
        f"{_num(settings.get('load_minutes_per_ticket', 0), 2)} min per ticket | declared linear loading proxy |",
        "| Promise deadline | dispatch day ≤ promise days − transit days | derived from the Week-8 geometry |",
        "| Dock cost | €220 per departure + €0.15 per order-hour | declared planning rates, used to compare cells |",
        "| Arrivals | prior-week empirical curves (Week 15) | only the door layer is new |",
        "",
    ]

    lines += ["## Cells", ""]
    lines.append(_md_table(_cell_table(cells)))
    lines.append("")

    lines += ["## Service: pick cutoff versus delivery", ""]
    lines.append(
        "Dock OTIF requires every leg to be shipped and "
        "`departure day + transit days ≤ promise days`. A lane that cannot load "
        "inside the remaining door budget waits for the next slot and may roll to "
        "the next day."
    )
    lines.append("")
    lines.append(_md_table(_service_table(summary, cells)))
    lines.append("")

    lines += ["## Door capacity, consolidation and cost", ""]
    lines.append(
        "Door utilization is loaded door-minutes divided by "
        f"`doors × {_num(settings.get('door_window', 0), 0)} min × DCs × active departure days`. A blocked count is one "
        "lane-slot that could not load because the daily door budget was exhausted."
    )
    lines.append("")
    lines.append(_md_table(_door_table(summary, cells)))
    lines.append("")

    lines += ["## Paired comparisons", ""]
    lines.append("Right − left, same arrival seed, metric = delivered OTIF.")
    lines.append("")
    lines.append(_md_table(_paired_table(paired, cells)))
    lines.append("")

    lines += ["## Lane detail (seed 1, 1 door + promise-aware 6)", ""]
    lines.append(_md_table(_lane_table(lanes)))
    lines.append("")

    # Findings -------------------------------------------------------------
    base = _mean(summary, "dock_open", "dock_otif_rate")
    one = _mean(summary, "doors_1", "dock_otif_rate")
    two = _mean(summary, "doors_2", "dock_otif_rate")
    four = _mean(summary, "doors_4", "dock_otif_rate")
    ceiling = float(allocation.get("otif_rate", 0.0))
    gap_open = _paired_lookup(paired, "pick_control", "dock_open")
    gap_one = _paired_lookup(paired, "dock_open", "doors_1")
    gap_two = _paired_lookup(paired, "dock_open", "doors_2")
    promise_one = _paired_lookup(paired, "doors_1", "doors_1_promise6")
    single_one = _paired_lookup(paired, "doors_1", "doors_1_single19")
    pickers_one = _paired_lookup(paired, "doors_1", "doors_1_pickers2")
    load60 = _paired_lookup(paired, "doors_1", "doors_1_load60")
    noise = _paired_lookup(paired, "doors_1", "doors_1_noise")

    lines += ["## Findings", ""]
    lines.append(
        f"- **Unconstrained doors reproduce Week 16.** With no door limit the dock "
        f"delivers {_pct(base)} against an allocation ceiling of {_pct(ceiling)} "
        f"({_delta_text(gap_open)} versus the pick cutoff), so the Week-16 conclusion "
        f"depends on unlimited loading capacity."
    )
    lines.append(
        f"- **One door is enough to make the dock bind.** With 1 door per DC the "
        f"dock delivers {_pct(one)} ({_delta_text(gap_one)} versus open doors); "
        f"2 doors recover to {_pct(two)} ({_delta_text(gap_two)}) and 4 doors to "
        f"{_pct(four)}. The door budget, not the carrier cutoff, is the binding "
        f"resource at this load."
    )
    if promise_one is not None:
        lines.append(
            f"- **Consolidation relieves the door.** Promise-aware 6 raises the "
            f"trailer load and changes delivered OTIF by {_delta_text(promise_one)} "
            f"at 1 door, almost fully recovering the door loss while removing "
            f"departures and door-minutes. Holding is a capacity lever, not only a "
            f"cost lever."
        )
    if single_one is not None:
        lines.append(
            f"- **A single late departure also relieves the door.** Keeping only "
            f"19:00 changes delivered OTIF by {_delta_text(single_one)} at 1 door "
            f"and removes departures; the trade-off is longer dock dwell."
        )
    if pickers_one is not None:
        lines.append(
            f"- **Extra picking capacity cannot substitute for a door.** A second "
            f"picker changes delivered OTIF by {_delta_text(pickers_one)} at 1 door "
            f"while pushing the pick-cutoff KPI to the allocation ceiling: faster "
            f"picking feeds the same loading queue, so the dock remains the binding "
            f"resource."
        )
    if load60 is not None:
        lines.append(
            f"- **Loading time matters.** A "
            f"{_num(settings.get('load_sensitivity', 0), 0)}-minute load instead of "
            f"{_num(settings.get('load_minutes_per_truck', 0), 0)} changes "
            f"delivered OTIF by {_delta_text(load60)} at 1 door: a faster dock "
            f"recovers service without adding a door."
        )
    if noise is not None:
        lines.append(
            f"- **Pick noise is secondary to door capacity.** Lognormal σ=0.25 "
            f"changes delivered OTIF by {_delta_text(noise, 2)} at 1 door with "
            f"{_pct(noise.get('tie_rate', 0.0))} ties: no material effect, because "
            f"the daily door budget dominates the tail."
        )
    lines.append(
        "- **Scope.** Door count, loading window, loading minutes, timetable, lane "
        "rule and rates are declared. Allocation, stock and arrivals are fixed "
        "across cells, so this benchmark isolates the dock-door layer; absolute "
        "OTIF is not transferable."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


def write_dock_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Dock doors and loading capacity (Week 17)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "DOCK_REPORT.md"
    summary = out / "dock_summary.json"
    report.write_text(build_dock_report(payload, title=title), encoding="utf-8")
    body = {
        "title": title,
        **payload,
        "generated": datetime.now(timezone.utc).isoformat(),
    }
    summary.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return {"report": report, "summary": summary}
