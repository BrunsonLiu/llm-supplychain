"""Markdown + JSON report for the inventory benchmark."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

_HORIZON_NOTES = {
    "eoq_rop": "fixed EOQ, reorder point = lead-time demand + safety stock",
    "periodic": "review every R weeks, order up to R + lead-time cover",
    "min_max": "continuous review, order up to upper target when below trigger",
}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if pd.isna(value):
        return None
    return value


def _md_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "_(empty)_"
    columns = [str(col) for col in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for _, row in frame.iterrows():
        cells = []
        for value in row:
            if isinstance(value, float):
                cells.append("—" if not math.isfinite(value) else f"{value:,.4g}")
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                cells.append("—")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _pct(value: Any) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.2%}"


def _num(value: Any, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):,.{digits}f}"


def _policy_table(frame: pd.DataFrame, mc: bool = False) -> pd.DataFrame:
    if frame.empty:
        return frame
    rows = []
    for _, row in frame.iterrows():
        label = row.get("label") or row.get("policy")
        if mc:
            rows.append(
                {
                    "policy": label,
                    "fill rate P5": _pct(row.get("fill_rate_p5")),
                    "fill rate P50": _pct(row.get("fill_rate_p50")),
                    "fill rate P95": _pct(row.get("fill_rate_p95")),
                    "cost P5": _num(row.get("total_cost_p5")),
                    "cost P50": _num(row.get("total_cost_p50")),
                    "cost P95": _num(row.get("total_cost_p95")),
                    "turns": _num(row.get("turns"), 2),
                }
            )
        else:
            rows.append(
                {
                    "policy": label,
                    "fill rate": _pct(row.get("fill_rate")),
                    "SKU-week in-stock": _pct(row.get("sku_week_instock_rate")),
                    "stockout weeks": _pct(row.get("stockout_week_rate")),
                    "avg on-hand": _num(row.get("avg_on_hand")),
                    "turns": _num(row.get("turns"), 2),
                    "holding": _num(row.get("holding_cost")),
                    "ordering": _num(row.get("ordering_cost")),
                    "stockout": _num(row.get("stockout_cost")),
                    "total cost": _num(row.get("total_cost")),
                    "cost / unit": _num(row.get("cost_per_unit"), 3),
                }
            )
    return pd.DataFrame(rows)


def _forecast_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        name = str(row["forecast"])
        rows.append(
            {
                "forecast": name,
                "WMAPE": _pct(row["wmape"]),
                "bias": _pct(row["bias"]),
                "units": _num(row["units"]),
            }
        )
    return pd.DataFrame(rows)


def _sweep_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "target SL": _pct(row["service_level"]),
                "z": _num(row.get("z"), 2),
                "fill rate": _pct(row["fill_rate"]),
                "SKU-week in-stock": _pct(row.get("sku_week_instock_rate")),
                "stockout weeks": _pct(row["stockout_week_rate"]),
                "avg on-hand": _num(row["avg_on_hand"]),
                "turns": _num(row.get("turns"), 2),
                "holding": _num(row.get("holding_cost")),
                "ordering": _num(row.get("ordering_cost")),
                "stockout": _num(row.get("stockout_cost")),
                "total cost": _num(row.get("total_cost")),
            }
        )
    return pd.DataFrame(rows)


def _lead_time_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "lead time (weeks)": int(row["lead_time_weeks"]),
                "policy": row.get("label") or row["policy"],
                "fill rate": _pct(row["fill_rate"]),
                "SKU-week in-stock": _pct(row.get("sku_week_instock_rate")),
                "avg on-hand": _num(row["avg_on_hand"]),
                "turns": _num(row.get("turns"), 2),
                "total cost": _num(row.get("total_cost")),
            }
        )
    return pd.DataFrame(rows)


def _milp_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "method": row["method"],
                "fill rate": _pct(row["fill_rate"]),
                "total cost": _num(row.get("total_cost")),
                "cost / unit": _num(row.get("cost_per_unit"), 3),
                "turns": _num(row.get("turns"), 2),
                "fixed orders": _num(row.get("fixed_orders")),
                "solve (s)": _num(row.get("solve_seconds"), 2),
            }
        )
    return pd.DataFrame(rows)


def _allocation_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "scenario": row["scenario"],
                "fill rate": _pct(row["fill_rate"]),
                "unmet units": _num(row["unmet_units"]),
                "transport": _num(row["transport_cost"]),
                "shortage": _num(row["shortage_cost"]),
                "total": _num(row["total_cost"]),
                "cost / unit": _num(row.get("cost_per_unit"), 3),
                "solve (s)": _num(row.get("solve_seconds"), 3),
            }
        )
    return pd.DataFrame(rows)


def _store_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in frame.iterrows():
        rows.append(
            {
                "store": row["store"],
                "demand": _num(row["demand_units"]),
                "shipped": _num(row["shipped_units"]),
                "unmet": _num(row["unmet_units"]),
                "fill rate": _pct(row["fill_rate"]),
                "DC1 share": _pct(row["dc1_share"]),
            }
        )
    return pd.DataFrame(rows)


def _assumption_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    display = []
    for row in rows:
        display.append(
            {
                "parameter": row["parameter"],
                "value": row["value"],
                "source": row["source"],
                "note": row.get("note", ""),
            }
        )
    return pd.DataFrame(display)


def build_inventory_report(
    results: Dict[str, Any],
    title: str = "Inventory policy benchmark",
) -> tuple[Dict[str, Any], str]:
    dataset = results.get("dataset", {})
    assumptions = results.get("assumptions", {})
    assumption_summary = results.get("assumption_summary", {})
    timestamps = datetime.now(timezone.utc).isoformat()

    replay = results.get("policy_replay", pd.DataFrame())
    mc = results.get("policy_mc", pd.DataFrame())
    sweep = results.get("service_sweep", pd.DataFrame())
    lead_time = results.get("lead_time", pd.DataFrame())
    forecast_accuracy = results.get("forecast_accuracy", pd.DataFrame())
    forecast_comparison = results.get("forecast_comparison", pd.DataFrame())
    milp = results.get("milp", {})
    allocation = results.get("allocation", {})

    summary: Dict[str, Any] = {
        "generated_at": timestamps,
        "title": title,
        "dataset": _json_safe(dataset),
        "assumptions": _json_safe(assumptions),
        "assumption_summary": _json_safe(assumption_summary),
        "forecast_accuracy": _json_safe(
            forecast_accuracy.to_dict(orient="records") if not forecast_accuracy.empty else []
        ),
        "policy_replay": _json_safe(
            replay.to_dict(orient="records") if not replay.empty else []
        ),
        "policy_monte_carlo": _json_safe(
            mc.to_dict(orient="records") if not mc.empty else []
        ),
        "forecast_comparison": _json_safe(
            forecast_comparison.to_dict(orient="records")
            if not forecast_comparison.empty
            else []
        ),
        "service_level_sweep": _json_safe(
            sweep.to_dict(orient="records") if not sweep.empty else []
        ),
        "lead_time_sensitivity": _json_safe(
            lead_time.to_dict(orient="records") if not lead_time.empty else []
        ),
        "milp": _json_safe(
            {
                key: value
                for key, value in milp.items()
                if key != "comparison"
            }
        ),
        "milp_comparison": _json_safe(
            milp.get("comparison", pd.DataFrame()).to_dict(orient="records")
            if isinstance(milp.get("comparison"), pd.DataFrame)
            else milp.get("comparison", [])
        ),
        "allocation": _json_safe(
            {
                key: value
                for key, value in allocation.items()
                if key not in {"summary", "stores"}
            }
        ),
        "allocation_summary": _json_safe(
            allocation.get("summary", pd.DataFrame()).to_dict(orient="records")
            if isinstance(allocation.get("summary"), pd.DataFrame)
            else []
        ),
    }

    lines = [f"# {title}", ""]
    lines.append(f"- Generated: `{timestamps}`")
    lines.append(
        f"- Data: Online Retail II, {dataset.get('skus', '?')} SKUs, "
        f"evaluation `{dataset.get('eval_start', '?')}` → `{dataset.get('eval_end', '?')}` "
        f"({dataset.get('eval_weeks', '?')} weeks)"
    )
    lines.append(
        f"- Eligibility: excluded {dataset.get('skus_excluded_insufficient_history', 0)} SKUs "
        f"with fewer than {dataset.get('min_history_nonzero_weeks', '?')} non-zero history weeks "
        "or mean demand below 1 unit/week; parameters are estimated on the preceding "
        f"{dataset.get('history_weeks', '?')} weeks only."
    )
    lines.append(
        f"- Forecast: **{dataset.get('primary_forecast', '?')}**, "
        f"evaluation WMAPE {_pct(dataset.get('forecast_wmape'))}"
    )
    lines.append(
        f"- Parameters estimated on `{dataset.get('history_start', '?')}` → "
        f"`{dataset.get('history_end', '?')}` ({dataset.get('history_weeks', '?')} weeks)"
    )
    lines.append(
        f"- Planning assumptions: lead time {assumptions.get('lead_time_weeks', '?')} weeks, "
        f"service level {_pct(assumptions.get('service_level'))}, "
        f"holding {_pct(assumptions.get('holding_rate_annual'))}/yr, "
        f"order cost {assumptions.get('ordering_cost', '?')}"
    )
    lines.append("")

    lines.extend(["## 1. Assumption layer", ""])
    lines.append(
        "Demand, price, and calendar come from the dataset. Everything else is an "
        "explicit assumption so a reviewer can challenge it instead of discovering it buried in code."
    )
    lines.append("")
    lines.append(_md_table(_assumption_table(results.get("assumption_rows", []))))
    lines.append("")
    lines.append(
        f"- Annual demand of the selected basket: **{_num(assumption_summary.get('annual_units'))}** units, "
        f"list value at observed prices **{_num(assumption_summary.get('annual_revenue_at_price'))}**."
    )
    lines.append(
        f"- Median weekly CV **{_num(assumption_summary.get('median_cv'), 2)}**, "
        f"median zero-demand share **{_pct(assumption_summary.get('median_zero_share'))}**, "
        f"median EOQ **{_num(assumption_summary.get('median_eoq'))}** units."
    )
    lines.append("")

    lines.extend(["## 2. Forecast quality in the evaluation window", ""])
    lines.append(_md_table(_forecast_table(forecast_accuracy)))
    lines.append("")
    lines.append(
        "WMAPE is the demand-weighted absolute error; bias is "
        "`Σ(forecast − actual) / Σ actual`, so a positive value means the forecast "
        "over-predicts. These errors are measured on the same SKU subset used by the policies."
    )
    lines.append(
        "The policy engine sees only the forecast, never the realized path. "
        "Forecast error therefore propagates directly into the inventory KPIs."
    )
    lines.append("")

    lines.extend(
        [f"## 3. Policy replay: {dataset.get('eval_weeks', '?')} weeks of realized demand", ""]
    )
    lines.append(_md_table(_policy_table(replay)))
    lines.append("")
    if not replay.empty:
        best_fill = replay.sort_values("fill_rate", ascending=False).iloc[0]
        best_cost = replay.sort_values("total_cost").iloc[0]
        lines.append(
            f"- Highest fill rate: **{best_fill.get('label', best_fill.get('policy'))}** "
            f"({_pct(best_fill.get('fill_rate'))}); lowest total cost: "
            f"**{best_cost.get('label', best_cost.get('policy'))}** "
            f"({_num(best_cost.get('total_cost'))})."
        )
    lines.append(
        "- Replay is a single realized path: useful for tracing orders and inventory, "
        "but it hides the tail risk that a Monte Carlo run exposes."
    )
    lines.append("")

    lines.extend(["## 4. Monte Carlo: demand and decision risk", ""])
    lines.append(
        f"{int(assumptions.get('n_simulations', 0))} scenarios per SKU. Demand is compound: "
        "zero with the historical intermittency probability, otherwise lognormal around the "
        "forecast with the historical CV, rescaled so the scenario mean equals the forecast."
    )
    lines.append("")
    lines.append(_md_table(_policy_table(mc, mc=True)))
    lines.append("")
    if not mc.empty:
        spread = (
            mc.assign(spread=lambda frame: frame["fill_rate_p95"] - frame["fill_rate_p5"])
            .sort_values("spread")
            .iloc[0]
        )
        lines.append(
            f"- Tightest fill-rate distribution: **{spread.get('label')}** "
            f"(P5–P95 spread {_pct(spread.get('spread'))})."
        )
    lines.append("")

    if not forecast_comparison.empty:
        lines.extend(["### 4b. Forecast source effect", ""])
        rows = []
        for _, row in forecast_comparison.iterrows():
            rows.append(
                {
                    "forecast": row["forecast"],
                    "policy": row.get("label", row.get("policy")),
                    "fill rate": _pct(row["fill_rate"]),
                    "avg on-hand": _num(row["avg_on_hand"]),
                    "turns": _num(row.get("turns"), 2),
                    "total cost": _num(row.get("total_cost")),
                }
            )
        lines.append(_md_table(pd.DataFrame(rows)))
        lines.append("")

    lines.extend(["## 5. Service-level trade-off", ""])
    lines.append(
        "The same policy is re-run across target cycle service levels, using the same "
        "Monte Carlo demand paths. This separates the service decision from the policy choice."
    )
    lines.append("")
    lines.append(_md_table(_sweep_table(sweep)))
    lines.append("")
    if not sweep.empty:
        cheapest = sweep.sort_values("total_cost").iloc[0]
        lines.append(
            f"- Cost-minimising target in this sweep: **{_pct(cheapest.get('service_level'))}** "
            f"at total cost {_num(cheapest.get('total_cost'))}; "
            "the 95% target is a business input, not an optimisation result."
        )
    lines.append("")

    lines.extend(["## 6. Lead-time sensitivity", ""])
    lines.append(
        "Lead time is not observable in the public dataset. Instead of hiding it, "
        "the benchmark re-runs every policy at several coverage horizons."
    )
    lines.append("")
    lines.append(_md_table(_lead_time_table(lead_time)))
    lines.append("")

    lines.extend(["## 7. Multi-period replenishment MILP", ""])
    lines.append(
        f"- Solver: OR-Tools CP-SAT; {milp.get('skus', '?')} SKUs (top by historical mean demand) × "
        f"{milp.get('weeks', '?')} weeks; lead time {milp.get('lead_time_weeks', '?')} weeks; "
        f"shared storage {_num(milp.get('storage_capacity'))} units and "
        f"inbound throughput {_num(milp.get('throughput_capacity'))} units/week."
    )
    lines.append(
        "- Rolling horizon re-plans weekly with the forecast and executes only the "
        "current-week order; perfect foresight uses realized demand and is the best "
        "achievable plan, not an implementable policy."
    )
    lines.append(
        "- The point-forecast rolling model is deterministic and holds no buffer against "
        "forecast error: it plans to the mean path, so it inherits the forecast's bias. "
        "This is the single largest driver of the rolling/perfect-foresight gap."
    )
    lines.append("")
    lines.append(_md_table(_milp_table(milp.get("comparison", pd.DataFrame()))))
    lines.append("")
    if milp.get("utilization"):
        util = milp["utilization"]
        lines.append(
            f"- Peak shared-capacity utilisation: rolling storage "
            f"{_pct(util.get('rolling_storage_peak'))}, throughput "
            f"{_pct(util.get('rolling_throughput_peak'))}; perfect foresight storage "
            f"{_pct(util.get('perfect_storage_peak'))}, throughput "
            f"{_pct(util.get('perfect_throughput_peak'))}."
        )
    if milp.get("statuses"):
        config = milp.get("config", {})
        budget = config.get("deterministic_time")
        basis = (
            f"CP-SAT deterministic-time budget {budget:g} per solve"
            if budget
            else f"wall-clock limit {config.get('time_limit_seconds', '?')}s per solve"
        )
        lines.append(
            f"- Rolling solver statuses: `{milp.get('statuses')}`. When the plan is "
            "infeasible (on-hand and pipeline already exceed the shared storage limit), "
            "that week executes zero orders rather than adding to an already violated "
            f"capacity. One worker, a fixed seed, and a {basis} make re-runs reproduce "
            "the same plan."
        )
    lines.append(
        "- The gap between rolling and perfect foresight is the value of forecast accuracy; "
        "the gap between the policies and perfect foresight is the value of reactivity "
        "(rule policies see realized demand every week and can reorder immediately)."
    )
    lines.append("")

    if allocation and not allocation.get("summary", pd.DataFrame()).empty:
        summary_frame = allocation.get("summary", pd.DataFrame())
        stores = allocation.get("stores", pd.DataFrame())
        config = allocation.get("config", {})
        lines.extend(["## 8. DC → store allocation", ""])
        lines.append(
            f"One representative week, {config.get('stores', '?')} stores, "
            f"2 DCs, DC stock covers {_pct(config.get('supply_factor'))} of store demand; "
            "store receiving capacity is an explicit space constraint."
        )
        lines.append("")
        lines.append(_md_table(_allocation_table(summary_frame)))
        lines.append("")
        if not stores.empty:
            lines.append("Priority scenario, store level:")
            lines.append("")
            lines.append(_md_table(_store_table(stores)))
            lines.append("")
        lines.append(
            "With equal penalties the LP is indifferent to *who* absorbs a shortage; "
            "priority weights change the allocation, not the total physical capacity."
        )
        lines.append("")

    lines.extend(
        [
            "## 9. Limitations",
            "",
            "- Lead time, costs, MOQ, store shares, and the DC cost matrix are assumptions, "
            "not observations. They are configurable in one dataclass and one network builder.",
            "- Point forecasts are used without a predictive distribution; the Monte Carlo "
            "layer is a scenario generator around the point forecast, not a calibrated "
            "probabilistic forecast.",
            "- The MILP is a single-echelon model on a Top-N SKU subset. It does not model "
            "multi-echelon inventory, case-pack rounding, truckload consolidation, or "
            "stochastic demand. A `z·σ`-buffered rolling variant exists as an API option "
            "(`rolling_horizon(..., safety_stock=...)`), but it is not reported here: under "
            "hard shared-capacity limits the buffered plan is often infeasible and the "
            "reported numbers move with the solver time limit.",
            "- Rule-based policies ignore shared storage and inbound throughput, while the "
            "MILP enforces them. The comparison therefore mixes policy quality with "
            "constraint feasibility and should be read as indicative, not as a controlled "
            "A/B test.",
            "- The rolling MILP is deterministic and plans to the point forecast, so it "
            "inherits forecast bias and has no mechanism to stock against forecast error. "
            "That is why its fill rate trails the rule policies even though its cost "
            "objective is better specified.",
            "- The reported MILP plan is the best incumbent found within the deterministic-"
            "time budget, not a proven optimum; a larger budget can change the plan.",
            "- MILP inventory turns are annualised from the 13-week window and are not "
            "comparable to full-year turns. Shared capacity is sized from the same window "
            "(storage = 5× mean weekly demand, inbound throughput = 3× mean weekly demand), "
            "so the throughput limit binds in peak weeks by construction.",
            "- No service-level optimisation is performed end-to-end: the sweep shows the "
            "cost-service frontier, while the target remains a business input.",
            "",
        ]
    )
    return summary, "\n".join(lines)


def write_inventory_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Inventory policy benchmark",
    detail: Optional[pd.DataFrame] = None,
) -> Dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary, markdown = build_inventory_report(results, title=title)

    paths = {
        "markdown": out_dir / "INVENTORY_REPORT.md",
        "summary": out_dir / "inventory_summary.json",
    }
    paths["markdown"].write_text(markdown, encoding="utf-8")
    with open(paths["summary"], "w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    if detail is not None and not detail.empty:
        paths["detail"] = out_dir / "inventory_policy_detail.csv"
        detail.to_csv(paths["detail"], index=False)
    return paths
