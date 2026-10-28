"""Week-12 mid-shift write-back: reroute at-risk pick tickets across DCs.

Weeks 9-11 treat the allocation as frozen: the pick layer only reports whether
the plan was executable. This module closes the loop. At a declared review
minute it reads the state of every DC's shift, projects which future pick
tickets will finish after their cutoff, and reroutes a ticket to another DC
when that DC has promise-feasible transit, weekly capacity and a shorter
projected queue. The remaining shift is then replayed from the review state.

The recovery is deliberately local:

* only tickets whose wave has not started are movable; in-progress waves stay
  with their DC;
* a moved ticket carries its stock to the target DC on an internal transfer, so
  the target starts picking after ``review + transfer_lead`` and does not need
  spare SKU stock of its own;
* the ticket keeps its original cut-off and the order must remain inside its
  promise from the new DC;
* the decision uses a deterministic projection of the remaining queue, not
  foresight of future pick-time noise. The ``oracle`` policy differs only in
  knowing which tickets will actually be late.

The move still needs target-DC weekly capacity and promise-feasible transit;
the ticket's own units travel from the source, so tight stock coverage does
not by itself block a reroute.

All parameters are declared assumptions: the review minute, transfer lead and
fee, the projection rule, and the pick-time model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from supply.fulfillment import FulfillmentResult
from supply.wave import (
    ArrivalPlan,
    PromisePlan,
    Schedule,
    WaveJob,
    build_wave_instance,
    simulate_online,
    unique_slots,
)
from supply.wave.instances import LABOR_COST_PER_MINUTE
from supply.network.warehouse import route_return

from .instances import E2EInstance, EPS, TIER_CUTOFFS, rebuild_arrivals
from .pipeline import (
    DCTickets,
    E2EResult,
    allocation_order_status,
    pick_tickets,
    run_pick_layer,
)
from .robustness import StressCell

DEFAULT_REVIEW_MINUTE = 120.0
DEFAULT_TRANSFER_LEAD = 30.0
DEFAULT_TRANSFER_FEE = 10.0
DEFAULT_MIN_GAIN = 5.0
DEFAULT_PHASE2_OFFSET = 500_003

POLICY_LABELS = {
    "none": "无回写（分单冻结）",
    "reroute": "迟到票据跨 DC 调动",
    "balance": "全队列跨 DC 再平衡",
    "oracle": "先知迟到集合（上界参考）",
}
DEFAULT_POLICIES: Tuple[str, ...] = ("none", "reroute", "balance", "oracle")


@dataclass(frozen=True)
class RecoveryConfig:
    review_minute: float = DEFAULT_REVIEW_MINUTE
    transfer_lead: float = DEFAULT_TRANSFER_LEAD
    transfer_fee: float = DEFAULT_TRANSFER_FEE
    min_gain: float = DEFAULT_MIN_GAIN
    max_moves: Optional[int] = None

    def __post_init__(self) -> None:
        if self.review_minute <= 0:
            raise ValueError("审核时点必须为正")
        if self.transfer_lead < 0:
            raise ValueError("跨 DC 调拨前置时间不能为负")
        if self.transfer_fee < 0:
            raise ValueError("调拨费用不能为负")
        if self.min_gain < 0:
            raise ValueError("最小改善阈值不能为负")
        if self.max_moves is not None and self.max_moves < 0:
            raise ValueError("最大调拨票数不能为负")


@dataclass(frozen=True)
class Move:
    ticket: str
    order: int
    from_dc: str
    to_dc: str
    units: int
    lines: int
    cutoff: int
    source_end: float
    estimated_end: float
    estimated_gain: float
    reason: str

    def as_dict(self) -> Dict[str, object]:
        return {
            "ticket": self.ticket,
            "order": self.order,
            "from_dc": self.from_dc,
            "to_dc": self.to_dc,
            "units": self.units,
            "lines": self.lines,
            "cutoff": self.cutoff,
            "source_end": self.source_end,
            "estimated_end": self.estimated_end,
            "estimated_gain": self.estimated_gain,
            "reason": self.reason,
        }


@dataclass
class RecoveryResult:
    policy: str
    config: RecoveryConfig
    moves: List[Move]
    order_otif: np.ndarray
    metrics: Dict[str, float]
    dc: List[Dict[str, object]]
    ticket_end: Dict[str, float]
    ticket_dc: Dict[str, str]

    @property
    def otif_rate(self) -> float:
        return float(self.order_otif.mean()) if self.order_otif.size else 0.0


@dataclass
class _DCState:
    name: str
    index: int
    tickets: DCTickets
    schedule: Schedule
    locked_jobs: List[WaveJob]
    locked_starts: List[float]
    locked_ends: List[float]
    locked_pickers: List[int]
    pending: List[str]
    picker_free: List[float]


def _split_phase_one(
    instance: E2EInstance,
    groups: Sequence[DCTickets],
    phase_one: E2EResult,
    review: float,
    pickers: int,
) -> Dict[str, _DCState]:
    by_name = {row.dc: row for row in phase_one.dc}
    order = {name: index for index, name in enumerate(instance.fulfillment.dc_names)}
    states: Dict[str, _DCState] = {}
    for group in groups:
        row = by_name.get(group.dc)
        if row is None:
            continue
        schedule = row.schedule
        locked = [
            index
            for index, start in enumerate(schedule.starts)
            if start <= review + EPS
        ]
        pending = [
            invoice
            for index, job in enumerate(schedule.jobs)
            if schedule.starts[index] > review + EPS
            for invoice in job.invoices
        ]
        free = [float(review)] * pickers
        for index in locked:
            picker = int(schedule.pickers[index])
            free[picker] = max(free[picker], float(schedule.ends[index]))
        states[group.dc] = _DCState(
            name=group.dc,
            index=order[group.dc],
            tickets=group,
            schedule=schedule,
            locked_jobs=[schedule.jobs[index] for index in locked],
            locked_starts=[float(schedule.starts[index]) for index in locked],
            locked_ends=[float(schedule.ends[index]) for index in locked],
            locked_pickers=[int(schedule.pickers[index]) for index in locked],
            pending=sorted(pending),
            picker_free=free,
        )
    for name in instance.fulfillment.dc_names:
        if name in states:
            continue
        empty = pd.DataFrame(columns=["invoice", "sku", "quantity", "order"])
        states[name] = _DCState(
            name=name,
            index=order[name],
            tickets=DCTickets(dc=name, frame=empty, order_index={}),
            schedule=Schedule(
                name=name,
                status="ONLINE",
                jobs=[],
                starts=[],
                ends=[],
                pickers=[],
                picker_count=pickers,
                shift_minutes=float(instance.shift_minutes),
                labor_cost_per_minute=LABOR_COST_PER_MINUTE,
            ),
            locked_jobs=[],
            locked_starts=[],
            locked_ends=[],
            locked_pickers=[],
            pending=[],
            picker_free=[float(review)] * pickers,
        )
    return states


def _subset_plans(
    instance: E2EInstance, ticket_orders: Mapping[str, int]
) -> Tuple[PromisePlan, ArrivalPlan]:
    if not ticket_orders:
        raise ValueError("子集票据不能为空")
    tier_of = {
        ticket: instance.pick.tier_of[instance.order_ids[order]]
        for ticket, order in ticket_orders.items()
    }
    cutoff_of = {
        ticket: instance.pick.cutoff_of[instance.order_ids[order]]
        for ticket, order in ticket_orders.items()
    }
    plan = PromisePlan(
        tier_of=tier_of,
        cutoff_of=cutoff_of,
        tier_counts={},
        cutoffs=dict(TIER_CUTOFFS),
        mix=dict(instance.pick.tier_onsite),
        seed=instance.pick.seed,
    )
    arrivals = ArrivalPlan(
        arrival_of={
            ticket: instance.pick.arrival_of[instance.order_ids[order]]
            for ticket, order in ticket_orders.items()
        },
        tier_onsite=dict(instance.pick.tier_onsite),
        tier_windows=dict(instance.pick.tier_windows),
        onsite={},
        seed=instance.pick.seed,
    )
    return plan, arrivals


def _wave_instance(instance: E2EInstance, frame: pd.DataFrame, dc: str):
    if frame.empty:
        raise ValueError("空票据集不能构建波次实例")
    return build_wave_instance(
        frame[["invoice", "sku", "quantity"]],
        instance.slots,
        instance.layout,
        max_orders=instance.max_orders,
        max_lines=instance.max_lines,
        meta={"dc": dc},
    )


def _project(
    instance: E2EInstance,
    state: _DCState,
    ticket_orders: Mapping[str, int],
    review: float,
    pickers: int,
) -> Optional[Schedule]:
    if not state.pending:
        return None
    frame = state.tickets.frame[
        state.tickets.frame["invoice"].isin(state.pending)
    ]
    plan, arrivals = _subset_plans(instance, ticket_orders)
    return simulate_online(
        _wave_instance(instance, frame, state.name),
        plan,
        arrivals,
        policy="edf",
        picker_count=pickers,
        shift_minutes=instance.shift_minutes,
        start_time=review,
        picker_free=state.picker_free,
        name=f"{state.name} · 审核投影",
    )


def _schedule_ends(schedule: Optional[Schedule]) -> Dict[str, float]:
    if schedule is None:
        return {}
    ends: Dict[str, float] = {}
    for job, end in zip(schedule.jobs, schedule.ends):
        for invoice in job.invoices:
            ends[invoice] = float(end)
    return ends


def _work_by_window(
    schedule: Optional[Schedule], windows: Sequence[int]
) -> Dict[int, float]:
    work = {int(window): 0.0 for window in sorted(set(int(value) for value in windows))}
    if schedule is None:
        return work
    for job in schedule.jobs:
        deadline = float(min(job.cutoff_of.values()))
        for window in work:
            if deadline <= window + EPS:
                work[window] += float(job.minutes)
    return work


def _ticket_minutes(
    states: Mapping[str, _DCState], instance: E2EInstance
) -> Dict[Tuple[str, str], float]:
    """Single-ticket wave minutes at every DC, using one shared candidate pool."""
    frames = [
        state.tickets.frame[state.tickets.frame["invoice"].isin(state.pending)]
        for state in states.values()
        if state.pending
    ]
    if not frames:
        return {}
    pool = pd.concat(frames, ignore_index=True)
    tickets = sorted(pool["invoice"].unique())
    minutes: Dict[Tuple[str, str], float] = {}
    for state in states.values():
        instance_at_dc = _wave_instance(instance, pool, state.name)
        lookup = instance_at_dc.by_id()
        for ticket in tickets:
            order = lookup[ticket]
            travel = float(route_return(instance_at_dc.layout, unique_slots([order])))
            minutes[(ticket, state.name)] = (
                travel / instance_at_dc.travel_meters_per_minute
                + order.lines * instance_at_dc.pick_minutes_per_line
                + order.units * instance_at_dc.pick_minutes_per_unit
                + instance_at_dc.setup_minutes_per_wave
            )
    return minutes


def _estimate_end(
    *,
    instance: E2EInstance,
    state: _DCState,
    order: int,
    review: float,
    transfer_lead: float,
    pickers: int,
    work: Mapping[int, float],
    minutes: float,
) -> Optional[float]:
    cutoff = float(
        instance.pick.cutoff_of[instance.order_ids[order]]
    )
    arrival = max(
        float(instance.pick.arrival_of[instance.order_ids[order]]),
        float(review) + float(transfer_lead),
    )
    if arrival > cutoff + EPS:
        return None
    free = max(float(review), min(state.picker_free))
    start = max(free, arrival)
    capacity = sum(max(0.0, cutoff - value) for value in state.picker_free)
    load = float(work[cutoff]) + minutes
    if capacity <= EPS or load > capacity + EPS:
        return None
    return float(start + load / max(1, pickers))


def _apply_move(
    *,
    ticket: str,
    source: _DCState,
    target: _DCState,
    order: int,
    units: int,
    lines: int,
    cutoff: int,
    source_end: float,
    estimated_end: float,
    reason: str,
) -> Move:
    return Move(
        ticket=ticket,
        order=order,
        from_dc=source.name,
        to_dc=target.name,
        units=int(units),
        lines=int(lines),
        cutoff=int(cutoff),
        source_end=float(source_end),
        estimated_end=float(estimated_end),
        estimated_gain=float(source_end - estimated_end),
        reason=reason,
    )


def _plan_moves(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    states: Mapping[str, _DCState],
    phase_one_ends: Mapping[str, float],
    config: RecoveryConfig,
    policy: str,
    pickers: int,
) -> List[Move]:
    """Greedy reroute against a deterministic projection of each DC's queue."""
    if policy not in {"reroute", "balance", "oracle"}:
        raise ValueError(f"未知回写策略: {policy}")
    if not any(state.pending for state in states.values()):
        return []

    projected: Dict[str, Optional[Schedule]] = {}
    for name, state in states.items():
        projected[name] = _project(
            instance,
            state,
            {
                ticket: state.tickets.order_index[ticket]
                for ticket in state.pending
            },
            config.review_minute,
            pickers,
        )
    projection_ends: Dict[str, float] = {}
    for schedule in projected.values():
        projection_ends.update(_schedule_ends(schedule))
    work = {
        name: _work_by_window(
            schedule, sorted(set(int(value) for value in instance.pick.cutoff_of.values()))
        )
        for name, schedule in projected.items()
    }
    minutes = _ticket_minutes(states, instance)

    rows_of: Dict[str, pd.DataFrame] = {}
    for state in states.values():
        for ticket, group in state.tickets.frame.groupby("invoice", sort=False):
            rows_of[str(ticket)] = group
    source_of = {
        ticket: name for name, state in states.items() for ticket in state.pending
    }
    order_of = {
        ticket: state.tickets.order_index[ticket]
        for state in states.values()
        for ticket in state.pending
    }
    ticket_units = {
        ticket: int(rows_of[ticket]["quantity"].sum()) for ticket in source_of
    }
    ticket_lines = {
        ticket: int(rows_of[ticket]["sku"].nunique()) for ticket in source_of
    }

    if policy == "oracle":
        ends_now = {ticket: float(phase_one_ends[ticket]) for ticket in source_of}
    else:
        ends_now = {ticket: float(projection_ends[ticket]) for ticket in source_of}

    load_units = np.asarray(allocation.dc_units, dtype=np.int64).copy()
    moves: List[Move] = []
    assigned = dict(source_of)

    if policy == "balance":
        candidates = sorted(
            source_of,
            key=lambda ticket: (-ends_now[ticket], ticket),
        )
    else:
        candidates = sorted(
            (
                ticket
                for ticket in source_of
                if ends_now[ticket]
                > float(instance.pick.cutoff_of[instance.order_ids[order_of[ticket]]])
                + EPS
            ),
            key=lambda ticket: (
                float(instance.pick.cutoff_of[instance.order_ids[order_of[ticket]]]),
                -ends_now[ticket],
                ticket,
            ),
        )

    for ticket in candidates:
        if config.max_moves is not None and len(moves) >= config.max_moves:
            break
        source_name = assigned[ticket]
        source = states[source_name]
        order = order_of[ticket]
        cutoff = int(instance.pick.cutoff_of[instance.order_ids[order]])
        source_end = ends_now[ticket]
        best: Optional[Tuple[float, str]] = None
        for target_name, target in states.items():
            if target_name == source_name:
                continue
            if (
                int(instance.fulfillment.transit_days[target.index, order])
                > int(instance.fulfillment.promise_days[order])
            ):
                continue
            if (
                int(load_units[target.index]) + ticket_units[ticket]
                > int(instance.fulfillment.dc_capacity[target.index])
            ):
                continue
            estimate = _estimate_end(
                instance=instance,
                state=target,
                order=order,
                review=config.review_minute,
                transfer_lead=config.transfer_lead,
                pickers=pickers,
                work=work[target_name],
                minutes=minutes[(ticket, target_name)],
            )
            if estimate is None:
                continue
            if policy in {"reroute", "oracle"} and estimate > cutoff - EPS:
                continue
            if estimate >= source_end - config.min_gain - EPS:
                continue
            if best is None or estimate < best[0] - EPS:
                best = (estimate, target_name)
        if best is None:
            continue

        estimate, target_name = best
        target = states[target_name]
        source_minutes = minutes[(ticket, source_name)]
        target_minutes = minutes[(ticket, target_name)]
        for window in work[source_name]:
            if cutoff <= window + EPS:
                work[source_name][window] = max(
                    0.0, work[source_name][window] - source_minutes
                )
        for window in work[target_name]:
            if cutoff <= window + EPS:
                work[target_name][window] += target_minutes
        load_units[source.index] -= ticket_units[ticket]
        load_units[target.index] += ticket_units[ticket]
        moves.append(
            _apply_move(
                ticket=ticket,
                source=source,
                target=target,
                order=order,
                units=ticket_units[ticket],
                lines=ticket_lines[ticket],
                cutoff=cutoff,
                source_end=source_end,
                estimated_end=estimate,
                reason="late" if policy in {"reroute", "oracle"} else "balance",
            )
        )
        assigned[ticket] = target_name
    return moves


def _combined_schedule(
    name: str,
    locked: _DCState,
    resumed: Optional[Schedule],
    pickers: int,
    shift_minutes: float,
    labor_cost_per_minute: float,
    review: float,
) -> Optional[Schedule]:
    jobs: List[WaveJob] = []
    starts: List[float] = []
    ends: List[float] = []
    picker_ids: List[int] = []
    for job, start, end, picker in zip(
        locked.locked_jobs,
        locked.locked_starts,
        locked.locked_ends,
        locked.locked_pickers,
    ):
        jobs.append(replace(job, index=len(jobs)))
        starts.append(float(start))
        ends.append(float(end))
        picker_ids.append(int(picker))
    if resumed is not None:
        for job, start, end, picker in zip(
            resumed.jobs, resumed.starts, resumed.ends, resumed.pickers
        ):
            jobs.append(replace(job, index=len(jobs)))
            starts.append(float(start))
            ends.append(float(end))
            picker_ids.append(int(picker))
    if not jobs:
        return None
    return Schedule(
        name=name,
        status="ONLINE",
        jobs=jobs,
        starts=starts,
        ends=ends,
        pickers=picker_ids,
        picker_count=int(pickers),
        shift_minutes=float(shift_minutes),
        labor_cost_per_minute=float(labor_cost_per_minute),
        meta={"review_minute": float(review)},
    )


def _resume_dc(
    instance: E2EInstance,
    state: _DCState,
    pending: Sequence[str],
    orders: Mapping[str, int],
    rows_of: Mapping[str, pd.DataFrame],
    config: RecoveryConfig,
    pickers: int,
    duration_noise: Optional[float],
    noise_seed: int,
) -> Optional[Schedule]:
    if not pending:
        return None
    frame = pd.concat(
        [rows_of[ticket] for ticket in sorted(pending)], ignore_index=True
    )
    plan, arrivals = _subset_plans(instance, orders)
    return simulate_online(
        _wave_instance(instance, frame, state.name),
        plan,
        arrivals,
        policy="edf",
        picker_count=pickers,
        shift_minutes=instance.shift_minutes,
        start_time=config.review_minute,
        picker_free=state.picker_free,
        duration_noise=duration_noise,
        noise_seed=int(noise_seed),
        name=f"{state.name} · 回写后",
    )


def apply_recovery(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    groups: Sequence[DCTickets],
    phase_one: E2EResult,
    policy: str,
    config: RecoveryConfig = RecoveryConfig(),
    pickers: Optional[int] = None,
    duration_noise: Optional[float] = None,
    noise_seed: int = 0,
) -> RecoveryResult:
    """Execute one recovery policy and score the resulting end-to-end OTIF."""
    if policy not in POLICY_LABELS:
        raise ValueError(f"未知回写策略: {policy}")
    if config.review_minute >= instance.shift_minutes:
        raise ValueError("审核时点必须早于班次结束")
    if duration_noise is not None and duration_noise < 0:
        raise ValueError("拣选时长噪声标准差不能为负")
    pickers = int(instance.pickers_per_dc if pickers is None else pickers)
    if pickers < 1:
        raise ValueError("每 DC 拣货员数量必须为正")

    states = _split_phase_one(
        instance, groups, phase_one, config.review_minute, pickers
    )
    rows_of: Dict[str, pd.DataFrame] = {}
    ticket_order: Dict[str, int] = {}
    for group in groups:
        for ticket, block in group.frame.groupby("invoice", sort=False):
            key = str(ticket)
            rows_of[key] = block
            ticket_order[key] = int(group.order_index[key])
    phase_one_ends: Dict[str, float] = {}
    for state in states.values():
        for job, end in zip(state.schedule.jobs, state.schedule.ends):
            for ticket in job.invoices:
                phase_one_ends[ticket] = float(end)

    moves = (
        _plan_moves(
            instance,
            allocation,
            states,
            phase_one_ends,
            config,
            policy,
            pickers,
        )
        if policy != "none"
        else []
    )
    assigned = {
        ticket: name for name, state in states.items() for ticket in state.pending
    }
    for move in moves:
        assigned[move.ticket] = move.to_dc
    pending_by_dc: Dict[str, List[str]] = {name: [] for name in states}
    for ticket, name in assigned.items():
        pending_by_dc[name].append(ticket)
    orders_by_dc: Dict[str, Dict[str, int]] = {name: {} for name in states}
    for name in states:
        for ticket in pending_by_dc[name]:
            orders_by_dc[name][ticket] = ticket_order[ticket]

    ticket_end: Dict[str, float] = {}
    ticket_dc: Dict[str, str] = {}
    dc_rows: List[Dict[str, object]] = []
    total_labor = 0.0
    total_waves = 0
    all_ends: List[float] = []
    moved_out = {name: 0 for name in states}
    moved_in = {name: 0 for name in states}
    for move in moves:
        moved_out[move.from_dc] += 1
        moved_in[move.to_dc] += 1

    for index, (name, state) in enumerate(states.items()):
        resumed = _resume_dc(
            instance,
            state,
            pending_by_dc[name],
            orders_by_dc[name],
            rows_of,
            config,
            pickers,
            duration_noise,
            noise_seed + 7919 * index,
        )
        combined = _combined_schedule(
            f"{name} · {POLICY_LABELS[policy]}",
            state,
            resumed,
            pickers,
            instance.shift_minutes,
            state.schedule.labor_cost_per_minute,
            config.review_minute,
        )
        if combined is None:
            continue
        total_labor += sum(job.minutes for job in combined.jobs)
        total_waves += len(combined.jobs)
        all_ends.extend(combined.ends)
        on_time = tardy = 0
        tardiness = 0.0
        for job, end in zip(combined.jobs, combined.ends):
            for ticket in job.invoices:
                order = ticket_order[ticket]
                cutoff = float(instance.pick.cutoff_of[instance.order_ids[order]])
                ticket_end[ticket] = float(end)
                ticket_dc[ticket] = assigned.get(ticket, name)
                late = max(0.0, float(end) - cutoff)
                if late <= EPS:
                    on_time += 1
                else:
                    tardy += 1
                    tardiness += late
        dc_rows.append(
            {
                "dc": name,
                "tickets": sum(job.orders for job in combined.jobs),
                "waves": len(combined.jobs),
                "labor_minutes": sum(job.minutes for job in combined.jobs),
                "on_time_tickets": on_time,
                "tardy_tickets": tardy,
                "tardiness_minutes": tardiness,
                "makespan": max(combined.ends),
                "moved_in": moved_in[name],
                "moved_out": moved_out[name],
            }
        )

    missing = set(ticket_order) - set(ticket_end)
    if missing:
        raise RuntimeError(f"{len(missing)} 张票据未进入回写后的排程，例如 {sorted(missing)[:3]}")

    status = allocation_order_status(instance, allocation)
    order_pick_ok = np.ones(instance.n_orders, dtype=bool)
    for ticket, end in ticket_end.items():
        order = ticket_order[ticket]
        cutoff = instance.pick.cutoff_of[instance.order_ids[order]]
        if end > float(cutoff) + EPS:
            order_pick_ok[order] = False
    order_otif = status["alloc_ok"] & order_pick_ok

    tickets = sum(row["tickets"] for row in dc_rows)
    on_time_tickets = sum(row["on_time_tickets"] for row in dc_rows)
    tardy_tickets = sum(row["tardy_tickets"] for row in dc_rows)
    tardiness = sum(row["tardiness_minutes"] for row in dc_rows)
    makespan = max(all_ends) if all_ends else 0.0
    fee = len(moves) * config.transfer_fee
    dc_index = {
        name: index for index, name in enumerate(instance.fulfillment.dc_names)
    }
    transport_delta = 0.0
    for move in moves:
        transport_delta += move.units * (
            float(instance.fulfillment.ship_cost[dc_index[move.to_dc], move.order])
            - float(instance.fulfillment.ship_cost[dc_index[move.from_dc], move.order])
        )
    metrics = {
        "e2e_otif_rate": float(order_otif.mean()) if order_otif.size else 0.0,
        "pick_on_time_rate": on_time_tickets / tickets if tickets else 0.0,
        "pick_on_time_tickets": on_time_tickets,
        "pick_tardy_tickets": tardy_tickets,
        "pick_tardiness": tardiness,
        "pick_makespan": makespan,
        "pick_waves": total_waves,
        "pick_labor_minutes": total_labor,
        "labor_per_ticket": total_labor / tickets if tickets else 0.0,
        "tickets": tickets,
        "moved_tickets": len(moves),
        "moved_units": sum(move.units for move in moves),
        "transfer_fee": fee,
        "transport_delta": transport_delta,
        "recovery_cost": fee + transport_delta,
        "review_minute": config.review_minute,
    }
    return RecoveryResult(
        policy=policy,
        config=config,
        moves=moves,
        order_otif=order_otif,
        metrics=metrics,
        dc=dc_rows,
        ticket_end=ticket_end,
        ticket_dc=ticket_dc,
    )


def replay_recovery(
    instance: E2EInstance,
    allocation: FulfillmentResult,
    scenario: str,
    cell: StressCell,
    seeds: Sequence[int],
    policies: Sequence[str] = DEFAULT_POLICIES,
    config: RecoveryConfig = RecoveryConfig(),
    review_sweep: Sequence[float] = (),
) -> Dict[str, pd.DataFrame]:
    """Replay the chain for every seed, policy and optional review minute."""
    if not seeds:
        raise ValueError("随机种子列表不能为空")
    unknown = sorted(set(policies) - set(POLICY_LABELS))
    if unknown:
        raise ValueError(f"未知回写策略: {unknown}")
    pickers = int(cell.pickers_per_dc or instance.pickers_per_dc)
    rows: List[Dict[str, object]] = []
    move_rows: List[Dict[str, object]] = []
    dc_rows: List[Dict[str, object]] = []
    review_rows: List[Dict[str, object]] = []
    for seed in seeds:
        shifted = rebuild_arrivals(instance, int(seed), cell.profile)
        groups = pick_tickets(shifted, allocation)
        phase_one = run_pick_layer(
            shifted,
            allocation,
            scenario=scenario,
            policy=cell.policy,
            wait_minutes=cell.wait_minutes,
            min_fill=cell.min_fill,
            pickers_per_dc=pickers,
            duration_noise=cell.duration_noise or None,
            noise_seed=int(seed),
        )
        base = apply_recovery(
            shifted,
            allocation,
            groups,
            phase_one,
            "none",
            config,
            pickers,
            cell.duration_noise or None,
            int(seed) + DEFAULT_PHASE2_OFFSET,
        )
        for policy in policies:
            result = (
                base
                if policy == "none"
                else apply_recovery(
                    shifted,
                    allocation,
                    groups,
                    phase_one,
                    policy,
                    config,
                    pickers,
                    cell.duration_noise or None,
                    int(seed) + DEFAULT_PHASE2_OFFSET,
                )
            )
            rescued = int((result.order_otif & ~base.order_otif).sum())
            lost = int((~result.order_otif & base.order_otif).sum())
            rows.append(
                {
                    "scenario": scenario,
                    "cell": cell.key,
                    "cell_label": cell.label,
                    "policy": policy,
                    "policy_label": POLICY_LABELS[policy],
                    "duration_noise": float(cell.duration_noise),
                    "seed": int(seed),
                    "rescued_orders": rescued,
                    "lost_orders": lost,
                    "net_orders": rescued - lost,
                    **result.metrics,
                }
            )
            for move in result.moves:
                move_rows.append(
                    {
                        "scenario": scenario,
                        "cell": cell.key,
                        "policy": policy,
                        "seed": int(seed),
                        **move.as_dict(),
                    }
                )
            for row in result.dc:
                dc_rows.append(
                    {
                        "scenario": scenario,
                        "cell": cell.key,
                        "policy": policy,
                        "seed": int(seed),
                        **row,
                    }
                )
        for review in review_sweep:
            if math.isclose(float(review), config.review_minute):
                continue
            swept = apply_recovery(
                shifted,
                allocation,
                groups,
                phase_one,
                "reroute",
                replace(config, review_minute=float(review)),
                pickers,
                cell.duration_noise or None,
                int(seed) + DEFAULT_PHASE2_OFFSET,
            )
            review_rows.append(
                {
                    "scenario": scenario,
                    "cell": cell.key,
                    "cell_label": cell.label,
                    "policy": "reroute",
                    "seed": int(seed),
                    "review_minute": float(review),
                    "rescued_orders": int(
                        (swept.order_otif & ~base.order_otif).sum()
                    ),
                    "lost_orders": int(
                        (~swept.order_otif & base.order_otif).sum()
                    ),
                    **swept.metrics,
                }
            )
    return {
        "runs": pd.DataFrame(rows),
        "moves": pd.DataFrame(move_rows),
        "dc": pd.DataFrame(dc_rows),
        "review_sweep": pd.DataFrame(review_rows),
        "control": pd.DataFrame(
            [row for row in rows if row["policy"] == "none"]
        ),
    }


def recovery_summary(
    runs: pd.DataFrame,
    metrics: Sequence[str] = (
        "e2e_otif_rate",
        "pick_on_time_rate",
        "pick_tardiness",
        "pick_makespan",
        "moved_tickets",
        "recovery_cost",
        "rescued_orders",
        "lost_orders",
    ),
) -> pd.DataFrame:
    """Distribution summary per policy x cell."""
    missing = sorted(set(metrics) - set(runs.columns))
    if missing:
        raise ValueError(f"缺少指标列: {missing}")
    keys = [key for key in ("scenario", "cell", "policy") if key in runs.columns]
    rows: List[Dict[str, object]] = []
    for values, block in runs.groupby(keys, sort=False):
        values = values if isinstance(values, tuple) else (values,)
        identity = dict(zip(keys, values))
        for metric in metrics:
            values_array = block[metric].astype(float).to_numpy()
            values_array = values_array[~np.isnan(values_array)]
            if values_array.size == 0:
                continue
            mean = float(values_array.mean())
            sd = (
                float(values_array.std(ddof=1))
                if values_array.size > 1
                else 0.0
            )
            ci95 = (
                1.96 * sd / math.sqrt(values_array.size)
                if values_array.size > 1
                else 0.0
            )
            down = metric in {"e2e_otif_rate", "pick_on_time_rate"}
            tail_count = max(1, int(math.ceil(0.10 * values_array.size)))
            ordered = np.sort(values_array)
            tail = ordered[:tail_count] if down else ordered[-tail_count:]
            rows.append(
                {
                    **identity,
                    "policy_label": str(block["policy_label"].iloc[0]),
                    "cell_label": str(block["cell_label"].iloc[0]),
                    "metric": metric,
                    "n": int(values_array.size),
                    "mean": mean,
                    "sd": sd,
                    "ci95": ci95,
                    "p10": float(np.percentile(values_array, 10)),
                    "p50": float(np.percentile(values_array, 50)),
                    "p90": float(np.percentile(values_array, 90)),
                    "tail10": float(tail.mean()),
                    "direction": "down" if down else "up",
                }
            )
    return pd.DataFrame(rows)
