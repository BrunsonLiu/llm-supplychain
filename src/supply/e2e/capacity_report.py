"""Markdown/JSON report for Week-34 extra pick capacity."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .dispatch_priority_report import _md_table, _pct, _table


def summarize_capacity(frame: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for policy, group in frame.groupby("policy", sort=False):
        rows.append(
            {
                "policy": policy,
                "seeds": int(len(group)),
                "orders": int(group["orders"].iloc[0]),
                "pickers": int(group["pickers_per_dc"].iloc[0]),
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
                "labor_minutes": float(group["labor_minutes"].mean()),
                "pick_makespan_minutes": float(
                    group["pick_makespan_minutes"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def _table_capacity(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        rows.append(
            {
                "场景": row.get("label", row.get("policy", "")),
                "目标": row.get("target_label", "—"),
                "拣货员/DC": row.get("pickers", 0),
                "接单率": _pct(row["accepted_rate"]),
                "收入接单": _pct(row.get("revenue_accept_rate", 0.0)),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "目标 OTIF": _pct(row.get("target_accepted_otif_mean", 0.0)),
                "非目标 OTIF": _pct(
                    row.get("rest_accepted_otif_mean", 0.0)
                ),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "发车": f"{row.get('departures', 0.0):.1f}",
                "拣选分钟": f"{row.get('labor_minutes', 0.0):,.0f}",
                "拣选跨度合计": f"{row.get('pick_makespan_minutes', 0.0):.0f}",
            }
        )
    return pd.DataFrame(rows)


def _find(summary: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    return next((row for row in summary if row.get("policy") == key), None)


def build_capacity_report(
    payload: Dict[str, Any],
    title: str = "Extra pick capacity (Week 34)",
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
        "This is the Week-28/29 value override replayed with **one vs two "
        "pickers per DC** on the same prepared flow. Acceptance and stock "
        "allocation are held fixed; only the labor resource changes. In the "
        "third arm, the second picker is combined with the Week-33 high-value "
        "pick priority, so the test separates 'more capacity' from 'same "
        "capacity, different order'. It does not add a door, stock, or a "
        "departure, and it does not model a picker wage."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table_capacity(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    all1 = _find(summary, "atp_all_1p")
    all2 = _find(summary, "atp_all_2p")
    if all1 and all2:
        lines.append(
            f"- **Accept-all 1 → 2 pickers:** accepted OTIF "
            f"{_pct(all1['accepted_otif_mean'])} → {_pct(all2['accepted_otif_mean'])} "
            f"({(all2['accepted_otif_mean'] - all1['accepted_otif_mean']) * 100:+.1f} pp), "
            f"target {_pct(all1['target_accepted_otif_mean'])} → "
            f"{_pct(all2['target_accepted_otif_mean'])}, rest "
            f"{_pct(all1['rest_accepted_otif_mean'])} → "
            f"{_pct(all2['rest_accepted_otif_mean'])}; pick makespan "
            f"{all1['pick_makespan_minutes']:.0f} → "
            f"{all2['pick_makespan_minutes']:.0f} min."
        )

    for target in ("top10", "top25"):
        one = _find(summary, f"atp_3_{target}_1p")
        two = _find(summary, f"atp_3_{target}_2p")
        two_pick = _find(summary, f"atp_3_{target}_2p_pick")
        if not (one and two):
            continue
        d_target = (
            two["target_accepted_otif_mean"] - one["target_accepted_otif_mean"]
        ) * 100
        d_rest = (
            two["rest_accepted_otif_mean"] - one["rest_accepted_otif_mean"]
        ) * 100
        d_all = (two["all_otif_mean"] - one["all_otif_mean"]) * 100
        lines.append(
            f"- **{two.get('target_label', target)} 1 → 2 pickers:** target "
            f"{_pct(one['target_accepted_otif_mean'])} → "
            f"{_pct(two['target_accepted_otif_mean'])} ({d_target:+.1f} pp), "
            f"rest {_pct(one['rest_accepted_otif_mean'])} → "
            f"{_pct(two['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), "
            f"all-order {d_all:+.1f} pp; pick makespan "
            f"{one['pick_makespan_minutes']:.0f} → "
            f"{two['pick_makespan_minutes']:.0f} min, labor "
            f"{one['labor_minutes']:,.0f} → {two['labor_minutes']:,.0f} min."
        )
        if two_pick:
            d_pick_target = (
                two_pick["target_accepted_otif_mean"]
                - two["target_accepted_otif_mean"]
            ) * 100
            d_pick_rest = (
                two_pick["rest_accepted_otif_mean"]
                - two["rest_accepted_otif_mean"]
            ) * 100
            lines.append(
                f"- **{two.get('target_label', target)} 2 pickers, EDF → "
                f"priority:** target {d_pick_target:+.1f} pp, rest "
                f"{d_pick_rest:+.1f} pp. This asks whether priority only works "
                f"once there is spare pick capacity."
            )

    if all1 and all2:
        d_all = (all2["accepted_otif_mean"] - all1["accepted_otif_mean"]) * 100
        if d_all >= 0.5:
            lines.append(
                "- **Pick capacity is binding in this instance.** Adding one "
                "picker improves aggregate accepted OTIF; the value-override "
                "gap is at least partly a labor constraint, not only a stock or "
                "arrival constraint. The second picker is not free: it adds "
                "labor and changes makespan, but this report does not price a "
                "picker wage."
            )
        else:
            lines.append(
                "- **More pick capacity alone does not move aggregate OTIF "
                "materially.** If target also stays flat, the remaining "
                "constraint is upstream arrival or stock, not pick minutes; if "
                "target moves while aggregate does not, capacity is being "
                "reallocated rather than created for the target."
            )
            if all1.get("pick_makespan_minutes"):
                per_day = float(all1["pick_makespan_minutes"]) / max(
                    1, len(order_days)
                )
                lines.append(
                    f"- **The first picker was not saturated.** Average daily "
                    f"pick span under 1 picker is **{per_day:.0f} min of a "
                    f"600-min shift**, and total labor is {all1['labor_minutes']:,.0f} "
                    f"min against 3 DCs × 5 days × 600 min. A second picker "
                    f"therefore adds slack, not throughput at the bottleneck. "
                    f"That is why 2-picker target/rest/all OTIF are identical "
                    f"to 1-picker and only makespan/labor move."
                )
    lines.append(
        "- **Priority with extra capacity is the cleaner test of the earlier "
        "nulls.** Week 33 gave priority no spare minute. Here the second picker "
        "creates slack; if priority still does nothing, ordering is not the "
        "mechanism even with slack. If it now helps target, the earlier null was "
        "a capacity interaction, not a wrong priority rule."
    )
    lines.append(
        "- **Read target and rest together.** A second picker can raise target "
        "OTIF by taking minutes from rest, or raise both by reducing queueing. "
        "The table separates those cases; aggregate OTIF alone cannot."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_capacity_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Extra pick capacity (Week 34)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "CAPACITY_REPORT.md"
    summary = out / "capacity_summary.json"
    report.write_text(
        build_capacity_report(payload, title=title), encoding="utf-8"
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
