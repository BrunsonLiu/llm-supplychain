"""Explicit assumption layer for inventory decisions.

Online Retail II provides demand, price, and calendar only. Lead time, holding
and shortage costs, order costs, initial stock, and MOQ are *not* observable in
the dataset. Every number produced by this package therefore mixes two sources:

* **Observed** -- weekly demand, selling price, demand volatility.
* **Assumed**  -- everything in :class:`InventoryAssumptions`.

Keeping the split explicit is the point: the optimiser is only as credible as
the assumptions it is fed, and a reviewer must be able to challenge each one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from statistics import NormalDist
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class InventoryAssumptions:
    """Planning assumptions shared by policy simulation and the MILP."""

    service_level: float = 0.95
    lead_time_weeks: int = 3
    review_period_weeks: int = 2
    holding_rate_annual: float = 0.22
    ordering_cost: float = 75.0
    cost_ratio: float = 0.60
    lost_margin_multiplier: float = 1.0
    initial_inventory_weeks: float = 3.0
    min_order_weeks: float = 0.5
    forecast_window_weeks: int = 52
    n_simulations: int = 300
    random_seed: int = 42

    def validate(self) -> None:
        if not 0.5 <= self.service_level < 1.0:
            raise ValueError("service_level 必须在 [0.5, 1) 之间")
        if self.lead_time_weeks < 0:
            raise ValueError("lead_time_weeks 不能为负")
        if self.review_period_weeks < 1:
            raise ValueError("review_period_weeks 必须 >= 1")
        if not 0 < self.cost_ratio < 1:
            raise ValueError("cost_ratio 必须在 (0, 1) 之间")
        if self.holding_rate_annual <= 0 or self.ordering_cost <= 0:
            raise ValueError("持有率与订货成本必须为正")
        if self.initial_inventory_weeks < 0:
            raise ValueError("initial_inventory_weeks 不能为负")
        if self.n_simulations < 1:
            raise ValueError("n_simulations 必须 >= 1")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def with_overrides(self, **overrides: Any) -> "InventoryAssumptions":
        return replace(self, **overrides)


def service_level_z(service_level: float) -> float:
    """Standard-normal quantile for a target cycle service level."""
    if not 0.5 <= service_level < 1.0:
        raise ValueError("service_level 必须在 [0.5, 1) 之间")
    if service_level == 0.5:
        return 0.0
    return float(NormalDist().inv_cdf(service_level))


def safety_stock(
    service_level: float,
    sigma_weekly: float,
    coverage_weeks: float,
) -> float:
    """Safety stock for a coverage horizon, assuming independent weekly errors."""
    if coverage_weeks <= 0:
        return 0.0
    return service_level_z(service_level) * max(sigma_weekly, 0.0) * float(np.sqrt(coverage_weeks))


def economic_order_quantity(
    annual_demand: float,
    ordering_cost: float,
    holding_cost_per_unit_year: float,
) -> float:
    if annual_demand <= 0 or ordering_cost <= 0 or holding_cost_per_unit_year <= 0:
        return 0.0
    return float(np.sqrt(2.0 * annual_demand * ordering_cost / holding_cost_per_unit_year))


def build_sku_economics(
    panel: pd.DataFrame,
    assumptions: InventoryAssumptions,
    history_weeks: Optional[int] = None,
    skus: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Estimate per-SKU demand and cost parameters from an estimation window.

    ``sigma_weekly`` is the standard deviation of the one-step demand
    innovation, estimated from first differences (``std(diff)/sqrt(2)``). It is
    deliberately conservative: for strongly seasonal SKUs it also absorbs the
    seasonal movement that a random-walk error model does not see.
    """
    assumptions.validate()
    frame = panel.copy()
    frame["week"] = pd.to_datetime(frame["week"])
    if skus is not None:
        frame = frame[frame["sku"].isin(skus)]

    window = history_weeks or assumptions.forecast_window_weeks
    ordered_weeks = sorted(frame["week"].unique())[:window]
    history = frame[frame["week"].isin(ordered_weeks)].sort_values(["sku", "week"])

    grouped = history.groupby("sku", observed=True)
    stats = grouped.agg(
        mean_weekly=("demand", "mean"),
        std_weekly=("demand", "std"),
        zero_share=("demand", lambda values: float((values <= 0).mean())),
        nonzero_weeks=("demand", lambda values: int((values > 0).sum())),
        price=("avg_price", "median"),
        total_demand=("demand", "sum"),
        description=("description", "first"),
        country=("country", "first"),
    )
    stats["std_weekly"] = stats["std_weekly"].fillna(0.0)
    stats["price"] = stats["price"].fillna(stats["price"].median()).fillna(0.0)

    diff_std = (
        history.groupby("sku", observed=True)["demand"]
        .diff()
        .groupby(history["sku"])
        .std(ddof=1)
    )
    sigma = diff_std.reindex(stats.index).fillna(0.0) / np.sqrt(2.0)
    fallback = np.where(
        stats["mean_weekly"] > 0,
        (stats["mean_weekly"] * 0.5).clip(lower=0.5),
        0.0,
    )
    sigma = sigma.where(sigma > 0, fallback)
    stats["sigma_weekly"] = sigma

    stats["cv"] = np.where(
        stats["mean_weekly"] > 0, stats["std_weekly"] / stats["mean_weekly"], 0.0
    )
    stats["unit_cost"] = (stats["price"] * assumptions.cost_ratio).clip(lower=0.01)
    stats["holding_cost_per_unit_week"] = (
        stats["unit_cost"] * assumptions.holding_rate_annual / 52.0
    )
    stats["stockout_cost_per_unit"] = (
        stats["price"]
        * (1.0 - assumptions.cost_ratio)
        * assumptions.lost_margin_multiplier
    )
    stats["ordering_cost"] = assumptions.ordering_cost
    stats["annual_demand"] = stats["mean_weekly"] * 52.0
    stats["eoq"] = [
        economic_order_quantity(
            annual, assumptions.ordering_cost, unit_cost * assumptions.holding_rate_annual
        )
        for annual, unit_cost in zip(stats["annual_demand"], stats["unit_cost"])
    ]
    stats["moq"] = (stats["mean_weekly"] * assumptions.min_order_weeks).clip(lower=1.0)
    stats["initial_inventory"] = stats["mean_weekly"] * assumptions.initial_inventory_weeks
    stats["annual_revenue"] = stats["annual_demand"] * stats["price"]

    stats = stats.sort_values("total_demand", ascending=False)
    return stats.reset_index()


def assumption_summary(
    economics: pd.DataFrame,
    assumptions: InventoryAssumptions,
) -> Dict[str, Any]:
    """Aggregate context for the report (units, value, coverage)."""
    annual_units = float(economics["annual_demand"].sum())
    annual_revenue = float(economics["annual_revenue"].sum())
    initial_units = float(economics["initial_inventory"].sum())
    initial_value = float((economics["initial_inventory"] * economics["unit_cost"]).sum())
    return {
        "skus": int(len(economics)),
        "annual_units": annual_units,
        "annual_revenue_at_price": annual_revenue,
        "initial_units": initial_units,
        "initial_value": initial_value,
        "median_cv": float(economics["cv"].median()),
        "median_zero_share": float(economics["zero_share"].median()),
        "median_eoq": float(economics["eoq"].median()),
        "assumptions": assumptions.to_dict(),
    }
