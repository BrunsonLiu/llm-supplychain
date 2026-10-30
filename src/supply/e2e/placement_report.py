"""Week-40 report: fixed-total stock rebalance across DCs.

Week 39 only closed the target gap at 150% total stock, so it could not tell
whether the gain came from *where* stock sits or from *more* stock. Week 40
holds every SKU's total stock at 100% of demand and changes only the DC shares.
"""
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


def summarize_placement(frame: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for placement, group in frame.groupby("placement", sort=False):
        first = group.iloc[0]
        rows.append(
            {
                "placement": placement,
                "label": first.get("label", placement),
                "shares": first.get("shares", ""),
                "seeds": int(len(group)),
                "orders": int(first["orders"]),
                "stock_units": int(first.get("stock_units", 0)),
                "accepted_orders": float(group["accepted_orders"].mean()),
                "accepted_rate": float(group["accepted_rate"].mean()),
                "accepted_otif_mean": float(group["accepted_otif_rate"].mean()),
                "target_accepted_otif_mean": float(
                    group["target_accepted_otif_rate"].mean()
                ),
                "rest_accepted_otif_mean": float(
                    group["rest_accepted_otif_rate"].mean()
                ),
                "all_otif_mean": float(group["e2e_otif_rate"].mean()),
                "accepted_fill_rate": float(group["accepted_fill_rate"].mean()),
                "accepted_backlog_units": float(
                    group["accepted_backlog_units"].mean()
                ),
                "avg_delivery_day": float(group["avg_delivery_day"].mean()),
                "departures": float(group["departures"].mean()),
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
                "布点": row.get("label", row["placement"]),
                "DC 占比": row.get("shares", ""),
                "库存单位": _num(row.get("stock_units", 0)),
                "接受订单": _num(row["accepted_orders"], 1),
                "接受 OTIF": _pct(row["accepted_otif_mean"]),
                "目标 OTIF": _pct(row["target_accepted_otif_mean"]),
                "非目标 OTIF": _pct(row["rest_accepted_otif_mean"]),
                "全量 OTIF": _pct(row["all_otif_mean"]),
                "满足率": _pct(row["accepted_fill_rate"]),
                "积压单位": _num(row["accepted_backlog_units"]),
                "平均交付日": f"{row['avg_delivery_day']:.2f}",
            }
        )
    return pd.DataFrame(rows)


def build_placement_report(
    payload: Dict[str, Any],
    title: str = "Fixed-total stock rebalance (Week 40)",
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
        f"- Seeds: **{settings.get('seeds', 0)}** | placements "
        f"**{settings.get('placements', [])}** | daily MILP "
        f"**{settings.get('milp_time', 0):.0f}s/day**"
    )
    lines.append(
        "- Conditions: **100% total stock**, **2× DC capacity**, **transit −1**, "
        "ATP accept-all. Only the DC stock shares change; every SKU's total units "
        "are held fixed."
    )
    lines.append("")

    lines += ["## Rule", ""]
    lines.append(
        "Week 39 could only close the target gap with 150% total stock, which "
        "confounds placement with more units. Week 40 fixes each SKU's total stock "
        "at 100% of demand and varies only the split across London / Rotterdam / "
        "Frankfurt. If target OTIF moves, local placement matters at fixed total; "
        "if it does not, the Week-39 gain came from the extra units, not from "
        "rebalancing."
    )
    lines.append("")

    lines += ["## Results", ""]
    lines.append(_md_table(_table(summary)))
    lines.append("")

    lines += ["## Findings", ""]
    baseline = next(
        (row for row in summary if row.get("placement") == "baseline"), None
    )
    if baseline:
        deltas = []
        for row in summary:
            if row.get("placement") == "baseline":
                continue
            delta = (
                row["target_accepted_otif_mean"]
                - baseline["target_accepted_otif_mean"]
            ) * 100
            deltas.append((row.get("label", row["placement"]), delta, row))
        lines.append(
            f"- **Baseline 34/28/38:** target OTIF "
            f"{_pct(baseline['target_accepted_otif_mean'])}, rest "
            f"{_pct(baseline['rest_accepted_otif_mean'])}, all "
            f"{_pct(baseline['all_otif_mean'])}, backlog "
            f"{baseline['accepted_backlog_units']:,.0f} units."
        )
        if not deltas:
            lines.append(
                "- **Only the baseline was selected.** Run at least one other "
                "placement to estimate a rebalance effect."
            )
            lines.append("")
            lines += ["## Limitations", ""]
            for item in payload.get("limitations", []):
                lines.append(f"- {item}")
            lines.append("")
            return "\n".join(lines)
        best_label, best_delta, best = max(deltas, key=lambda item: item[1])
        lines.append(
            f"- **Best fixed-total rebalance: {best_label}** target "
            f"{_pct(best['target_accepted_otif_mean'])} ({best_delta:+.1f} pp vs "
            f"baseline), backlog {best['accepted_backlog_units']:,.0f} units."
        )
        settings = payload.get("settings", {})
        noise = float(
            payload.get("solver_noise_pp", settings.get("solver_noise_pp", 0.0))
        )
        if best_delta >= max(2.0, noise + 0.5):
            lines.append(
                "- **Placement is part of the residual.** At fixed total stock, "
                "moving units toward the right DC raises target OTIF beyond the "
                "observed solver noise; this supports a placement story rather "
                "than a pure 'more stock' story. It is still a within-week, "
                "within-layout estimate, not a replenishment policy."
            )
        elif best_delta >= 1.0:
            lines.append(
                f"- **Directional, but not robust.** The best arm is "
                f"{best_delta:+.1f} pp, which is smaller than the "
                f"{noise:.1f} pp baseline spread across repeated runs; the arm "
                "ranking also flips between runs. Treat this as inconclusive, not "
                "as evidence that rebalancing closes the gap."
            )
        else:
            lines.append(
                "- **Placement alone does not close the gap.** At fixed 100% total "
                "stock, none of these DC shares materially improves target OTIF; "
                "the Week-39 150% gain is therefore mostly extra total units, not "
                "a better split of the same units. This is a negative result and "
                "should be reported as such."
            )
        repeats = payload.get(
            "baseline_repeats", settings.get("baseline_repeats", [])
        )
        if repeats:
            lines.append(
                "- **Baseline repeats matter:** the same 34/28/38 arm produced "
                + " / ".join(f"{float(value):.1f}%" for value in repeats)
                + " target OTIF across repeated 400×30 runs. A 2–3 pp arm gap is "
                "inside that spread; only a gap larger than the spread should be "
                "read as a placement effect."
            )
        lines.append(
            "- **Total stock is held fixed per SKU.** The shares are applied to "
            "each SKU's total with a deterministic 0.75–1.25 jitter, so the arms "
            "differ in placement, not in the amount purchased."
        )
        lines.append(
            f"- **All arms accept {baseline['accepted_orders']:.0f} orders** at "
            "2× capacity and transit −1; this is not an acceptance-mix, "
            "throughput or carrier effect."
        )
    lines.append(
        "- **Four shares are not an optimizer.** The set (34/28/38, 33/33/34, "
        "30/40/30, 40/24/36) is a small design, not a search over all feasible "
        "placements; a null does not prove every rebalance is useless."
    )
    lines.append("")

    lines += ["## Limitations", ""]
    for item in payload.get("limitations", []):
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_placement_report(
    payload: Dict[str, Any],
    out_dir: Path | str,
    title: str = "Fixed-total stock rebalance (Week 40)",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = out / "PLACEMENT_REPORT.md"
    summary = out / "placement_summary.json"
    report.write_text(
        build_placement_report(payload, title=title), encoding="utf-8"
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
