"""Markdown/JSON report for the Week-24 order-acceptance experiment."""
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


def _table(summary: List[Dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for row in summary:
        accepted = float(row.get("accepted_orders_mean", 0.0))
        total = float(row.get("orders_mean", accepted + row.get("lost_orders_mean", 0.0)))
        rows.append(
            {
                "场景": row.get("label", row.get("policy", "")),
                "报价": row.get("quote_policy", ""),
                "接单上限": row.get("accept_cutoff", "全部"),
                "接受订单": _num(accepted, 1),
                "接单率": _pct(row.get("accepted_rate", 1.0)),
                "接单 quoted OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "接单原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "接单 fill": _pct(row.get("accepted_fill_mean", 0.0)),
                "接单 backlog": _num(row.get("accepted_backlog_units", 0.0)),
                "流失订单": _num(row.get("lost_orders_mean", 0.0), 1),
                "流失单位": _num(row.get("lost_units", 0.0)),
                "平均承诺": _num(row.get("accepted_avg_promise_days", 0.0), 2),
                "全量 OTIF": _pct(row.get("e2e_otif_mean", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def build_order_acceptance_report(
    payload: Dict[str, Any],
    title: str = "Order acceptance under daily replenishment (Week 24)",
    generated: Optional[str] = None,
) -> str:
    stamp = generated or datetime.now(timezone.utc).isoformat()
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary = payload.get("summary", [])
    order_days = payload.get("order_days", {})
    daily = [row for row in summary if row.get("accept_cutoff") != "全部"]
    accepted_all = next(
        (
            row
            for row in summary
            if row.get("accept_cutoff") == "全部"
            and row.get("quote_policy") == "atp"
        ),
        None,
    )
    static_all = next(
        (
            row
            for row in summary
            if row.get("accept_cutoff") == "全部"
            and row.get("quote_policy") == "static"
            and row.get("policy") != "single_week_static"
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
    lines.append("")

    lines += ["## Rule", ""]
    lines.append(
        "A new order is **accepted** only when its quoted promise at arrival is "
        "within the cutoff; otherwise it is rejected immediately. Rejected orders "
        "consume no stock and do not enter the dispatch queue, but they remain in the "
        "all-order denominator (`全量 OTIF`). Accepted-order metrics use only the "
        "accepted orders; `接单率` is accepted orders / all orders."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    if accepted_all:
        lines.append(
            f"- **Accept-all is the reference.** With daily replenishment and "
            f"`{accepted_all.get('quote_policy', 'atp')}` quoting, accepted OTIF is "
            f"{_pct(accepted_all['accepted_otif_mean'])} and the original SLA is "
            f"{_pct(accepted_all['accepted_static_sla_mean'])} at "
            f"{accepted_all['accepted_avg_promise_days']:.2f} average quoted days; "
            f"{_num(accepted_all['lost_orders_mean'], 1)} orders are lost. "
            f"The all-order OTIF is {_pct(accepted_all['e2e_otif_mean'])}."
        )
    if accepted_all and static_all:
        lines.append(
            f"- **ATP accept-all still has the Week-22 split.** vs fixed 2/3/5, "
            f"ATP raises accepted quoted OTIF by "
            f"{(accepted_all['accepted_otif_mean'] - static_all['accepted_otif_mean']) * 100:+.1f} pp "
            f"and fill by "
            f"{(accepted_all['accepted_fill_mean'] - static_all['accepted_fill_mean']) * 100:+.1f} pp, "
            f"but lowers the original SLA by "
            f"{(accepted_all['accepted_static_sla_mean'] - static_all['accepted_static_sla_mean']) * 100:+.1f} pp "
            f"and lengthens the average quote. Acceptance cannot repair that gap by "
            f"itself; it only changes who stays in the denominator."
        )
    for row in daily:
        reference = (
            accepted_all
            if row.get("quote_policy") == "atp"
            else static_all
        )
        if not reference:
            continue
        accepted = float(row.get("accepted_orders_mean", 0.0))
        if accepted <= 0:
            lines.append(
                f"- **Cutoff {row.get('accept_cutoff')} days with "
                f"`{row.get('quote_policy')}` rejects every order.** "
                f"`{row.get('label', '')}` accepts 0 orders and loses "
                f"{_num(row.get('lost_units', 0))} units; its 0% accepted OTIF is "
                f"an empty denominator, not a service success. A cutoff must be "
                f"compatible with the quote policy's feasible tiers."
            )
            continue
        q_gain = (
            row["accepted_otif_mean"] - reference["accepted_otif_mean"]
        ) * 100
        s_gain = (
            row["accepted_static_sla_mean"]
            - reference["accepted_static_sla_mean"]
        ) * 100
        lost = row["lost_orders_mean"] - reference.get("lost_orders_mean", 0.0)
        unit_loss = row.get("lost_units", 0) - reference.get("lost_units", 0)
        if q_gain <= 0.1 and s_gain <= 0.1:
            verdict = (
                f"Accepted service does **not** improve ({q_gain:+.1f} pp quoted, "
                f"{s_gain:+.1f} pp original SLA); rejection only removes "
                f"{_num(lost, 1)} orders ({_num(unit_loss)} units). This cutoff is "
                f"not a service lever for this quote policy."
            )
        else:
            verdict = (
                f"The service gain is bought with lost demand, not free: "
                f"{_num(lost, 1)} more orders ({_num(unit_loss)} units) are rejected."
            )
        lines.append(
            f"- **Cutoff {row.get('accept_cutoff')} days with "
            f"`{row.get('quote_policy')}`:** accepts "
            f"{_pct(row.get('accepted_rate', 0.0))} of orders; accepted OTIF "
            f"{_pct(row['accepted_otif_mean'])} ({q_gain:+.1f} pp vs its "
            f"accept-all reference), original SLA "
            f"{_pct(row['accepted_static_sla_mean'])} ({s_gain:+.1f} pp). "
            f"{verdict}"
        )
    lines.append(
        "- **Read the loss column with the service column.** A higher accepted OTIF "
        "is not a better policy if the denominator shrank; `全量 OTIF` and "
        "`流失订单/单位` are shown for exactly this reason."
    )
    lines.append(
        "- **Acceptance is not a second inventory lever.** It can protect the "
        "accepted pool, but it cannot serve the rejected demand; the inventory and "
        "replenishment decision still sets the feasible frontier."
    )
    lines.append(
        "- **Solver variation is visible.** The time-limited MILP is not "
        "bit-for-bit reproducible; treat differences below ~1 pp as solver noise."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_order_acceptance_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Order acceptance under daily replenishment (Week 24)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "ORDER_ACCEPTANCE_REPORT.md"
    summary = out / "order_acceptance_summary.json"
    report.write_text(
        build_order_acceptance_report(payload, title=title), encoding="utf-8"
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
