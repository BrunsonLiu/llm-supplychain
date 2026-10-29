"""Outbound dispatch: pick completion -> carrier cutoff -> line-haul departure.

Weeks 9-15 score the chain at the pick cutoff. A warehouse can be "on time"
and still miss the customer promise when the parcel misses the line-haul
departure, so this module adds one declared outbound layer on top of the same
allocation, arrival curves and pick simulation:

* every DC has line-haul departures at 13:00 and 19:00 (configurable);
* a departure closes ``load_minutes`` before it leaves, and a ticket that
  misses the cutoff rolls to the next departure;
* tickets sharing a DC and destination country form a lane that can be held
  to consolidate a load, as long as the hold does not break the promise.

Three policies are compared:

* ``immediate``: release every available ticket at the next departure;
* ``hold``: wait for ``min_load`` tickets or the end of the dispatch day;
* ``promise``: wait for ``min_load``, the promise deadline, or ``max_hold``.

The promise deadline per ticket is ``promise_days - transit_days`` dispatch
days, so a 2-day promise with 2-day transit must leave on day 0. The pick
cutoffs (12:00/16:00/18:00) stay in place as the warehouse release policy; this
layer only changes how the finished parcels leave the dock.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult

from .arrival import EmpiricalArrivals
from .instances import E2EInstance, EPS, rebuild_arrivals
from .pipeline import (
    DCTickets,
    E2EResult,
    allocation_order_status,
    pick_tickets,
    run_pick_layer,
)

DEFAULT_DEPARTURES: Tuple[float, ...] = (300.0, 660.0)  # 13:00 and 19:00
DEFAULT_LOAD_MINUTES = 30.0
DEFAULT_MIN_LOAD = 6
DEFAULT_CAPACITY = 300
DEFAULT_MAX_DAYS = 3
DEFAULT_MAX_HOLD_MINUTES = 1440.0
DEFAULT_DISPATCH_COST = 220.0
DEFAULT_HOLDING_COST = 0.15
DEFAULT_DOORS_PER_DC = 0
DEFAULT_DOOR_WINDOW_MINUTES = 600.0
DEFAULT_DOCK_LOAD_MINUTES = 75.0
DEFAULT_DOCK_LOAD_PER_TICKET = 0.5
DISPATCH_POLICIES = ("none", "immediate", "hold", "promise")

DISPATCH_METRICS: Dict[str, str] = {
    "dock_otif_rate": "交付 OTIF（含发车）",
    "pick_otif_rate": "拣选截单 OTIF（对照口径）",
    "dock_delta_orders": "交付 − 拣选截单（单）",
    "departures": "发车次数",
    "departures_per_dc": "每 DC 发车次数",
    "orders_per_departure": "每车票据数",
    "units_per_departure": "每车件数",
    "load_factor": "装载率（对 300 单上限）",
    "mean_wait_minutes": "平均等车 (min)",
    "p90_wait_minutes": "P90 等车 (min)",
    "roll_tickets": "次日及以后发车票据",
    "roll_rate": "滚存票据占比",
    "dispatch_cost": "发车成本 (€)",
    "holding_cost": "等待成本 (€)",
    "dock_cost": "月台总成本 (€)",
    "unshipped_tickets": "未发出票据",
}


def _is_positive(value: float) -> bool:
    return float(value) > 0.0


@dataclass(frozen=True)
class DispatchConfig:
    """Declared outbound timetable, consolidation rule and dock cost."""

    policy: str = "promise"
    departures: Tuple[float, ...] = DEFAULT_DEPARTURES
    load_minutes: float = DEFAULT_LOAD_MINUTES
    min_load: int = DEFAULT_MIN_LOAD
    capacity: int = DEFAULT_CAPACITY
    max_days: int = DEFAULT_MAX_DAYS
    max_hold_minutes: float = DEFAULT_MAX_HOLD_MINUTES
    dispatch_cost: float = DEFAULT_DISPATCH_COST
    holding_cost_per_order_hour: float = DEFAULT_HOLDING_COST
    doors_per_dc: int = DEFAULT_DOORS_PER_DC
    door_window_minutes: float = DEFAULT_DOOR_WINDOW_MINUTES
    dock_load_minutes: float = DEFAULT_DOCK_LOAD_MINUTES
    dock_load_per_ticket: float = DEFAULT_DOCK_LOAD_PER_TICKET
    hold_day: int = 0

    def __post_init__(self) -> None:
        if self.policy not in DISPATCH_POLICIES or self.policy == "none":
            raise ValueError(f"未知发车策略: {self.policy}")
        slots = tuple(float(x) for x in self.departures)
        if not slots:
            raise ValueError("发车时刻不能为空")
        if any(not 0.0 < x < 1440.0 for x in slots):
            raise ValueError("发车时刻必须在 0 到 1440 分钟内")
        if any(b <= a for a, b in zip(slots, slots[1:])):
            raise ValueError("发车时刻必须严格递增")
        if self.load_minutes < 0:
            raise ValueError("装车截止提前量不能为负")
        if int(self.min_load) < 1:
            raise ValueError("最小发车批量必须为正")
        if int(self.capacity) < 1:
            raise ValueError("每车容量必须为正")
        if int(self.max_days) < 0:
            raise ValueError("发车天数上限不能为负")
        if self.max_hold_minutes < 0:
            raise ValueError("最长等待时间不能为负")
        if self.dispatch_cost < 0 or self.holding_cost_per_order_hour < 0:
            raise ValueError("发车/等待成本不能为负")
        if int(self.doors_per_dc) < 0:
            raise ValueError("门位数量不能为负")
        if self.door_window_minutes <= 0:
            raise ValueError("门位可用窗口必须为正")
        if self.dock_load_minutes < 0 or self.dock_load_per_ticket < 0:
            raise ValueError("装车分钟不能为负")
        if not 0 <= int(self.hold_day) <= int(self.max_days):
            raise ValueError("hold_day 必须落在发车天数范围内")
        object.__setattr__(self, "departures", slots)

    @property
    def last_departure(self) -> float:
        return self.departures[-1]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy,
            "departures": list(self.departures),
            "load_minutes": float(self.load_minutes),
            "min_load": int(self.min_load),
            "capacity": int(self.capacity),
            "max_days": int(self.max_days),
            "max_hold_minutes": float(self.max_hold_minutes),
            "dispatch_cost": float(self.dispatch_cost),
            "holding_cost_per_order_hour": float(self.holding_cost_per_order_hour),
            "doors_per_dc": int(self.doors_per_dc),
            "door_window_minutes": float(self.door_window_minutes),
            "dock_load_minutes": float(self.dock_load_minutes),
            "dock_load_per_ticket": float(self.dock_load_per_ticket),
            "hold_day": int(self.hold_day),
        }


@dataclass(frozen=True)
class DispatchCell:
    """One dock cell: dispatch policy plus the pick knobs it runs under."""

    key: str
    label: str
    policy: str = "promise"
    min_load: int = DEFAULT_MIN_LOAD
    departures: Tuple[float, ...] = DEFAULT_DEPARTURES
    capacity: int = DEFAULT_CAPACITY
    duration_noise: float = 0.0
    pickers_per_dc: Optional[int] = None
    load_minutes: float = DEFAULT_LOAD_MINUTES
    max_days: int = DEFAULT_MAX_DAYS
    max_hold_minutes: float = DEFAULT_MAX_HOLD_MINUTES
    dispatch_cost: float = DEFAULT_DISPATCH_COST
    holding_cost_per_order_hour: float = DEFAULT_HOLDING_COST
    doors_per_dc: int = DEFAULT_DOORS_PER_DC
    door_window_minutes: float = DEFAULT_DOOR_WINDOW_MINUTES
    dock_load_minutes: float = DEFAULT_DOCK_LOAD_MINUTES
    dock_load_per_ticket: float = DEFAULT_DOCK_LOAD_PER_TICKET

    def __post_init__(self) -> None:
        if self.policy not in DISPATCH_POLICIES:
            raise ValueError(f"未知发车策略: {self.policy}")
        if int(self.min_load) < 1:
            raise ValueError("最小发车批量必须为正")
        if int(self.capacity) < 1:
            raise ValueError("每车容量必须为正")
        if self.duration_noise < 0:
            raise ValueError("拣选时长噪声标准差不能为负")
        if self.pickers_per_dc is not None and self.pickers_per_dc < 1:
            raise ValueError("每 DC 拣货员数量必须为正")
        if self.load_minutes < 0:
            raise ValueError("装车截止提前量不能为负")
        if int(self.max_days) < 0:
            raise ValueError("发车天数上限不能为负")
        if self.max_hold_minutes < 0:
            raise ValueError("最长等待时间不能为负")
        if self.dispatch_cost < 0 or self.holding_cost_per_order_hour < 0:
            raise ValueError("发车/等待成本不能为负")
        if int(self.doors_per_dc) < 0:
            raise ValueError("门位数量不能为负")
        if self.door_window_minutes <= 0:
            raise ValueError("门位可用窗口必须为正")
        if self.dock_load_minutes < 0 or self.dock_load_per_ticket < 0:
            raise ValueError("装车分钟不能为负")

    def config(self) -> DispatchConfig:
        return DispatchConfig(
            policy=self.policy if self.policy != "none" else "promise",
            departures=self.departures,
            load_minutes=self.load_minutes,
            max_days=self.max_days,
            min_load=self.min_load,
            capacity=self.capacity,
            max_hold_minutes=self.max_hold_minutes,
            dispatch_cost=self.dispatch_cost,
            holding_cost_per_order_hour=self.holding_cost_per_order_hour,
            doors_per_dc=self.doors_per_dc,
            door_window_minutes=self.door_window_minutes,
            dock_load_minutes=self.dock_load_minutes,
            dock_load_per_ticket=self.dock_load_per_ticket,
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "policy": self.policy,
            "min_load": int(self.min_load),
            "departures": list(self.departures),
            "capacity": int(self.capacity),
            "duration_noise": float(self.duration_noise),
            "pickers_per_dc": self.pickers_per_dc,
            "load_minutes": float(self.load_minutes),
            "max_days": int(self.max_days),
            "max_hold_minutes": float(self.max_hold_minutes),
            "dispatch_cost": float(self.dispatch_cost),
            "holding_cost_per_order_hour": float(self.holding_cost_per_order_hour),
            "doors_per_dc": int(self.doors_per_dc),
            "door_window_minutes": float(self.door_window_minutes),
            "dock_load_minutes": float(self.dock_load_minutes),
            "dock_load_per_ticket": float(self.dock_load_per_ticket),
        }


@dataclass(frozen=True)
class DispatchTicket:
    """One pick ticket (order x DC) with its promise deadline in days."""

    ticket: str
    dc: str
    order: int
    lane: str
    pick_end: float
    transit_days: int
    promise_days: int
    units: int = 1
    deadline_day: int = 0

    def __post_init__(self) -> None:
        if self.pick_end < 0:
            raise ValueError("拣选完成时间不能为负")
        if self.transit_days < 0 or self.promise_days < 0:
            raise ValueError("转运天数与承诺天数不能为负")
        if self.deadline_day < 0:
            raise ValueError("承诺截止发车日不能为负")
        if self.units < 0:
            raise ValueError("票据件数不能为负")


@dataclass(frozen=True)
class Departure:
    index: int
    dc: str
    lane: str
    day: int
    minute: float
    orders: int
    tickets: int
    units: int
    mean_wait_minutes: float
    max_wait_minutes: float

    @property
    def clock_minute(self) -> float:
        return float(self.day) * 1440.0 + float(self.minute)


@dataclass(frozen=True)
class ScheduledTicket:
    ticket: str
    dc: str
    order: int
    lane: str
    pick_end: float
    transit_days: int
    promise_days: int
    units: int
    deadline_day: int
    ship_day: int
    ship_minute: float
    wait_minutes: float
    departure_index: int


@dataclass
class DispatchPlay:
    config: DispatchConfig
    departures: List[Departure]
    tickets: List[ScheduledTicket]
    unshipped: List[str]
    door_minutes_used: float = 0.0
    door_capacity_minutes: float = 0.0
    door_blocked: int = 0


@dataclass
class DispatchOutcome:
    play: DispatchPlay
    delivered_day: Dict[int, int]
    unshipped_orders: List[int]
    order_promise_ok: np.ndarray
    order_dock_ok: np.ndarray
    metrics: Dict[str, float]


def departure_slots(config: DispatchConfig) -> List[Tuple[int, float, float]]:
    """(day, departure minute, cutoff minute) for every declared departure."""
    if not isinstance(config, DispatchConfig):
        raise TypeError("config 必须是 DispatchConfig")
    slots: List[Tuple[int, float, float]] = []
    for day in range(int(config.max_days) + 1):
        for minute in config.departures:
            slots.append((day, float(minute), day * 1440.0 + minute - config.load_minutes))
    return slots


def promise_deadline(
    promise_days: int, transit_days: int, max_days: int = DEFAULT_MAX_DAYS
) -> int:
    """Latest dispatch day that still lands inside the promise."""
    if promise_days < 0 or transit_days < 0:
        raise ValueError("承诺天数与转运天数不能为负")
    if max_days < 0:
        raise ValueError("发车天数上限不能为负")
    return int(max(0, min(int(max_days), int(promise_days) - int(transit_days))))


def _should_dispatch(
    config: DispatchConfig,
    group: Sequence[DispatchTicket],
    day: int,
    last_of_day: bool,
    slot_minute: float,
) -> bool:
    if config.policy == "immediate":
        return True
    if len(group) >= int(config.min_load):
        return True
    if (
        config.max_hold_minutes > 0
        and slot_minute - min(t.pick_end for t in group)
        >= config.max_hold_minutes - EPS
    ):
        return True
    if config.policy == "hold":
        return day > config.hold_day or (day == config.hold_day and last_of_day)
    deadline = min(t.deadline_day for t in group)
    if day > deadline:
        return True
    return day == deadline and last_of_day


def dispatch_tickets(
    records: Sequence[DispatchTicket],
    config: DispatchConfig = DispatchConfig(),
    priority_orders: Optional[Sequence[int]] = None,
) -> DispatchPlay:
    """Run the dock simulation over already-picked tickets.

    ``priority_orders`` is a real dispatch priority: within a lane, tickets of
    those orders are loaded before lower-priority tickets (then EDF). It can
    move a high-value parcel onto an earlier departure, but it can also push a
    low-value parcel past its promise; it does not add capacity.
    """
    if not isinstance(config, DispatchConfig):
        raise TypeError("config 必须是 DispatchConfig")
    priority = {
        int(order)
        for order in ([] if priority_orders is None else priority_orders)
    }
    pending = list(records)
    if not pending:
        return DispatchPlay(config=config, departures=[], tickets=[], unshipped=[])

    departures: List[Departure] = []
    scheduled: List[ScheduledTicket] = []
    door_used: Dict[Tuple[str, int], float] = {}
    door_blocked = 0
    for day, minute, cutoff in departure_slots(config):
        available = [t for t in pending if t.pick_end <= cutoff + EPS]
        if not available:
            continue
        slot_minute = day * 1440.0 + minute
        by_lane: Dict[Tuple[str, str], List[DispatchTicket]] = {}
        for ticket in available:
            by_lane.setdefault((ticket.dc, ticket.lane), []).append(ticket)
        removed: set = set()
        last_of_day = abs(minute - config.last_departure) <= EPS
        for (dc, lane), group in by_lane.items():
            ordered = sorted(
                group,
                key=lambda t: (
                    0 if t.order in priority else 1,
                    t.deadline_day,
                    t.pick_end,
                    t.ticket,
                ),
            )
            if not _should_dispatch(config, ordered, day, last_of_day, slot_minute):
                continue
            batch = ordered[: int(config.capacity)]
            load_minutes = config.dock_load_minutes + config.dock_load_per_ticket * len(
                batch
            )
            if config.doors_per_dc > 0:
                used = door_used.get((dc, day), 0.0)
                capacity = config.doors_per_dc * config.door_window_minutes
                if used + load_minutes > capacity + EPS:
                    door_blocked += 1
                    continue
                door_used[(dc, day)] = used + load_minutes
            waits = [slot_minute - ticket.pick_end for ticket in batch]
            index = len(departures)
            departures.append(
                Departure(
                    index=index,
                    dc=dc,
                    lane=lane,
                    day=day,
                    minute=minute,
                    orders=len({ticket.order for ticket in batch}),
                    tickets=len(batch),
                    units=int(sum(ticket.units for ticket in batch)),
                    mean_wait_minutes=float(np.mean(waits)),
                    max_wait_minutes=float(np.max(waits)),
                )
            )
            for ticket, wait in zip(batch, waits):
                scheduled.append(
                    ScheduledTicket(
                        ticket=ticket.ticket,
                        dc=ticket.dc,
                        order=ticket.order,
                        lane=ticket.lane,
                        pick_end=ticket.pick_end,
                        transit_days=ticket.transit_days,
                        promise_days=ticket.promise_days,
                        units=ticket.units,
                        deadline_day=ticket.deadline_day,
                        ship_day=day,
                        ship_minute=minute,
                        wait_minutes=float(wait),
                        departure_index=index,
                    )
                )
                removed.add(ticket.ticket)
        if removed:
            pending = [ticket for ticket in pending if ticket.ticket not in removed]
        if not pending:
            break

    active_days = max((row.day for row in departures), default=0) + 1
    n_dcs = len({ticket.dc for ticket in records})
    door_capacity = (
        config.doors_per_dc
        * config.door_window_minutes
        * n_dcs
        * active_days
    )
    return DispatchPlay(
        config=config,
        departures=departures,
        tickets=scheduled,
        unshipped=[ticket.ticket for ticket in pending],
        door_minutes_used=float(sum(door_used.values())),
        door_capacity_minutes=float(door_capacity),
        door_blocked=int(door_blocked),
    )


def ticket_records(
    instance: E2EInstance,
    pick_result: E2EResult,
    tickets: Sequence[DCTickets],
) -> List[DispatchTicket]:
    """Join pick completion times with order promises and DC transit days."""
    fulfillment = instance.fulfillment
    dc_index = {name: index for index, name in enumerate(fulfillment.dc_names)}
    groups = {group.dc: group for group in tickets}
    records: List[DispatchTicket] = []
    for dc_row in pick_result.dc:
        if dc_row.dc not in groups:
            raise ValueError(f"缺少 DC 票据: {dc_row.dc}")
        group = groups[dc_row.dc]
        ends: Dict[str, float] = {}
        for job, end in zip(dc_row.schedule.jobs, dc_row.schedule.ends):
            for ticket in job.invoices:
                ends[str(ticket)] = float(end)
        units = group.frame.groupby("invoice")["quantity"].sum().to_dict()
        for ticket, order in group.order_index.items():
            if ticket not in ends:
                raise ValueError(f"票据缺少完工时间: {ticket}")
            promise = int(fulfillment.promise_days[order])
            transit = int(fulfillment.transit_days[dc_index[dc_row.dc], order])
            records.append(
                DispatchTicket(
                    ticket=str(ticket),
                    dc=dc_row.dc,
                    order=int(order),
                    lane=str(fulfillment.destinations[order]),
                    pick_end=float(ends[ticket]),
                    transit_days=transit,
                    promise_days=promise,
                    units=int(units.get(ticket, 0)),
                    deadline_day=promise_deadline(promise, transit),
                )
            )
    return records


def _dispatch_metrics(
    instance: E2EInstance,
    pick_result: E2EResult,
    play: DispatchPlay,
    order_dock_ok: np.ndarray,
) -> Dict[str, float]:
    orders = int(instance.n_orders)
    scheduled = play.tickets
    departures = len(play.departures)
    waits = np.array([row.wait_minutes for row in scheduled], dtype=float)
    dock_ok_orders = int(order_dock_ok.sum())
    pick_ok_orders = int(pick_result.metrics.get("e2e_otif_orders", 0))
    dispatch_cost = departures * float(play.config.dispatch_cost)
    holding_cost = (
        float(waits.sum()) / 60.0 * float(play.config.holding_cost_per_order_hour)
        if waits.size
        else 0.0
    )
    tickets_per_departure = len(scheduled) / departures if departures else 0.0
    units = sum(row.units for row in scheduled)
    return {
        "dock_otif_orders": float(dock_ok_orders),
        "dock_otif_rate": dock_ok_orders / orders if orders else 0.0,
        "pick_otif_rate": float(pick_result.metrics.get("e2e_otif_rate", 0.0)),
        "dock_delta_orders": float(dock_ok_orders - pick_ok_orders),
        "departures": float(departures),
        "departures_per_dc": departures / instance.fulfillment.n_dcs
        if instance.fulfillment.n_dcs
        else 0.0,
        "orders_per_departure": tickets_per_departure,
        "units_per_departure": units / departures if departures else 0.0,
        "load_factor": tickets_per_departure / float(play.config.capacity)
        if play.config.capacity
        else 0.0,
        "mean_wait_minutes": float(waits.mean()) if waits.size else 0.0,
        "p90_wait_minutes": float(np.percentile(waits, 90)) if waits.size else 0.0,
        "roll_tickets": float(sum(1 for row in scheduled if row.ship_day >= 1)),
        "roll_rate": (
            sum(1 for row in scheduled if row.ship_day >= 1) / len(scheduled)
            if scheduled
            else 0.0
        ),
        "dispatch_cost": float(dispatch_cost),
        "holding_cost": float(holding_cost),
        "dock_cost": float(dispatch_cost + holding_cost),
        "unshipped_tickets": float(len(play.unshipped)),
        "door_minutes_used": float(play.door_minutes_used),
        "door_capacity_minutes": float(play.door_capacity_minutes),
        "door_utilization": (
            float(play.door_minutes_used / play.door_capacity_minutes)
            if play.door_capacity_minutes
            else 0.0
        ),
        "door_blocked": float(play.door_blocked),
        "load_minutes_per_departure": (
            float(play.door_minutes_used / departures)
            if departures and play.config.doors_per_dc > 0
            else 0.0
        ),
    }


def simulate_dispatch(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    pick_result: E2EResult,
    tickets: Sequence[DCTickets],
    config: DispatchConfig = DispatchConfig(),
    priority_orders: Optional[Sequence[int]] = None,
) -> DispatchOutcome:
    """Add the line-haul layer and re-score every order at delivery."""
    records = ticket_records(instance, pick_result, tickets)
    play = dispatch_tickets(records, config, priority_orders=priority_orders)
    delivered: Dict[int, int] = {}
    for row in play.tickets:
        day = int(row.ship_day) + int(row.transit_days)
        delivered[int(row.order)] = max(delivered.get(int(row.order), -1), day)
    unshipped_orders = sorted(
        {
            int(ticket.order)
            for ticket in records
            if ticket.ticket in set(play.unshipped)
        }
    )
    status = allocation_order_status(instance, allocation)
    promise_ok = np.zeros(instance.n_orders, dtype=bool)
    blocked = set(unshipped_orders)
    for order, day in delivered.items():
        if order in blocked:
            continue
        promise_ok[order] = day <= int(instance.fulfillment.promise_days[order])
    dock_ok = status["alloc_ok"] & promise_ok
    metrics = _dispatch_metrics(instance, pick_result, play, dock_ok)
    return DispatchOutcome(
        play=play,
        delivered_day=delivered,
        unshipped_orders=unshipped_orders,
        order_promise_ok=promise_ok,
        order_dock_ok=dock_ok,
        metrics=metrics,
    )


def _control_metrics(pick_result: E2EResult) -> Dict[str, float]:
    return {
        "dock_otif_orders": float(pick_result.metrics.get("e2e_otif_orders", 0)),
        "dock_otif_rate": float(pick_result.metrics.get("e2e_otif_rate", 0.0)),
        "pick_otif_rate": float(pick_result.metrics.get("e2e_otif_rate", 0.0)),
        "dock_delta_orders": 0.0,
        "departures": 0.0,
        "departures_per_dc": 0.0,
        "orders_per_departure": 0.0,
        "units_per_departure": 0.0,
        "load_factor": 0.0,
        "mean_wait_minutes": 0.0,
        "p90_wait_minutes": 0.0,
        "roll_tickets": 0.0,
        "roll_rate": 0.0,
        "dispatch_cost": 0.0,
        "holding_cost": 0.0,
        "dock_cost": 0.0,
        "unshipped_tickets": 0.0,
        "door_minutes_used": 0.0,
        "door_capacity_minutes": 0.0,
        "door_utilization": 0.0,
        "door_blocked": 0.0,
        "load_minutes_per_departure": 0.0,
    }


def run_dispatch_cell(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    cell: DispatchCell,
    seed: int,
    arrivals: EmpiricalArrivals,
    scenario: str = "milp_load",
    keep_cutoffs: bool = False,
    priority_orders: Optional[Sequence[int]] = None,
) -> Tuple[Dict[str, Any], Optional[DispatchOutcome]]:
    """Run one cell for one seed and return a tidy row plus the dock outcome."""
    shifted = rebuild_arrivals(
        instance,
        int(seed),
        arrival_curve=arrivals.curve_for(int(seed)),
        keep_cutoffs=keep_cutoffs,
    )
    pick_result = run_pick_layer(
        shifted,
        allocation,
        scenario=scenario,
        policy="edf",
        pickers_per_dc=cell.pickers_per_dc,
        duration_noise=cell.duration_noise or None,
        noise_seed=int(seed),
        name=f"{scenario} · {cell.label}",
    )
    if cell.policy == "none":
        metrics = _control_metrics(pick_result)
        outcome = None
    else:
        outcome = simulate_dispatch(
            shifted,
            allocation,
            pick_result,
            pick_tickets(shifted, allocation),
            cell.config(),
            priority_orders=priority_orders,
        )
        metrics = outcome.metrics
    row: Dict[str, Any] = {
        "scenario": scenario,
        "cell": cell.key,
        "cell_label": cell.label,
        "policy": cell.policy,
        "min_load": int(cell.min_load),
        "profile": "逐周经验曲线",
        "duration_noise": float(cell.duration_noise),
        "pickers_per_dc": cell.pickers_per_dc,
        "seed": int(seed),
        **pick_result.metrics,
        **metrics,
    }
    return row, outcome


def run_dispatch_monte_carlo(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    cells: Sequence[DispatchCell],
    seeds: Sequence[int],
    arrivals: EmpiricalArrivals,
    scenario: str = "milp_load",
) -> pd.DataFrame:
    """Replay every cell on shared seeds, reusing pick work across cells."""
    if not cells:
        raise ValueError("至少需要一个发车回放格")
    if not seeds:
        raise ValueError("随机种子列表不能为空")
    rows: List[Dict[str, Any]] = []
    shifted_cache: Dict[int, E2EInstance] = {}
    pick_cache: Dict[Tuple[int, Optional[int], float], E2EResult] = {}
    ticket_cache: Dict[Tuple[int, Optional[int], float], List[DCTickets]] = {}
    for seed in seeds:
        seed = int(seed)
        if seed not in shifted_cache:
            shifted_cache[seed] = rebuild_arrivals(
                instance, seed, arrival_curve=arrivals.curve_for(seed)
            )
        shifted = shifted_cache[seed]
        for cell in cells:
            key = (seed, cell.pickers_per_dc, float(cell.duration_noise))
            if key not in pick_cache:
                pick_cache[key] = run_pick_layer(
                    shifted,
                    allocation,
                    scenario=scenario,
                    policy="edf",
                    pickers_per_dc=cell.pickers_per_dc,
                    duration_noise=cell.duration_noise or None,
                    noise_seed=seed,
                    name=f"{scenario} · {cell.key}",
                )
                ticket_cache[key] = pick_tickets(shifted, allocation)
            pick_result = pick_cache[key]
            if cell.policy == "none":
                metrics = _control_metrics(pick_result)
            else:
                metrics = simulate_dispatch(
                    shifted,
                    allocation,
                    pick_result,
                    ticket_cache[key],
                    cell.config(),
                ).metrics
            rows.append(
                {
                    "scenario": scenario,
                    "cell": cell.key,
                    "cell_label": cell.label,
                    "policy": cell.policy,
                    "min_load": int(cell.min_load),
                    "profile": "逐周经验曲线",
                    "duration_noise": float(cell.duration_noise),
                    "pickers_per_dc": cell.pickers_per_dc,
                    "seed": seed,
                    **pick_result.metrics,
                    **metrics,
                }
            )
    return pd.DataFrame(rows)


def lane_summary(outcome: DispatchOutcome) -> pd.DataFrame:
    """Per DC x destination lane load, wait and roll-up."""
    rows: List[Dict[str, Any]] = []
    by_lane: Dict[Tuple[str, str], List[ScheduledTicket]] = {}
    for ticket in outcome.play.tickets:
        by_lane.setdefault((ticket.dc, ticket.lane), []).append(ticket)
    for (dc, lane), tickets in sorted(by_lane.items()):
        departures = len(
            {
                ticket.departure_index
                for ticket in tickets
            }
        )
        waits = [ticket.wait_minutes for ticket in tickets]
        rows.append(
            {
                "dc": dc,
                "lane": lane,
                "tickets": len(tickets),
                "units": int(sum(ticket.units for ticket in tickets)),
                "departures": departures,
                "mean_wait_minutes": float(np.mean(waits)) if waits else 0.0,
                "roll_tickets": sum(1 for t in tickets if t.ship_day >= 1),
                "roll_rate": (
                    sum(1 for t in tickets if t.ship_day >= 1) / len(tickets)
                    if tickets
                    else 0.0
                ),
            }
        )
    return pd.DataFrame(rows)
