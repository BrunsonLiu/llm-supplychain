"""Markdown + JSON report for the Week-7 wave release scheduling benchmark."""
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
                cells.append("—" if not math.isfinite(value) else f"{value:,.2f}")
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                cells.append("—")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.1%}"


def _num(value: Any, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"


def _scenario_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "方案": row["scenario"],
                "状态": row["status"],
                "波次": row["waves"],
                "单均工时": _num(row["labor_per_order"], 2),
                "准时率": _pct(row["on_time_rate"]),
                "迟到单": row["tardy_orders"],
                "迟到订单分钟": _num(row["total_tardiness"], 0),
                "最大迟到 (min)": _num(row["max_tardiness"], 0),
                "Makespan": _num(row["makespan"], 0),
                "加班 (min)": _num(row["overtime"], 0),
                "拣货员利用率": _pct(row["picker_utilization"]),
                "求解 (s)": _num(row["solve_seconds"], 2),
            }
            for row in rows
        ]
    )


def _promise_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "承诺层": row["tier"],
                "截单": row["cutoff"],
                "订单": row["orders"],
                "准时": row["on_time"],
                "准时率": _pct(row["on_time_rate"]),
                "迟到": row["tardy"],
                "迟到分钟": _num(row["total_tardiness"], 0),
                "最大迟到 (min)": _num(row["max_tardiness"], 0),
            }
            for row in rows
        ]
    )


def _sensitivity_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "拣货员": row["pickers"],
                "EDF 准时率": _pct(row["edf_on_time_rate"]),
                "EDF 迟到分钟": _num(row["edf_tardiness"], 0),
                "EDF makespan": _num(row["edf_makespan"], 0),
                "CP-SAT 状态": row["mip_status"],
                "CP-SAT 准时率": _pct(row["mip_on_time_rate"]),
                "CP-SAT 迟到分钟": _num(row["mip_tardiness"], 0),
                "CP-SAT makespan": _num(row["mip_makespan"], 0),
                "求解 (s)": _num(row["mip_seconds"], 2),
            }
            for row in rows
        ]
    )


def _detail_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "波次": row["wave"],
                "拣货员": row["picker"],
                "开始": row["start"],
                "结束": row["end"],
                "工时 (min)": _num(row["minutes"], 1),
                "订单": row["orders"],
                "最紧截单": row["deadline"],
                "迟到单": row["late_orders"],
                "最大迟到 (min)": _num(row["max_late"], 0),
            }
            for row in rows
        ]
    )


def build_schedule_report(
    results: Dict[str, Any],
    title: str = "Wave release scheduling benchmark",
    generated: str = "",
) -> str:
    dataset = results["dataset"]
    plan = results["plan"]
    settings = results["schedule"]
    summary = results["summary"]
    sensitivity = results.get("sensitivity", [])
    promises = results.get("promises", {})
    detail = results.get("detail", [])

    rows = {row["key"]: row for row in summary}
    full = rows.get("full_edf")
    tiered = rows.get("tiered_edf")
    tiered_mip = rows.get("tiered_cpsat")
    single = rows.get("single_edf")
    best = max(
        summary,
        key=lambda row: (row["on_time_rate"], -row["total_tardiness"], -row["makespan"]),
    )

    lines = [
        f"# {title}",
        "",
        f"- Generated: `{generated}`",
        (
            f"- Orders: **{_num(dataset['orders'], 0)}** real invoices / "
            f"**{_num(dataset['lines'], 0)}** lines / "
            f"**{_num(dataset['units'], 0)}** units, week {dataset['week']}"
        ),
        (
            f"- Batching basis: Week-6 partition, wave cap "
            f"**{dataset['max_orders']} orders / {dataset['max_lines']} lines**; "
            f"labor minutes include travel, picking and per-wave setup."
        ),
        (
            f"- Promise mix: express **{_pct(plan['mix']['express'])}** (cutoff "
            f"{plan['cutoffs']['express']} min), standard "
            f"**{_pct(plan['mix']['standard'])}** ({plan['cutoffs']['standard']} min), "
            f"economy **{_pct(plan['mix']['economy'])}** ({plan['cutoffs']['economy']} min), "
            f"assigned by seeded shuffle."
        ),
        (
            f"- Shift: start {settings['start_hour']:02d}:00, length "
            f"**{_num(settings['shift_minutes'], 0)} min**, "
            f"**{settings['pickers']} pickers**; overtime is allowed and reported, "
            f"not constrained."
        ),
        f"- Best scenario in this run: **{best['scenario']}** (on-time {_pct(best['on_time_rate'])})",
        "",
        "## Assumptions",
        "",
        (
            "| Item | Assumption | Note |\n"
            "|---|---|---|\n"
            "| Promise tier mix | 20% / 50% / 30% | No customer-promise data in Online Retail II; tiers are assigned by seeded shuffle. |\n"
            "| Cutoffs | 12:00 / 16:00 / 18:00 | Minutes 240 / 480 / 600 after the 08:00 shift start. |\n"
            "| Pickers | 2 identical workers | No skills, zones, breaks, or absenteeism. |\n"
            "| Shift | 08:00–18:00 (600 min) | Waves may finish after 18:00; overtime is a reported metric, not a hard constraint. |\n"
            "| Scheduling objective | tardiness × 100 + makespan × 1 | A policy weight: one late order-minute is worth 100 minutes of shift length. |\n"
            f"| Wave labor | Week-6 model | Travel at {_num(dataset['travel_m_per_minute'], 1)} m/min, "
            f"{_num(dataset['pick_min_per_line'], 2)} min/line + "
            f"{_num(dataset['pick_min_per_unit'], 2)} min/unit, "
            f"{_num(dataset['setup_min_per_wave'], 1)} min setup/wave. |"
        ),
        "",
        "## Methods",
        "",
        "- **Week-6 batching**: the CP-SAT set-partitioning partition (36 waves in the main run) is reused unchanged, so travel and picking labor match the Week-6 report.",
        "- **Tier-aware batching**: the same Clarke-Wright savings merge, but pairs are only scored inside a promise tier; orders with different cutoffs are never merged.",
        "- **EDF scheduling**: waves are released earliest-deadline-first onto identical pickers, where a wave's deadline is the earliest cutoff among its orders.",
        "- **CP-SAT scheduling**: optional intervals on parallel pickers, no overlap per picker, and an objective of per-order tardiness minutes plus makespan. The EDF plan is injected as an integer-consistent hint, so the solver starts from EDF and returns the best plan it finds; when it cannot improve, differences are rounding-level.",
        "",
        "## Scenario comparison",
        "",
        _md_table(_scenario_table(summary)),
        "",
        "On-time is counted per order against its own cutoff; a wave that finishes early for an express order but late for an economy order splits the credit accordingly. Tardiness is in order-minutes.",
        "",
    ]

    for key, label in (("full_edf", "Full batching + EDF"), ("tiered_edf", "Tier-aware batching + EDF")):
        if key in promises:
            lines.extend(
                [
                    f"### Promise tiers — {label}",
                    "",
                    _md_table(_promise_table(promises[key])),
                    "",
                ]
            )

    if sensitivity:
        lines.extend(
            [
                "## Picker-count sensitivity",
                "",
                "Same tier-aware partition and cutoffs, re-scheduled with 1/2/3 pickers. This isolates scheduling freedom from batching: with enough pickers both rules meet every cutoff, while a single picker forces a choice.",
                "",
                _md_table(_sensitivity_table(sensitivity)),
                "",
            ]
        )

    if detail:
        lines.extend(
            [
                "## Schedule detail — tier-aware batching + CP-SAT",
                "",
                _md_table(_detail_table(detail)),
                "",
            ]
        )

    lines.extend(["## Interpretation", ""])
    if single and full and tiered:
        same_waves = tiered["waves"] == full["waves"]
        lines.append(
            f"1. **Batching saves labor, but couples deadlines.** Pick-by-order needs "
            f"{_num(single['labor_per_order'], 2)} min/order; full batching drops it to "
            f"{_num(full['labor_per_order'], 2)} min/order. The same merge, however, puts "
            f"express and economy orders in one wave, so the wave finishes when its slowest "
            f"line is picked and the express promise inherits the whole wave."
        )
        lines.append(
            f"2. **Full batching + EDF misses {full['tardy_orders']} orders** "
            f"({_pct(1.0 - full['on_time_rate'])}), with "
            f"{_num(full['total_tardiness'], 0)} order-minutes of tardiness. "
            f"Tier-aware batching keeps the wave count {'unchanged' if same_waves else 'close'} "
            f"({tiered['waves']} vs {full['waves']}) and raises on-time to "
            f"{_pct(tiered['on_time_rate'])} at {_num(tiered['labor_per_order'], 2)} min/order "
            f"— the deadline is protected by not merging across cutoffs, not by adding pickers."
        )
    if tiered and tiered_mip:
        if tiered_mip["total_tardiness"] <= 1e-6 and tiered["total_tardiness"] <= 1e-6:
            lines.append(
                f"3. **EDF already meets every cutoff at 2 pickers**, so CP-SAT mainly "
                f"reshuffles the same work: makespan "
                f"{_num(tiered['makespan'], 0)} → {_num(tiered_mip['makespan'], 0)} min, "
                f"status `{tiered_mip['status']}`. Scheduling freedom has little value when "
                f"capacity is ample."
            )
        else:
            lines.append(
                f"3. **CP-SAT improves the service plan over EDF**: tardiness "
                f"{_num(tiered['total_tardiness'], 0)} → {_num(tiered_mip['total_tardiness'], 0)} "
                f"order-minutes, makespan {_num(tiered['makespan'], 0)} → "
                f"{_num(tiered_mip['makespan'], 0)} min."
            )
    if sensitivity:
        tight = min(sensitivity, key=lambda row: row["pickers"])
        lines.append(
            f"4. **Scheduling matters when pickers are scarce.** With "
            f"{tight['pickers']} picker{'s' if tight['pickers'] > 1 else ''}, EDF leaves "
            f"{_num(tight['edf_tardiness'], 0)} order-minutes late; CP-SAT returns "
            f"{_num(tight['mip_tardiness'], 0)}. With enough capacity the gap closes, "
            f"which is the honest boundary of the optimisation: fix the batching policy "
            f"first, then schedule."
        )
    lines.append(
        "5. **The result is a policy statement, not a universal rule.** The on-time gain "
        "comes from refusing to merge across cutoffs. If the promise mix or cutoffs are "
        "wrong, the partition is wrong; a production system must feed real promise and "
        "cutoff data into this layer instead of a fixed 20/50/30 mix."
    )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Promise tiers, cutoffs, picker count, shift length and the objective weights are declared assumptions; the dataset contains no customer promises, picker roster, or labor rules.",
            "- The order pool is one static trading week. Orders do not arrive during the shift, and there is no re-optimisation when a wave finishes early or a picker is pulled away.",
            "- Pickers are identical and never blocked: no zones, skills, breaks, congestion, replenishment delays, or handover time between waves.",
            "- Batching is fixed before scheduling. The benchmark does not jointly optimise batching and release times, and the tier-aware partition only forbids cross-tier merges; it does not search for the best deadline-aware partition.",
            "- CP-SAT runs with a wall-clock budget and a fixed weight ratio. `OPTIMAL` is not guaranteed on a larger order pool, and the weights are a policy choice rather than a tuned production setting.",
            "- The reported CP-SAT status is `FEASIBLE`, not `OPTIMAL`. Its bound is weak because the objective mixes order-minutes with makespan; `FEASIBLE` only means the EDF-seeded incumbent was not improved within the budget, not that a better schedule does not exist.",
            "- Overtime is reported, not constrained: the model can finish after 18:00, so the makespan and overtime columns are consequences of the plan rather than a legal shift limit.",
            "",
        ]
    )
    return "\n".join(lines)


def write_schedule_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Wave release scheduling benchmark",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    report_path = out / "WAVE_SCHEDULE_REPORT.md"
    summary_path = out / "wave_schedule_summary.json"
    report_path.write_text(
        build_schedule_report(results, title=title, generated=generated),
        encoding="utf-8",
    )
    payload = {"generated": generated, "title": title, **results}
    summary_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": report_path, "summary": summary_path}
