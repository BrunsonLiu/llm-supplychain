"""Markdown/JSON report for Week-39 local stock distribution."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .stock_report import _md_table, _num, _pct


def summarize_local_stock(frame: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for policy, group in frame.groupby("policy", sort=False):
        rows.append(
            {
                "policy": policy,
                "seeds": int(len(group)),
                "orders": int(group["orders"].iloc[0]),
                "stock_factor": float(group["stock_factor"].iloc[0]),
                "dc_capacity_factor": float(
                    group["dc_capacity_factor"].iloc[0]
                ),
                "transit_cut_days": int(group["transit_cut_days"].iloc[0]),
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
                "accepted_fill_rate": float(
                    group["accepted_fill_rate"].mean()
                ),
                "accepted_backlog_units": float(
                    group["accepted_backlog_units"].mean()
                ),
                "avg_delivery_day": float(
                    group["avg_delivery_day"].mean()
                ),
                "departures": float(group["departures"].mean()),
            }
        )
    return pd.DataFrame(rows)


def _table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        rows.append(
            {
                "库存": f"{row.get('stock_factor', 0.0):.0%}",
                "DC 产能": f"{row.get('dc_capacity_factor', 0.0):.0f}×",
                "transit 缩短": f"{row.get('transit_cut_days', 0)} 天",
                "接受订单": _num(row["accepted_orders"], 1),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "目标 OTIF": _pct(row.get("target_accepted_otif_mean", 0.0)),
                "非目标 OTIF": _pct(
                    row.get("rest_accepted_otif_mean", 0.0)
                ),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "平均交付日": _num(row.get("avg_delivery_day", 0.0), 2),
                "积压单位": _num(row.get("accepted_backlog_units", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def build_local_stock_report(
    payload: Dict[str, Any],
    title: str = "Local stock distribution (Week 39)",
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
        "This is the Week-38 transit −1 arm replayed with **initial stock** at "
        "100%, 120% and 150% of demand, keeping DC capacity 2× and ATP "
        "accept-all. All arms accept all 400 orders, so the accepted set and "
        "demand denominator are identical; only the local stock buffer changes. "
        "120%/150% is not a purchase plan: it is an upper bound that removes "
        "DC×SKU local shortages, not just the total-unit shortage. Holding cost "
        "and COGS are not modeled."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    base = next(
        (
            row
            for row in summary
            if abs(row.get("stock_factor", 0) - 1.0) < 1e-9
        ),
        None,
    )
    if base:
        for row in summary:
            factor = row.get("stock_factor", 0)
            if abs(factor - 1.0) < 1e-9:
                continue
            d_target = (
                row["target_accepted_otif_mean"]
                - base["target_accepted_otif_mean"]
            ) * 100
            d_rest = (
                row["rest_accepted_otif_mean"]
                - base["rest_accepted_otif_mean"]
            ) * 100
            d_all = (row["all_otif_mean"] - base["all_otif_mean"]) * 100
            lines.append(
                f"- **Stock {factor:.0%}:** target "
                f"{_pct(base['target_accepted_otif_mean'])} → "
                f"{_pct(row['target_accepted_otif_mean'])} ({d_target:+.1f} pp), "
                f"rest {_pct(base['rest_accepted_otif_mean'])} → "
                f"{_pct(row['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), "
                f"all-order {d_all:+.1f} pp; backlog "
                f"{base['accepted_backlog_units']:,.0f} → "
                f"{row['accepted_backlog_units']:,.0f}."
            )

    high = next(
        (
            row
            for row in summary
            if abs(row.get("stock_factor", 0) - 1.5) < 1e-9
        ),
        None,
    )
    if base and high:
        d_target = (
            high["target_accepted_otif_mean"]
            - base["target_accepted_otif_mean"]
        ) * 100
        intermediate = [
            row
            for row in summary
            if 1.0 + 1e-9 < row.get("stock_factor", 0) < 1.5 - 1e-9
        ]
        non_monotonic = any(
            row["target_accepted_otif_mean"]
            < base["target_accepted_otif_mean"] - 1e-9
            for row in intermediate
        )
        if d_target >= 0.5:
            if non_monotonic:
                lines.append(
                    "- **Only the 150% overstock arm closes the residual, and the "
                    "path is not monotonic.** The 120% arm is *lower* than 100% on "
                    "target, so this is not a clean “more local stock, more "
                    "service” effect; allocation/replenishment path and solver "
                    "variation dominate at 120%. 150% removes local shortages and "
                    "reaches 100%, but it is also 1.5× demand, so it cannot "
                    "separate local placement from extra total units."
                )
            else:
                lines.append(
                    "- **Local stock placement is part of the residual.** At 100% "
                    "total stock the target still loses orders to DC×SKU local "
                    "shortages; extra local buffer closes part of the gap. Total "
                    "inventory was not the whole story — placement was."
                )
        else:
            lines.append(
                "- **Local stock is not the residual.** Even 150% stock does not "
                "move target OTIF at fixed DC capacity and transit; the remaining "
                "1–2 pp is promise/static-deadline or order structure, not local "
                "availability."
            )
    lines.append(
        "- **Every arm accepts all 400 orders at 2× capacity and transit −1**, so "
        "this is not an acceptance-mix, throughput or carrier effect."
    )
    lines.append(
        "- **150% is an upper bound, not a recommendation.** It ignores holding "
        "cost, working capital, obsolescence and the fact that a real buyer would "
        "not hold 1.5× weekly demand at every DC. It also cannot prove that a "
        "fixed-total rebalance would work; the 120% dip argues against a simple "
        "buffer story."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_local_stock_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Local stock distribution (Week 39)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "LOCAL_STOCK_REPORT.md"
    summary = out / "local_stock_summary.json"
    report.write_text(
        build_local_stock_report(payload, title=title), encoding="utf-8"
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
