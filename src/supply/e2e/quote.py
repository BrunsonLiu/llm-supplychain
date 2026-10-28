"""Week 18: promise quoting (ATP) and the promise-service frontier.

Every earlier e2e week draws the customer promise from a fixed 2/3/5-day mix
before allocation. This module makes the promise a decision: quote the tier
implied by the slowest order line's fastest in-stock DC, then score the same
orders against both the quoted promise and the Week-15 baseline SLA.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult

from .dispatch import DispatchCell, run_dispatch_cell
from .instances import E2EInstance, rebuild_pick_plan
from .joint import capacity_aware_allocation
from .pipeline import allocation_order_status

QUOTE_POLICIES = (
    "static",
    "atp",
    "atp_buffer",
    "atp_cap2",
    "atp_cap3",
    "all_2",
    "all_3",
    "all_5",
)
DEFAULT_MAX_PROMISE = 5


def tier_for_days(days: float) -> int:
    """Map a physically feasible day count to the declared 2/3/5 tier."""
    if days <= 2:
        return 2
    if days <= 3:
        return 3
    return 5


def _atp_quotes(instance: E2EInstance) -> np.ndarray:
    fulfillment = instance.fulfillment
    orders = instance.n_orders
    demand = np.zeros((orders, fulfillment.n_skus), dtype=np.int64)
    np.add.at(demand, (fulfillment.line_order, fulfillment.line_sku), fulfillment.line_qty)
    quotes = np.full(orders, DEFAULT_MAX_PROMISE, dtype=np.int64)
    for order in range(orders):
        lines = np.flatnonzero(fulfillment.line_order == order)
        if lines.size == 0:
            continue
        leg_days = []
        for line in lines:
            sku = int(fulfillment.line_sku[line])
            qty = int(fulfillment.line_qty[line])
            available = fulfillment.stock[:, sku] >= qty
            if not bool(available.any()):
                leg_days = [DEFAULT_MAX_PROMISE]
                break
            leg_days.append(int(fulfillment.transit_days[available, order].min()))
        earliest = 1 + max(leg_days)
        quotes[order] = tier_for_days(earliest)
    return quotes


def quote_promises(instance: E2EInstance, policy: str) -> np.ndarray:
    """Promise vector for one quoting policy."""
    if policy not in QUOTE_POLICIES:
        raise ValueError(f"未知承诺策略: {policy}")
    if policy == "static":
        return instance.fulfillment.promise_days.astype(np.int64).copy()
    if policy in ("atp", "atp_buffer", "atp_cap2", "atp_cap3"):
        quotes = _atp_quotes(instance)
        if policy == "atp_buffer":
            quotes = np.where(quotes == 2, 3, np.where(quotes == 3, 5, 5))
        elif policy == "atp_cap2":
            quotes = np.minimum(quotes, 2)
        elif policy == "atp_cap3":
            quotes = np.minimum(quotes, 3)
        return quotes.astype(np.int64)
    if policy == "all_2":
        return np.full(instance.n_orders, 2, dtype=np.int64)
    if policy == "all_3":
        return np.full(instance.n_orders, 3, dtype=np.int64)
    return np.full(instance.n_orders, 5, dtype=np.int64)


@dataclass(frozen=True)
class QuoteCell:
    """One quoting policy on top of one dispatch/pick cell."""

    key: str
    label: str
    quote: str
    dispatch: DispatchCell
    keep_cutoffs: bool = False


def solve_quote(
    instance: E2EInstance,
    policy: str,
    service_time: float = 30.0,
    milp_time: float = 60.0,
    workers: int = 4,
    service_late_weight: float = 5.0,
    service_otif_bonus: float = 200.0,
    pick_overload_penalty: float = 5.0,
    keep_cutoffs: bool = False,
):
    """Apply a quoting policy and solve its allocation once."""
    promises = quote_promises(instance, policy)
    quoted = rebuild_pick_plan(instance, promises, keep_cutoffs=keep_cutoffs)
    allocation = capacity_aware_allocation(
        quoted,
        service_time=service_time,
        milp_time=milp_time,
        workers=workers,
        service_late_weight=service_late_weight,
        service_otif_bonus=service_otif_bonus,
        pick_overload_penalty=pick_overload_penalty,
        name=f"报价 {policy}",
    )
    return quoted, allocation


def _quote_metrics(
    quoted: E2EInstance,
    allocation: FulfillmentResult,
    outcome,
    baseline_promises: np.ndarray,
) -> Dict[str, float]:
    status = allocation_order_status(quoted, allocation)
    alloc_ok = status["alloc_ok"]
    orders = quoted.n_orders
    delivered = outcome.delivered_day if outcome is not None else {}
    quoted_days = quoted.fulfillment.promise_days
    quoted_ok = 0
    static_ok = 0
    late = 0
    delivered_days: List[int] = []
    for order in range(orders):
        if not bool(alloc_ok[order]):
            continue
        day = delivered.get(order)
        if day is None:
            continue
        delivered_days.append(int(day))
        if day <= int(quoted_days[order]):
            quoted_ok += 1
        if day <= int(baseline_promises[order]):
            static_ok += 1
        if day > int(quoted_days[order]):
            late += 1
    return {
        "quoted_otif_rate": quoted_ok / orders if orders else 0.0,
        "static_sla_otif_rate": static_ok / orders if orders else 0.0,
        "late_orders": float(late),
        "mean_delivered_day": float(np.mean(delivered_days)) if delivered_days else 0.0,
        "avg_promise_days": float(np.mean(quoted_days)) if orders else 0.0,
        "fast_share": float(np.mean(quoted_days == 2)) if orders else 0.0,
        "slow_share": float(np.mean(quoted_days == 5)) if orders else 0.0,
    }


def run_quote_monte_carlo(
    quoted: E2EInstance,
    allocation: FulfillmentResult,
    cell: QuoteCell,
    seeds: Sequence[int],
    arrivals,
    baseline_promises: np.ndarray,
    scenario: str = "milp_load",
) -> pd.DataFrame:
    """Replay one quoting policy over arrival seeds; allocation stays fixed."""
    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        row, outcome = run_dispatch_cell(
            quoted,
            allocation,
            cell.dispatch,
            int(seed),
            arrivals,
            keep_cutoffs=cell.keep_cutoffs,
        )
        row.update(_quote_metrics(quoted, allocation, outcome, baseline_promises))
        row.update(
            {
                "scenario": scenario,
                "cell": cell.key,
                "cell_label": cell.label,
                "quote": cell.quote,
                "policy": cell.dispatch.policy,
                "seed": int(seed),
                "fill_rate": float(allocation.unit_fill_rate),
                "alloc_otif_rate": float(allocation.otif_rate),
                "alloc_cost": float(allocation.total_cost),
                "solve_seconds": float(allocation.solve_seconds),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def quote_frontier(frame: pd.DataFrame) -> pd.DataFrame:
    """Mean promise, fast share and both service metrics per cell."""
    if frame.empty:
        return pd.DataFrame()
    grouped = frame.groupby(["cell", "cell_label"], sort=False)
    rows = []
    for (cell, label), group in grouped:
        rows.append(
            {
                "cell": cell,
                "label": label,
                "avg_promise_days": float(group["avg_promise_days"].mean()),
                "fast_share": float(group["fast_share"].mean()),
                "slow_share": float(group["slow_share"].mean()),
                "quoted_otif_rate": float(group["quoted_otif_rate"].mean()),
                "static_sla_otif_rate": float(group["static_sla_otif_rate"].mean()),
                "fill_rate": float(group["fill_rate"].mean()),
                "alloc_otif_rate": float(group["alloc_otif_rate"].mean()),
                "pick_otif_rate": float(group["pick_otif_rate"].mean()),
            }
        )
    return pd.DataFrame(rows)
