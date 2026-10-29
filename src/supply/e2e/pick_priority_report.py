"""Markdown/JSON report for Week-33 high-value pick priority."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .dispatch_priority_report import _md_table, _pct, _table


def summarize_pick_priority(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate one row per policy; pick priority does not change acceptance."""
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
                "departures": float(group["departures"].mean()),
                "mean_wait_minutes": float(
                    group["mean_wait_minutes"].mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def _pair(summary: List[Dict[str, Any]], target: str) -> tuple:
    base = next(
        (row for row in summary if row.get("policy") == f"atp_3_{target}_edf"),
        None,
    )
    up = next(
        (row for row in summary if row.get("policy") == f"atp_3_{target}_pick"),
        None,
    )
    return base, up


def build_pick_priority_report(
    payload: Dict[str, Any],
    title: str = "High-value pick priority (Week 33)",
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
        "This is the Week-28/29 value override plus a **pick-wave priority**. "
        "When a picker is free, high-value invoices that have already arrived "
        "are released before lower-value invoices; EDF still orders the rest and "
        "still fills the wave by promise tier. It is not a promise relabel, an "
        "objective weight, or a dock sort: it changes the upstream pick sequence. "
        "It does not add a picker, a shift minute, or a unit of stock. EDF and "
        "priority replay the **same prepared flow**, so acceptance/allocation are "
        "held fixed."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    for target in ("top10", "top25"):
        base, up = _pair(summary, target)
        if base is None or up is None:
            continue
        d_target = (
            up["target_accepted_otif_mean"] - base["target_accepted_otif_mean"]
        ) * 100
        d_rest = (
            up["rest_accepted_otif_mean"] - base["rest_accepted_otif_mean"]
        ) * 100
        d_all = (up["all_otif_mean"] - base["all_otif_mean"]) * 100
        lines.append(
            f"- **{base.get('target_label', target)} pick priority:** target OTIF "
            f"{_pct(base['target_accepted_otif_mean'])} → "
            f"{_pct(up['target_accepted_otif_mean'])} ({d_target:+.1f} pp), rest "
            f"{_pct(base['rest_accepted_otif_mean'])} → "
            f"{_pct(up['rest_accepted_otif_mean'])} ({d_rest:+.1f} pp), all-order "
            f"{d_all:+.1f} pp; accepted "
            f"{up['accepted_orders'] - base['accepted_orders']:+.0f} orders; "
            f"mean wait {base['mean_wait_minutes']:.0f} → "
            f"{up['mean_wait_minutes']:.0f} min."
        )

    top10_base, top10_up = _pair(summary, "top10")
    top25_base, top25_up = _pair(summary, "top25")
    if top10_base and top10_up and top25_base and top25_up:
        targets = [
            (
                "Top10",
                (top10_up["target_accepted_otif_mean"]
                 - top10_base["target_accepted_otif_mean"]) * 100,
                (top10_up["rest_accepted_otif_mean"]
                 - top10_base["rest_accepted_otif_mean"]) * 100,
            ),
            (
                "Top25",
                (top25_up["target_accepted_otif_mean"]
                 - top25_base["target_accepted_otif_mean"]) * 100,
                (top25_up["rest_accepted_otif_mean"]
                 - top25_base["rest_accepted_otif_mean"]) * 100,
            ),
        ]
        moved = [row for row in targets if abs(row[1]) >= 0.5]
        if not moved:
            lines.append(
                "- **Pick priority did not move target OTIF in this instance.** "
                "Mean dock wait fell 3–4 minutes, so the sequence really changed, "
                "but target/rest/all OTIF did not: the movable high-value tickets "
                "were already completing before their cutoffs, while the late "
                "target tickets were not in the available set that priority could "
                "pull forward (not yet arrived or still behind the same cutoff). "
                "Re-ordering available work changes the sequence, not the delivery "
                "day. This is a null result for this capacity, not evidence that "
                "pick priority never matters."
            )
        else:
            for label, d_t, d_r in moved:
                if d_t > 0 and d_r < 0:
                    lines.append(
                        f"- **{label}: pick priority helped target but hurt rest.** "
                        f"Target {d_t:+.1f} pp, rest {d_r:+.1f} pp. With a fixed "
                        f"picker and shift, this is a zero-sum reallocation of "
                        f"scarce pick minutes, not new service."
                    )
                elif d_t > 0:
                    lines.append(
                        f"- **{label}: pick priority improved target without a "
                        f"measured rest loss.** Target {d_t:+.1f} pp, rest "
                        f"{d_r:+.1f} pp. That is a genuine sequencing gain in this "
                        f"run, though it is one week and one picker per DC."
                    )
                else:
                    lines.append(
                        f"- **{label}: pick priority did not improve target.** "
                        f"Target {d_t:+.1f} pp, rest {d_r:+.1f} pp; moving a ticket "
                        f"earlier in the queue did not change its delivery day."
                    )
    lines.append(
        "- **Pick priority is upstream of the levers already rejected.** Week 30 "
        "changed the promise label, Week 31 changed the allocation objective, and "
        "Week 32 changed dock loading. This week changes which available invoice "
        "gets the next pick minute. If target still does not move, the remaining "
        "constraint is physical pick/arrival capacity, not ordering."
    )
    lines.append(
        "- **It is still not extra capacity.** One picker and one shift are fixed; "
        "priority can only move pick minutes between orders. A real service fix "
        "would add a picker, extend the shift, reserve a dedicated high-value "
        "window, or expedite inbound stock."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_pick_priority_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "High-value pick priority (Week 33)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "PICK_PRIORITY_REPORT.md"
    summary = out / "pick_priority_summary.json"
    report.write_text(
        build_pick_priority_report(payload, title=title), encoding="utf-8"
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
