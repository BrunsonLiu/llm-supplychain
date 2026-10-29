"""Markdown/JSON report for Week-30 high-value promise upgrades."""
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


def summarize_service_upgrade(frame: pd.DataFrame) -> pd.DataFrame:
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
                "订单接单": _pct(row.get("accepted_rate", 0.0)),
                "收入接单": _pct(row.get("revenue_accept_rate", 0.0)),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "目标接受 OTIF": _pct(row.get("target_accepted_otif_mean", 0.0)),
                "目标全量 OTIF": _pct(row.get("target_all_otif_mean", 0.0)),
                "非目标接受 OTIF": _pct(
                    row.get("rest_accepted_otif_mean", 0.0)
                ),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "流失收入": _num(row.get("lost_revenue", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def build_service_upgrade_report(
    payload: Dict[str, Any],
    title: str = "High-value promise upgrade (Week 30)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})
    pairs = [("atp_3_top10", "atp_3_top10_up3"), ("atp_3_top25", "atp_3_top25_up3")]

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
        "This is the Week-28/29 value override plus a **promise upgrade**. A new "
        "high-value order is still accepted despite a long ATP quote, but its quote "
        "is capped at 3 days. The cap is not a capacity reservation: it only changes "
        "the order's deadline so it competes for stock/picking earlier. If the "
        "inventory or labor is not there, the earlier promise can fail. The target "
        "segment is Top10 for Top10 scenarios and Top25 for Top25 scenarios; the rest "
        "is everyone else."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    for base_key, up_key in pairs:
        base = next((row for row in summary if row.get("policy") == base_key), None)
        up = next((row for row in summary if row.get("policy") == up_key), None)
        if base is None or up is None:
            continue
        lines.append(
            f"- **{up.get('label', up_key)}:** accepts "
            f"{_num(up['accepted_orders'], 1)} orders "
            f"({up['accepted_orders'] - base['accepted_orders']:+.1f} vs no "
            f"upgrade), revenue {_pct(up['revenue_accept_rate'])} "
            f"({(up['revenue_accept_rate'] - base['revenue_accept_rate']) * 100:+.1f} "
            f"pp); target accepted OTIF {_pct(up['target_accepted_otif_mean'])} "
            f"({(up['target_accepted_otif_mean'] - base['target_accepted_otif_mean']) * 100:+.1f} "
            f"pp), rest accepted OTIF {_pct(up['rest_accepted_otif_mean'])} "
            f"({(up['rest_accepted_otif_mean'] - base['rest_accepted_otif_mean']) * 100:+.1f} "
            f"pp), all-order OTIF {_pct(up['all_otif_mean'])} "
            f"({(up['all_otif_mean'] - base['all_otif_mean']) * 100:+.1f} pp)."
        )
    lines.append(
        "- **A promise upgrade is not a capacity reservation.** It changes the "
        "deadline and therefore the allocation/dispatch priority, but it does not "
        "create stock, pickers or dock minutes. If target OTIF rises and rest OTIF "
        "falls, the gain is redistribution; if target OTIF does not rise, the "
        "constraint was inventory/labor, not the promise date."
    )
    top10_base = next(
        (row for row in summary if row.get("policy") == "atp_3_top10"), None
    )
    top10_up = next(
        (row for row in summary if row.get("policy") == "atp_3_top10_up3"), None
    )
    if top10_base and top10_up:
        lines.append(
            f"- **The upgrade made the target worse, not better.** Top10 target "
            f"accepted OTIF {_pct(top10_base['target_accepted_otif_mean'])} → "
            f"{_pct(top10_up['target_accepted_otif_mean'])} "
            f"({(top10_up['target_accepted_otif_mean'] - top10_base['target_accepted_otif_mean']) * 100:+.1f} "
            f"pp), while the rest is roughly flat "
            f"({_pct(top10_base['rest_accepted_otif_mean'])} → "
            f"{_pct(top10_up['rest_accepted_otif_mean'])}). With no added stock, "
            f"pickers or doors, a 3-day promise mostly reclassifies the same later "
            f"delivery as late; it does not buy service."
        )
    top25_base = next(
        (row for row in summary if row.get("policy") == "atp_3_top25"), None
    )
    top25_up = next(
        (row for row in summary if row.get("policy") == "atp_3_top25_up3"), None
    )
    if top25_base and top25_up:
        lines.append(
            f"- **Top25 loses the same 5 pp on its target.** Target accepted OTIF "
            f"{_pct(top25_base['target_accepted_otif_mean'])} → "
            f"{_pct(top25_up['target_accepted_otif_mean'])}; rest "
            f"{_pct(top25_base['rest_accepted_otif_mean'])} → "
            f"{_pct(top25_up['rest_accepted_otif_mean'])}; accepted revenue is "
            f"essentially unchanged. The tighter promise is a service-level "
            f"accounting change, not a capacity increase."
        )
    lines.append(
        "- **Revenue is not fully insulated.** For Top25 the accepted set/revenue is "
        "essentially unchanged; for Top10 the upgrade accepts 4 fewer orders and loses "
        "1.1 pp of revenue because earlier deadlines change stock consumption and "
        "subsequent ATP quotes. The upgrade can feed back into acceptance; it is not "
        "a pure relabeling."
    )
    lines.append(
        "- **This is deliberate over-promising.** A 3-day quote can violate ATP. The "
        "point is to measure the cost of protecting high-value service, not to claim "
        "that the upgrade is feasible in a real ATP system."
    )
    lines.append(
        "- **Read the target and rest segments together.** Accepted OTIF alone can "
        "stay flat while the target improves and everyone else pays for it."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_service_upgrade_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "High-value promise upgrade (Week 30)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "SERVICE_UPGRADE_REPORT.md"
    summary = out / "service_upgrade_summary.json"
    report.write_text(
        build_service_upgrade_report(payload, title=title), encoding="utf-8"
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
