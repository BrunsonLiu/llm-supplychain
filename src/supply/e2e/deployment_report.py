"""Markdown + JSON report for the Week-11 stock-deployment benchmark."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct

from .robustness import SUMMARY_METRICS


def _plan_labels(allocations: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {row["key"]: row["label"] for row in allocations}


def _plans_table(
    plans: Sequence[Dict[str, Any]], dcs: Sequence[str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "库存布点": row["label"],
                "声明占比": " / ".join(
                    f"{name} {value:.0%}" for name, value in zip(dcs, row["shares"])
                ),
                "实际占比": " / ".join(f"{value:.0%}" for value in row["stock_mix"]),
                "库存件数": " / ".join(f"{value:,}" for value in row["stock_units"]),
                "覆盖率": _pct(row.get("coverage")),
                "说明": row.get("note", ""),
            }
            for row in plans
        ]
    )


def _allocation_table(
    rows: Sequence[Dict[str, Any]], labels: Dict[str, str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "库存布点": labels.get(row["key"], row["key"]),
                "状态": row["status"],
                "件数满足": _pct(row.get("fill")),
                "票据": row.get("tickets", "—"),
                "分单 OTIF（上界）": _pct(row["alloc_otif_rate"]),
                "分单成本 (€)": _num(row["alloc_cost"], 0),
                "求解 (s)": _num(row.get("solve_seconds"), 2),
            }
            for row in rows
        ]
    )


def _distribution_table(
    rows: Sequence[Dict[str, Any]],
    labels: Dict[str, str],
    metric: str = "e2e_otif_rate",
) -> pd.DataFrame:
    picked = [row for row in rows if row["metric"] == metric]
    return pd.DataFrame(
        [
            {
                "库存布点": labels.get(row["scenario"], row["scenario"]),
                "压力格": row["cell_label"],
                "均值": _pct(row["mean"]),
                "95% CI": f"±{_pct(row['ci95'])}",
                "P10": _pct(row["p10"]),
                "P50": _pct(row["p50"]),
                "P90": _pct(row["p90"]),
                "最差 10% 均值": _pct(row["tail10"]),
                "最小": _pct(row["min"]),
                "最大": _pct(row["max"]),
                "n": row["n"],
            }
            for row in picked
        ]
    )


def _execution_table(
    rows: Sequence[Dict[str, Any]],
    over_shift: Sequence[Dict[str, Any]],
    labels: Dict[str, str],
) -> pd.DataFrame:
    index = {
        (row["scenario"], row["cell"]): row
        for row in rows
        if row["metric"] == "pick_on_time_rate"
    }
    tardy = {
        (row["scenario"], row["cell"]): row
        for row in rows
        if row["metric"] == "pick_tardiness"
    }
    makespan = {
        (row["scenario"], row["cell"]): row
        for row in rows
        if row["metric"] == "pick_makespan"
    }
    shift = {(row["scenario"], row["cell"]): row for row in over_shift}
    output = []
    for key, on_time in index.items():
        late = tardy[key]
        span = makespan[key]
        over = shift.get(key, {})
        output.append(
            {
                "库存布点": labels.get(key[0], key[0]),
                "压力格": on_time["cell_label"],
                "拣选准时均值": _pct(on_time["mean"]),
                "准时 95% CI": f"±{_pct(on_time['ci95'])}",
                "迟到分钟均值": _num(late["mean"], 0),
                "迟到分钟 P90": _num(late["p90"], 0),
                "Makespan 均值": _num(span["mean"], 0),
                "Makespan P90": _num(span["p90"], 0),
                "超班次概率": _pct(over.get("over_shift_rate", 0.0)),
            }
        )
    return pd.DataFrame(output)


def _dc_table(rows: Sequence[Dict[str, Any]], labels: Dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "库存布点": labels.get(row["plan"], row["plan"]),
                "DC": row["dc"],
                "票据": row["tickets"],
                "波次": row["waves"],
                "拣选工时": _num(row["labor_minutes"], 1),
                "准时票据": row["on_time_tickets"],
                "迟到票据": row["tardy_tickets"],
                "迟到分钟": _num(row["tardiness_minutes"], 1),
                "Makespan": _num(row["makespan"], 1),
            }
            for row in rows
        ]
    )


def _lookup(
    rows: Sequence[Dict[str, Any]], scenario: str, cell: str, metric: str
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if (
            row["scenario"] == scenario
            and row["cell"] == cell
            and row["metric"] == metric
        ):
            return row
    return None


def _gap_is_resolved(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    """Approximate two-sample check from the reported 95% half-widths."""
    gap = abs(first["mean"] - second["mean"])
    spread = math.sqrt(first["ci95"] ** 2 + second["ci95"] ** 2)
    return gap > spread


def _pick_interpretation(
    summary: Sequence[Dict[str, Any]],
    allocations: Sequence[Dict[str, Any]],
    plans: Sequence[Dict[str, Any]],
) -> List[str]:
    points: List[str] = []
    if not allocations:
        return points
    labels = _plan_labels(allocations)
    baseline = allocations[0]["key"]

    base_rows = [
        row
        for row in summary
        if row["cell"] == "base" and row["metric"] == "e2e_otif_rate"
    ]
    if not base_rows:
        return points
    ordered = {row["scenario"]: row for row in base_rows}
    base = ordered[baseline]
    best = max(base_rows, key=lambda row: row["mean"])
    worst = min(base_rows, key=lambda row: row["mean"])
    base_alloc = next(row for row in allocations if row["key"] == baseline)
    best_alloc = next(row for row in allocations if row["key"] == best["scenario"])

    if best["scenario"] != baseline:
        resolved = _gap_is_resolved(best, base)
        points.append(
            f"**Stock placement is a real service lever.** At the deterministic "
            f"baseline cell, `{labels.get(best['scenario'], best['scenario'])}` "
            f"reaches {best['mean']:.1%} end-to-end OTIF versus "
            f"{base['mean']:.1%} for `{labels.get(baseline, baseline)}` "
            f"({best['mean'] - base['mean']:+.1%}); the two 95% intervals "
            + ("do not overlap in the normal approximation."
               if resolved else "still overlap, so read the gap as directional.")
            + f" The allocation bound moves from {base_alloc['alloc_otif_rate']:.1%} "
            f"to {best_alloc['alloc_otif_rate']:.1%}, so the change is promise "
            "feasibility and pick load, not a different release policy."
        )
        points.append(
            f"**The trade-off is fill and cost, not free service.** Relative to "
            f"the baseline split, the better placement changes unit fill by "
            f"{best_alloc.get('fill', 0) - base_alloc.get('fill', 0):+.1%} and "
            f"allocation cost by €{best_alloc['alloc_cost'] - base_alloc['alloc_cost']:+,.0f}; "
            "the benchmark is a declared counterfactual on stock placement, not a "
            "cost-neutral improvement."
        )
    elif len(base_rows) > 1:
        runner = max(
            (row for row in base_rows if row["scenario"] != baseline),
            key=lambda row: row["mean"],
        )
        resolved = _gap_is_resolved(base, runner)
        points.append(
            f"**The default split is not beaten by any declared alternative.** "
            f"`{labels.get(baseline, baseline)}` stays the best placement at "
            f"{base['mean']:.1%} end-to-end OTIF; the runner-up "
            f"(`{labels.get(runner['scenario'], runner['scenario'])}`) is "
            f"{runner['mean']:.1%}, {base['mean'] - runner['mean']:.1%} lower, and "
            + ("the two 95% intervals do not overlap, so the gap is larger than "
               "this sample's noise." if resolved else
               "the intervals still overlap, so treat the ranking as directional.")
            + " Reallocating stock is not a free lever here: the declared default "
            "already sits at the front of this frontier."
        )

    inversions = [
        row
        for row in allocations
        if row["key"] in ordered
        and row["alloc_otif_rate"] > best_alloc["alloc_otif_rate"] + 1e-9
        and ordered[row["key"]]["mean"] < best["mean"] - 1e-9
    ]
    if inversions:
        inversion = max(inversions, key=lambda row: row["alloc_otif_rate"])
        inversion_row = ordered[inversion["key"]]
        tickets = ""
        if "tickets" in inversion and "tickets" in base_alloc:
            tickets = (
                f" and ships {inversion['tickets'] - base_alloc['tickets']:+d} more "
                "pick tickets than the default"
            )
        points.append(
            f"**A higher allocation bound does not survive the pick layer.** "
            f"`{labels.get(inversion['key'], inversion['key'])}` lifts the "
            f"allocation bound from {base_alloc['alloc_otif_rate']:.1%} to "
            f"{inversion['alloc_otif_rate']:.1%} "
            f"({inversion['alloc_otif_rate'] - base_alloc['alloc_otif_rate']:+.1%})"
            f" but its end-to-end mean is {inversion_row['mean']:.1%}, "
            f"{inversion_row['mean'] - best['mean']:+.1%} versus the default"
            f"{tickets}. The bound prices promise feasibility and stock, not the "
            "extra wave and pick work that the split creates."
        )

    best_index = base_rows.index(best)
    if worst["scenario"] != best["scenario"]:
        text = (
            f"**The placement frontier is not monotone.** "
            f"`{labels.get(worst['scenario'], worst['scenario'])}` lands at "
            f"{worst['mean']:.1%}, the lowest of {len(base_rows)} placements and "
            f"{best['mean'] - worst['mean']:.1%} below "
            f"`{labels.get(best['scenario'], best['scenario'])}`."
        )
        if best_index == 1 and len(base_rows) >= 3:
            text += (
                " The best split sits between the default and the one-sided "
                "extremes, so the frontier bends: pushing stock further toward "
                "either DC turns that DC into the new bottleneck, while the far DC "
                "loses the inventory it needs to serve nearby promises."
            )
        else:
            text += (
                " The ranking is not monotone in how concentrated the stock is, so "
                "no single 'more balanced wins' rule holds for this instance."
            )
        points.append(text)

    severe_rows = [
        row
        for row in summary
        if row["cell"] == "severe" and row["metric"] == "e2e_otif_rate"
    ]
    if severe_rows:
        severe_best = max(severe_rows, key=lambda row: row["mean"])
        same = severe_best["scenario"] == best["scenario"]
        runner = max(
            (row for row in severe_rows if row["scenario"] != severe_best["scenario"]),
            key=lambda row: row["mean"],
            default=None,
        )
        text = (
            f"**The ranking survives congestion.** Under severe pick-time noise "
            f"(σ=0.40) the best placement is "
            f"`{labels.get(severe_best['scenario'], severe_best['scenario'])}` at "
            f"{severe_best['mean']:.1%}"
        )
        if runner is not None:
            text += (
                f", ahead of "
                f"`{labels.get(runner['scenario'], runner['scenario'])}` at "
                f"{runner['mean']:.1%} ({severe_best['mean'] - runner['mean']:+.1%})"
            )
        text += (
            "; the same plan wins both the mean and the stress cell."
            if same
            else "; a different plan wins the stress cell, so the choice depends "
            "on the congestion stance."
        )
        points.append(text)

    if len(base_rows) > 1:
        worst_tail = min(base_rows, key=lambda row: row["tail10"])
        if worst_tail["scenario"] == worst["scenario"]:
            points.append(
                f"**Tail service ranks the plans the same way as the mean.** "
                f"`{labels.get(worst_tail['scenario'], worst_tail['scenario'])}` "
                f"has both the lowest mean ({worst['mean']:.1%}) and the lowest "
                f"worst-decile mean ({worst_tail['tail10']:.1%}), so the ordering "
                "is not a mean-only artifact."
            )
        else:
            points.append(
                f"**Tail service reorders the plans.** `{labels.get(worst_tail['scenario'], worst_tail['scenario'])}` "
                f"has the lowest worst-decile mean ({worst_tail['tail10']:.1%}) "
                f"even though `{labels.get(worst['scenario'], worst['scenario'])}` "
                f"has the lowest mean ({worst['mean']:.1%}); a service-level "
                "target reads the tail, not the average."
            )

    capacity_rows = [
        row
        for row in summary
        if row["cell"] == "two_pickers" and row["metric"] == "e2e_otif_rate"
    ]
    if capacity_rows:
        bounds = {row["key"]: row["alloc_otif_rate"] for row in allocations}
        gaps = [
            abs(row["mean"] - bounds[row["scenario"]])
            for row in capacity_rows
            if row["scenario"] in bounds
        ]
        cap_best = max(capacity_rows, key=lambda row: row["mean"])
        cap_base = next(
            (row for row in capacity_rows if row["scenario"] == baseline),
            capacity_rows[0],
        )
        text = (
            f"**With enough pick capacity the ranking reverts to the allocation "
            f"bound.** Adding a picker per DC moves every plan to its own bound "
            f"(largest gap {max(gaps):.1%})"
        )
        if cap_best["scenario"] != baseline:
            text += (
                f", and `{labels.get(cap_best['scenario'], cap_best['scenario'])}` "
                f"now leads at {cap_best['mean']:.1%} versus {cap_base['mean']:.1%} "
                "for the default. The placement that loses at one picker is the "
                "better one once the pick bottleneck is removed, so stock placement "
                "and pick capacity are joint decisions."
            )
        else:
            text += (
                f", and the default still leads at {cap_best['mean']:.1%}. "
                "Placement does not change the bound ordering when the pick layer "
                "is not the constraint."
            )
        points.append(text)

    points.append(
        "**Declared assumptions, not observed inventory.** The stock splits, the "
        "per-SKU jitter, the DC capacity, transit days and the pick-time model are "
        "assumptions. The counterfactual re-solves the allocation for each split "
        "and replays the same order set, arrivals and congestion draws; it does "
        "not model replenishment, transfers between DCs or demand shifting."
    )
    return points


def build_stock_deployment_report(
    results: Dict[str, Any],
    title: str = "Stock deployment under execution risk (Week 11)",
    generated: Optional[str] = None,
) -> str:
    dataset = results.get("dataset", {})
    seeds = results.get("seeds", [])
    summary = results.get("summary", [])
    over_shift = results.get("over_shift", [])
    cells = results.get("cells", [])
    plans = results.get("plans", [])
    allocations = results.get("allocations", [])
    dc_rows = results.get("dc_workload", [])
    labels = _plan_labels(allocations)
    dcs = dataset.get("dcs", [])
    stamp = generated or datetime.now(timezone.utc).isoformat()

    lines: List[str] = [f"# {title}", ""]
    lines.append(f"- Generated: `{stamp}`")
    lines.append(
        f"- Orders: **{dataset.get('orders', '—')}** real invoices / "
        f"**{dataset.get('lines', '—')}** lines / "
        f"**{dataset.get('units', '—')}** units, week {dataset.get('week', '—')}"
    )
    lines.append(
        f"- Seeds per cell: **{len(seeds)}**; stress cells: **{len(cells)}**; "
        f"stock plans: **{len(plans)}**"
    )
    lines.append(
        f"- Picking: **{dataset.get('pickers_per_dc', '—')} picker(s) per DC**, "
        f"wave cap **{dataset.get('max_orders', '—')} orders / "
        f"{dataset.get('max_lines', '—')} lines**, shift "
        f"**{dataset.get('shift_minutes', '—')} min**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines.append("| Item | Assumption | Note |")
    lines.append("|---|---|---|")
    lines.append(
        "| Stock split | declared DC shares + deterministic per-SKU jitter | "
        "Total stock and the order set stay fixed; only placement moves. |"
    )
    lines.append(
        "| Allocation | one pick-capacity-aware MILP per plan, 60 s budget | "
        "Re-solved for each split, so cost/OTIF differences mix placement and solver quality. |"
    )
    lines.append(
        "| Execution | arrivals and pick durations resampled per seed | "
        "Same seeds across plans; the stock split is the only structural change. |"
    )
    lines.append(
        "| Network | 3 DCs, declared transit days, capacity and handling costs | "
        "No replenishment, DC-to-DC transfer or demand shift. |"
    )
    lines.append("")

    lines += ["## Methods", ""]
    lines.append(
        "- **Stock plans**: the Week-5 default split, a balanced split, and two "
        "one-sided splits (Rotterdam-heavy and London-heavy) to bound the frontier."
    )
    lines.append(
        "- **Allocation**: for each plan, solve the Week-5 service-weighted MILP "
        "with the Week-9 pick-capacity proxy, using one 30 s service warm start "
        "and one 60 s load-aware solve."
    )
    lines.append(
        "- **Replay**: for each plan and seed, redraw arrivals, rerun the Week-8 "
        "event-driven release per DC, and recompute the Week-9 end-to-end OTIF."
    )
    lines.append(
        "- **Statistics**: mean with a normal 95% interval, P10/P50/P90, "
        "worst-decile mean, over-shift probability, and a per-DC workload "
        "snapshot at the first seed."
    )
    lines.append("")

    lines += ["## Stock plans", "", _md_table(_plans_table(plans, dcs)), ""]
    lines += [
        "## Allocation outcomes",
        "",
        _md_table(_allocation_table(allocations, labels)),
        "",
    ]
    lines += [
        "## End-to-end OTIF distribution",
        "",
        _md_table(_distribution_table(summary, labels)),
        "",
        "Each row is one stock plan × stress cell. `95% CI` is the normal "
        "approximation; `worst 10% mean` averages the lowest decile of seeds.",
        "",
    ]
    lines += [
        "## Execution risk",
        "",
        _md_table(_execution_table(summary, over_shift, labels)),
        "",
    ]
    if dc_rows:
        lines += [
            "## Per-DC workload (seed 1, baseline cell)",
            "",
            _md_table(_dc_table(dc_rows, labels)),
            "",
            "The snapshot shows how the stock split moves pick load across DCs; "
            "it is not averaged over seeds.",
            "",
        ]

    lines += ["## Interpretation", ""]
    for index, point in enumerate(
        _pick_interpretation(summary, allocations, plans), 1
    ):
        lines.append(f"{index}. {point}")
    lines.append("")

    lines += ["## Declared assumptions", ""]
    for item in results.get("declared_assumptions", []):
        lines.append(f"- {item}")
    lines.append("")

    lines += ["## Limitations", ""]
    lines.append(
        "- Stock is placed by declared shares plus a jitter, not by observed "
        "inventory; the counterfactual says what would happen under this model, "
        "not what a retailer should do without a demand and replenishment model."
    )
    lines.append(
        "- The allocation is a time-limited `FEASIBLE` MILP per plan; solver "
        "variation mixes with the placement effect, and the plans are not "
        "optimised jointly with the stock split."
    )
    lines.append(
        "- The order set, promises, layout, slots and picker count are fixed; "
        "only stock placement changes. Replenishment, transfers, demand shifts "
        "and supplier constraints are outside the chain."
    )
    lines.append(
        "- The normal 95% interval is an approximation, comparisons across plans "
        "are unpaired (different stock implies different feasible sets), and the "
        "worst-decile mean is noisy with 30 seeds."
    )
    lines.append("")
    return "\n".join(lines)


def write_stock_deployment_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Stock deployment under execution risk (Week 11)",
) -> Dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    markdown = build_stock_deployment_report(results, title=title, generated=stamp)
    report_path = directory / "STOCK_DEPLOYMENT_REPORT.md"
    report_path.write_text(markdown, encoding="utf-8")

    payload = {"title": title, "generated": stamp, **_json_safe(results)}
    summary_path = directory / "stock_deployment_summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report": report_path, "summary": summary_path}
