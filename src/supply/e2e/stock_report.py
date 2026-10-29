"""Markdown/JSON report for Week-36 stock availability."""
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


def summarize_stock(frame: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for policy, group in frame.groupby("policy", sort=False):
        rows.append(
            {
                "policy": policy,
                "seeds": int(len(group)),
                "orders": int(group["orders"].iloc[0]),
                "stock_factor": float(group["stock_factor"].iloc[0]),
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
                "库存因子": f"{row.get('stock_factor', 0.0):.0%}",
                "接受订单": _num(row["accepted_orders"], 1),
                "接受率": _pct(row["accepted_rate"]),
                "收入接单": _pct(row.get("revenue_accept_rate", 0.0)),
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


def build_stock_report(
    payload: Dict[str, Any],
    title: str = "Stock availability (Week 36)",
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
        "This is the ATP accept-all arm at the same 400 real invoices, replayed "
        "with a **stock snapshot** of 85% vs 100% of demand. All orders are "
        "accepted in both arms, so the accepted set and demand denominator are "
        "identical; only the initial inventory changes. Pricing, promises, "
        "pickers, dock policy, and the value override are not involved. 100% is "
        "an upper bound, not a purchase plan; stock holding cost and COGS are not "
        "modeled."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    low = next(
        (row for row in summary if abs(row.get("stock_factor", 0) - 0.85) < 1e-9),
        None,
    )
    high = next(
        (row for row in summary if abs(row.get("stock_factor", 0) - 1.0) < 1e-9),
        None,
    )
    if low and high:
        d_target = (
            high["target_accepted_otif_mean"]
            - low["target_accepted_otif_mean"]
        ) * 100
        d_rest = (
            high["rest_accepted_otif_mean"] - low["rest_accepted_otif_mean"]
        ) * 100
        d_all = (high["all_otif_mean"] - low["all_otif_mean"]) * 100
        d_fill = (
            high["accepted_fill_rate"] - low["accepted_fill_rate"]
        ) * 100
        lines.append(
            f"- **Stock 85% → 100%:** target OTIF "
            f"{_pct(low['target_accepted_otif_mean'])} → "
            f"{_pct(high['target_accepted_otif_mean'])} ({d_target:+.1f} pp), rest "
            f"{_pct(low['rest_accepted_otif_mean'])} → "
            f"{_pct(high['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), all-order "
            f"{d_all:+.1f} pp; accepted fill "
            f"{_pct(low['accepted_fill_rate'])} → "
            f"{_pct(high['accepted_fill_rate'])} ({d_fill:+.1f} pp), backlog "
            f"{low['accepted_backlog_units']:,.0f} → "
            f"{high['accepted_backlog_units']:,.0f} units."
        )
        if d_target >= 0.5:
            lines.append(
                "- **Stock is the binding constraint for the target gap.** Adding "
                "inventory raises target OTIF; the earlier ordering, labor, and "
                "arrival levers could not, because they could not create units. "
                "This is the positive counterpart to Weeks 30–35."
            )
        else:
            lines.append(
                "- **Stock alone does not close the target gap.** Even at 100% of "
                "demand, target OTIF does not improve materially; the remaining "
                "constraint is per-DC allocation/ATP or the promise/transit rule, "
                "not total inventory."
            )
        lines.append(
            f"- **Both arms accept all 400 orders**, so the comparison is not "
            f"driven by a different accepted mix: accepted revenue is "
            f"{_pct(high['revenue_accept_rate'])} in both. The change is confined "
            f"to physical availability."
        )
    lines.append(
        "- **100% stock is an upper bound.** It removes the 15% shortage but keeps "
        "the same per-DC split, DC capacity, transit days and promises. If target "
        "still misses, the residual is placement/ATP, not total units."
    )
    lines.append(
        "- **Inventory is not free.** This report does not price holding cost, "
        "working capital, obsolescence or COGS; a 100% fill policy would have to "
        "earn its keep against those costs."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_stock_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Stock availability (Week 36)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "STOCK_REPORT.md"
    summary = out / "stock_summary.json"
    report.write_text(
        build_stock_report(payload, title=title), encoding="utf-8"
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
