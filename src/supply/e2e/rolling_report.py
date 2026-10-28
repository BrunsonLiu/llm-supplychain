"""Markdown/JSON report for the Week-19 rolling-allocation benchmark."""
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


def _row(summary: List[Dict[str, Any]], policy: str) -> Optional[Dict[str, Any]]:
    for row in summary:
        if row["policy"] == policy:
            return row
    return None


def _delta(left: Optional[Dict[str, Any]], right: Optional[Dict[str, Any]], key: str) -> str:
    if left is None or right is None:
        return "n/a"
    return f"{(float(left[key]) - float(right[key])) * 100:+.1f} pp"


def _summary_table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        days = row.get("days")
        days = 1 if days is None or pd.isna(days) else int(days)
        rows.append(
            {
                "策略": row["label"],
                "天数": days,
                "fill": _pct(row["fill_rate"]),
                "分单 OTIF": _pct(row["otif_rate"]),
                "迟到 units": _num(row.get("late_units", 0)),
                "期末 backlog": _num(row.get("backlog_units", 0)),
                "补货 units": _num(row.get("replenished_units", 0)),
                "平均库存": _num(row.get("avg_inventory_units", 0)),
            }
        )
    return pd.DataFrame(rows)


def _by_day_table(by_day: List[Dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(by_day)
    if frame.empty:
        return frame
    pivot = frame.pivot_table(
        index="day",
        columns="label",
        values="otif_rate",
        aggfunc="mean",
    )
    pivot = pivot.reset_index()
    pivot.columns = ["订单日"] + [str(column) for column in pivot.columns[1:]]
    for column in pivot.columns[1:]:
        pivot[column] = pivot[column].map(_pct)
    return pivot


def build_rolling_report(
    payload: Dict[str, Any],
    title: str = "Multi-day rolling allocation and replenishment (Week 19)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    by_day = payload.get("by_order_day", [])
    order_days = payload.get("order_days", {})

    base = _row(summary, "single_week")
    none = _row(summary, "none")
    daily1 = _row(summary, "daily_1d")
    daily2 = _row(summary, "daily_2d")
    safety = _row(summary, "daily_1d_safety")
    batch = _row(summary, "batch_2d")
    none_days = {
        int(row["day"]): row
        for row in by_day
        if row.get("policy") == "none"
    }
    monday = _pct(none_days[0]["otif_rate"]) if 0 in none_days else "n/a"
    friday = (
        _pct(none_days[max(none_days)]["otif_rate"]) if none_days else "n/a"
    )

    lines: List[str] = [f"# {title}", ""]
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
        f"- MILP: **{settings.get('milp_time', 0):.0f}s/day/policy**, "
        f"stock factor **{settings.get('stock_factor', 0):.0%}**, "
        f"safety **{settings.get('safety', 0):.0%}**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines += [
        "| Item | Assumption | Note |",
        "|---|---|---|",
        "| Order day | actual invoice weekday | Sat/Sun invoices land on Friday |",
        "| Flow days | 5 weekdays | Monday–Friday of the target week |",
        "| Allocation | Week-9 capacity-aware MILP, re-solved daily | only still-open lines and remaining stock |",
        "| Delivery day | allocation day + declared transit days | transit already includes 1 handling day |",
        "| Replenishment | order-up-to remaining-week cover | target declines from 85% weekly stock to zero; no extra total supply |",
        "| Safety | +10% over the declining target | declared buffer, not a service-level policy |",
        "| Baseline | one-shot weekly allocation | Week-18 allocation layer, same deadline rule |",
        "| Scope | allocation only | picking, release, dispatch and doors are not replayed |",
        "",
    ]

    lines += ["## Weekly snapshot vs rolling flow", ""]
    lines.append(
        "`分单 OTIF` = every line allocated and `allocation day + transit ≤ order day + promise`; "
        "`fill` includes late allocations. The baseline is the same 400 orders and stock snapshot "
        "allocated once, so the difference is the timing/carryover effect."
    )
    lines.append("")
    lines.append(_md_table(_summary_table(summary)))
    lines.append("")

    lines += ["## OTIF by order day", ""]
    lines.append(_md_table(_by_day_table(by_day)))
    lines.append("")

    lines += ["## Findings", ""]
    lines.append(
        f"- **A weekly snapshot hides the intra-week service decay.** The one-shot baseline allocates "
        f"{_pct(base['fill_rate']) if base else 'n/a'} of units at "
        f"{_pct(base['otif_rate']) if base else 'n/a'} OTIF; the no-replenishment flow is similar on "
        f"fill ({_pct(none['fill_rate']) if none else 'n/a'}) but {_delta(none, base, 'otif_rate')} "
        f"on OTIF. The weekly number is not a service level: the no-replenishment by-day OTIF falls from "
        f"{monday} on Monday to {friday} on Friday as the initial stock is consumed."
    )
    lines.append(
        f"- **Daily re-optimization is not the same as one weekly allocation.** Even with no "
        f"replenishment, rolling allocation is {_delta(none, base, 'otif_rate')} versus the one-shot "
        f"baseline: the weekly MILP commits stock to early orders, while the daily MILP can leave it "
        f"for orders that are still open. This is a scheduling effect, not extra inventory."
    )
    lines.append(
        f"- **Replenishment moves stock through the week; it does not create a second week of supply.** "
        f"With a 1-day lead and a declining order-up-to target, OTIF moves "
        f"{_delta(daily1, none, 'otif_rate')} versus no replenishment, fill "
        f"{_pct(daily1['fill_rate']) if daily1 else 'n/a'}, backlog "
        f"{_num(daily1['backlog_units']) if daily1 else 'n/a'} vs "
        f"{_num(none['backlog_units']) if none else 'n/a'}, with "
        f"{_num(daily1['replenished_units']) if daily1 else 'n/a'} units reordered. "
        f"Because the target shrinks with the remaining week, the policy redistributes the same 85% "
        f"stock toward later order days rather than lifting total availability."
    )
    lines.append(
        f"- **Lead time is a service tax.** A 2-day lead moves OTIF {_delta(daily2, daily1, 'otif_rate')} "
        f"versus 1-day, with fill {_pct(daily2['fill_rate']) if daily2 else 'n/a'}, backlog "
        f"{_num(daily2['backlog_units']) if daily2 else 'n/a'} and late units "
        f"{_num(daily2['late_units']) if daily2 else 'n/a'} vs "
        f"{_num(daily1['late_units']) if daily1 else 'n/a'}: a 2-day lead fits only the day-0 order into "
        f"the five-day flow, so the last order days receive little or no replenishment."
    )
    lines.append(
        f"- **A 10% safety add-on is not a free buffer.** It moves OTIF "
        f"{_delta(safety, daily1, 'otif_rate')} and fill "
        f"{_pct(safety['fill_rate']) if safety else 'n/a'} versus the 1-day policy, while raising "
        f"average inventory from {_num(daily1['avg_inventory_units']) if daily1 else 'n/a'} to "
        f"{_num(safety['avg_inventory_units']) if safety else 'n/a'}; the extra units help only if the "
        f"shortage is on the replenished SKU, and they are still capped by the 85% weekly snapshot."
    )
    lines.append(
        f"- **Batching every two days is dominated by daily replenishment.** Batch OTIF is "
        f"{_pct(batch['otif_rate']) if batch else 'n/a'} vs "
        f"{_pct(daily1['otif_rate']) if daily1 else 'n/a'} for daily 1-day; its ending backlog is also "
        f"higher ({_num(batch['backlog_units']) if batch else 'n/a'} vs "
        f"{_num(daily1['backlog_units']) if daily1 else 'n/a'}), and late units rise to "
        f"{_num(batch['late_units']) if batch else 'n/a'} vs "
        f"{_num(daily1['late_units']) if daily1 else 'n/a'}. The batch delays allocation without "
        f"clearing more units; the five-day flow is too short for the saved cycles to amortize."
    )
    lines.append(
        "- **Service decays within the week.** The by-day table is the operational warning: early "
        "orders are served from initial stock, late orders depend on replenishment timing. A weekly "
        "OTIF number can hide a Friday stockout."
    )
    lines.append(
        "- **Scope.** This is the inventory-carryover layer only. Picking, online release, dispatch "
        "and dock doors are not replayed; replenishment is a declining order-up-to cover with no MOQ, "
        "supplier capacity or DC transfer; the result is one week, one stock snapshot and one layout."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")

    return "\n".join(lines)


def write_rolling_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Multi-day rolling allocation and replenishment (Week 19)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "ROLLING_REPORT.md"
    summary = out / "rolling_summary.json"
    report.write_text(build_rolling_report(payload, title=title), encoding="utf-8")
    body = {
        "title": title,
        **payload,
        "generated": datetime.now(timezone.utc).isoformat(),
    }
    summary.write_text(
        json.dumps(body, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return {"report": report, "summary": summary}
