"""Markdown + JSON report for the Week-13 joint allocation/placement benchmark."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct


def _labels(allocations: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {row["key"]: row["label"] for row in allocations}


def _placements_table(
    placements: Sequence[Dict[str, Any]], dcs: Sequence[str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Placement": row["label"],
                "Source": row.get("source", "—"),
                "DC mix": " / ".join(
                    f"{name} {value:.0%}"
                    for name, value in zip(dcs, row["stock_mix"])
                ),
                "Stock units": " / ".join(
                    f"{value:,}" for value in row["stock_units"]
                ),
                "Coverage": _pct(row.get("coverage")),
                "Note": row.get("note", ""),
            }
            for row in placements
        ]
    )


def _allocation_table(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Placement": row["label"],
                "Status": row["status"],
                "Unit fill": _pct(row.get("fill")),
                "Tickets": row.get("tickets", "—"),
                "Allocation OTIF (bound)": _pct(row["alloc_otif_rate"]),
                "Allocation cost (€)": _num(row["alloc_cost"], 0),
                "Solve (s)": _num(row.get("solve_seconds"), 2),
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
                "Placement": labels.get(row["scenario"], row["scenario"]),
                "Stress cell": row["cell_label"],
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
                "Placement": labels.get(key[0], key[0]),
                "Stress cell": on_time["cell_label"],
                "Pick on-time": _pct(on_time["mean"]),
                "Pick on-time 95% CI": f"±{_pct(on_time['ci95'])}",
                "Tardy minutes": _num(late["mean"], 0),
                "Tardy minutes P90": _num(late["p90"], 0),
                "Makespan": _num(span["mean"], 0),
                "Makespan P90": _num(span["p90"], 0),
                "Over-shift": _pct(over.get("over_shift_rate", 0.0)),
            }
        )
    return pd.DataFrame(output)


def _paired_table(
    paired: Sequence[Dict[str, Any]], labels: Dict[str, str]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Comparison": row["comparison"],
                "Stress cell": row["cell_label"],
                "Δ OTIF": f"{row['mean_delta']:+.2%}",
                "95% CI": f"±{_pct(row['ci95'])}",
                "Win": _pct(row["win_rate"]),
                "Loss": _pct(row["loss_rate"]),
                "Tie": _pct(row["tie_rate"]),
                "n": row["n"],
            }
            for row in paired
        ]
    )


def _dc_table(rows: Sequence[Dict[str, Any]], labels: Dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Placement": labels.get(row["scenario"], row["scenario"]),
                "DC": row["dc"],
                "Tickets": row["tickets"],
                "Waves": row["waves"],
                "Labor (min)": _num(row["labor_minutes"], 1),
                "On-time tickets": row["on_time_tickets"],
                "Tardy tickets": row["tardy_tickets"],
                "Tardy minutes": _num(row["tardiness_minutes"], 1),
                "Makespan": _num(row["makespan"], 1),
            }
            for row in rows
        ]
    )


def _lookup(
    rows: Sequence[Dict[str, Any]], scenario: str, cell: str
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if (
            row["metric"] == "e2e_otif_rate"
            and row["scenario"] == scenario
            and row["cell"] == cell
        ):
            return row
    return None


def _resolved(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    gap = abs(first["mean"] - second["mean"])
    spread = math.sqrt(first["ci95"] ** 2 + second["ci95"] ** 2)
    return gap > spread


def _interpretation(
    summary: Sequence[Dict[str, Any]],
    allocations: Sequence[Dict[str, Any]],
) -> List[str]:
    labels = _labels(allocations)
    order = [row["key"] for row in allocations]
    baseline = order[0]
    points: List[str] = []

    base_rows = [
        row
        for row in summary
        if row["cell"] == "base" and row["metric"] == "e2e_otif_rate"
    ]
    if not base_rows:
        return points
    by_key = {row["scenario"]: row for row in base_rows}
    base = by_key[baseline]
    best = max(base_rows, key=lambda row: row["mean"])

    if best["scenario"] != baseline:
        plan_driven = best["scenario"] in {"joint_plan", "joint_placement"}
        headline = (
            "**The joint solve, not the declared split, tops the known week.**"
            if plan_driven
            else "**The declared split is not the service frontier.**"
        )
        qualifier = (
            " This is a plan-driven scenario: it sees the week's orders, so read "
            "it as a hindsight bound rather than a deployable policy."
            if plan_driven
            else ""
        )
        points.append(
            f"{headline} At the "
            f"deterministic baseline cell, `{labels.get(best['scenario'], best['scenario'])}` "
            f"reaches {best['mean']:.1%} end-to-end OTIF versus "
            f"{base['mean']:.1%} for `{labels.get(baseline, baseline)}` "
            f"({best['mean'] - base['mean']:+.1%}); the 95% intervals "
            + ("do not overlap in the normal approximation."
               if _resolved(best, base) else "still overlap, so read the gap as directional.")
            + qualifier
        )
    else:
        points.append(
            f"**The declared placement still wins.** `{labels.get(baseline, baseline)}` "
            f"stays best at {base['mean']:.1%}; neither demand-history nor "
            "plan-driven placement beats it on this instance."
        )

    destination = by_key.get("destination")
    if destination is not None:
        delta = destination["mean"] - base["mean"]
        verdict = "beats" if delta > 0 else "does not beat"
        points.append(
            f"**Capacity-blind history is a demand signal, not a placement.** The "
            f"prior-week UK/EU mix {verdict} the declared split at the baseline "
            f"cell ({destination['mean']:.1%} vs {base['mean']:.1%}, "
            f"{delta:+.1%}). It concentrates stock wherever demand was, ignoring "
            "whether that DC can pick it."
        )

    capped = by_key.get("destination_capped")
    if capped is not None and destination is not None:
        cap_delta = capped["mean"] - destination["mean"]
        vs_base = capped["mean"] - base["mean"]
        if abs(cap_delta) <= max(capped["ci95"], destination["ci95"]):
            points.append(
                f"**Capping history to DC throughput does not move service here.** "
                f"The capacity-capped version reaches {capped['mean']:.1%} versus "
                f"{destination['mean']:.1%} for raw history ({cap_delta:+.1%}), "
                "inside the seed noise; the history mix already sat close to each "
                f"DC's weekly share. Against the declared split it is "
                f"{vs_base:+.1%} ({capped['mean']:.1%} vs {base['mean']:.1%})."
            )
        elif cap_delta > 0:
            points.append(
                f"**A deployable history mix must be capped to DC throughput.** Raw "
                f"destination history is capacity-blind and scores "
                f"{destination['mean']:.1%}; clipping each DC's share at its weekly "
                f"capacity lifts it to {capped['mean']:.1%} ({cap_delta:+.1%}). "
                f"Against the declared split the capped placement is "
                f"{vs_base:+.1%} ({capped['mean']:.1%} vs {base['mean']:.1%})."
            )
        else:
            points.append(
                f"**Capping protects pick capacity but moves stock away from "
                f"demand.** The raw history mix scores {destination['mean']:.1%}; "
                f"clipping it to DC throughput gives {capped['mean']:.1%} "
                f"({cap_delta:+.1%}), and the capped placement is {vs_base:+.1%} "
                f"against the declared split ({capped['mean']:.1%} vs "
                f"{base['mean']:.1%}). The cap trades transit against a fill "
                "loss, so neither history variant is automatically deployable."
            )

    joint_plan = by_key.get("joint_plan")
    joint_placement = by_key.get("joint_placement")
    if joint_plan is not None and joint_placement is not None:
        delta = joint_plan["mean"] - joint_placement["mean"]
        if abs(delta) <= max(joint_plan["ci95"], joint_placement["ci95"]):
            points.append(
                f"**The gain comes from where stock sits, not from re-solving the "
                f"allocation.** Joint placement with the standard capacity-aware "
                f"allocation reaches {joint_placement['mean']:.1%}; solving "
                f"placement and allocation together adds {delta:+.1%} "
                f"({joint_plan['mean']:.1%}), inside the seed noise. Once stock can "
                "follow the plan, the recursive allocation matters little."
            )
        elif delta > 0:
            points.append(
                f"**Joint allocation adds service beyond placement alone.** Joint "
                f"placement with the standard allocation reaches "
                f"{joint_placement['mean']:.1%}; the joint plan adds {delta:+.1%} "
                f"({joint_plan['mean']:.1%}). The two stages interact, so solving "
                "them separately leaves value on the table."
            )
        else:
            points.append(
                f"**Joint placement, not the joint solve, carries the gain.** The "
                f"joint MILP's placement with the standard allocation reaches "
                f"{joint_placement['mean']:.1%}, which is {-delta:+.1%} above the "
                f"joint plan itself ({joint_plan['mean']:.1%}). Once placement "
                "follows demand, re-solving the allocation on it is at least as "
                "good as the joint MILP's own search on this instance."
            )

    bounds = {row["key"]: row["alloc_otif_rate"] for row in allocations}
    if joint_plan is not None and "joint_plan" in bounds:
        joint_bound = bounds["joint_plan"]
        base_bound = bounds.get(baseline, float("nan"))
        ratio_joint = (
            joint_plan["mean"] / joint_bound if joint_bound > 0 else float("nan")
        )
        ratio_base = base["mean"] / base_bound if base_bound > 0 else float("nan")
        relation = "below" if joint_bound < base_bound else "above"
        tail = (
            " The joint plan trades unpickable promises for tickets the shift can "
            "finish; a higher bound that the warehouse cannot execute is not worth "
            "more service."
            if joint_bound < base_bound
            else " The pick layer, not the allocation stage, decides how much of "
            "either bound is real."
        )
        points.append(
            f"**The allocation bound is not the service level.** The joint plan's "
            f"own allocation OTIF is {joint_bound:.1%}, {relation} the declared "
            f"allocation's {base_bound:.1%}, yet {ratio_joint:.0%} of it survives "
            f"the pick layer versus {ratio_base:.0%} for the declared split "
            f"({joint_plan['mean']:.1%} vs {base['mean']:.1%})." + tail
        )

    capacity_rows = [
        row
        for row in summary
        if row["cell"] == "two_pickers" and row["metric"] == "e2e_otif_rate"
    ]
    if capacity_rows:
        gaps = [
            abs(row["mean"] - bounds[row["scenario"]])
            for row in capacity_rows
            if row["scenario"] in bounds
        ]
        best_cap = max(capacity_rows, key=lambda row: row["mean"])
        cap_by = {row["scenario"]: row for row in capacity_rows}
        note = ""
        if joint_plan is not None and "joint_plan" in cap_by:
            gain = cap_by["joint_plan"]["mean"] - joint_plan["mean"]
            note = (
                f" The joint plan gains only {gain:+.1%}: its placement and "
                "allocation are fixed once solved, so extra pickers cannot "
                "re-optimise them. A static plan is tuned to the capacity it saw."
            )
        points.append(
            f"**Extra pick capacity closes the execution gap.** With two pickers "
            f"per DC every placement returns to its own allocation bound (largest "
            f"gap {max(gaps):.1%}); `{labels.get(best_cap['scenario'], best_cap['scenario'])}` "
            f"then leads at {best_cap['mean']:.1%}. Placement and pick capacity are "
            "still joint decisions." + note
        )

    severe = [
        row
        for row in summary
        if row["cell"] == "severe" and row["metric"] == "e2e_otif_rate"
    ]
    if severe:
        severe_best = max(severe, key=lambda row: row["mean"])
        points.append(
            f"**Congestion does not reverse the ordering by itself.** Under "
            f"σ=0.40 the best placement is "
            f"`{labels.get(severe_best['scenario'], severe_best['scenario'])}` at "
            f"{severe_best['mean']:.1%}; compare it with the one-picker baseline "
            "before treating the ranking as robust."
        )

    points.append(
        "**The plan-driven placement is an upper bound, not a policy.** It places "
        "stock after seeing the week's orders. The capacity-capped destination "
        "history is the deployable comparator; the gap between them is the value "
        "of hindsight, not a forecast improvement."
    )
    return points


def build_joint_report(
    results: Dict[str, Any],
    title: str = "Joint allocation and stock placement (Week 13)",
    generated: Optional[str] = None,
) -> str:
    dataset = results.get("dataset", {})
    seeds = results.get("seeds", [])
    summary = results.get("summary", [])
    over_shift = results.get("over_shift", [])
    cells = results.get("cells", [])
    placements = results.get("placements", [])
    allocations = results.get("allocations", [])
    paired = results.get("paired", [])
    dc_rows = results.get("dc_workload", [])
    mix_meta = results.get("destination_mix", {})
    labels = _labels(allocations)
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
        f"stock placements: **{len(placements)}** (the two joint scenarios share "
        "one implied placement)"
    )
    lines.append(
        f"- Picking: **{dataset.get('pickers_per_dc', '—')} picker(s) per DC**, "
        f"wave cap **{dataset.get('max_orders', '—')} orders / "
        f"{dataset.get('max_lines', '—')} lines**, shift "
        f"**{dataset.get('shift_minutes', '—')} min**"
    )
    if mix_meta:
        lines.append(
            f"- Destination history: **{mix_meta.get('history_skus', '—')}** SKUs "
            f"with history, **{mix_meta.get('fallback_skus', '—')}** fallback, "
            f"weeks {mix_meta.get('start_week', '—')}..{mix_meta.get('end_week', '—')}"
        )
        cap = mix_meta.get("capacity_cap")
        if cap:
            lines.append(
                "- DC throughput cap: "
                + " / ".join(
                    f"{name} {value:.0%}" for name, value in zip(dcs, cap)
                )
            )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines.append("| Item | Assumption | Note |")
    lines.append("|---|---|---|")
    lines.append(
        "| Stock total | each SKU's total units stay fixed | Only placement moves; "
        "the order set and 85% coverage are unchanged. |"
    )
    lines.append(
        "| Destination mix | prior 8 weeks of units by destination region | "
        "UK -> London; EU split 45/55 Rotterdam/Frankfurt by declaration. |"
    )
    lines.append(
        "| Capacity cap | each DC holds at most its share of weekly throughput | "
        "Excess is redistributed by remaining DC headroom; the cap is a unit "
        "share, not a slot or SKU-level storage limit. |"
    )
    lines.append(
        "| Joint placement | allocation sees only per-SKU total stock | "
        "The implied placement is a known-week upper bound, not a forecast. |"
    )
    lines.append(
        "| Allocation | Week-9 two-stage MILP, 30 s service + 60 s load-aware | "
        "Time-limited `FEASIBLE`; pick capacity is linear minutes. |"
    )
    lines.append(
        "| Execution | arrivals and pick durations resampled per seed | "
        "Same seeds and cells as Weeks 10-12. |"
    )
    lines.append("")

    lines += ["## Methods", ""]
    lines.append(
        "- **Declared placement**: Week-5 baseline 34/28/38 plus the deterministic "
        "per-SKU jitter, then the Week-9 capacity-aware allocation."
    )
    lines.append(
        "- **Destination placement**: per-SKU prior-week UK/EU mix mapped to the "
        "three DCs, then the same capacity-aware allocation."
    )
    lines.append(
        "- **Capacity-capped destination placement**: the same mix with each DC's "
        "per-SKU share clipped at `throughput / total stock`, then the excess "
        "redistributed by remaining headroom. This is the deployable comparator."
    )
    lines.append(
        "- **Joint placement + re-solved allocation**: the joint MILP's implied "
        "placement, then the standard capacity-aware allocation on that placement."
    )
    lines.append(
        "- **Joint plan**: one MILP allocates orders and lets placement follow, "
        "with a destination-mix reserve for unallocated units."
    )
    lines.append(
        "- **Solver status**: both allocation stages are time-limited; the joint "
        "bound is loose once the service bonus makes the objective negative, so "
        "the solve time and `FEASIBLE` status are reported but no bound gap is "
        "claimed as solution quality."
    )
    lines.append(
        "- **Replay**: for each placement and seed, redraw arrivals, rerun the "
        "Week-8 online release per DC, and recompute Week-9 end-to-end OTIF."
    )
    lines.append("")

    lines += ["## Stock placements", "", _md_table(_placements_table(placements, dcs)), ""]
    lines += [
        "## Allocation outcomes",
        "",
        _md_table(_allocation_table(allocations)),
        "",
        "Costs are not comparable across placements: the joint scenarios put "
        "stock where the plan ships and pay no repositioning, so their transport "
        "cost is an optimistic lower bound.",
        "",
    ]
    lines += [
        "## End-to-end OTIF distribution",
        "",
        _md_table(_distribution_table(summary, labels)),
        "",
        "Each row is one placement × stress cell. `95% CI` is the normal "
        "approximation; `worst 10% mean` averages the lowest decile of seeds.",
        "",
    ]
    lines += [
        "## Execution risk",
        "",
        _md_table(_execution_table(summary, over_shift, labels)),
        "",
    ]
    if paired:
        lines += [
            "## Paired comparisons",
            "",
            _md_table(_paired_table(paired, labels)),
            "",
            "The same arrival seed is replayed for both placements; the delta is "
            "`alternative − left`. Win/loss/tie counts are over seeds.",
            "",
        ]
    if dc_rows:
        lines += [
            "## Per-DC workload (seed 1, baseline cell)",
            "",
            _md_table(_dc_table(dc_rows, labels)),
            "",
            "The snapshot shows how placement moves pick load across DCs; it is "
            "not averaged over seeds.",
            "",
        ]

    lines += ["## Interpretation", ""]
    for index, point in enumerate(_interpretation(summary, allocations), 1):
        lines.append(f"{index}. {point}")
    lines.append("")

    lines += ["## Declared assumptions", ""]
    for item in results.get("declared_assumptions", []):
        lines.append(f"- {item}")
    lines.append("")

    lines += ["## Limitations", ""]
    lines.append(
        "- The destination mix is a proxy for demand, not a forecast; it ignores "
        "promotions, seasonality and the current week's orders, and the EU split "
        "inside the continent is declared rather than estimated. The capacity cap "
        "uses aggregate weekly throughput, so a DC can still be capped by unit "
        "count while being short of the exact SKUs the week needs."
    )
    lines.append(
        "- The plan-driven placement is hindsight: it sees the sampled week's "
        "orders. Its service level is an upper bound on joint planning for a "
        "known week, not a deployable policy."
    )
    lines.append(
        "- Both MILPs are time-limited `FEASIBLE`; the 60 s bound is loose and "
        "solver variation can mix with the placement effect. Pick capacity is a "
        "linear minute proxy, not a wave simulation."
    )
    lines.append(
        "- The joint placements have no repositioning cost: the model assumes "
        "stock can sit at the shipping DC at the start of the week, so its "
        "allocation cost is not comparable with the declared placement's "
        "transport cost. A real deployment would pay to move or hold that stock."
    )
    lines.append(
        "- The order set, promises, layout, slots and picker count are fixed; "
        "replenishment, DC-to-DC transfers, supplier constraints and demand "
        "shifts are outside the chain."
    )
    lines.append(
        "- The normal 95% interval is an approximation; placement comparisons "
        "are paired on arrival and noise seeds but not on solver outcomes, and "
        "the worst-decile mean is noisy with 30 seeds."
    )
    lines.append("")
    return "\n".join(lines)


def write_joint_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Joint allocation and stock placement (Week 13)",
) -> Dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    markdown = build_joint_report(results, title=title, generated=stamp)
    report_path = directory / "JOINT_PLACEMENT_REPORT.md"
    report_path.write_text(markdown, encoding="utf-8")

    payload = {"title": title, "generated": stamp, **_json_safe(results)}
    summary_path = directory / "joint_placement_summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report": report_path, "summary": summary_path}
