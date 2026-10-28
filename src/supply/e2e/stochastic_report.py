"""Markdown + JSON report for the Week-14 stochastic placement benchmark."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct


def _labels(placements: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    return {row["key"]: row["label"] for row in placements}


def _placement_table(
    placements: Sequence[Dict[str, Any]],
    predicted: Sequence[Dict[str, Any]],
    dcs: Sequence[str],
) -> pd.DataFrame:
    scores = {row["key"]: row for row in predicted}
    rows = []
    for placement in placements:
        score = scores.get(placement["key"], {})
        rows.append(
            {
                "Placement": placement["label"],
                "DC mix": " / ".join(
                    f"{name} {value:.0%}"
                    for name, value in zip(dcs, placement["stock_mix"])
                ),
                "Stock units": " / ".join(
                    f"{value:,}" for value in placement["stock_units"]
                ),
                "Peak pick (min)": _num(placement.get("peak_pick_minutes"), 0),
                "Peak / shift": _pct(placement.get("peak_vs_shift")),
                "Predicted E[unmet]": _pct(score.get("expected_unmet_rate")),
                "Predicted CVaR": _pct(score.get("cvar_unmet_rate")),
                "Note": placement.get("note", ""),
            }
        )
    return pd.DataFrame(rows)


def _scenario_table(
    scenarios: Dict[str, Any], dcs: Sequence[str]
) -> pd.DataFrame:
    rows = []
    for scenario in scenarios.get("scenarios", []):
        shares = scenario.get("serviceable_share", [])
        rows.append(
            {
                "Week": scenario["week"],
                "Weight": _pct(scenario["weight"]),
                "Raw units": f"{scenario['raw_units']:,}",
                "Scale": _num(scenario["scale"], 3),
                "Active SKUs": scenario["active_skus"],
                "History lines": scenario["history_lines"],
                **{
                    f"Serviceable {name}": _pct(value)
                    for name, value in zip(dcs, shares)
                },
            }
        )
    return pd.DataFrame(rows)


def _sweep_table(sweep: Sequence[Dict[str, Any]], dcs: Sequence[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "λ": _num(row["lambda"], 2),
                "DC mix": " / ".join(
                    f"{value:.0%}" for value in row["stock_mix"]
                ),
                "E[unmet]": _pct(row["expected_unmet_rate"]),
                "CVaR": _pct(row["cvar_unmet_rate"]),
                "Peak pick (min)": _num(row["peak_minutes"], 0),
                "Status": row["status"],
                "Solve (s)": _num(row["solve_seconds"], 1),
            }
            for row in sweep
        ]
    )


def _allocation_table(rows: Sequence[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Placement": row["label"],
                "Status": row["status"],
                "Unit fill": _pct(row["fill"]),
                "Fill range": f"{row['fill_min']:.0%}–{row['fill_max']:.0%}",
                "Tickets": row.get("tickets", "—"),
                "Allocation OTIF": _pct(row["alloc_otif_rate"]),
                "OTIF range": (
                    f"{row['alloc_otif_min']:.0%}–{row['alloc_otif_max']:.0%}"
                ),
                "Cost (€)": _num(row["alloc_cost"], 0),
                "Solve (s)": _num(row["solve_seconds"], 1),
                "reps": row.get("reps", "—"),
            }
            for row in rows
        ]
    )


def _distribution_table(
    rows: Sequence[Dict[str, Any]],
    labels: Dict[str, str],
) -> pd.DataFrame:
    picked = [
        row for row in rows if row["metric"] == "e2e_otif_rate"
    ]
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
                "Pick on-time CI": f"±{_pct(on_time['ci95'])}",
                "Tardy minutes": _num(late["mean"], 0),
                "Tardy P90": _num(late["p90"], 0),
                "Makespan": _num(span["mean"], 0),
                "Makespan P90": _num(span["p90"], 0),
                "Over-shift": _pct(over.get("over_shift_rate", 0.0)),
            }
        )
    return pd.DataFrame(output)


def _paired_table(
    paired: Sequence[Dict[str, Any]],
    labels: Dict[str, str],
) -> pd.DataFrame:
    rows = [
        row
        for row in paired
        if row.get("metric") == "e2e_otif_rate" and row.get("cell") == "base"
    ]
    return pd.DataFrame(
        [
            {
                "Comparison": row["comparison"],
                "Δ OTIF": f"{row['mean_delta']:+.2%}",
                "95% CI": f"±{_pct(row['ci95'])}",
                "Win": _pct(row["win_rate"]),
                "Loss": _pct(row["loss_rate"]),
                "Tie": _pct(row["tie_rate"]),
                "n": row["n"],
            }
            for row in rows
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


def _by_key(rows: Sequence[Dict[str, Any]], key: str = "key") -> Dict[str, Dict[str, Any]]:
    return {str(row[key]): row for row in rows}


def _summary_row(
    rows: Sequence[Dict[str, Any]],
    scenario: str,
    cell: str = "base",
    metric: str = "e2e_otif_rate",
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if (
            row.get("metric") == metric
            and row.get("scenario") == scenario
            and row.get("cell") == cell
        ):
            return row
    return None


def _paired_row(
    rows: Sequence[Dict[str, Any]], left: str, right: str, cell: str = "base"
) -> Optional[Dict[str, Any]]:
    for row in rows:
        if (
            row.get("metric") == "e2e_otif_rate"
            and row.get("left") == left
            and row.get("right") == right
            and row.get("cell") == cell
        ):
            return row
    return None


def _shift(placements: Sequence[Dict[str, Any]], key: str) -> float:
    for row in placements:
        if row.get("key") == key:
            return float(row.get("peak_vs_shift", 0.0))
    return 0.0


def _interpretation(results: Dict[str, Any]) -> List[str]:
    summary = results.get("summary", [])
    placements = results.get("placements", [])
    predicted = _by_key(results.get("predicted", []))
    allocations = _by_key(results.get("allocations", []))
    sweep = results.get("sweep", [])
    paired = results.get("paired", [])
    reps = int(results.get("reps", 1) or 1)
    stock_gap = 1.0 - float(
        (results.get("settings") or {}).get("stock_factor", 0.85)
    )
    points: List[str] = []
    sweep_flat = True

    declared = predicted.get("declared", {})
    expected = predicted.get("stochastic_expected", {})
    capped = predicted.get("destination_capped", {})
    destination = predicted.get("destination", {})

    declared_peak = _shift(placements, "declared")
    expected_peak = _shift(placements, "stochastic_expected")
    dest_peak = _shift(placements, "destination")
    capped_peak = _shift(placements, "destination_capped")
    peak_binds = max(declared_peak, expected_peak) > 1.0

    if declared and expected:
        gap = expected["expected_unmet_rate"] - declared["expected_unmet_rate"]
        if abs(gap) < 0.005:
            capacity_note = (
                "The stock-based peak also exceeds one shift: the busiest DC "
                f"holds {max(declared_peak, expected_peak):.0%} of a shift's "
                "pick minutes if all of its stock ships, so part of the shortfall "
                "is execution, not only stock."
                if peak_binds
                else "Pick minutes stay below one shift for both plans, so the "
                f"shortfall comes from the {stock_gap:.0%} stock-coverage gap and "
                "DC-level serviceability."
            )
            points.append(
                "**The fluid model cannot separate the declared split from the "
                "scenario plan.** Predicted unmet is "
                f"{declared['expected_unmet_rate']:.1%} for `declared` and "
                f"{expected['expected_unmet_rate']:.1%} for λ=0 ({gap:+.1%}). "
                f"{capacity_note} With per-SKU totals fixed, most of the "
                "shortfall is common to every placement; the placement is then "
                "chosen by the cover and peak-minute tie-break, not by the "
                "service objective."
            )
        elif gap < 0:
            points.append(
                "**The scenario plan lowers predicted unmet.** Expected unmet "
                f"falls from {declared['expected_unmet_rate']:.1%} under the "
                f"declared split to {expected['expected_unmet_rate']:.1%} "
                f"({gap:+.1%}); the second stage re-optimises each prior week on "
                "the chosen placement."
            )
        else:
            points.append(
                "**The scenario plan does not beat the declared split on "
                f"predicted service.** Expected unmet is "
                f"{expected['expected_unmet_rate']:.1%} versus "
                f"{declared['expected_unmet_rate']:.1%} ({gap:+.1%}); the "
                "second stage cannot find a better fluid plan for the prior weeks, "
                "so the placement is decided by the tie-break."
            )

    if declared and capped:
        gap = capped["expected_unmet_rate"] - declared["expected_unmet_rate"]
        if gap > 0.02:
            uncapped = destination.get("expected_unmet_rate")
            uncapped_text = f"{uncapped:.1%}" if uncapped is not None else "—"
            points.append(
                "**Capacity-blind demand history strands pick capacity.** The "
                f"uncapped destination mix predicts {uncapped_text} "
                "unmet; clipping it to DC throughput improves that to "
                f"{capped['expected_unmet_rate']:.1%}, still {gap:+.1%} worse "
                f"than the declared split ({declared['expected_unmet_rate']:.1%}). "
                "History says where demand was, not where one shift can pick it."
            )
        elif gap < -0.02:
            points.append(
                "**Capping demand history beats the declared split on the "
                "scenario set.** The capped mix predicts "
                f"{capped['expected_unmet_rate']:.1%} unmet versus "
                f"{declared['expected_unmet_rate']:.1%} for the declared split "
                f"({gap:+.1%}); prior-week destinations plus a throughput cap "
                "already encode where the demand and the pick capacity are."
            )
        else:
            points.append(
                "**Capping demand history is not enough on its own.** The capped "
                f"mix predicts {capped['expected_unmet_rate']:.1%} unmet versus "
                f"{declared['expected_unmet_rate']:.1%} for the declared split "
                f"({gap:+.1%}); the fluid score gives credit for unit coverage, "
                "so it cannot see where each SKU's stock has to sit to be pickable."
            )

    if sweep:
        e_values = [row["expected_unmet_rate"] for row in sweep]
        c_values = [row["cvar_unmet_rate"] for row in sweep]
        e_spread = max(e_values) - min(e_values)
        c_spread = max(c_values) - min(c_values)
        spread = max(e_spread, c_spread)
        sweep_flat = spread < 0.005
        mixes = {
            tuple(round(float(value), 4) for value in row["stock_mix"])
            for row in sweep
        }
        lam_lo = min(row["lambda"] for row in sweep)
        lam_hi = max(row["lambda"] for row in sweep)
        if spread < 0.005 and len(mixes) == 1:
            points.append(
                "**CVaR weight does not move the decision on this scenario set.** "
                f"Across λ∈[{lam_lo:.2f}, {lam_hi:.2f}], predicted E[unmet] and "
                f"CVaR vary by at most {spread:.2%} and every λ selects the same "
                "DC mix. The prior weeks share the same shortfall pattern, so the "
                "upper tail is nearly the same number as the mean; CVaR is a "
                "capability here, not a source of gain."
            )
        elif spread < 0.005:
            points.append(
                "**CVaR weight is not identified on this scenario set.** "
                f"Across λ∈[{lam_lo:.2f}, {lam_hi:.2f}], predicted E[unmet] and "
                f"CVaR vary by at most {spread:.2%}, yet the selected DC mix "
                "changes; the objective is nearly flat, so the solver's "
                "cover and peak-minute tie-break decides the placement."
            )
        else:
            points.append(
                "**CVaR weight changes the predicted risk.** Predicted E[unmet] "
                f"or CVaR spans {spread:.1%} across λ∈[{lam_lo:.2f}, "
                f"{lam_hi:.2f}], with "
                + ("a different DC mix at each λ; the risk-averse end trades "
                   "expected service for a lighter tail."
                   if len(mixes) > 1
                   else "the same DC mix throughout; the risk term re-scores a "
                   "placement the service objective already selected.")
            )

    if declared and expected:
        if dest_peak > 1.0:
            points.append(
                "**Demand history ignores pick capacity.** The uncapped "
                f"destination mix puts {dest_peak:.0%} of one shift's pick "
                f"minutes in the busiest DC; capping it to throughput reduces "
                f"that to {capped_peak:.0%}, while the declared split is at "
                f"{declared_peak:.0%} and the scenario plan at {expected_peak:.0%}. "
                "Stock that exceeds a DC's shift cannot be picked before the "
                "cutoff, so a capacity-blind history is not a deployable plan."
            )
        elif peak_binds:
            points.append(
                "**Peak pick load exceeds one shift for every placement.** The "
                f"busiest DC holds {declared_peak:.0%} of a shift's pick minutes "
                f"under the declared split and {expected_peak:.0%} under the "
                "scenario plan; the pick layer, not the allocation LP, decides "
                "how much of the predicted service survives."
            )
        else:
            points.append(
                "**Pick load does not bind at this order volume.** The busiest "
                f"DC holds {declared_peak:.0%} of a shift's pick minutes under "
                f"the declared split and {expected_peak:.0%} under the scenario "
                "plan, so the predicted shortfall is driven by per-SKU stock and "
                "DC-level serviceability, not by pick capacity."
            )

    base_declared = _summary_row(summary, "declared")
    base_expected = _summary_row(summary, "stochastic_expected")
    base_cvar = _summary_row(summary, "stochastic_cvar")
    pick_declared = _summary_row(
        summary, "declared", metric="pick_on_time_rate"
    )
    pick_expected = _summary_row(
        summary, "stochastic_expected", metric="pick_on_time_rate"
    )
    if base_declared and base_expected:
        delta = base_expected["mean"] - base_declared["mean"]
        pair = _paired_row(paired, "declared", "stochastic_expected")
        resolved = (
            pair is not None
            and pair["ci95"] > 0
            and abs(pair["mean_delta"]) > pair["ci95"]
        )
        if resolved and delta > 0:
            exec_note = (
                f" Pick on-time moves from {pick_declared['mean']:.1%} to "
                f"{pick_expected['mean']:.1%}."
                if pick_declared and pick_expected
                else ""
            )
            if expected_peak < declared_peak:
                why = (
                    "the scenario plan also lowers the busiest DC from "
                    f"{declared_peak:.0%} to {expected_peak:.0%} of a shift, "
                    "consistent with a gain from execution balance."
                )
            else:
                why = (
                    "the scenario plan does not lower the peak load "
                    f"({expected_peak:.0%} vs {declared_peak:.0%}), so the gain "
                    "comes from which DC holds each SKU rather than from total "
                    "pick load."
                )
            points.append(
                "**The scenario placement wins the out-of-sample week.** At the "
                f"deterministic baseline cell it reaches {base_expected['mean']:.1%} "
                f"end-to-end OTIF versus {base_declared['mean']:.1%} for the "
                f"declared split ({delta:+.1%}); the paired 95% interval excludes "
                f"zero. The fluid objective called the two placements equal, so "
                f"{why}{exec_note}"
            )
        elif resolved and delta < 0:
            points.append(
                "**Execution does not reward the scenario placement on this "
                f"week.** It reaches {base_expected['mean']:.1%} versus "
                f"{base_declared['mean']:.1%} for the declared split "
                f"({delta:+.1%}), and the paired interval excludes zero. A "
                "service-equivalent fluid plan can still lose once order-level "
                "serviceability and cutoff timing enter."
            )
        else:
            if pair is not None and pair["ci95"] <= 0:
                resolution = (
                    "the paired interval is degenerate because every replay is "
                    "identical, so it cannot establish significance"
                )
            else:
                resolution = "the paired interval includes zero"
            points.append(
                "**The realized difference is not resolved by the paired "
                f"interval.** The baseline cell shows {base_expected['mean']:.1%} "
                f"for the scenario plan and {base_declared['mean']:.1%} for the "
                f"declared split ({delta:+.1%}) with n={base_expected['n']} and "
                f"±{_pct((pair or {}).get('ci95', 0.0))}; {resolution}. The "
                "allocation LP is time-limited and re-run per replicate, so read "
                "small placement differences against that spread."
            )

    if base_cvar and base_expected:
        delta = base_cvar["mean"] - base_expected["mean"]
        pair = _paired_row(paired, "stochastic_expected", "stochastic_cvar")
        resolved = (
            pair is not None
            and pair["ci95"] > 0
            and abs(pair["mean_delta"]) > pair["ci95"]
        )
        if resolved and delta > 0:
            attribution = (
                "The predicted objective was flat, so this reflects how the risk "
                "weight redistributes SKUs across DCs, not a better forecast."
                if sweep_flat
                else "The predicted risk also moved across the sweep, so the risk "
                "weight is acting as intended."
            )
            points.append(
                "**The CVaR placement improves realized OTIF.** λ=0.5 reaches "
                f"{base_cvar['mean']:.1%} versus {base_expected['mean']:.1%} for "
                f"λ=0 ({delta:+.1%}); the paired interval excludes zero. "
                f"{attribution}"
            )
        elif resolved and delta < 0:
            attribution = (
                "The predicted objective was flat, so the risk weight changed the "
                "placement without improving the forecast."
                if sweep_flat
                else "The predicted risk moved across the sweep, yet the realized "
                "gain did not follow."
            )
            points.append(
                "**The CVaR placement lowers realized OTIF on this week.** λ=0.5 "
                f"reaches {base_cvar['mean']:.1%} versus {base_expected['mean']:.1%} "
                f"for λ=0 ({delta:+.1%}); the paired interval excludes zero. "
                f"{attribution}"
            )
        else:
            if pair is not None and pair["ci95"] <= 0:
                resolution = (
                    "the paired interval is degenerate because every replay is "
                    "identical"
                )
            else:
                resolution = "the paired interval includes zero"
            attribution = (
                "The predicted objective was also flat, so the CVaR term did not "
                "change the decision."
                if sweep_flat
                else "The predicted risk moved across the sweep, but the realized "
                "difference is not resolved."
            )
            points.append(
                "**λ=0 and λ=0.5 are indistinguishable at the reported "
                f"precision.** They reach {base_expected['mean']:.1%} and "
                f"{base_cvar['mean']:.1%} ({delta:+.1%}); {resolution}. "
                f"{attribution}"
            )

    if declared and allocations.get("declared"):
        alloc = allocations["declared"]
        pred_service = 1.0 - declared["expected_unmet_rate"]
        e2e_note = (
            f"only {base_declared['mean']:.1%} reach end-to-end OTIF once wave "
            "batching and cutoff timing are simulated"
            if base_declared
            else "the end-to-end figure is lower once wave batching and cutoff "
            "timing are simulated"
        )
        points.append(
            "**The fluid score tracks unit fill, not end-to-end OTIF.** For "
            f"`declared`, predicted service is {pred_service:.1%}, the Week-9 "
            f"MILP fills {alloc['fill']:.1%} of units and {alloc['alloc_otif_rate']:.1%} "
            f"of orders meet the allocation OTIF, but {e2e_note}. Read the "
            "placement model as a unit-service proxy, not as an OTIF forecast."
        )

    ranges = []
    for key in ("declared", "destination_capped", "stochastic_expected", "stochastic_cvar"):
        row = allocations.get(key)
        if row:
            ranges.append(
                (row["label"], row["alloc_otif_max"] - row["alloc_otif_min"])
            )
    if ranges:
        widest = max(ranges, key=lambda item: item[1])
        dest_row = allocations.get("destination")
        dest_range = (
            dest_row["alloc_otif_max"] - dest_row["alloc_otif_min"]
            if dest_row
            else 0.0
        )
        dest_note = (
            " The capacity-blind destination baseline is noisier still at "
            f"{dest_range:.1%}."
            if dest_range > widest[1]
            else ""
        )
        if reps < 2:
            points.append(
                "**Each placement has a single allocation solve.** The OTIF "
                "range column is zero by construction, so it cannot separate "
                "placement quality from solver noise; the realized placement "
                "gaps below come from one MILP draw per placement."
            )
        elif widest[1] >= 0.02:
            points.append(
                "**Allocation solver noise is material.** Across "
                f"{reps} replicates the allocation-OTIF range is widest for "
                f"`{widest[0]}` at {widest[1]:.1%}.{dest_note} Placement "
                "comparisons use the pooled mean over replicates; a single solve "
                "is not a stable estimate."
            )
        else:
            points.append(
                "**Allocation solver noise is bounded below the placement "
                f"effects.** Across {reps} replicates the widest allocation-OTIF "
                f"range is {widest[1]:.1%} for `{widest[0]}`{dest_note}, so the "
                "placement differences below are not driven by a single solver "
                "draw."
            )

    lookback = int((results.get("settings") or {}).get("lookback_weeks", 6) or 6)
    points.append(
        "**This is one target week, not a forecast evaluation.** The scenario "
        "set uses only prior weeks and the stock totals are deployable, but the "
        "out-of-sample result is a single draw. The "
        f"{lookback}-week set is too short to estimate tail probabilities "
        "precisely."
    )
    return points


def build_stochastic_report(
    results: Dict[str, Any],
    title: str = "Uncertainty-aware stock placement (Week 14)",
    generated: Optional[str] = None,
) -> str:
    dataset = results.get("dataset", {})
    seeds = results.get("seeds", [])
    reps = results.get("reps", 1)
    settings = results.get("settings", {})
    scenario_set = results.get("scenarios", {})
    stock_plan = results.get("stock_plan", {})
    pick = results.get("pick_proxy", {})
    placements = results.get("placements", [])
    predicted = results.get("predicted", [])
    sweep = results.get("sweep", [])
    allocations = results.get("allocations", [])
    summary = results.get("summary", [])
    over_shift = results.get("over_shift", [])
    paired = results.get("paired", [])
    dc_rows = results.get("dc_workload", [])
    cells = results.get("cells", [])
    dcs = dataset.get("dcs", [])
    labels = _labels(placements)
    stamp = generated or datetime.now(timezone.utc).isoformat()

    lines: List[str] = [f"# {title}", ""]
    lines.append(f"- Generated: `{stamp}`")
    lines.append(
        f"- Orders: **{dataset.get('orders', '—')}** real invoices / "
        f"**{dataset.get('lines', '—')}** lines / "
        f"**{dataset.get('units', '—')}** units, week {dataset.get('week', '—')}"
    )
    weeks = scenario_set.get("weeks") or ["—"]
    lines.append(
        f"- Scenarios: **{len(scenario_set.get('weeks', []))}** prior weeks "
        f"({weeks[0]}..{weeks[-1]}) | stock "
        f"**{stock_plan.get('stock_units', '—')}** units "
        f"({_pct(stock_plan.get('coverage'))}) from the scenario mean"
    )
    lines.append(
        f"- Seeds per cell: **{len(seeds)}** × **{reps}** allocation "
        f"replicate(s); stress cells: **{len(cells)}**; placements: "
        f"**{len(placements)}**"
    )
    lines.append(
        f"- Picking: **{dataset.get('pickers_per_dc', '—')} picker(s) per DC**, "
        f"shift **{dataset.get('shift_minutes', '—')} min**, wave cap "
        f"**{dataset.get('max_orders', '—')} orders / "
        f"{dataset.get('max_lines', '—')} lines**"
    )
    if pick:
        lines.append(
            f"- Pick proxy: **{pick.get('minutes_per_unit', 0):.5f} min/unit** "
            f"(order route + line/unit handling + wave setup + "
            f"{pick.get('congestion_margin', 0):.0%} congestion), "
            f"**{pick.get('capacity_per_dc', 0):.0f} min** per DC per shift"
        )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines.append("| Item | Assumption | Note |")
    lines.append("|---|---|---|")
    lines.append(
        "| Stock totals | scenario mean × "
        f"{settings.get('stock_factor', 0):.0%} | "
        "Per-SKU totals come from the prior weeks, not the target week; only the "
        "DC location is optimized. |"
    )
    lines.append(
        "| Scenario weights | equal | Each prior week is one draw; no fitted "
        "seasonality or forecast model is used. |"
    )
    lines.append(
        "| Scenario volume | rescaled to the target week's units | "
        "Weekly volume is treated as known; the SKU × destination mix is not. |"
    )
    lines.append(
        "| Serviceability | promise mix 30/50/20 and declared transit days | "
        "A unit is serviceable from a DC when its transit fits the promise; "
        "this is an assumption layer, not observed carrier data. |"
    )
    lines.append(
        "| Pick budget | linear minutes per DC per scenario | "
        "Order route + line/unit handling + wave setup + 20% congestion; it is "
        "not a wave or cutoff simulation. |"
    )
    lines.append(
        "| Risk | "
        f"E[unmet] and CVaR α={settings.get('cvar_alpha', 0):.2f} | "
        "CVaR uses the Uryasev variables and empirical interpolation; the "
        "default weight is "
        f"{settings.get('cvar_weight', 0):.2f}. |"
    )
    lines.append(
        "| Allocation | Week-9 two-stage MILP, time-limited FEASIBLE | "
        f"{settings.get('service_time', 0):.0f} s service + "
        f"{settings.get('milp_time', 0):.0f} s load-aware, repeated "
        f"{reps}× per placement. |"
    )
    lines.append("")

    lines += ["## Methods", ""]
    lines.append(
        "- **Scenario construction**: the last "
        f"{settings.get('lookback_weeks', '—')} complete weeks before the target "
        "week, restricted to the instance's SKUs and countries, aggregated by "
        "week × SKU × country, then rescaled so each week has the target week's "
        "total units."
    )
    lines.append(
        "- **Serviceable demand**: each scenario's units are split by declared "
        "promise tier; a DC can serve a unit when its declared transit fits that "
        "tier. The matrix is per scenario, SKU and DC."
    )
    lines.append(
        "- **First stage**: one integer stock placement with each SKU's total "
        "fixed to the scenario-mean level. A small tie-break rewards placing a "
        "SKU where prior weeks could serve it and lowers the global peak "
        "pick-minute load; the service coefficient is 6×10^5 times larger, so "
        "these terms only decide among service-equivalent placements."
    )
    lines.append(
        "- **Second stage**: a fluid allocation per scenario, bounded by the "
        "placement, serviceable demand, per-DC weekly throughput and the linear "
        "pick-minute budget. Unmet units close each SKU balance."
    )
    lines.append(
        "- **Risk objective**: "
        "`(1-λ)·E[unmet] + λ·CVaR_α(unmet)`, with λ swept; the reported "
        f"placement uses λ={settings.get('cvar_weight', 0.5):.2f} unless noted."
    )
    lines.append(
        "- **Out-of-sample evaluation**: every placement is allocated by the "
        "Week-9 capacity-aware MILP and replayed through the Week-10 Monte "
        "Carlo. Allocation is repeated to separate placement from solver noise."
    )
    lines.append("")

    if scenario_set.get("scenarios"):
        lines += ["## Demand scenarios", ""]
        lines.append(
            f"Target volume **{scenario_set.get('target_units', 0):,}** units; "
            "each prior week is rescaled to it. `Serviceable` is the share of "
            "that week's units each DC can deliver inside the declared promise "
            "mix."
        )
        lines.append("")
        lines.append(_md_table(_scenario_table(scenario_set, dcs)))
        lines.append("")

    if placements:
        lines += ["## Stock placements", ""]
        lines.append(_md_table(_placement_table(placements, predicted, dcs)))
        lines.append("")
        lines.append(
            "`Peak pick` is the stock units in the busiest DC times the linear "
            "pick-minute coefficient; `Peak / shift` above 100% means that DC "
            "holds more work than one picker can start inside the shift."
        )
        lines.append("")

    if predicted:
        lines += ["## Predicted service", ""]
        rows = []
        for row in predicted:
            values = row.get("scenario_unmet_rate", [])
            rows.append(
                {
                    "Placement": row["label"],
                    "E[unmet]": _pct(row.get("expected_unmet_rate")),
                    "CVaR": _pct(row.get("cvar_unmet_rate")),
                    "Worst scenario": _pct(max(values)) if values else "—",
                    "Best scenario": _pct(min(values)) if values else "—",
                    "Status": row.get("status", "—"),
                }
            )
        lines.append(_md_table(pd.DataFrame(rows)))
        lines.append("")
        if predicted:
            spread = [
                (max(values) - min(values)) if values else float("nan")
                for values in (
                    row.get("scenario_unmet_rate", []) for row in predicted
                )
            ]
            lines.append(
                "Scenario-to-scenario spread of unserved units: "
                + " / ".join(
                    f"{row['label']} {value:.1%}"
                    for row, value in zip(predicted, spread)
                )
                + "."
            )
            lines.append("")
            lines.append(
                "These are fluid unit-service scores over the prior-week "
                "scenarios, not end-to-end OTIF forecasts; the allocation and "
                "execution sections below evaluate each placement separately."
            )
            lines.append("")

    if sweep:
        lines += ["## CVaR weight sweep", ""]
        lines.append(_md_table(_sweep_table(sweep, dcs)))
        lines.append("")

    if allocations:
        lines += ["## Allocation outcomes", ""]
        lines.append(_md_table(_allocation_table(allocations)))
        lines.append("")
        lines.append(
            "`OTIF range` is the spread across allocation replicates on the same "
            "placement; `Cost` is the mean reported fulfillment cost. Allocation "
            "OTIF covers shipping inside the promise but not pick-cutoff risk; the "
            "end-to-end table adds wave batching and cutoff timing."
        )
        lines.append("")

    if summary:
        lines += ["## End-to-end OTIF distribution", ""]
        lines.append(_md_table(_distribution_table(summary, labels)))
        lines.append("")

    if summary:
        lines += ["## Execution risk", ""]
        lines.append(_md_table(_execution_table(summary, over_shift, labels)))
        lines.append("")

    if paired:
        lines += ["## Placement differences", ""]
        lines.append(_md_table(_paired_table(paired, labels)))
        lines.append("")
        lines.append(
            "Differences are `right − left` on shared arrival seeds and "
            "replicate indices; the interval is the normal approximation over "
            "pooled runs."
        )
        lines.append("")

    if dc_rows:
        lines += ["## Per-DC workload (replicate 1, seed 1)", ""]
        lines.append(_md_table(_dc_table(dc_rows, labels)))
        lines.append("")

    lines += ["## Interpretation", ""]
    for point in _interpretation(results):
        lines.append(f"- {point}")
    lines.append("")

    lines += ["## Declared assumptions", ""]
    assumptions = results.get("declared_assumptions", [])
    if assumptions:
        for item in assumptions:
            lines.append(f"- {item}")
    else:
        lines.append("- _(none recorded)_")
    lines.append("")

    lines += ["## Limitations", ""]
    lines.append(
        f"- The scenario set has {settings.get('lookback_weeks', 6)} weeks. CVaR "
        "and the upper tail are estimated from that many observations; the "
        "interpolation is coarse."
    )
    lines.append(
        "- The second stage is fluid: it has no order identity, wave batching, "
        "cutoff timing, or travel sequence. The pick-minute budget is a linear "
        "proxy calibrated to the Week-9 labor model, not a simulation."
    )
    lines.append(
        "- The objective is unserved units only. Transport cost, handling cost "
        "and the fixed cost of opening a DC are not in the placement model, so "
        "the result is a service frontier, not a profit-maximizing plan."
    )
    lines.append(
        "- Serviceability uses declared transit days and the 30/50/20 promise "
        "mix. A different carrier network or premium promise share can change "
        "which DC is valuable."
    )
    lines.append(
        "- Allocation is time-limited and solver-dependent. The replicate spread "
        "is reported, but it is not a formal confidence interval for the MILP "
        "optimum."
    )
    lines.append(
        "- One target week is one draw. The report separates predicted scenario "
        "service from realized OTIF, but does not claim a forecast improvement "
        "over Week-13 hindsight."
    )
    lines.append("")

    return "\n".join(lines)


def write_stochastic_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Uncertainty-aware stock placement (Week 14)",
    stem: str = "STOCHASTIC_PLACEMENT_REPORT",
) -> Dict[str, Path]:
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / f"{stem}.md"
    summary = directory / "stochastic_placement_summary.json"
    report.write_text(
        build_stochastic_report(results, title=title), encoding="utf-8"
    )
    payload = {
        "title": title,
        "dataset": results.get("dataset", {}),
        "seeds": results.get("seeds", []),
        "reps": results.get("reps", 1),
        "settings": results.get("settings", {}),
        "scenarios": results.get("scenarios", {}),
        "stock_plan": results.get("stock_plan", {}),
        "pick_proxy": results.get("pick_proxy", {}),
        "placements": results.get("placements", []),
        "predicted": results.get("predicted", []),
        "sweep": results.get("sweep", []),
        "allocations": results.get("allocations", []),
        "cells": results.get("cells", []),
        "summary": results.get("summary", []),
        "over_shift": results.get("over_shift", []),
        "paired": results.get("paired", []),
        "dc_workload": results.get("dc_workload", []),
        "declared_assumptions": results.get("declared_assumptions", []),
    }
    summary.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": report, "summary": summary}
