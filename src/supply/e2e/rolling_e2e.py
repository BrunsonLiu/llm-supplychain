"""Week 20: multi-day rolling allocation joined to picking and dispatch.

Week 19 measured the allocation layer only. This module takes the same daily
flow, then for every day runs the Week-16 pick/dispatch stack on that day's
sub-instance. Delivery is scored on the **absolute** promise date
(``order_day + promise``), and a ticket that misses the day's last departure
fails that order rather than rolling into a later day.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult

from .arrival import EmpiricalArrivals
from .dispatch import DispatchCell, run_dispatch_cell
from .instances import E2EInstance
from .joint import capacity_aware_allocation
from .quote import QUOTE_POLICIES, quote_promises
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
    promise_days: np.ndarray
    accepted: np.ndarray
    rejected_units: int


def prepare_flow(
    instance: E2EInstance,
    order_day: np.ndarray,
    policy: str,
    service_time: float = 3.0,
    milp_time: float = 8.0,
    workers: int = 2,
    safety: float = 0.10,
    quote_policy: str = "static",
    accept_cutoff_days: int = 5,
    accept_value_threshold: Optional[float] = None,
    order_value: Optional[np.ndarray] = None,
    upgrade_value_threshold: Optional[float] = None,
    upgrade_to_days: Optional[int] = None,
    allocation_priority: Optional[np.ndarray] = None,
) -> PreparedFlow:
    """Allocate each day's open lines and keep the sub-instance for dispatch.

    ``quote_policy`` refreshes the promise for **newly arriving** orders only:
    old orders keep the absolute promise they were quoted at arrival. The
    default ``static`` reproduces Week 20/21 exactly.

    ``accept_cutoff_days`` rejects a new order when its quoted promise is
    longer than the cutoff. Rejected lines are removed from allocation and
    stock is not consumed; they remain in the demand denominator and are
    reported separately so acceptance cannot look free.

    ``accept_value_threshold`` optionally overrides the cutoff for high-value
    orders: a long-promise order is kept when its ``order_value`` is at least
    this threshold. This is a revenue-protection rule, not a margin rule;
    ``order_value`` must align with ``instance.fulfillment.order_ids``.

    ``upgrade_value_threshold`` + ``upgrade_to_days`` optionally accelerate a
    new high-value order's promise: its quote is capped at ``upgrade_to_days``
    even when ATP returns a longer promise. This is deliberately an
    over-promise stress test: the earlier deadline makes the order compete for
    stock/picking earlier, but does not guarantee that the inventory exists.

    ``allocation_priority`` optionally multiplies each order's unmet/late
    penalty inside the daily allocation. This is real stock prioritisation, not
    a promise relabel: a high-value order is more expensive to leave unmet, so
    the solver gives it scarce stock first. It still cannot create inventory.
    """
    if policy not in E2E_ROLLING_POLICIES:
        raise ValueError(f"未知端到端补货策略: {policy}")
    if quote_policy not in QUOTE_POLICIES:
        raise ValueError(f"未知承诺策略: {quote_policy}")
    if accept_cutoff_days < 2 or accept_cutoff_days > 5:
        raise ValueError("接单截止承诺必须在 2..5 天")
    if accept_value_threshold is not None or upgrade_value_threshold is not None:
        if order_value is None:
            raise ValueError("价值阈值需要 order_value")
        if np.asarray(order_value).shape != (instance.n_orders,):
            raise ValueError("order_value 必须与订单数一致")
    if upgrade_value_threshold is not None:
        if upgrade_to_days is None or upgrade_to_days < 2 or upgrade_to_days > 5:
            raise ValueError("承诺升级必须给出 2..5 天")
    if allocation_priority is not None:
        priority = np.asarray(allocation_priority, dtype=float)
        if priority.shape != (instance.n_orders,):
            raise ValueError("allocation_priority 必须与订单数一致")
        if not np.all(np.isfinite(priority)) or np.any(priority <= 0):
            raise ValueError("allocation_priority 必须为有限正数")
    fulfillment = instance.fulfillment
    days = min(FLOW_DAYS, int(order_day.max()) + 1 if order_day.size else 0)
    remaining = fulfillment.line_qty.copy()
    stock = fulfillment.stock.copy()
    capacity = fulfillment.dc_capacity.copy()
    pipeline: Dict[int, np.ndarray] = {}
    prepared: List[PreparedDay] = []
    replenished = 0
    rejected_units = 0
    accepted = np.ones(fulfillment.n_orders, dtype=bool)
    quotes = fulfillment.promise_days.astype(np.int64).copy()
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
        new_mask = order_day[open_orders] == day
        if quote_policy != "static" and bool(new_mask.any()):
            candidates = quote_promises(daily, quote_policy)
            quotes[open_orders[new_mask]] = candidates[new_mask]
        if upgrade_value_threshold is not None and bool(new_mask.any()):
            new_orders = open_orders[new_mask]
            values = np.asarray(order_value, dtype=float)[new_orders]
            high_value = new_orders[values >= float(upgrade_value_threshold)]
            if high_value.size:
                quotes[high_value] = np.minimum(
                    quotes[high_value], int(upgrade_to_days)
                )
        if accept_cutoff_days < 5 and bool(new_mask.any()):
            new_orders = open_orders[new_mask]
            long_promise = quotes[new_orders] > accept_cutoff_days
            if accept_value_threshold is not None:
                values = np.asarray(order_value, dtype=float)[new_orders]
                long_promise &= values < float(accept_value_threshold)
            rejected = new_orders[long_promise]
            if rejected.size:
                accepted[rejected] = False
                for order in rejected:
                    order_lines = fulfillment.line_order == order
                    remaining[order_lines] = 0
                    rejected_units += int(fulfillment.line_qty[order_lines].sum())
                built = _daily_instance(
                    instance, order_day, remaining, stock, capacity, day
                )
                if built is None:
                    continue
                daily, lines, open_orders = built
                new_mask = order_day[open_orders] == day
        residual = np.maximum(
            1, order_day[open_orders] + quotes[open_orders] - day
        )
        daily = replace(
            daily,
            fulfillment=replace(
                daily.fulfillment, promise_days=residual.astype(np.int64)
            ),
        )
        before = stock.copy()
        allocation = capacity_aware_allocation(
            daily,
            service_time=service_time,
            milp_time=milp_time,
            workers=workers,
            pick_deadlines=ROLLING_DEADLINES,
            order_priority=(
                None
                if allocation_priority is None
                else np.asarray(allocation_priority, dtype=float)[open_orders]
            ),
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
        promise_days=quotes,
        accepted=accepted,
        rejected_units=rejected_units,
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
    segments: Optional[Dict[str, np.ndarray]] = None,
) -> pd.DataFrame:
    """Run one seed through every day and score absolute delivery dates.

    ``segments`` optionally maps a label to an order mask. Each label adds
    ``{label}_accepted_otif_rate`` and ``{label}_all_otif_rate``, which is how
    Week 30 checks whether a high-value promise upgrade helps the target
    segment or just moves lateness to everyone else.
    """
    if cell.policy == "none":
        raise ValueError("Week 20 只比较发车策略，不接受 none")
    fully = _fully_allocated(base, flow.remaining)
    deadline = order_day + flow.promise_days
    static_deadline = _deadline(base, order_day)
    accepted = flow.accepted
    if accepted.size != base.n_orders:
        accepted = np.ones(base.n_orders, dtype=bool)
    accepted_lines = accepted[base.fulfillment.line_order]
    accepted_units = int(base.fulfillment.line_qty[accepted_lines].sum())
    accepted_backlog = int(flow.remaining[accepted_lines].sum())
    rows: List[Dict[str, Any]] = []
    demand = max(1, flow.demand_units)
    segment_masks: Dict[str, np.ndarray] = {}
    for name, mask in (segments or {}).items():
        array = np.asarray(mask, dtype=bool)
        if array.shape != (base.n_orders,):
            raise ValueError(f"segment {name} 必须与订单数一致")
        segment_masks[str(name)] = array
    for seed in seeds:
        delivered: Dict[int, int] = {}
        unshipped: set = set()
        door_used = 0.0
        door_capacity = 0.0
        door_blocked = 0
        departures = 0
        dispatch_cost = 0.0
        holding_cost = 0.0
        shipped_tickets = 0
        roll_tickets = 0
        wait_minutes = 0.0
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
            door_used += float(outcome.play.door_minutes_used)
            door_capacity += float(outcome.play.door_capacity_minutes)
            door_blocked += int(outcome.play.door_blocked)
            metrics = outcome.metrics
            departures += int(metrics.get("departures", 0))
            dispatch_cost += float(metrics.get("dispatch_cost", 0.0))
            holding_cost += float(metrics.get("holding_cost", 0.0))
            tickets = int(len(outcome.play.tickets))
            shipped_tickets += tickets
            roll_tickets += int(metrics.get("roll_tickets", 0.0))
            wait_minutes += float(metrics.get("mean_wait_minutes", 0.0)) * tickets
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
        static_on_time = np.zeros(base.n_orders, dtype=bool)
        delivered_days: List[int] = []
        for order in range(base.n_orders):
            if not fully[order] or order in unshipped or order not in delivered:
                continue
            day = int(delivered[order])
            delivered_days.append(day)
            if day <= int(deadline[order]):
                on_time[order] = True
            if day <= int(static_deadline[order]):
                static_on_time[order] = True
        accepted_delivered = [
            int(delivered[order])
            for order in np.flatnonzero(accepted)
            if order in delivered and fully[order] and order not in unshipped
        ]
        accepted_on_time = on_time[accepted]
        accepted_static = static_on_time[accepted]
        accepted_orders = int(accepted.sum())
        accepted_quotes = flow.promise_days[accepted]
        late_orders = int(base.n_orders - on_time.sum())
        row = {
            "policy": flow.policy,
            "seed": int(seed),
            "e2e_otif_rate": float(on_time.mean()) if base.n_orders else 0.0,
            "static_sla_otif_rate": (
                float(static_on_time.mean()) if base.n_orders else 0.0
            ),
            "accepted_otif_rate": (
                float(accepted_on_time.mean()) if accepted_orders else 0.0
            ),
            "accepted_static_sla_otif_rate": (
                float(accepted_static.mean()) if accepted_orders else 0.0
            ),
            "accepted_orders": accepted_orders,
            "lost_orders": int(base.n_orders - accepted_orders),
            "accepted_units": accepted_units,
            "lost_units": int(flow.rejected_units),
            "accepted_rate": (
                float(accepted.mean()) if base.n_orders else 0.0
            ),
            "accepted_fill_rate": (
                1.0 - accepted_backlog / accepted_units
                if accepted_units
                else 0.0
            ),
            "accepted_backlog_units": accepted_backlog,
            "accepted_late_orders": int(accepted_orders - accepted_on_time.sum()),
            "avg_promise_days": (
                float(flow.promise_days.mean()) if base.n_orders else 0.0
            ),
            "accepted_avg_promise_days": (
                float(accepted_quotes.mean()) if accepted_orders else 0.0
            ),
            "fast_share": (
                float((flow.promise_days == 2).mean()) if base.n_orders else 0.0
            ),
            "accepted_fast_share": (
                float((accepted_quotes == 2).mean()) if accepted_orders else 0.0
            ),
            "fill_rate": float(
                1.0 - (flow.remaining.sum() + flow.rejected_units) / demand
            ),
            "late_orders": int(late_orders),
            "backlog_units": int(flow.remaining.sum()),
            "avg_delivery_day": (
                float(np.mean(accepted_delivered)) if accepted_delivered else 0.0
            ),
            "replenished_units": int(flow.replenished_units),
            "departures": departures,
            "dispatch_cost": dispatch_cost,
            "holding_cost": holding_cost,
            "dock_cost": dispatch_cost + holding_cost,
            "shipped_tickets": shipped_tickets,
            "orders_per_departure": (
                shipped_tickets / departures if departures else 0.0
            ),
            "load_factor": (
                shipped_tickets / (departures * cell.capacity)
                if departures and cell.capacity
                else 0.0
            ),
            "roll_rate": (
                roll_tickets / shipped_tickets if shipped_tickets else 0.0
            ),
            "mean_wait_minutes": (
                wait_minutes / shipped_tickets if shipped_tickets else 0.0
            ),
            "orders": int(base.n_orders),
            "door_minutes_used": door_used,
            "door_capacity_minutes": door_capacity,
            "door_utilization": (
                door_used / door_capacity if door_capacity > 0 else 0.0
            ),
            "door_blocked": int(door_blocked),
        }
        for name, mask in segment_masks.items():
            selected = mask & accepted
            row[f"{name}_accepted_orders"] = int(selected.sum())
            row[f"{name}_accepted_otif_rate"] = (
                float(on_time[selected].mean()) if selected.any() else 0.0
            )
            row[f"{name}_all_otif_rate"] = (
                float(on_time[mask].mean()) if mask.any() else 0.0
            )
        for day in range(FLOW_DAYS):
            mask = np.asarray(order_day) == day
            if mask.any():
                row[f"otif_day_{day}"] = float(on_time[mask].mean())
            else:
                row[f"otif_day_{day}"] = float("nan")
            accepted_mask = mask & accepted
            if accepted_mask.any():
                row[f"accepted_otif_day_{day}"] = float(
                    on_time[accepted_mask].mean()
                )
            else:
                row[f"accepted_otif_day_{day}"] = float("nan")
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
        metrics = outcome.metrics
        tickets = int(len(outcome.play.tickets))
        departures = int(metrics.get("departures", 0))
        rows.append(
            {
                "policy": "single_week",
                "seed": int(seed),
                "e2e_otif_rate": float(outcome.order_dock_ok.mean()),
                "static_sla_otif_rate": float(outcome.order_dock_ok.mean()),
                "accepted_otif_rate": float(outcome.order_dock_ok.mean()),
                "accepted_static_sla_otif_rate": float(
                    outcome.order_dock_ok.mean()
                ),
                "accepted_orders": int(instance.n_orders),
                "lost_orders": 0,
                "accepted_units": demand,
                "lost_units": 0,
                "accepted_rate": 1.0,
                "accepted_fill_rate": float(allocation.unit_fill_rate),
                "accepted_backlog_units": int(allocation.unmet.sum()),
                "accepted_late_orders": int((~outcome.order_dock_ok).sum()),
                "avg_promise_days": float(
                    instance.fulfillment.promise_days.mean()
                ),
                "accepted_avg_promise_days": float(
                    instance.fulfillment.promise_days.mean()
                ),
                "fast_share": float(
                    (instance.fulfillment.promise_days == 2).mean()
                ),
                "accepted_fast_share": float(
                    (instance.fulfillment.promise_days == 2).mean()
                ),
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
                "departures": departures,
                "dispatch_cost": float(metrics.get("dispatch_cost", 0.0)),
                "holding_cost": float(metrics.get("holding_cost", 0.0)),
                "dock_cost": float(metrics.get("dock_cost", 0.0)),
                "shipped_tickets": tickets,
                "orders_per_departure": (
                    tickets / departures if departures else 0.0
                ),
                "load_factor": (
                    tickets / (departures * cell.capacity)
                    if departures and cell.capacity
                    else 0.0
                ),
                "roll_rate": float(metrics.get("roll_rate", 0.0)),
                "mean_wait_minutes": float(
                    metrics.get("mean_wait_minutes", 0.0)
                ),
                "orders": int(instance.n_orders),
                "door_minutes_used": float(outcome.play.door_minutes_used),
                "door_capacity_minutes": float(outcome.play.door_capacity_minutes),
                "door_utilization": (
                    float(outcome.play.door_minutes_used)
                    / float(outcome.play.door_capacity_minutes)
                    if outcome.play.door_capacity_minutes > 0
                    else 0.0
                ),
                "door_blocked": int(outcome.play.door_blocked),
                "otif_day_0": float(outcome.order_dock_ok.mean()),
                "accepted_otif_day_0": float(outcome.order_dock_ok.mean()),
                **{
                    f"otif_day_{day}": float("nan")
                    for day in range(1, FLOW_DAYS)
                },
                **{
                    f"accepted_otif_day_{day}": float("nan")
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
                "static_sla_otif_mean": (
                    float(group["static_sla_otif_rate"].mean())
                    if "static_sla_otif_rate" in group
                    else float(otif.mean())
                ),
                "avg_promise_days": (
                    float(group["avg_promise_days"].mean())
                    if "avg_promise_days" in group
                    else 0.0
                ),
                "fast_share": (
                    float(group["fast_share"].mean())
                    if "fast_share" in group
                    else 0.0
                ),
                "fill_mean": float(group["fill_rate"].mean()),
                "accepted_rate": (
                    float(group["accepted_rate"].mean())
                    if "accepted_rate" in group
                    else 1.0
                ),
                "accepted_otif_mean": (
                    float(group["accepted_otif_rate"].mean())
                    if "accepted_otif_rate" in group
                    else float(otif.mean())
                ),
                "accepted_static_sla_mean": (
                    float(group["accepted_static_sla_otif_rate"].mean())
                    if "accepted_static_sla_otif_rate" in group
                    else float(group["static_sla_otif_rate"].mean())
                    if "static_sla_otif_rate" in group
                    else float(otif.mean())
                ),
                "accepted_fill_mean": (
                    float(group["accepted_fill_rate"].mean())
                    if "accepted_fill_rate" in group
                    else float(group["fill_rate"].mean())
                ),
                "accepted_orders_mean": (
                    float(group["accepted_orders"].mean())
                    if "accepted_orders" in group
                    else float(group["orders"].mean())
                    if "orders" in group
                    else 0.0
                ),
                "lost_orders_mean": (
                    float(group["lost_orders"].mean())
                    if "lost_orders" in group
                    else 0.0
                ),
                "accepted_units": (
                    int(group["accepted_units"].iloc[0])
                    if "accepted_units" in group
                    else 0
                ),
                "lost_units": (
                    int(group["lost_units"].iloc[0])
                    if "lost_units" in group
                    else 0
                ),
                "accepted_backlog_units": (
                    int(group["accepted_backlog_units"].iloc[0])
                    if "accepted_backlog_units" in group
                    else int(group["backlog_units"].iloc[0])
                ),
                "accepted_late_orders_mean": (
                    float(group["accepted_late_orders"].mean())
                    if "accepted_late_orders" in group
                    else float(group["late_orders"].mean())
                ),
                "accepted_avg_promise_days": (
                    float(group["accepted_avg_promise_days"].mean())
                    if "accepted_avg_promise_days" in group
                    else float(group["avg_promise_days"].mean())
                    if "avg_promise_days" in group
                    else 0.0
                ),
                "accepted_fast_share": (
                    float(group["accepted_fast_share"].mean())
                    if "accepted_fast_share" in group
                    else float(group["fast_share"].mean())
                    if "fast_share" in group
                    else 0.0
                ),
                "late_orders_mean": float(group["late_orders"].mean()),
                "backlog_units": int(group["backlog_units"].iloc[0]),
                "avg_delivery_day": float(group["avg_delivery_day"].mean()),
                "replenished_units": int(group["replenished_units"].iloc[0]),
                "door_utilization": (
                    float(group["door_utilization"].mean())
                    if "door_utilization" in group
                    else 0.0
                ),
                "door_blocked_mean": (
                    float(group["door_blocked"].mean())
                    if "door_blocked" in group
                    else 0.0
                ),
                **{
                    f"otif_day_{day}": float(group[f"otif_day_{day}"].mean())
                    for day in range(FLOW_DAYS)
                    if f"otif_day_{day}" in group
                },
                **{
                    f"accepted_otif_day_{day}": float(
                        group[f"accepted_otif_day_{day}"].mean()
                    )
                    for day in range(FLOW_DAYS)
                    if f"accepted_otif_day_{day}" in group
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
