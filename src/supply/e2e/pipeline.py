"""Chain the allocation, wave picking and online release layers.

The pipeline takes a Week-5 allocation, turns every shipped line into a pick
ticket per DC (a split order becomes two tickets), then runs the Week-8
event-driven release per DC with that DC's own pickers. The end-to-end OTIF is
the intersection of three conditions:

1. the order is fully shipped (no unmet units);
2. every shipped line lands inside the customer promise (allocation lateness);
3. every pick ticket finishes before its pick cutoff (12:00/16:00/18:00).

The pick layer never re-optimises the allocation: it only reports whether the
plan is executable inside the warehouse.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult
from supply.wave import (
    DEFAULT_MIN_FILL,
    DEFAULT_WAIT_MINUTES,
    ArrivalPlan,
    PromisePlan,
    Schedule,
    build_wave_instance,
    dynamic_metrics,
    simulate_online,
)
from supply.wave.instances import LABOR_COST_PER_MINUTE

from .instances import E2EInstance, EPS, TIER_CUTOFFS

POLICY_LABELS = {
    "single": "在线按单释放",
    "edf": "在线 EDF 即时装满",
    "savings": "在线节省重批",
    "savings_wait": "在线节省 + 等待凑波",
}


@dataclass
class DCTickets:
    dc: str
    frame: pd.DataFrame  # invoice (ticket id), sku, quantity, order
    order_index: Dict[str, int]


@dataclass
class DCPickResult:
    dc: str
    tickets: int
    orders: int
    waves: int
    labor_minutes: float
    labor_per_ticket: float
    makespan: float
    idle_minutes: float
    on_time_tickets: int
    tardy_tickets: int
    tardiness_minutes: float
    max_tardiness: float
    fill: float
    schedule: Schedule

    def as_dict(self) -> Dict[str, object]:
        return {
            "dc": self.dc,
            "tickets": self.tickets,
            "orders": self.orders,
            "waves": self.waves,
            "labor_minutes": self.labor_minutes,
            "labor_per_ticket": self.labor_per_ticket,
            "makespan": self.makespan,
            "idle_minutes": self.idle_minutes,
            "on_time_tickets": self.on_time_tickets,
            "tardy_tickets": self.tardy_tickets,
            "tardiness_minutes": self.tardiness_minutes,
            "max_tardiness": self.max_tardiness,
            "fill": self.fill,
        }


@dataclass
class E2EResult:
    name: str
    scenario: str
    policy: str
    pickers_per_dc: int
    allocation: FulfillmentResult
    dc: List[DCPickResult]
    order_otif: np.ndarray
    alloc_ok: np.ndarray
    fully_filled: np.ndarray
    metrics: Dict[str, float]

    @property
    def otif_rate(self) -> float:
        return float(self.order_otif.mean()) if self.order_otif.size else 0.0


def allocation_order_status(
    instance: E2EInstance, allocation: FulfillmentResult
) -> Dict[str, np.ndarray]:
    """Per-order fully-filled and allocation-on-time flags, same rule as Week 5."""
    fulfillment = instance.fulfillment
    fulfilled = allocation.shipments.sum(axis=1)
    late_mask = fulfillment.transit_days > fulfillment.promise_days[None, :]
    late_units = (allocation.shipments * late_mask[:, fulfillment.line_order].T).sum(
        axis=1
    )
    order_demand = np.bincount(
        fulfillment.line_order, weights=fulfillment.line_qty, minlength=fulfillment.n_orders
    )
    order_fulfilled = np.bincount(
        fulfillment.line_order, weights=fulfilled, minlength=fulfillment.n_orders
    )
    order_late = np.bincount(
        fulfillment.line_order, weights=late_units, minlength=fulfillment.n_orders
    )
    fully = order_fulfilled == order_demand
    on_time = order_late == 0
    return {
        "demand": order_demand,
        "fulfilled": order_fulfilled,
        "late_units": order_late,
        "fully_filled": fully,
        "alloc_ok": fully & on_time,
    }


def pick_tickets(instance: E2EInstance, allocation: FulfillmentResult) -> List[DCTickets]:
    """Split the allocation into per-DC pick tickets (one per order-DC pair)."""
    fulfillment = instance.fulfillment
    shipments = np.asarray(allocation.shipments)
    if shipments.shape != (fulfillment.n_lines, fulfillment.n_dcs):
        raise ValueError("allocation.shipments 形状与实例不一致")
    groups: List[DCTickets] = []
    for dc in range(fulfillment.n_dcs):
        rows = []
        for line in range(fulfillment.n_lines):
            quantity = int(shipments[line, dc])
            if quantity <= 0:
                continue
            order = int(fulfillment.line_order[line])
            invoice = fulfillment.order_ids[order]
            rows.append(
                {
                    "invoice": f"{invoice}@{fulfillment.dc_names[dc]}",
                    "sku": fulfillment.sku_names[int(fulfillment.line_sku[line])],
                    "quantity": quantity,
                    "order": order,
                }
            )
        if not rows:
            continue
        frame = pd.DataFrame(rows)
        mapping = {
            str(row.invoice): int(row.order)
            for row in frame[["invoice", "order"]].drop_duplicates().itertuples()
        }
        groups.append(
            DCTickets(dc=fulfillment.dc_names[dc], frame=frame, order_index=mapping)
        )
    return groups


def _pick_plan_for(instance: E2EInstance, tickets: DCTickets):
    plan = PromisePlan(
        tier_of={ticket: instance.pick.tier_of[instance.order_ids[order]] for ticket, order in tickets.order_index.items()},
        cutoff_of={ticket: instance.pick.cutoff_of[instance.order_ids[order]] for ticket, order in tickets.order_index.items()},
        tier_counts={},
        cutoffs=dict(TIER_CUTOFFS),
        mix=dict(instance.pick.tier_onsite),
        seed=instance.pick.seed,
    )
    arrivals = ArrivalPlan(
        arrival_of={
            ticket: instance.pick.arrival_of[instance.order_ids[order]]
            for ticket, order in tickets.order_index.items()
        },
        tier_onsite=dict(instance.pick.tier_onsite),
        tier_windows=dict(instance.pick.tier_windows),
        onsite={},
        seed=instance.pick.seed,
    )
    return plan, arrivals


def _run_dc(
    instance: E2EInstance,
    tickets: DCTickets,
    policy: str,
    pickers: int,
    wait_minutes: float,
    min_fill: int,
    name: str,
    duration_noise: Optional[float],
    noise_seed: int,
    priority_orders: Optional[Sequence[int]] = None,
) -> tuple[DCPickResult, Dict[str, float]]:
    wave_instance = build_wave_instance(
        tickets.frame[["invoice", "sku", "quantity"]],
        instance.slots,
        instance.layout,
        max_orders=instance.max_orders,
        max_lines=instance.max_lines,
        meta={"dc": tickets.dc},
    )
    plan, arrivals = _pick_plan_for(instance, tickets)
    priority = {
        int(order) for order in ([] if priority_orders is None else priority_orders)
    }
    priority_tickets = {
        ticket
        for ticket, order in tickets.order_index.items()
        if int(order) in priority
    }
    schedule = simulate_online(
        wave_instance,
        plan,
        arrivals,
        policy=policy,
        picker_count=pickers,
        shift_minutes=instance.shift_minutes,
        wait_minutes=wait_minutes,
        min_fill=min_fill,
        duration_noise=duration_noise,
        noise_seed=noise_seed,
        name=f"{name} · {tickets.dc}",
        priority_invoices=priority_tickets or None,
    )

    end_of: Dict[str, float] = {}
    for job, end in zip(schedule.jobs, schedule.ends):
        for ticket in job.invoices:
            end_of[ticket] = float(end)
    on_time = tardy = 0
    tardiness = 0.0
    max_late = 0.0
    for ticket, end in end_of.items():
        late = max(0.0, end - plan.cutoff_of[ticket])
        if late <= EPS:
            on_time += 1
        else:
            tardy += 1
            tardiness += late
            max_late = max(max_late, late)

    metrics = dynamic_metrics(schedule, arrivals)
    result = DCPickResult(
        dc=tickets.dc,
        tickets=len(end_of),
        orders=len(tickets.order_index),
        waves=metrics["waves"],
        labor_minutes=metrics["labor_minutes"],
        labor_per_ticket=(
            metrics["labor_minutes"] / len(end_of) if end_of else 0.0
        ),
        makespan=metrics["makespan"],
        idle_minutes=metrics["idle_minutes"],
        on_time_tickets=on_time,
        tardy_tickets=tardy,
        tardiness_minutes=tardiness,
        max_tardiness=max_late,
        fill=metrics["avg_fill"],
        schedule=schedule,
    )
    return result, end_of


def run_pick_layer(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    scenario: str,
    policy: str = "edf",
    wait_minutes: float = DEFAULT_WAIT_MINUTES,
    min_fill: int = DEFAULT_MIN_FILL,
    pickers_per_dc: Optional[int] = None,
    duration_noise: Optional[float] = None,
    noise_seed: int = 0,
    name: Optional[str] = None,
    priority_orders: Optional[Sequence[int]] = None,
) -> E2EResult:
    """Run every DC's online release and score the end-to-end order outcome."""
    if policy not in POLICY_LABELS:
        raise ValueError(f"未知在线策略: {policy}")
    pickers = int(instance.pickers_per_dc if pickers_per_dc is None else pickers_per_dc)
    if pickers < 1:
        raise ValueError("每 DC 拣货员数量必须为正")
    if duration_noise is not None and duration_noise < 0:
        raise ValueError("拣选时长噪声标准差不能为负")
    label = name or f"{scenario} · {POLICY_LABELS[policy]}"

    status = allocation_order_status(instance, allocation)
    ticket_groups = pick_tickets(instance, allocation)
    dc_results: List[DCPickResult] = []
    order_pick_ok = np.ones(instance.n_orders, dtype=bool)
    for index, tickets in enumerate(ticket_groups):
        dc_result, end_of = _run_dc(
            instance,
            tickets,
            policy,
            pickers,
            wait_minutes,
            min_fill,
            label,
            duration_noise,
            noise_seed + 7919 * index,
            priority_orders=priority_orders,
        )
        dc_results.append(dc_result)
        for ticket, end in end_of.items():
            order = tickets.order_index[ticket]
            cutoff = instance.pick.cutoff_of[instance.order_ids[order]]
            if end > cutoff + EPS:
                order_pick_ok[order] = False

    order_otif = status["alloc_ok"] & order_pick_ok
    metrics = _e2e_metrics(
        instance, allocation, status, dc_results, order_otif, order_pick_ok, pickers
    )
    return E2EResult(
        name=label,
        scenario=scenario,
        policy=policy,
        pickers_per_dc=pickers,
        allocation=allocation,
        dc=dc_results,
        order_otif=order_otif,
        alloc_ok=status["alloc_ok"],
        fully_filled=status["fully_filled"],
        metrics=metrics,
    )


def _e2e_metrics(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    status: Mapping[str, np.ndarray],
    dc_results: List[DCPickResult],
    order_otif: np.ndarray,
    order_pick_ok: np.ndarray,
    pickers: int,
) -> Dict[str, float]:
    orders = instance.n_orders
    tickets = sum(row.tickets for row in dc_results)
    labor = sum(row.labor_minutes for row in dc_results)
    labor_cost = labor * LABOR_COST_PER_MINUTE
    on_time_tickets = sum(row.on_time_tickets for row in dc_results)
    tardy_tickets = sum(row.tardy_tickets for row in dc_results)
    tardiness = sum(row.tardiness_minutes for row in dc_results)
    makespan = max((row.makespan for row in dc_results), default=0.0)
    idle = sum(row.idle_minutes for row in dc_results)
    alloc_ok_orders = int(status["alloc_ok"].sum())
    otif_orders = int(order_otif.sum())
    pick_ok_orders = int(order_pick_ok.sum())
    return {
        "orders": orders,
        "tickets": tickets,
        "waves": sum(row.waves for row in dc_results),
        "dcs": len(dc_results),
        "unit_fill_rate": allocation.unit_fill_rate,
        "order_fill_rate": allocation.order_fill_rate,
        "alloc_otif_rate": allocation.otif_rate,
        "alloc_on_time_orders": alloc_ok_orders,
        "split_rate": allocation.split_rate,
        "shipments": allocation.shipments_count,
        "transport": allocation.transport_cost,
        "fixed": allocation.fixed_cost,
        "late": allocation.late_cost,
        "unmet": allocation.unmet_cost,
        "alloc_cost": allocation.total_cost,
        "pick_labor_minutes": labor,
        "labor_per_ticket": labor / tickets if tickets else 0.0,
        "pick_on_time_tickets": on_time_tickets,
        "pick_tardy_tickets": tardy_tickets,
        "pick_on_time_rate": on_time_tickets / tickets if tickets else 0.0,
        "pick_tardiness": tardiness,
        "pick_max_late": max((row.max_tardiness for row in dc_results), default=0.0),
        "pick_makespan": makespan,
        "pick_idle": idle,
        "pick_ok_orders": pick_ok_orders,
        "labor_cost": labor_cost,
        "total_cost": allocation.total_cost + labor_cost,
        "e2e_otif_orders": otif_orders,
        "e2e_otif_rate": otif_orders / orders if orders else 0.0,
        "pick_loss_orders": alloc_ok_orders - otif_orders,
        "pickers_per_dc": int(pickers),
    }


def e2e_summary(results: Mapping[str, E2EResult]) -> List[Dict[str, object]]:
    rows = []
    for key, result in results.items():
        rows.append(
            {
                "key": key,
                "scenario": result.name,
                "policy": result.policy,
                "pick_status": result.allocation.status,
                "pickers_per_dc": result.pickers_per_dc,
                **result.metrics,
            }
        )
    return rows


def e2e_dc_table(result: E2EResult) -> List[Dict[str, object]]:
    return [row.as_dict() for row in result.dc]


def run_release_sweep(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    scenario: str,
    policies: Mapping[str, Dict[str, object]],
) -> Dict[str, E2EResult]:
    """Re-run the pick layer under different release policies for one allocation."""
    results: Dict[str, E2EResult] = {}
    for key, params in policies.items():
        results[key] = run_pick_layer(
            instance,
            allocation,
            scenario=scenario,
            policy=str(params.get("policy", "edf")),
            wait_minutes=float(params.get("wait_minutes", DEFAULT_WAIT_MINUTES)),
            min_fill=int(params.get("min_fill", DEFAULT_MIN_FILL)),
            pickers_per_dc=params.get("pickers_per_dc"),  # type: ignore[arg-type]
            duration_noise=params.get("duration_noise"),  # type: ignore[arg-type]
            noise_seed=int(params.get("noise_seed", 0)),
        )
    return results
