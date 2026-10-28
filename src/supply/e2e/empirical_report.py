"""Markdown + JSON report for the Week-15 empirical arrival-curve benchmark."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct

from .robustness import SUMMARY_METRICS


def _label_map(cells: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {row["key"]: row["label"] for row in cells}


def _curve_table(rows: Sequence[Dict[str, Any]], hours: Sequence[int]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Week": row["week"],
                "Role": row.get("role")
                or row.get("note")
                or ("经验曲线" if row.get("used") else "未使用"),
                "Weekday lines": f"{row['lines_weekday']:,}",
                "In window": f"{row['lines_used']:,}",
                "Coverage": _pct(row["coverage"]),
                "Weekend share": _pct(row["weekend_share"]),
                **{f"{hour:02d}": _pct(row.get(str(hour))) for hour in hours},
                "Peak": f"{row['peak_hour']:02d}:00" if row.get("peak_hour") else "—",
            }
            for row in rows
        ]
    )


def _cell_table(cells: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Cell": row["label"],
                "Arrival": {
                    "uniform": "均匀（声明）",
                    "spike": "尖峰（声明）",
                    "mean": "前几周平均经验曲线",
                    "empirical": "逐周经验曲线",
                }.get(row["arrival"], row["arrival"]),
                "Policy": row["policy"],
                "Pick noise σ": _num(row.get("duration_noise"), 2),
                "Pickers / DC": row.get("pickers_per_dc") or "—",
            }
            for row in cells
        ]
    )


def _timing_table(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Cell": row["label"],
                "Mid-shift orders": f"{row['orders']:,}",
                "Mean window fraction": _pct(row["mean_fraction"]),
                "Median window fraction": _pct(row["median_fraction"]),
                "Arrive after half": _pct(row["share_after_half"]),
                "Arrive after 3/4": _pct(row["share_after_three_quarters"]),
                "Mean shift minute": _num(row["mean_minute"], 0),
            }
            for row in rows
        ]
    )


def _distribution_table(
    rows: Sequence[Dict[str, Any]], metric: str = "e2e_otif_rate"
) -> pd.DataFrame:
    picked = [row for row in rows if row["metric"] == metric]
    return pd.DataFrame(
        [
            {
                "Cell": row["cell_label"],
                "Mean": _pct(row["mean"]),
                "95% CI": f"±{_pct(row['ci95'])}",
                "P10": _pct(row["p10"]),
                "P50": _pct(row["p50"]),
                "P90": _pct(row["p90"]),
                "Worst 10% mean": _pct(row["tail10"]),
                "n": row["n"],
            }
            for row in picked
        ]
    )


def _execution_table(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    wanted = [
        ("pick_on_time_rate", "Picked on time", True),
        ("pick_tardiness", "Tardy minutes", False),
        ("pick_makespan", "Makespan (min)", False),
        ("labor_per_ticket", "Labor / ticket (min)", False),
    ]
    by_cell: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for row in rows:
        by_cell.setdefault(row["cell_label"], {})[row["metric"]] = row
    table = []
    for cell_label, metrics in by_cell.items():
        entry: Dict[str, Any] = {"Cell": cell_label}
        for metric, label, pct in wanted:
            row = metrics.get(metric)
            if row is None:
                entry[label] = "—"
            elif pct:
                entry[label] = _pct(row["mean"])
            else:
                entry[label] = _num(row["mean"], 0)
        table.append(entry)
    return pd.DataFrame(table)


def _paired_table(
    rows: Sequence[Dict[str, Any]], labels: Dict[str, str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Comparison": (
                    f"{labels.get(row['right'], row['right'])} − "
                    f"{labels.get(row['left'], row['left'])}"
                ),
                "Δ OTIF": f"{row['mean_delta']:+.1%}",
                "95% CI": f"±{row['ci95']:.1%}",
                "Win": _pct(row["win_rate"]),
                "Loss": _pct(row["loss_rate"]),
                "Tie": _pct(row["tie_rate"]),
                "n": row["n"],
            }
            for row in rows
            if row["metric"] == "e2e_otif_rate"
        ]
    )


def _over_shift_table(
    rows: Sequence[Dict[str, Any]], labels: Dict[str, str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Cell": labels.get(
                    row.get("cell") or row.get("cell_label") or row.get("scenario"),
                    row.get("cell") or row.get("cell_label") or row.get("scenario"),
                ),
                "Over-shift rate": _pct(row["over_shift_rate"]),
                "Mean makespan": _num(row["mean_makespan"], 0),
                "P90 makespan": _num(row["p90_makespan"], 0),
                "n": row["n"],
            }
            for row in rows
        ]
    )


def _lookup(
    rows: Sequence[Dict[str, Any]], cell: str, metric: str
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["cell"] == cell and row["metric"] == metric:
            return row
    return None


def _paired_lookup(
    rows: Sequence[Dict[str, Any]], left: str, right: str
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["left"] == left and row["right"] == right:
            return row
    return None


def _delta_text(row: Optional[Dict[str, Any]], digits: int = 1) -> str:
    if row is None:
        return "n/a"
    return f"{row['mean_delta']:+.{digits}%} ±{row['ci95']:.{digits}%}"


def _interpretation(payload: Dict[str, Any]) -> List[str]:
    summary = payload.get("summary", [])
    paired = payload.get("paired", [])
    arrivals = payload.get("arrivals", {})
    diag = arrivals.get("diagnostics", {})
    settings = payload.get("settings", {})
    pickers = int(settings.get("pickers", 1))
    lines: List[str] = []

    peak = diag.get("target_peak_hour")
    peak_share = diag.get("target_peak_share")
    after_half = diag.get("target_share_after_half")
    l1_uniform = diag.get("uniform_l1_mean")
    l1_holdout = diag.get("holdout_l1")
    percentile = diag.get("holdout_percentile")
    if peak is not None:
        closer = 1.0 - float(percentile or 0.0)
        lines.append(
            f"- **The observed day is back-loaded.** The target week peaks at "
            f"{int(peak):02d}:00 with {_pct(peak_share)} of in-window lines in that "
            f"hour and {_pct(after_half)} after the halfway point; the prior-week "
            f"curves sit {_num(l1_uniform, 3)} (total variation) away from uniform. "
            f"The target curve is a holdout: its distance to the prior mean is "
            f"{_num(l1_holdout, 3)}, closer than {_pct(closer)} of prior-week pairs, "
            f"so it is reported but never used."
        )

    uniform = _lookup(summary, "uniform_edf", "e2e_otif_rate")
    empirical = _lookup(summary, "empirical_week_edf", "e2e_otif_rate")
    spike = _lookup(summary, "spike_edf", "e2e_otif_rate")
    d_uniform = _paired_lookup(paired, "uniform_edf", "empirical_week_edf")
    if d_uniform is not None and uniform is not None and empirical is not None:
        delta = d_uniform["mean_delta"]
        ci = d_uniform["ci95"]
        if delta < -0.005 and abs(delta) > ci:
            verdict = (
                "the declared uniform window is optimistic: the observed curve "
                "delivers fewer end-to-end on-time orders"
            )
        elif delta > 0.005 and abs(delta) > ci:
            verdict = (
                "the declared uniform window is conservative: the observed curve "
                "delivers more end-to-end on-time orders"
            )
        else:
            verdict = (
                "the uniform declaration is not materially biased here; the gap is "
                "inside the paired interval"
            )
        lines.append(
            f"- **Uniform vs empirical.** End-to-end OTIF moves from "
            f"{_pct(uniform['mean'])} (uniform) to {_pct(empirical['mean'])} "
            f"(week curves), {_delta_text(d_uniform)} with a "
            f"{_pct(d_uniform['win_rate'])} win rate, so {verdict}."
        )

    d_spike = _paired_lookup(paired, "spike_edf", "empirical_week_edf")
    if d_spike is not None and spike is not None:
        delta = d_spike["mean_delta"]
        ci = d_spike["ci95"]
        if delta < -0.005 and abs(delta) > ci:
            verdict = (
                "the declared spike still understates how late the real day runs"
            )
        elif delta > 0.005 and abs(delta) > ci:
            verdict = (
                "the declared spike is more pessimistic than the observed curve"
            )
        else:
            verdict = "the declared spike is a reasonable proxy for the observed curve"
        lines.append(
            f"- **Spike vs empirical.** The spike cell scores {_pct(spike['mean'])}; "
            f"the week curves add {_delta_text(d_spike)} (win rate "
            f"{_pct(d_spike['win_rate'])}), so {verdict}."
        )

    d_week = _paired_lookup(paired, "empirical_mean_edf", "empirical_week_edf")
    if d_week is not None:
        delta = d_week["mean_delta"]
        ci = d_week["ci95"]
        if delta < -0.005 and abs(delta) > ci:
            verdict = (
                "week-to-week shape noise is itself a risk source; planning on the "
                "average curve would overstate service"
            )
        elif delta > 0.005 and abs(delta) > ci:
            verdict = "the average curve is pessimistic relative to the weekly draws"
        else:
            verdict = (
                "the average curve summarises the weekly draws without material bias"
            )
        lines.append(
            f"- **Average curve vs weekly draws.** Using one mean curve gives "
            f"{_delta_text(d_week)} against resampling a prior week per seed "
            f"(win rate {_pct(d_week['win_rate'])}); {verdict}."
        )

    emp_savings = _paired_lookup(paired, "empirical_week_edf", "empirical_week_savings")
    spike_savings = _paired_lookup(paired, "spike_edf", "spike_savings")
    if emp_savings is not None and spike_savings is not None:
        emp_delta = emp_savings["mean_delta"]
        spike_delta = spike_savings["mean_delta"]
        if emp_delta > 0.005 and emp_delta > emp_savings["ci95"]:
            verdict = (
                "the re-batch gain survives calibration, so it is not a spike artefact"
            )
        elif (
            spike_delta > 0.005
            and spike_delta > spike_savings["ci95"]
            and (emp_delta <= 0.005 or emp_delta <= emp_savings["ci95"])
        ):
            verdict = (
                "the Week-10 re-batch finding was tied to the declared spike; under "
                "the observed curve it is not significant"
            )
        else:
            verdict = (
                "neither arrival family shows a significant re-batch gain at this load"
            )
        lines.append(
            f"- **Release policy under each arrival family.** Savings re-batching adds "
            f"{_delta_text(emp_savings)} under the week curves and "
            f"{_delta_text(spike_savings)} under the declared spike; {verdict}."
        )

    noise = _paired_lookup(paired, "empirical_week_edf", "empirical_week_noise")
    if noise is not None:
        delta = noise["mean_delta"]
        ci = noise["ci95"]
        if abs(delta) <= max(ci, 0.005):
            tail = (
                "OTIF is unchanged inside the paired interval at this load, so "
                "execution risk is not yet visible above the allocation outcome"
            )
        else:
            tail = (
                "the arrival calibration does not remove execution risk"
            )
        lines.append(
            f"- **Congestion noise stacks on the arrival shape.** Adding σ="
            f"{_num(settings.get('noise_sigma'), 2)} pick-duration noise moves OTIF by "
            f"{_delta_text(noise)} on the same curves; {tail}."
        )

    extra = _paired_lookup(paired, "empirical_week_edf", "empirical_week_two_pickers")
    if extra is not None:
        base = _lookup(summary, "empirical_week_edf", "e2e_otif_rate")
        target = _lookup(summary, "empirical_week_two_pickers", "e2e_otif_rate")
        delta = extra["mean_delta"]
        ci = extra["ci95"]
        if abs(delta) <= max(ci, 0.005):
            heading = "Picking capacity is not the binding constraint here"
            tail = (
                "a second picker leaves OTIF unchanged at this load, so the chain is "
                "allocation-bound before picking capacity binds"
            )
        else:
            heading = "Capacity still dominates"
            tail = (
                f"with {pickers} picker(s) per DC the chain is capacity-bound "
                f"regardless of the arrival shape"
            )
        lines.append(
            f"- **{heading}.** A second picker per DC moves OTIF from "
            f"{_pct(base['mean'] if base else None)} to "
            f"{_pct(target['mean'] if target else None)} "
            f"({_delta_text(extra)}, win rate {_pct(extra['win_rate'])}); {tail}."
        )

    if paired and all(float(row.get("ci95") or 0.0) == 0.0 for row in paired):
        lines.append(
            "- **The replays are degenerate at this load.** Every paired interval is "
            "zero, so each arrival family produces the same outcome: the pick layer "
            "is not binding and OTIF is set by the allocation. Increase orders or "
            "remove pickers to separate the arrival families."
        )

    coverage = payload.get("cutoff_coverage", {})
    if coverage:
        share_noon = coverage.get("240")
        share_four = coverage.get("480")
        lines.append(
            f"- **The observed clock stresses the promise design.** Only "
            f"{_pct(share_noon)} of target-week weekday lines are invoiced before "
            f"12:00 and {_pct(share_four)} before 16:00. The 12:00 express cutoff is "
            f"a declared policy, not a target the observed timing can meet; invoice "
            f"creation time is also not a DC receipt scan, so this is a design "
            f"warning rather than a measured service level."
        )

    lines.append(
        "- **Scope.** Only the intraday shape is calibrated. Promise windows, the "
        "70/50/40 on-site share, pick cutoffs, pick-duration noise, stock, layout and "
        "the allocation are unchanged from Weeks 9-10, so the comparison isolates "
        "arrival timing."
    )
    return lines


def build_empirical_report(
    payload: Dict[str, Any],
    title: str = "Empirical intraday arrivals (Week 15)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    arrivals = payload.get("arrivals", {})
    diag = arrivals.get("diagnostics", {})
    cells = payload.get("cells", [])
    seeds = payload.get("seeds", [])
    hours = list(range(arrivals.get("start_hour", 8), arrivals.get("end_hour", 18)))

    lines: List[str] = [f"# {title}", ""]
    lines.append(f"- Generated: `{stamp}`")
    lines.append(
        f"- Orders: **{dataset.get('orders', 0)}** real invoices / "
        f"**{dataset.get('lines', 0)}** lines / **{dataset.get('units', 0):,}** units, "
        f"week {dataset.get('week', '')}"
    )
    lines.append(
        f"- Arrival window: **Mon–Fri {hours[0]:02d}:00–{hours[-1] + 1:02d}:00** from "
        f"Online Retail II `InvoiceDate` | prior weeks "
        f"**{arrivals.get('lookback_weeks', 0)}** | target week is a **holdout**"
    )
    lines.append(
        f"- Seeds: **{len(seeds)}** | cells: **{len(cells)}** | "
        f"pickers/DC: **{settings.get('pickers', 1)}** | shift "
        f"**{_num(settings.get('shift_minutes'), 0)} min** | wave cap "
        f"**{dataset.get('max_orders', 0)} orders / {dataset.get('max_lines', 0)} lines**"
    )
    lines.append(
        f"- Allocation: **{payload.get('allocation', {}).get('label', '')}** "
        f"({payload.get('allocation', {}).get('status', '')}) | solver "
        f"**{_num(settings.get('milp_time'), 0)} s**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines.append(
        "| Item | Assumption | Note |"
    )
    lines.append("|---|---|---|")
    lines.append(
        "| Arrival shape | prior-week hourly shares of invoice lines | Mon–Fri, inside the "
        "business window; shapes are observed, the clock is invoice creation |"
    )
    lines.append(
        "| On-site share | 70% / 50% / 40% for express / standard / economy | declared, "
        "unchanged from Weeks 8-14 |"
    )
    lines.append(
        "| Tier windows | 120 / 360 / 480 min | declared; the curve is rescaled into each "
        "window |"
    )
    lines.append(
        "| Pick cutoffs | 12:00 / 16:00 / 18:00 | declared mapping from the 2/3/5-day promise |"
    )
    lines.append(
        "| Congestion | lognormal multiplier σ declared | no pick-duration data exists in "
        "the public dataset |"
    )
    lines.append(
        "| Allocation | Week-9 capacity-aware MILP, time-limited | stock, slots, layout and "
        "promises are fixed across cells |"
    )
    lines.append("")

    lines += ["## Observed intraday curve", ""]
    lines.append(
        "Shares are the fraction of a week's in-window invoice lines per clock hour. "
        "Weekends are excluded from the shape estimate; the excluded share is reported."
    )
    lines.append("")
    lines.append(_md_table(_curve_table(arrivals.get("rows", []), hours)))
    lines.append("")
    lines.append(
        f"Target-week coverage of weekday lines inside the window: "
        f"**{_pct(diag.get('target_coverage'))}**; weekend share of its lines: "
        f"**{_pct(diag.get('target_weekend_share'))}**. "
        f"Mean total-variation distance to uniform: "
        f"**{_num(diag.get('uniform_l1_mean'), 3)}**; "
        f"mean pairwise distance among prior weeks: "
        f"**{_num(diag.get('pairwise_l1_mean'), 3)}** "
        f"(max {_num(diag.get('pairwise_l1_max'), 3)})."
    )
    lines.append("")

    lines += ["## Benchmark cells", ""]
    lines.append(_md_table(_cell_table(cells)))
    lines.append("")

    lines += ["## Where mid-shift orders land", ""]
    lines.append(
        "Each mid-shift order draws a minute inside its tier window. The table "
        "averages that relative position across seeds and orders."
    )
    lines.append("")
    lines.append(_md_table(_timing_table(payload.get("timing", []))))
    lines.append("")

    lines += ["## End-to-end OTIF distribution", ""]
    lines.append(
        "Every cell is replayed on the same seeds with the same allocation; only the "
        "arrival draw, release policy, noise or picker count changes."
    )
    lines.append("")
    lines.append(_md_table(_distribution_table(payload.get("summary", []))))
    lines.append("")

    lines += ["## Paired differences", ""]
    lines.append(
        "Differences are `right − left` on shared seeds within each cell pair; the "
        "interval is the normal approximation over seeds."
    )
    lines.append("")
    lines.append(_md_table(_paired_table(payload.get("paired", []), _label_map(cells))))
    lines.append("")

    lines += ["## Execution risk", ""]
    lines.append(
        f"Shift length {_num(settings.get('shift_minutes'), 0)} min; "
        f"{settings.get('pickers', 1)} picker(s) per DC."
    )
    lines.append("")
    lines.append(_md_table(_execution_table(payload.get("summary", []))))
    lines.append("")
    lines.append(_md_table(_over_shift_table(payload.get("over_shift", []), _label_map(cells))))
    lines.append("")

    lines += ["## Interpretation", ""]
    lines.extend(_interpretation(payload))
    lines.append("")

    lines += ["## Limitations", ""]
    lines.append(
        "- `InvoiceDate` is the retailer's invoice creation timestamp, not a warehouse "
        "receipt scan; the curve is a public proxy for intraday demand timing."
    )
    lines.append(
        "- The shape is estimated on 6 prior weeks with Mon–Fri filtering and a "
        "08:00–18:00 window; the 2–5% of lines outside the window and the weekend "
        "lines are excluded from the shape, not from the demand."
    )
    lines.append(
        "- Only the arrival shape is calibrated. Pick minutes, congestion σ, stock, "
        "slots, layout, promises and the allocation remain the Week-9/10 declarations."
    )
    lines.append(
        "- The curve is rescaled into each declared tier window, so a late-day peak "
        "shifts arrivals later inside a short express window rather than making them "
        "infeasible; absolute timing is not a clock replay."
    )
    lines.append(
        "- One target week, one warehouse layout, one labour model and one allocation; "
        "differences are conditional on those choices and absolute OTIF is not "
        "transferable."
    )
    lines.append(
        "- Week curves are resampled by seed index, so the empirical cell mixes shape "
        "noise with seed noise; paired intervals compare cells on the same seeds but "
        "not on identical arrival times."
    )
    lines.append("")
    return "\n".join(lines)


def write_empirical_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Empirical intraday arrivals (Week 15)",
) -> Dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    markdown = build_empirical_report(results, title=title, generated=stamp)
    report_path = directory / "EMPIRICAL_ARRIVALS_REPORT.md"
    report_path.write_text(markdown, encoding="utf-8")
    payload = {"title": title, "generated": stamp, **_json_safe(results)}
    summary_path = directory / "empirical_arrivals_summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report": report_path, "summary": summary_path}
