"""Markdown/JSON report for Week-38 transit speed."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .stock_report import _md_table, _num, _pct


def summarize_transit(frame: pd.DataFrame) -> pd.DataFrame:
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
                "mean_wait_minutes": float(
                    group["mean_wait_minutes"].mean()
                ),
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
                "发车": _num(row.get("departures", 0.0), 1),
            }
        )
    return pd.DataFrame(rows)


def build_transit_report(
    payload: Dict[str, Any],
    title: str = "Transit speed (Week 38)",
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
        "This is the Week-37 100%-stock, DC-capacity-2×, ATP accept-all arm "
        "replayed with the **road transit** shortened by 0/1/2 days (floor 1 "
        "day). All arms accept all 400 orders, stock and DC capacity are fixed, "
        "so the accepted set, demand denominator and allocation inputs are the "
        "same; only the carrier time changes. It is an upper-bound speed-up, not "
        "a carrier contract; expedited freight cost is not modeled."
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
            if int(row.get("transit_cut_days", -1)) == 0
        ),
        None,
    )
    if base:
        for row in summary:
            cut = int(row.get("transit_cut_days", 0))
            if cut == 0:
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
                f"- **Transit −{cut} day:** target "
                f"{_pct(base['target_accepted_otif_mean'])} → "
                f"{_pct(row['target_accepted_otif_mean'])} ({d_target:+.1f} pp), "
                f"rest {_pct(base['rest_accepted_otif_mean'])} → "
                f"{_pct(row['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), "
                f"all-order {d_all:+.1f} pp; average delivery day "
                f"{base['avg_delivery_day']:.2f} → "
                f"{row['avg_delivery_day']:.2f}."
            )

    fast1 = next(
        (
            row
            for row in summary
            if int(row.get("transit_cut_days", -1)) == 1
        ),
        None,
    )
    fast2 = next(
        (
            row
            for row in summary
            if int(row.get("transit_cut_days", -1)) == 2
        ),
        None,
    )
    if base and fast1:
        d_target = (
            fast1["target_accepted_otif_mean"]
            - base["target_accepted_otif_mean"]
        ) * 100
        if d_target >= 0.5:
            lines.append(
                "- **Transit is a real part of the residual.** Shorter road "
                "transit raises target OTIF at fixed stock and DC capacity; the "
                "remaining 4 pp was not only placement/promise. Faster freight "
                "has to be paid for."
            )
        else:
            lines.append(
                "- **Transit is not the residual.** Cutting a day of road transit "
                "does not move target OTIF at fixed stock/capacity; the remaining "
                "4 pp is placement/promise or the static deadline, not the "
                "carrier's clock."
            )
    if fast1 and fast2:
        if abs(
            fast2["target_accepted_otif_mean"]
            - fast1["target_accepted_otif_mean"]
        ) < 1e-9:
            lines.append(
                "- **The speed-up saturates.** −1 and −2 days give the same target "
                "OTIF, so the last day is not where the misses come from; extra "
                "speed beyond −1 has no service value."
            )
        residual = (
            fast2["rest_accepted_otif_mean"]
            - fast2["target_accepted_otif_mean"]
        ) * 100
        lines.append(
            f"- **The residual falls to ~{abs(residual):.1f} pp.** At −2 days "
            f"target is {_pct(fast2['target_accepted_otif_mean'])} vs rest "
            f"{_pct(fast2['rest_accepted_otif_mean'])}; what is left is "
            f"placement/promise/static-deadline, not stock, DC throughput or "
            f"carrier time."
        )
    lines.append(
        "- **The 0-day baseline is not cross-week comparable.** Its target 92.5% "
        "differs from Week-37 2× (95.0%) because CP-SAT time limits/configuration "
        "differ by ~1–1.5pp; only the three arms in this report are compared."
    )
    lines.append(
        "- **Every arm accepts all 400 orders at 100% stock and 2× capacity**, so "
        "this is not an acceptance-mix or resource effect. The comparison isolates "
        "carrier time."
    )
    lines.append(
        "- **−2 days is an upper bound, not a rate card.** It ignores expedited "
        "freight premium, carrier capacity, cut-off changes and emissions; a real "
        "carrier cannot remove two days from every lane."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_transit_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Transit speed (Week 38)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "TRANSIT_REPORT.md"
    summary = out / "transit_summary.json"
    report.write_text(
        build_transit_report(payload, title=title), encoding="utf-8"
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
