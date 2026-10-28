"""Weekly replenishment simulation: replay and Monte Carlo.

The engine is deliberately simple and auditable: weekly buckets, lost sales,
orders placed at the start of a week and received after ``lead_time_weeks``,
and three rule-based policies. It is vectorised over Monte Carlo scenarios so
200 SKUs x 300 scenarios stay in the seconds range.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from .assumptions import service_level_z
from .policies import PolicySpec


@dataclass
class PolicyRun:
    policy: PolicySpec
    weeks: int
    weekly: Dict[str, np.ndarray] = field(default_factory=dict)
    scenario: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: Dict[str, float] = field(default_factory=dict)
    parameters: Dict[str, float] = field(default_factory=dict)


def _forecast_sum(forecast_cum: np.ndarray, start: int, length: int) -> float:
    if length <= 0:
        return 0.0
    end = min(start + length, len(forecast_cum) - 1)
    return float(max(0.0, forecast_cum[end] - forecast_cum[start]))


def run_policy(
    demand: np.ndarray,
    forecast: Sequence[float],
    economics: Mapping[str, Any],
    policy: PolicySpec,
    lead_time_weeks: int,
    initial_inventory: Optional[float] = None,
) -> PolicyRun:
    """Simulate one replenishment rule against one or more demand paths.

    ``demand`` has shape ``(scenarios, weeks)``; ``forecast`` has shape
    ``(weeks,)`` and is the information set available at each review. The
    policy reacts to realized demand through the inventory position, exactly as
    a planner would.
    """
    policy.validate()
    demand = np.atleast_2d(np.asarray(demand, dtype=float))
    if demand.ndim != 2 or demand.shape[1] == 0:
        raise ValueError("demand 必须是 (scenarios, weeks) 的二维非空数组")
    scenarios, weeks = demand.shape
    forecast = np.asarray(forecast, dtype=float)
    if forecast.shape != (weeks,):
        raise ValueError(f"forecast 长度应为 {weeks}，实际 {forecast.shape}")

    lead = max(int(lead_time_weeks), 0)
    review = max(int(policy.review_period_weeks), 1)
    z = service_level_z(policy.service_level)

    mean = float(economics["mean_weekly"])
    sigma = float(economics["sigma_weekly"])
    moq = float(economics["moq"])
    eoq = max(float(economics["eoq"]), moq)
    initial = (
        float(initial_inventory)
        if initial_inventory is not None
        else float(economics["initial_inventory"])
    )
    holding_unit_week = float(economics["holding_cost_per_unit_week"])
    ordering_cost = float(economics["ordering_cost"])
    stockout_cost = float(economics["stockout_cost_per_unit"])

    # Simulate a short tail so in-transit orders can arrive; only the first
    # ``weeks`` periods are scored.
    tail = lead + 1
    horizon = weeks + tail
    tail_level = float(np.mean(forecast[-min(4, weeks):])) if weeks else 0.0
    forecast_ext = np.concatenate([forecast, np.full(tail, tail_level)])
    forecast_cum = np.concatenate([[0.0], np.cumsum(forecast_ext)])
    demand_ext = np.empty((scenarios, horizon))
    demand_ext[:, :weeks] = demand
    demand_ext[:, weeks:] = tail_level

    on_hand = np.full(scenarios, initial, dtype=float)
    pipeline = np.zeros((scenarios, horizon + lead + 2))
    rows = np.arange(scenarios)

    weekly = {
        key: np.zeros((scenarios, weeks))
        for key in ("demand", "sales", "lost", "on_hand", "orders", "order_count")
    }

    for t in range(horizon):
        on_hand += pipeline[:, t]
        on_order = pipeline[:, t + 1 : t + 1 + lead].sum(axis=1) if lead > 0 else 0.0
        position = on_hand + on_order

        safety_cover = z * sigma * np.sqrt(lead) if lead > 0 else 0.0
        trigger = _forecast_sum(forecast_cum, t, lead) + safety_cover
        upper = _forecast_sum(forecast_cum, t, lead + review) + z * sigma * np.sqrt(
            lead + review
        )

        if policy.kind == "eoq_rop":
            quantity = np.where(position < trigger, eoq, 0.0)
        elif policy.kind == "periodic":
            review_week = t % review == 0
            if review_week:
                quantity = np.maximum(upper - position, 0.0)
            else:
                quantity = np.zeros(scenarios)
        elif policy.kind == "min_max":
            quantity = np.where(
                position < trigger, np.maximum(upper - position, moq), 0.0
            )
        else:  # pragma: no cover - guarded by PolicySpec.validate
            raise ValueError(policy.kind)

        quantity = np.where(quantity > 0, np.maximum(quantity, moq), 0.0)
        placed = quantity > 0

        if lead == 0:
            on_hand += quantity
        else:
            pipeline[rows, t + lead] += quantity

        available = np.maximum(on_hand, 0.0)
        sales = np.minimum(available, demand_ext[:, t])
        lost = demand_ext[:, t] - sales
        on_hand = available - sales

        if t < weeks:
            weekly["demand"][:, t] = demand_ext[:, t]
            weekly["sales"][:, t] = sales
            weekly["lost"][:, t] = lost
            weekly["on_hand"][:, t] = on_hand
            weekly["orders"][:, t] = quantity
            weekly["order_count"][:, t] = placed.astype(float)

    scenario = pd.DataFrame(
        {
            "demand_units": weekly["demand"].sum(axis=1),
            "sold_units": weekly["sales"].sum(axis=1),
            "lost_units": weekly["lost"].sum(axis=1),
            "orders": weekly["order_count"].sum(axis=1),
            "order_units": weekly["orders"].sum(axis=1),
            "avg_on_hand": weekly["on_hand"].mean(axis=1),
            "holding_cost": holding_unit_week * weekly["on_hand"].sum(axis=1),
            "ordering_cost": ordering_cost * weekly["order_count"].sum(axis=1),
            "stockout_cost": stockout_cost * weekly["lost"].sum(axis=1),
        }
    )
    scenario["total_cost"] = (
        scenario["holding_cost"] + scenario["ordering_cost"] + scenario["stockout_cost"]
    )
    scenario["fill_rate"] = np.where(
        scenario["demand_units"] > 0,
        1.0 - scenario["lost_units"] / scenario["demand_units"].replace(0, np.nan),
        1.0,
    )
    demand_weeks = weekly["demand"] > 0
    stockout_weeks = (weekly["lost"] > 1e-9) & demand_weeks
    demand_week_count = demand_weeks.sum(axis=1)
    safe_weeks = np.where(demand_week_count > 0, demand_week_count, 1)
    scenario["stockout_week_rate"] = np.where(
        demand_week_count > 0,
        stockout_weeks.sum(axis=1) / safe_weeks,
        0.0,
    )
    scenario["sku_week_instock_rate"] = 1.0 - scenario["stockout_week_rate"]
    scenario["turns"] = np.where(
        scenario["avg_on_hand"] > 0,
        scenario["sold_units"] / scenario["avg_on_hand"] * (52.0 / weeks),
        np.nan,
    )
    scenario["cost_per_unit"] = np.where(
        scenario["sold_units"] > 0,
        scenario["total_cost"] / scenario["sold_units"].replace(0, np.nan),
        np.nan,
    )

    summary = {
        "weeks": float(weeks),
        "scenarios": float(scenarios),
        "demand_units": float(scenario["demand_units"].mean()),
        "sold_units": float(scenario["sold_units"].mean()),
        "lost_units": float(scenario["lost_units"].mean()),
        "fill_rate": _pooled_fill(scenario),
        "stockout_week_rate": float(scenario["stockout_week_rate"].mean()),
        "sku_week_instock_rate": float(scenario["sku_week_instock_rate"].mean()),
        "avg_on_hand": float(scenario["avg_on_hand"].mean()),
        "turns": _safe_mean(scenario["turns"]),
        "orders": float(scenario["orders"].mean()),
        "order_units": float(scenario["order_units"].mean()),
        "holding_cost": float(scenario["holding_cost"].mean()),
        "ordering_cost": float(scenario["ordering_cost"].mean()),
        "stockout_cost": float(scenario["stockout_cost"].mean()),
        "total_cost": float(scenario["total_cost"].mean()),
        "cost_per_unit": _safe_mean(scenario["cost_per_unit"]),
    }
    for column, label in (
        ("fill_rate", "fill_rate"),
        ("total_cost", "total_cost"),
        ("avg_on_hand", "avg_on_hand"),
    ):
        values = scenario[column].dropna()
        summary[f"{label}_p5"] = float(values.quantile(0.05)) if len(values) else np.nan
        summary[f"{label}_p50"] = float(values.quantile(0.50)) if len(values) else np.nan
        summary[f"{label}_p95"] = float(values.quantile(0.95)) if len(values) else np.nan

    return PolicyRun(
        policy=policy,
        weeks=weeks,
        weekly=weekly,
        scenario=scenario,
        summary=summary,
        parameters={
            "z": z,
            "mean_weekly": mean,
            "sigma_weekly": sigma,
            "eoq": eoq,
            "moq": moq,
            "initial_inventory": initial,
            "reorder_point_at_mean": mean * lead + z * sigma * np.sqrt(lead),
            "order_up_to_at_mean": mean * (lead + review)
            + z * sigma * np.sqrt(lead + review),
            "lead_time_weeks": float(lead),
            "review_period_weeks": float(review),
        },
    )


def _pooled_fill(scenario: pd.DataFrame) -> float:
    demand = float(scenario["demand_units"].sum())
    lost = float(scenario["lost_units"].sum())
    if demand <= 0:
        return 1.0
    return 1.0 - lost / demand


def _safe_mean(values: pd.Series) -> float:
    clean = values.dropna()
    return float(clean.mean()) if len(clean) else float("nan")


def simulate_demand_scenarios(
    forecast: Sequence[float],
    economics: Mapping[str, Any],
    n_simulations: int,
    seed: int,
    cv_cap: float = 1.5,
    zero_cap: float = 0.6,
) -> np.ndarray:
    """Compound demand: zero with probability ``p0``, else lognormal around the forecast.

    The non-zero branch is scaled by ``1 / (1 - p0)`` so the scenario mean stays
    equal to the forecast. This keeps intermittent SKUs from being silently
    under-forecast.
    """
    forecast = np.asarray(forecast, dtype=float)
    if forecast.ndim != 1:
        raise ValueError("forecast 必须是一维数组")
    weeks = len(forecast)
    p0 = float(np.clip(economics.get("zero_share", 0.0), 0.0, zero_cap))
    cv = float(np.clip(economics.get("cv", 0.0), 0.05, cv_cap))
    sigma_log = float(np.sqrt(np.log1p(cv**2)))
    scale = 1.0 / max(1.0 - p0, 0.05)
    mu_log = float(np.log(scale) - 0.5 * sigma_log**2)

    rng = np.random.default_rng(seed)
    noise = rng.lognormal(mu_log, sigma_log, size=(n_simulations, weeks))
    zeros = rng.random((n_simulations, weeks)) < p0
    demand = forecast[np.newaxis, :] * noise
    demand[zeros] = 0.0
    demand[:, forecast <= 0] = 0.0
    return demand


def run_all_policies(
    demand: np.ndarray,
    forecast: Sequence[float],
    economics: Mapping[str, Any],
    policies: Iterable[PolicySpec],
    lead_time_weeks: int,
    initial_inventory: float | None = None,
) -> Dict[str, PolicyRun]:
    return {
        policy.kind: run_policy(
            demand,
            forecast,
            economics,
            policy,
            lead_time_weeks,
            initial_inventory=initial_inventory,
        )
        for policy in policies
    }


def aggregate_runs(
    runs_by_sku: Mapping[str, Mapping[str, PolicyRun]],
    economics: pd.DataFrame,
    policy_kind: str,
    weeks: int,
) -> pd.DataFrame:
    """Per-scenario portfolio metrics for one policy across all SKUs."""
    total_scenarios: Optional[int] = None
    accumulated: Dict[str, np.ndarray] = {}

    for sku, runs in runs_by_sku.items():
        if policy_kind not in runs:
            continue
        run = runs[policy_kind]
        econ = economics.loc[sku]
        if total_scenarios is None:
            total_scenarios = run.weekly["demand"].shape[0]
            for key in ("demand", "sales", "lost", "on_hand", "order_count"):
                accumulated[key] = np.zeros((total_scenarios, weeks))
            accumulated["holding"] = np.zeros((total_scenarios, weeks))
            accumulated["ordering"] = np.zeros((total_scenarios, weeks))
            accumulated["stockout"] = np.zeros((total_scenarios, weeks))
            accumulated["demand_sku_weeks"] = np.zeros((total_scenarios, weeks))
            accumulated["stockout_sku_weeks"] = np.zeros((total_scenarios, weeks))

        accumulated["demand"] += run.weekly["demand"]
        accumulated["sales"] += run.weekly["sales"]
        accumulated["lost"] += run.weekly["lost"]
        accumulated["on_hand"] += run.weekly["on_hand"]
        accumulated["order_count"] += run.weekly["order_count"]
        accumulated["demand_sku_weeks"] += run.weekly["demand"] > 0
        accumulated["stockout_sku_weeks"] += (run.weekly["lost"] > 1e-9) & (
            run.weekly["demand"] > 0
        )
        accumulated["holding"] += run.weekly["on_hand"] * float(
            econ["holding_cost_per_unit_week"]
        )
        accumulated["ordering"] += run.weekly["order_count"] * float(
            econ["ordering_cost"]
        )
        accumulated["stockout"] += run.weekly["lost"] * float(
            econ["stockout_cost_per_unit"]
        )

    if total_scenarios is None:
        raise ValueError(f"没有任何 SKU 包含策略 {policy_kind} 的结果")

    frame = pd.DataFrame(
        {
            "demand_units": accumulated["demand"].sum(axis=1),
            "sold_units": accumulated["sales"].sum(axis=1),
            "lost_units": accumulated["lost"].sum(axis=1),
            "orders": accumulated["order_count"].sum(axis=1),
            "avg_on_hand": accumulated["on_hand"].mean(axis=1),
            "holding_cost": accumulated["holding"].sum(axis=1),
            "ordering_cost": accumulated["ordering"].sum(axis=1),
            "stockout_cost": accumulated["stockout"].sum(axis=1),
        }
    )
    frame["total_cost"] = (
        frame["holding_cost"] + frame["ordering_cost"] + frame["stockout_cost"]
    )
    frame["fill_rate"] = np.where(
        frame["demand_units"] > 0,
        1.0 - frame["lost_units"] / frame["demand_units"].replace(0, np.nan),
        1.0,
    )
    demand_weeks = accumulated["demand"] > 0
    stockout_weeks = (accumulated["lost"] > 1e-9) & demand_weeks
    demand_week_count = demand_weeks.sum(axis=1)
    safe_weeks = np.where(demand_week_count > 0, demand_week_count, 1)
    frame["stockout_week_rate"] = np.where(
        demand_week_count > 0,
        stockout_weeks.sum(axis=1) / safe_weeks,
        0.0,
    )
    demand_sku_weeks = accumulated["demand_sku_weeks"].sum(axis=1)
    stockout_sku_weeks = accumulated["stockout_sku_weeks"].sum(axis=1)
    frame["sku_week_instock_rate"] = np.where(
        demand_sku_weeks > 0,
        1.0 - stockout_sku_weeks / np.where(demand_sku_weeks > 0, demand_sku_weeks, 1),
        1.0,
    )
    frame["turns"] = np.where(
        frame["avg_on_hand"] > 0,
        frame["sold_units"] / frame["avg_on_hand"] * (52.0 / weeks),
        np.nan,
    )
    frame["cost_per_unit"] = np.where(
        frame["sold_units"] > 0,
        frame["total_cost"] / frame["sold_units"].replace(0, np.nan),
        np.nan,
    )
    return frame


def summarize_portfolio(
    scenarios: pd.DataFrame,
    policy: PolicySpec,
) -> Dict[str, Any]:
    """Mean / percentile KPI summary for one policy at portfolio level."""

    def q(column: str, quantile: float) -> float:
        values = scenarios[column].dropna()
        return float(values.quantile(quantile)) if len(values) else float("nan")

    demand = float(scenarios["demand_units"].sum())
    lost = float(scenarios["lost_units"].sum())
    return {
        "policy": policy.kind,
        "label": policy.label,
        "service_level": policy.service_level,
        "demand_units": demand / len(scenarios),
        "lost_units": lost / len(scenarios),
        "fill_rate": 1.0 - lost / demand if demand > 0 else 1.0,
        "fill_rate_p5": q("fill_rate", 0.05),
        "fill_rate_p50": q("fill_rate", 0.50),
        "fill_rate_p95": q("fill_rate", 0.95),
        "stockout_week_rate": float(scenarios["stockout_week_rate"].mean()),
        "sku_week_instock_rate": float(scenarios["sku_week_instock_rate"].mean()),
        "avg_on_hand": float(scenarios["avg_on_hand"].mean()),
        "turns": _safe_mean(scenarios["turns"]),
        "orders": float(scenarios["orders"].mean()),
        "holding_cost": float(scenarios["holding_cost"].mean()),
        "ordering_cost": float(scenarios["ordering_cost"].mean()),
        "stockout_cost": float(scenarios["stockout_cost"].mean()),
        "total_cost": float(scenarios["total_cost"].mean()),
        "total_cost_p5": q("total_cost", 0.05),
        "total_cost_p50": q("total_cost", 0.50),
        "total_cost_p95": q("total_cost", 0.95),
        "cost_per_unit": _safe_mean(scenarios["cost_per_unit"]),
    }


def service_level_sweep(
    demand: np.ndarray,
    forecast: Sequence[float],
    economics: Mapping[str, Any],
    lead_time_weeks: int,
    service_levels: Sequence[float],
    kind: str = "eoq_rop",
    review_period_weeks: int = 2,
) -> pd.DataFrame:
    rows = []
    for level in service_levels:
        policy = PolicySpec(kind, float(level), review_period_weeks)
        run = run_policy(demand, forecast, economics, policy, lead_time_weeks)
        row = dict(run.summary)
        row.update(
            {
                "service_level": float(level),
                "policy": policy.kind,
                "label": policy.label,
                "avg_on_hand": run.summary["avg_on_hand"],
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def lead_time_sensitivity(
    demand: np.ndarray,
    forecast: Sequence[float],
    economics: Mapping[str, Any],
    policies: Iterable[PolicySpec],
    lead_times: Sequence[int],
) -> pd.DataFrame:
    rows = []
    for lead in lead_times:
        for policy in policies:
            run = run_policy(demand, forecast, economics, policy, lead)
            row = dict(run.summary)
            row.update(
                {
                    "policy": policy.kind,
                    "label": policy.label,
                    "lead_time_weeks": int(lead),
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)
