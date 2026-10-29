"""Markdown/JSON report for Week-27 revenue-weighted order acceptance."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def _pct(value: float) -> str:
    return f"{float(value) * 100:.1f}%"


def _num(value: float, digits: int = 0) -> str:
    return f"{float(value):,.{digits}f}"


def summarize_revenue_acceptance(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per acceptance scenario with order/unit/revenue denominators."""
    rows: List[Dict[str, Any]] = []
    for policy, group in frame.groupby("policy", sort=False):
        otif = group["e2e_otif_rate"].to_numpy(dtype=float)
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
                "quoted_otif_mean": float(otif.mean()),
                "fill_mean": float(group["fill_rate"].mean()),
                "accepted_fill_mean": float(
                    group["accepted_fill_rate"].mean()
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
                "报价": row.get("quote_policy", ""),
                "上限": row.get("accept_cutoff", "全部"),
                "接受订单": _num(row["accepted_orders"], 1),
                "订单接单率": _pct(row.get("accepted_rate", 0.0)),
                "接受单位": _num(row.get("accepted_units", 0)),
                "流失单位": _num(row.get("lost_units", 0)),
                "接受收入": _num(row.get("accepted_revenue", 0.0)),
                "流失收入": _num(row.get("lost_revenue", 0.0)),
                "收入接单率": _pct(row.get("revenue_accept_rate", 0.0)),
                "接单 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("quoted_otif_mean", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def build_revenue_acceptance_report(
    payload: Dict[str, Any],
    title: str = "Revenue-weighted order acceptance (Week 27)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})
    accepted_all = next(
        (
            row
            for row in summary
            if row.get("quote_policy") == "atp"
            and row.get("accept_cutoff") == "全部"
        ),
        None,
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
        f"- Seeds: **{settings.get('seeds', 0)}** | scenario "
        f"**{settings.get('scenarios', [])}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day**"
    )
    lines.append(
        f"- Revenue coverage: **{settings.get('revenue_coverage', 0.0):.1%}** of "
        f"orders matched to a positive invoice revenue; total demand revenue "
        f"**{dataset.get('demand_revenue', 0.0):,.0f}**."
    )
    lines.append("")

    lines += ["## Rule", ""]
    lines.append(
        "This is the Week-24 acceptance rule with a third denominator. A new order "
        "whose quoted promise exceeds the cutoff is rejected; rejected orders "
        "consume no stock, do not enter picking/dispatch, and remain in the all-order "
        "denominator. Revenue is the real invoice line revenue "
        "(`quantity × unit price`) sampled from Online Retail II. `收入接单率` is "
        "accepted revenue / all-demand revenue; it is **not** profit, because COGS, "
        "returns and fulfillment cost are not modeled."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    for row in summary:
        if row.get("accept_cutoff") == "全部":
            continue
        accepted_orders = float(row.get("accepted_orders", 0.0))
        if accepted_orders <= 0:
            lines.append(
                f"- **{row.get('label', '')} accepts nothing.** Revenue acceptance "
                f"0.0%, lost revenue {_num(row.get('lost_revenue', 0.0))}; this is an "
                f"empty denominator, not a service success."
            )
            continue
        order_rate = float(row.get("accepted_rate", 0.0))
        revenue_rate = float(row.get("revenue_accept_rate", 0.0))
        unit_rate = (
            row["accepted_units"] / (row["accepted_units"] + row["lost_units"])
            if row["accepted_units"] + row["lost_units"]
            else 0.0
        )
        gap = (revenue_rate - order_rate) * 100
        avg_accepted = row["accepted_revenue"] / accepted_orders
        avg_lost = (
            row["lost_revenue"] / (row["orders"] - accepted_orders)
            if row["orders"] > accepted_orders
            else 0.0
        )
        lines.append(
            f"- **{row.get('label', '')}:** order acceptance "
            f"{_pct(order_rate)}, unit acceptance {_pct(unit_rate)}, revenue "
            f"acceptance {_pct(revenue_rate)} ({gap:+.1f} pp vs order rate). "
            f"Accepted revenue {_num(row['accepted_revenue'])}; lost revenue "
            f"{_num(row['lost_revenue'])}. Average revenue per accepted order "
            f"{_num(avg_accepted)} vs lost order {_num(avg_lost)}."
        )
    if accepted_all:
        lines.append(
            f"- **ATP accept-all is the revenue benchmark.** It accepts all "
            f"{_num(accepted_all['orders'])} orders, revenue "
            f"{_num(accepted_all['accepted_revenue'])}, accepted OTIF "
            f"{_pct(accepted_all['accepted_otif_mean'])} and original SLA "
            f"{_pct(accepted_all['accepted_static_sla_mean'])}. Any cutoff below must "
            f"be judged against the revenue it removes, not only the accepted OTIF."
        )
    atp3 = next(
        (row for row in summary if row.get("policy") == "atp_3"), None
    )
    static3 = next(
        (row for row in summary if row.get("policy") == "static_3"), None
    )
    if atp3:
        avg_acc = atp3["accepted_revenue"] / atp3["accepted_orders"]
        avg_lost = atp3["lost_revenue"] / (atp3["orders"] - atp3["accepted_orders"])
        lines.append(
            f"- **ATP ≤3 days: order acceptance overstates revenue retention.** "
            f"Orders {_pct(atp3['accepted_rate'])} but revenue only "
            f"{_pct(atp3['revenue_accept_rate'])}; average accepted order "
            f"{_num(avg_acc)} vs rejected {_num(avg_lost)}. The cutoff keeps small "
            f"high-price-per-unit orders and drops large high-revenue baskets. The "
            f"100% accepted OTIF is bought with "
            f"{_pct(1.0 - atp3['revenue_accept_rate'])} of demand revenue, not "
            f"29% of orders."
        )
    if static3:
        lines.append(
            f"- **Static ≤3 days: the opposite selection.** Orders "
            f"{_pct(static3['accepted_rate'])}, units "
            f"{_pct(static3['accepted_units'] / (static3['accepted_units'] + static3['lost_units']))}, "
            f"revenue {_pct(static3['revenue_accept_rate'])}: rejected orders are "
            f"lower-value on average, so revenue is retained better than order "
            f"count suggests. But accepted OTIF is still "
            f"{_pct(static3['accepted_otif_mean'])}—the same as accept-all—so this "
            f"is revenue loss without a service gain."
        )
    lines.append(
        "- **Order, unit and revenue acceptance can diverge.** If revenue acceptance "
        "is lower than order acceptance, the rejected tail is high-value; if higher, "
        "the policy keeps high-value orders. Neither direction is “free” — the lost "
        "revenue column is the price of the smaller accepted pool."
    )
    lines.append(
        "- **Revenue is not margin.** The data has no COGS, slotting cost or "
        "fulfillment cost per order, so a high-revenue order is not necessarily a "
        "high-profit order; this is a revenue-at-risk lens, not an NPV/profit claim."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_revenue_acceptance_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Revenue-weighted order acceptance (Week 27)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "REVENUE_ACCEPTANCE_REPORT.md"
    summary = out / "revenue_acceptance_summary.json"
    report.write_text(
        build_revenue_acceptance_report(payload, title=title), encoding="utf-8"
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
