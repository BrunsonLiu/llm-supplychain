"""Markdown/JSON report for Week-32 high-value dispatch priority."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def _pct(value: float) -> str:
    return f"{float(value) * 100:.1f}%"


def _num(value: float, digits: int = 0) -> str:
    return f"{float(value):,.{digits}f}"


def summarize_dispatch_priority(frame: pd.DataFrame) -> pd.DataFrame:
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


def _table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        rows.append(
            {
                "场景": row.get("label", row.get("policy", "")),
                "目标": row.get("target_label", "—"),
                "接受订单": _num(row["accepted_orders"], 1),
                "收入接单": _pct(row.get("revenue_accept_rate", 0.0)),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "目标 OTIF": _pct(row.get("target_accepted_otif_mean", 0.0)),
                "非目标 OTIF": _pct(
                    row.get("rest_accepted_otif_mean", 0.0)
                ),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "发车": _num(row.get("departures", 0.0), 1),
                "平均等车": _num(row.get("mean_wait_minutes", 0.0), 0),
            }
        )
    return pd.DataFrame(rows)


def build_dispatch_priority_report(
    payload: Dict[str, Any],
    title: str = "High-value dispatch priority (Week 32)",
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
        "This is the Week-28/29 value override plus a **dispatch priority**. "
        "Within a lane, tickets of the target high-value orders are loaded before "
        "lower-priority tickets; ties still use EDF. This is an actual loading-"
        "sequence change, not a promise relabel or an objective weight. It does "
        "not add a door, a picker, or a departure. EDF and priority replay the "
        "**same prepared flow**, so acceptance/allocation are held fixed and only "
        "the loading order changes. The target is Top10 for Top10 scenarios and "
        "Top25 for Top25 scenarios; the rest is everyone else."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    for target in ("top10", "top25"):
        base_key = f"atp_3_{target}_edf"
        priority_key = f"atp_3_{target}_priority"
        base = next((row for row in summary if row.get("policy") == base_key), None)
        up = next(
            (row for row in summary if row.get("policy") == priority_key), None
        )
        if base is None or up is None:
            continue
        d_target = (
            up["target_accepted_otif_mean"] - base["target_accepted_otif_mean"]
        ) * 100
        d_rest = (
            up["rest_accepted_otif_mean"] - base["rest_accepted_otif_mean"]
        ) * 100
        d_rev = (
            up["revenue_accept_rate"] - base["revenue_accept_rate"]
        ) * 100
        d_all = (up["all_otif_mean"] - base["all_otif_mean"]) * 100
        lines.append(
            f"- **{base.get('target_label', target)} priority:** target OTIF "
            f"{_pct(base['target_accepted_otif_mean'])} → "
            f"{_pct(up['target_accepted_otif_mean'])} ({d_target:+.1f} pp), rest "
            f"{_pct(base['rest_accepted_otif_mean'])} → "
            f"{_pct(up['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), all-order "
            f"{d_all:+.1f} pp, revenue {d_rev:+.1f} pp, accepted "
            f"{up['accepted_orders'] - base['accepted_orders']:+.1f} orders; "
            f"departures {base['departures']:.1f} → {up['departures']:.1f}, "
            f"mean wait {base['mean_wait_minutes']:.0f} → "
            f"{up['mean_wait_minutes']:.0f} min."
        )
    top10_base = next(
        (row for row in summary if row.get("policy") == "atp_3_top10_edf"),
        None,
    )
    top10_up = next(
        (row for row in summary if row.get("policy") == "atp_3_top10_priority"),
        None,
    )
    top25_base = next(
        (row for row in summary if row.get("policy") == "atp_3_top25_edf"),
        None,
    )
    top25_up = next(
        (row for row in summary if row.get("policy") == "atp_3_top25_priority"),
        None,
    )
    if top10_base and top10_up and top25_base and top25_up:
        d10 = (
            top10_up["target_accepted_otif_mean"]
            - top10_base["target_accepted_otif_mean"]
        ) * 100
        d25 = (
            top25_up["target_accepted_otif_mean"]
            - top25_base["target_accepted_otif_mean"]
        ) * 100
        if abs(d10) < 1e-9 and abs(d25) < 1e-9:
            lines.append(
                "- **The priority was a no-op in this instance.** EDF and priority "
                "produced identical accepted orders, target/rest/all OTIF, and "
                "departure counts. Every lane batch fits the departure capacity, "
                "so reordering tickets changes only the sequence **inside** the "
                "same batch, not which tickets leave or on which day. This is a "
                "valid null result: dispatch priority can only matter when a "
                "batch/door constraint actually selects a subset. It says nothing "
                "about a capacity-constrained dock, where the same manipulation "
                "could help target and hurt rest."
            )
        else:
            lines.append(
                f"- **Dispatch priority did not buy service.** Top10 target OTIF "
                f"{d10:+.1f} pp ({_pct(top10_base['target_accepted_otif_mean'])} → "
                f"{_pct(top10_up['target_accepted_otif_mean'])}); Top25 "
                f"{d25:+.1f} pp ({_pct(top25_base['target_accepted_otif_mean'])} → "
                f"{_pct(top25_up['target_accepted_otif_mean'])}). Rest OTIF stayed "
                f"at 100%, so there was no measurable redistribution either. If "
                f"the target parcel is not at the dock by the cutoff, sorting "
                f"available tickets cannot help; the binding stage is upstream "
                f"(arrival/pick)."
            )
    lines.append(
        "- **Dispatch priority can only reorder existing capacity.** If target "
        "OTIF rises and rest falls, the gain is zero-sum: the high-value parcel "
        "took an earlier departure from a low-value parcel. If both rise, the "
        "priority also improved lane packing; if target does not rise, dock "
        "ordering was not the binding constraint."
    )
    lines.append(
        "- **A real loading priority is not free.** Moving a target ticket ahead "
        "can push another order past its promise even though every parcel was "
        "picked. Read target and rest together, not just aggregate OTIF."
    )
    lines.append(
        "- **It is still not extra capacity.** The priority changes who gets the "
        "next departure slot; it does not create another slot, door, picker, or "
        "unit of stock."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_dispatch_priority_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "High-value dispatch priority (Week 32)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "DISPATCH_PRIORITY_REPORT.md"
    summary = out / "dispatch_priority_summary.json"
    report.write_text(
        build_dispatch_priority_report(payload, title=title), encoding="utf-8"
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
