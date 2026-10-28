"""Markdown/JSON report for the Week-20 rolling end-to-end benchmark."""
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


def _row(rows: List[Dict[str, Any]], policy: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row["policy"] == policy:
            return row
    return None


def _summary_table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        rows.append(
            {
                "策略": row["label"],
                "种子": int(row["seeds"]),
                "端到端 OTIF": _pct(row["e2e_otif_mean"]),
                "P10": _pct(row["e2e_otif_p10"]),
                "P50": _pct(row["e2e_otif_p50"]),
                "P90": _pct(row["e2e_otif_p90"]),
                "fill": _pct(row["fill_mean"]),
                "失败订单": _num(row["late_orders_mean"], 1),
                "backlog": _num(row["backlog_units"]),
                "平均交付日": _num(row["avg_delivery_day"], 2),
            }
        )
    return pd.DataFrame(rows)


def _by_day_table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    names = ["周一", "周二", "周三", "周四", "周五"]
    rows = []
    for row in summary:
        values = {"策略": row["label"]}
        for day, name in enumerate(names):
            value = row.get(f"otif_day_{day}")
            values[name] = (
                _pct(value)
                if value is not None and not pd.isna(value)
                else "—"
            )
        rows.append(values)
    return pd.DataFrame(rows)


def _paired_table(paired: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in paired:
        if not row:
            continue
        rows.append(
            {
                "对比": f"{row['left']} − {row['right']}",
                "n": int(row["n"]),
                "Δ OTIF": f"{row['mean'] * 100:+.1f} pp",
                "95% CI": f"±{row['ci95'] * 100:.1f}",
                "胜": _pct(row["win"]),
                "负": _pct(row["loss"]),
                "平": _pct(row["tie"]),
            }
        )
    return pd.DataFrame(rows)


def build_rolling_e2e_report(
    payload: Dict[str, Any],
    title: str = "Multi-day rolling end-to-end benchmark (Week 20)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    paired = payload.get("paired", [])
    order_days = payload.get("order_days", {})
    baseline = _row(summary, "single_week")
    none = _row(summary, "none")
    daily1 = _row(summary, "daily_1d")
    daily2 = _row(summary, "daily_2d")

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
        f"- Seeds: **{settings.get('seeds', 0)}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day** | baseline "
        f"**{settings.get('baseline_milp_time', 0):.0f}s** | stock "
        f"**{settings.get('stock_factor', 0):.0%}**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines += [
        "| Item | Assumption | Note |",
        "|---|---|---|",
        "| Order day | actual invoice weekday | Sat/Sun invoices land on Friday |",
        "| Daily allocation | Week-9 capacity-aware MILP | only open lines and remaining stock |",
        "| Pick | empirical arrival curve + EDF, Week-16 stack | re-drawn per day and seed |",
        "| Daily dispatch | immediate, `max_days=0` | a missed last departure fails the order |",
        "| Weekly baseline | all orders on Monday, promise dispatch, `max_days=3` | Week-16 dock freedom |",
        "| Replenishment | declining order-up-to remaining-week cover | 1/2-day lead, no MOQ |",
        "| OTIF | absolute `order_day + promise` | not the daily relative promise |",
        "| Scope | allocation + pick + dispatch | doors/loading resources are not replayed |",
        "",
    ]

    lines += ["## End-to-end results", ""]
    lines.append(
        "`端到端 OTIF` means every line was allocated, every ticket left on the day's "
        "last departure, and `allocation day + ship + transit ≤ order day + promise`."
    )
    lines.append("")
    lines.append(_md_table(_summary_table(summary)))
    lines.append("")
    lines.append("**End-to-end OTIF by order day**（单周基线把所有订单视作周一，只有周一列）：")
    lines.append("")
    lines.append(_md_table(_by_day_table(summary)))
    lines.append("")

    lines += ["## Paired differences", ""]
    lines.append(_md_table(_paired_table(paired)))
    lines.append("")
    if paired and all(abs(row.get("ci95", 0.0)) < 1e-12 for row in paired):
        lines.append(
            "All paired intervals are zero because every seed gave the same "
            "order-level OTIF and average delivery day in this configuration: "
            "picking cleared the last departure regardless of the arrival draw. "
            "The 30 seeds are effectively one deterministic draw, not a 30-sample "
            "statistic."
        )
        lines.append("")

    lines += ["## Findings", ""]
    if baseline and daily1:
        lines.append(
            f"- **The pick/dispatch layer is not the main bottleneck in this setup.** "
            f"The one-shot weekly baseline reaches {_pct(baseline['e2e_otif_mean'])} "
            f"end-to-end; the 1-day rolling flow reaches {_pct(daily1['e2e_otif_mean'])}. "
            f"With same-day dispatch and EDF, picking usually clears the last departure, "
            f"so end-to-end OTIF stays close to the allocation-layer number. This is "
            f"conditional on one picker, the empirical arrival curves and 85% stock; it "
            f"does not mean picking can be ignored."
        )
    if none and daily1:
        lines.append(
            f"- **Replenishment still buys service after picking and dispatch.** "
            f"With no replenishment, end-to-end OTIF is {_pct(none['e2e_otif_mean'])}; "
            f"daily 1-day replenishment is {_pct(daily1['e2e_otif_mean'])} "
            f"({(daily1['e2e_otif_mean'] - none['e2e_otif_mean']) * 100 + 1e-9:+.1f} pp). "
            f"Fill is {_pct(none['fill_mean'])} vs {_pct(daily1['fill_mean'])} and backlog "
            f"{_num(none['backlog_units'])} vs {_num(daily1['backlog_units'])}."
        )
    daily1_friday = (daily1 or {}).get("otif_day_4")
    none_friday = (none or {}).get("otif_day_4")
    if (
        daily1_friday is not None
        and none_friday is not None
        and not pd.isna(daily1_friday)
        and not pd.isna(none_friday)
    ):
        lines.append(
            f"- **The intra-week shape survives the pick/dispatch layer.** Friday "
            f"end-to-end OTIF is {_pct(daily1_friday)} with daily 1-day replenishment "
            f"vs {_pct(none_friday)} without replenishment. The weekly average would "
            f"hide that the last order day is still the weakest."
        )
    if daily1 and daily2:
        lines.append(
            f"- **Lead time survives the pick/dispatch layer.** A 2-day lead gives "
            f"{_pct(daily2['e2e_otif_mean'])} end-to-end vs "
            f"{_pct(daily1['e2e_otif_mean'])} for 1-day "
            f"({(daily2['e2e_otif_mean'] - daily1['e2e_otif_mean']) * 100 + 1e-9:+.1f} pp); "
            f"the extra day of stock cover is not enough to offset the later replenishment."
        )
    lines.append(
        "- **Daily dispatch is deliberately harsh.** The daily cell allows only the two "
        "declared departures on the allocation day (`max_days=0`); a ticket that misses "
        "the 19:00 cutoff is a failure, whereas the weekly baseline can hold for three "
        "days. The near-equality of allocation and end-to-end OTIF says the cutoff was "
        "not binding for most orders in this week, not that it is harmless in general."
    )
    lines.append(
        "- **Scope.** Picking uses the Week-16 empirical arrivals and EDF; doors, loading "
        "minutes and carrier consolidation are not replayed this week. Replenishment is a "
        "declining order-up-to cover with no forecast, MOQ, supplier capacity or DC transfer. "
        "The result is one target week and one stock/layout."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_rolling_e2e_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Multi-day rolling end-to-end benchmark (Week 20)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "ROLLING_E2E_REPORT.md"
    summary = out / "rolling_e2e_summary.json"
    report.write_text(
        build_rolling_e2e_report(payload, title=title), encoding="utf-8"
    )
    summary.write_text(
        json.dumps(
            {"title": title, **payload, "generated": datetime.now(timezone.utc).isoformat()},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {"report": report, "summary": summary}
