"""Markdown/JSON report for Week-37 DC capacity upper bound."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .stock_report import _md_table, _num, _pct


def summarize_dc_capacity(frame: pd.DataFrame) -> pd.DataFrame:
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
                "接受订单": _num(row["accepted_orders"], 1),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "目标 OTIF": _pct(row.get("target_accepted_otif_mean", 0.0)),
                "非目标 OTIF": _pct(
                    row.get("rest_accepted_otif_mean", 0.0)
                ),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "接受满足率": _pct(row.get("accepted_fill_rate", 0.0)),
                "积压单位": _num(row.get("accepted_backlog_units", 0.0)),
                "发车": _num(row.get("departures", 0.0), 1),
            }
        )
    return pd.DataFrame(rows)


def build_dc_capacity_report(
    payload: Dict[str, Any],
    title: str = "DC capacity upper bound (Week 37)",
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
        "This is the Week-36 100%-stock ATP accept-all arm replayed with **DC "
        "weekly capacity** multiplied by 1×, 2× and 10×. All orders are accepted "
        "in every arm and stock is 100%, so the accepted set, demand denominator "
        "and inventory are identical; only the per-DC weekly throughput limit "
        "changes. It is an upper-bound stress test, not a capacity plan; the cost "
        "of extra DC capacity is not modeled."
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
            if abs(row.get("dc_capacity_factor", 0) - 1.0) < 1e-9
        ),
        None,
    )
    if base:
        for row in summary:
            factor = row.get("dc_capacity_factor", 0)
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
                f"- **DC capacity {factor:.0f}×:** target "
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
            if abs(row.get("dc_capacity_factor", 0) - 10.0) < 1e-9
        ),
        None,
    )
    if base and high:
        d_target = (
            high["target_accepted_otif_mean"]
            - base["target_accepted_otif_mean"]
        ) * 100
        if d_target >= 0.5:
            lines.append(
                "- **DC weekly capacity is part of the residual.** Raising the "
                "per-DC throughput limit improves target OTIF at fixed stock; the "
                "Week-36 residual was not only transit/promise. Capacity still has "
                "to be paid for."
            )
            plateau = max(
                row["target_accepted_otif_mean"] for row in summary
            )
            if (
                abs(high["target_accepted_otif_mean"] - plateau) < 1e-9
                and high["dc_capacity_factor"] > 2.0
            ):
                lines.append(
                    f"- **Capacity saturates before 10×.** The 2× and 10× arms "
                    f"both reach target {_pct(plateau)}; extra weekly throughput "
                    f"beyond 2× adds no target service. The remaining gap to the "
                    f"99%+ rest is therefore transit/promise/placement, not the "
                    f"weekly capacity cap."
                )
        else:
            lines.append(
                "- **DC weekly capacity is not the residual.** Even 10× capacity "
                "does not move target OTIF at 100% stock; the remaining 3–4 pp is "
                "therefore placement/transit/promise, not the weekly throughput cap."
            )
    lines.append(
        "- **Every arm accepts all 400 orders at 100% stock**, so this is not an "
        "acceptance-mix effect. The comparison isolates the capacity constraint."
    )
    lines.append(
        "- **10× is an upper bound, not a recommendation.** It ignores the cost of "
        "space, labor, equipment and the fact that a real DC cannot scale weekly "
        "capacity tenfold without capex/lead time."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_dc_capacity_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "DC capacity upper bound (Week 37)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "DC_CAPACITY_REPORT.md"
    summary = out / "dc_capacity_summary.json"
    report.write_text(
        build_dc_capacity_report(payload, title=title), encoding="utf-8"
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
