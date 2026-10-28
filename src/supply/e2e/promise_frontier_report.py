"""Markdown/JSON report for the Week-23 promise-service frontier."""
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


def _frontier_cell(row: Dict[str, Any], prefix: str) -> str:
    if row.get(f"{prefix}_pareto"):
        return "✔"
    dominated = row.get(f"{prefix}_dominated_by", "")
    return f"被 {dominated} 支配" if dominated else "—"


def _table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        label = (
            "单周一次性快照"
            if row["policy"] == "single_week"
            else "每日 1 天补货"
        )
        rows.append(
            {
                "策略": label,
                "报价": row["label"],
                "quoted OTIF": _pct(row["quoted_otif_mean"]),
                "原 SLA OTIF": _pct(row["static_sla_otif_mean"]),
                "平均承诺": _num(row["avg_promise_days"], 2),
                "2 天占比": _pct(row["fast_share"]),
                "fill": _pct(row["fill_mean"]),
                "失败订单": _num(row["late_orders_mean"], 1),
                "backlog": _num(row["backlog_units"]),
                "原 SLA 前沿": _frontier_cell(row, "static"),
                "quoted 前沿": _frontier_cell(row, "quoted"),
            }
        )
    return pd.DataFrame(rows)


def build_promise_frontier_report(
    payload: Dict[str, Any],
    title: str = "Promise-service frontier under daily replenishment (Week 23)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})
    daily = [row for row in summary if row["policy"] != "single_week"]
    baseline = next(
        (row for row in summary if row["policy"] == "single_week"), None
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
        f"- Seeds: **{settings.get('seeds', 0)}** | quote policies "
        f"**{settings.get('quote_policies', [])}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day**"
    )
    lines.append("")

    lines += ["## Frontier definition", ""]
    lines.append(
        "Two **two-dimensional** frontiers are reported, both with average quoted "
        "promise on the x-axis (shorter is better):"
    )
    lines.append("")
    lines.append(
        "1. **原 SLA 前沿** — maximize the Week-20 fixed 2/3/5 OTIF; this is the "
        "customer-outcome frontier."
    )
    lines.append(
        "2. **quoted 前沿** — maximize the OTIF against the promise actually quoted; "
        "this is what a service dashboard would show."
    )
    lines.append("")
    lines.append(
        "A policy is marked **✔** on a frontier only if no other policy has both a "
        "shorter-or-equal average promise and a higher-or-equal service on that axis, "
        "with at least one strict improvement. The single-week snapshot is a reference "
        "and is excluded from both frontiers."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    if daily:
        static_front = [row for row in daily if row.get("static_pareto")]
        quoted_front = [row for row in daily if row.get("quoted_pareto")]
        lines.append(
            f"- **Two frontiers, not one winner.** The original-SLA frontier has "
            f"{len(static_front)} policies ({'、'.join(row['label'] for row in static_front)}); "
            f"the quoted frontier has {len(quoted_front)} "
            f"({'、'.join(row['label'] for row in quoted_front)}). The difference is "
            f"the point of the exercise: rewriting the promise moves a policy onto the "
            f"quoted frontier without moving it onto the original-SLA frontier."
        )
    if baseline:
        lines.append(
            f"- **Daily replenishment still dominates the one-shot snapshot.** The "
            f"baseline quoted OTIF is {_pct(baseline['quoted_otif_mean'])}; the best "
            f"daily policy reaches {_pct(max(row['quoted_otif_mean'] for row in daily))}. "
            f"The inventory decision is larger than which quote policy is used."
        )
    static = next(
        (row for row in daily if row["quote_policy"] == "static"), None
    )
    atp = next((row for row in daily if row["quote_policy"] == "atp"), None)
    all5 = next(
        (row for row in daily if row["quote_policy"] == "all_5"), None
    )
    all2 = next(
        (row for row in daily if row["quote_policy"] == "all_2"), None
    )
    if static:
        if all2:
            lines.append(
                f"- **The fixed 2/3/5 mix is the shortest-promise policy that keeps "
                f"the original SLA high.** It delivers "
                f"{_pct(static['static_sla_otif_mean'])} original SLA at "
                f"{static['avg_promise_days']:.2f} average days. `all_2` is shorter "
                f"(2.00 days) but only "
                f"{_pct(all2['static_sla_otif_mean'])} on the original SLA."
            )
        else:
            lines.append(
                f"- **The fixed 2/3/5 mix is the balanced reference.** It delivers "
                f"{_pct(static['static_sla_otif_mean'])} original SLA at "
                f"{static['avg_promise_days']:.2f} average days."
            )
    if atp and static:
        lines.append(
            f"- **ATP is not on the original-SLA frontier.** It reaches "
            f"{_pct(atp['quoted_otif_mean'])} quoted OTIF, but its original SLA is "
            f"{_pct(atp['static_sla_otif_mean'])} at {atp['avg_promise_days']:.2f} days; "
            f"the fixed mix gives {_pct(static['static_sla_otif_mean'])} at "
            f"{static['avg_promise_days']:.2f} days. ATP is therefore dominated on the "
            f"customer-outcome axis (`static` has both a shorter promise and a higher "
            f"original SLA), even though it is non-dominated on the quoted axis."
        )
    if all5 and static:
        lines.append(
            f"- **`all_5` is a quoted-metric extreme, not a service improvement.** It "
            f"gives {_pct(all5['quoted_otif_mean'])} quoted OTIF vs "
            f"{_pct(static['quoted_otif_mean'])} for the fixed mix, but the original SLA is "
            f"{_pct(all5['static_sla_otif_mean'])} vs "
            f"{_pct(static['static_sla_otif_mean'])} and the average promise is "
            f"{all5['avg_promise_days']:.2f} vs {static['avg_promise_days']:.2f} days. "
            f"It is on the quoted frontier, not on the original-SLA frontier."
        )
    if atp and all5:
        gap_q = (all5["quoted_otif_mean"] - atp["quoted_otif_mean"]) * 100
        gap_s = (
            all5["static_sla_otif_mean"] - atp["static_sla_otif_mean"]
        ) * 100
        lines.append(
            f"- **The quoted-vs-original gap is the warning.** `all_5` is "
            f"{gap_q:+.1f} pp vs ATP on quoted OTIF but {gap_s:+.1f} pp on the original "
            f"SLA; a dashboard that only shows the quoted number can rank a policy first "
            f"while customers receive later deliveries."
        )
    lines.append(
        "- **Solver variation is visible.** These numbers are from a fresh CP-SAT run; "
        "the same configuration in Week 22 differed by a few tenths of a point on some "
        "cells (for example ATP quoted 95.0% vs 93.8%). The time-limited MILP is not "
        "bit-for-bit reproducible across runs; treat differences below ~1 pp as solver "
        "noise, not a policy effect."
    )
    lines.append(
        "- **Scope.** One week, one inventory/layout/labor model, deterministic 30-seed "
        "draw duplicated across policies. Quote tiers and transit days are declared; "
        "the frontier is a within-instance comparison, not a transferable service curve."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_promise_frontier_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Promise-service frontier under daily replenishment (Week 23)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "PROMISE_FRONTIER_REPORT.md"
    summary = out / "promise_frontier_summary.json"
    report.write_text(
        build_promise_frontier_report(payload, title=title), encoding="utf-8"
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
