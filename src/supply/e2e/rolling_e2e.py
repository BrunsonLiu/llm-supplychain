"""Week 20: multi-day rolling allocation joined to picking and dispatch.

Week 19 measured the allocation layer only. This module takes the same daily
flow, then for every day runs the Week-16 pick/dispatch stack on that day's
sub-instance. Delivery is scored on the **absolute** promise date
(``order_day + promise``), and a ticket that misses the day's last departure
fails that order rather than rolling into a later day.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult

from .arrival import EmpiricalArrivals
from .dispatch import DispatchCell, run_dispatch_cell
from .instances import E2EInstance
from .joint import capacity_aware_allocation
from .rolling import (
    FLOW_DAYS,
    ROLLING_DEADLINES,
    _daily_instance,
    _replenish,
)

E2E_ROLLING_POLICIES = ("none", "daily_1d", "daily_2d")
E2E_POLICY_LABELS = {
    "none": "不补货 · 日滚动端到端",
    "daily_1d": "每日 1 天补货 · 日滚动端到端",
    "daily_2d": "每日 2 天补货 · 日滚动端到端",
    "single_week": "单周一次性快照 · 端到端",
}
DEFAULT_SEEDS = tuple(range(1, 31))


@dataclass
class PreparedDay:
    day: int
    instance: E2EInstance
    allocation: FulfillmentResult
    lines: np.ndarray
    open_orders: np.ndarray


@dataclass
class PreparedFlow:
    policy: str
    days: List[PreparedDay]
    remaining: np.ndarray
    demand_units: int
    replenished_units: int
    stock_start: int


def prepare_flow(
    instance: E2EInstance,
    order_day: np.ndarray,
    policy: str,
    service_time: float = 3.0,
    milp_time: float = 8.0,
    workers: int = 2,
    safety: float = 0.10,
) -> PreparedFlow:
    """Allocate each day's open lines and keep the sub-instance for dispatch."""
    if policy not in E2E_ROLLING_POLICIES:
        raise ValueError(f"未知端到端补货策略: {policy}")
    fulfillment = instance.fulfillment
    days = min(FLOW_DAYS, int(order_day.max()) + 1 if order_day.size else 0)
    remaining = fulfillment.line_qty.copy()
    stock = fulfillment.stock.copy()
    capacity = fulfillment.dc_capacity.copy()
    pipeline: Dict[int, np.ndarray] = {}
    prepared: List[PreparedDay] = []
    replenished = 0
    for day in range(days):
        if day in pipeline:
            arrival = pipeline.pop(day)
            stock += arrival
            replenished += int(arrival.sum())
        built = _daily_instance(
            instance, order_day, remaining, stock, capacity, day
        )
        if built is None:
            continue
        daily, lines, open_orders = built
        before = stock.copy()
        allocation = capacity_aware_allocation(
            daily,
            service_time=service_time,
            milp_time=milp_time,
            workers=workers,
            pick_deadlines=ROLLING_DEADLINES,
            name=f"Week 20 · {policy} · day {day}",
        )
        for position, line in enumerate(lines):
            remaining[line] -= int(allocation.shipments[position].sum())
        stock = before - allocation.stock_used
        capacity = np.maximum(0, capacity - allocation.dc_units)
        _replenish(policy, day, stock, fulfillment.stock, days, pipeline, safety)
        prepared.append(
            PreparedDay(
                day=day,
                instance=daily,
                allocation=allocation,
                lines=lines,
                open_orders=open_orders,
            )
        )
    return PreparedFlow(
        policy=policy,
        days=prepared,
        remaining=remaining,
        demand_units=int(fulfillment.line_qty.sum()),
        replenished_units=replenished,
        stock_start=int(fulfillment.stock.sum()),
    )


def _dispatch_instance(prepared: PreparedDay) -> E2EInstance:
    """Map residual 1..5-day promises to the three pick tiers before dispatch.

    Allocation uses the exact remaining days, but the pick plan and ticket
    cutoff map only supports the declared 2/3/5 tiers. A 1-day residual is the
    express tier; a 4-day residual rounds to the 5-day tier.
    """
    promises = prepared.instance.fulfillment.promise_days
    tiered = np.where(promises <= 2, 2, np.where(promises == 3, 3, 5))
    fulfillment = replace(
        prepared.instance.fulfillment, promise_days=tiered.astype(np.int64)
    )
    return replace(prepared.instance, fulfillment=fulfillment)


def _fully_allocated(instance: E2EInstance, remaining: np.ndarray) -> np.ndarray:
    result = np.zeros(instance.n_orders, dtype=bool)
    for order in range(instance.n_orders):
        order_lines = np.flatnonzero(instance.fulfillment.line_order == order)
        result[order] = bool(np.all(remaining[order_lines] == 0))
    return result


def _deadline(instance: E2EInstance, order_day: np.ndarray) -> np.ndarray:
    return order_day + instance.fulfillment.promise_days


def run_flow_e2e(
    flow: PreparedFlow,
    base: E2EInstance,
    order_day: np.ndarray,
    seeds: Sequence[int],
    arrivals: EmpiricalArrivals,
    cell: DispatchCell,
) -> pd.DataFrame:
    """Run one seed through every day and score absolute delivery dates."""
    if cell.policy == "none":
        raise ValueError("Week 20 只比较发车策略，不接受 none")
    fully = _fully_allocated(base, flow.remaining)
    deadline = _deadline(base, order_day)
    rows: List[Dict[str, Any]] = []
    demand = max(1, flow.demand_units)
    for seed in seeds:
        delivered: Dict[int, int] = {}
        unshipped: set = set()
        for prepared in flow.days:
            _, outcome = run_dispatch_cell(
                _dispatch_instance(prepared),
                prepared.allocation,
                cell,
                int(seed),
                arrivals,
                scenario="milp_load",
            )
            if outcome is None:
                continue
            mapping = {
                local: int(order)
                for local, order in enumerate(prepared.open_orders)
            }
            for local, local_day in outcome.delivered_day.items():
                order = mapping[int(local)]
                absolute = int(prepared.day) + int(local_day)
                delivered[order] = max(delivered.get(order, 0), absolute)
            for local in outcome.unshipped_orders:
                unshipped.add(mapping[int(local)])
        on_time = np.zeros(base.n_orders, dtype=bool)
        delivered_days: List[int] = []
        for order in range(base.n_orders):
            if not fully[order] or order in unshipped or order not in delivered:
                continue
            day = int(delivered[order])
            delivered_days.append(day)
            if day <= int(deadline[order]):
                on_time[order] = True
        late_orders = int(base.n_orders - on_time.sum())
        row = {
            "policy": flow.policy,
            "seed": int(seed),
            "e2e_otif_rate": float(on_time.mean()) if base.n_orders else 0.0,
            "fill_rate": float(1.0 - flow.remaining.sum() / demand),
            "late_orders": int(late_orders),
            "backlog_units": int(flow.remaining.sum()),
            "avg_delivery_day": (
                float(np.mean(delivered_days)) if delivered_days else 0.0
            ),
            "replenished_units": int(flow.replenished_units),
            "orders": int(base.n_orders),
        }
        for day in range(FLOW_DAYS):
            mask = np.asarray(order_day) == day
            if mask.any():
                row[f"otif_day_{day}"] = float(on_time[mask].mean())
            else:
                row[f"otif_day_{day}"] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def run_single_week_e2e(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    seeds: Sequence[int],
    arrivals: EmpiricalArrivals,
    cell: DispatchCell,
) -> pd.DataFrame:
    """Week-16 dock layer on one weekly allocation, absolute promise dates."""
    rows = []
    demand = max(1, int(instance.fulfillment.line_qty.sum()))
    for seed in seeds:
        _, outcome = run_dispatch_cell(
            instance, allocation, cell, int(seed), arrivals, scenario="milp_load"
        )
        if outcome is None:
            raise ValueError("单周基线需要发车策略")
        rows.append(
            {
                "policy": "single_week",
                "seed": int(seed),
                "e2e_otif_rate": float(outcome.order_dock_ok.mean()),
                "fill_rate": float(allocation.unit_fill_rate),
                "late_orders": int(
                    (~outcome.order_dock_ok).sum()
                ),
                "backlog_units": int(allocation.unmet.sum()),
                "avg_delivery_day": (
                    float(np.mean(list(outcome.delivered_day.values())))
                    if outcome.delivered_day
                    else 0.0
                ),
                "replenished_units": 0,
                "orders": int(instance.n_orders),
                "otif_day_0": float(outcome.order_dock_ok.mean()),
                **{
                    f"otif_day_{day}": float("nan")
                    for day in range(1, FLOW_DAYS)
                },
            }
        )
    return pd.DataFrame(rows)


def summarize_flow(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    rows = []
    for policy, group in frame.groupby("policy", sort=False):
        otif = group["e2e_otif_rate"].to_numpy(dtype=float)
        rows.append(
            {
                "policy": policy,
                "label": E2E_POLICY_LABELS.get(policy, policy),
                "seeds": int(len(group)),
                "e2e_otif_mean": float(otif.mean()),
                "e2e_otif_p10": float(np.percentile(otif, 10)),
                "e2e_otif_p50": float(np.percentile(otif, 50)),
                "e2e_otif_p90": float(np.percentile(otif, 90)),
                "fill_mean": float(group["fill_rate"].mean()),
                "late_orders_mean": float(group["late_orders"].mean()),
                "backlog_units": int(group["backlog_units"].iloc[0]),
                "avg_delivery_day": float(group["avg_delivery_day"].mean()),
                "replenished_units": int(group["replenished_units"].iloc[0]),
                **{
                    f"otif_day_{day}": float(group[f"otif_day_{day}"].mean())
                    for day in range(FLOW_DAYS)
                    if f"otif_day_{day}" in group
                },
            }
        )
    return pd.DataFrame(rows)


def paired_e2e_delta(
    frame: pd.DataFrame, left: str, right: str
) -> Dict[str, float]:
    """Paired mean/CI/win-loss for two policies on identical seeds."""
    left_frame = frame[frame["policy"] == left].set_index("seed")
    right_frame = frame[frame["policy"] == right].set_index("seed")
    common = sorted(set(left_frame.index) & set(right_frame.index))
    if not common:
        return {}
    delta = (
        left_frame.loc[common, "e2e_otif_rate"].to_numpy()
        - right_frame.loc[common, "e2e_otif_rate"].to_numpy()
    )
    mean = float(delta.mean())
    std = float(delta.std(ddof=1)) if len(delta) > 1 else 0.0
    half = 1.96 * std / np.sqrt(len(delta)) if len(delta) > 1 else 0.0
    return {
        "left": left,
        "right": right,
        "n": int(len(delta)),
        "mean": mean,
        "ci95": half,
        "win": float((delta > 0).mean()),
        "loss": float((delta < 0).mean()),
        "tie": float((delta == 0).mean()),
    }


def prepare_baseline(
    instance: E2EInstance,
    service_time: float = 30.0,
    milp_time: float = 60.0,
    workers: int = 2,
) -> FulfillmentResult:
    return capacity_aware_allocation(
        instance,
        service_time=service_time,
        milp_time=milp_time,
        workers=workers,
        pick_deadlines=ROLLING_DEADLINES,
        name="Week 20 · 单周快照",
    )


def e2e_cells() -> List[DispatchCell]:
    return [
        DispatchCell(
            key=f"week20_{policy}",
            label=f"Week 20 · {policy}",
            policy="immediate",
            min_load=1,
            max_days=0,
            pickers_per_dc=1,
        )
        for policy in E2E_ROLLING_POLICIES
    ]


def baseline_cell() -> DispatchCell:
    return DispatchCell(
        key="week20_single_week",
        label="Week 20 · 单周快照",
        policy="promise",
        min_load=6,
        max_days=3,
        pickers_per_dc=1,
    )
