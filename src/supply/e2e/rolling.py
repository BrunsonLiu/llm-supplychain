"""Week 19: multi-day rolling allocation with inventory carryover.

The earlier e2e weeks allocate one fixed weekly order pool against one stock
snapshot. This module splits the same 400 invoices into five weekday order
batches, re-solves the capacity-aware MILP every day for the still-open lines,
carries stock forward, and optionally restores consumed units after a declared
replenishment lead time. It is intentionally a **weekly allocation layer**:
picking, release and dispatch are fixed to their Week-16/17 conclusions and are
not replayed, so the result isolates inventory carryover from dock effects.
"""
from __future__ import annotations

import gc
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentInstance

from .instances import E2EInstance
from .joint import capacity_aware_allocation

FLOW_DAYS = 5
ROLLING_POLICIES = (
    "none",
    "daily_1d",
    "daily_2d",
    "daily_1d_safety",
    "batch_2d",
)
POLICY_LABELS = {
    "none": "不补货（仅 85% 初始库存）",
    "daily_1d": "每日回补 · 1 天前置期",
    "daily_2d": "每日回补 · 2 天前置期",
    "daily_1d_safety": "每日回补 +10% 安全量 · 1 天",
    "batch_2d": "每 2 天批量回补 · 1 天",
}
DEFAULT_SAFETY = 0.10
ROLLING_DEADLINES = {1: 240, 2: 240, 3: 480, 4: 480, 5: 600}


@dataclass(frozen=True)
class RollingCell:
    key: str
    label: str
    policy: str


def order_day_map(instance: E2EInstance, clean: pd.DataFrame) -> np.ndarray:
    """Map every invoice to weekday 0..4; weekend invoices land on Friday."""
    frame = clean.copy()
    frame["invoice"] = frame["invoice"].astype(str)
    dates = (
        frame.drop_duplicates("invoice")
        .set_index("invoice")["invoice_date"]
        .sort_index()
    )
    days = np.full(instance.n_orders, FLOW_DAYS - 1, dtype=np.int64)
    for index, invoice in enumerate(instance.order_ids):
        stamp = dates.get(str(invoice))
        if stamp is None or pd.isna(stamp):
            continue
        days[index] = min(int(pd.Timestamp(stamp).dayofweek), FLOW_DAYS - 1)
    return days


def _daily_instance(
    instance: E2EInstance,
    order_day: np.ndarray,
    remaining: np.ndarray,
    stock: np.ndarray,
    capacity: np.ndarray,
    day: int,
) -> Optional[tuple]:
    """Build a one-day sub-instance of still-open lines."""
    remaining_order = np.bincount(
        instance.fulfillment.line_order,
        weights=remaining,
        minlength=instance.n_orders,
    )
    open_orders = np.flatnonzero((order_day <= day) & (remaining_order > 0))
    if open_orders.size == 0:
        return None
    order_pos = {int(order): pos for pos, order in enumerate(open_orders)}
    lines = np.flatnonzero(
        (remaining > 0)
        & np.isin(instance.fulfillment.line_order, open_orders)
    )
    if lines.size == 0:
        return None
    local_order = np.array(
        [order_pos[int(instance.fulfillment.line_order[line])] for line in lines],
        dtype=np.int64,
    )
    fulfillment = instance.fulfillment
    promises = np.maximum(
        1,
        order_day[open_orders] + fulfillment.promise_days[open_orders] - day,
    )
    daily = replace(
        fulfillment,
        order_ids=[fulfillment.order_ids[int(order)] for order in open_orders],
        destinations=[fulfillment.destinations[int(order)] for order in open_orders],
        line_order=local_order,
        line_sku=fulfillment.line_sku[lines],
        line_qty=remaining[lines].copy(),
        stock=stock.copy(),
        dc_capacity=capacity.copy(),
        ship_cost=fulfillment.ship_cost[:, open_orders].copy(),
        transit_days=fulfillment.transit_days[:, open_orders].copy(),
        promise_days=promises,
        meta={**fulfillment.meta, "rolling_day": int(day)},
    )
    return replace(instance, fulfillment=daily), lines, open_orders


def _replenish(
    policy: str,
    day: int,
    stock: np.ndarray,
    initial_stock: np.ndarray,
    days: int,
    pipeline: Dict[int, np.ndarray],
    safety: float,
) -> None:
    """Order up to the stock cover needed for the remaining week.

    The target declines linearly from the initial weekly level to zero, so the
    policy **moves** stock toward later days instead of adding a second week of
    supply. Total available units stay close to the 85% initial snapshot.
    """
    if policy == "none":
        return
    if policy == "batch_2d" and day % 2 == 0:
        return
    lead = 2 if policy == "daily_2d" else 1
    arrival = day + lead
    if arrival >= days:
        return
    cover = max(0.0, float(days - arrival) / float(days))
    target = initial_stock.astype(float) * cover
    if policy == "daily_1d_safety":
        target = target * (1.0 + safety)
    future = np.zeros_like(stock)
    for future_day, units in pipeline.items():
        if future_day >= day:
            future += units
    need = np.ceil(target - (stock + future)).astype(np.int64)
    need = np.maximum(0, need)
    _add(pipeline, arrival, need)


def _add(pipeline: Dict[int, np.ndarray], day: int, units: np.ndarray) -> None:
    if day >= FLOW_DAYS:
        return
    if day not in pipeline:
        pipeline[day] = np.zeros_like(units)
    pipeline[day] += units


def run_rolling_policy(
    instance: E2EInstance,
    order_day: np.ndarray,
    policy: str,
    service_time: float = 4.0,
    milp_time: float = 12.0,
    workers: int = 4,
    safety: float = DEFAULT_SAFETY,
) -> Dict[str, Any]:
    """Replay one replenishment policy over the five-day order flow."""
    if policy not in ROLLING_POLICIES:
        raise ValueError(f"未知补货策略: {policy}")
    fulfillment = instance.fulfillment
    days = int(order_day.max()) + 1 if order_day.size else 0
    days = min(FLOW_DAYS, days)
    remaining = fulfillment.line_qty.copy()
    total_demand = int(remaining.sum())
    stock = fulfillment.stock.copy()
    capacity = fulfillment.dc_capacity.copy()
    pipeline: Dict[int, np.ndarray] = {}
    order_delivery: Dict[int, int] = {}
    allocated_units = 0
    replenished = 0
    stockout_days = 0
    inventory_start: List[int] = []
    inventory_end: List[int] = []
    daily_rows: List[Dict[str, Any]] = []
    deadline = order_day + fulfillment.promise_days

    for day in range(days):
        arrived = 0
        if day in pipeline:
            arrival = pipeline.pop(day)
            stock += arrival
            arrived = int(arrival.sum())
            replenished += arrived
        inventory_start.append(int(stock.sum()))
        built = _daily_instance(
            instance, order_day, remaining, stock, capacity, day
        )
        if built is None:
            inventory_end.append(int(stock.sum()))
            daily_rows.append(
                {
                    "day": day,
                    "orders_open": 0,
                    "units_open": 0,
                    "allocated_units": 0,
                    "backlog_units": int(remaining.sum()),
                    "replenished_units": 0,
                    "inventory_units": int(stock.sum()),
                }
            )
            continue
        daily, lines, open_orders = built
        order_pos = {
            int(order): pos for pos, order in enumerate(open_orders)
        }
        before = stock.copy()
        allocation = capacity_aware_allocation(
            daily,
            service_time=service_time,
            milp_time=milp_time,
            workers=workers,
            pick_deadlines=ROLLING_DEADLINES,
            name=f"滚动 {policy} · day {day}",
        )
        allocations = allocation.shipments
        for position, line in enumerate(lines):
            shipped = int(allocations[position].sum())
            if shipped <= 0:
                continue
            remaining[line] -= shipped
            allocated_units += shipped
            order = int(fulfillment.line_order[line])
            local = order_pos[order]
            for dc in np.flatnonzero(allocations[position] > 0):
                candidate = day + int(
                    daily.fulfillment.transit_days[int(dc), local]
                )
                order_delivery[order] = max(
                    order_delivery.get(order, 0), candidate
                )
        stock = before - allocation.stock_used
        capacity = np.maximum(0, capacity - allocation.dc_units)
        _replenish(policy, day, stock, fulfillment.stock, days, pipeline, safety)
        if int(allocation.unmet.sum()) > 0:
            stockout_days += 1
        inventory_end.append(int(stock.sum()))
        daily_rows.append(
            {
                "day": day,
                "orders_open": int(open_orders.size),
                "units_open": int(daily.fulfillment.line_qty.sum()),
                "allocated_units": int(allocation.fulfilled_units),
                "backlog_units": int(remaining.sum()),
                "replenished_units": arrived,
                "inventory_units": int(stock.sum()),
                "solve_seconds": float(allocation.solve_seconds),
            }
        )
        del allocation
        gc.collect()

    fully = np.zeros(instance.n_orders, dtype=bool)
    for order in range(instance.n_orders):
        order_lines = np.flatnonzero(fulfillment.line_order == order)
        fully[order] = bool(np.all(remaining[order_lines] == 0))
    on_time = np.zeros(instance.n_orders, dtype=bool)
    late_units = 0
    for order in range(instance.n_orders):
        if not fully[order]:
            continue
        delivered = order_delivery.get(order)
        if delivered is None:
            continue
        if delivered <= int(deadline[order]):
            on_time[order] = True
        order_lines = np.flatnonzero(fulfillment.line_order == order)
        for line in order_lines:
            shipped = int(fulfillment.line_qty[line] - remaining[line])
            if shipped > 0 and delivered > int(deadline[order]):
                late_units += shipped

    order_days = []
    for day in range(days):
        mask = order_day == day
        order_days.append(
            {
                "day": day,
                "orders": int(mask.sum()),
                "otif_rate": float(on_time[mask].mean()) if mask.any() else 0.0,
                "fill_rate": (
                    float(
                        1.0
                        - remaining[
                            np.isin(fulfillment.line_order, np.flatnonzero(mask))
                        ].sum()
                        / max(
                            1,
                            fulfillment.line_qty[
                                np.isin(
                                    fulfillment.line_order, np.flatnonzero(mask)
                                )
                            ].sum(),
                        )
                    )
                    if mask.any()
                    else 0.0
                ),
            }
        )

    return {
        "policy": policy,
        "label": POLICY_LABELS.get(policy, policy),
        "days": days,
        "demand_units": total_demand,
        "allocated_units": allocated_units,
        "fill_rate": allocated_units / total_demand if total_demand else 0.0,
        "otif_rate": float(on_time.mean()) if instance.n_orders else 0.0,
        "late_units": late_units,
        "backlog_units": int(remaining.sum()),
        "replenished_units": replenished,
        "stockout_days": stockout_days,
        "avg_inventory_units": (
            float(np.mean(inventory_start)) if inventory_start else 0.0
        ),
        "orders": instance.n_orders,
        "fully_allocated": int(fully.sum()),
        "daily": daily_rows,
        "by_order_day": order_days,
    }


def single_week_baseline(
    instance: E2EInstance,
    service_time: float = 4.0,
    milp_time: float = 12.0,
    workers: int = 4,
) -> Dict[str, Any]:
    """The Week-18 one-shot weekly allocation, scored on the same deadline rule."""
    allocation = capacity_aware_allocation(
        instance,
        service_time=service_time,
        milp_time=milp_time,
        workers=workers,
        pick_deadlines=ROLLING_DEADLINES,
        name="单周快照",
    )
    fulfillment = instance.fulfillment
    order_units = fulfillment.order_units()
    order_fulfilled = np.bincount(
        fulfillment.line_order,
        weights=allocation.shipments.sum(axis=1),
        minlength=instance.n_orders,
    )
    fully = order_fulfilled >= order_units
    delivery = np.zeros(instance.n_orders, dtype=np.int64)
    for order in range(instance.n_orders):
        order_lines = np.flatnonzero(fulfillment.line_order == order)
        day_used = 1
        for line in order_lines:
            for dc in np.flatnonzero(allocation.shipments[line] > 0):
                day_used = max(day_used, int(fulfillment.transit_days[dc, order]))
        delivery[order] = day_used
    on_time = fully & (delivery <= fulfillment.promise_days)
    late_units = int(
        sum(
            int(order_units[order])
            for order in range(instance.n_orders)
            if fully[order] and delivery[order] > int(fulfillment.promise_days[order])
        )
    )
    return {
        "policy": "single_week",
        "label": "单周一次性快照（Week-18 口径）",
        "days": 1,
        "demand_units": int(fulfillment.line_qty.sum()),
        "allocated_units": int(allocation.fulfilled_units),
        "fill_rate": allocation.unit_fill_rate,
        "otif_rate": float(on_time.mean()) if instance.n_orders else 0.0,
        "late_units": late_units,
        "backlog_units": int(allocation.unmet.sum()),
        "replenished_units": 0,
        "stockout_days": 0,
        "avg_inventory_units": float(fulfillment.stock.sum()),
        "orders": instance.n_orders,
        "fully_allocated": int(fully.sum()),
        "solve_seconds": float(allocation.solve_seconds),
    }


def rolling_cells() -> List[RollingCell]:
    return [
        RollingCell(policy, POLICY_LABELS[policy], policy)
        for policy in ROLLING_POLICIES
    ]
