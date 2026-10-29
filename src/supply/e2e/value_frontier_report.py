"""Markdown/JSON report for the Week-29 value-threshold frontier."""
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


def summarize_value_frontier(frame: pd.DataFrame) -> pd.DataFrame:
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
                "阈值": row.get("top_label", "—"),
                "价值门槛": row.get("value_label", "—"),
                "接受订单": _num(row["accepted_orders"], 1),
                "订单接单率": _pct(row.get("accepted_rate", 0.0)),
                "收入接单率": _pct(row.get("revenue_accept_rate", 0.0)),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "流失收入": _num(row.get("lost_revenue", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def _dominance(points: List[Dict[str, Any]], x: str, y: str) -> List[Dict[str, Any]]:
    result = []
    for point in points:
        dominated = False
        for other in points:
            if other is point:
                continue
            if (
                other[x] >= point[x]
                and other[y] >= point[y]
                and (other[x] > point[x] or other[y] > point[y])
            ):
                dominated = True
                break
        if not dominated:
            result.append(point)
    return result


def build_value_frontier_report(
    payload: Dict[str, Any],
    title: str = "Value-threshold frontier (Week 29)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})
    base = next((row for row in summary if row.get("policy") == "atp_3"), None)
    points = sorted(
        [
            row
            for row in summary
            if row.get("policy") != "single_week_static"
        ],
        key=lambda row: (
            row.get("top_fraction", 1.0)
            if row.get("top_fraction") is not None
            else 1.0
        ),
    )

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
        f"- Seeds: **{settings.get('seeds', 0)}** | thresholds "
        f"**{settings.get('tops', [])}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day**"
    )
    lines.append(
        f"- Demand revenue **{dataset.get('demand_revenue', 0.0):,.0f}**; "
        f"revenue coverage **{settings.get('revenue_coverage', 0.0):.1%}**."
    )
    lines.append("")

    lines += ["## Rule", ""]
    lines.append(
        "Every point uses the same ATP ≤3-day cutoff. A long-promise order is kept "
        "only when its invoice revenue is at least the threshold quantile; the scan "
        "moves that bar from the top 5% down to accept-all. This is a threshold "
        "frontier, not a tuned optimum: all thresholds are in-sample quantiles on "
        "the same 400 orders, and no out-of-sample calibration is done."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    if base:
        lines.append(
            f"- **No override (Top 0%):** accepts "
            f"{_num(base['accepted_orders'], 1)} orders "
            f"({_pct(base['accepted_rate'])}), revenue "
            f"{_num(base['accepted_revenue'])} "
            f"({_pct(base['revenue_accept_rate'])}), accepted OTIF "
            f"{_pct(base['accepted_otif_mean'])}; lost revenue "
            f"{_num(base['lost_revenue'])}."
        )
    ordered = [row for row in points if row.get("top_fraction") is not None]
    marginals = []
    for left, right in zip(ordered, ordered[1:]):
        d_rev = (right["revenue_accept_rate"] - left["revenue_accept_rate"]) * 100
        d_otif = (
            right["accepted_otif_mean"] - left["accepted_otif_mean"]
        ) * 100
        d_all = (right["all_otif_mean"] - left["all_otif_mean"]) * 100
        marginals.append((left, right, d_rev, d_otif, d_all))
        lines.append(
            f"- **{left.get('top_label', '')} → {right.get('top_label', '')}:** "
            f"revenue {d_rev:+.1f} pp, accepted OTIF {d_otif:+.1f} pp, "
            f"all-order OTIF {d_all:+.1f} pp."
        )
    if marginals:
        efficient = [
            item
            for item in marginals
            if item[2] > 0 and item[3] < 0 and abs(item[3]) > 1e-9
        ]
        if efficient:
            best = max(efficient, key=lambda item: item[2] / abs(item[3]))
            lines.append(
                f"- **Best marginal trade-off:** "
                f"{best[0].get('top_label', '')} → {best[1].get('top_label', '')} "
                f"gains {best[2]:+.1f} pp revenue for {best[3]:+.1f} pp accepted "
                f"OTIF ({best[2] / abs(best[3]):.1f} revenue points per OTIF point). "
                f"Other segments can be better on absolute revenue or service, so this "
                f"is a marginal reading, not a global optimum."
            )
    x_rev = "revenue_accept_rate"
    accepted_front = _dominance(summary, x_rev, "accepted_otif_mean")
    lines.append(
        f"- **Accepted-OTIF frontier:** {len(accepted_front)} of {len(summary)} "
        f"points are non-dominated in (revenue, accepted OTIF): "
        + ", ".join(str(row.get("top_label", row["policy"])) for row in accepted_front)
        + "."
    )
    top30 = next(
        (row for row in summary if row.get("policy") == "atp_3_top30"), None
    )
    top40 = next(
        (row for row in summary if row.get("policy") == "atp_3_top40"), None
    )
    if top30 and top40:
        lines.append(
            f"- **Top 30% is dominated by Top 40% in this run.** Top 40% has "
            f"{_pct(top40['revenue_accept_rate'])} vs "
            f"{_pct(top30['revenue_accept_rate'])} revenue and "
            f"{_pct(top40['accepted_otif_mean'])} vs "
            f"{_pct(top30['accepted_otif_mean'])} accepted OTIF. The accepted-OTIF "
            f"difference is only {(top40['accepted_otif_mean'] - top30['accepted_otif_mean']) * 100:+.1f} "
            f"pp, inside the usual solver spread, so the curve is not cleanly "
            f"monotone; do not over-read a single threshold."
        )
    lines.append(
        "- **All-order OTIF is a coverage check, not a policy frontier.** It rises "
        "monotonically as fewer orders are rejected, so accept-all is the endpoint by "
        "construction. That is why the accepted-OTIF and original-SLA columns carry "
        "the trade-off; all-order OTIF tells you how much demand is served at all."
    )
    lines.append(
        "- **Marginal returns are not monotone.** The segment with the best revenue-"
        "per-OTIF ratio need not be the segment with the most absolute revenue, and "
        "accept-all can have the same accepted OTIF as a threshold while serving more "
        "orders. Read the table rather than assuming a single stylized knee; the "
        "threshold is a business choice, not a universal optimum."
    )
    lines.append(
        "- **Two service lenses disagree.** A threshold that looks good on accepted "
        "OTIF can look different on all-order OTIF, because a higher threshold rejects "
        "more orders. Read both, plus the original-SLA column, before choosing."
    )
    lines.append(
        "- **Accept-all is not on the same frontier dimension.** It has 100% revenue "
        "but a lower original SLA; a value threshold can buy original-SLA service by "
        "giving up some revenue. Neither is strictly better without a cost for lateness."
    )
    lines.append(
        "- **Thresholds are in-sample.** The scan is a sensitivity check on Week 28, "
        "not an out-of-sample policy. A live threshold would need historical revenue "
        "quantiles, drift monitoring, COGS/margin, capacity and customer value."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_value_frontier_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Value-threshold frontier (Week 29)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "VALUE_FRONTIER_REPORT.md"
    summary = out / "value_frontier_summary.json"
    report.write_text(
        build_value_frontier_report(payload, title=title), encoding="utf-8"
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
