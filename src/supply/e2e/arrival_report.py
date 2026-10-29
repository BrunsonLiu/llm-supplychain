"""Markdown/JSON report for Week-35 inbound arrival expedite."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .dispatch_priority_report import _md_table, _pct, _table


def summarize_arrival(frame: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for policy, group in frame.groupby("policy", sort=False):
        rows.append(
            {
                "policy": policy,
                "seeds": int(len(group)),
                "orders": int(group["orders"].iloc[0]),
                "accepted_orders": float(group["accepted_orders"].mean()),
                "lost_orders": float(group["lost_orders"].mean()),
                "accepted_rate": float(group["accepted_rate"].mean()),
                "accepted_units": int(group["accepted_units"].iloc[0]),
                "lost_units": int(group["lost_units"].iloc[0]),
                "demand_revenue": float(group["demand_revenue"].iloc[0]),
                "accepted_revenue": float(group["accepted_revenue"].iloc[0]),
                "lost_revenue": float(group["lost_revenue"].iloc[0]),
                "revenue_accept_rate": float(
                    group["revenue_accept_rate"].iloc[0]
                ),
                "accepted_otif_mean": float(
                    group["accepted_otif_rate"].mean()
                ),
                "accepted_static_sla_mean": float(
                    group["accepted_static_sla_otif_rate"].mean()
                ),
                "all_otif_mean": float(group["e2e_otif_rate"].mean()),
                "target_accepted_orders": float(
                    group["target_accepted_orders"].mean()
                ),
                "target_accepted_otif_mean": float(
                    group["target_accepted_otif_rate"].mean()
                ),
                "target_all_otif_mean": float(
                    group["target_all_otif_rate"].mean()
                ),
                "rest_accepted_otif_mean": float(
                    group["rest_accepted_otif_rate"].mean()
                ),
                "departures": float(group["departures"].mean()),
                "mean_wait_minutes": float(
                    group["mean_wait_minutes"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def _find(summary: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    return next((row for row in summary if row.get("policy") == key), None)


def build_arrival_report(
    payload: Dict[str, Any],
    title: str = "Inbound arrival expedite (Week 35)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})

    lines = [f"# {title}", ""]
    lines.append(f"- Generated: `{stamp}`")
    lines.append(
        f"- Orders: **{dataset.get('orders', 0)}** real invoices / "
        f"**{dataset.get('lines', 0)}** lines / **{dataset.get('units', 0):,}** units, "
        f"week {dataset.get('week', '')}"
    )
    lines.append(
        f"- Flow: **{len(order_days)}** weekdays | "
        + " | ".join(f"day {day}: {count}" for day, count in order_days.items())
    )
    lines.append(
        f"- Seeds: **{settings.get('seeds', 0)}** | scenarios "
        f"**{settings.get('scenarios', [])}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day**"
    )
    lines.append(
        f"- Demand revenue **{dataset.get('demand_revenue', 0.0):,.0f}**; "
        f"revenue coverage **{settings.get('revenue_coverage', 0.0):.1%}**."
    )
    lines.append("")

    lines += ["## Rule", ""]
    lines.append(
        "This is the Week-28/29 value override replayed with an **inbound "
        "arrival expedite** on the same prepared flow. In the target arm, every "
        "high-value order is marked onsite at minute zero instead of its sampled "
        "arrival; in the all-early arm, every open order is onsite at zero. "
        "Stock, promises, picker count, pick order and dock policy are unchanged, "
        "so only the arrival timestamp moves. It does not add inventory, labor, "
        "or a departure; an expedite cost is not modeled."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    for target in ("top10", "top25"):
        base = _find(summary, f"atp_3_{target}_base")
        target_early = _find(summary, f"atp_3_{target}_target_early")
        all_early = _find(summary, f"atp_3_{target}_all_early")
        if not base:
            continue
        if target_early:
            d_target = (
                target_early["target_accepted_otif_mean"]
                - base["target_accepted_otif_mean"]
            ) * 100
            d_rest = (
                target_early["rest_accepted_otif_mean"]
                - base["rest_accepted_otif_mean"]
            ) * 100
            d_all = (
                target_early["all_otif_mean"] - base["all_otif_mean"]
            ) * 100
            lines.append(
                f"- **{base.get('target_label', target)} target arrivals at 0:** "
                f"target {_pct(base['target_accepted_otif_mean'])} → "
                f"{_pct(target_early['target_accepted_otif_mean'])} "
                f"({d_target:+.1f} pp), rest "
                f"{_pct(base['rest_accepted_otif_mean'])} → "
                f"{_pct(target_early['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), "
                f"all-order {d_all:+.1f} pp."
            )
        if all_early:
            d_target = (
                all_early["target_accepted_otif_mean"]
                - base["target_accepted_otif_mean"]
            ) * 100
            d_rest = (
                all_early["rest_accepted_otif_mean"]
                - base["rest_accepted_otif_mean"]
            ) * 100
            d_all = (all_early["all_otif_mean"] - base["all_otif_mean"]) * 100
            note = ""
            if (
                abs(d_all) < 0.5
                and all_early["departures"] < base["departures"] - 1.0
            ):
                note = (
                    f" **The arrival manipulation was real:** departures fell "
                    f"from {base['departures']:.1f} to "
                    f"{all_early['departures']:.1f} (more consolidated waves), "
                    f"yet OTIF did not move; earlier freight changed batching, "
                    f"not service. The late orders are blocked by stock/"
                    f"allocation, not by their arrival clock."
                )
            lines.append(
                f"- **{base.get('target_label', target)} all arrivals at 0:** "
                f"target {d_target:+.1f} pp, rest {d_rest:+.1f} pp, all-order "
                f"{d_all:+.1f} pp; departures "
                f"{base['departures']:.1f} → {all_early['departures']:.1f}."
                f"{note}"
            )

    top10_base = _find(summary, "atp_3_top10_base")
    top10_early = _find(summary, "atp_3_top10_all_early")
    if top10_base and top10_early:
        d_all = (
            top10_early["all_otif_mean"] - top10_base["all_otif_mean"]
        ) * 100
        if d_all >= 0.5:
            lines.append(
                "- **Arrival timing is a real binding constraint.** Moving all "
                "open orders to minute zero raises aggregate accepted OTIF; the "
                "Week-34 result (extra picker had no effect) is consistent: the "
                "shift had labor slack, so the queue was waiting on freight, not "
                "on pickers."
            )
        else:
            lines.append(
                "- **Arrival timing alone does not close the gap.** Even with "
                "every open order onsite at minute zero, aggregate/target OTIF "
                "does not improve materially; the remaining constraint is stock "
                "or the value/ATP rule, not the arrival clock."
            )
    lines.append(
        "- **Target-only expedite is a sharper test than all-early.** If target "
        "rises while rest is unchanged, the target's late orders were genuinely "
        "waiting for inbound; if target does not rise, the late target orders "
        "were already onsite or blocked by stock, not by their arrival stamp."
    )
    lines.append(
        "- **This is not free.** Expediting inbound has a freight/premium cost "
        "that this report does not model; it also assumes the warehouse can "
        "receive the order at minute zero."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_arrival_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Inbound arrival expedite (Week 35)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "ARRIVAL_REPORT.md"
    summary = out / "arrival_summary.json"
    report.write_text(
        build_arrival_report(payload, title=title), encoding="utf-8"
    )
    summary.write_text(
        json.dumps(
            {
                "title": title,
                **payload,
                "generated": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {"report": report, "summary": summary}
