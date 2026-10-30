"""Week 41 report: demand-weighted stock placement MILP."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

import pandas as pd


def _mean(group: pd.DataFrame, column: str) -> float:
    if column not in group:
        return 0.0
    return float(pd.to_numeric(group[column], errors="coerce").mean())


def summarize_access(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per policy, averaging seeds within each policy."""
    rows = []
    for policy, group in frame.groupby("policy", sort=False):
        first = group.iloc[0]
        rows.append(
            {
                "policy": policy,
                "label": first.get("label", policy),
                "accepted_orders": _mean(group, "accepted_orders"),
                "accepted_otif_mean": _mean(group, "accepted_otif_rate"),
                "target_accepted_otif_mean": _mean(
                    group, "target_accepted_otif_rate"
                ),
                "target_accepted_otif_min": float(
                    pd.to_numeric(
                        group["target_accepted_otif_rate"], errors="coerce"
                    ).min()
                ),
                "target_accepted_otif_max": float(
                    pd.to_numeric(
                        group["target_accepted_otif_rate"], errors="coerce"
                    ).max()
                ),
                "rest_accepted_otif_mean": _mean(
                    group, "rest_accepted_otif_rate"
                ),
                "accepted_fill_rate": _mean(group, "accepted_fill_rate"),
                "accepted_backlog_units": _mean(
                    group, "accepted_backlog_units"
                ),
                "avg_delivery_day": _mean(group, "avg_delivery_day"),
                "moved_units_mean": _mean(group, "moved_units"),
                "coverage_mean": _mean(group, "coverage"),
                "peak_pick_minutes_mean": _mean(group, "peak_pick_minutes"),
                "pick_capacity": _mean(group, "pick_capacity"),
                "overload_minutes_mean": _mean(group, "overload_minutes"),
                "milp_status": first.get("milp_status", "—"),
            }
        )
    return pd.DataFrame(rows)


def _pct(value: float) -> str:
    return f"{100.0 * float(value):.1f}%"


def _num(value: float, digits: int = 0) -> str:
    return f"{float(value):,.{digits}f}"


def build_access_report(payload: Mapping[str, Any]) -> str:
    dataset = payload.get("dataset", {})
    settings = payload.get("settings", {})
    summary: Sequence[Mapping[str, Any]] = payload.get("summary", [])
    rows = {str(row["policy"]): row for row in summary}
    load_keys = [key for key in rows if key.endswith("_load")]
    baseline = rows.get("baseline")
    oracle = rows.get("access_oracle")
    history = rows.get("access_history")

    lines = [
        f"# Week {settings.get('week', 41)}: demand-weighted stock placement",
        "",
        f"- Orders: **{dataset.get('orders', '—')}** | "
        f"units: **{_num(dataset.get('units', 0))}** | "
        f"week: **{dataset.get('week', '—')}**",
        f"- Seeds: **{settings.get('seeds', '—')}** | "
        f"repeats: **{settings.get('repeats', 1)}** | "
        f"MILP time: **{settings.get('solver_time', '—')} s** | "
        f"history lookback: **{settings.get('lookback_weeks', '—')} weeks** | "
        f"DC share bounds: **{settings.get('min_share', 0):.0%}–"
        f"{settings.get('max_share', 1):.0%}**",
        "",
        "## Design",
        "",
        f"Week {int(settings.get('week', 41)) - 1} compared hand-picked DC stock "
        "splits and found only a directional, non-robust difference. This run "
        "keeps the same fixed total stock, 400 invoices, 30 seeds, 2x DC "
        "capacity and transit -1, but replaces the hand-picked shares with a "
        "small integer program:",
        "",
        "```",
        "max  sum_{d,s} z[d,s]",
        "s.t. sum_d y[d,s] = stock_total[s]",
        "     z[d,s] <= y[d,s]",
        "     z[d,s] <= demand[d,s]",
        "     min_share * total <= sum_s y[d,s] <= max_share * total",
        "     y, z integer >= 0",
        "```",
        "",
        "`demand[d,s]` is a partition of demand: each line is assigned to one "
        "best on-time DC. `access_oracle` uses the current week's realised lines; "
        "`access_history` uses the prior six weeks' country x SKU quantities and "
        "the current week's destination/transit matrix. The 10%/60% share bounds "
        "stop the coverage objective from parking almost all stock in one DC.",
    ]
    if load_keys:
        lines += [
            "",
            "The `_load` arms add a stock-implied pick-minute cap. With "
            f"`c={float(settings.get('pick_load_coeff', 0)):.3f}` minutes per "
            "unit and per-DC capacity "
            f"`{float(settings.get('load_capacity', 0)):.0f}` minutes:",
            "",
            "```",
            "L[d] = sum_s y[d,s] * c",
            "L[d] <= capacity[d] + overload[d]",
            "max coverage - penalty * sum_d overload[d] - moves",
            "```",
            "",
            "This is a placement proxy, not a queue simulation: it penalises "
            "parking stock where the pick layer would have to work it, but it "
            "does not know arrival order or wave release.",
        ]
    lines += [
        "",
        "## Results",
        "",
        "| policy | target OTIF | rest OTIF | all OTIF | backlog | fill | "
        "avg day | coverage | peak pick | moved units | MILP |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary:
        coverage = (
            "—" if row["policy"] == "baseline" else _pct(row.get("coverage_mean", 0))
        )
        peak_pick = (
            "—"
            if row["policy"] == "baseline"
            or float(row.get("pick_capacity", 0)) <= 0
            else f"{_num(row.get('peak_pick_minutes_mean', 0))} min"
        )
        lines.append(
            f"| {row['policy']} | {_pct(row.get('target_accepted_otif_mean', 0))} | "
            f"{_pct(row.get('rest_accepted_otif_mean', 0))} | "
            f"{_pct(row.get('accepted_otif_mean', 0))} | "
            f"{_num(row.get('accepted_backlog_units', 0))} | "
            f"{_pct(row.get('accepted_fill_rate', 0))} | "
            f"{float(row.get('avg_delivery_day', 0)):.2f} | "
            f"{coverage} | {peak_pick} | "
            f"{_num(row.get('moved_units_mean', 0))} | "
            f"{row.get('milp_status', '—')} |"
        )
    lines.append("")

    if baseline:
        base_target = float(baseline.get("target_accepted_otif_mean", 0))
        lines += ["## Findings", ""]
        for key, label in (("access_oracle", "oracle"), ("access_history", "history")):
            row = rows.get(key)
            if not row:
                continue
            delta_pp = 100.0 * (
                float(row.get("target_accepted_otif_mean", 0)) - base_target
            )
            moved = float(row.get("moved_units_mean", 0))
            if abs(delta_pp) >= 5.0:
                verdict = "materially different on this run"
            elif abs(delta_pp) >= 2.5:
                verdict = "directional, inside the 5pp solver-noise band"
            else:
                verdict = "not material on this run"
            direction = (
                "flat" if abs(delta_pp) < 0.05 else ("higher" if delta_pp > 0 else "lower")
            )
            lines.append(
                f"- **{label}**: target {_pct(base_target)} -> "
                f"{_pct(row.get('target_accepted_otif_mean', 0))} "
                f"({delta_pp:+.1f}pp, {direction}), moved {_num(moved)} units; "
                f"{verdict}."
            )
        if int(settings.get("repeats", 1)) > 1:
            ranges = []
            for key in ("baseline", "access_history", "access_oracle"):
                row = rows.get(key)
                if not row:
                    continue
                ranges.append(
                    f"{key} {_pct(row.get('target_accepted_otif_min', 0))}–"
                    f"{_pct(row.get('target_accepted_otif_max', 0))}"
                )
            lines.append(
                "- **Repeated runs**: target OTIF ranges "
                + "; ".join(ranges)
                + ". Treat differences smaller than this range as solver/"
                "arrival noise, not a treatment effect."
            )
        pareto_like = []
        for key, row in rows.items():
            if key == "baseline":
                continue
            target_ok = float(row.get("target_accepted_otif_mean", 0)) >= base_target
            rest_ok = float(row.get("rest_accepted_otif_mean", 0)) >= float(
                baseline.get("rest_accepted_otif_mean", 0)
            )
            all_ok = float(row.get("accepted_otif_mean", 0)) >= float(
                baseline.get("accepted_otif_mean", 0)
            )
            strict = (
                float(row.get("target_accepted_otif_mean", 0)) > base_target
                or float(row.get("rest_accepted_otif_mean", 0))
                > float(baseline.get("rest_accepted_otif_mean", 0))
                or float(row.get("accepted_otif_mean", 0))
                > float(baseline.get("accepted_otif_mean", 0))
            )
            if target_ok and rest_ok and all_ok and strict:
                pareto_like.append(key)
        if pareto_like:
            backlog_note = []
            for key in pareto_like:
                row = rows[key]
                backlog_note.append(
                    f"`{key}` backlog {_num(row.get('accepted_backlog_units', 0))} "
                    f"vs baseline {_num(baseline.get('accepted_backlog_units', 0))}"
                )
            scope = (
                "mean across repeats"
                if int(settings.get("repeats", 1)) > 1
                else "single run"
            )
            lines.append(
                "- **Pareto-looking on this run**: "
                + ", ".join(f"`{key}`" for key in pareto_like)
                + " is at least as good as baseline on target, rest and "
                "all-order OTIF, with a strict gain somewhere. "
                + "; ".join(backlog_note)
                + f". This is a {scope}; check the ranges and backlog before "
                "calling it robust."
            )
        else:
            lines.append(
                "- **No arm is a Pareto improvement.** Each non-baseline arm "
                "loses at least one of target, rest or all-order OTIF."
            )
        if oracle and history:
            gap_pp = 100.0 * (
                float(oracle.get("target_accepted_otif_mean", 0))
                - float(history.get("target_accepted_otif_mean", 0))
            )
            lines.append(
                f"- **oracle - history gap**: {gap_pp:+.1f}pp. A gap of this "
                "size suggests forecast quality matters, but even the oracle "
                "does not turn better demand information into a Pareto gain at "
                "this fixed total."
            )
            rest_pp = 100.0 * (
                float(oracle.get("rest_accepted_otif_mean", 0))
                - float(baseline.get("rest_accepted_otif_mean", 0))
            )
            all_pp = 100.0 * (
                float(oracle.get("accepted_otif_mean", 0))
                - float(baseline.get("accepted_otif_mean", 0))
            )
            target_pp_oracle = 100.0 * (
                float(oracle.get("target_accepted_otif_mean", 0)) - base_target
            )
            if rest_pp < -1.0:
                lines.append(
                    f"- **The oracle does not buy target service.** Its target "
                    f"moves {target_pp_oracle:+.1f}pp while rest moves "
                    f"{rest_pp:+.1f}pp and all-order OTIF {all_pp:+.1f}pp "
                    "versus baseline: this is reallocation, not a Pareto gain."
                )
        if not pareto_like:
            lines.append(
                "- **No arm dominates the hand-picked baseline.** The coverage "
                "MILP improves its own proxy (`coverage`) but not all three "
                "end-to-end metrics. A likely reason is that the objective "
                "ignores pick load/queue and arrival timing; concentrating "
                "stock in the demand-accessible DC can create a pick bottleneck "
                "that the static proxy never sees."
            )
        for load_key, base_key in (
            ("access_history_load", "access_history"),
            ("access_oracle_load", "access_oracle"),
        ):
            load_row = rows.get(load_key)
            base_row = rows.get(base_key)
            if not load_row or not base_row:
                continue
            load_pp = 100.0 * (
                float(load_row.get("target_accepted_otif_mean", 0))
                - float(base_row.get("target_accepted_otif_mean", 0))
            )
            lines.append(
                f"- **{load_key} vs {base_key}**: target "
                f"{_pct(base_row.get('target_accepted_otif_mean', 0))} -> "
                f"{_pct(load_row.get('target_accepted_otif_mean', 0))} "
                f"({load_pp:+.1f}pp); all-order "
                f"{_pct(base_row.get('accepted_otif_mean', 0))} -> "
                f"{_pct(load_row.get('accepted_otif_mean', 0))}; backlog "
                f"{_num(base_row.get('accepted_backlog_units', 0))} -> "
                f"{_num(load_row.get('accepted_backlog_units', 0))}; peak "
                f"stock-implied pick "
                f"{_num(load_row.get('peak_pick_minutes_mean', 0))} min/DC, "
                f"overload {_num(load_row.get('overload_minutes_mean', 0))} min. "
                "The load cap is a placement proxy, so this tests whether "
                "avoiding concentration helps, not whether the real queue is "
                "optimised."
            )
        lines.append(
            "- **This is not a production policy.** `access_oracle` sees the "
            "week's orders; `access_history` still uses the current week's "
            "destination/transit matrix and assumes the transfer is available "
            "before the week starts. Both are declared experiment arms."
        )
        lines.append("")
    else:
        lines += ["## Findings", "", "- No baseline row; cannot compute deltas.", ""]

    limitations = payload.get("limitations", [])
    if limitations:
        lines += ["## Limitations", ""] + [f"- {item}" for item in limitations] + [""]
    return "\n".join(lines)


def write_access_report(
    payload: Mapping[str, Any],
    directory: str | Path,
    title: str | None = None,
    stem: str = "ACCESS",
) -> Dict[str, Path]:
    """Write ``<STEM>_REPORT.md`` and ``<stem>_summary.json``."""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    if title:
        data["title"] = title
    prefix = str(stem).strip().upper() or "ACCESS"
    report = out / f"{prefix}_REPORT.md"
    summary = out / f"{prefix.lower()}_summary.json"
    report.write_text(build_access_report(data), encoding="utf-8")
    summary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"report": report, "summary": summary}
