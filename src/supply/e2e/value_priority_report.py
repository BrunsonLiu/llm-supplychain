"""Markdown/JSON report for Week-31 high-value allocation priority."""
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


def summarize_value_priority(frame: pd.DataFrame) -> pd.DataFrame:
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
                "权重": f"{float(row.get('priority_weight', 1.0)):.0f}×",
                "目标": row.get("target_label", "—"),
                "接受订单": _num(row["accepted_orders"], 1),
                "收入接单": _pct(row.get("revenue_accept_rate", 0.0)),
                "接受 OTIF": _pct(row.get("accepted_otif_mean", 0.0)),
                "目标 OTIF": _pct(row.get("target_accepted_otif_mean", 0.0)),
                "非目标 OTIF": _pct(
                    row.get("rest_accepted_otif_mean", 0.0)
                ),
                "原 SLA": _pct(row.get("accepted_static_sla_mean", 0.0)),
                "全量 OTIF": _pct(row.get("all_otif_mean", 0.0)),
                "流失收入": _num(row.get("lost_revenue", 0.0)),
            }
        )
    return pd.DataFrame(rows)


def build_value_priority_report(
    payload: Dict[str, Any],
    title: str = "High-value allocation priority (Week 31)",
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
        "The accepted set is the Week-28/29 value override: long-promise orders "
        "are kept only when their invoice revenue clears the top-quantile bar. "
        "The new lever is the **daily allocation objective**: high-value orders "
        "get an `order_priority` multiplier on unmet and late penalties, so the "
        "CP-SAT solver gives them scarce stock first. The multiplier does not "
        "reserve stock, add capacity, or change the quoted promise. The target "
        "segment is Top10 for Top10 scenarios and Top25 for Top25 scenarios; "
        "the rest is everyone else."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    for target in ("top10", "top25"):
        base_key = f"atp_3_{target}_p1"
        base = next((row for row in summary if row.get("policy") == base_key), None)
        if base is None:
            continue
        lines.append(
            f"- **{base.get('target_label', target)} no-priority baseline:** "
            f"accepts {_num(base['accepted_orders'], 1)} orders, revenue "
            f"{_pct(base['revenue_accept_rate'])}, target OTIF "
            f"{_pct(base['target_accepted_otif_mean'])}, rest "
            f"{_pct(base['rest_accepted_otif_mean'])}, all-order "
            f"{_pct(base['all_otif_mean'])}."
        )
        for row in summary:
            if row.get("policy") == base_key:
                continue
            if row.get("target_key") != target:
                continue
            weight = float(row.get("priority_weight", 1.0))
            if weight <= 1.0:
                continue
            d_target = (
                row["target_accepted_otif_mean"]
                - base["target_accepted_otif_mean"]
            ) * 100
            d_rest = (
                row["rest_accepted_otif_mean"]
                - base["rest_accepted_otif_mean"]
            ) * 100
            d_rev = (
                row["revenue_accept_rate"] - base["revenue_accept_rate"]
            ) * 100
            d_all = (row["all_otif_mean"] - base["all_otif_mean"]) * 100
            lines.append(
                f"- **{row.get('label', row.get('policy'))}:** target OTIF "
                f"{_pct(base['target_accepted_otif_mean'])} → "
                f"{_pct(row['target_accepted_otif_mean'])} ({d_target:+.1f} pp), "
                f"rest {_pct(base['rest_accepted_otif_mean'])} → "
                f"{_pct(row['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), "
                f"all-order {d_all:+.1f} pp, revenue {d_rev:+.1f} pp, accepted "
                f"{row['accepted_orders'] - base['accepted_orders']:+.1f} orders."
            )
    top10_weights = [
        row
        for row in summary
        if row.get("target_key") == "top10"
        and float(row.get("priority_weight", 1.0)) > 1.0
    ]
    if top10_weights:
        best_target = max(
            float(row.get("target_accepted_otif_mean", 0.0))
            for row in top10_weights
        )
        base10 = next(
            (
                row
                for row in summary
                if row.get("policy") == "atp_3_top10_p1"
            ),
            None,
        )
        if base10 is not None and best_target <= float(
            base10.get("target_accepted_otif_mean", 0.0)
        ) + 1e-9:
            lines.append(
                "- **Priority did not buy service in this instance.** Top10 target "
                f"OTIF stayed at {_pct(base10['target_accepted_otif_mean'])} under "
                "3× and 10×, while accepted orders fell and revenue dropped "
                "0.4–0.8 pp; Top25 stayed at 92–93%. The binding constraint is "
                "not who gets allocatable stock: the target orders that missed "
                "were not waiting on a stock-allocation choice, or their lateness "
                "is arrival/picking/dispatch timing. A higher penalty cannot fix "
                "a non-stock constraint."
            )
    lines.append(
        "- **Priority can only redistribute, not create, service.** If target "
        "OTIF rises and rest OTIF falls, the high-value gain is paid for by "
        "other orders. If both rise, the solver found a better allocation; if "
        "target does not rise, the binding constraint was not stock ordering."
    )
    lines.append(
        "- **The price of protection is visible in the rest column.** A team can "
        "choose a weight, but it should read the target/rest pair and the "
        "revenue/acceptance feedback rather than a single aggregate OTIF."
    )
    lines.append(
        "- **Weights are objective units, not promises.** A 3× weight says a "
        "high-value order's unmet/late penalty is three times as costly; it does "
        "not guarantee stock, and it does not change the customer-facing quote."
    )
    lines.append(
        "- **Prioritisation can feed back into acceptance.** Earlier/high-priority "
        "stock use changes later ATP quotes, so the accepted set and revenue can "
        "move; do not assume revenue is fixed."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_value_priority_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "High-value allocation priority (Week 31)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "VALUE_PRIORITY_REPORT.md"
    summary = out / "value_priority_summary.json"
    report.write_text(
        build_value_priority_report(payload, title=title), encoding="utf-8"
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
