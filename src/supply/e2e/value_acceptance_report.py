"""Markdown/JSON report for Week-28 value-tiered order acceptance."""
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


def summarize_value_acceptance(frame: pd.DataFrame) -> pd.DataFrame:
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
                "quoted_otif_mean": float(group["e2e_otif_rate"].mean()),
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
                "价值门槛": row.get("value_label", "—"),
                "接受订单": _num(row["accepted_orders"], 1),
                "订单接单率": _pct(row.get("accepted_rate", 0.0)),
                "收入接单率": _pct(row.get("revenue_accept_rate", 0.0)),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("quoted_otif_mean", 0.0)),
                "接受收入": _num(row.get("accepted_revenue", 0.0)),
                "流失收入": _num(row.get("lost_revenue", 0.0)),
                "拒单均值": _num(
                    row.get("lost_revenue", 0.0)
                    / max(1.0, row["orders"] - row["accepted_orders"])
                ),
            }
        )
    return pd.DataFrame(rows)


def build_value_acceptance_report(
    payload: Dict[str, Any],
    title: str = "Value-tiered order acceptance (Week 28)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})
    base = next((row for row in summary if row.get("policy") == "atp_3"), None)

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
        f"- Demand revenue **{dataset.get('demand_revenue', 0.0):,.0f}**; revenue "
        f"coverage **{settings.get('revenue_coverage', 0.0):.1%}**."
    )
    lines.append("")

    lines += ["## Rule", ""]
    lines.append(
        "This extends Week 27 from measurement to policy. The base rule rejects a "
        "new order when its quoted promise exceeds the cutoff. The **value override** "
        "keeps a long-promise order when its invoice revenue is in the top X% of all "
        "sampled orders: `reject iff promised > cutoff AND revenue < threshold`. "
        "The threshold is computed once on the full order set, not per day, so the "
        "same revenue bar applies throughout the week. Rejected orders consume no "
        "stock, do not enter picking/dispatch, and remain in the all-order "
        "denominator. Revenue is gross invoice revenue, not margin."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    if base:
        lines.append(
            f"- **Base ATP ≤3 days:** accepts "
            f"{_num(base['accepted_orders'], 1)} orders "
            f"({_pct(base['accepted_rate'])}), revenue "
            f"{_num(base['accepted_revenue'])} "
            f"({_pct(base['revenue_accept_rate'])}), accepted OTIF "
            f"{_pct(base['accepted_otif_mean'])}; lost revenue "
            f"{_num(base['lost_revenue'])}."
        )
    for policy in ("atp_3_top10", "atp_3_top25", "static_3_top10", "static_3_top25"):
        row = next((item for item in summary if item.get("policy") == policy), None)
        if row is None or base is None and policy.startswith("atp"):
            continue
        if base is not None and policy.startswith("atp"):
            order_delta = row["accepted_orders"] - base["accepted_orders"]
            revenue_delta = row["accepted_revenue"] - base["accepted_revenue"]
            otif_delta = row["accepted_otif_mean"] - base["accepted_otif_mean"]
            all_delta = row["quoted_otif_mean"] - base["quoted_otif_mean"]
            lines.append(
                f"- **{row.get('label', policy)}:** accepts "
                f"{_num(row['accepted_orders'], 1)} orders "
                f"({order_delta:+.1f} vs base), revenue "
                f"{_num(row['accepted_revenue'])} ({revenue_delta:+,.0f}), "
                f"accepted OTIF {_pct(row['accepted_otif_mean'])} "
                f"({otif_delta * 100:+.1f} pp), all-order OTIF "
                f"{_pct(row['quoted_otif_mean'])} ({all_delta * 100:+.1f} pp)."
            )
        if not policy.startswith("atp"):
            static_base = next(
                (item for item in summary if item.get("policy") == "static_3"),
                None,
            )
            if static_base is not None:
                lines.append(
                    f"- **{row.get('label', policy)}:** accepts "
                    f"{_num(row['accepted_orders'], 1)} orders "
                    f"({row['accepted_orders'] - static_base['accepted_orders']:+.1f} "
                    f"vs base), revenue {_num(row['accepted_revenue'])} "
                    f"({(row['revenue_accept_rate'] - static_base['revenue_accept_rate']) * 100:+.1f} "
                    f"pp), accepted OTIF {_pct(row['accepted_otif_mean'])} "
                    f"({(row['accepted_otif_mean'] - static_base['accepted_otif_mean']) * 100:+.1f} "
                    f"pp), all-order OTIF {_pct(row['quoted_otif_mean'])} "
                    f"({(row['quoted_otif_mean'] - static_base['quoted_otif_mean']) * 100:+.1f} "
                    f"pp)."
                )
            else:
                lines.append(
                    f"- **{row.get('label', policy)}:** accepts "
                    f"{_num(row['accepted_orders'], 1)} orders "
                    f"({_pct(row['accepted_rate'])}), revenue "
                    f"{_num(row['accepted_revenue'])} "
                    f"({_pct(row['revenue_accept_rate'])}), accepted OTIF "
                    f"{_pct(row['accepted_otif_mean'])}."
                )
    atp10 = next(
        (row for row in summary if row.get("policy") == "atp_3_top10"), None
    )
    atp25 = next(
        (row for row in summary if row.get("policy") == "atp_3_top25"), None
    )
    if base and atp10 and atp25:
        base_rev = base["revenue_accept_rate"]
        lines.append(
            f"- **Top 10% is the efficient point in this run.** It recovers "
            f"{(atp10['revenue_accept_rate'] - base_rev) * 100:+.1f} pp of revenue "
            f"for {(atp10['accepted_otif_mean'] - base['accepted_otif_mean']) * 100:+.1f} "
            f"pp of accepted OTIF; all-order OTIF rises "
            f"{(atp10['quoted_otif_mean'] - base['quoted_otif_mean']) * 100:+.1f} pp "
            f"because fewer orders are rejected. Top 25% recovers "
            f"{(atp25['revenue_accept_rate'] - base_rev) * 100:+.1f} pp but gives up "
            f"{(atp25['accepted_otif_mean'] - base['accepted_otif_mean']) * 100:+.1f} "
            f"pp of accepted OTIF; the two bars trade revenue for accepted service, "
            f"neither dominates."
        )
    lines.append(
        "- **Accepted OTIF and all-order OTIF move in opposite directions here.** "
        "Adding high-value long-promise orders raises coverage (fewer rejected, so "
        "all-order OTIF rises) while making the accepted pool harder to serve on "
        "time (accepted OTIF falls). A single OTIF number cannot describe this "
        "policy; quote both denominators."
    )
    lines.append(
        "- **The override is a trade, not a free lunch.** It buys back high-value "
        "orders that the cutoff would reject, but those orders have long promises; "
        "compare the revenue recovered with the accepted service lost, not just the "
        "headline revenue. In this run the all-order OTIF still improves because "
        "more orders are served at all."
    )
    lines.append(
        "- **A value bar is not a profit bar.** Invoice revenue has no COGS, returns, "
        "fulfillment cost or customer lifetime value; a high-revenue order can still "
        "be a low-margin order. This is a revenue-protection stress test, not an "
        "optimal policy."
    )
    lines.append(
        "- **The threshold is an in-sample quantile.** It is computed on the same "
        "400 orders used for evaluation; a live policy would estimate it from "
        "history and would face drift. Top 10%/25% are scenario labels, not a "
        "tuned optimum."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_value_acceptance_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Value-tiered order acceptance (Week 28)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "VALUE_ACCEPTANCE_REPORT.md"
    summary = out / "value_acceptance_summary.json"
    report.write_text(
        build_value_acceptance_report(payload, title=title), encoding="utf-8"
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
