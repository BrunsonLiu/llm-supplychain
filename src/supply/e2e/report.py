"""Markdown + JSON report for the end-to-end allocation -> picking chain."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from supply.wave.schedule_report import _json_safe, _md_table, _num, _pct


def _scenario_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "方案": row["name"],
                "分单状态": row.get("pick_status", "—"),
                "订单填满": _pct(row["order_fill_rate"]),
                "分单 OTIF": _pct(row["alloc_otif_rate"]),
                "端到端 OTIF": _pct(row["e2e_otif_rate"]),
                "拣选准时": _pct(row["pick_on_time_rate"]),
                "拣选丢失单": row["pick_loss_orders"],
                "票据": row["tickets"],
                "波次": row["waves"],
                "单票工时": _num(row["labor_per_ticket"], 2),
                "最长完工": _num(row["pick_makespan"], 0),
                "分单成本": _num(row["alloc_cost"], 0),
                "拣选成本": _num(row["labor_cost"], 0),
                "总成本": _num(row["total_cost"], 0),
                "求解 (s)": _num(row.get("solve_seconds"), 2),
            }
            for row in rows
        ]
    )


def _dc_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "DC": row["dc"],
                "票据": row["tickets"],
                "订单": row["orders"],
                "波次": row["waves"],
                "工时 (min)": _num(row["labor_minutes"], 1),
                "单票工时": _num(row["labor_per_ticket"], 2),
                "准时票据": row["on_time_tickets"],
                "迟到票据": row["tardy_tickets"],
                "迟到分钟": _num(row["tardiness_minutes"], 0),
                "最长完工": _num(row["makespan"], 0),
                "空闲分钟": _num(row["idle_minutes"], 0),
            }
            for row in rows
        ]
    )


def _release_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "释放策略": row["name"],
                "波次": row["waves"],
                "票据": row["tickets"],
                "单票工时": _num(row["labor_per_ticket"], 2),
                "拣选准时": _pct(row["pick_on_time_rate"]),
                "迟到票据": row["pick_tardy_tickets"],
                "迟到分钟": _num(row["pick_tardiness"], 0),
                "最长完工": _num(row["pick_makespan"], 0),
                "端到端 OTIF": _pct(row["e2e_otif_rate"]),
                "总成本": _num(row["total_cost"], 0),
            }
            for row in rows
        ]
    )


def _picker_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "每 DC 拣货员": row["pickers_per_dc"],
                "分单 OTIF": _pct(row["alloc_otif_rate"]),
                "拣选准时": _pct(row["pick_on_time_rate"]),
                "端到端 OTIF": _pct(row["e2e_otif_rate"]),
                "拣选丢失单": row["pick_loss_orders"],
                "波次": row["waves"],
                "单票工时": _num(row["labor_per_ticket"], 2),
                "最长完工": _num(row["pick_makespan"], 0),
                "拣选工时": _num(row["pick_labor_minutes"], 1),
            }
            for row in rows
        ]
    )


def _by_key(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(row.get("key")): row for row in rows}


def _pick_interpretation(
    scenarios: List[Dict[str, Any]],
    release: List[Dict[str, Any]],
    pickers: List[Dict[str, Any]],
) -> List[str]:
    points: List[str] = []
    rows = _by_key(scenarios)
    greedy = rows.get("greedy")
    load = rows.get("milp_load") or rows.get("milp_service")
    cost = rows.get("milp_cost")

    if greedy and load and cost:
        delta_otif = load["e2e_otif_rate"] - greedy["e2e_otif_rate"]
        delta_cost = load["total_cost"] - greedy["total_cost"]
        cost_gap = cost["total_cost"] - load["total_cost"]
        cost_otif = cost["e2e_otif_rate"] - load["e2e_otif_rate"]
        movement = "cuts" if delta_cost <= 0 else "adds"
        against = "less" if cost_otif <= 0 else "more"
        points.append(
            f"**The load-aware plan moves both axes against greedy, but the pure cost "
            f"model does not dominate it.** Load-aware allocation changes end-to-end OTIF "
            f"by {delta_otif * 100:+.1f} percentage points and {movement} "
            f"€{abs(delta_cost):,.0f} in total cost relative to greedy. The cost MILP "
            f"lands at €{cost['total_cost']:,.0f} against €{load['total_cost']:,.0f} for "
            f"the load plan, with {abs(cost_otif) * 100:.1f} percentage points {against} "
            f"end-to-end OTIF. At this time limit both MILP plans are `FEASIBLE`, not "
            f"proven optima, so the cost ranking between them is indicative."
        )

    if load:
        loss = load["pick_loss_orders"]
        if loss == 0:
            points.append(
                f"**The pick layer is not the constraint at this load.** All "
                f"{load['tickets']} tickets clear their cutoff, so end-to-end OTIF equals "
                f"allocation OTIF at {load['e2e_otif_rate']:.1%}; every lost order is lost "
                f"upstream in stock, promise or split limits, not inside the warehouse."
            )
        else:
            points.append(
                f"**Allocation OTIF is an upper bound on end-to-end OTIF.** Under the "
                f"load-aware plan {load['alloc_otif_rate']:.1%} of orders are fully "
                f"shipped on time, but only {load['e2e_otif_rate']:.1%} also clear their "
                f"pick cutoff: {loss} orders are lost inside the warehouse, with "
                f"{load['pick_tardy_tickets']} of {load['tickets']} tickets finishing late "
                f"(max {_num(load['pick_max_late'], 0)} min)."
            )

    release_rows = _by_key(release)
    single = release_rows.get("single")
    edf = release_rows.get("edf")
    if single and edf:
        saved = single["pick_labor_minutes"] - edf["pick_labor_minutes"]
        saved_share = saved / single["pick_labor_minutes"] if single["pick_labor_minutes"] else 0.0
        if abs(edf["e2e_otif_rate"] - single["e2e_otif_rate"]) <= 1e-9:
            service = (
                f"End-to-end OTIF is unchanged at {edf['e2e_otif_rate']:.1%} because "
                f"picking is not binding at this load."
            )
        else:
            service = (
                f"End-to-end OTIF moves from {single['e2e_otif_rate']:.1%} to "
                f"{edf['e2e_otif_rate']:.1%}."
            )
        points.append(
            f"**Batching is the largest labor lever in the chain.** On the same allocation, "
            f"releasing one order per wave needs {single['waves']} waves and "
            f"{_num(single['pick_labor_minutes'], 0)} pick-minutes; EDF fill needs "
            f"{edf['waves']} waves and {_num(edf['pick_labor_minutes'], 0)} pick-minutes, "
            f"a {saved_share:.1%} reduction. {service}"
        )

    if pickers:
        ordered = sorted(pickers, key=lambda row: row["pickers_per_dc"])
        low = ordered[0]
        high = ordered[-1]
        if high["pickers_per_dc"] > low["pickers_per_dc"]:
            if (
                low["pick_on_time_rate"] >= 1.0 - 1e-9
                and high["pick_on_time_rate"] >= 1.0 - 1e-9
            ):
                points.append(
                    f"**Staffing is slack at this load.** With "
                    f"{low['pickers_per_dc']} picker(s)/DC every ticket already clears its "
                    f"cutoff, and going to {high['pickers_per_dc']} leaves end-to-end OTIF "
                    f"at {high['e2e_otif_rate']:.1%} while changing waves "
                    f"{low['waves']} → {high['waves']} and pick-minutes "
                    f"{_num(low['pick_labor_minutes'], 0)} → "
                    f"{_num(high['pick_labor_minutes'], 0)}. The capacity sweep only bites "
                    f"once the backlog grows past what one picker can serve before the "
                    f"cutoffs."
                )
            elif high["pick_on_time_rate"] >= 1.0 - 1e-9:
                points.append(
                    f"**Picking capacity, not allocation, sets end-to-end OTIF at "
                    f"{low['pickers_per_dc']} picker(s)/DC.** Going to "
                    f"{high['pickers_per_dc']} pickers/DC moves pick on-time from "
                    f"{low['pick_on_time_rate']:.1%} to {high['pick_on_time_rate']:.1%} and "
                    f"end-to-end OTIF from {low['e2e_otif_rate']:.1%} to "
                    f"{high['e2e_otif_rate']:.1%} on the same orders. At the higher "
                    f"staffing level end-to-end OTIF collapses onto allocation OTIF, so the "
                    f"remaining loss is upstream."
                )
            else:
                points.append(
                    f"**The shift is capacity-constrained at both staffing levels.** "
                    f"Moving from {low['pickers_per_dc']} to {high['pickers_per_dc']} "
                    f"pickers/DC raises pick on-time from {low['pick_on_time_rate']:.1%} to "
                    f"{high['pick_on_time_rate']:.1%} and end-to-end OTIF from "
                    f"{low['e2e_otif_rate']:.1%} to {high['e2e_otif_rate']:.1%}, but "
                    f"{high['pick_tardy_tickets']} tickets still miss their cutoff at the "
                    f"higher level."
                )

    points.append(
        "**These are feasible plans, not proven optima.** CP-SAT returns "
        "`FEASIBLE` on most 400-order runs, the reported gaps are wide, and repeated runs "
        "of the same model differ because the solve is time-limited with parallel workers. "
        "The pick-capacity constraint is a cumulative linear proxy for wave picking, and "
        "the promise-to-cutoff map, arrival process and labor minutes are declared "
        "assumptions, so the absolute OTIF levels are not transferable."
    )
    return points


def build_e2e_report(
    results: Dict[str, Any],
    title: str = "End-to-end fulfillment benchmark",
    generated: str = "",
) -> str:
    dataset = results.get("dataset", {})
    settings = results.get("settings", {})
    scenarios = results.get("scenarios", [])
    dc_workload = results.get("dc_workload", [])
    release = results.get("release", [])
    pickers = results.get("picker_sensitivity", [])
    assumptions = results.get("assumptions", [])

    lines = [
        f"# {title}",
        "",
        f"- Generated: `{generated}`",
        (
            f"- Orders: **{_num(dataset.get('orders'), 0)}** real invoices / "
            f"**{_num(dataset.get('lines'), 0)}** lines / "
            f"**{_num(dataset.get('units'), 0)}** units, week {dataset.get('week', '—')}"
        ),
        (
            f"- DCs: **{dataset.get('dcs', '—')}**; stock covers "
            f"**{_pct(dataset.get('stock_coverage'))}** of sampled demand. "
            f"Promises 2/3/5 days map to pick cutoffs "
            f"**12:00 / 16:00 / 18:00**."
        ),
        (
            f"- Picking: **{settings.get('pickers', '—')} picker(s) per DC**, "
            f"wave cap **{dataset.get('max_orders_per_wave', '—')} orders / "
            f"{dataset.get('max_lines_per_wave', '—')} lines**, "
            f"shift **{_num(settings.get('shift_minutes'), 0)} min**. "
            f"Release policy **{settings.get('policy_label', settings.get('policy', '—'))}**."
        ),
        "",
        "## Assumptions",
        "",
        (
            "| Item | Assumption | Note |\n"
            "|---|---|---|\n"
            f"| Promise mix | 30% / 50% / 20% express / standard / economy | "
            "No customer-promise field in Online Retail II; tiers are a declared seeded shuffle. |\n"
            "| Promise → cutoff | 2d/3d/5d → 12:00/16:00/18:00 | "
            "One promise field drives both the allocation lateness penalty and the warehouse cutoff. |\n"
            f"| Arrivals | express {_pct(dataset.get('tier_onsite', {}).get('express'))}, "
            f"standard {_pct(dataset.get('tier_onsite', {}).get('standard'))}, "
            f"economy {_pct(dataset.get('tier_onsite', {}).get('economy'))} before the start | "
            "The rest arrive uniformly inside a declared tier window; no release timestamps exist in the data. |\n"
            f"| Picking capacity | {settings.get('pickers', '—')} identical picker(s) per DC | "
            "No zones, skills, breaks or congestion; DCs do not share labor. |\n"
            f"| Wave labor | travel {_num(dataset.get('travel_m_per_minute'), 1)} m/min, "
            f"{_num(dataset.get('pick_min_per_line'), 2)} min/line + "
            f"{_num(dataset.get('pick_min_per_unit'), 2)} min/unit, "
            f"{_num(dataset.get('setup_min_per_wave'), 1)} min setup/wave | "
            "Same Week-6 model for every DC and every scenario. |\n"
            f"| Labor cost | €{_num(dataset.get('labor_cost_per_minute'), 2)}/picker-minute | "
            "Added to the allocation cost to form the end-to-end total. |\n"
            "| Pick-capacity proxy | cumulative pick-minutes per DC and promise tier | "
            "A linear surrogate inside the allocation MILP; the online simulation is the ground truth. |"
        ),
        "",
        "## Methods",
        "",
        "- **Allocation (Week 5)**: each order is assigned to at most two DCs under stock, weekly throughput and split limits. Greedy is deadline-first; the MILP minimises transport, fixed shipment, lateness and unmet penalties.",
        "- **Pick tickets**: every shipped line becomes a ticket keyed by invoice and DC, so a split order creates one ticket per DC. Ticket quantities come from the allocation, not from a re-optimisation.",
        "- **Online release (Week 8)**: per DC, the event-driven simulation forms waves from the arrived pool and dispatches them to that DC's pickers. A ticket is on time when its wave finishes before the promise cutoff.",
        "- **End-to-end OTIF**: an order counts only when it is fully shipped, every shipped unit lands inside the promise, and every one of its pick tickets finishes before the cutoff. Allocation OTIF is therefore an upper bound.",
        "- **Pick-capacity-aware allocation**: the MILP adds cumulative pick-minute budgets per DC at 240/480/600 minutes, counting 0.35 min per touched line, 0.02 min per unit and 0.5 min per shipment. Overload is soft and priced at €5 per pick-minute, and the service plan warm-starts the solve.",
        "- **Release and staffing sweeps**: the same allocation is replayed under each release policy and under 1/2/3 pickers per DC to separate allocation effects from warehouse-execution effects.",
        "",
        "## Scenario comparison",
        "",
        _md_table(_scenario_table(scenarios)),
        "",
        "All scenarios use the same orders, stock, promises and arrival draw. `分单 OTIF` is the Week-5 outcome; `端到端 OTIF` additionally requires every pick ticket to clear its cutoff. Cost columns are euros; labor is priced at €0.45 per picker-minute.",
        "",
    ]

    if dc_workload:
        lines.extend(
            [
                "## Per-DC workload — pick-capacity-aware allocation",
                "",
                _md_table(_dc_table(dc_workload)),
                "",
                "Tickets, not orders, drive the workload: a split order appears at two DCs. Idle minutes are paid picker capacity with no wave in progress.",
                "",
            ]
        )

    if release:
        lines.extend(
            [
                "## Release-policy sweep",
                "",
                _md_table(_release_table(release)),
                "",
                "One allocation, four online policies. No policy sees future arrivals; waiting is bounded by the declared window and fill target.",
                "",
            ]
        )

    if pickers:
        lines.extend(
            [
                "## Picker sensitivity",
                "",
                _md_table(_picker_table(pickers)),
                "",
                "Same allocation, same arrivals, only the number of pickers per DC changes. This isolates whether the end-to-end loss comes from allocation or from warehouse capacity.",
                "",
            ]
        )

    if assumptions:
        lines.extend(["## Declared assumptions", ""])
        lines.extend(f"- {item}" for item in assumptions)
        lines.append("")

    lines.extend(["## Interpretation", ""])
    for index, point in enumerate(
        _pick_interpretation(scenarios, release, pickers), start=1
    ):
        lines.append(f"{index}. {point}")
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- The end-to-end chain is a simulation, not a forecast. Online Retail II provides invoices and quantities; DC stock, throughput, transit, promises, cutoffs and arrivals are declared assumptions.",
            "- The pick layer replays a fixed allocation. It never asks the allocator to re-plan after a wave runs late, and it never rebalances pickers across DCs.",
            "- The pick-capacity proxy is a cumulative linear budget. It ignores batching, travel sharing and wave setup, so it can reject or accept plans that the online simulation would score differently.",
            "- CP-SAT allocations at 400 orders are time-limited `FEASIBLE` solutions with wide gaps; repeated runs differ. The scenario ranking is indicative, not a proven optimum ordering.",
            "- Labor is one identical pool per DC with no breaks, zones, skills or congestion. Picking cost uses a flat €0.45/min rate.",
            "- One trading week, one seed, one layout and one arrival draw. No confidence intervals or stochastic robustness are reported.",
            "- Last-mile transit is captured only through the allocation's promise-day arithmetic; carrier performance and customer-facing delivery promises are outside the model.",
            "",
        ]
    )
    return "\n".join(lines)


def write_e2e_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "End-to-end fulfillment benchmark",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    report_path = out / "E2E_REPORT.md"
    summary_path = out / "e2e_summary.json"
    report_path.write_text(
        build_e2e_report(results, title=title, generated=generated),
        encoding="utf-8",
    )
    payload = {"generated": generated, "title": title, **results}
    summary_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": report_path, "summary": summary_path}
