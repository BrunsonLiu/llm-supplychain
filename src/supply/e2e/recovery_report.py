"""Markdown + JSON report for the Week-12 mid-shift write-back benchmark."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct

DOWN_METRICS = {
    "e2e_otif_rate",
    "pick_on_time_rate",
    "pick_tardiness",
    "pick_makespan",
}


def _labels(allocations: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {row["key"]: row["label"] for row in allocations}


def _placement_table(
    placements: Sequence[Dict[str, Any]],
    allocations: Sequence[Dict[str, Any]],
    dcs: Sequence[str],
) -> pd.DataFrame:
    allocation = {row["key"]: row for row in allocations}
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
                "分单界 OTIF": _pct(
                    allocation.get(row["key"], {}).get("alloc_otif_rate")
                ),
                "分单成本 (€)": _num(
                    allocation.get(row["key"], {}).get("alloc_cost"), 0
                ),
            }
            for row in placements
        ]
    )


def _summary_row(
    summary: Sequence[Dict[str, Any]],
    placement: str,
    cell: str,
    policy: str,
    metric: str,
) -> Optional[Dict[str, Any]]:
    for row in summary:
        if (
            row["scenario"] == placement
            and row["cell"] == cell
            and row["policy"] == policy
            and row["metric"] == metric
        ):
            return row
    return None


def _paired_row(
    paired: Sequence[Dict[str, Any]],
    placement: str,
    cell: str,
    policy: str,
) -> Optional[Dict[str, Any]]:
    for row in paired:
        if (
            row["scenario"] == placement
            and row["cell"] == cell
            and row["policy"] == policy
        ):
            return row
    return None


def _policy_table(
    placements: Sequence[Dict[str, Any]],
    cells: Sequence[Dict[str, Any]],
    policies: Sequence[Dict[str, str]],
    summary: Sequence[Dict[str, Any]],
    paired: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    rows = []
    for placement in placements:
        for cell in cells:
            base = _summary_row(
                summary, placement["key"], cell["key"], "none", "e2e_otif_rate"
            )
            for policy in policies:
                row = _summary_row(
                    summary,
                    placement["key"],
                    cell["key"],
                    policy["key"],
                    "e2e_otif_rate",
                )
                if row is None:
                    continue
                delta = None if base is None else row["mean"] - base["mean"]
                pair = _paired_row(
                    paired, placement["key"], cell["key"], policy["key"]
                )
                moves = _summary_row(
                    summary,
                    placement["key"],
                    cell["key"],
                    policy["key"],
                    "moved_tickets",
                )
                cost = _summary_row(
                    summary,
                    placement["key"],
                    cell["key"],
                    policy["key"],
                    "recovery_cost",
                )
                rows.append(
                    {
                        "库存布点": placement["label"],
                        "压力格": cell["label"],
                        "回写策略": policy["label"],
                        "端到端 OTIF": _pct(row["mean"]),
                        "95% CI": f"±{_pct(row['ci95'])}",
                        "Δ vs 无回写": (
                            "—"
                            if policy["key"] == "none" or delta is None
                            else f"{delta:+.1%}"
                        ),
                        "胜/平/负": (
                            "—"
                            if pair is None
                            else f"{pair['win_rate']:.0%} / "
                            f"{pair['tie_rate']:.0%} / {pair['loss_rate']:.0%}"
                        ),
                        "调动票据": _num(moves["mean"], 1) if moves else "—",
                        "回写成本 (€)": _num(cost["mean"], 0) if cost else "—",
                    }
                )
    return pd.DataFrame(rows)


def _execution_table(
    placements: Sequence[Dict[str, Any]],
    cells: Sequence[Dict[str, Any]],
    policies: Sequence[Dict[str, str]],
    summary: Sequence[Dict[str, Any]],
    over_shift: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    shift = {
        (row["scenario"], row["cell"], row["policy"]): row for row in over_shift
    }
    rows = []
    for placement in placements:
        for cell in cells:
            for policy in policies:
                on_time = _summary_row(
                    summary,
                    placement["key"],
                    cell["key"],
                    policy["key"],
                    "pick_on_time_rate",
                )
                if on_time is None:
                    continue
                late = _summary_row(
                    summary,
                    placement["key"],
                    cell["key"],
                    policy["key"],
                    "pick_tardiness",
                )
                span = _summary_row(
                    summary,
                    placement["key"],
                    cell["key"],
                    policy["key"],
                    "pick_makespan",
                )
                over = shift.get((placement["key"], cell["key"], policy["key"]), {})
                rows.append(
                    {
                        "库存布点": placement["label"],
                        "压力格": cell["label"],
                        "回写策略": policy["label"],
                        "拣选准时": _pct(on_time["mean"]),
                        "迟到分钟": _num(late["mean"], 0) if late else "—",
                        "Makespan": _num(span["mean"], 0) if span else "—",
                        "超班次概率": _pct(over.get("over_shift_rate", 0.0)),
                    }
                )
    return pd.DataFrame(rows)


def _move_table(
    placements: Sequence[Dict[str, Any]],
    cells: Sequence[Dict[str, Any]],
    policies: Sequence[Dict[str, str]],
    rows: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    index = {
        (row["scenario"], row["cell"], row["policy"]): row for row in rows
    }
    output = []
    for placement in placements:
        for cell in cells:
            for policy in policies:
                row = index.get((placement["key"], cell["key"], policy["key"]))
                if row is None or policy["key"] == "none":
                    continue
                output.append(
                    {
                        "库存布点": placement["label"],
                        "压力格": cell["label"],
                        "回写策略": policy["label"],
                        "有调动种子": f"{row['seeds_with_moves']}/{row['runs']}",
                        "平均票据": _num(row["mean_moves"], 1),
                        "平均件数": _num(row["mean_units"], 0),
                        "平均调拨费 (€)": _num(row["mean_fee"], 0),
                        "平均运输差 (€)": _num(row["mean_transport_delta"], 0),
                        "救回订单": row["rescued_orders"],
                        "丢失订单": row["lost_orders"],
                    }
                )
    return pd.DataFrame(output)


def _route_table(
    placements: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    top: int = 8,
) -> pd.DataFrame:
    labels = {row["key"]: row["label"] for row in placements}
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame = (
        frame.groupby(
            ["scenario", "cell_label", "policy_label", "from_dc", "to_dc"],
            as_index=False,
        )["moves"]
        .sum()
        .sort_values(["scenario", "cell_label", "policy_label", "moves"], ascending=[True, True, True, False])
    )
    frame = frame.groupby(["scenario", "cell_label", "policy_label"], sort=False).head(top)
    return pd.DataFrame(
        [
            {
                "库存布点": labels.get(row["scenario"], row["scenario"]),
                "压力格": row["cell_label"],
                "回写策略": row["policy_label"],
                "方向": f"{row['from_dc']} → {row['to_dc']}",
                "票据": int(row["moves"]),
            }
            for _, row in frame.iterrows()
        ]
    )


def _review_table(
    placements: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
    baseline_review: float,
) -> pd.DataFrame:
    labels = {row["key"]: row["label"] for row in placements}
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    output = []
    for placement, block in frame.groupby("scenario", sort=False):
        reference = block[
            block["review_minute"].astype(float) == float(baseline_review)
        ]
        ref_mean = float(reference["mean_otif"].mean()) if not reference.empty else math.nan
        for row in block.itertuples():
            delta = (
                "—"
                if math.isnan(ref_mean)
                else f"{float(row.mean_otif) - ref_mean:+.1%}"
            )
            output.append(
                {
                    "库存布点": labels.get(placement, placement),
                    "审核时点": f"{int(row.review_minute)} min",
                    "端到端 OTIF": _pct(row.mean_otif),
                    "Δ vs 默认时点": delta,
                    "平均调动票据": _num(row.mean_moves, 1),
                    "救回订单": int(row.rescued_orders),
                    "丢失订单": int(row.lost_orders),
                }
            )
    return pd.DataFrame(output)


def _dc_table(
    placements: Sequence[Dict[str, Any]],
    rows: Sequence[Dict[str, Any]],
) -> pd.DataFrame:
    labels = {row["key"]: row["label"] for row in placements}
    return pd.DataFrame(
        [
            {
                "库存布点": labels.get(row["scenario"], row["scenario"]),
                "回写策略": row["policy_label"],
                "DC": row["dc"],
                "票据": row["tickets"],
                "波次": row["waves"],
                "准时": row["on_time_tickets"],
                "迟到": row["tardy_tickets"],
                "迟到分钟": _num(row["tardiness_minutes"], 0),
                "Makespan": _num(row["makespan"], 0),
                "调入": row["moved_in"],
                "调出": row["moved_out"],
            }
            for row in rows
        ]
    )


def _best_policy(
    summary: Sequence[Dict[str, Any]], placement: str, cell: str
) -> Optional[Dict[str, Any]]:
    rows = [
        row
        for row in summary
        if row["scenario"] == placement
        and row["cell"] == cell
        and row["metric"] == "e2e_otif_rate"
        and row["policy"] != "none"
    ]
    return max(rows, key=lambda row: row["mean"], default=None)


def _policy_label(policies: Sequence[Dict[str, str]], key: str) -> str:
    return next((row["label"] for row in policies if row["key"] == key), key)


def _pick_interpretation(results: Dict[str, Any]) -> List[str]:
    placements = results.get("placements", [])
    cells = results.get("cells", [])
    policies = results.get("policies", [])
    summary = results.get("summary", [])
    paired = results.get("paired", [])
    allocations = results.get("allocations", [])
    review = results.get("review_sweep_summary", [])
    move_summary = results.get("move_summary", [])
    if not placements or not cells or not summary:
        return []

    bound = {row["key"]: float(row["alloc_otif_rate"]) for row in allocations}
    points: List[str] = []
    base_cell = "base"
    if not any(cell["key"] == base_cell for cell in cells):
        base_cell = cells[0]["key"]
    base_label = next(
        (cell["label"] for cell in cells if cell["key"] == base_cell), base_cell
    )

    gains = {}
    for placement in placements:
        key = placement["key"]
        none = _summary_row(summary, key, base_cell, "none", "e2e_otif_rate")
        best = _best_policy(summary, key, base_cell)
        if none is None or best is None:
            continue
        gains[key] = {
            "none": none["mean"],
            "best": best,
            "gain": best["mean"] - none["mean"],
            "gap": bound.get(key, math.nan) - none["mean"],
        }
    if not gains:
        return points

    best_placement = max(gains, key=lambda key: gains[key]["gain"])
    info = gains[best_placement]
    best_policy = info["best"]
    label = _policy_label(policies, best_policy["policy"])
    pair = _paired_row(paired, best_placement, base_cell, best_policy["policy"])
    placement_label = next(
        (row["label"] for row in placements if row["key"] == best_placement),
        best_placement,
    )
    gap = info["gap"]
    closure = (
        info["gain"] / gap if gap > 0 else math.nan
    )
    points.append(
        f"**Mid-shift write-back recovers part of the pick-layer loss, not the "
        f"allocation loss.** At the deterministic baseline cell, "
        f"`{placement_label}` runs at {info['none']:.1%} end-to-end OTIF with no "
        f"write-back and at {best_policy['mean']:.1%} with `{label}` "
        f"({info['gain']:+.1%}); the allocation bound is "
        f"{bound.get(best_placement, float('nan')):.1%}, so the pick layer gives "
        f"up {gap:.1%} and `{label}` closes "
        + (
            f"{closure:.0%} of that loss."
            if not math.isnan(closure)
            else "an undefined share of that loss."
        )
        + (
            f" The paired win rate against no write-back is "
            f"{pair['win_rate']:.0%} across the shared seeds."
            if pair is not None
            else ""
        )
    )

    if len(gains) > 1:
        other = min(gains, key=lambda key: gains[key]["gain"])
        other_info = gains[other]
        other_label = next(
            (row["label"] for row in placements if row["key"] == other), other
        )
        if other != best_placement and abs(info["gain"] - other_info["gain"]) > 0.002:
            points.append(
                f"**Recovery needs a spare DC, so the gain depends on placement.** "
                f"`{other_label}` gains only {other_info['gain']:+.1%} from its "
                f"best policy ({_policy_label(policies, other_info['best']['policy'])}) "
                f"versus {info['gain']:+.1%} for `{placement_label}`. A split that "
                "loads one DC leaves queue slack elsewhere for moved tickets to "
                "use; a split that congests every DC gives the planner nowhere to "
                "send work."
            )

    two = next((cell for cell in cells if cell["key"] == "two_pickers"), None)
    if two is not None:
        rows = [
            _summary_row(summary, placement["key"], two["key"], "none", "e2e_otif_rate")
            for placement in placements
        ]
        gaps = [
            abs(row["mean"] - bound.get(placement["key"], math.nan))
            for placement, row in zip(placements, rows)
            if row is not None
        ]
        moves = [
            row["mean_moves"]
            for row in results.get("move_summary", [])
            if row["cell"] == two["key"]
        ]
        if gaps:
            text = (
                f"**Extra pick capacity does what write-back cannot.** With "
                f"{two['label']}, no-write-back already sits within "
                f"{max(gaps):.1%} of each allocation bound"
            )
            if moves:
                text += f" and the average policy moves {max(moves):.1f} tickets"
            text += (
                ". Rerouting shifts work between queues; it does not add picker "
                "minutes, so it is not a capacity substitute."
            )
            points.append(text)

    reroute = _summary_row(summary, best_placement, base_cell, "reroute", "e2e_otif_rate")
    oracle = _summary_row(summary, best_placement, base_cell, "oracle", "e2e_otif_rate")
    if reroute is not None and oracle is not None:
        diff = oracle["mean"] - reroute["mean"]
        points.append(
            f"**Knowing the realised late set adds little.** On `{placement_label}` "
            f"the oracle policy reaches {oracle['mean']:.1%} versus "
            f"{reroute['mean']:.1%} for projected-late rerouting "
            f"({diff:+.1%}). The binding constraint is the queue model and the "
            "available picker minutes at the target DC, not knowledge of which "
            "ticket will actually miss its cutoff."
        )

    if review:
        frame = pd.DataFrame(review)
        default_review = float(results.get("settings", {}).get("review_minute", 0.0))
        swept_minutes = [
            float(value)
            for value in frame["review_minute"].unique()
            if abs(float(value) - default_review) > 1e-9
        ]
        spreads = []
        for placement, block in frame.groupby("scenario", sort=False):
            if block["review_minute"].nunique() < 2:
                continue
            spreads.append(
                (
                    float(block["mean_otif"].max() - block["mean_otif"].min()),
                    placement,
                )
            )
        if not swept_minutes:
            points.append(
                "**No extra review minute was evaluated in this run.** The "
                "default review row is shown for reference; add "
                "`--review-sweep` values to compare timing."
            )
        elif not spreads:
            points.append(
                "**Review timing was not resolved by this sweep.** Every swept "
                "review minute produced the same mean end-to-end OTIF, so the "
                "choice of review time did not bind in this run."
            )
        else:
            spread, placement = max(spreads)
            block = frame[frame["scenario"] == placement]
            best = block.loc[block["mean_otif"].idxmax()]
            worst = block.loc[block["mean_otif"].idxmin()]
            placement_label = next(
                (row["label"] for row in placements if row["key"] == placement),
                placement,
            )
            if spread < 0.001:
                points.append(
                    f"**Review timing has no measurable effect here.** On "
                    f"`{placement_label}` every swept review minute lands within "
                    f"{spread:.1%} of the same mean end-to-end OTIF."
                )
            else:
                points.append(
                    f"**Review timing is a real trade-off.** On "
                    f"`{placement_label}`, {int(best['review_minute'])} min gives "
                    f"the highest mean end-to-end OTIF ({best['mean_otif']:.1%}) "
                    f"and {int(worst['review_minute'])} min the lowest "
                    f"({worst['mean_otif']:.1%}). An early review sees fewer locked "
                    "waves but decides under a longer projection horizon; a late "
                    "review knows more but has fewer movable tickets left."
                )

    if move_summary:
        frame = pd.DataFrame(move_summary)
        labels = {row["key"]: row["label"] for row in placements}
        reroute_rows = frame[
            (frame["policy"] == "reroute") & (frame["mean_moves"] > 0)
        ]
        balance_rows = frame[
            (frame["policy"] == "balance") & (frame["mean_moves"] > 0)
        ]
        if not reroute_rows.empty:
            row = reroute_rows.sort_values("mean_moves", ascending=False).iloc[0]
            points.append(
                f"**Write-back is small and targeted.** The busiest reroute cell "
                f"(`{labels.get(row['scenario'], row['scenario'])}` / "
                f"`{row['cell_label']}`) moves {row['mean_moves']:.1f} tickets per "
                f"shift on average, with €{row['mean_fee']:.0f} in transfer fees "
                f"and €{row['mean_transport_delta']:.0f} in transport delta per "
                "run. It is an operational adjustment, not a re-plan."
            )
        if not balance_rows.empty:
            row = balance_rows.sort_values("mean_moves", ascending=False).iloc[0]
            points.append(
                f"**Preemptive balancing moves much more work.** The busiest "
                f"balance cell (`{labels.get(row['scenario'], row['scenario'])}` / "
                f"`{row['cell_label']}`) moves {row['mean_moves']:.1f} tickets per "
                f"shift, {row['rescued_orders']} rescues and "
                f"{row['lost_orders']} losses in total across seeds. The extra "
                "moves buy earlier queue relief, but they also raise transfer cost "
                "and the risk of moving a ticket that would have made its cutoff."
            )

    points.append(
        "**Declared assumptions, not observed operations.** The review minute, "
        "transfer lead and fee, projection rule, cutoffs and pick-time model are "
        "assumptions. Moved tickets carry their stock on an internal transfer; "
        "replenishment, DC-to-DC transport scheduling, batching changes and "
        "picker rostering are outside the chain."
    )
    return points


def build_recovery_report(
    results: Dict[str, Any],
    title: str = "Mid-shift write-back under stock-placement imbalance (Week 12)",
    generated: Optional[str] = None,
) -> str:
    dataset = results.get("dataset", {})
    seeds = results.get("seeds", [])
    cells = results.get("cells", [])
    placements = results.get("placements", [])
    allocations = results.get("allocations", [])
    policies = results.get("policies", [])
    summary = results.get("summary", [])
    paired = results.get("paired", [])
    over_shift = results.get("over_shift", [])
    moves = results.get("move_summary", [])
    routes = results.get("move_routes", [])
    review = results.get("review_sweep_summary", [])
    dc_rows = results.get("dc_workload", [])
    settings = results.get("settings", {})
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
        f"stock placements: **{len(placements)}**; policies: **{len(policies)}**"
    )
    lines.append(
        f"- Review at **{settings.get('review_minute', '—')} min**, transfer lead "
        f"**{settings.get('transfer_lead', '—')} min**, fee "
        f"**€{settings.get('transfer_fee', '—')}/ticket**, minimum projected gain "
        f"**{settings.get('min_gain', '—')} min**"
    )
    lines.append(
        f"- Picking: **{dataset.get('pickers_per_dc', '—')} picker(s) per DC**, "
        f"wave cap **{dataset.get('max_orders', '—')} orders / "
        f"{dataset.get('max_lines', '—')} lines**, shift "
        f"**{dataset.get('shift_minutes', '—')} min**, EDF release"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines.append("| Item | Assumption | Note |")
    lines.append("|---|---|---|")
    lines.append(
        "| Review | phase 1 runs to the declared minute; waves already started are locked | "
        "Only pick tickets in not-yet-started waves are movable. |"
    )
    lines.append(
        "| Transfer | the ticket's stock moves to the target DC; target starts after review + lead | "
        "Target transit must still fit the customer promise; weekly capacity is checked. |"
    )
    lines.append(
        "| Projection | deterministic EDF replay of each DC's remaining queue | "
        "The planner sees planned minutes, not future noise. The oracle policy only "
        "knows the realised late set. |"
    )
    lines.append(
        "| Execution | phase 2 resamples pick durations with a shared seed | "
        "All policies share the same phase-2 draw, so differences isolate moves. |"
    )
    lines.append(
        "| Network | 3 DCs, declared transit days, DC stock and capacity | "
        "No replenishment, transfer transport schedule or demand shift. |"
    )
    lines.append("")

    lines += ["## Methods", ""]
    lines.append(
        "- **Phase split**: run the Week-8 online release from shift start to the "
        "review minute, lock every wave that has started, and keep the remaining "
        "tickets as the movable set."
    )
    lines.append(
        "- **Projection**: replay each DC's movable tickets with EDF from the "
        "review state, using deterministic wave minutes and the pickers' carry-over "
        "free times."
    )
    lines.append(
        "- **Policies**: `none` freezes the allocation but still replays phase 2; "
        "`reroute` moves projected-late tickets; `balance` moves any pending ticket "
        "whose projected end improves by at least the declared minimum; `oracle` "
        "uses the realised late set from phase 1 as its candidate list."
    )
    lines.append(
        "- **Choice rule**: for each candidate, estimate the target's completion "
        "from its free time, transfer arrival, cutoff-window workload and "
        "single-ticket minutes; require promise-feasible transit, weekly DC "
        "capacity, an on-time estimate for late candidates, and the minimum gain."
    )
    lines.append(
        "- **Replay**: resample arrivals per seed, run phase 1, apply each policy, "
        "replay phase 2 per DC and recompute end-to-end OTIF against the same "
        "allocation bound."
    )
    lines.append(
        "- **Statistics**: mean with a normal 95% interval, P10/P50/P90, "
        "worst-decile mean, paired policy deltas on shared seeds, and over-shift "
        "probability."
    )
    lines.append("")

    lines += [
        "## Stock placements",
        "",
        _md_table(_placement_table(placements, allocations, dcs)),
        "",
        "Each placement is re-solved through the same Week-11 allocation chain; the "
        "allocation bound is the ceiling that write-back cannot exceed.",
        "",
    ]

    lines += [
        "## Policy impact by stress cell",
        "",
        _md_table(_policy_table(placements, cells, policies, summary, paired)),
        "",
        "`Δ vs no write-back` is the paired mean difference on shared seeds; "
        "`win / tie / loss` counts seeds where the policy beats, matches or loses "
        "to `none`.",
        "",
    ]

    lines += [
        "## Execution risk",
        "",
        _md_table(_execution_table(placements, cells, policies, summary, over_shift)),
        "",
    ]

    lines += [
        "## Move behaviour",
        "",
        _md_table(_move_table(placements, cells, policies, moves)),
        "",
    ]
    if routes:
        lines += [
            "### Move directions",
            "",
            _md_table(_route_table(placements, routes)),
            "",
        ]

    if review:
        minutes = {float(row["review_minute"]) for row in review}
        default_minute = float(settings.get("review_minute", 120.0))
        note = (
            "The sweep reruns `reroute` at each review minute on the same seeds; "
            "the default review row is shown for reference."
            if any(abs(value - default_minute) > 1e-9 for value in minutes)
            else "No extra review minute was evaluated in this run; the default "
            "review row is shown for reference."
        )
        lines += [
            "## Review-timing sweep",
            "",
            _md_table(_review_table(placements, review, default_minute)),
            "",
            note,
            "",
        ]

    if dc_rows:
        lines += [
            "## Per-DC workload (seed 1, base cell)",
            "",
            _md_table(_dc_table(placements, dc_rows)),
            "",
            "The snapshot shows how write-back redistributes tickets and tardiness "
            "across DCs; it is not averaged over seeds.",
            "",
        ]

    lines += ["## Interpretation", ""]
    for index, point in enumerate(_pick_interpretation(results), 1):
        lines.append(f"{index}. {point}")
    lines.append("")

    lines += ["## Declared assumptions", ""]
    for item in results.get("declared_assumptions", []):
        lines.append(f"- {item}")
    lines.append("")

    lines += ["## Limitations", ""]
    lines.append(
        "- The projection is deterministic and the pick-time model is declared, "
        "not fitted. A queue estimator with safety buffers would change which "
        "tickets are moved."
    )
    lines.append(
        "- A moved ticket carries its stock on an internal transfer but is assumed "
        "to clear it within the declared lead time; replenishment, transfer "
        "transport capacity and handling congestion are outside the chain."
    )
    lines.append(
        "- Phase 2 is a replay, not a new allocation: the allocation bound, cutoffs "
        "and order set stay fixed, and moved tickets keep their original cutoffs."
    )
    lines.append(
        "- The review sweep reruns one policy on one cell per placement; it is a "
        "timing diagnostic, not a full cross-product of review × policy × stress."
    )
    lines.append(
        "- The normal 95% interval is an approximation, and policy comparisons are "
        "paired only within a placement and cell; placements are separate "
        "counterfactuals with different feasible allocations."
    )
    lines.append("")
    return "\n".join(lines)


def write_recovery_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Mid-shift write-back under stock-placement imbalance (Week 12)",
) -> Dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    markdown = build_recovery_report(results, title=title, generated=stamp)
    report_path = directory / "RECOVERY_REPORT.md"
    report_path.write_text(markdown, encoding="utf-8")

    payload = {"title": title, "generated": stamp, **_json_safe(results)}
    summary_path = directory / "recovery_summary.json"
    summary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report": report_path, "summary": summary_path}
