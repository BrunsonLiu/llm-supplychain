"""Markdown/JSON report for Week-22 rolling promise re-quoting."""
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


def _lookup(
    summary: List[Dict[str, Any]], policy: str, quote: str
) -> Optional[Dict[str, Any]]:
    for row in summary:
        if row["policy"] == policy and row["quote_policy"] == quote:
            return row
    return None


def _table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        label = (
            "单周一次性快照"
            if row["policy"] == "single_week"
            else row["label"]
        )
        rows.append(
            {
                "策略": label,
                "报价": row["quote_policy"],
                "quoted OTIF": _pct(row["quoted_otif_mean"]),
                "原 SLA OTIF": _pct(row["static_sla_otif_mean"]),
                "平均承诺": _num(row["avg_promise_days"], 2),
                "2 天占比": _pct(row["fast_share"]),
                "fill": _pct(row["fill_mean"]),
                "失败订单": _num(row["late_orders_mean"], 1),
                "backlog": _num(row["backlog_units"]),
                "平均交付日": _num(row["avg_delivery_day"], 2),
            }
        )
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
                "Δ quoted": f"{row['mean'] * 100 + 1e-9:+.1f} pp",
                "Δ 原 SLA": f"{row['static_mean'] * 100 + 1e-9:+.1f} pp",
                "95% CI": f"±{row['ci95'] * 100:.1f}",
                "胜": _pct(row["win"]),
                "负": _pct(row["loss"]),
                "平": _pct(row["tie"]),
            }
        )
    return pd.DataFrame(rows)


def _by_day_table(by_day: List[Dict[str, Any]]) -> pd.DataFrame:
    names = ["周一", "周二", "周三", "周四", "周五"]
    rows = []
    for row in by_day:
        values = {
            "策略": (
                "单周一次性快照"
                if row["policy"] == "single_week"
                else row["label"]
            ),
            "报价": row["quote_policy"],
        }
        for day, name in enumerate(names):
            value = row.get(f"otif_day_{day}")
            values[name] = (
                _pct(value) if value is not None and not pd.isna(value) else "—"
            )
        rows.append(values)
    return pd.DataFrame(rows)


def build_rolling_quote_report(
    payload: Dict[str, Any],
    title: str = "Rolling replenishment with daily promise re-quoting (Week 22)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    paired = payload.get("paired", [])
    by_day = payload.get("by_day", [])
    order_days = payload.get("order_days", {})
    daily_static = _lookup(summary, "daily_1d", "static")
    daily_atp = _lookup(summary, "daily_1d", "atp")
    daily_buffer = _lookup(summary, "daily_1d", "atp_buffer")
    none_static = _lookup(summary, "none", "static")
    none_atp = _lookup(summary, "none", "atp")
    base_static = _lookup(summary, "single_week", "static")

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
        f"- Seeds: **{settings.get('seeds', 0)}** | replenishment "
        f"**{settings.get('policies', [])}** | quote policies "
        f"**{settings.get('quote_policies', [])}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day** | stock "
        f"**{settings.get('stock_factor', 0):.0%}**"
    )
    lines.append("")

    lines += ["## Assumptions", ""]
    lines += [
        "| Item | Assumption | Note |",
        "|---|---|---|",
        "| Daily quote | ATP from start-of-day on-hand stock | new orders only |",
        "| Old orders | keep the absolute promise quoted at arrival | not re-quoted |",
        "| Quote tiers | 2 / 3 / 5 days | fastest in-stock DC per line |",
        "| Dynamic quote | `atp` / `atp_buffer` | buffer maps 2→3 and 3→5 |",
        "| Replenishment | order-up-to remaining-week cover | 1/2-day lead, no MOQ |",
        "| Pick / dispatch | empirical arrivals + EDF, two departures | `max_days=0` |",
        "| Scoring | quoted promise and original static SLA | both absolute dates |",
        "",
    ]

    lines += ["## Results", ""]
    lines.append(
        "`quoted OTIF` uses the promise actually quoted to the customer; "
        "`原 SLA OTIF` uses the Week-20 fixed 2/3/5 promise as a common baseline. "
        "A longer quote can raise quoted OTIF while lowering the original SLA; "
        "both are shown so a quote policy cannot win by simply buying time."
    )
    lines.append("")
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Paired differences", ""]
    lines.append(_md_table(_paired_table(paired)))
    lines.append("")

    lines += ["## OTIF by order day", ""]
    lines.append(_md_table(_by_day_table(by_day)))
    lines.append("")

    lines += ["## Findings", ""]
    if daily_static and daily_atp:
        q_delta = (
            daily_atp["quoted_otif_mean"] - daily_static["quoted_otif_mean"]
        ) * 100 + 1e-9
        s_delta = (
            daily_atp["static_sla_otif_mean"]
            - daily_static["static_sla_otif_mean"]
        ) * 100 + 1e-9
        p_delta = daily_atp["avg_promise_days"] - daily_static["avg_promise_days"]
        if q_delta > 0.1 and s_delta >= -0.1:
            lines.append(
                f"- **Daily ATP improves the quoted service without sacrificing the "
                f"original SLA.** With 1-day replenishment, quoted OTIF is "
                f"{_pct(daily_atp['quoted_otif_mean'])} vs "
                f"{_pct(daily_static['quoted_otif_mean'])} for the fixed mix "
                f"({q_delta:+.1f} pp), and the original SLA is "
                f"{_pct(daily_atp['static_sla_otif_mean'])} vs "
                f"{_pct(daily_static['static_sla_otif_mean'])} ({s_delta:+.1f} pp); "
                f"average quote moves {p_delta:+.2f} days. This is a genuine "
                f"frontier improvement in this instance, not only a longer promise."
            )
        elif q_delta > 0.1:
            lines.append(
                f"- **Daily ATP raises quoted OTIF while lowering the original SLA.** "
                f"With 1-day replenishment, quoted OTIF rises {q_delta:+.1f} pp "
                f"({_pct(daily_static['quoted_otif_mean'])} → "
                f"{_pct(daily_atp['quoted_otif_mean'])}), but the original SLA falls "
                f"{s_delta:+.1f} pp and the average quote moves {p_delta:+.2f} days. "
                f"The quote is not a free service gain; it combines a longer promise "
                f"with allocation re-prioritization."
            )
        elif q_delta < -0.1:
            lines.append(
                f"- **Daily ATP over-promises in this flow.** Quoted OTIF falls "
                f"{q_delta:+.1f} pp ({_pct(daily_static['quoted_otif_mean'])} → "
                f"{_pct(daily_atp['quoted_otif_mean'])}); average quote moves "
                f"{p_delta:+.2f} days. ATP on current stock ignores same-day "
                f"competition and future arrivals, so it cannot protect service here."
            )
        else:
            lines.append(
                f"- **Daily ATP is essentially neutral here.** Quoted OTIF moves "
                f"{q_delta:+.1f} pp and the original SLA {s_delta:+.1f} pp; average "
                f"quote moves {p_delta:+.2f} days. The fixed mix already matches the "
                f"stock available at this load."
            )
    if daily_static and daily_atp:
        lines.append(
            f"- **The quote is not a pure wording A/B.** The allocation MILP also uses "
            f"the quoted promise as a deadline, so daily ATP changes fill "
            f"({_pct(daily_static['fill_mean'])} → {_pct(daily_atp['fill_mean'])}) and "
            f"backlog ({daily_static['backlog_units']:,} → "
            f"{daily_atp['backlog_units']:,}). Part of the quoted-OTIF gain is more "
            f"units allocated, not just a longer promise; the original-SLA column keeps "
            f"the customer baseline fixed."
        )
    if daily_atp and daily_buffer:
        buffer_q = (
            daily_buffer["quoted_otif_mean"] - daily_atp["quoted_otif_mean"]
        ) * 100 + 1e-9
        buffer_s = (
            daily_buffer["static_sla_otif_mean"]
            - daily_atp["static_sla_otif_mean"]
        ) * 100 + 1e-9
        if buffer_q >= -0.1 and buffer_s >= -0.1:
            lines.append(
                f"- **Buffering buys a small service gain at a large promise cost.** "
                f"`atp_buffer` gives {_pct(daily_buffer['quoted_otif_mean'])} quoted "
                f"OTIF vs {_pct(daily_atp['quoted_otif_mean'])} for raw ATP "
                f"({buffer_q:+.1f} pp), and the original SLA moves {buffer_s:+.1f} pp; "
                f"but the average quote is {daily_buffer['avg_promise_days']:.2f} vs "
                f"{daily_atp['avg_promise_days']:.2f} days. The extra day is not free."
            )
        else:
            lines.append(
                f"- **Buffering the quote trades service for time.** `atp_buffer` gives "
                f"{_pct(daily_buffer['quoted_otif_mean'])} quoted OTIF vs "
                f"{_pct(daily_atp['quoted_otif_mean'])} for raw ATP "
                f"({buffer_q:+.1f} pp), the original SLA moves {buffer_s:+.1f} pp, and "
                f"the average quote is {daily_buffer['avg_promise_days']:.2f} vs "
                f"{daily_atp['avg_promise_days']:.2f} days. Longer quotes can look safer "
                f"while delivering later."
            )
    if none_static and none_atp:
        lines.append(
            f"- **Without replenishment, re-quoting cannot create stock.** No-replenishment "
            f"quoted OTIF is {_pct(none_atp['quoted_otif_mean'])} with ATP vs "
            f"{_pct(none_static['quoted_otif_mean'])} with the fixed mix; the average "
            f"quote is {none_atp['avg_promise_days']:.2f} vs "
            f"{none_static['avg_promise_days']:.2f} days. This separates the quote "
            f"decision from the inventory decision."
        )
    if daily_static and base_static:
        lines.append(
            f"- **Daily replenishment still dominates the quote policy.** Daily static "
            f"quoted OTIF is {_pct(daily_static['quoted_otif_mean'])} vs "
            f"{_pct(base_static['quoted_otif_mean'])} for the one-shot snapshot "
            f"({(daily_static['quoted_otif_mean'] - base_static['quoted_otif_mean']) * 100:+.1f} pp). "
            f"The biggest service lever remains inventory, not the wording of the promise."
        )
    if paired and all(abs(row.get("ci95", 0.0)) < 1e-12 for row in paired):
        lines.append(
            "- **The seed intervals are zero.** Every seed gives the same order-level "
            "OTIF and delivery day, so the paired differences are deterministic "
            "boundaries, not 30 independent samples."
        )
    lines.append(
        "- **Scope.** This is allocation + pick + dispatch + a daily quote. It does "
        "not model customer acceptance, cancellations, re-quotes, carrier capacity, "
        "dock doors or a second departure day. Quote tiers, replenishment lead time "
        "and transit days are declared values."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_rolling_quote_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Rolling replenishment with daily promise re-quoting (Week 22)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "ROLLING_QUOTE_REPORT.md"
    summary = out / "rolling_quote_summary.json"
    report.write_text(
        build_rolling_quote_report(payload, title=title), encoding="utf-8"
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
